# ASTRA v18.0 — AŞAMA 1 KRİTİK GÜNCELLEMELERİ

## Tarih: 2026-05-29

---

## 🔴 Kritik #1 — Dynamic Fractional Kelly (engines/risk_manager.py)

### Sorun
`pozisyon_buyuklugu_hesapla` içindeki Kelly hesabı statik bir `win_rate`
parametresi kullanıyordu. Gerçek piyasa performansından bağımsız, her zaman
aynı pozisyon boyutu üretiyordu.

### Çözüm
**KellyEngine** sınıfı: per-coin rolling window (son 50 işlem) ile canlı
win_rate ve ortalama R:R takibi.

- `f = (W - (1-W)/R) × 0.5` — Half-Kelly formülü
- Yetersiz veri (<10 işlem) → sabit RISK_PERCENT'e güvenli düşüş
- Negatif Kelly → min pozisyon uyarısı (sistematik kayıp tespit edildi)
- Drawdown dampening: 3 kademeli (`%30 DD` → `%0.6x`, `%22.5 DD` → `%0.8x`)
- Sharpe < -0.5 ise ek `%0.7x` damp

### Yeni: Execution Kalitesi Takibi
**ExecutionKalitesi** sınıfı:
- Per-trade slippage bps hesabı (hedef fiyat vs gerçek fill)
- P95 slippage (kötü dolumları yakala)
- Fill süresi (ms) ortalaması
- `/risk` komutu artık execution kalite raporunu gösteriyor

### Yeni: Canlı Performans Metrikleri
**PerformansMetrikleri** sınıfı (rolling, batch analytics gerekmez):
- **Sharpe Ratio**: risk-adjusted getiri (yıllık ölçekli)
- **Sortino Ratio**: sadece downside volatiliteyi cezalandırır
- **Calmar Ratio**: yıllık getiri / max drawdown
- **Omega Ratio**: kazanç toplamı / kayıp toplamı
- `/risk` komutunda canlı gösteriliyor

---

## 🔴 Kritik #2 — CVD Delta (core/indicators.py + data/market_data.py)

### Sorun
Feature setinde `Taker_Ratio` (anlık oran) vardı ama kümülatif alıcı/satıcı
baskısı hiç hesaplanmıyordu. Sahte breakout tespiti eksikti.

### Çözüm
3 yeni indicator fonksiyonu:

**`hesapla_cvd_delta(df)`** — Cumulative Volume Delta (normalize, −1/+1)
- `taker_buy_base` sütunu varsa: gerçek CVD
- Yoksa: mum yönüne göre hacim atfı (yaklaşık)

**`hesapla_cvd_momentum(df)`** — CVD hız değişimi (z-score normalize)
- Son N mumda alıcı baskısının ivmesi

**`hesapla_cvd_divergence(df)`** — Fiyat-CVD uyumsuzluğu
- `+1`: Bullish divergence (fiyat düşüyor, CVD yükseliyor → gerçek dip)
- `-1`: Bearish divergence (fiyat yükseliyor, CVD düşüyor → sahte kırılım)

**Model feature setine eklendi**: `CVD_Norm`, `CVD_Momentum`, `CVD_Divergence`

**Canlı market data'ya entegre**: `market_veri_topla()` artık CVD döndürüyor,
sentiment skoruna katkısı var (±0.5 puan).

**Execution dampening**: CVD divergence varsa pozisyon boyutu %20 küçültülüyor.

---

## 🔴 Kritik #3 — Likidasyon Isı Haritası (data/market_data.py)

### Sorun
Likidasyon seviyeleri bilinmiyordu. SL/TP yerleşimi körlemesine yapılıyordu.

### Çözüm
**`likidasyon_isi_haritasi(sembol, mevcut_fiyat)`**:
- Binance `fapi/v1/allForceOrders` API'si ile son 100 gerçek likidasyon emri
- Fiyat bantlarına göre likidasyon yoğunluğu (ısı haritası)
- **Magnet Seviyesi**: En yoğun likidasyon bölgesi → fiyatın oraya "çekilme" eğilimi
- En yakın LONG/SHORT likidasyon seviyeleri
- Yoğunluk skoru ≥5 → log uyarısı

**`order_book_depth_profil(sembol)`** (eski `order_book_imbalance` yükseltmesi):
- %0.5'lik fiyat bantlarında bid/ask hacim dağılımı
- **Duvar Tespiti**: Ortalama hacmin 3x üstündeki seviyeler = güçlü destek/direnç
- `bid_duvari` / `ask_duvari` sözlükleri: fiyat + hacim + mesafe

---

## 🟢 Kritik #4 — Ensemble Confidence Interval (main.py)

### Sorun
Ensemble model tek bir tahmin üretiyordu. "Ne kadar emin olduğumuz"
bilinmiyordu.

### Çözüm
Stacking ensemble'da tüm base model tahminlerinin **standart sapması** hesaplanır:

- `std > 0.20` → pozisyon %50 küçültülür (yüksek belirsizlik)
- `std > 0.15` → pozisyon %25 küçültülür (orta belirsizlik)
- `std ≤ 0.15` → normal pozisyon (ensemble hemfikir)

`model_belirsizlik` değeri `sonuc` dict'ine eklendi.

---

## Etkilenen Dosyalar
- `engines/risk_manager.py` — tam yeniden yazım
- `data/market_data.py` — CVD + likidasyon haritası + gelişmiş OB
- `core/indicators.py` — 3 yeni CVD fonksiyonu eklendi
- `main.py` — entegrasyon (feature set, execution, sonuc dict, Kelly güncelleme)
