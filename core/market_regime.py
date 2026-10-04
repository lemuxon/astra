# =========================================================
# ASTRA v30.0 — GELIŞMIŞ MARKET REGIME DETECTION
# ranging, volatility crush, breakout, chop, fake breakout,
# low liquidity, news volatility filtreleri
# =========================================================
import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import sys; sys.path.append("..")

log = logging.getLogger("ASTRA.REGIME")

@dataclass
class RegimeAnaliz:
    rejim:           str    # Ana rejim
    alt_rejim:       str    # Alt kategori
    chop_index:      float  # 0-100, >61 = chop
    volatility_crush: bool  # Volatilite sıkışması
    breakout_setup:  bool   # Kırılım hazırlığı
    fake_breakout:   bool   # Sahte kırılım tespiti
    low_liquidity:   bool   # Düşük hacim
    islem_yapilabilir: bool # Bu rejimde işlem açılmalı mı?
    guven:           float  # Rejim güveni 0-1
    aciklama:        str


class GelismisRegimeDetector:
    """
    v14 gelişmiş rejim tespiti.
    Sadece 'TREND/RANGE' değil, 8 farklı durum.
    """

    def tespit_et(self, df: pd.DataFrame, close: pd.Series,
                   volume: Optional[pd.Series] = None) -> RegimeAnaliz:
        try:
            return self._analiz(df, close, volume)
        except Exception as e:
            log.debug(f"[REGIME] Analiz hatası: {e}")
            return RegimeAnaliz("RANGE","NORMAL",50,False,False,False,False,True,0.5,"Fallback")

    def _analiz(self, df: pd.DataFrame, close: pd.Series,
                 volume: Optional[pd.Series] = None) -> RegimeAnaliz:
        if len(close) < 30:
            return RegimeAnaliz("RANGE","NORMAL",50,False,False,False,False,True,0.5,"Yetersiz veri")

        # ── Temel hesaplamalar ────────────────────────────
        ema20  = close.ewm(span=20).mean()
        ema50  = close.ewm(span=50).mean()
        ema200 = close.ewm(span=200).mean() if len(close) >= 200 else ema50
        atr    = self._atr(df)
        son_close  = float(close.iloc[-1])
        son_ema20  = float(ema20.iloc[-1])
        son_ema50  = float(ema50.iloc[-1])
        son_ema200 = float(ema200.iloc[-1])

        # ── Chop Index ────────────────────────────────────
        # Yüksek chop = yatay, düşük = trendli
        chop = self._chop_index(df, close, atr)

        # ── Volatility Crush ─────────────────────────────
        # ATR son 5 bar ortalaması son 20 bar ortalamasının %50 altındaysa
        atr_kisa = float(atr.iloc[-5:].mean()) if len(atr) >= 5 else float(atr.iloc[-1])
        atr_uzun = float(atr.iloc[-20:].mean()) if len(atr) >= 20 else atr_kisa
        vol_crush = atr_kisa < atr_uzun * 0.5

        # ── Breakout Setup ────────────────────────────────
        # BB daraldıysa ve fiyat band kenarına yakınsa
        bb_std = close.rolling(20).std()
        bb_bw  = float((bb_std * 4 / ema20).iloc[-1]) if len(bb_std) >= 20 else 0
        breakout_setup = bb_bw < 0.02 and vol_crush   # sıkışma

        # ── Fake Breakout ─────────────────────────────────
        # Son 3 bar yüksek hacimle kırılım ama geri döndü
        fake_breakout = False
        if len(close) >= 5 and volume is not None:
            ort_vol  = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else 0
            son_vol  = float(volume.iloc[-1])
            yuzde_deg = (son_close - float(close.iloc[-3])) / float(close.iloc[-3]) * 100
            # Yüksek hacimle hareket etti ama %0.5'ten az kaldı → fake
            if son_vol > ort_vol * 2 and abs(yuzde_deg) < 0.5:
                fake_breakout = True

        # ── Low Liquidity ─────────────────────────────────
        low_liq = False
        if volume is not None and len(volume) >= 20:
            ort_vol = float(volume.iloc[-20:].mean())
            son_vol = float(volume.iloc[-1])
            low_liq = son_vol < ort_vol * 0.3

        # ── Ana Rejim Belirleme ───────────────────────────
        ema_yukari = son_ema20 > son_ema50 > son_ema200
        ema_asagi  = son_ema20 < son_ema50 < son_ema200
        fiyat_over_200 = son_close > son_ema200

        if chop > 61.8:          # Chop eşiği: Fibonacci 61.8
            rejim = "RANGE"
            alt   = "CHOP"
            guven = min((chop - 61.8) / 38.2, 1.0)
        elif ema_yukari and fiyat_over_200:
            rejim = "TREND_UP"
            alt   = "STRONG" if chop < 40 else "WEAK"
            guven = max(0, (61.8 - chop) / 61.8)
        elif ema_asagi and not fiyat_over_200:
            rejim = "TREND_DOWN"
            alt   = "STRONG" if chop < 40 else "WEAK"
            guven = max(0, (61.8 - chop) / 61.8)
        elif son_close < son_ema200 * 0.95:
            rejim = "BEAR"
            alt   = "CRASH" if (son_ema20 - son_ema200)/son_ema200 < -0.1 else "NORMAL"
            guven = 0.7
        else:
            rejim = "RANGE"
            alt   = "NORMAL"
            guven = 0.5

        # Volatility override
        if atr_uzun > 0 and atr_kisa / atr_uzun > 2.5:
            rejim = "VOLATILE"
            alt   = "NEWS" if low_liq else "SPIKE"
            guven = 0.8

        # ── İşlem yapılabilir mi? ─────────────────────────
        islem_yap = True
        nedenler  = []

        if fake_breakout:
            islem_yap = False; nedenler.append("Fake breakout")
        if low_liq and rejim != "TREND_UP":
            islem_yap = False; nedenler.append("Düşük likidite")
        if chop > 70 and rejim == "RANGE":
            islem_yap = False; nedenler.append("Aşırı chop")
        if rejim == "VOLATILE" and alt == "NEWS":
            islem_yap = False; nedenler.append("Haber volatilitesi")

        aciklama = f"{rejim}/{alt} chop:{chop:.1f}"
        if nedenler:
            aciklama += f" | ❌ {', '.join(nedenler)}"

        return RegimeAnaliz(
            rejim=rejim, alt_rejim=alt,
            chop_index=round(chop, 1),
            volatility_crush=vol_crush,
            breakout_setup=breakout_setup,
            fake_breakout=fake_breakout,
            low_liquidity=low_liq,
            islem_yapilabilir=islem_yap,
            guven=round(guven, 2),
            aciklama=aciklama,
        )

    def _atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        try:
            h = df["High"]; l = df["Low"]; c = df["Close"]
            tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
            return tr.rolling(period).mean()
        except Exception:
            return pd.Series(0, index=df.index)

    def _chop_index(self, df: pd.DataFrame, close: pd.Series,
                     atr: pd.Series, period: int = 14) -> float:
        """
        Chop Index: 100 * log10(sum(ATR,n) / (highest-lowest)) / log10(n)
        >61.8 = chop, <38.2 = trend
        """
        try:
            n = period
            if len(close) < n + 1:
                return 50.0
            son_n   = close.iloc[-n:]
            atr_son = atr.iloc[-n:].sum()
            yuksek  = float(son_n.max())
            dusuk   = float(son_n.min())
            if yuksek == dusuk or atr_son == 0:
                return 50.0
            import math
            # Standart Chop Index: 100 * log10(ATR_sum / range) / log10(n)
            if atr_son <= 0 or (yuksek - dusuk) <= 0:
                return 50.0
            chop = 100 * math.log10(atr_son / (yuksek - dusuk)) / math.log10(n)
            return min(max(float(chop), 0), 100)
        except Exception:
            return 50.0


