# =========================================================
# ASTRA v30.0 — RL ORTAMI (Gymnasium + Stable-Baselines3)
# ExchangeSimulator üzerine inşa edilmiş Gymnasium env.
#
# Durum (Observation):
#   coin_analiz feature'larından türetilen 20 boyutlu vektör
#   + açık pozisyon bilgisi + PnL durumu
#
# Aksiyon:
#   0 = WAIT, 1 = LONG, 2 = SHORT, 3 = CLOSE
#
# Ödül:
#   risk-adjusted PnL (Sharpe benzeri)
#   + drawdown cezası
#   + işlem maliyeti cezası
#
# Kullanım:
#   1. Gece eğitim: rl_ajan_egit(sembol, n_steps=500_000)
#   2. Gündüz canlı: rl_tahmin(features_dict) → aksiyon
#   3. Her 7 günde bir otomatik yeniden eğitim
#
# stable-baselines3 yüklü değilse sessizce devre dışı.
# =========================================================
import logging, os, time
from pathlib import Path
from typing import Optional, Dict, Tuple
import numpy as np

log = logging.getLogger("ASTRA.RL")
import threading as _rl_threading
_rl_egitim_aktif: set = set()        # v29: eşzamanlı RL eğitimi engelleme
_rl_egitim_lock = _rl_threading.Lock()

RL_MODEL_DIR = "saved_models/rl"
Path(RL_MODEL_DIR).mkdir(parents=True, exist_ok=True)

try:
    import gymnasium as gym
    from gymnasium import spaces
    GYMNASIUM_AVAILABLE = True
except ImportError:
    try:
        import gym
        from gym import spaces
        GYMNASIUM_AVAILABLE = True
    except ImportError:
        GYMNASIUM_AVAILABLE = False

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv
    SB3_AVAILABLE = True
except ImportError:
    SB3_AVAILABLE = False

if not (GYMNASIUM_AVAILABLE and SB3_AVAILABLE):
    log.warning("[RL] stable-baselines3 veya gymnasium yüklü değil. "
                "'pip install stable-baselines3 gymnasium' ile ekleyin. "
                "RL ajanı devre dışı.")

# ── Feature normalizasyon sabitleri ──────────────────────
FEATURE_KEYS = [
    "RSI", "Stoch_RSI", "Williams_R", "CCI", "MACD", "MACD_Hist",
    "ATR_pct", "BB_Width", "Volume_Ratio", "ADX", "DI_Diff",
    "EMA9_21_cross", "SuperTrend_Dir", "Momentum_5", "Momentum_20",
    "Price_EMA50", "Price_EMA200", "OBV_Diff", "CVD_Norm", "CVD_Momentum",
]
OBS_DIM = len(FEATURE_KEYS) + 4  # feature'lar + [pnl_pct, pozisyon_yon, drawdown, dongu_no]


