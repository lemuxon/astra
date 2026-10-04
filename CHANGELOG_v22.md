# ASTRA v22.0 — AŞAMA 5: SMART EXECUTION + MODEL VERSİYONLAMA + ON-CHAIN

## Tarih: 2026-05-29 | Temel: v21.0

---

## ⚡ Güncelleme 1 — Smart Execution: TWAP/VWAP/Iceberg (execution/smart_execution.py)

### Eski Durum
Tüm emirler tek seferde market order olarak gönderiliyordu.
Büyük emir → order book'u yer → kötü ortalama fiyat (market impact).

### Yeni: Akıllı Emir Bölme
**`SmartExecutor`** sınıfı, emri boyutuna göre stratejiye yönlendirir:

- **MARKET**: < 80 USDT emirler → doğrudan (gecikme yok)
- **TWAP**: Eşit zaman dilimleri (varsayılan 4 parça, 3sn arayla)
- **VWAP**: Hacme orantılı dağıtım (likit anlarda daha çok)
- **ICEBERG**: Düşük likiditede gizli küçük parçalar

**Adaptif dilim sayısı:** Volatilite > %3 → 6-8 parça, < %1 → 2 parça.

`execution_engine._pozisyon_ac_impl` içine entegre edildi. Büyük emirler
otomatik bölünür, slippage iyileşmesi (bps) loglanır.

**`/smartexec`** komutu: Market/TWAP/VWAP/Iceberg dağılımı.

---

## 📦 Güncelleme 2 — Model Registry: Versiyonlama (engines/model_registry.py)

### Eski Durum
Modeller .pkl dosyaları üzerine yazılıyordu. "Hangi versiyon daha iyiydi?"
sorusu cevaplanamıyordu. Kötü bir retrain'i geri almak imkansızdı.

### Yeni: MLflow-Tarzı Bağımsız Registry (ek servis gerektirmez)
**`ModelRegistry`** (SQLite tabanlı):

- **register()**: Her eğitimde versiyon, accuracy, params, market koşulları kaydedilir
- **Versiyonlu saklama**: `saved_models/versions/rf_BTCUSDT_v3.pkl`
- **canli_sonuc_guncelle()**: Her kapanan işlem aktif modelin canlı PnL'ini günceller
- **rollback_gerekli_mi()**: Aktif model kötü performans (>5 işlem, ort < %-5) gösterirse
  daha iyi eski versiyonu tespit eder
- **rollback_yap()**: Otomatik olarak eski iyi versiyona geri döner + Telegram bildirimi

`rf_egit`'e entegre — her RF eğitimi otomatik versiyonlanıyor.
`_on_position_closed`'da canlı performans + rollback kontrolü.

**`/registry BTCUSDT`** komutu: Versiyon geçmişi + canlı PnL.

---

## ⛓️ Güncelleme 3 — On-Chain Veri (data/onchain_data.py)

### Eski Durum
Sadece fiyat + funding + OI verisi vardı. Büyük cüzdan hareketleri ve
borsa para akışı görünmüyordu — fiyattan 4-12 saat önceki sinyaller kaçıyordu.

### Yeni: On-Chain Sentiment
**`exchange_netflow_proxy()`**: Borsa para giriş/çıkış proxy'si
(Coingecko global market verisi — ücretsiz)
- Para çıkışı (HODL) → bullish
- Para girişi → satış baskısı

**`whale_hareket_tespit()`**: Büyük cüzdan hareketleri
- Glassnode API anahtarı varsa gerçek veri
- Yoksa nötr (proxy)

**`onchain_sentiment()`**: Birleşik skor (-2..+2)
→ `market_veri_topla` sentiment skoruna eklenir (artık -6..+6 aralığı)

**Tüm API'ler opsiyonel:** Anahtar yoksa proxy/nötr, bot çalışmaya devam eder.

**`/onchain BTCUSDT`** komutu: Netflow + whale + birleşik skor.

`.env` opsiyonel: `GLASSNODE_API_KEY`, `ETHERSCAN_API_KEY`

---

## Etkilenen / Eklenen Dosyalar
| Dosya | Değişim |
|-------|---------|
| `execution/smart_execution.py` | **YENİ** — TWAP/VWAP/Iceberg executor |
| `engines/model_registry.py` | **YENİ** — Model versiyonlama + rollback |
| `data/onchain_data.py` | **YENİ** — On-chain sentiment |
| `execution/execution_engine.py` | Smart executor entegrasyonu |
| `engines/model_engine.py` | RF eğitimi registry'ye kaydediliyor |
| `data/market_data.py` | On-chain sentiment + genişletilmiş skor aralığı |
| `main.py` | v22 imports, position_closed registry, /registry /onchain /smartexec |
| `config.py` | Smart exec ayarları |

---

## Yeni Telegram Komutları
- `/smartexec` — TWAP/VWAP execution istatistikleri
- `/registry [coin]` — Model versiyon geçmişi
- `/onchain [coin]` — On-chain sentiment

## Opsiyonel .env Anahtarları
```
GLASSNODE_API_KEY=...    # Whale tracking (yoksa proxy)
ETHERSCAN_API_KEY=...    # ETH on-chain (yoksa proxy)
```