_detector = None
def get_regime_detector() -> GelismisRegimeDetector:
    global _detector
    if _detector is None:
        _detector = GelismisRegimeDetector()
    return _detector


# =========================================================
# v19: HMM (Hidden Markov Model) Rejim Dedektörü
# Kural bazlı rejim tespitini istatistiksel öğrenmeyle destekler.
# hmmlearn yoksa sessizce devre dışı kalır.
# 3 gizli durum: CALM / TRENDING / STRESSED
# =========================================================
import json, os, time as _time
from pathlib import Path

_HMM_MODEL_PATH  = "saved_models/hmm_rejim.pkl"
_HMM_SCALER_PATH = "saved_models/hmm_scaler.pkl"
_HMM_CACHE: dict = {}   # {sembol: (ts, rejim)}
_HMM_CACHE_TTL   = 120  # 2 dakika

try:
    from hmmlearn import hmm as _hmm_lib
    import pickle
    from sklearn.preprocessing import StandardScaler
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False

_DURUM_ETIKETLERI = {0: "CALM", 1: "TRENDING", 2: "STRESSED"}


class HMMRegimDetector:
    """
    Gaussian HMM ile gizli piyasa rejimi tespiti.
    Feature'lar: log_return, volatility, volume_ratio, atr_pct

    Eğitim: 100+ günlük saatlik veriyle otomatik.
    Predict: son N mumdan anlık rejim tahmini.
    """
    def __init__(self, n_states: int = 3):
        self.n_states  = n_states
        self._model    = None
        self._scaler   = None
        self._egitildi = False
        self._egitim_ts= 0.0
        self._yukle()

    def _yukle(self):
        if not HMM_AVAILABLE: return
        try:
            if os.path.exists(_HMM_MODEL_PATH):
                with open(_HMM_MODEL_PATH, "rb") as f:
                    self._model = pickle.load(f)
                with open(_HMM_SCALER_PATH, "rb") as f:
                    self._scaler = pickle.load(f)
                self._egitildi = True
                log.info("[HMM] Model yüklendi.")
        except Exception as e:
            log.warning(f"[HMM] Model yüklenemedi: {e}")

    def _kaydet(self):
        if not HMM_AVAILABLE or self._model is None: return
        try:
            Path("saved_models").mkdir(exist_ok=True)
            with open(_HMM_MODEL_PATH, "wb") as f:
                pickle.dump(self._model, f)
            with open(_HMM_SCALER_PATH, "wb") as f:
                pickle.dump(self._scaler, f)
        except Exception as e:
            log.warning(f"[HMM] Kayıt hatası: {e}")

    def _feature_cikar(self, close: pd.Series,
                        volume: pd.Series = None,
                        atr: pd.Series = None) -> np.ndarray:
        """4 feature: log_ret, rolling_vol, volume_ratio, atr_pct"""
        log_ret    = np.log(close / close.shift(1)).fillna(0)
        rol_vol    = log_ret.rolling(12).std().fillna(0)

        if volume is not None and len(volume) == len(close):
            vol_ort    = volume.rolling(20).mean().replace(0, 1e-10)
            vol_ratio  = (volume / vol_ort).clip(0.1, 10).fillna(1)
        else:
            vol_ratio = pd.Series(1.0, index=close.index)

        if atr is not None and len(atr) == len(close):
            atr_pct = (atr / close.replace(0, 1e-10) * 100).fillna(0)
        else:
            atr_pct = rol_vol * 100

        feat = pd.DataFrame({
            "log_ret":   log_ret,
            "vol":       rol_vol,
            "vol_ratio": vol_ratio,
            "atr_pct":   atr_pct,
        }).dropna()
        return feat.values, feat.index

    def egit(self, close: pd.Series,
              volume: pd.Series = None,
              atr: pd.Series = None) -> bool:
        """HMM'i verilen seri üzerinde eğit ve kaydet."""
        if not HMM_AVAILABLE:
            log.debug("[HMM] hmmlearn yüklü değil, atlandı.")
            return False
        if len(close) < 200:
            log.warning("[HMM] Eğitim için yetersiz veri (<200 mum)")
            return False
        try:
            feat, _ = self._feature_cikar(close, volume, atr)
            scaler  = StandardScaler()
            feat_s  = scaler.fit_transform(feat)

            model = _hmm_lib.GaussianHMM(
                n_components  = self.n_states,
                covariance_type = "full",
                n_iter        = 100,
                random_state  = 42,
                verbose       = False,
            )
            model.fit(feat_s)
            self._model    = model
            self._scaler   = scaler
            self._egitildi = True
            self._egitim_ts= _time.time()
            self._kaydet()
            log.info(f"[HMM] Eğitim tamamlandı. "
                     f"Convergence={model.monitor_.converged} "
                     f"Log-likelihood={model.score(feat_s):.2f}")
            return True
        except Exception as e:
            log.error(f"[HMM] Eğitim hatası: {e}")
            return False

    def rejim_tahmin(self, close: pd.Series,
                      volume: pd.Series = None,
                      atr: pd.Series = None,
                      son_n: int = 50) -> dict:
        """
        Son N mumdan anlık HMM rejim tahmini.
        Döner: {rejim: str, durum_id: int, olasilik: float, detay: dict}
        """
        if not HMM_AVAILABLE or not self._egitildi or self._model is None:
            return {"rejim": "UNKNOWN", "durum_id": -1,
                    "olasilik": 0.0, "hmm_aktif": False}

        try:
            close_son = close.iloc[-son_n:] if len(close) >= son_n else close
            vol_son   = volume.iloc[-son_n:]  if volume is not None and len(volume) >= son_n else volume
            atr_son   = atr.iloc[-son_n:]    if atr is not None and len(atr) >= son_n else atr

            feat, _ = self._feature_cikar(close_son, vol_son, atr_son)
            if len(feat) < 5:
                return {"rejim": "UNKNOWN", "durum_id": -1, "olasilik": 0.0, "hmm_aktif": True}

            feat_s    = self._scaler.transform(feat)
            durumlar  = self._model.predict(feat_s)
            posteriors= self._model.predict_proba(feat_s)

            son_durum = int(durumlar[-1])
            son_prob  = float(posteriors[-1][son_durum])

            # Son 5 durumun modu (kararlılık)
            son5      = durumlar[-5:]
            mod_durum = int(np.bincount(son5).argmax())

            etiket = _DURUM_ETIKETLERI.get(mod_durum, "UNKNOWN")

            # Her durumun ortalama volatilitesine göre etiket ata
            # (eğitimden bağımsız anlamsal etiketleme)
            durum_ozet = {}
            for d in range(self.n_states):
                mask = durumlar == d
                if mask.sum() > 0:
                    durum_ozet[_DURUM_ETIKETLERI.get(d, str(d))] = {
                        "sayi":    int(mask.sum()),
                        "son_mu":  d == son_durum,
                    }

            return {
                "rejim":     etiket,
                "durum_id":  mod_durum,
                "olasilik":  round(son_prob, 3),
                "hmm_aktif": True,
                "detay":     durum_ozet,
            }
        except Exception as e:
            log.warning(f"[HMM] Tahmin hatası: {e}")
            return {"rejim": "UNKNOWN", "durum_id": -1, "olasilik": 0.0, "hmm_aktif": True}

    def piyasa_rejimi_birlestir(self, kural_rejim: str, hmm_sonuc: dict) -> str:
        """
        Kural bazlı rejim + HMM rejimini birleştir.
        HMM STRESSED → kural rejimi ne olursa olsun VOLATILE override.
        HMM CALM + kural TREND → güvenilir TREND.
        """
        if not hmm_sonuc.get("hmm_aktif"):
            return kural_rejim
        hmm_rejim = hmm_sonuc.get("rejim", "UNKNOWN")
        olasilik  = hmm_sonuc.get("olasilik", 0.0)

        if hmm_rejim == "STRESSED" and olasilik > 0.7:
            return "VOLATILE"   # Güçlü stres sinyali → override
        if hmm_rejim == "CALM" and kural_rejim in ("RANGE", "TREND_UP", "TREND_DOWN"):
            return kural_rejim  # HMM sakin, kural güvenilir → kural kalsın
        # v58 K-36: BURADA "TREND_UP" DÖNÜLÜYORDU — YÖN UYDURMASI.
        # HMM'in durumları volatilite/hacim üzerinden etiketlenir
        # (_DURUM_ETIKETLERI = {0:CALM, 1:TRENDING, 2:STRESSED}); "TRENDING"
        # bir TREND OLDUĞUNU söyler, YÖNÜNÜ söylemez. Kod yönü yukarı
        # varsayıyordu — düşen bir trend de aynı HMM durumunu üretir.
        #
        # Etkisi (ölçüldü, 3 yıl 4h 5 sembol, 1500 örnek): bu dal
        # örneklerin yalnızca %0.1'inde tetikleniyor (TRENDING 1/1500),
        # yani BUGÜN pratikte ölü. Ama HMM yeniden eğitilince canlanır ve
        # o zaman her RANGE barı sessizce TREND_UP olur: ai_score'daki
        # RANGE cezası (−1) kalkar, sl_tp_hesapla RANGE çarpanları yerine
        # TREND çarpanlarını kullanır. İkisi de ALIŞ yönünde kayar.
        #
        # ⚠️ GEREKÇE PERFORMANS DEĞİL, DOĞRULUK (K-26'nın aynısı):
        # ölçülebilir bir kazanç iddiası YOK, dal zaten tetiklenmiyor.
        # Yönsüz bir sinyalden yön üretmek yapısal hatadır.
        #
        # Doğru davranış: yön bilinmiyorsa UYDURMA — kural rejimi kalsın.
        # (Yön üretmek isteniyorsa +DI/−DI gerekir; bu fonksiyonun
        #  elinde o veri yok, dolayısıyla burada yapılamaz.)
        return kural_rejim


_hmm_detector: HMMRegimDetector = None

def get_hmm_detector() -> HMMRegimDetector:
    global _hmm_detector
    if _hmm_detector is None:
        _hmm_detector = HMMRegimDetector(n_states=3)
    return _hmm_detector
