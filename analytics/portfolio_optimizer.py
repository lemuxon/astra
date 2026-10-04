# =========================================================
# ASTRA v30.0 — PORTFOLIO OPTIMIZER
# Mean-Variance Optimization (MVO) + Risk Parity
# scipy.optimize — zaten requirements.txt'de mevcut
#
# Kullanım:
#   1. Tüm coinlerin getiri serileri ile çalışır
#   2. MVO: En yüksek Sharpe oranı için optimal ağırlıklar
#   3. Risk Parity: Her coin eşit risk katkısı
#   4. Sonuç: Her coin için max_usdt sınırı içinde USDT limiti
#
# _execution_isle'de pozisyon buyukluğunu override eder.
# Korelasyon Engine'in bloklaması devrede kalır.
# =========================================================
import logging, time
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

log = logging.getLogger("ASTRA.PORTFOLIO")

try:
    from scipy.optimize import minimize
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    log.warning("[PORTFOLIO] scipy bulunamadı — eşit ağırlık kullanılacak.")

_CACHE_TTL    = 300   # 5 dakika — her 5 dakikada bir yeniden optimize et
_MIN_GETIRI   = 30    # Minimum veri noktası
_MAX_AGIRLIK  = 0.40  # Tek coin max %40 portföy ağırlığı
_MIN_AGIRLIK  = 0.05  # Tek coin min %5 (diversification)


