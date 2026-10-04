# =========================================================
# ASTRA v30.0 — ADAPTIVE POSITION SIZING
# Volatility + Confidence + Regime + Streak bazlı
# =========================================================
import logging
from typing import Optional
import sys; sys.path.append("..")

log = logging.getLogger("ASTRA.SIZING")

class AdaptiveSizing:
    """
    Pozisyon boyutunu dinamik olarak hesaplar.
    
    Formül:
        usdt = base_usdt * confidence_mult * regime_mult * vol_mult * streak_mult
    """

    def __init__(self, base_usdt: float = 20.0, max_usdt: float = 100.0):
        self.base_usdt  = base_usdt
        self.max_usdt   = max_usdt
        self._kayip_seri = 0
        self._kazanc_seri = 0

    def sonuc_bildir(self, kazandi: bool):
        """Her kapanan işlemden sonra çağır."""
        if kazandi:
            self._kayip_seri   = 0
            self._kazanc_seri += 1
        else:
            self._kazanc_seri  = 0
            self._kayip_seri  += 1

    def hesapla(self,
                confidence:   int,
                rejim:        str,
                atr_pct:      float,
                ai_score:     int,
                edge_score:   float,
                bakiye:       float,
                max_bakiye_pct: float = 0.15) -> float:
        """
        Adaptif pozisyon boyutu döndür (USDT).
        
        Args:
            confidence:      0-100 model güveni
            rejim:           Piyasa rejimi
            atr_pct:         ATR/fiyat %
            ai_score:        -12..+12
            edge_score:      0-100 edge kalitesi
            bakiye:          Mevcut bakiye
            max_bakiye_pct:  Max pozisyon bakiye %'si
        """
        usdt = self.base_usdt

        # 1. Confidence çarpanı (0.5x - 1.5x)
        conf_mult = 0.5 + (confidence / 100.0)
        conf_mult = max(0.5, min(1.5, conf_mult))

        # 2. Regime çarpanı
        regime_mult = {
            "TREND_UP":   1.3,
            "TREND_DOWN": 1.2,
            "RANGE":      0.8,
            "VOLATILE":   0.5,
            "BEAR":       0.6,
        }.get(rejim, 0.8)

        # 3. Volatility çarpanı (yüksek vol = küçük pozisyon)
        if atr_pct < 0.5:
            vol_mult = 1.3
        elif atr_pct < 1.0:
            vol_mult = 1.1
        elif atr_pct < 2.0:
            vol_mult = 1.0
        elif atr_pct < 3.5:
            vol_mult = 0.7
        else:
            vol_mult = 0.4   # çok volatil

        # 4. Streak çarpanı (kayıp serisi = küçült)
        if self._kayip_seri >= 4:
            streak_mult = 0.3
        elif self._kayip_seri == 3:
            streak_mult = 0.5
        elif self._kayip_seri == 2:
            streak_mult = 0.7
        elif self._kayip_seri == 1:
            streak_mult = 0.85
        elif self._kazanc_seri >= 3:
            streak_mult = 1.2  # kazanç serisinde hafif büyüt
        else:
            streak_mult = 1.0

        # 5. Edge score çarpanı
        edge_mult = 0.7 + (edge_score / 100.0) * 0.6

        # 6. AI score çarpanı
        ai_abs = abs(ai_score)
        if ai_abs >= 8:
            ai_mult = 1.3
        elif ai_abs >= 6:
            ai_mult = 1.1
        elif ai_abs >= 4:
            ai_mult = 1.0
        else:
            ai_mult = 0.8

        # Hesapla
        usdt = self.base_usdt * conf_mult * regime_mult * vol_mult * streak_mult * edge_mult * ai_mult
        
        # Sınırla
        max_by_balance = bakiye * max_bakiye_pct
        usdt = min(usdt, self.max_usdt, max_by_balance, bakiye * 0.9)

        # ── v52 KRİTİK DÜZELTME: minimum, LİMİTLERİ EZMEMELİ ──
        # Eski kod `usdt = max(usdt, 5.0)` yazıyordu; bu, bakiye limitini
        # ve kayıp-serisi korumasını GEÇERSİZ kılıyordu:
        #   • Bakiye 8$ → limit 1.20$ olmalı, ama 5$ pozisyon açılıyordu (4.2x aşım)
        #   • 4 ard arda kayıpta streak_mult=0.3 ile küçültme yapılıyor,
        #     sonra minimum bunu 5$'a geri çekiyordu → koruma etkisiz.
        # Doğru davranış: hesaplanan boyut minimumun altındaysa, bu
        # "işlem yapılamayacak kadar küçük" demektir → 0 dön, işlem AÇMA.
        MIN_ISLEM_USDT = 5.0
        if usdt < MIN_ISLEM_USDT:
            log.info(f"[SIZING] Hesaplanan boyut {usdt:.2f}$ < minimum "
                     f"{MIN_ISLEM_USDT}$ (bakiye {bakiye:.2f}$, limit "
                     f"{max_by_balance:.2f}$) → işlem açılmayacak")
            return 0.0

        log.debug(
            f"[SIZING] base:{self.base_usdt:.1f} "
            f"conf:{conf_mult:.2f} reg:{regime_mult:.2f} "
            f"vol:{vol_mult:.2f} streak:{streak_mult:.2f} "
            f"edge:{edge_mult:.2f} ai:{ai_mult:.2f} "
            f"→ {usdt:.2f}$"
        )
        return round(usdt, 2)

    @property
    def durum(self) -> dict:
        return {
            "kayip_seri":  self._kayip_seri,
            "kazanc_seri": self._kazanc_seri,
            "base_usdt":   self.base_usdt,
        }


_instance = None
def get_adaptive_sizing(base_usdt=20.0, max_usdt=100.0) -> AdaptiveSizing:
    global _instance
    if _instance is None:
        try:
            from config import TRADE_USDT
            base_usdt = TRADE_USDT
        except ImportError: pass
        _instance = AdaptiveSizing(base_usdt, max_usdt)
    return _instance
