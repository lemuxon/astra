# =========================================================
# ASTRA v30.0 — AI MEMORY / PERFORMANCE TRACKER
# engines/performance_tracker.py
# =========================================================

import logging
import numpy as np
from datetime import datetime, timezone

import sys
sys.path.append("..")
from data.database import (son_sinyaller, win_rate_hesapla,
                             toplam_pnl, model_gecmisi, baglanti_al)

log = logging.getLogger("ASTRA.TRACKER")


class PerformanceTracker:
    """
    AI Hafızası:
    - Her sinyalin gerçekte doğru olup olmadığını takip eder
    - Model doğruluk trendini izler
    - Telegram raporu üretir
    """

    def __init__(self, sembol: str = "BTCUSDT"):
        self.sembol = sembol

    def sinyal_dogruluk_hesapla(self) -> dict:
        """Son sinyallerin gerçek fiyat hareketiyle karşılaştırması."""
        sinyaller = son_sinyaller(self.sembol, limit=100)
        if len(sinyaller) < 2:
            return {"mesaj": "Yeterli sinyal yok"}

        # v55 DÜZELTME: son_sinyaller() `ORDER BY id DESC` döner (en YENİ önce).
        # Eski kod sinyaller[i+1]'i "sonraki sinyal" sanıyordu; oysa o
        # kronolojik olarak ÖNCEKİ sinyaldi. Yani her sinyalin tahmini,
        # o sinyalden ÖNCE çoktan gerçekleşmiş fiyat hareketiyle
        # karşılaştırılıyordu — öngörü doğruluğunun tam TERSİ.
        # Listeyi kronolojik sıraya çevirerek eşleştirme doğru hale getirildi.
        sinyaller = list(reversed(sinyaller))

        dogru = 0
        toplam = 0
        for i in range(len(sinyaller) - 1):
            s       = sinyaller[i]      # önce gelen sinyal
            s_sonra = sinyaller[i + 1]  # ondan SONRA gelen sinyal
            karar   = s["karar"]
            fiyat   = s["fiyat"]
            sonraki = s_sonra["fiyat"]

            beklenti = None
            if "BUY" in karar or "AL" in karar:
                beklenti = "YUKARI"
            elif "SELL" in karar or "SAT" in karar:
                beklenti = "ASAGI"

            if beklenti:
                gercek = "YUKARI" if sonraki > fiyat else "ASAGI"
                if beklenti == gercek:
                    dogru += 1
                toplam += 1

        oran = round(dogru / toplam * 100, 2) if toplam > 0 else 0
        return {
            "toplam_sinyal":  toplam,
            "dogru":          dogru,
            "yanlis":         toplam - dogru,
            "dogruluk":       oran,
        }

    def model_trend(self) -> dict:
        """Son N modelin doğruluk trendi."""
        gecmis = model_gecmisi(self.sembol, limit=20)
        if not gecmis:
            return {"trend": "VERİ YOK"}
        dogruluklar = [g["dogruluk"] for g in gecmis]
        ort = np.mean(dogruluklar)
        son = dogruluklar[0]
        trend = "ARTIYOR" if son > ort else ("DUŞUYOR" if son < ort else "STABIL")
        return {
            "son_dogruluk":  round(son, 4),
            "ortalama":      round(ort, 4),
            "trend":         trend,
            "gecmis":        dogruluklar[:5],
        }

    def pnl_analiz(self) -> dict:
        """PnL ve istatistik özeti."""
        istatistik = win_rate_hesapla("PAPER")
        pnl        = toplam_pnl("PAPER")
        return {
            "toplam_pnl":  pnl,
            "istatistik":  istatistik,
        }

    def tam_rapor(self) -> dict:
        return {
            "ts":             datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "sembol":         self.sembol,
            "sinyal_dogruluk": self.sinyal_dogruluk_hesapla(),
            "model_trend":    self.model_trend(),
            "pnl_analiz":     self.pnl_analiz(),
        }

    def telegram_raporu(self) -> str:
        r   = self.tam_rapor()
        sd  = r["sinyal_dogruluk"]
        mt  = r["model_trend"]
        pnl = r["pnl_analiz"]
        ist = pnl["istatistik"]

        return (
            f"🧠 <b>AI MEMORY RAPORU — {self.sembol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📡 Sinyal Doğruluğu\n"
            f"  Toplam : {sd.get('toplam_sinyal', 0)}\n"
            f"  Doğru  : {sd.get('dogru', 0)} (%{sd.get('dogruluk', 0)})\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🤖 Model Trendi\n"
            f"  Son Acc: %{mt.get('son_dogruluk', 0)*100:.1f}\n"
            f"  Ort Acc: %{mt.get('ortalama', 0)*100:.1f}\n"
            f"  Trend  : {mt.get('trend', '-')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Paper Trading\n"
            f"  PnL    : {pnl['toplam_pnl']:+.4f}\n"
            f"  İşlem  : {ist.get('toplam', 0)}\n"
            f"  Win %  : %{ist.get('win_rate', 0)}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
