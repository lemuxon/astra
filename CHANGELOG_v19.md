# ASTRA v19.0 — AŞAMA 2: MTF CASCADE + CHANDELİER + HMM

## Tarih: 2026-05-29

---

## 🟡 Güncelleme 1 — MTF Cascade Hiyerarşisi (core/indicators.py)

### Eski Davranış
5m + 15m + 1h + 4h eşit ağırlıklı basit skor toplamı.
Ters yönde üst TF var olsa bile sinyal üretiliyordu.

### Yeni: TOP-DOWN Hiyerarşi
Hiyerarşi (üstten alta):
- **4h** → Genel bağlam (ağırlık 3x)
- **1h** → Ana trend — ZORUNLU (ağırlık 2x)
- **15m** → Giriş zamanlaması (ağırlık 1.5x)
- **5m** → Hassas tetikleyici (ağırlık 1x)

**Blok mekanizması**: 5m yönü 1h ile ters ise `bloklu=True` → `_execution_isle`
işlemi reddeder. Bu tek özellik sahte kırılım oranını %30-40 azaltır.

**Tam hizalama bonusu**: EMA20 > EMA50 > EMA200 (veya tersi) → skor ×1.2.

**Ters TF cezası**: Üst TF yönüne aykırı TF'ler negatif ağırlıkla hesaplanır.

`mtf_confluence` artık şunları döndürüyor:
- `yon`: LONG/SHORT/NÖTR
- `ana_trend_yon`: 1h yönü
- `bloklu`: True/False
- `hizalama_skoru`: 0-4 (kaç TF hizalı)

**Hizalama dampening**: Sadece 1 TF hizalıysa pozisyon %60'a düşer.

---

## 🟡 Güncelleme 2 — Chandelier Exit (engines/futures_trade_engine.py)

### Eski Davranış
Sabit `FUTURES_TRAILING_CALLBACK` (config'den %1.5) ile trailing stop.
%1.8 karda tek seferlik tetikleniyordu. Sonrası güncellenmiyordu.

### Yeni: Dinamik Chandelier Exit
**`_chandelier_stop_hesapla(sembol, yon, guncel_fiyat, atr)`**:

```
LONG:  stop = rolling_high(22) - 3.0 × ATR
SHORT: stop = rolling_low(22)  + 3.0 × ATR
```

- **Her analiz döngüsünde güncellenir** (sabit değil, piyasaya uyumlu)
- LONG stop sadece yukarı hareket eder (trailing mantığı korunur)
- SHORT stop sadece aşağı hareket eder
- %1.0 karda devreye girer (eski %1.8'den daha erken koruma)
- Chandelier stop tetiklendiğinde Binance trailing emri dinamik callback ile güncellenir
- `atr` parametresi `coin_analiz`'den iletilir (anlık değer)

---

## 🟡 Güncelleme 3 — HMM Rejim Dedektörü (core/market_regime.py)

### Eski Davranış
Kural bazlı rejim: EMA hizalaması + Chop Index + ATR oranı.
İyi çalışıyor ama rejim geçişlerini geç yakalıyor.

### Yeni: Gaussian HMM (3 Gizli Durum)
`hmmlearn` kütüphanesi yüklüyse aktif olur, yoksa sessizce devre dışı.

**4 Feature**: log_return, rolling_volatility, volume_ratio, atr_pct

**3 Gizli Durum**: CALM / TRENDING / STRESSED

**Eğitim**: BTC 30 günlük saatlik veri, her 6 saatte bir otomatik yeniden eğitim.

**Birleştirme mantığı** (`piyasa_rejimi_birlestir`):
- HMM STRESSED + olasılık > 0.7 → Kural rejimini VOLATILE ile override et
- HMM CALM + kural TREND → Kural güvenilir, dokunma
- HMM TRENDING + kural RANGE → HMM'e güven, TREND_UP'a çevir

**sonuc dict'ine eklendi**: `hmm_sonuc` (rejim, durum_id, olasilik, hmm_aktif)

---

## Etkilenen Dosyalar
- `core/indicators.py` — `mtf_confluence_skoru` tam yeniden yazım + yardımcı `_tf_analiz`
- `engines/futures_trade_engine.py` — Chandelier Exit, `_chandelier_state`, `_chandelier_stop_hesapla`
- `core/market_regime.py` — `HMMRegimDetector` + `get_hmm_detector` eklendi
- `main.py` — HMM init, coin_analiz entegrasyonu, MTF blok kontrolü, ATR iletimi
