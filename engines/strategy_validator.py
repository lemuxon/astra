# =========================================================
# ASTRA v30.0 — STRATEJİ DAYANIKLILIK & DOĞRULAMA KATMANI
# =========================================================
# Amaç: Bir stratejinin/modelin canlıya çıkmadan veya canlıda kalmadan
#       önce çok katmanlı dayanıklılık testlerinden geçmesi.
#
# Üç katman:
#   1. Walk-Forward Robustness  — zamana göre tutarlılık (deflated Sharpe)
#   2. Monte Carlo Stres Testi  — fat-tail + bootstrap + tarihsel kriz senaryoları
#   3. Otomatik Onay/Red Kapısı — tüm testleri birleştirip GO / NO-GO kararı
#
# Çıktı: StratejiKarari (onay: bool, skor: 0-100, sebepler: list)
#
# Felsefe: "Bir strateji geçemiyorsa, parayla test etmek yerine reddet."
# =========================================================
import logging
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable
from datetime import datetime, timezone

log = logging.getLogger("ASTRA.VALIDATOR")

# ── Eşikler (config'den override edilebilir) ──────────────
try:
    from config import (
        VALIDATOR_MIN_SKOR, VALIDATOR_MIN_DSR, VALIDATOR_MAX_DD_PCT,
        VALIDATOR_MIN_WF_TUTARLILIK, VALIDATOR_BOOTSTRAP_N,
    )
except ImportError:
    VALIDATOR_MIN_SKOR         = 60.0   # 100 üzerinden geçme eşiği
    VALIDATOR_MIN_DSR          = 0.0    # Deflated Sharpe Ratio > 0 olmalı
    VALIDATOR_MAX_DD_PCT       = 35.0   # Worst-case drawdown tavanı
    VALIDATOR_MIN_WF_TUTARLILIK= 0.55   # WF pencerelerinin kaçı pozitif olmalı
    VALIDATOR_BOOTSTRAP_N      = 2000   # Bootstrap simülasyon sayısı


@dataclass
class StratejiKarari:
    """Doğrulama sonucu — GO/NO-GO kararı."""
    onay:          bool
    skor:          float                      # 0-100 birleşik dayanıklılık skoru
    sebepler:      List[str] = field(default_factory=list)
    wf_sonuc:      Dict      = field(default_factory=dict)
    mc_sonuc:      Dict      = field(default_factory=dict)
    stres_sonuc:   Dict      = field(default_factory=dict)
    ts:            str       = ""

    def __post_init__(self):
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()

    def telegram_raporu(self) -> str:
        durum = "✅ ONAYLANDI" if self.onay else "❌ REDDEDİLDİ"
        satirlar = [
            f"🛡️ <b>STRATEJİ DOĞRULAMA</b>",
            f"━━━━━━━━━━━━━━━━",
            f"Sonuç: <b>{durum}</b>",
            f"Dayanıklılık Skoru: {self.skor:.1f}/100",
            f"━━━━━━━━━━━━━━━━",
        ]
        if self.wf_sonuc:
            satirlar.append(f"📈 Walk-Forward:")
            satirlar.append(f"  DSR: {self.wf_sonuc.get('dsr', 0):.3f}")
            satirlar.append(f"  Tutarlılık: %{self.wf_sonuc.get('tutarlilik', 0)*100:.0f}")
        if self.stres_sonuc:
            satirlar.append(f"💥 Stres Testi:")
            satirlar.append(f"  Worst-case DD: %{self.stres_sonuc.get('worst_dd_pct', 0):.1f}")
            satirlar.append(f"  Kriz hayatta kalma: %{self.stres_sonuc.get('hayatta_kalma', 0)*100:.0f}")
        satirlar.append(f"━━━━━━━━━━━━━━━━")
        satirlar.append("📋 <b>Değerlendirme:</b>")
        for s in self.sebepler[:8]:
            satirlar.append(f"  • {s}")
        return "\n".join(satirlar)


