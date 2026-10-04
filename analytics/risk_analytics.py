# =========================================================
# ASTRA v30.0 — ADVANCED RISK ANALYTICS
# VaR (3 yöntem + ağırlıklı), Expected Shortfall,
# Portfolio Correlation, Volatility Regime Switching (HMM)
# =========================================================
import logging, numpy as np, pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, List
import sys; sys.path.append("..")
from config import (ANALYTICS_VAR_HIST_W, ANALYTICS_VAR_PARAM_W, ANALYTICS_VAR_MC_W,
                    PORTFOLIO_MAX_CORR, HMM_N_STATES, MC_SIMULATIONS, MC_CONFIDENCE)

log = logging.getLogger("ASTRA.RISK_ANALYTICS")

try:
    from scipy import stats as scipy_stats; SCIPY_OK = True
except ImportError: SCIPY_OK = False

try:
    from hmmlearn import hmm as hmmlearn_hmm; HMM_OK = True
except ImportError: HMM_OK = False

# ── Veri Yapıları ─────────────────────────────────────────

@dataclass
class VaRSonuc:
    sembol:             str
    gun:                int
    confidence:         float
    # Üç yöntem
    var_historical:     float   # Tarihsel simülasyon
    var_parametric:     float   # Normal dağılım varsayımı
    var_mc:             float   # Monte Carlo
    var_agirlikli:      float   # Ağırlıklı ortalama (ana değer)
    expected_shortfall: float   # CVaR — VaR'ı aşan kayıpların ortalaması
    # Dolar cinsinden
    var_usdt:           float
    es_usdt:            float
    ts:                 str = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None).isoformat())

    def telegram_str(self) -> str:
        return (f"📉 <b>VaR — {self.sembol}</b>\n"
                f"  Tarihsel  : %{self.var_historical:.3f} ({self.var_usdt:.2f}$)\n"
                f"  Parametrik: %{self.var_parametric:.3f}\n"
                f"  Monte Carlo: %{self.var_mc:.3f}\n"
                f"  ⭐ Ağırlıklı: %{self.var_agirlikli:.3f} ({self.var_usdt:.2f}$)\n"
                f"  ES (CVaR)  : %{self.expected_shortfall:.3f} ({self.es_usdt:.2f}$)")

@dataclass
class KorelesyonSonuc:
    semboller:         List[str]
    korelasyon_matrix: Dict      # {sembol1: {sembol2: corr}}
    yuksek_korelasyonlar: List   # [(s1,s2,corr)]
    portfoy_var:       float     # Portföy seviyesinde VaR
    diversification:   float     # 1 = tam çeşitlenmiş, 0 = tek hisse gibi
    yeni_poz_engel:    bool      # Yeni pozisyon açılmalı mı?
    sebep:             str

@dataclass
class RejimSonuc:
    rejim:             str       # "CALM" / "NORMAL" / "STRESSED"
    rejim_indeks:      int
    olasiliklar:       List[float]
    volatilite_son:    float
    volatilite_ort:    float
    hmm_kullanildi:    bool
    aciklama:          str


