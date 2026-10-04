# =========================================================
# ASTRA v30.0 — ONLINE LEARNING ENGINE
# River kütüphanesi ile per-mum anlık model güncellemesi.
# Batch retrain (saatlik) ile paralel çalışır — birbirini
# bloklamaz, ikisi de aktiftir.
#
# Neden Online Learning?
#   Batch model: 500 örnek topla → 30s eğit → deploy
#   Online model: Her mum kapanışında 1ms güncelleme
#   Rejim geçişlerinde batch modelden 5-10x daha hızlı uyum.
#
# Mimari:
#   - Per-coin Hoeffding Adaptive Tree (ADWIN drift tespiti dahil)
#   - Adaptive Standardization (online scaler)
#   - Batch model tahminini online model ile birleştir (ensemble)
#   - Drift dedektörü: ADWIN
# =========================================================
import logging, os, pickle, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import numpy as np

log = logging.getLogger("ASTRA.ONLINE")

# ── v58 (K-70): DİZİN İZOLASYONA UYAR ───────────────────────
# Eskiden sabit koduydu ve `tests/izolasyon.py`'nin MODEL_DIR
# yönlendirmesini GÖRMÜYORDU. Sonuç: test paketi her koşuşta ÜRETİM
# `saved_models/online/` dizinine yazıyordu (kanıt: `online_TESTLEARN.pkl`,
# `test_denetim_duzeltmeleri.py` üretiyor). K-1 ve K-21 ile aynı sınıf.
#
# K-65 (her eğitimde kaydet) bu sızıntıyı BÜYÜTTÜ: eskiden yalnızca
# egitim%100==0 anında yazılıyordu, artık her adımda.
#
# Dizin ÇAĞRI ANINDA çözülür — import anında değil. `izole_et()` proje
# modüllerinden ÖNCE çalışsa da, geç import edilen bir modül sabit yolu
# çoktan yakalamış olabilirdi.
_ONLINE_MODEL_DIR = "saved_models/online"   # yalnızca varsayılan


def _online_dizin() -> str:
    """Online model dizini. MODEL_DIR ayarlıysa onun altında."""
    taban = os.getenv("MODEL_DIR") or "saved_models"
    yol = os.path.join(taban, "online")
    try:
        Path(yol).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning(f"[ONLINE] Dizin oluşturulamadı ({yol}): {e}")
    return yol

try:
    from river import tree, preprocessing, drift, metrics, ensemble, linear_model
    # ── v58 (K-45): river 0.15+ AdaptiveRandomForestClassifier'ı
    # `river.ensemble`'dan `river.forest.ARFClassifier`'a TAŞIDI.
    # Eski isim çağrıldığı için OnlineLearner her kurulumda
    # AttributeError atıyordu ve istisna main.py'da `log.debug` ile
    # yutuluyordu → online öğrenme HİÇ çalışmadı, kimse fark etmedi.
    # (Kurulu sürüm: river 0.21.2 — `river.ensemble`'da hiçbir Forest
    #  sınıfı kalmamış.)
    try:
        from river.forest import ARFClassifier as _ARF      # river >= 0.15
    except ImportError:                                      # eski sürümler
        _ARF = getattr(ensemble, "AdaptiveRandomForestClassifier", None)
    RIVER_AVAILABLE = _ARF is not None
    if _ARF is None:
        logging.getLogger("ASTRA").error(
            "[ONLINE] river kurulu ama uyumlu ARF sınıfı bulunamadı — "
            "online öğrenme DEVRE DIŞI")
    log.info("[ONLINE] River kütüphanesi mevcut — online learning aktif.")
except ImportError:
    RIVER_AVAILABLE = False
    log.warning("[ONLINE] River yüklü değil. 'pip install river' ile ekleyin. "
                "Online learning devre dışı — sadece batch modeller çalışacak.")


