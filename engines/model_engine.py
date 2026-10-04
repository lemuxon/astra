# =========================================================
# ASTRA v30.0 — MODEL ENGINE (Seviye 2: AI/ML)
# - Per-coin modeller
# - Ensemble (Voting + Stacking)
# - Optuna hiperparametre opt.
# - Temporal Fusion Transformer (basit)
# - Online feedback loop
# - RL benzeri reward tracking
# =========================================================
import os, time, pickle, logging, json, threading
import numpy as np, pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier, VotingClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.calibration import CalibratedClassifierCV
import sys; sys.path.append("..")
from config import MODEL_DIR, LOOKBACK, WALK_FORWARD_SPLITS, MIN_USEFUL_ACC
from data.database import performans_kaydet
from engines.backtest_engine import walk_forward_cv, overfitting_skoru

try:
    import xgboost as xgb; XGB_AVAILABLE = True
except ImportError: XGB_AVAILABLE = False
try:
    import lightgbm as lgb; LGB_AVAILABLE = True
except ImportError: LGB_AVAILABLE = False
try:
    import optuna; optuna.logging.set_verbosity(optuna.logging.WARNING); OPTUNA_AVAILABLE = True
except ImportError: OPTUNA_AVAILABLE = False
try:
    from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
    from tensorflow.keras.layers import Dense, LSTM, Dropout, BatchNormalization, MultiHeadAttention, LayerNormalization, GlobalAveragePooling1D
    from tensorflow.keras.models import Sequential, Model, load_model
    from tensorflow.keras import Input
    KERAS_AVAILABLE = True
except ImportError: KERAS_AVAILABLE = False

log = logging.getLogger("ASTRA.MODEL")
# v23: Keras/TF thread-safe değil — paralel coin analizinde inference'ı serialize et
_tf_lock = threading.Lock()
_tft_retrain_aktif: set = set()      # v29: eşzamanlı TFT eğitimi engelleme
_tft_retrain_lock = threading.Lock()
Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)

# ── Stacking Wrapper — modül scope'unda (pickle için zorunlu) ────
class StackingWrapper:
    """Pickle edilebilir stacking ensemble wrapper."""
    def __init__(self, base_models, meta):
        self.base_models = base_models
        self.meta        = meta

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    def predict_proba(self, X):
        probas = []
        for m, _, _, _ in self.base_models:
            try:
                probas.append(m.predict_proba(X)[:, 1])
            except (ValueError, AttributeError, OSError):
                pass
        if not probas:
            return np.column_stack([np.zeros(len(X)), np.ones(len(X))])
        X_meta = np.column_stack(probas)
        n_exp = (self.meta.n_features_in_
                 if hasattr(self.meta, 'n_features_in_')
                 else len(self.base_models))
        if X_meta.shape[1] > n_exp:
            X_meta = X_meta[:, :n_exp]
        elif X_meta.shape[1] < n_exp:
            pad    = np.zeros((X_meta.shape[0], n_exp - X_meta.shape[1]))
            X_meta = np.hstack([X_meta, pad])
        return self.meta.predict_proba(X_meta)



# ── RL Reward Tracker ─────────────────────────────────────
_rl_rewards: dict = {}   # {sembol: [reward_listesi]}

