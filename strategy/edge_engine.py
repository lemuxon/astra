# =========================================================
# ASTRA v30.0 — EDGE ENGINE (Strateji Filtresi)
# Gerçek market edge: sinyalin işlem değeri var mı?
#
# Sorun: AI skoru yüksek ama piyasa gerçekten uygun mu?
# Çözüm: Çok katmanlı filtre — her katman ayrı "veto" kullanır.
#
# Katmanlar:
#   1. Regime Uyumu      — strateji rejime uygun mu?
#   2. Signal Quality    — sinyal güçlü mü?
#   3. Market Microstructure — gerçek edge var mı?
#   4. Risk-Adjusted Score — beklenen R/R yeterli mi?
#   5. Adaptive Threshold — rejime göre dinamik eşik
# =========================================================
import logging
from dataclasses import dataclass, field
from typing import Optional
import sys; sys.path.append("..")
from config import (MIN_CONFIDENCE, MIN_AI_SCORE_BUY, MIN_AI_SCORE_SELL,
                    REGIME_TREND_MIN_AI, REGIME_RANGE_MIN_AI,
                    REGIME_BEAR_MIN_AI, REGIME_VOLATILE_MIN_AI)

log = logging.getLogger("ASTRA.EDGE")

REJIM_STRATEJI_MAP = {
    "TREND_UP":   ["TREND_FOLLOW"],
    "TREND_DOWN": ["TREND_FOLLOW"],
    "RANGE":      ["MEAN_REVERSION", "GRID"],
    "VOLATILE":   ["MEAN_REVERSION"],
    "BEAR":       ["TREND_FOLLOW"],  # short trend follow
}


@dataclass
class EdgeSonuc:
    gecti:        bool
    edge_score:   float   # 0–100 arası edge kalitesi
    confidence:   int
    strateji:     str
    sebep:        str
    detay:        dict = field(default_factory=dict)

    def __str__(self):
        d = "✅" if self.gecti else "❌"
        return f"{d} edge={self.edge_score:.1f} conf=%{self.confidence} {self.strateji} ({self.sebep})"