def etiket_uret(bar_ts, onceki_bar_ts, son_close, onceki_close):
    """Online öğrenme etiketi — YALNIZCA yeni kapanmış bar geldiyse üretilir.

    ── v58 (K-64): UYDURMA ETİKET (K-17'nin online ikizi) ───────────
    Eski satır içi kural şuydu:
        _gercek = 1 if son_close > onceki_close > 0 else 0 if onceki_close > 0 else None
    Yani her analiz turunda bir etiket üretiyordu. Ama K-16'dan beri
    `son_close` KAPANMIŞ barın kapanışıdır ve 4h ufkunda 4 saat sabit
    kalır; tur ~1 dk'da bir döner. Sonuç: aynı bar defalarca
    "fiyat yükselmedi (0)" diye öğretiliyordu.

    ÖLÇÜM (2026-09-06, canlı bot, 5 dk, 20 örnekleme):
        son_close değişimi : 0   (5 sembolün hepsinde)
        online eğitim adımı: +6  / sembol
        → 6 adımın 6'sı da uydurma "0"
    Oran: ~288 eğitim adımına 1 gerçek etiket.

    Kimlikten bakılır (bar_ts), değerden değil: iki farklı bar aynı
    fiyattan kapanabilir; o meşru "0" etiketi kaybolmamalı.

    Döner: 1 (yükseldi) / 0 (yükselmedi) / None (öğrenme — yeni bar yok)
    """
    if bar_ts is None or onceki_bar_ts is None:
        return None                      # ilk tur: kıyaslanacak bar yok
    if bar_ts == onceki_bar_ts:
        return None                      # aynı bar — yeni bilgi yok
    if not (onceki_close and onceki_close > 0):
        return None                      # referans fiyat yok
    return 1 if son_close > onceki_close else 0


