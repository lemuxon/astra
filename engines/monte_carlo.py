# =========================================================
# ASTRA v30.0 — MONTE CARLO RİSK ANALİZİ
# VaR, CVaR, Max Drawdown simülasyonu
# Liquidation riski hesaplama
# =========================================================
import logging, numpy as np, pandas as pd
from datetime import datetime, timezone
from typing import Optional
import sys; sys.path.append("..")
from config import MC_SIMULATIONS, MC_CONFIDENCE, MC_LOOKBACK_DAYS

log = logging.getLogger("ASTRA.MONTE_CARLO")

class MonteCarloRisk:

    def __init__(self, simulations: int = MC_SIMULATIONS,
                 confidence: float = MC_CONFIDENCE):
        self.simulations = simulations
        self.confidence  = confidence

    def getiri_hesapla(self, close: pd.Series) -> np.ndarray:
        """Logaritmik getiriler."""
        return np.log(close / close.shift(1)).dropna().values

    def var_hesapla(self, getiriler: np.ndarray,
                    bakiye: float, gun: int = 1) -> dict:
        """
        Value at Risk (VaR) ve Conditional VaR (CVaR).

        ⚠️ v58 (K-46) — BİRİM SÖZLEŞMESİ:
        `gun` parametresi GİRDİNİN BİR ADIMI kadar ölçekler. Yani
        `getiriler` GÜNLÜK getiri değilse sonuç GÜN cinsinden DEĞİLDİR.
        Çağıran taraf günlük veri vermekle yükümlü.

        Bu sessizce ihlal edilmişti: `monte_carlo_raporu` saatlik veri
        besliyor, çıktı "1G VaR" diye gösteriliyordu → risk ~5 kat
        düşük. Ayrıca `pozisyon_icin_tam_analiz`'deki
        `var_pct > 3 → YÜKSEK` eşiği günlük VaR için kalibre olduğundan
        risk seviyesi pratikte hep "DÜŞÜK" çıkıyordu.
        """
        if len(getiriler) < 10:
            return {"var": 0, "cvar": 0, "confidence": self.confidence}

        mu  = np.mean(getiriler)
        sig = np.std(getiriler)

        # Monte Carlo simülasyonu
        sim_getiriler = np.random.normal(
            mu * gun, sig * np.sqrt(gun), self.simulations
        )

        # VaR: kayıpların (1-confidence) yüzdeliği
        esik = np.percentile(sim_getiriler, (1 - self.confidence) * 100)
        var  = abs(min(esik, 0)) * bakiye

        # CVaR (Expected Shortfall): VaR'ın ötesindeki ortalama kayıp
        kayiplar = sim_getiriler[sim_getiriler < esik]
        cvar     = abs(np.mean(kayiplar)) * bakiye if len(kayiplar) > 0 else var * 1.3

        return {
            "var_usdt":   round(var, 2),
            "cvar_usdt":  round(cvar, 2),
            "var_pct":    round(abs(min(esik, 0)) * 100, 3),
            "gun":        gun,
            "confidence": self.confidence,
            "sim_count":  self.simulations,
        }

    def max_drawdown_sim(self, getiriler: np.ndarray,
                          bakiye: float, gun: int = 30) -> dict:
        """
        30 günlük max drawdown simülasyonu.
        En kötü senaryo ve beklenen drawdown hesaplar.
        """
        if len(getiriler) < 10:
            return {"beklenen_dd": 0, "worst_case_dd": 0}

        mu  = np.mean(getiriler)
        sig = np.std(getiriler)
        drawdownlar = []

        for _ in range(min(self.simulations, 5000)):
            sim = np.random.normal(mu, sig, gun)
            kumulatif = bakiye * np.exp(np.cumsum(sim))
            peak = np.maximum.accumulate(kumulatif)
            dd   = (kumulatif - peak) / peak
            drawdownlar.append(float(dd.min()))

        drawdownlar = np.array(drawdownlar)
        beklenen    = float(np.mean(drawdownlar))
        worst       = float(np.percentile(drawdownlar, 5))  # %5 en kötü

        return {
            "beklenen_dd_pct": round(abs(beklenen) * 100, 2),
            "worst_case_dd_pct": round(abs(worst) * 100, 2),
            "beklenen_dd_usdt": round(abs(beklenen) * bakiye, 2),
            "worst_case_usdt":  round(abs(worst) * bakiye, 2),
            "gun": gun,
        }

    def likidisyon_riski(self, giris_fiyat: float, miktar: float,
                          kaldirac: int, margin_usdt: float,
                          getiriler: np.ndarray,
                          yon: str = "LONG") -> dict:
        """
        Likidasyon simülasyonu.
        Mevcut pozisyon için likidasyon fiyatını ve olasılığını hesaplar.
        """
        if giris_fiyat <= 0 or miktar <= 0:
            return {"likidasyon_fiyat": 0, "likidasyon_olasiligi": 0}

        # Binance ISOLATED margin likidasyon fiyatı
        if yon == "LONG":
            likidasyon_fiyat = giris_fiyat * (1 - (1 / kaldirac) + 0.004)
        else:
            likidasyon_fiyat = giris_fiyat * (1 + (1 / kaldirac) - 0.004)

        uzaklik_pct = abs(giris_fiyat - likidasyon_fiyat) / giris_fiyat * 100

        # Monte Carlo ile likidasyon olasılığı
        if len(getiriler) >= 5:
            mu  = np.mean(getiriler)
            sig = np.std(getiriler)
            sim = np.random.normal(mu, sig, (min(self.simulations, 5000), 10))
            sim_fiyatlar = giris_fiyat * np.exp(np.cumsum(sim, axis=1))

            if yon == "LONG":
                likit_sayisi = np.any(sim_fiyatlar <= likidasyon_fiyat, axis=1).sum()
            else:
                likit_sayisi = np.any(sim_fiyatlar >= likidasyon_fiyat, axis=1).sum()

            olasilik = likit_sayisi / len(sim) * 100
        else:
            olasilik = 0

        return {
            "likidasyon_fiyat":    round(likidasyon_fiyat, 4),
            "uzaklik_pct":         round(uzaklik_pct, 2),
            "likidasyon_olasiligi":round(olasilik, 2),
            "guvenli":             olasilik < 5.0,
            "yon": yon,
        }

    def pozisyon_icin_tam_analiz(self, close: pd.Series,
                                  bakiye: float,
                                  pozisyonlar: list = None) -> dict:
        """
        Tüm risk metriklerini tek seferde döner.
        pozisyonlar: [{sembol, giris, miktar, kaldirac, yon}, ...]
        """
        getiriler = self.getiri_hesapla(close)
        var       = self.var_hesapla(getiriler, bakiye)
        dd        = self.max_drawdown_sim(getiriler, bakiye)

        likit_riskleri = []
        if pozisyonlar:
            for poz in pozisyonlar:
                lr = self.likidisyon_riski(
                    poz.get("giris", 0), poz.get("miktar", 0),
                    poz.get("kaldirac", 5), bakiye,
                    getiriler, poz.get("yon", "LONG")
                )
                lr["sembol"] = poz.get("sembol","?")
                likit_riskleri.append(lr)

        # Genel risk değerlendirmesi
        risk_seviyesi = "DÜŞÜK"
        if var["var_pct"] > 3 or dd["worst_case_dd_pct"] > 20:
            risk_seviyesi = "YÜKSEK"
        elif var["var_pct"] > 1.5 or dd["worst_case_dd_pct"] > 10:
            risk_seviyesi = "ORTA"

        return {
            "ts":             datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "bakiye":         bakiye,
            "var":            var,
            "drawdown":       dd,
            "likidasyon":     likit_riskleri,
            "risk_seviyesi":  risk_seviyesi,
            "tavsiye":        self._tavsiye_uret(var, dd, likit_riskleri),
        }

    def _tavsiye_uret(self, var: dict, dd: dict, likit: list) -> list:
        tavsiyeler = []
        if var["var_pct"] > 3:
            tavsiyeler.append("⚠️ Günlük VaR yüksek — pozisyon büyüklüğünü azalt")
        if dd["worst_case_dd_pct"] > 20:
            tavsiyeler.append("⚠️ 30 günlük worst-case drawdown %20 üstü — kaldıracı kıs")
        for poz in likit:
            if poz.get("likidasyon_olasiligi", 0) > 5:
                tavsiyeler.append(
                    f"🚨 {poz['sembol']} likidasyon riski %{poz['likidasyon_olasiligi']:.1f} — SL'yi daralt"
                )
        if not tavsiyeler:
            tavsiyeler.append("✅ Risk seviyeleri normal sınırlarda")
        return tavsiyeler

# Singleton
_mc_instance: Optional[MonteCarloRisk] = None

def get_mc() -> MonteCarloRisk:
    global _mc_instance
    if _mc_instance is None:
        _mc_instance = MonteCarloRisk()
    return _mc_instance