class EdgeEngine:
    """
    Çok katmanlı sinyal kalite filtresi.
    Her katman bağımsız — biri veto ederse sinyal geçmez.
    """

    def filtrele(self, ai_score: int, rejim: str,
                  mtf_skor: int, market_data: dict,
                  yukselis_guveni: float, son_atr: float,
                  son_close: float, strateji: str = None) -> dict:
        """
        Sinyali tüm katmanlardan geçirir.
        Döner: EdgeSonuc.__dict__
        """
        yon = "LONG" if ai_score > 0 else "SHORT"
        detay = {}

        # ── 1. Minimum AI Skoru (Rejime Göre Adaptif) ────
        ai_esik = self._ai_esik_hesapla(rejim, yon)
        ai_gecer = (yon == "LONG" and ai_score >= ai_esik) or \
                   (yon == "SHORT" and ai_score <= -ai_esik)

        detay["ai_esik"] = ai_esik; detay["ai_gecer"] = ai_gecer
        if not ai_gecer:
            return EdgeSonuc(False, 0, 0, strateji or "?",
                              f"AI skor {ai_score} < eşik {ai_esik} ({rejim})",
                              detay).__dict__

        # ── 2. Strateji–Rejim Uyumu ───────────────────────
        uygun_stratejiler = REJIM_STRATEJI_MAP.get(rejim, ["TREND_FOLLOW"])
        secilen_strateji  = strateji or uygun_stratejiler[0]
        if strateji and strateji not in uygun_stratejiler:
            log.debug(f"[EDGE] Strateji–rejim uyumsuz: {strateji} / {rejim}")
            secilen_strateji = uygun_stratejiler[0]
        detay["strateji"] = secilen_strateji

        # ── 3. MTF Confluence ─────────────────────────────
        mtf_esik   = 2 if rejim in ("TREND_UP","TREND_DOWN") else 3
        mtf_gecer  = abs(mtf_skor) >= mtf_esik
        detay["mtf_skor"]  = mtf_skor
        detay["mtf_esik"]  = mtf_esik
        detay["mtf_gecer"] = mtf_gecer

        if not mtf_gecer and rejim != "VOLATILE":
            return EdgeSonuc(False, 0, 0, secilen_strateji,
                              f"MTF skor {mtf_skor} < eşik {mtf_esik}",
                              detay).__dict__

        # ── 4. Market Microstructure ──────────────────────
        ms_skor      = market_data.get("market_sentiment", 0)
        funding      = market_data.get("funding_rate", 0)
        ls_ratio     = market_data.get("ls_ratio", 1.0)
        fear_greed   = market_data.get("fear_greed", 50)
        oi_degisim   = market_data.get("oi_degisim_pct", 0)
        order_book   = market_data.get("order_book", {})

        # Contrarian göstergeler
        # Aşırı long + yüksek funding = long riski
        long_doyum = (ls_ratio > 2.5 and funding > 0.001)
        # Aşırı short + negatif funding = short riski
        short_doyum = (ls_ratio < 0.5 and funding < -0.001)

        if yon == "LONG" and long_doyum:
            log.debug(f"[EDGE] Long doyum: ls={ls_ratio:.2f} funding={funding:.5f}")
            # Engelleme değil — sadece skor düşür
            detay["long_doyum_uyari"] = True

        ob_imbalance = order_book.get("imbalance", 0.5)
        ob_uygun     = (yon == "LONG" and ob_imbalance > 0.45) or \
                       (yon == "SHORT" and ob_imbalance < 0.55)
        detay["ob_imbalance"] = ob_imbalance

        # ── 5. Volatilite Filtresi ────────────────────────
        atr_pct = (son_atr / son_close) * 100 if son_close > 0 else 0
        # Çok yüksek volatilite = giriş riski
        if atr_pct > 4.0 and rejim != "VOLATILE":
            return EdgeSonuc(False, 0, 0, secilen_strateji,
                              f"ATR çok yüksek: %{atr_pct:.2f} (rejim={rejim})",
                              detay).__dict__
        detay["atr_pct"] = round(atr_pct, 3)

        # ── 6. Güven Skoru Hesapla ────────────────────────
        confidence = self._confidence_hesapla(
            ai_score, yukselis_guveni, mtf_skor, ms_skor,
            ob_imbalance, yon, fear_greed, oi_degisim
        )
        detay["confidence"] = confidence

        if confidence < MIN_CONFIDENCE:
            return EdgeSonuc(False, 0, confidence, secilen_strateji,
                              f"Güven %{confidence} < %{MIN_CONFIDENCE}",
                              detay).__dict__

        # ── 7. Edge Score ─────────────────────────────────
        edge_score = self._edge_score_hesapla(
            ai_score, confidence, mtf_skor, ms_skor,
            ob_uygun, atr_pct, rejim
        )
        detay["edge_score"] = round(edge_score, 2)

        log.info(f"[EDGE] ✅ {yon} rejim={rejim} strateji={secilen_strateji} "
                  f"edge={edge_score:.1f} conf=%{confidence}")

        return EdgeSonuc(
            gecti=True, edge_score=edge_score,
            confidence=confidence, strateji=secilen_strateji,
            sebep=f"Tüm filtreler geçildi",
            detay=detay
        ).__dict__

    def _ai_esik_hesapla(self, rejim: str, yon: str) -> int:
        """Rejime göre dinamik AI skoru eşiği."""
        esikler = {
            "TREND_UP":   REGIME_TREND_MIN_AI,
            "TREND_DOWN": REGIME_TREND_MIN_AI,
            "RANGE":      REGIME_RANGE_MIN_AI,
            "BEAR":       REGIME_BEAR_MIN_AI,
            "VOLATILE":   REGIME_VOLATILE_MIN_AI,
        }
        return esikler.get(rejim, MIN_AI_SCORE_BUY)

    def _confidence_hesapla(self, ai_score, yukselis, mtf_skor,
                              ms_skor, ob_imbalance, yon,
                              fear_greed, oi_degisim) -> int:
        """Çok faktörlü güven skoru (0–100)."""
        puan = 45  # başlangıç

        # AI katkısı
        if abs(ai_score) >= 8:   puan += 25
        elif abs(ai_score) >= 5: puan += 18
        elif abs(ai_score) >= 3: puan += 10

        # Model güveni
        if yukselis > 65:        puan += 10
        elif yukselis > 55:      puan += 5

        # MTF
        if abs(mtf_skor) >= 4:   puan += 10
        elif abs(mtf_skor) >= 2: puan += 5

        # Market sentiment
        if (yon == "LONG" and ms_skor > 1) or (yon == "SHORT" and ms_skor < -1):
            puan += 8

        # Order book
        if (yon == "LONG" and ob_imbalance > 0.60) or \
           (yon == "SHORT" and ob_imbalance < 0.40):
            puan += 5

        # Fear & Greed contrarian
        if yon == "LONG" and fear_greed < 25:    puan += 7   # aşırı korku = fırsat
        elif yon == "SHORT" and fear_greed > 75: puan += 7   # aşırı açgözlülük

        # OI artışı sinyal kuvvetlendirme
        if abs(oi_degisim) > 2:   puan += 3

        return min(puan, 100)

    def _edge_score_hesapla(self, ai_score, confidence, mtf_skor,
                              ms_skor, ob_uygun, atr_pct, rejim) -> float:
        """
        Edge kalitesi: 0–100.
        100 = mükemmel setup. 50 = kabul edilebilir. <50 = zayıf.
        """
        skor = 0.0

        # AI katkısı (%35 ağırlık)
        ai_norm = min(abs(ai_score) / 10, 1.0)
        skor   += ai_norm * 35

        # Güven (%25 ağırlık)
        skor   += (confidence / 100) * 25

        # MTF (%20 ağırlık)
        mtf_norm = min(abs(mtf_skor) / 8, 1.0)
        skor     += mtf_norm * 20

        # Market structure (%10 ağırlık)
        if ob_uygun: skor += 7
        if abs(ms_skor) > 1: skor += 3

        # Volatilite cezası (%10)
        if atr_pct > 3:   skor -= 8
        elif atr_pct > 2: skor -= 3

        # Rejim bonusu
        if rejim in ("TREND_UP", "TREND_DOWN"): skor += 5
        elif rejim == "VOLATILE": skor -= 5

        return round(max(0, min(100, skor)), 2)