class OnlineLearner:
    """
    Per-coin online öğrenme motoru.

    Her yeni kapanan mum:
      1. Feature'ları al (coin_analiz cache'inden)
      2. Bir önceki mumun gerçek sonucunu hesapla (fiyat arttı mı?)
      3. Model.learn_one(x, y) — anlık güncelleme
      4. Model.predict_proba_one(x) — sonraki mum için tahmin

    Batch model tahminiyle ağırlıklı birleştirme:
      final_prob = online_ağırlık × online_prob + (1 - online_ağırlık) × batch_prob
    """

    def __init__(self, sembol: str,
                 online_agirlik: float = 0.35,
                 drift_esik: float = 0.002):
        self.sembol        = sembol
        self.online_agirlik= online_agirlik   # Online modelin blend ağırlığı
        self._lock         = threading.Lock()
        self._egitim_sayisi= 0
        self._drift_sayisi = 0
        self._accuracy     = metrics.Accuracy() if RIVER_AVAILABLE else None
        self._son_x: Optional[dict] = None    # Bir önceki X (label için)
        self._son_fiyat: float      = 0.0

        if RIVER_AVAILABLE:
            # Hoeffding Adaptive Tree — ADWIN drift dedektörü dahil
            # v58 (K-45): sürümden bağımsız sınıf (bkz. import bloğu)
            self._model = _ARF(
                n_models=5,
                max_features="sqrt",
                drift_detector=drift.ADWIN(delta=drift_esik),
                seed=42,
            )
            self._scaler = preprocessing.AdaptiveStandardScaler()
            self._drift_detector = drift.ADWIN(delta=drift_esik)
        else:
            self._model  = None
            self._scaler = None
            self._drift_detector = None

        self._yukle()
        log.info(f"[ONLINE/{sembol}] Başlatıldı — "
                 f"river={'✅' if RIVER_AVAILABLE else '❌'} "
                 f"eğitim={self._egitim_sayisi}")

    def _yukle(self):
        if not RIVER_AVAILABLE: return
        path = os.path.join(_online_dizin(), f"online_{self.sembol}.pkl")
        try:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    state = pickle.load(f)
                self._model         = state.get("model", self._model)
                self._scaler        = state.get("scaler", self._scaler)
                self._egitim_sayisi = state.get("egitim", 0)
                self._drift_sayisi  = state.get("drift",  0)
                log.info(f"[ONLINE/{self.sembol}] Yüklendi — "
                         f"eğitim={self._egitim_sayisi} drift={self._drift_sayisi}")
        except Exception as e:
            log.warning(f"[ONLINE/{self.sembol}] Yüklenemedi: {e}")

    def _kaydet(self):
        if not RIVER_AVAILABLE or self._model is None: return
        path = os.path.join(_online_dizin(), f"online_{self.sembol}.pkl")
        try:
            with open(path, "wb") as f:
                pickle.dump({
                    "model":   self._model,
                    "scaler":  self._scaler,
                    "egitim":  self._egitim_sayisi,
                    "drift":   self._drift_sayisi,
                    "ts":      datetime.now(timezone.utc).isoformat(),
                }, f)
        except Exception as e:
            log.warning(f"[ONLINE/{self.sembol}] Kayıt hatası: {e}")

    def guncelle_ve_tahmin(self, features: dict,
                            gercek_sonuc: Optional[int] = None,
                            mevcut_fiyat: float = 0.0) -> dict:
        """
        Bir önceki X'e gerçek label ekle (learn) + yeni X için tahmin yap.
        Her mum kapanışında çağrılır.

        Args:
            features:       coin_analiz'den gelen feature dict
            gercek_sonuc:   Eğer biliniyorsa 0/1, yoksa None
            mevcut_fiyat:   Anlık fiyat (drift tespiti için)

        Returns:
            {prob: float 0-1, drift: bool, egitim_sayisi: int, aktif: bool}
        """
        if not RIVER_AVAILABLE or self._model is None:
            return {"prob": 0.5, "drift": False, "egitim_sayisi": 0, "aktif": False}

        with self._lock:
            try:
                # Temizle — sadece sayısal feature'lar
                x = {k: float(v) for k, v in features.items()
                     if isinstance(v, (int, float)) and not np.isnan(float(v))}

                if not x:
                    return {"prob": 0.5, "drift": False,
                            "egitim_sayisi": self._egitim_sayisi, "aktif": True}

                # Online scaler
                # v58 (K-50): ZİNCİRLEME ÇAĞRI KIRILDI.
                # Eski hâli `self._scaler.learn_one(x).transform_one(x)`
                # idi. river 0.15+ `learn_one()` artık `self` DEĞİL `None`
                # döndürüyor (yerinde değiştiriyor) → AttributeError:
                # 'NoneType' object has no attribute 'transform_one'.
                # K-45 ile aynı kök: river API göçü. Bu ikincisi ancak
                # K-45 + K-48 hatayı GÖRÜNÜR kıldıktan sonra ortaya çıktı —
                # öncesinde `log.debug` ile yutuluyordu.
                self._scaler.learn_one(x)
                x_scaled = self._scaler.transform_one(x)

                # Bir önceki mum için label varsa öğren
                if self._son_x is not None and gercek_sonuc is not None:
                    # v23: Accuracy'yi öğrenmeden ÖNCE ölç (data leakage önleme)
                    pred = self._model.predict_one(self._son_x)
                    if pred is not None:
                        self._accuracy.update(gercek_sonuc, pred)
                    self._model.learn_one(self._son_x, gercek_sonuc)
                    self._egitim_sayisi += 1

                    # Drift tespiti (fiyat tabanlı)
                    if mevcut_fiyat > 0 and self._son_fiyat > 0:
                        log_ret = abs(np.log(mevcut_fiyat / self._son_fiyat))
                        self._drift_detector.update(log_ret)
                        if self._drift_detector.drift_detected:
                            self._drift_sayisi += 1
                            log.warning(f"[ONLINE/{self.sembol}] Drift tespit! "
                                        f"#{self._drift_sayisi} fiyat={mevcut_fiyat:.2f}")

                    # ── v58 (K-65): HER GERÇEK EĞİTİMDE KAYDET ──────
                    # Eskiden koşul `% 100 == 0` idi ve `saved_models/online/`
                    # 2026-08-11'den beri BOŞTU: eşik hiç tutmadı, model
                    # durumu diske HİÇ yazılmadı. Her yeniden başlatmada
                    # (bot bugün ~12 kez) sayaç 0'dan başlıyordu → blend
                    # ağırlığı `egitim < 50` dalında 0.1'e ÇAKILI kalıyordu;
                    # "online öğrenme" hiçbir zaman birikmiyordu.
                    #
                    # K-64'ten sonra eğitim adımı bar başına 1 (4h'de sembol
                    # başına günde ~6) — her adımda kaydetmek ucuz.
                    self._kaydet()

                # Tahmin
                prob_dict = self._model.predict_proba_one(x_scaled)
                prob = float(prob_dict.get(1, 0.5)) if prob_dict else 0.5

                # State güncelle
                self._son_x     = x_scaled
                self._son_fiyat = mevcut_fiyat

                drift_var = self._drift_detector.drift_detected if self._drift_detector else False

                return {
                    "prob":           round(prob, 4),
                    "drift":          drift_var,
                    "egitim_sayisi":  self._egitim_sayisi,
                    "drift_sayisi":   self._drift_sayisi,
                    "accuracy":       round(float(self._accuracy.get()), 4) if self._egitim_sayisi > 10 else 0.5,
                    "aktif":          True,
                }

            except Exception as e:
                log.warning(f"[ONLINE/{self.sembol}] Hata: {e}")
                return {"prob": 0.5, "drift": False,
                        "egitim_sayisi": self._egitim_sayisi, "aktif": True}

    def birlesik_tahmin(self, batch_prob: float, online_sonuc: dict) -> float:
        """
        Batch model tahmini + online model tahminini birleştir.
        Online model yeterince eğitilmemişse batch'e daha çok ağırlık ver.
        """
        if not online_sonuc.get("aktif") or not RIVER_AVAILABLE:
            return batch_prob

        online_prob   = online_sonuc.get("prob", 0.5)
        egitim        = online_sonuc.get("egitim_sayisi", 0)

        # İlk 50 örnekte online modele güvenme
        if egitim < 50:
            agirlik = 0.1
        elif egitim < 200:
            agirlik = 0.2
        else:
            agirlik = self.online_agirlik

        # Drift varsa online modele daha az güven (henüz uyum sağlamadı)
        if online_sonuc.get("drift"):
            agirlik *= 0.5

        birlesik = agirlik * online_prob + (1 - agirlik) * batch_prob
        return round(float(birlesik), 4)

    def durum_raporu(self) -> str:
        acc = float(self._accuracy.get()) if (RIVER_AVAILABLE and self._egitim_sayisi > 10) else 0
        return (f"Online[{self.sembol}]: n={self._egitim_sayisi} "
                f"drift={self._drift_sayisi} acc={acc:.3f} "
                f"river={'✅' if RIVER_AVAILABLE else '❌'}")


# ── Global Registry ───────────────────────────────────────
_online_learners: dict = {}   # {sembol: OnlineLearner}
_ol_lock = threading.Lock()

def get_online_learner(sembol: str) -> OnlineLearner:
    with _ol_lock:
        if sembol not in _online_learners:
            _online_learners[sembol] = OnlineLearner(sembol)
        return _online_learners[sembol]

def online_durum_raporu() -> str:
    if not _online_learners:
        return "Online learner: henüz başlatılmadı"
    satirlar = ["🧬 <b>ONLINE LEARNING DURUMU v20</b>", "━━━━━━━━━━━━━━━━"]
    for s, ol in _online_learners.items():
        satirlar.append(ol.durum_raporu())
    return "\n".join(satirlar)
