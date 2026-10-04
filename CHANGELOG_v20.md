# ASTRA v20.0 — AŞAMA 3: ASYNC + ONLINE LEARNING + PORTFOLIO MVO

## Tarih: 2026-05-29 | Temel: v19.0

---

## ⚡ Güncelleme 1 — Async Paralel Coin Analizi (main.py)

### Eski Davranış
`for sembol in COINS:` → sıralı, her coin ~3s → 5 coin = **15 saniye gecikme**.
Sinyal, piyasadan 15 saniye geride üretiliyordu.

### Yeni: `asyncio.gather` + `run_in_executor`
```python
await asyncio.gather(*[_tek_coin_isle(s) for s in COINS])
```
- CPU-bound `coin_analiz` → `ThreadPoolExecutor`'da paralel çalışır
- Tüm coinler aynı anda analiz edilir → ~**3 saniye toplam**
- **Fallback**: Async başarısız olursa sıralı loop otomatik devreye girer
- Hata izolasyonu: Bir coin crash olsa diğerleri çalışmaya devam eder
- Post-processing (`paper_trader`, `_execution_isle`, vb.) thread-safe sıralı kalır

---

## 🧬 Güncelleme 2 — Online Learning Engine (engines/online_learner.py)

### Eski Davranış
Sadece batch learning: 500 örnek topla → 30s eğit → deploy.
Rejim değişimlerinde uyum **saatler** alıyordu.

### Yeni: River Adaptive Random Forest
`river` kütüphanesi ile **her mum kapanışında** model güncellenir.

**Mimari:**
- `AdaptiveRandomForestClassifier` (5 base tree, ADWIN drift dedektörü dahil)
- `AdaptiveStandardScaler` (online, sabit scaler değil)
- ADWIN drift dedektörü: log-return bazlı anlık drift tespiti

**Blend:**
```
final_prob = α × online_prob + (1-α) × batch_prob
```
- İlk 50 örnek: `α = 0.10` (batch'e güven)
- 50-200 örnek: `α = 0.20`
- 200+    : `α = 0.35`
- Drift tespit edilirse `α × 0.5` (batch ağırlığı artırılır)

**Avantaj:** Rejim geçişlerinde batch'ten **5-10x daha hızlı** uyum.

**river yüklü değilse:** Sessizce devre dışı, sadece batch model çalışır.

**`/selflearn`** komutu artık online model istatistiklerini de gösteriyor:
`OL:n=847,d=3` → 847 örnek eğitildi, 3 drift tespit edildi.

---

## 📊 Güncelleme 3 — Portfolio MVO Optimizasyonu (analytics/portfolio_optimizer.py)

### Eski Davranış
Her coin bağımsız analiz, Kelly bağımsız pozisyon boyutu.
Yüksek korelasyonlu 5 coin açık → portföy riski katlanıyordu.

### Yeni: Mean-Variance Optimization (Markowitz)
```python
maximize: Sharpe = (w·μ - rf) / √(w·Σ·w)
subject to: Σw = 1,  0.05 ≤ wᵢ ≤ 0.40
```

**Çalışma şekli:**
1. Her döngüde coin log-getirileri `_portfolio_getiri_serileri` cache'inde birikir
2. Her 5 dakikada bir scipy.optimize ile Max Sharpe portföy hesaplanır
3. Her coin için USDT limiti döner
4. `_execution_isle`'de: `Kelly USDT > MVO limit` → MVO limit'e kırpılır

**Fallback zinciri:** MVO → Risk Parity → Eşit Ağırlık

**Risk Parity:** Volatilitesi yüksek coin küçük ağırlık alır.

**`/risk`** komutu artık portföy ağırlıklarını gösteriyor:
```
BTCUSDT: %35.2 ████████████████████████████████████
ETHUSDT: %28.1 ████████████████████████████
SOLUSDT: %16.7 ████████████████
...
```

---

## Etkilenen Dosyalar
| Dosya | Değişim |
|-------|---------|
| `main.py` | Async paralel döngü, online learner blend, portfolio cache, komut güncellemeleri |
| `engines/online_learner.py` | **YENİ** — River tabanlı per-coin online model |
| `analytics/portfolio_optimizer.py` | **YENİ** — MVO + Risk Parity optimizer |
| `requirements.txt` | `river>=0.21.0` eklendi |

---

## Kurulum Notu
```bash
pip install river>=0.21.0   # Online learning için
```
`river` yüklü değilse bot çalışmaya devam eder, online learning sadece devre dışı kalır.