class PortfolioOptimizer:
    """
    MVO (Markowitz Mean-Variance Optimization) + Risk Parity.

    Akış:
      1. Coin getiri serileri alınır (son 30 gün, 1h)
      2. Beklenen getiri + kovaryans matrisi hesaplanır
      3. scipy.minimize ile max Sharpe optimizasyonu
      4. Fallback: Risk Parity (eşit risk katkısı)
      5. Her coin için USDT limiti döner

    Kullanım noktası: _execution_isle → pozisyon_buyuklugu
    """

    def __init__(self, risk_free_rate: float = 0.05 / 252):
        self._rf           = risk_free_rate   # Günlük risk-free rate
        self._agirliklar: Dict[str, float] = {}   # Son optimize ağırlıklar
        self._son_optimize: float = 0.0
        self._yontem: str  = "Başlatılmadı"
        self._sharpe: float= 0.0

    def optimize(self, getiri_serileri: Dict[str, pd.Series],
                  toplam_bakiye: float) -> Dict[str, float]:
        """
        Portföy optimizasyonu — USDT limitleri döner.

        Args:
            getiri_serileri: {sembol: log_getiri_serisi}
            toplam_bakiye:   Kullanılabilir toplam USDT

        Returns:
            {sembol: max_usdt_limiti}
        """
        # Cache kontrolü
        if (time.time() - self._son_optimize < _CACHE_TTL
                and self._agirliklar):
            return self._agirlik_to_usdt(self._agirliklar, toplam_bakiye)

        semboller = list(getiri_serileri.keys())
        n = len(semboller)

        if n == 0:
            return {}
        if n == 1:
            return {semboller[0]: toplam_bakiye * _MAX_AGIRLIK}

        # Getiri matrisini hazırla
        df = pd.DataFrame(getiri_serileri).dropna()
        if len(df) < _MIN_GETIRI:
            log.warning(f"[MVO] Yetersiz veri ({len(df)}<{_MIN_GETIRI}) — eşit ağırlık")
            return self._esit_agirlik(semboller, toplam_bakiye)

        try:
            mu   = df.mean().values * 252          # Yıllıklaştırılmış beklenen getiri
            cov  = df.cov().values * 252            # Yıllıklaştırılmış kovaryans
            agirliklar = self._mvo_optimize(mu, cov, semboller)
            self._yontem = "MVO (Max Sharpe)"
        except Exception as e:
            log.warning(f"[MVO] Optimizasyon hatası: {e} — Risk Parity'e geçiliyor")
            try:
                cov = df.cov().values * 252
                agirliklar = self._risk_parity(cov, semboller)
                self._yontem = "Risk Parity"
            except Exception as e2:
                log.warning(f"[RISK PARITY] Hatası: {e2} — eşit ağırlık")
                return self._esit_agirlik(semboller, toplam_bakiye)

        self._agirliklar   = agirliklar
        self._son_optimize = time.time()

        # Sharpe hesapla
        try:
            w   = np.array([agirliklar[s] for s in semboller])
            mu2 = df.mean().values * 252
            cov2= df.cov().values * 252
            p_ret = float(w @ mu2)
            p_vol = float(np.sqrt(w @ cov2 @ w))
            self._sharpe = (p_ret - self._rf * 252) / p_vol if p_vol > 0 else 0
        except Exception:
            self._sharpe = 0

        log.info(f"[PORTFOLIO] Yöntem:{self._yontem} Sharpe:{self._sharpe:.3f} "
                 f"Ağırlıklar:{[(s, round(v,3)) for s,v in agirliklar.items()]}")

        return self._agirlik_to_usdt(agirliklar, toplam_bakiye)

    def _mvo_optimize(self, mu: np.ndarray, cov: np.ndarray,
                       semboller: List[str]) -> Dict[str, float]:
        """Scipy ile Maximum Sharpe Ratio optimizasyonu."""
        if not SCIPY_AVAILABLE:
            raise RuntimeError("scipy yok")

        n = len(semboller)

        def neg_sharpe(w):
            ret = float(w @ mu)
            vol = float(np.sqrt(w @ cov @ w))
            if vol < 1e-10: return 0.0
            return -(ret - self._rf * 252) / vol

        kısıtlar = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        sınırlar = [(_MIN_AGIRLIK, _MAX_AGIRLIK) for _ in range(n)]
        x0       = np.ones(n) / n

        sonuc = minimize(
            neg_sharpe, x0,
            method="SLSQP",
            bounds=sınırlar,
            constraints=kısıtlar,
            options={"maxiter": 500, "ftol": 1e-9},
        )

        if not sonuc.success:
            raise RuntimeError(f"Optimizasyon yakınsayamadı: {sonuc.message}")

        w = sonuc.x
        # v23: NaN/inf koruması — singular kovaryans NaN ağırlık üretebilir
        if not np.all(np.isfinite(w)):
            raise RuntimeError("Optimizasyon NaN/inf ağırlık üretti")
        w = np.clip(w, _MIN_AGIRLIK, _MAX_AGIRLIK)
        _toplam = w.sum()
        if _toplam <= 0:
            raise RuntimeError("Ağırlık toplamı sıfır")
        w = w / _toplam
        return {s: round(float(w[i]), 4) for i, s in enumerate(semboller)}

    def _risk_parity(self, cov: np.ndarray,
                      semboller: List[str]) -> Dict[str, float]:
        """
        Risk Parity: Her coin eşit risk katkısı.
        Basit yaklaşım: ağırlık = 1 / volatilite (normalize)
        """
        n = len(semboller)
        vol = np.sqrt(np.diag(cov))
        vol = np.where(vol < 1e-10, 1e-10, vol)
        w   = (1.0 / vol)
        w   = np.clip(w / w.sum(), _MIN_AGIRLIK, _MAX_AGIRLIK)
        w   = w / w.sum()
        return {s: round(float(w[i]), 4) for i, s in enumerate(semboller)}

    def _esit_agirlik(self, semboller: List[str],
                       toplam_bakiye: float) -> Dict[str, float]:
        agirlik = min(1.0 / len(semboller), _MAX_AGIRLIK)
        return {s: round(toplam_bakiye * agirlik, 2) for s in semboller}

    def _agirlik_to_usdt(self, agirliklar: Dict[str, float],
                          toplam_bakiye: float) -> Dict[str, float]:
        """Ağırlıkları USDT limitine çevir (max %90 kullan)."""
        kullanilabilir = toplam_bakiye * 0.90
        return {s: round(v * kullanilabilir, 2) for s, v in agirliklar.items()}

    def coin_usdt_limiti(self, sembol: str,
                          getiri_serileri: Dict[str, pd.Series],
                          toplam_bakiye: float,
                          fallback_usdt: float = 20.0) -> float:
        """Tek coin için USDT limitini döner. _execution_isle'den çağrılır."""
        try:
            limitler = self.optimize(getiri_serileri, toplam_bakiye)
            return limitler.get(sembol, fallback_usdt)
        except Exception as e:
            log.warning(f"[PORTFOLIO] {sembol} limit hesaplanamadı: {e}")
            return fallback_usdt

    def durum_raporu(self) -> str:
        if not self._agirliklar:
            return "Portfolio: henüz optimize edilmedi"
        gecen = int(time.time() - self._son_optimize)
        satirlar = [
            f"📊 <b>PORTFOLIO OPTİMİZASYON v20</b>",
            f"━━━━━━━━━━━━━━━━",
            f"Yöntem: {self._yontem}",
            f"Sharpe: {self._sharpe:.3f}",
            f"Son güncelleme: {gecen}s önce",
            "Ağırlıklar:",
        ]
        for s, w in sorted(self._agirliklar.items(), key=lambda x: -x[1]):
            bar = "█" * int(w * 20)
            satirlar.append(f"  {s}: %{w*100:.1f} {bar}")
        return "\n".join(satirlar)


# ── Singleton ─────────────────────────────────────────────
_optimizer: Optional[PortfolioOptimizer] = None

def get_portfolio_optimizer() -> PortfolioOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = PortfolioOptimizer()
    return _optimizer
