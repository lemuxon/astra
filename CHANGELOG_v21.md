# ASTRA v21.0 — AŞAMA 4: TFT + PPO/RL + A/B TEST

## Tarih: 2026-05-29 | Temel: v20.0

---

## 🔬 Güncelleme 1 — Temporal Fusion Transformer (engines/model_engine.py)

### Eski Durum
model_engine.py'de `MultiHeadAttention` import'u vardı ama hiçbir yerde
kullanılmıyordu. "TFT (basit)" yorum satırında kalıyordu.

### Yeni: Gerçek TFT Mimarisi
```
Input → Variable Selection (Sigmoid Gate) → LSTM Encoder →
Multi-Head Attention (4 head, 64 dim) → Add & Norm →
Feed Forward → GAP → Output (sigmoid)
```

**`_tft_model_olustur(lookback, n_features)`** — Keras Model
**`tft_egit_ve_kaydet(X, y, sembol)`** — Full feature matrix üzerinde eğitim

Variable Selection Network: Her feature için sigmoid gate → önemli
feature'ları otomatik seçer, gereksizleri bastırır.

**Ensemble entegrasyonu:** TFT `en_iyi_model_yukle_veya_egit` adaylarına eklendi.
sklearn-uyumlu `_TFTWrapper` ile `predict_proba` arayüzü sağlandı.

**6 saatlik retrain:** Batch'ten çok daha ağır (30-60s), background thread'de.

**`/tft BTCUSDT`** komutu: Manuel eğitim tetikler, acc döner.

---

## 🤖 Güncelleme 2 — PPO/RL Ajanı (simulation/rl_environment.py)

### Eski Durum
`exchange_simulator.py` tam olarak RL ortamı için hazırdı ama bağlı
bir RL ajanı yoktu. `_rl_rewards` sadece istatistik topluyordu.

### Yeni: Gymnasium Ortamı + PPO Ajanı

**`AstraFuturesEnv`** — Gymnasium uyumlu:
- Observation: 20 feature + [pnl_pct, poz_yon, drawdown, ep_norm]
- Action: 0=WAIT, 1=LONG, 2=SHORT, 3=CLOSE
- Reward: Sharpe benzeri risk-adjusted PnL − drawdown cezası

**`rl_ajan_egit()`** — PPO (Stable-Baselines3):
- n_steps=100k (gece eğitim, background thread)
- saved_models/rl/ klasörüne kaydedilir

**`rl_tahmin()`** — Canlı aksiyon tahmini (deterministic)

**Haftalık otomatik yeniden eğitim:** `dongu % 1008` → BTC + ETH'de PPO güncellenir.

**`rl_aksiyon`** artık `sonuc` dict'inde — future entegrasyon için hazır.

**Kurulum:** `pip install stable-baselines3 gymnasium`
Yüklü değilse: sessizce devre dışı.

---

## 🧪 Güncelleme 3 — A/B Test Çerçevesi (engines/ab_test.py)

### Eski Durum
Strateji karşılaştırması sistematik değildi. Hangi parametrenin
daha iyi çalıştığını bilmek için manuel takip gerekiyordu.

### Yeni: İstatistiksel A/B Test

**Varyant atama:** `MD5(sembol + dongu) % 2` → deterministik, tekrarlanabilir.
Aynı sinyal her zaman aynı gruba düşer.

**İstatistiksel test:** Mann-Whitney U (parametrik olmayan, küçük örneklem uyumlu)
- p < 0.05 → istatistiksel anlamlı fark var
- Etki büyüklüğü: rank-biserial correlation
- Min 30 işlem gerekli

**`_on_position_closed`'a entegre:** Her kapanan işlem otomatik kaydedilir.

**`/abtest`** Telegram komutu: Anlık karşılaştırma raporu:
```
[A] Mevcut_Strateji 🏆 (n=87)
  WR:%54.0 | PnL:+0.823% | Sharpe:+1.24
[B] TFT_Stratejisi (n=89)
  WR:%51.0 | PnL:+0.571% | Sharpe:+0.91
Mann-Whitney U | p=0.0312 | ✅ Anlamlı fark
Kazanan: Mevcut_Strateji (etki=0.18)
```

**Her 2 saatte otomatik rapor** → Telegram'a gönderilir.

---

## Etkilenen / Eklenen Dosyalar
| Dosya | Değişim |
|-------|---------|
| `engines/model_engine.py` | TFT mimarisi + `_TFTWrapper` + ensemble entegrasyonu |
| `simulation/rl_environment.py` | **YENİ** — AstraFuturesEnv + PPO trainer |
| `engines/ab_test.py` | **YENİ** — A/B test framework + Mann-Whitney |
| `main.py` | TFT/RL/A/B imports, sonuc dict, position_closed, /tft /abtest komutları |
| `requirements.txt` | stable-baselines3, gymnasium eklendi |

---

## Kurulum (Opsiyonel)
```bash
pip install stable-baselines3>=2.2.0 gymnasium>=0.29.0
```
Bu kütüphaneler yüklü değilse TFT eğitimi ve RL ajanı devre dışı kalır,
bot sorunsuz çalışmaya devam eder.