class AdvancedRiskAnalytics:
    """
    Üç katmanlı risk analizi:
    1. VaR / ES — üç yöntem + ağırlıklı birleşim
    2. Portfolio Correlation — yeni pozisyon sinyali filtresi
    3. Volatility Regime Switching — HMM tabanlı
    """

    def __init__(self):
        self._hmm_modeller: Dict = {}    # {sembol: fitted HMM}

    # ──────────────────────────────────────────────────────
    # 1. VaR & Expected Shortfall
    # ──────────────────────────────────────────────────────

    def var_hesapla(self, close: pd.Series, bakiye: float,
                     gun: int = 1,
                     confidence: float = MC_CONFIDENCE) -> VaRSonuc:
        """
        Üç yöntemle VaR hesapla, ağırlıklı ortalamasını döndür.

        Tarihsel: Geçmiş getiri dağılımından doğrudan percentile.
        Parametrik: Normal dağılım varsayımı (Cornish-Fisher düzeltmeli).
        Monte Carlo: Getiri parametrelerinden simülasyon.
        """
        sembol = str(close.name) if close.name else "PORTFOY"
        getiriler = np.log(close / close.shift(1)).dropna().values

        if len(getiriler) < 20:
            sifir = VaRSonuc(sembol=sembol, gun=gun, confidence=confidence,
                              var_historical=0, var_parametric=0, var_mc=0,
                              var_agirlikli=0, expected_shortfall=0,
                              var_usdt=0, es_usdt=0)
            return sifir

        esik = 1 - confidence
        mu   = np.mean(getiriler)
        sig  = np.std(getiriler)

        # ── Tarihsel VaR ──────────────────────────────────
        var_hist_pct = float(abs(np.percentile(getiriler * np.sqrt(gun),
                                                esik * 100))) * 100
        # Expected Shortfall (tarihsel)
        esik_deger  = np.percentile(getiriler, esik * 100)
        es_kayiplar = getiriler[getiriler <= esik_deger]
        es_pct      = float(abs(np.mean(es_kayiplar))) * 100 if len(es_kayiplar) > 0 else var_hist_pct * 1.25

        # ── Parametrik VaR (Cornish-Fisher) ───────────────
        if SCIPY_OK:
            skewness = float(scipy_stats.skew(getiriler))
            kurtosis = float(scipy_stats.kurtosis(getiriler))
            z        = scipy_stats.norm.ppf(esik)
            # Cornish-Fisher genişlemesi
            z_cf = (z + (z**2-1)*skewness/6 +
                    (z**3-3*z)*kurtosis/24 -
                    (2*z**3-5*z)*skewness**2/36)
            var_param_pct = float(abs(mu*gun - z_cf*sig*np.sqrt(gun))) * 100
        else:
            from statistics import NormalDist
            z             = NormalDist().inv_cdf(esik)
            var_param_pct = float(abs(mu*gun - z*sig*np.sqrt(gun))) * 100

        # ── Monte Carlo VaR ────────────────────────────────
        # v55: Eskiden `np.random.seed(42)` ile NumPy'ın GLOBAL RNG'si her
        # çağrıda yeniden tohumlanıyordu. İki sorun: (1) MC bacağı fiilen
        # deterministik hale gelip üç yöntemi birleştirmenin değerini
        # azaltıyordu, (2) aynı process'teki DİĞER kodun (backtest,
        # simülasyon) RNG state'i sessizce sıfırlanıyordu.
        # Artık yalnızca bu fonksiyona ait yerel bir Generator kullanılıyor.
        _rng = np.random.default_rng(42)
        sim = _rng.normal(mu*gun, sig*np.sqrt(gun), min(MC_SIMULATIONS, 5000))
        var_mc_pct = float(abs(np.percentile(sim, esik*100))) * 100

        # ── Ağırlıklı Birleşim ────────────────────────────
        w_h, w_p, w_m = ANALYTICS_VAR_HIST_W, ANALYTICS_VAR_PARAM_W, ANALYTICS_VAR_MC_W
        # Ağırlık toplamı 1.0 olmalı
        toplam = w_h + w_p + w_m
        var_agirlikli = (var_hist_pct*w_h + var_param_pct*w_p + var_mc_pct*w_m) / toplam

        # USDT değerleri
        var_usdt = bakiye * var_agirlikli / 100
        es_usdt  = bakiye * es_pct / 100

        sonuc = VaRSonuc(
            sembol=sembol, gun=gun, confidence=confidence,
            var_historical=round(var_hist_pct,4),
            var_parametric=round(var_param_pct,4),
            var_mc=round(var_mc_pct,4),
            var_agirlikli=round(var_agirlikli,4),
            expected_shortfall=round(es_pct,4),
            var_usdt=round(var_usdt,2),
            es_usdt=round(es_usdt,2),
        )
        log.info(f"[VaR] {sembol}: hist={var_hist_pct:.3f}% param={var_param_pct:.3f}% "
                 f"mc={var_mc_pct:.3f}% → ağırlıklı={var_agirlikli:.3f}% ({var_usdt:.2f}$)")
        return sonuc

    # ──────────────────────────────────────────────────────
    # 2. Portfolio Correlation
    # ──────────────────────────────────────────────────────

    def portfolio_korelasyon(self,
                              fiyat_serileri: Dict[str, pd.Series],
                              yeni_sembol: str = None,
                              yeni_yon: str = None) -> KorelesyonSonuc:
        """
        Açık pozisyonlar arasındaki korelasyonu hesaplar.
        Yeni pozisyon açılırsa mevcut portföyle uyumunu kontrol eder.
        """
        semboller = list(fiyat_serileri.keys())
        if len(semboller) < 2:
            return KorelesyonSonuc(
                semboller=semboller, korelasyon_matrix={},
                yuksek_korelasyonlar=[], portfoy_var=0,
                diversification=1.0, yeni_poz_engel=False,
                sebep="Tek sembol — korelasyon yok"
            )

        # Getiri serileri
        getiri_df = pd.DataFrame({
            s: np.log(v / v.shift(1)).dropna()
            for s, v in fiyat_serileri.items()
        }).dropna()

        if getiri_df.empty or len(getiri_df) < 10:
            return KorelesyonSonuc(
                semboller=semboller, korelasyon_matrix={},
                yuksek_korelasyonlar=[], portfoy_var=0,
                diversification=1.0, yeni_poz_engel=False,
                sebep="Yetersiz veri"
            )

        corr_matrix = getiri_df.corr()
        corr_dict   = corr_matrix.to_dict()

        # Yüksek korelasyonları bul
        yuksek = []
        for i, s1 in enumerate(semboller):
            for s2 in semboller[i+1:]:
                try:
                    c = float(corr_matrix.loc[s1, s2])
                    if abs(c) >= PORTFOLIO_MAX_CORR:
                        yuksek.append((s1, s2, round(c, 4)))
                except (ValueError, AttributeError, TypeError):
                    pass

        # Portföy VaR (çeşitlendirme etkisiyle)
        ortalama_var = float(getiri_df.std().mean()) * 100
        if len(semboller) > 1:
            cov = getiri_df.cov().values
            n   = len(semboller)
            agirliklar = np.ones(n) / n
            portfoy_var_pct = float(np.sqrt(agirliklar @ cov @ agirliklar)) * 100 * 1.645
        else:
            portfoy_var_pct = ortalama_var

        # Diversification ratio: portföy riski / ağırlıklı ortalama risk
        diversification = (1 - portfoy_var_pct / max(ortalama_var, 1e-10)
                           ) if ortalama_var > 0 else 1.0
        diversification = round(min(max(diversification, 0), 1), 4)

        # Yeni pozisyon engel kontrolü
        engel = False; sebep = "OK"
        if yeni_sembol and yeni_sembol in corr_matrix.columns:
            for mevcut in semboller:
                if mevcut == yeni_sembol: continue
                try:
                    c = abs(float(corr_matrix.loc[yeni_sembol, mevcut]))
                    if c >= PORTFOLIO_MAX_CORR:
                        engel = True
                        sebep = (f"{yeni_sembol}↔{mevcut} korelasyon "
                                 f"{c:.2f} ≥ {PORTFOLIO_MAX_CORR} eşiği")
                        break
                except (AttributeError, ValueError, TypeError):
                    pass

        log.info(f"[KORREL] {len(semboller)} sembol | "
                 f"Yüksek korrel: {len(yuksek)} | "
                 f"Portföy VaR: %{portfoy_var_pct:.3f} | "
                 f"Div: {diversification:.3f} | "
                 f"Engel: {engel}")

        return KorelesyonSonuc(
            semboller=semboller,
            korelasyon_matrix=corr_dict,
            yuksek_korelasyonlar=yuksek,
            portfoy_var=round(portfoy_var_pct, 4),
            diversification=diversification,
            yeni_poz_engel=engel,
            sebep=sebep,
        )

    def korelasyon_sinyal_filtresi(self,
                                    yeni_sembol: str,
                                    acik_pozlar: list,
                                    fiyat_getir_fn) -> tuple:
        """
        Yeni pozisyon açılmadan önce portföy korelasyonunu kontrol eder.
        Döner: (izin_var: bool, sebep: str)
        """
        if not acik_pozlar:
            return True, "Açık pozisyon yok"

        fiyat_serileri = {}
        for poz in acik_pozlar:
            sembol = poz.get("sembol", "")
            try:
                df = fiyat_getir_fn(sembol, period="7d", interval="1h")
                if df is not None and "Close" in df.columns:
                    fiyat_serileri[sembol] = df["Close"]
            except (ValueError, AttributeError, TypeError, OSError) as e:
                log.warning(f"[KORREL] {sembol} fiyat alınamadı: {e}")

        if yeni_sembol not in fiyat_serileri:
            try:
                df = fiyat_getir_fn(yeni_sembol, period="7d", interval="1h")
                if df is not None and "Close" in df.columns:
                    fiyat_serileri[yeni_sembol] = df["Close"]
            except (OSError, ValueError, AttributeError): pass

        if not fiyat_serileri:
            return True, "Fiyat verisi alınamadı — izin verildi"

        sonuc = self.portfolio_korelasyon(fiyat_serileri, yeni_sembol)
        if sonuc.yeni_poz_engel:
            return False, sonuc.sebep
        return True, "Korelasyon OK"

    # ──────────────────────────────────────────────────────
    # 3. Volatility Regime Switching (HMM)
    # ──────────────────────────────────────────────────────

    def volatilite_rejimi(self, close: pd.Series,
                           sembol: str = "BTC") -> RejimSonuc:
        """
        Piyasanın volatilite rejimini tespit eder.
        HMM (Gaussian Hidden Markov Model) kullanır.
        hmmlearn kurulu değilse threshold tabanlı fallback.

        Rejimler:
          0 = CALM    (düşük volatilite)
          1 = NORMAL
          2 = STRESSED (yüksek volatilite)
        """
        getiriler = np.log(close / close.shift(1)).dropna().values
        if len(getiriler) < 30:
            return RejimSonuc(rejim="NORMAL", rejim_indeks=1,
                               olasiliklar=[0.2,0.6,0.2],
                               volatilite_son=0, volatilite_ort=0,
                               hmm_kullanildi=False, aciklama="Yetersiz veri")

        vol_son = float(np.std(getiriler[-20:])) * 100
        vol_ort = float(np.std(getiriler)) * 100

        # ── HMM ile ───────────────────────────────────────
        if HMM_OK:
            try:
                model_key = sembol
                if model_key not in self._hmm_modeller:
                    model = hmmlearn_hmm.GaussianHMM(
                        n_components=HMM_N_STATES,
                        covariance_type="full",
                        n_iter=100, random_state=42, verbose=False
                    )
                    X = getiriler.reshape(-1, 1)
                    model.fit(X)
                    # Durumları volatiliteye göre sırala (0=düşük 2=yüksek)
                    std_per_state = [float(np.sqrt(model.covars_[i][0][0]))
                                     for i in range(HMM_N_STATES)]
                    siralama = np.argsort(std_per_state)
                    model._state_labels = {
                        siralama[0]: "CALM",
                        siralama[1]: "NORMAL",
                        siralama[2]: "STRESSED",
                    } if HMM_N_STATES == 3 else {}
                    self._hmm_modeller[model_key] = model

                model = self._hmm_modeller[model_key]
                X     = getiriler.reshape(-1, 1)
                son_durum  = int(model.predict(X)[-1])
                olasiliklar = model.predict_proba(X)[-1].tolist()

                etiket = model._state_labels.get(son_durum, "NORMAL")
                log.info(f"[HMM] {sembol}: rejim={etiket} "
                         f"olasılıklar={[round(p,2) for p in olasiliklar]} "
                         f"vol_son={vol_son:.4f}%")
                return RejimSonuc(
                    rejim=etiket, rejim_indeks=son_durum,
                    olasiliklar=[round(p,4) for p in olasiliklar],
                    volatilite_son=round(vol_son,4),
                    volatilite_ort=round(vol_ort,4),
                    hmm_kullanildi=True,
                    aciklama=f"HMM {HMM_N_STATES} durum"
                )
            except (ValueError, AttributeError, TypeError, OSError) as e:
                log.warning(f"[HMM] {sembol} HMM hatası: {e} — threshold fallback")

        # ── Threshold fallback ────────────────────────────
        oran = vol_son / max(vol_ort, 1e-10)
        if oran < 0.7:
            rejim = "CALM"; idx = 0; olasilik = [0.7, 0.2, 0.1]
        elif oran > 1.5:
            rejim = "STRESSED"; idx = 2; olasilik = [0.1, 0.2, 0.7]
        else:
            rejim = "NORMAL"; idx = 1; olasilik = [0.15, 0.7, 0.15]

        return RejimSonuc(rejim=rejim, rejim_indeks=idx,
                          olasiliklar=olasilik,
                          volatilite_son=round(vol_son,4),
                          volatilite_ort=round(vol_ort,4),
                          hmm_kullanildi=False,
                          aciklama="Threshold tabanlı")

    # ──────────────────────────────────────────────────────
    # Birleşik Analiz
    # ──────────────────────────────────────────────────────

    def tam_analiz(self, sembol: str, close: pd.Series,
                    bakiye: float,
                    fiyat_serileri: Dict[str, pd.Series] = None,
                    acik_pozlar: list = None) -> dict:
        """VaR + ES + Korelasyon + Rejim → DB'ye kaydet → döndür."""
        close.name = sembol

        var_sonuc   = self.var_hesapla(close, bakiye)
        rejim_sonuc = self.volatilite_rejimi(close, sembol)

        korrel_sonuc = None
        if fiyat_serileri and len(fiyat_serileri) > 1:
            korrel_sonuc = self.portfolio_korelasyon(fiyat_serileri)

        # DB'ye kaydet
        try:
            from data.db_manager import risk_analytics_kaydet
            risk_analytics_kaydet(
                sembol=sembol,
                var_hist=var_sonuc.var_historical,
                var_param=var_sonuc.var_parametric,
                var_mc=var_sonuc.var_mc,
                var_agirlikli=var_sonuc.var_agirlikli,
                expected_shortfall=var_sonuc.expected_shortfall,
                portfolio_corr=korrel_sonuc.korelasyon_matrix if korrel_sonuc else {},
                volatility_regime=rejim_sonuc.rejim,
                drawdown_pct=0,
            )
        except (ValueError, AttributeError, TypeError, OSError) as e:
            log.warning(f"[ANALYTICS] DB kayıt hatası: {e}")

        # Tavsiyeler
        tavsiyeler = self._tavsiyeler(var_sonuc, rejim_sonuc, korrel_sonuc)

        return {
            "var":           var_sonuc,
            "rejim":         rejim_sonuc,
            "korelasyon":    korrel_sonuc,
            "tavsiyeler":    tavsiyeler,
            "ts":            datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        }

    def _tavsiyeler(self, var, rejim, korrel) -> list:
        t = []
        if var.var_agirlikli > 3:
            t.append("⚠️ VaR yüksek — pozisyon büyüklüğünü azalt")
        if var.expected_shortfall > var.var_agirlikli * 1.5:
            t.append("⚠️ ES/VaR oranı yüksek — kuyruk riski var")
        if rejim.rejim == "STRESSED":
            t.append("🌊 Stres rejimi — kaldıracı düşür, pozisyon açma")
        elif rejim.rejim == "CALM":
            t.append("✅ Sakin rejim — normal işlem yapılabilir")
        if korrel and korrel.yuksek_korelasyonlar:
            ciftler = ", ".join(f"{a}↔{b}" for a,b,_ in korrel.yuksek_korelasyonlar[:3])
            t.append(f"⚠️ Yüksek korelasyon: {ciftler}")
        if korrel and korrel.diversification < 0.2:
            t.append("⚠️ Portföy çeşitliliği düşük")
        if not t:
            t.append("✅ Risk seviyeleri normal")
        return t

    def telegram_raporu(self, analiz: dict) -> str:
        var = analiz["var"]; rejim = analiz["rejim"]
        korrel = analiz.get("korelasyon")
        tavsiyeler = "\n".join(analiz.get("tavsiyeler",[]))
        rejim_emoji = {"CALM":"🌊","NORMAL":"📊","STRESSED":"🚨"}.get(rejim.rejim,"❓")
        korrel_str = ""
        if korrel and korrel.yuksek_korelasyonlar:
            korrel_str = "\n".join(f"  {a}↔{b}: {c:.2f}"
                                    for a,b,c in korrel.yuksek_korelasyonlar[:5])
        korelasyon_text = (
            f"🔗 Korelasyon:\n{korrel_str}"
            if korrel_str
            else "🔗 Korelasyon: Yok"
        )

        return (
            f"📊 <b>ADVANCED RISK ANALYTICS</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{var.telegram_str()}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{rejim_emoji} <b>Volatilite Rejimi: {rejim.rejim}</b>\n"
            f"  Son vol: %{rejim.volatilite_son:.4f}\n"
            f"  Ort vol: %{rejim.volatilite_ort:.4f}\n"
            f"  HMM: {'Evet' if rejim.hmm_kullanildi else 'Hayır (threshold)'}\n"
            f"  Olasılıklar: {[round(p,2) for p in rejim.olasiliklar]}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{korelasyon_text}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 {tavsiyeler}"
        )


# Singleton
_analytics_instance: Optional[AdvancedRiskAnalytics] = None

def get_analytics() -> AdvancedRiskAnalytics:
    global _analytics_instance
    if _analytics_instance is None:
        _analytics_instance = AdvancedRiskAnalytics()
    return _analytics_instance