class AstraFuturesEnv:
    """
    Gymnasium-uyumlu ASTRA futures ortamı.
    ExchangeSimulator ile gerçekçi slippage + latency.
    """

    metadata = {"render_modes": []}

    def __init__(self, fiyat_serileri: np.ndarray,
                  feature_serileri: np.ndarray,
                  baslangic_bakiye: float = 10000.0,
                  komisyon_bps: float = 4.0,
                  max_kaldirac: int = 5,
                  episode_uzunluk: int = 200):
        """
        fiyat_serileri:   (T,) fiyat serisi
        feature_serileri: (T, n_features) normalize feature matrisi
        """
        if not GYMNASIUM_AVAILABLE:
            raise RuntimeError("gymnasium/gym yüklü değil")

        self.fiyatlar      = fiyat_serileri
        self.features      = feature_serileri
        self.T             = len(fiyat_serileri)   # v23 fix: bare 'fiyatlar' NameError düzeltildi
        self.baslangic     = baslangic_bakiye
        self.komisyon      = komisyon_bps / 10000
        self.max_kaldirac  = max_kaldirac
        self.ep_uzunluk    = episode_uzunluk

        # Gymnasium spaces
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0,
            shape=(OBS_DIM,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(4)  # 0=WAIT,1=LONG,2=SHORT,3=CLOSE

        self._reset_state()

    def _reset_state(self):
        self.bakiye        = self.baslangic
        self.poz_yon       = 0      # 0=yok, 1=long, -1=short
        self.giris_fiyat   = 0.0
        self.poz_usdt      = 0.0
        self.adim          = 0
        self.ep_baslangic  = np.random.randint(0, max(1, len(self.fiyatlar) - self.ep_uzunluk))
        self.zirve_bakiye  = self.baslangic
        self.toplam_islem  = 0
        self.getiriler     = []

    def reset(self, seed=None, options=None):
        self._reset_state()
        obs = self._gozlem()
        return obs, {}

    def _gozlem(self) -> np.ndarray:
        idx = self.ep_baslangic + self.adim
        idx = min(idx, len(self.features) - 1)

        feat = self.features[idx].copy()
        # Clip to observation bounds
        feat = np.clip(feat, -10.0, 10.0)

        # Ek bilgiler
        pnl_pct   = 0.0
        if self.poz_yon != 0 and self.giris_fiyat > 0:
            guncel = self.fiyatlar[idx]
            pnl_pct = (guncel - self.giris_fiyat) / self.giris_fiyat * self.poz_yon * 100

        drawdown = max(0, (self.zirve_bakiye - self.bakiye) / self.zirve_bakiye * 100)
        ep_norm  = self.adim / max(self.ep_uzunluk, 1)

        extra = np.array([
            pnl_pct / 10.0,          # normalize
            float(self.poz_yon),     # -1, 0, 1
            drawdown / 10.0,
            ep_norm,
        ], dtype=np.float32)

        obs = np.concatenate([feat[:len(FEATURE_KEYS)], extra]).astype(np.float32)
        return obs

    def step(self, action: int) -> Tuple:
        idx    = self.ep_baslangic + self.adim
        fiyat  = self.fiyatlar[min(idx, len(self.fiyatlar) - 1)]
        odul   = 0.0
        bitti  = False

        # ── Aksiyon işle ─────────────────────────────────
        if action == 1 and self.poz_yon == 0:      # LONG aç
            self.poz_yon     = 1
            self.giris_fiyat = fiyat * (1 + self.komisyon)
            self.poz_usdt    = self.bakiye * 0.1 * self.max_kaldirac
            self.toplam_islem+= 1
            odul -= 0.5   # işlem maliyeti cezası

        elif action == 2 and self.poz_yon == 0:    # SHORT aç
            self.poz_yon     = -1
            self.giris_fiyat = fiyat * (1 - self.komisyon)
            self.poz_usdt    = self.bakiye * 0.1 * self.max_kaldirac
            self.toplam_islem+= 1
            odul -= 0.5

        elif action == 3 and self.poz_yon != 0:    # Kapat
            cikis_fiyat = fiyat * (1 - self.poz_yon * self.komisyon)
            pnl_pct     = (cikis_fiyat - self.giris_fiyat) / self.giris_fiyat * self.poz_yon
            pnl_usdt    = self.poz_usdt * pnl_pct
            self.bakiye += pnl_usdt
            self.zirve_bakiye = max(self.zirve_bakiye, self.bakiye)
            self.getiriler.append(pnl_pct)

            # Risk-adjusted reward: Sharpe benzeri
            if len(self.getiriler) >= 5:
                ort = np.mean(self.getiriler[-20:])
                std = np.std(self.getiriler[-20:]) + 1e-8
                odul = float(ort / std) * 10
            else:
                odul = float(pnl_pct) * 100

            # Drawdown cezası
            dd = (self.zirve_bakiye - self.bakiye) / self.zirve_bakiye
            odul -= dd * 5

            self.poz_yon = 0; self.giris_fiyat = 0.0; self.poz_usdt = 0.0
            self.toplam_islem += 1

        elif action == 0:   # WAIT
            # Açık pozisyon varsa floating PnL'i küçük ödül/ceza olarak ver
            if self.poz_yon != 0 and self.giris_fiyat > 0:
                float_pnl = (fiyat - self.giris_fiyat) / self.giris_fiyat * self.poz_yon
                odul = float_pnl * 10

        # ── Episode sonu ─────────────────────────────────
        self.adim += 1
        if self.adim >= self.ep_uzunluk or self.bakiye < self.baslangic * 0.5:
            bitti = True
            # Açık pozisyonu zorla kapat
            if self.poz_yon != 0 and self.giris_fiyat > 0:
                pnl = (fiyat - self.giris_fiyat) / self.giris_fiyat * self.poz_yon
                odul += pnl * 50

        obs = self._gozlem()
        return obs, odul, bitti, False, {}

    def render(self): pass
    def close(self): pass


# ── PPO Ajanı Eğitimi ─────────────────────────────────────
def rl_ajan_egit(fiyat_serileri: np.ndarray,
                  feature_serileri: np.ndarray,
                  sembol: str,
                  n_steps: int = 200_000,
                  baslangic_bakiye: float = 10000.0) -> bool:
    """
    PPO ajanını verilen fiyat + feature serileri üzerinde eğit.
    Gece background thread'de çalıştırılmak üzere tasarlandı.

    Returns: True = başarılı eğitim, False = başarısız/devre dışı
    """
    if not (GYMNASIUM_AVAILABLE and SB3_AVAILABLE):
        log.warning(f"[RL] {sembol} — SB3 yüklü değil, eğitim atlandı")
        return False

    if len(fiyat_serileri) < 300:
        log.warning(f"[RL] {sembol} — yetersiz veri ({len(fiyat_serileri)} < 300)")
        return False

    try:
        log.info(f"[RL] {sembol} PPO eğitimi başlıyor — {n_steps:,} adım")
        t0 = time.time()

        def _make_env():
            return AstraFuturesEnv(
                fiyat_serileri   = fiyat_serileri,
                feature_serileri = feature_serileri,
                baslangic_bakiye = baslangic_bakiye,
            )

        env = DummyVecEnv([_make_env])
        model = PPO(
            "MlpPolicy", env,
            n_steps       = 2048,
            batch_size    = 64,
            n_epochs      = 10,
            learning_rate = 3e-4,
            gamma         = 0.99,
            gae_lambda    = 0.95,
            clip_range    = 0.2,
            verbose       = 0,
        )
        model.learn(total_timesteps=n_steps)

        # Kaydet
        yol = os.path.join(RL_MODEL_DIR, f"ppo_{sembol.replace('-','_')}")
        model.save(yol)
        log.info(f"[RL] {sembol} PPO kaydedildi — süre:{time.time()-t0:.0f}s")
        return True

    except Exception as e:
        log.error(f"[RL] {sembol} eğitim hatası: {type(e).__name__}: {e}")
        return False


def rl_tahmin(features_dict: dict, sembol: str,
               poz_yon: int = 0, pnl_pct: float = 0.0,
               drawdown: float = 0.0) -> dict:
    """
    PPO ajanından aksiyon al.
    coin_analiz feature dict'ini obs vektörüne çevirir.

    Returns: {aksiyon: int, aksiyon_adi: str, prob: float, aktif: bool}
    AKSIYON: 0=WAIT, 1=LONG, 2=SHORT, 3=CLOSE
    """
    AKSIYON_ADI = {0: "WAIT", 1: "LONG", 2: "SHORT", 3: "CLOSE"}

    if not SB3_AVAILABLE:
        return {"aksiyon": 0, "aksiyon_adi": "WAIT", "prob": 0.5, "aktif": False}

    yol = os.path.join(RL_MODEL_DIR, f"ppo_{sembol.replace('-','_')}.zip")
    if not os.path.exists(yol):
        return {"aksiyon": 0, "aksiyon_adi": "WAIT", "prob": 0.5, "aktif": False}

    try:
        model = PPO.load(yol)

        # Feature vektörü oluştur
        feat = np.array([
            float(features_dict.get(k, 0.0)) for k in FEATURE_KEYS
        ], dtype=np.float32)
        feat = np.clip(feat, -10.0, 10.0)

        extra = np.array([
            pnl_pct / 10.0, float(poz_yon),
            drawdown / 10.0, 0.5,  # ep_norm = orta nokta varsay
        ], dtype=np.float32)

        obs = np.concatenate([feat, extra]).reshape(1, -1)

        aksiyon, _states = model.predict(obs, deterministic=True)
        aksiyon = int(aksiyon[0])

        return {
            "aksiyon":     aksiyon,
            "aksiyon_adi": AKSIYON_ADI.get(aksiyon, "WAIT"),
            "prob":        0.8,   # PPO deterministic — sabit güven
            "aktif":       True,
        }

    except Exception as e:
        log.warning(f"[RL] {sembol} tahmin hatası: {e}")
        return {"aksiyon": 0, "aksiyon_adi": "WAIT", "prob": 0.5, "aktif": False}


def rl_arka_plan_egitim(sembol: str, fiyat_df, feature_df,
                          baslangic_bakiye: float = 10000.0):
    """
    main.py'den çağrılır. Background thread'de PPO eğitir.
    7 günde bir tetiklenir (dongu % 1008 == 0, ~7*24*6 döngü).
    v29: Aynı coin için eşzamanlı RL eğitimi engellendi.
    """
    import threading as _thr
    with _rl_egitim_lock:
        if sembol in _rl_egitim_aktif:
            log.debug(f"[RL] {sembol} zaten eğitiliyor — atlandı")
            return
        _rl_egitim_aktif.add(sembol)

    def _egit():
        try:
            fiyatlar = fiyat_df.values.astype(np.float32) if hasattr(fiyat_df, 'values') else np.array(fiyat_df, dtype=np.float32)
            features = feature_df.values.astype(np.float32) if hasattr(feature_df, 'values') else np.array(feature_df, dtype=np.float32)
            # v23: feature_olustur NaN satırları düşürür → fiyat & feature uzunlukları farklı olabilir.
            # Son N satırı hizala (env idx eşleşmesi için zorunlu).
            n_align = min(len(fiyatlar), len(features))
            if n_align < 300:
                log.warning(f"[RL ARKA PLAN] {sembol} hizalama sonrası yetersiz veri ({n_align})")
                return
            fiyatlar = fiyatlar[-n_align:]
            features = features[-n_align:]
            # Feature sayısını OBS_DIM - 4 ile eşitle
            n_feat = len(FEATURE_KEYS)
            if features.shape[1] > n_feat:
                features = features[:, :n_feat]
            elif features.shape[1] < n_feat:
                pad = np.zeros((features.shape[0], n_feat - features.shape[1]), dtype=np.float32)
                features = np.hstack([features, pad])
            # NaN/inf temizle (PPO eğitimini bozar)
            features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
            fiyatlar = np.nan_to_num(fiyatlar, nan=0.0)
            rl_ajan_egit(fiyatlar, features, sembol,
                         n_steps=100_000, baslangic_bakiye=baslangic_bakiye)
        except Exception as e:
            log.error(f"[RL ARKA PLAN] {sembol}: {e}")
        finally:
            with _rl_egitim_lock:
                _rl_egitim_aktif.discard(sembol)

    _thr.Thread(target=_egit, daemon=True, name=f"rl_{sembol}").start()
    log.info(f"[RL] {sembol} arka plan eğitim başlatıldı")