def rl_reward_kaydet(sembol: str, pnl_pct: float, ai_score: int):
    """Kapanan işlemden RL reward hesapla ve sakla.
    v17 fix: Kayıp ceza çarpanı düzeltildi (negatif*1.5 = daha negatif = doğru ceza).
    ai_score tutarlılığı da ödüllendiriliyor (yüksek score + kazanç = bonus).
    """
    # Kazanç: pnl aynen, kayıp: 1.5x ceza (mutlak değer alıp negatife çevir)
    if pnl_pct >= 0:
        reward = pnl_pct
    else:
        reward = pnl_pct * 1.5  # Zaten negatif, 1.5 ile çarpılınca daha negatif = doğru ceza

    # ai_score tutarlılık bonusu/cezası
    score_yon  = 1 if ai_score > 0 else (-1 if ai_score < 0 else 0)
    sonuc_yonu = 1 if pnl_pct > 0 else -1
    if score_yon == sonuc_yonu and abs(ai_score) >= 5:
        reward += 0.5   # Güçlü tahmin + doğru = bonus
    elif score_yon != sonuc_yonu and abs(ai_score) >= 5:
        reward -= 0.5   # Güçlü tahmin + yanlış = ekstra ceza

    if sembol not in _rl_rewards: _rl_rewards[sembol] = []
    _rl_rewards[sembol].append({"reward": reward, "ai_score": ai_score,
                                 "ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()})
    if len(_rl_rewards[sembol]) > 200: _rl_rewards[sembol] = _rl_rewards[sembol][-200:]
    log.info(f"[RL] {sembol} reward={reward:.3f} (pnl={pnl_pct:.2f}% ai={ai_score})")

def rl_ortalama_reward(sembol: str) -> float:
    rewards = _rl_rewards.get(sembol, [])
    if not rewards: return 0.0
    return float(np.mean([r["reward"] for r in rewards[-20:]]))

# ── Kaydet / Yükle ────────────────────────────────────────
_model_io_lock = threading.Lock()   # v29: model dosya yazma/okuma serialize

def model_kaydet(model, isim: str):
    yol = os.path.join(MODEL_DIR, f"{isim}.pkl")
    # v29: atomik yazma — yarı yazılmış dosyayı okuyan thread'i önle.
    # Önce .tmp'ye yaz, sonra atomik rename (os.replace).
    tmp = yol + f".tmp.{os.getpid()}.{threading.get_ident()}"
    with _model_io_lock:
        try:
            with open(tmp, "wb") as f:
                pickle.dump(model, f)
            os.replace(tmp, yol)   # atomik
            log.info(f"Model kaydedildi: {yol}")
        except Exception as e:
            log.error(f"[MODEL] {isim} kayıt hatası: {e}")
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except OSError: pass

def model_yukle(isim: str):
    yol = os.path.join(MODEL_DIR, f"{isim}.pkl")
    if not os.path.exists(yol): return None
    if os.path.getsize(yol) == 0:
        log.warning(f"[MODEL] {yol} boş dosya — siliniyor")
        try: os.remove(yol)
        except OSError: pass
        return None
    try:
        with open(yol, "rb") as f:
            model = pickle.load(f)
        # v15: Temel predict testi — eski sklearn pkl uyumsuzluğunu yakala
        if hasattr(model, "predict") and hasattr(model, "n_features_in_"):
            _ = model.n_features_in_  # erişilebilir mi?
        return model
    except (pickle.UnpicklingError, EOFError, AttributeError) as e:
        log.warning(f"[MODEL] {yol} yüklenemedi (uyumsuz pkl?): {e} — siliniyor")
        try: os.remove(yol)
        except OSError: pass
        return None
    except Exception as e:
        log.warning(f"[MODEL] {yol} beklenmedik hata: {e} — siliniyor")
        try: os.remove(yol)
        except OSError: pass
        return None

def model_yasi(isim: str) -> float:
    yol = os.path.join(MODEL_DIR, f"{isim}.pkl")
    if not os.path.exists(yol): return float("inf")
    return time.time() - os.path.getmtime(yol)

def scaler_kaydet(scaler, isim: str):
    yol = os.path.join(MODEL_DIR, f"scaler_{isim}.pkl")
    tmp = yol + f".tmp.{os.getpid()}.{threading.get_ident()}"
    with _model_io_lock:
        try:
            with open(tmp, "wb") as f:
                pickle.dump(scaler, f)
            os.replace(tmp, yol)
        except Exception as e:
            log.error(f"[SCALER] {isim} kayıt hatası: {e}")
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except OSError: pass

def scaler_yukle(isim: str):
    yol = os.path.join(MODEL_DIR, f"scaler_{isim}.pkl")
    if not os.path.exists(yol): return None
    with open(yol, "rb") as f: return pickle.load(f)

_BOS_WF = {"splits": 0, "ortalama": 0.0, "std": 0.0,
           "min": 0.0, "max": 0.0, "auc_ort": 0, "detay": [],
           # v58 (K-37): beceri = accuracy − çoğunluk sınıfı taban çizgisi
           "beceri_ort": 0.0, "beceri_std": 0.0, "taban_ort": 0.0}


def _wf_guvenli(X, y, model_cls, params, n_splits=None):
    """walk_forward_cv — çökerse eğitimi düşürmeden boş sonuç döner.

    v58 (K-20): Model SEÇİMİ artık buna dayanıyor (tek hold-out yerine).
    Walk-forward, zaman serisinde dürüst olan tek tahmindir: her katman
    yalnızca GEÇMİŞLE eğitilip GELECEĞE bakar.

    ⚠️ Feedback BİLEREK yok — WF ham piyasa verisi üzerinde çalışır.
    Feedback zaman sırasız olduğu için katmanlara dağıtılamaz (K-18).
    """
    try:
        # v58 (K-23): üçlü bariyer etiketleri örtüşür → embargo şart
        emb = 0
        try:
            from config import HEDEF_TIPI, HEDEF_MAX_BAR
            if HEDEF_TIPI == "ucgen_bariyer":
                emb = HEDEF_MAX_BAR
        except ImportError:
            pass
        return walk_forward_cv(X, y, model_cls, params,
                               n_splits=n_splits or WALK_FORWARD_SPLITS,
                               embargo=emb)
    except Exception as e:
        log.warning(f"[WF] hesaplanamadı ({model_cls.__name__}): {e}")
        return dict(_BOS_WF)


def wf_kaydet(isim: str, wf: dict):
    """Walk-forward sonucunu modelin YANINA yaz.

    v58 (K-27): Model seçimi WF'ye dayanıyor (K-20) ama WF yalnızca
    EĞİTİM anında hesaplanıyordu. Önbellekten yüklenen modellerin
    meta'sı boş geldiği için WF=0 oluyor ve seçim sessizce `test_acc`e
    düşüyordu. Modeller 1 saat taze kaldığından bu, çağrıların
    ÇOĞUNLUĞUYDU — logda 229 kez "hiçbir adayda WF yok" uyarısı.
    (Uyarı sesli olmasaydı bu boşluk görünmezdi — §5.2.)
    """
    try:
        with open(os.path.join(MODEL_DIR, f"wf_{isim}.json"), "w") as f:
            json.dump(wf, f)
    except OSError as e:
        log.debug(f"[WF] {isim} kaydedilemedi: {e}")


def wf_yukle(isim: str) -> dict:
    """Kayıtlı WF sonucunu oku (yoksa boş)."""
    yol = os.path.join(MODEL_DIR, f"wf_{isim}.json")
    if not os.path.exists(yol):
        return dict(_BOS_WF)
    try:
        with open(yol) as f:
            return json.load(f)
    except (OSError, ValueError):
        return dict(_BOS_WF)


def _wf_ortalama(meta) -> float:
    """meta içinden WF HAM accuracy ortalamasını çıkar (yoksa 0).

    ⚠️ Seçim için bunu KULLANMA — `_wf_beceri` var (K-37). Bu yalnızca
    raporlama/geriye uyumluluk içindir.
    """
    try:
        return float((meta or {}).get("wf", {}).get("ortalama", 0.0) or 0.0)
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _wf_beceri(meta) -> float:
    """meta içinden WF BECERİSİNİ çıkar: accuracy − taban çizgisi.

    v58 (K-37): Model seçimi ham accuracy'ye bakıyordu. Sınıf dengesi
    katmandan katmana %50.1–%53.5 arasında oynadığı için ham accuracy
    modelleri karşılaştırmaz — dengesizliği ödüllendirir.

    Eski WF dosyalarında bu anahtar YOK; o durumda 0 dönüyoruz (bilinmiyor
    = beceri yok). Sessizce ham accuracy'ye düşmek, düzeltmenin kendisini
    etkisiz kılardı (§5.2: istenen ≠ yapılan olduğu her yerde sesli ol —
    bu yüzden `_wf_eski_format` ayrıca sayılıyor).
    """
    try:
        wf = (meta or {}).get("wf", {}) or {}
        if "beceri_ort" not in wf:
            return 0.0
        return float(wf.get("beceri_ort", 0.0) or 0.0)
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _wf_beceri_std(meta) -> float:
    """Becerinin katmanlar arası standart sapması (belirsizlik ölçüsü)."""
    try:
        wf = (meta or {}).get("wf", {}) or {}
        return float(wf.get("beceri_std", 0.0) or 0.0)
    except (AttributeError, TypeError, ValueError):
        return 0.0


def guven_notrle(guven: float, meta, sembol: str = "") -> float:
    """Beceri anlamlı değilse model güvenini NÖTRE (50.0) çeker.

    v58 (K-37). Bu fonksiyon main.py'daki satır içi bloktan ÇIKARILDI:
    mutasyon testi, satır içi hâlin davranışsal olarak test EDİLEMEDİĞİNİ
    gösterdi (kaynakta string arayan test, bloğu kaldıran mutasyonu
    yakalayamadı — K-29'daki "yanlış katmanı doğrulayan test" tuzağı).

    NEDEN: WF beceri değerleri 0.00–0.05, std 0.04–0.08 → çoğu model taban
    çizgisinden ayırt edilemez. Buna rağmen sistem her koşulda bir model
    seçip `predict_proba` çıktısını `yukselis_guveni` yapıyordu; o değer
    doğrudan ai_score'a giriyor (>=80 → +2, >=70 → +1, <50 → −1, <40 → −2)
    ve giriş eşiği |ai| >= 4. Yani bot GÜRÜLTÜNÜN ÜST KUYRUĞUNA göre işlem
    açıyordu — üstelik aday kapısı tam o kuyruğu arıyor (üretim logu:
    4037 kez "acc<0.52 → yeniden eğit").

    §5.1'deki fail-open deseninin AYNASI:
        orada  "bilmiyorum"              → "sorun yok"
        burada "ölçülebilir beceri yok"  → "işte güvenilir olasılık"

    50.0 NÖTRDÜR: ai_score_hesapla'da 40–60 bandı puan eklemez/çıkarmaz.
    Diğer bileşenler (MACD, MA, MTF, osilatörler) çalışmaya devam eder —
    sinyal susturulmuyor, yalnızca modelin sahte katkısı kaldırılıyor.

    Hata hâlinde FAIL-CLOSED: nötr döner. Sessizce modele güvenmek,
    düzeltmenin tam tersi olurdu.
    """
    try:
        if model_beceri_anlamli_mi(meta):
            return float(guven)
        if abs(float(guven) - 50.0) > 0.01:
            log.info(f"[MODEL/{sembol}] beceri anlamlı değil "
                     f"({_wf_beceri(meta):+.4f} ≤ {_wf_beceri_std(meta):.4f}) "
                     f"→ güven {float(guven):.1f} yerine 50.0 (nötr)")
        return 50.0
    except Exception as e:
        log.error(f"[MODEL/{sembol}] beceri kontrolü başarısız: "
                  f"{type(e).__name__}: {e} → güven nötrleniyor (fail-closed)")
        return 50.0


def model_beceri_anlamli_mi(meta) -> bool:
    """Bu modelin becerisi kendi belirsizliğinden BÜYÜK mü?

    v58 (K-37): Ölçülen WF beceri değerleri 0.00–0.05, std 0.04–0.08.
    Yani çoğu model taban çizgisinden AYIRT EDİLEMEZ. Sistem yine de
    birini seçip onun olasılığını `yukselis_guveni` olarak kullanıyordu
    → bot gürültünün üst kuyruğuna göre işlem açıyordu.

    Bu, §5.1'deki fail-open deseninin aynası: orada "bilmiyorum" →
    "sorun yok" diye kodlanmıştı; burada "ölçülebilir beceri yok" →
    "işte güvenilir bir olasılık" diye kodlanıyordu.

    Eşik AYARLANABİLİR BİR SAYI DEĞİL: "tahmin kendi standart hatasından
    büyük mü" istatistiksel ifadesi. Uydurma bir sabit eklemiyoruz
    (§0 kuralı: veri görülmeden konan eşikler oynatılmaz).
    """
    b = _wf_beceri(meta)
    s = _wf_beceri_std(meta)
    return b > 0 and b > s


# ── v58 (K-18): EĞİTİM / TEST BÖLME — feedback TEST'e girmez ──
def egitim_test_bol(X: pd.DataFrame, y: pd.Series, sembol: str,
                    test_size: float = 0.2):
    """Zaman sıralı böl; feedback kayıtlarını YALNIZCA train'e ekle.

    ── NEDEN VAR (ölçülen sızıntı, 2026-09-03) ──────────────────
    Eskiden `en_iyi_model_yukle_veya_egit` feedback'i verinin SONUNA
    ekliyordu (`pd.concat([X, X_fb])`), sonra her eğitici
    `train_test_split(..., shuffle=False)` ile SON %20'yi test yapıyordu.
    Sonuç: test seti neredeyse tamamen feedback kayıtlarından oluşuyordu.

    Feedback etiketleri o dönemde %99.5 oranında 0'dı (bkz. K-17), yani
    test seti TEK SINIFLI hale geliyordu. Model "0" diyerek %96-100
    accuracy alıyordu:

        feedback YOK  → test_acc 0.516   (test'te target=1 oranı 0.484)
        feedback VAR  → test_acc 0.963   (test'te target=1 oranı 0.000)

    Raporlanan accuracy hiçbir şey ölçmüyordu. Dürüst rakam (0.516)
    çoğunluk sınıfı taban çizgisiyle (0.518) aynı — model sıfır öngörü
    gücüne sahip. Bağımsız sinyal analizi de aynı sonuca varmıştı
    (excess getiri +%0.003, p=0.93 — bkz. ANALIZ_KAYIP_NEDENI.md §3).

    ── KURAL ────────────────────────────────────────────────────
    TEST SETİ YALNIZCA PİYASA VERİSİDİR. Feedback (işlem sonucu) farklı
    bir etiket semantiğine sahiptir ("işlem kârlı mıydı" ≠ "sonraki bar
    yukarı mı") ve zaman sırası da yoktur; test setine girerse ölçüm
    anlamını kaybeder. Eğitimde kullanılması meşrudur.
    """
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=test_size, shuffle=False)

    # ── v58 (K-23): EMBARGO — örtüşen etiketleri temizle ────────
    # Üçlü bariyer etiketi HEDEF_MAX_BAR bar ileriye bakar. Train'in son
    # satırlarının etiketi, test döneminin fiyatlarından hesaplanmıştır;
    # bırakılırsa model test dönemini dolaylı olarak görür ve üçlü
    # bariyer eski hedeften "daha iyi" görünür — sebebi sızıntıdır.
    # (López de Prado, purging/embargo.)
    try:
        from config import HEDEF_TIPI, HEDEF_MAX_BAR
        if HEDEF_TIPI == "ucgen_bariyer" and HEDEF_MAX_BAR > 0:
            kes = min(HEDEF_MAX_BAR, max(0, len(X_tr) - 20))
            if kes > 0:
                X_tr = X_tr.iloc[:-kes]
                y_tr = y_tr.iloc[:-kes]
    except ImportError:
        pass

    try:
        X_tr, y_tr = feedback_veri_yukle(sembol, X_tr, y_tr)
    except Exception as e:      # feedback yoksa/bozuksa eğitim sürmeli
        log.warning(f"[FEEDBACK/{sembol}] train'e eklenemedi: {e}")
    return X_tr, X_te, y_tr, y_te


# ── Optuna Optimizasyonu ──────────────────────────────────
def rf_optimize(X_tr, y_tr, X_te, y_te, n_trials=25) -> dict:
    if not OPTUNA_AVAILABLE or len(X_tr) < 60:
        return {"n_estimators":300,"max_depth":10,"min_samples_leaf":2,"max_features":"sqrt","random_state":42,"n_jobs":-1}
    def objective(trial):
        params = {"n_estimators":trial.suggest_int("n_estimators",100,500),
                  "max_depth":trial.suggest_int("max_depth",4,15),
                  "min_samples_leaf":trial.suggest_int("min_samples_leaf",1,10),
                  "max_features":trial.suggest_categorical("max_features",["sqrt","log2"]),
                  "random_state":42,"n_jobs":-1}
        m = RandomForestClassifier(**params); m.fit(X_tr, y_tr)
        return f1_score(y_te, m.predict(X_te), average="weighted")
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best = study.best_params; best.update({"random_state":42,"n_jobs":-1})
    log.info(f"[OPTUNA RF] best f1={study.best_value:.3f}")
    return best

def xgb_optimize(X_tr, y_tr, X_te, y_te, n_trials=25) -> dict:
    if not OPTUNA_AVAILABLE or not XGB_AVAILABLE or len(X_tr) < 60:
        return {"n_estimators":200,"max_depth":6,"learning_rate":0.05,
                "subsample":0.8,"colsample_bytree":0.8,"eval_metric":"logloss",
                "random_state":42,"verbosity":0}
    def objective(trial):
        params = {"n_estimators":trial.suggest_int("n_estimators",100,400),
                  "max_depth":trial.suggest_int("max_depth",3,10),
                  "learning_rate":trial.suggest_float("learning_rate",0.01,0.2,log=True),
                  "subsample":trial.suggest_float("subsample",0.6,1.0),
                  "colsample_bytree":trial.suggest_float("colsample_bytree",0.6,1.0),
                  "min_child_weight":trial.suggest_int("min_child_weight",1,10),
                  "eval_metric":"logloss","random_state":42,"verbosity":0}
        m = xgb.XGBClassifier(**params)
        # v58 (K-19): `eval_set` kaldırıldı. early_stopping_rounds zaten
        # yoktu, yani modeli etkilemiyordu — ama holdout'u fit()'e sokmak
        # early stopping ileride geri açılırsa sessiz bir sızıntıya döner.
        m.fit(X_tr, y_tr, verbose=False)
        return f1_score(y_te, m.predict(X_te), average="weighted")
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best = study.best_params; best.update({"eval_metric":"logloss","random_state":42,"verbosity":0})
    log.info(f"[OPTUNA XGB] best f1={study.best_value:.3f}")
    return best

# ── Per-Coin Eğitim ───────────────────────────────────────
def rf_egit(X: pd.DataFrame, y: pd.Series, sembol: str) -> tuple:
    if len(X) < 40: return None, 0, {}
    X_tr,X_te,y_tr,y_te = egitim_test_bol(X,y,sembol,0.2)   # v58 K-18
    wf = _wf_guvenli(X,y,RandomForestClassifier,
                     {"n_estimators":300,"max_depth":10,"random_state":42,"n_jobs":-1})
    # v58 (K-19): parametre seçimi TEST setine bakmamalı. Eskiden
    # `rf_optimize(X_tr,y_tr,X_te,y_te)` Optuna'ya 25 denemede TEST
    # setindeki f1'i maksimize ettiriyordu; sonra aynı test setinin
    # skoru "dürüst accuracy" diye raporlanıyordu (ölçülen şişme: +2.6
    # puan). Artık train'den ayrılan bir DOĞRULAMA seti kullanılıyor.
    if len(X_tr) >= 80:
        X_opt, X_val, y_opt, y_val = train_test_split(
            X_tr, y_tr, test_size=0.25, shuffle=False)
        best_params = rf_optimize(X_opt, y_opt, X_val, y_val)
    else:
        best_params = rf_optimize(X_tr, y_tr, X_tr, y_tr)
    model = RandomForestClassifier(**best_params)
    model.fit(X_tr,y_tr)
    # v33 FIX: Kalibrasyon sızıntısı düzeltildi.
    # ESKİ HATA: cal_model.fit(X_te, y_te) → test seti kalibrasyonda kullanılıyordu,
    # bu test_acc'yi yapay olarak şişiriyordu (+30-37 puan sızıntı ölçüldü).
    # YENİ: kalibrasyon train'den ayrılan ayrı bir set ile yapılır; test seti
    # ASLA görülmez → raporlanan accuracy dürüst olur.
    try:
        if len(X_tr) >= 50:
            X_tr2, X_cal, y_tr2, y_cal = train_test_split(
                X_tr, y_tr, test_size=0.25, shuffle=False)
            # En az iki sınıf varsa kalibre et
            if len(set(y_tr2)) > 1 and len(set(y_cal)) > 1:
                model = RandomForestClassifier(**best_params)
                model.fit(X_tr2, y_tr2)
                cal_model = CalibratedClassifierCV(model, cv=None, method="isotonic")
                cal_model.fit(X_cal, y_cal)   # train'den ayrılan set — test DEĞİL
            else:
                cal_model = model   # kalibrasyon yapılamadı, ham model
        else:
            cal_model = model
    except Exception as _cal_e:
        log.debug(f"[RF/{sembol}] kalibrasyon atlandı: {_cal_e}")
        cal_model = model
    # test_acc artık kaydedilen modelle (cal_model) ÖLÇÜLÜR — tutarlılık
    train_acc=accuracy_score(y_tr,model.predict(X_tr))
    test_acc =accuracy_score(y_te,cal_model.predict(X_te))
    of_skoru=overfitting_skoru(train_acc,test_acc,wf["std"])
    if hasattr(model,"feature_importances_"):
        imp=sorted(zip(X.columns,model.feature_importances_),key=lambda x:x[1],reverse=True)[:6]
        log.info(f"[RF/{sembol}] Top features: {[(f,round(v,3)) for f,v in imp]}")
    isim=f"rf_{sembol.replace('-','_')}"
    model_kaydet(cal_model, isim); wf_kaydet(isim, wf)   # v58 K-27
    performans_kaydet(sembol,"RF_Calibrated",test_acc)
    # v22: Model registry'ye versiyonla
    try:
        from engines.model_registry import get_model_registry
        get_model_registry().register(
            sembol, "rf", os.path.join(MODEL_DIR, f"{isim}.pkl"),
            accuracy=test_acc, params={"n_est":best_params.get("n_estimators")},
            feature_sayisi=X.shape[1], orneklem=len(X)
        )
    except Exception as _re: log.debug(f"[REGISTRY] {_re}")
    log.info(f"[RF/{sembol}] WF:{wf['ortalama']:.3f}±{wf['std']:.3f} OF:{of_skoru['risk']}")
    return cal_model, test_acc, {"wf":wf,"overfitting":of_skoru}

def xgb_egit(X: pd.DataFrame, y: pd.Series, sembol: str) -> tuple:
    if not XGB_AVAILABLE or len(X) < 40: return None, 0, {}
    X_tr,X_te,y_tr,y_te = egitim_test_bol(X,y,sembol,0.2)   # v58 K-18
    # v58 (K-19): parametre seçimi TEST setine bakmamalı (rf_egit ile aynı
    # gerekçe). Train'den ayrılan doğrulama seti kullanılır.
    if len(X_tr) >= 80:
        X_opt, X_val, y_opt, y_val = train_test_split(
            X_tr, y_tr, test_size=0.25, shuffle=False)
        best_params = xgb_optimize(X_opt, y_opt, X_val, y_val)
    else:
        best_params = xgb_optimize(X_tr, y_tr, X_tr, y_tr)
    model = xgb.XGBClassifier(**best_params)
    # Versiyon bağımsız fit (XGBoost 1.x ve 2.x uyumlu)
    model.fit(X_tr, y_tr, verbose=False)
    # v33 FIX: Kalibrasyon test setiyle DEĞİL, train'den ayrılan setle yapılır.
    cal_model = model
    try:
        if len(X_tr) >= 50:
            X_tr2, X_cal, y_tr2, y_cal = train_test_split(
                X_tr, y_tr, test_size=0.25, shuffle=False)
            if len(set(y_tr2)) > 1 and len(set(y_cal)) > 1:
                model = xgb.XGBClassifier(**best_params)
                model.fit(X_tr2, y_tr2, verbose=False)
                cal_model = CalibratedClassifierCV(model, cv=None, method="isotonic")
                cal_model.fit(X_cal, y_cal)   # test DEĞİL
    except (ValueError, TypeError) as _e:
        log.debug(f"[XGB/{sembol}] kalibrasyon atlandı: {_e}")
        cal_model = model
    acc=accuracy_score(y_te,cal_model.predict(X_te))   # kaydedilen modelle ölç
    isim=f"xgb_{sembol.replace('-','_')}"
    model_kaydet(cal_model, isim)
    performans_kaydet(sembol,"XGB_Calibrated",acc)
    wf = _wf_guvenli(X, y, xgb.XGBClassifier,
                     {**{k: v for k, v in best_params.items()},
                      "eval_metric": "logloss", "verbosity": 0})
    wf_kaydet(isim, wf)   # v58 K-27 — WF hesaplandıktan SONRA
    log.info(f"[XGB/{sembol}] test_acc={acc:.3f} WF={wf['ortalama']:.3f}±{wf['std']:.3f}")
    return cal_model, acc, {"wf":wf}

def lgb_egit(X: pd.DataFrame, y: pd.Series, sembol: str) -> tuple:
    if not LGB_AVAILABLE or len(X) < 40: return None, 0, {}
    X_tr,X_te,y_tr,y_te = egitim_test_bol(X,y,sembol,0.2)   # v58 K-18
    model = lgb.LGBMClassifier(n_estimators=300,max_depth=6,learning_rate=0.03,
                                num_leaves=31,min_child_samples=20,random_state=42,verbose=-1)
    # v58 (K-19): early stopping TEST setine bakıyordu — model, test
    # skorunu maksimize eden iterasyonda duruyor ve aynı test skoru
    # "dürüst" diye raporlanıyordu. Artık train'den ayrılan doğrulama
    # seti kullanılıyor.
    if len(X_tr) >= 80:
        X_fit, X_val, y_fit, y_val = train_test_split(
            X_tr, y_tr, test_size=0.25, shuffle=False)
        model.fit(X_fit, y_fit, eval_set=[(X_val, y_val)],
                  callbacks=[lgb.early_stopping(30, verbose=False)])
    else:
        model.fit(X_tr, y_tr)
    acc=accuracy_score(y_te,model.predict(X_te))
    wf = _wf_guvenli(X, y, lgb.LGBMClassifier,
                     {"n_estimators":300,"max_depth":6,"learning_rate":0.03,
                      "num_leaves":31,"min_child_samples":20,
                      "random_state":42,"verbose":-1})
    isim=f"lgb_{sembol.replace('-','_')}"
    model_kaydet(model, isim); wf_kaydet(isim, wf)   # v58 K-27
    performans_kaydet(sembol,"LightGBM",acc)
    log.info(f"[LGB/{sembol}] test_acc={acc:.3f} WF={wf['ortalama']:.3f}±{wf['std']:.3f}")
    return model, acc, {"wf":wf}

def gb_egit(X: pd.DataFrame, y: pd.Series, sembol: str) -> tuple:
    """GradientBoosting — ek çeşitlilik için."""
    if len(X) < 60: return None, 0, {}
    X_tr,X_te,y_tr,y_te = egitim_test_bol(X,y,sembol,0.2)   # v58 K-18
    model = GradientBoostingClassifier(n_estimators=200,max_depth=4,learning_rate=0.05,
                                        subsample=0.8,random_state=42)
    model.fit(X_tr,y_tr)
    acc=accuracy_score(y_te,model.predict(X_te))
    wf = _wf_guvenli(X, y, GradientBoostingClassifier,
                     {"n_estimators":200,"max_depth":4,"learning_rate":0.05,
                      "subsample":0.8,"random_state":42})
    isim=f"gb_{sembol.replace('-','_')}"
    model_kaydet(model, isim); wf_kaydet(isim, wf)   # v58 K-27
    log.info(f"[GB/{sembol}] test_acc={acc:.3f} WF={wf['ortalama']:.3f}±{wf['std']:.3f}")
    return model, acc, {"wf":wf}

# ── Stacking Ensemble ─────────────────────────────────────
def stacking_ensemble_olustur(X: pd.DataFrame, y: pd.Series,
                               sembol: str, adaylar: list) -> tuple:
    """
    2-seviyeli stacking:
    L1: RF + XGB + LGB + GB
    L2: LogisticRegression meta-learner (olasılıkları birleştirir)
    """
    if len(adaylar) < 2: return None, 0, {}
    X_tr,X_te,y_tr,y_te = egitim_test_bol(X,y,sembol,0.25)  # v58 K-18
    # L1 tahminleri topla
    meta_features_tr = []
    meta_features_te = []
    gecerli_adaylar  = []
    for model, acc, meta, isim in adaylar:
        try:
            X_l1_tr,X_l1_te,y_l1_tr,_ = train_test_split(X_tr,y_tr,test_size=0.3,shuffle=False)
            model.fit(X_l1_tr,y_l1_tr)
            proba_tr = model.predict_proba(X_l1_te)[:,1]
            proba_te = model.predict_proba(X_te)[:,1]
            meta_features_tr.append(proba_tr)
            meta_features_te.append(proba_te)
            gecerli_adaylar.append((model,acc,meta,isim))
        except (ValueError, AttributeError, TypeError) as e:
            log.warning(f"[STACKING] {isim} atlandı: {e}")
    if len(gecerli_adaylar) < 2: return None, 0, {}
    # L2 meta-learner
    min_len = min(len(p) for p in meta_features_tr)
    X_meta_tr = np.column_stack([p[:min_len] for p in meta_features_tr])
    X_meta_te = np.column_stack([p for p in meta_features_te])
    y_meta_tr = y_l1_te = y_tr.iloc[-min_len:].values if hasattr(y_tr,'iloc') else y_tr[-min_len:]
    meta_learner = LogisticRegression(C=1.0,max_iter=1000,random_state=42)
    try:
        meta_learner.fit(X_meta_tr,y_meta_tr)
        # Stacking wrapper objesi
        wrapper = StackingWrapper(gecerli_adaylar,meta_learner)
        acc = accuracy_score(y_te,wrapper.predict(X_te))
        log.info(f"[STACKING/{sembol}] acc={acc:.3f} ({len(gecerli_adaylar)} model)")
        model_kaydet(wrapper, f"stacking_{sembol.replace('-','_')}")
        return wrapper, acc, {"type":"stacking","n_models":len(gecerli_adaylar)}
    except (ValueError, AttributeError) as e:
        log.warning(f"[STACKING] Meta-learner hatası: {e}"); return None, 0, {}

# ── Temporal Fusion Transformer (TFT) ────────────────────
# v21: LSTM iskeletinde MultiHeadAttention import'u vardı ama kullanılmıyordu.
# Gerçek TFT mimarisi: çoklu zaman serisi + statik feature → attention → tahmin.
# LSTM'ye göre: rejim geçişlerinde daha hızlı uyum, feature önem haritası.
#
# Mimari (basitleştirilmiş production TFT):
#   Input → Variable Selection (Gating) → Encoder (LSTM) →
#   Multi-Head Attention → Add & Norm → Feed Forward → Çıktı

def _tft_model_olustur(lookback: int, n_features: int,
                         d_model: int = 64, n_heads: int = 4,
                         dropout: float = 0.1) -> "Model":
    """
    Production TFT mimarisi.
    d_model: attention boyutu (64 = dengeli hız/kalite)
    n_heads: attention başlıkları (4 = 16-boyutlu her başlık)
    """
    if not KERAS_AVAILABLE:
        return None
    from tensorflow.keras.layers import (
        Dense, LSTM, Dropout, BatchNormalization,
        MultiHeadAttention, LayerNormalization,
        GlobalAveragePooling1D, Multiply, Activation,
        Add, Flatten, Reshape
    )
    from tensorflow.keras.models import Model
    from tensorflow.keras import Input
    import tensorflow as tf

    inp = Input(shape=(lookback, n_features), name="tft_input")

    # ── Variable Selection Network (Gating) ──────────────
    # Her feature için önem ağırlığı öğren
    gate = Dense(n_features, activation="sigmoid", name="vsel_gate")(inp)
    selected = Multiply(name="vsel_out")([inp, gate])

    # ── Encoder: LSTM ────────────────────────────────────
    enc = LSTM(d_model, return_sequences=True, name="enc_lstm")(selected)
    enc = Dropout(dropout)(enc)
    enc = BatchNormalization()(enc)

    # ── Multi-Head Self-Attention ─────────────────────────
    attn_out, attn_weights = MultiHeadAttention(
        num_heads=n_heads, key_dim=d_model // n_heads,
        dropout=dropout, name="mha"
    )(enc, enc, return_attention_scores=True)

    # ── Add & Norm (Residual) ─────────────────────────────
    attn_out = Add()([enc, attn_out])
    attn_out = LayerNormalization(epsilon=1e-6)(attn_out)

    # ── Point-wise Feed Forward ───────────────────────────
    ff = Dense(d_model * 2, activation="relu")(attn_out)
    ff = Dropout(dropout)(ff)
    ff = Dense(d_model)(ff)
    ff = Add()([attn_out, ff])
    ff = LayerNormalization(epsilon=1e-6)(ff)

    # ── Output ────────────────────────────────────────────
    pooled = GlobalAveragePooling1D()(ff)
    out    = Dense(32, activation="relu")(pooled)
    out    = Dropout(dropout)(out)
    out    = Dense(1, activation="sigmoid", name="output")(out)

    model = Model(inputs=inp, outputs=out, name="TFT_v21")
    model.compile(
        optimizer="adam",
        loss="binary_crossentropy",
        metrics=["accuracy"],
    )
    return model


def tft_egit_ve_kaydet(X: pd.DataFrame, y: pd.Series,
                         sembol: str, lookback: int = LOOKBACK) -> tuple:
    """
    TFT eğitimi — çoklu feature + zaman penceresi.
    LSTM'den farkı: tüm feature'lar (close değil, full feature set) kullanılır.
    Attention haritası hangi zaman adımının önemli olduğunu gösterir.

    Returns: (model, accuracy, scaler) veya (None, 0, None)
    """
    if not KERAS_AVAILABLE:
        log.debug("[TFT] Keras yüklü değil — atlandı")
        return None, 0, None
    if len(X) < lookback + 50:
        log.debug(f"[TFT/{sembol}] Yetersiz veri ({len(X)} < {lookback+50})")
        return None, 0, None

    try:
        import tensorflow as tf
        tf.get_logger().setLevel("ERROR")

        scaler = StandardScaler()
        X_s = scaler.fit_transform(X.values)
        n_feat = X_s.shape[1]

        # Zaman pencereli diziler oluştur
        Xs, ys = [], []
        for i in range(lookback, len(X_s)):
            Xs.append(X_s[i - lookback:i])
            ys.append(int(y.iloc[i]))
        Xs = np.array(Xs)   # (N, lookback, n_features)
        ys = np.array(ys)

        # Train / Val split (zaman sırası korunarak)
        split = int(len(Xs) * 0.8)
        X_tr, X_val = Xs[:split], Xs[split:]
        y_tr, y_val = ys[:split], ys[split:]

        model = _tft_model_olustur(lookback, n_feat)
        if model is None:
            return None, 0, None

        history = model.fit(
            X_tr, y_tr,
            validation_data=(X_val, y_val),
            epochs=40,
            batch_size=32,
            verbose=0,
            callbacks=[
                EarlyStopping(patience=6, restore_best_weights=True,
                               monitor="val_accuracy"),
                ReduceLROnPlateau(patience=3, factor=0.5, verbose=0),
            ],
        )

        preds  = (model.predict(X_val, verbose=0).flatten() >= 0.5).astype(int)
        acc    = float(accuracy_score(y_val, preds))

        isim = f"tft_{sembol.replace('-','_')}"
        yol  = os.path.join(MODEL_DIR, f"{isim}.keras")
        model.save(yol)
        scaler_kaydet(scaler, isim)

        val_acc = max(history.history.get("val_accuracy", [acc]))
        log.info(f"[TFT/{sembol}] Eğitim tamamlandı — "
                 f"val_acc={acc:.3f} best={val_acc:.3f} "
                 f"features={n_feat} lookback={lookback}")
        performans_kaydet(sembol, "TFT_v21", acc)
        return model, acc, scaler

    except Exception as e:
        log.error(f"[TFT/{sembol}] Eğitim hatası: {type(e).__name__}: {e}")
        return None, 0, None


def tft_tahmin_yap(X_son_satirlar: pd.DataFrame,
                    sembol: str, lookback: int = LOOKBACK) -> dict:
    """
    TFT ile son lookback satırdan tahmin üret.
    X_son_satirlar: feature_olustur çıktısının son (lookback) satırı

    Returns: {prob: float, tahmin: int, aktif: bool}
    """
    if not KERAS_AVAILABLE:
        return {"prob": 0.5, "tahmin": 0, "aktif": False}

    isim = f"tft_{sembol.replace('-', '_')}"
    yol  = os.path.join(MODEL_DIR, f"{isim}.keras")

    try:
        if not os.path.exists(yol):
            return {"prob": 0.5, "tahmin": 0, "aktif": False}

        model  = load_model(yol, compile=False)
        scaler = scaler_yukle(isim)
        if scaler is None:
            return {"prob": 0.5, "tahmin": 0, "aktif": False}

        if len(X_son_satirlar) < lookback:
            return {"prob": 0.5, "tahmin": 0, "aktif": False}

        X_scaled = scaler.transform(X_son_satirlar.values[-lookback:])
        X_inp    = X_scaled.reshape(1, lookback, -1)
        with _tf_lock:   # v23: thread-safe inference
            prob = float(model.predict(X_inp, verbose=0)[0][0])
        tahmin   = 1 if prob >= 0.5 else 0

        return {"prob": round(prob, 4), "tahmin": tahmin, "aktif": True}

    except Exception as e:
        log.warning(f"[TFT/{sembol}] Tahmin hatası: {e}")
        return {"prob": 0.5, "tahmin": 0, "aktif": False}


# ── LSTM + Attention ──────────────────────────────────────
def lstm_egit_ve_kaydet(close: pd.Series, sembol: str, lookback: int = LOOKBACK) -> tuple:
    if not KERAS_AVAILABLE or len(close) < lookback+50: return None, None
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(close.values.reshape(-1,1))
    X_l,y_l=[],[]
    for i in range(lookback,len(scaled)):
        X_l.append(scaled[i-lookback:i,0]); y_l.append(scaled[i,0])
    X_l=np.array(X_l).reshape(-1,lookback,1); y_l=np.array(y_l)
    model=Sequential([
        LSTM(128,return_sequences=True,input_shape=(lookback,1)),
        Dropout(0.2), BatchNormalization(),
        LSTM(64,return_sequences=True),
        Dropout(0.2),
        LSTM(32), Dropout(0.2),
        Dense(16,activation="relu"), Dense(1)
    ])
    model.compile(optimizer="adam",loss="huber")
    model.fit(X_l,y_l,epochs=60,batch_size=32,verbose=0,
              callbacks=[EarlyStopping(patience=8,restore_best_weights=True),
                         ReduceLROnPlateau(patience=4,factor=0.5,verbose=0)])
    yol=os.path.join(MODEL_DIR,f"lstm_{sembol.replace('-','_')}.keras")
    model.save(yol); scaler_kaydet(scaler,f"lstm_{sembol.replace('-','_')}")
    log.info(f"[LSTM/{sembol}] eğitildi ve kaydedildi")
    return model, scaler

def lstm_tahmin_yap(close: pd.Series, sembol: str, lookback: int = LOOKBACK):
    if not KERAS_AVAILABLE: return None
    yol=os.path.join(MODEL_DIR,f"lstm_{sembol.replace('-','_')}.keras")
    model=load_model(yol) if os.path.exists(yol) else None
    scaler=scaler_yukle(f"lstm_{sembol.replace('-','_')}")
    if model is None or scaler is None:
        model,scaler=lstm_egit_ve_kaydet(close,sembol,lookback)
    if model is None: return None
    try:
        scaled=scaler.transform(close.values[-lookback:].reshape(-1,1))
        X_input=scaled.reshape(1,lookback,1)
        with _tf_lock:   # v23: thread-safe inference
            tahmin=scaler.inverse_transform(model.predict(X_input,verbose=0))
        return round(float(tahmin[0][0]),2)
    except (ValueError, OSError, RuntimeError) as e:
        log.error(f"LSTM tahmin hatası: {e}"); return None

# ── Feedback Loop ─────────────────────────────────────────
def feedback_ekle(sembol: str, features: dict, gercek_sonuc: int, pnl_pct: float = 0):
    """Feedback kaydeder. MAX_FEEDBACK_KAYIT aşılırsa eski kayıtlar temizlenir."""
    fb_path = os.path.join(MODEL_DIR, f"feedback_{sembol.replace('-','_')}.jsonl")
    satir = {"features": features, "target": gercek_sonuc, "pnl_pct": pnl_pct,
             "ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}
    try:
        # MAX_FEEDBACK_KAYIT kontrolü
        try:
            from config import MAX_FEEDBACK_KAYIT
        except ImportError:
            MAX_FEEDBACK_KAYIT = 1000
        if os.path.exists(fb_path):
            with open(fb_path) as f:
                satirlar = f.readlines()
            if len(satirlar) >= MAX_FEEDBACK_KAYIT:
                # Son %80'ini tut
                koru = int(MAX_FEEDBACK_KAYIT * 0.8)
                with open(fb_path, "w") as f:
                    f.writelines(satirlar[-koru:])
                log.info(f"[FEEDBACK] {sembol} {len(satirlar)}→{koru} kayıt (max:{MAX_FEEDBACK_KAYIT})")
        with open(fb_path, "a") as f:
            f.write(json.dumps(satir) + "\n")
    except (OSError, ValueError) as e:
        log.warning(f"[FEEDBACK] Yazma hatası: {e}")

# Feedback cache — her döngüde disk okumayı önler
_fb_cache: dict = {}          # {sembol: (mtime, [satirlar])}
_fb_cache_lock = __import__("threading").Lock()

def feedback_veri_yukle(sembol: str, X: pd.DataFrame, y: pd.Series) -> tuple:
    fb_path=os.path.join(MODEL_DIR,f"feedback_{sembol.replace('-','_')}.jsonl")
    if not os.path.exists(fb_path): return X, y
    try:
        # Cache: dosya değişmediyse yeniden okuma
        mtime = os.path.getmtime(fb_path)
        with _fb_cache_lock:
            if sembol in _fb_cache and _fb_cache[sembol][0] == mtime:
                satirlar = _fb_cache[sembol][1]
            else:
                satirlar=[]
                with open(fb_path) as f:
                    for line in f:
                        line=line.strip()
                        if line: satirlar.append(json.loads(line))
                satirlar=satirlar[-500:]
                _fb_cache[sembol] = (mtime, satirlar)
        kayitlar=[s for s in satirlar if "features" in s and "target" in s]
        if not kayitlar: return X, y
        df_fb=pd.DataFrame([{**k["features"],"Target":k["target"]} for k in kayitlar])
        ortak=[c for c in X.columns if c in df_fb.columns]
        if not ortak: return X, y
        X_fb=df_fb[ortak].dropna()
        y_fb=df_fb.loc[X_fb.index,"Target"]
        X_birles=pd.concat([X,X_fb],ignore_index=True)
        y_birles=pd.concat([y,y_fb],ignore_index=True)
        log.info(f"[FEEDBACK/{sembol}] {len(X_fb)} kayıt eğitime eklendi")
        return X_birles, y_birles
    except (OSError, ValueError, KeyError) as e:
        log.warning(f"[FEEDBACK] Yükleme hatası: {e}"); return X, y

# ── Ana Fonksiyon ─────────────────────────────────────────
def en_iyi_model_yukle_veya_egit(X: pd.DataFrame, y: pd.Series,
                                   sembol: str, yeniden_egit_suresi: int = 3600) -> tuple:
    # v58 (K-18): feedback ARTIK BURADA EKLENMİYOR.
    # Eskiden `X, y = feedback_veri_yukle(sembol, X, y)` satırı feedback'i
    # verinin sonuna ekliyordu; alttaki her eğitici `shuffle=False` ile son
    # %20'yi test yaptığı için TEST SETİ tamamen feedback oluyordu ve
    # accuracy 0.52 yerine 0.96 raporlanıyordu. Feedback artık
    # `egitim_test_bol()` içinde YALNIZCA train'e ekleniyor.
    isim_base = sembol.replace("-","_")
    adaylar   = []

    for prefix, egitim_fn in [
        (f"rf_{isim_base}",  lambda: rf_egit(X,y,sembol)),
        (f"xgb_{isim_base}", lambda: xgb_egit(X,y,sembol)),
        (f"lgb_{isim_base}", lambda: lgb_egit(X,y,sembol)),
        (f"gb_{isim_base}",  lambda: gb_egit(X,y,sembol)),
    ]:
        yas=model_yasi(prefix)
        if yas < yeniden_egit_suresi:
            model=model_yukle(prefix)
            if model is not None:
                _,X_te,_,y_te=train_test_split(X,y,test_size=0.2,shuffle=False)
                try:
                    acc=accuracy_score(y_te,model.predict(X_te))
                    # ── v58 (K-55): TAZE MODEL ARTIK KOŞULSUZ ADAY ──────
                    # Eskiden `acc < MIN_USEFUL_ACC` ise model TAZE OLSA
                    # BİLE atılıp YENİDEN EĞİTİLİYORDU. Yeni model de
                    # gürültü olduğu için genelde yine eşiği geçemiyor →
                    # HER ÇAĞRIDA yeniden eğitim.
                    #
                    # ÖLÇÜM: son 2 saatte 525 `[SKIP]`. `/btc` komutu tek
                    # başına 75 sn sürüyordu; o sürede 11 SKIP, 11 model
                    # kaydı, 8 Optuna koşusu, 1 TFT. Kullanıcının CPU
                    # şikâyetinin ve komut gecikmesinin kaynağı buydu.
                    #
                    # NEDEN GÜVENLİ — davranış DEĞİŞMİYOR:
                    # K-37 sonrası 634 model seçiminin **0**'ında beceri
                    # anlamlı çıktı (1284 nötrleme). Model katkısı her
                    # durumda 50.0 (nötr) olduğu için HANGİ modelin
                    # seçildiği sinyali ETKİLEMİYOR. Yani eşik bir koruma
                    # sağlamıyor, yalnızca maliyet üretiyordu.
                    #
                    # Gerçek koruma K-37'de: beceri belirsizlikten büyük
                    # değilse güven zaten nötrleniyor. Seçim de WF
                    # BECERİSİYLE yapılıyor (K-37), ham accuracy ile değil.
                    # acc yine loglanıyor ama SEÇMİYOR ve ELEMİYOR.
                    adaylar.append((model,acc,{"wf":wf_yukle(prefix)},prefix))
                    if acc < MIN_USEFUL_ACC:
                        log.info(f"[MODEL] {prefix} acc={acc:.3f} < "
                                 f"{MIN_USEFUL_ACC} — aday olarak KALIYOR "
                                 f"(seçim WF becerisiyle, K-55)")
                    continue
                except (ValueError, AttributeError, OSError): pass
        # v55: Tek bir eğiticinin çökmesi TÜM sembolün model seçimini iptal
        # etmemeli (gb_egit/lgb_egit'in iç hata yönetimi yok).
        try:
            model,acc,meta=egitim_fn()
        except Exception as _ee:
            log.error(f"[MODEL/{sembol}] {prefix} eğitim hatası: "
                      f"{type(_ee).__name__}: {_ee}")
            continue
        # v58 (K-55): yeni eğitilen model de koşulsuz aday. Eşik hem
        # eleme yapıyor hem de yukarıdaki yeniden-eğitim döngüsünü
        # besliyordu; seçim WF becerisine bağlı (K-37) ve beceri yoksa
        # güven nötrleniyor — eleme gereksiz.
        if model is not None:
            adaylar.append((model,acc,meta,prefix))

    # v21: TFT aday — 6 saatte bir yeniden eğit (ağır model)
    tft_prefix = f"tft_{isim_base}"
    tft_yas    = model_yasi(tft_prefix)
    if KERAS_AVAILABLE:
        if tft_yas < max(yeniden_egit_suresi, 21600):  # min 6 saatte bir
            # Mevcut TFT'yi yükle ve değerlendir
            tft_yol = os.path.join(MODEL_DIR, f"{tft_prefix}.keras")
            if os.path.exists(tft_yol):
                try:
                    _tft_m = load_model(tft_yol, compile=False)
                    _tft_sc= scaler_yukle(tft_prefix)
                    if _tft_sc is not None:
                        # Wrapper: sklearn predict_proba arayüzü
                        class _TFTWrapper:
                            def __init__(self, m, sc, lk):
                                self._m=m; self._sc=sc; self._lk=lk
                            def predict(self, Xb):
                                return (self.predict_proba(Xb)[:,1]>=0.5).astype(int)
                            def predict_proba(self, Xb):
                                # v23: per-row loop yerine BATCH inference (200x hızlanma)
                                arr = Xb.values if hasattr(Xb,'values') else np.asarray(Xb)
                                n = len(arr)
                                if n < self._lk:
                                    return np.column_stack([np.full(n,0.5),np.full(n,0.5)])
                                Xs = self._sc.transform(arr)
                                # Kayan pencereleri tek tensöre yığ
                                pencereler = []
                                idx_map    = []
                                for i in range(n):
                                    if i < self._lk - 1:
                                        idx_map.append(None)   # yeterli geçmiş yok
                                    else:
                                        pencereler.append(Xs[i-self._lk+1:i+1])
                                        idx_map.append(len(pencereler)-1)
                                preds = np.full(n, 0.5)
                                if pencereler:
                                    batch = np.stack(pencereler)  # (M, lookback, feat)
                                    with _tf_lock:   # v23: thread-safe inference
                                        p_batch = self._m.predict(batch, verbose=0, batch_size=256).flatten()
                                    for i, mi in enumerate(idx_map):
                                        if mi is not None:
                                            preds[i] = p_batch[mi]
                                return np.column_stack([1-preds, preds])
                        wrapper=_TFTWrapper(_tft_m, _tft_sc, LOOKBACK)
                        _,X_te,_,y_te=train_test_split(X,y,test_size=0.2,shuffle=False)
                        try:
                            tft_acc=accuracy_score(y_te,wrapper.predict(X_te))
                            # v58 (K-55): eşik ELEMİYOR (bkz. yukarıdaki
                            # gerekçe). Seçim WF becerisiyle, beceri yoksa
                            # güven zaten nötrleniyor (K-37).
                            adaylar.append((wrapper,tft_acc,{"type":"TFT"},tft_prefix))
                            log.info(f"[TFT/{sembol}] Mevcut model yüklendi acc={tft_acc:.3f}")
                        except Exception as _te: log.debug(f"[TFT] eval: {_te}")
                except Exception as _te: log.debug(f"[TFT] yükleme: {_te}")
        else:
            # TFT yeniden eğit (background'da — ağır)
            # v29: Aynı coin için eşzamanlı TFT eğitimini engelle (.keras race fix)
            import threading as _thr
            with _tft_retrain_lock:
                if sembol in _tft_retrain_aktif:
                    log.debug(f"[TFT/{sembol}] zaten eğitiliyor — atlandı")
                else:
                    _tft_retrain_aktif.add(sembol)
                    def _tft_retrain():
                        try:
                            tft_m, tft_acc, tft_sc = tft_egit_ve_kaydet(X, y, sembol, LOOKBACK)
                            log.info(f"[TFT/{sembol}] Retrain tamamlandı acc={tft_acc:.3f}")
                        except Exception as _e:
                            log.error(f"[TFT/{sembol}] retrain hatası: {_e}")
                        finally:
                            with _tft_retrain_lock:
                                _tft_retrain_aktif.discard(sembol)
                    _thr.Thread(target=_tft_retrain, daemon=True, name=f"tft_{sembol}").start()
            # v55 denetimi: burada `adaylar.append((model,acc,meta,prefix))` vardı.
            # Bu değişkenler TFT'ye değil, yukarıdaki klasik model döngüsünden
            # ARTAKALAN son iterasyona (gb_egit) aitti. İki hataya yol açıyordu:
            #   1) gb zaten eklenmişse aynı model ensemble'a İKİ KEZ giriyordu,
            #   2) gb başarısızsa (None,0,{}) listeye giriyor ve `max()` ile
            #      "en iyi model" olarak None seçilebiliyordu → AttributeError.
            # Klasik modeller döngü içinde zaten doğru eklendiği için satır kaldırıldı.

    if not adaylar:
        for prefix in [f"xgb_{isim_base}",f"lgb_{isim_base}",f"rf_{isim_base}"]:
            m=model_yukle(prefix)
            if m is not None:
                _,X_te,_,y_te=train_test_split(X,y,test_size=0.2,shuffle=False)
                try:
                    acc=accuracy_score(y_te,m.predict(X_te))
                    return m,acc,{},"fallback"
                except (ValueError, AttributeError, OSError): pass
        return None,0,{},"Yok"

    # ── v58 (K-20): SEÇİM WALK-FORWARD İLE ──────────────────────
    # Eskiden `max(adaylar, key=acc)` kullanılıyordu. `acc` tek bir
    # hold-out bölünmesinden gelir; 195 satırlık bir testte varyansı
    # yüksektir ve K-18 öncesinde tamamen sahteydi. Walk-forward ise
    # 8 katmanda yalnızca geçmişle eğitip geleceğe bakar.
    # test_acc HÂLÂ raporlanıyor (log + registry) ama SEÇMİYOR.
    for _m, _a, _meta, _p in adaylar:
        log.info(f"[ADAY/{sembol}] {_p} test_acc={_a:.3f} "
                 f"WF={_wf_ortalama(_meta):.3f}")

    # Stacking dene
    if len(adaylar) >= 2:
        s_model,s_acc,s_meta=stacking_ensemble_olustur(X,y,sembol,adaylar)
        # v58 (K-55): stacking adaylığı da eşiksiz — aynı gerekçe.
        if s_model is not None:
            en_iyi_tekil=max(adaylar,key=lambda x:_wf_ortalama(x[2]))
            # Stacking'in kendi WF'si yok (bileşik model); en iyi tekilin
            # WF'sini geçemiyorsa tekili tercih et. Eşik acc üzerinden
            # değil, tekilin test_acc'siyle karşılaştırılıyor — stacking
            # için elimizdeki tek ortak ölçü bu.
            if s_acc >= en_iyi_tekil[1]-0.005:
                log.info(f"[STACKING/{sembol}] seçildi acc={s_acc:.3f} "
                         f"(tekil en iyi WF={_wf_ortalama(en_iyi_tekil[2]):.3f})")
                return s_model,s_acc,s_meta,f"stacking_{isim_base}"

    # ── v58 (K-37): SEÇİM HAM ACCURACY DEĞİL, BECERİ İLE ─────────
    # K-20 seçimi WF'ye bağlamıştı ama WF'nin HAM ortalamasına bakıyordu.
    # Sınıf dengesi katmanlar arasında %50.1–%53.5 oynuyor; ham accuracy
    # bu yüzden modelleri karşılaştırmaz. Ölçüm: 40 katmanın %25'inde
    # taban çizgisi 0.52'nin ÜSTÜNDE — orada "eşiği geçen" model sabit
    # tahminciden kötüydü ve yine de seçilebiliyordu.
    # beceri = accuracy − çoğunluk sınıfı taban çizgisi (katman başına).
    if any("beceri_ort" in ((a[2] or {}).get("wf") or {}) for a in adaylar):
        en_iyi=max(adaylar,key=lambda x:_wf_beceri(x[2]))
        olcut=(f"beceri={_wf_beceri(en_iyi[2]):+.4f}"
               f"±{_wf_beceri_std(en_iyi[2]):.4f}")
    elif any(_wf_ortalama(a[2]) > 0 for a in adaylar):
        # Eski format WF dosyası (beceri alanı yok) — yeniden eğitilene
        # kadar ham ortalamaya düşüyoruz, ama SESSİZ DEĞİL (§5.2).
        en_iyi=max(adaylar,key=lambda x:_wf_ortalama(x[2]))
        olcut=f"WF={_wf_ortalama(en_iyi[2]):.3f} (ESKİ FORMAT)"
        log.warning(f"[MODEL/{sembol}] WF dosyalarında beceri alanı yok — "
                    f"seçim ham accuracy'ye düştü (K-37 öncesi format). "
                    f"Model yeniden eğitilince düzelir.")
    else:
        en_iyi=max(adaylar,key=lambda x:x[1])
        olcut="WF yok → test_acc"
        log.warning(f"[MODEL/{sembol}] hiçbir adayda WF yok — seçim "
                    f"test_acc'ye düştü (tek hold-out, varyansı yüksek)")
    anlamli = model_beceri_anlamli_mi(en_iyi[2])
    log.info(f"[MODEL/{sembol}] seçildi: {en_iyi[3]} "
             f"test_acc={en_iyi[1]:.3f} {olcut} "
             f"anlamlı={'EVET' if anlamli else 'HAYIR'}")
    if not anlamli:
        # Sesli olmak ŞART: bu durumda modelin katkısı main.py'da
        # nötrleniyor. Sessiz kalsaydı "model çalışıyor" sanılırdı.
        log.warning(f"[MODEL/{sembol}] {en_iyi[3]} becerisi kendi "
                    f"belirsizliğinden büyük DEĞİL "
                    f"({_wf_beceri(en_iyi[2]):+.4f} ≤ "
                    f"{_wf_beceri_std(en_iyi[2]):.4f}) → güven nötrlenecek")
    return en_iyi[0],en_iyi[1],en_iyi[2],en_iyi[3]