class StratejiValidator:
    """
    Çok katmanlı strateji dayanıklılık doğrulayıcı.

    Kullanım:
      validator = StratejiValidator()
      karar = validator.dogrula(
          getiriler=trade_getiri_serisi,   # işlem bazlı % getiriler
          equity_curve=equity_serisi,       # opsiyonel
          wf_pencere_sonuclari=[...]        # walk-forward pencere accuracy/getiri
      )
      if karar.onay: ...  # canlıya al
    """

    # ── Deflated Sharpe Ratio ─────────────────────────────
    @staticmethod
    def deflated_sharpe(getiriler: np.ndarray,
                         deneme_sayisi: int = 1) -> float:
        """
        Deflated Sharpe Ratio (Bailey & López de Prado, 2014).
        Çoklu deneme (strateji aramada) Sharpe'ı şişirir; DSR bunu düzeltir.

        Pozitif DSR = strateji şanstan daha iyi (istatistiksel olarak).
        deneme_sayisi: kaç farklı strateji/parametre denendi (overfit cezası).
        """
        n = len(getiriler)
        if n < 20:
            return 0.0
        mu  = np.mean(getiriler)
        sig = np.std(getiriler, ddof=1)
        if sig < 1e-12:
            return 0.0
        sharpe = mu / sig

        # Çarpıklık (skewness) ve basıklık (kurtosis)
        g = (getiriler - mu) / sig
        skew = np.mean(g ** 3)
        kurt = np.mean(g ** 4)

        # Sharpe tahmininin standart sapması (yüksek momentler dahil)
        sr_std = np.sqrt(
            (1 - skew * sharpe + (kurt - 1) / 4 * sharpe ** 2) / (n - 1)
        )
        if sr_std < 1e-12:
            return 0.0

        # Çoklu deneme beklenen max Sharpe (deflation eşiği)
        from math import sqrt, log as ln
        euler = 0.5772156649
        if deneme_sayisi > 1:
            z1 = (1 - euler) * _norm_ppf(1 - 1.0 / deneme_sayisi)
            z2 = euler * _norm_ppf(1 - 1.0 / (deneme_sayisi * np.e))
            beklenen_max_sr = sr_std * (z1 + z2)
        else:
            beklenen_max_sr = 0.0

        # DSR = P(gerçek Sharpe > deflation eşiği)
        dsr_z = (sharpe - beklenen_max_sr) / sr_std
        return float(_norm_cdf(dsr_z))

    # ── Walk-Forward Tutarlılık ───────────────────────────
    @staticmethod
    def walk_forward_tutarlilik(pencere_getirileri: List[float]) -> dict:
        """
        Walk-forward pencerelerinin ne kadarı pozitif?
        Tutarlı strateji çoğu pencerede kâr eder; tek bir pencereye bağımlı değil.
        """
        if not pencere_getirileri:
            return {"tutarlilik": 0.0, "pozitif": 0, "toplam": 0, "ort_getiri": 0.0}
        arr = np.array(pencere_getirileri)
        pozitif = int(np.sum(arr > 0))
        toplam  = len(arr)
        return {
            "tutarlilik": pozitif / toplam,
            "pozitif":    pozitif,
            "toplam":     toplam,
            "ort_getiri": float(np.mean(arr)),
            "std_getiri": float(np.std(arr)),
            "en_kotu":    float(np.min(arr)),
        }

    # ── Bootstrap Monte Carlo (fat-tail korumalı) ─────────
    @staticmethod
    def bootstrap_stres(getiriler: np.ndarray,
                         bakiye: float = 10000.0,
                         n_sim: int = VALIDATOR_BOOTSTRAP_N,
                         horizon: int = 100) -> dict:
        """
        Tarihsel getirilerden bootstrap (yeniden örnekleme) ile stres testi.
        Gaussian varsayımı YOK — gerçek dağılımın fat-tail'leri korunur.

        İşlem sırasını rastgele karıştırıp binlerce alternatif gelecek üretir.
        """
        if len(getiriler) < 20:
            return {"worst_dd_pct": 0, "medyan_dd_pct": 0,
                    "ruin_olasiligi": 0, "p5_final": 0}

        getiriler = np.asarray(getiriler, dtype=float)
        # % getiriler → çarpan (1 + r/100)
        carpanlar = 1 + getiriler / 100.0
        carpanlar = np.clip(carpanlar, 0.01, None)  # -%99 taban

        drawdownlar = []
        final_bakiyeler = []
        ruin_sayisi = 0
        RUIN_ESIK = bakiye * 0.5   # %50 kayıp = iflas
        _rng = np.random.default_rng(7)   # v24: izole RNG

        for _ in range(n_sim):
            # Bootstrap: getirileri yerine koyarak yeniden örnekle
            ornek = _rng.choice(carpanlar, size=horizon, replace=True)
            equity = bakiye * np.cumprod(ornek)
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / peak
            drawdownlar.append(float(dd.min()))
            final_bakiyeler.append(float(equity[-1]))
            if equity.min() < RUIN_ESIK:
                ruin_sayisi += 1

        drawdownlar = np.array(drawdownlar)
        final_bakiyeler = np.array(final_bakiyeler)

        return {
            "worst_dd_pct":    round(abs(np.percentile(drawdownlar, 1)) * 100, 2),
            "medyan_dd_pct":   round(abs(np.median(drawdownlar)) * 100, 2),
            "ruin_olasiligi":  round(ruin_sayisi / n_sim, 4),
            "p5_final":        round(float(np.percentile(final_bakiyeler, 5)), 2),
            "medyan_final":    round(float(np.median(final_bakiyeler)), 2),
            "hayatta_kalma":   round(1 - ruin_sayisi / n_sim, 4),
            "n_sim":           n_sim,
        }

    # ── Tarihsel Kriz Senaryoları ─────────────────────────
    @staticmethod
    def kriz_senaryolari(getiriler: np.ndarray, bakiye: float = 10000.0) -> dict:
        """
        Stratejiyi bilinen kripto kriz senaryolarında simüle et.
        Getiri dağılımına şok uygulayıp hayatta kalmayı ölçer.

        Senaryolar (kripto tarihinden kabaca):
          - COVID çöküşü (Mart 2020): -%50 ani
          - LUNA/UST (Mayıs 2022): -%40 + yüksek volatilite
          - FTX (Kasım 2022): -%25 + likidite krizi
          - Flash crash: -%15 tek mumda
        """
        if len(getiriler) < 20:
            return {}

        senaryolar = {
            "COVID_-50%":      {"sok": -0.50, "vol_carpan": 3.0},
            "LUNA_-40%":       {"sok": -0.40, "vol_carpan": 4.0},
            "FTX_-25%":        {"sok": -0.25, "vol_carpan": 2.5},
            "Flash_Crash_-15%":{"sok": -0.15, "vol_carpan": 5.0},
        }

        mu  = np.mean(getiriler) / 100.0
        sig = np.std(getiriler) / 100.0
        sonuclar = {}
        # v24 fix: izole RNG — global np.random.seed çağrısı bootstrap'in
        # rastgeleliğini ve diğer modülleri kirletmesin
        _rng = np.random.default_rng(42)

        for ad, p in senaryolar.items():
            # Şok uygula + volatiliteyi artır
            sok_getiri = p["sok"]
            sok_sonrasi = bakiye * (1 + sok_getiri)
            # Şok sonrası 20 mum yüksek-vol toparlanma denemesi
            toparlanma = _rng.normal(mu, sig * p["vol_carpan"], 20)
            equity = sok_sonrasi * np.cumprod(1 + toparlanma)
            min_equity = float(min(equity.min(), sok_sonrasi))
            hayatta = min_equity > bakiye * 0.3  # %70 kayıpta iflas sayılır
            sonuclar[ad] = {
                "min_bakiye_pct": round(min_equity / bakiye * 100, 1),
                "hayatta_kaldi":  hayatta,
            }

        hayatta_sayisi = sum(1 for s in sonuclar.values() if s["hayatta_kaldi"])
        return {
            "senaryolar":      sonuclar,
            "hayatta_kalma_orani": round(hayatta_sayisi / len(senaryolar), 2),
        }

    # ── ANA DOĞRULAMA — birleşik GO/NO-GO ─────────────────
    def dogrula(self,
                getiriler: np.ndarray,
                wf_pencere_getirileri: Optional[List[float]] = None,
                deneme_sayisi: int = 1,
                bakiye: float = 10000.0,
                min_islem: int = 30) -> StratejiKarari:
        """
        Tüm dayanıklılık testlerini çalıştır → birleşik karar.

        getiriler:              işlem bazlı % getiri serisi (zorunlu)
        wf_pencere_getirileri:  walk-forward pencere getirileri (opsiyonel)
        deneme_sayisi:          kaç strateji/param denendi (overfit deflation için)
        """
        sebepler = []
        getiriler = np.asarray(getiriler, dtype=float)

        # Yeterli veri kontrolü
        if len(getiriler) < min_islem:
            return StratejiKarari(
                onay=False, skor=0.0,
                sebepler=[f"Yetersiz veri: {len(getiriler)}/{min_islem} işlem. "
                          f"Doğrulama için daha fazla işlem geçmişi gerekli."]
            )

        skor = 0.0

        # ── 1. Deflated Sharpe (35 puan) ──────────────────
        dsr = self.deflated_sharpe(getiriler, deneme_sayisi)
        wf_t = self.walk_forward_tutarlilik(wf_pencere_getirileri or [])
        if dsr >= 0.95:
            skor += 35; sebepler.append(f"DSR={dsr:.2f} — çok güçlü istatistiksel kanıt")
        elif dsr >= 0.75:
            skor += 25; sebepler.append(f"DSR={dsr:.2f} — iyi istatistiksel kanıt")
        elif dsr >= 0.5:
            skor += 12; sebepler.append(f"DSR={dsr:.2f} — zayıf ama pozitif kanıt")
        else:
            sebepler.append(f"DSR={dsr:.2f} — yetersiz; getiriler şanstan ayırt edilemiyor")

        # ── 2. Walk-Forward Tutarlılık (25 puan) ──────────
        if wf_pencere_getirileri:
            tut = wf_t["tutarlilik"]
            if tut >= 0.70:
                skor += 25; sebepler.append(f"WF tutarlılık %{tut*100:.0f} — pencereler arası kararlı")
            elif tut >= VALIDATOR_MIN_WF_TUTARLILIK:
                skor += 15; sebepler.append(f"WF tutarlılık %{tut*100:.0f} — kabul edilebilir")
            else:
                sebepler.append(f"WF tutarlılık %{tut*100:.0f} — tek pencereye bağımlı, kırılgan")
        else:
            skor += 8  # WF verisi yoksa kısmi puan
            sebepler.append("WF verisi yok — kısmi puan")

        # ── 3. Bootstrap Stres (25 puan) ──────────────────
        stres = self.bootstrap_stres(getiriler, bakiye)
        worst_dd = stres.get("worst_dd_pct", 100)
        ruin = stres.get("ruin_olasiligi", 1.0)
        if worst_dd <= 20 and ruin <= 0.01:
            skor += 25; sebepler.append(f"Stres: worst-DD %{worst_dd:.0f}, iflas riski %{ruin*100:.1f} — sağlam")
        elif worst_dd <= VALIDATOR_MAX_DD_PCT and ruin <= 0.05:
            skor += 15; sebepler.append(f"Stres: worst-DD %{worst_dd:.0f}, iflas riski %{ruin*100:.1f} — kabul edilebilir")
        else:
            sebepler.append(f"Stres: worst-DD %{worst_dd:.0f}, iflas riski %{ruin*100:.1f} — RİSKLİ")

        # ── 4. Kriz Senaryoları (15 puan) ─────────────────
        kriz = self.kriz_senaryolari(getiriler, bakiye)
        hayatta = kriz.get("hayatta_kalma_orani", 0)
        if hayatta >= 0.75:
            skor += 15; sebepler.append(f"Kriz testleri: %{hayatta*100:.0f} senaryoda hayatta kaldı")
        elif hayatta >= 0.5:
            skor += 8; sebepler.append(f"Kriz testleri: %{hayatta*100:.0f} — orta dayanıklılık")
        else:
            sebepler.append(f"Kriz testleri: %{hayatta*100:.0f} — kriz dayanıklılığı zayıf")

        # ── BİRLEŞİK KARAR ────────────────────────────────
        onay = (
            skor >= VALIDATOR_MIN_SKOR
            and dsr >= VALIDATOR_MIN_DSR
            and worst_dd <= VALIDATOR_MAX_DD_PCT
            and ruin <= 0.10
        )

        # Sert veto koşulları (skor yüksek olsa bile)
        if ruin > 0.10:
            onay = False
            sebepler.insert(0, f"⛔ VETO: İflas olasılığı %{ruin*100:.0f} > %10")
        if worst_dd > VALIDATOR_MAX_DD_PCT:
            onay = False
            sebepler.insert(0, f"⛔ VETO: Worst-case DD %{worst_dd:.0f} > %{VALIDATOR_MAX_DD_PCT}")

        return StratejiKarari(
            onay=onay, skor=round(skor, 1), sebepler=sebepler,
            wf_sonuc={"dsr": round(dsr, 3), "tutarlilik": round(wf_t["tutarlilik"], 3)},
            mc_sonuc=stres,
            stres_sonuc={
                "worst_dd_pct": worst_dd,
                "hayatta_kalma": kriz.get("hayatta_kalma_orani", 0),
            },
        )


# ── Normal dağılım yardımcıları (scipy bağımsız) ──────────
def _norm_cdf(x: float) -> float:
    """Standart normal CDF — erf tabanlı."""
    from math import erf, sqrt
    return 0.5 * (1 + erf(x / sqrt(2)))

def _norm_ppf(p: float) -> float:
    """Standart normal ters CDF (quantile) — Acklam yaklaşımı."""
    if p <= 0: return -8.0
    if p >= 1: return 8.0
    # Beasley-Springer-Moro yaklaşımı
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = (-2 * np.log(p)) ** 0.5
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= phigh:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = (-2 * np.log(1 - p)) ** 0.5
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


# ── Singleton ─────────────────────────────────────────────
_validator: Optional[StratejiValidator] = None

def get_validator() -> StratejiValidator:
    global _validator
    if _validator is None:
        _validator = StratejiValidator()
    return _validator
