# ASTRA v35.0 — TESTNET UYUMU: DESTEKLENMEYEN ÇAĞRILAR SUSTURULDU

## Tarih: 2026-05-31 | Temel: v34.0

### Sorun (kullanıcı logları)
Testnet'te sürekli tekrarlayan hatalar:
```
[LİKİDASYON ISI] XRPUSDT alınamadı: 400 Client Error: allForceOrders
[FUTURES] L/S ratio hatası BTCUSDT: Expecting value: line 1 column 1
```
Bunlar her döngüde 5 coin × 2 çağrı = ~10 başarısız istek üretiyordu.

### Kök Neden: Testnet Bu Endpoint'leri Desteklemiyor
- `fapi/v1/allForceOrders` (likidasyon ısı haritası) → testnet 400 döner
- `topLongShortPositionRatio` (L/S ratio) → testnet boş yanıt → JSON hatası

Bu BİR KOD HATASI DEĞİL — testnet eksikliği. Canlı Binance'te
ikisi de çalışır. Ama testnet'te gereksiz hata logu + gereksiz
ağ isteği üretiyorlardı.

### Düzeltme: Otomatik Testnet Tespiti
- `config.py`'ye `IS_TESTNET` bayrağı: FUTURES_BASE_URL'de "testnet"
  geçiyorsa otomatik True olur.
- **Likidasyon ısı haritası**: testnet'te API'yi hiç çağırmaz, boş
  (ama geçerli) harita döner → bot normal devam eder.
- **L/S ratio**: testnet'te nötr 1.0 döner, API'yi çağırmaz.
- Bonus: L/S ratio'da JSON parse hatası (ValueError) da artık
  yakalanıyor (eskiden sadece RequestException yakalanıyordu).
- Log seviyesi warning→debug (testnet dışı geçici hatalar da
  log'u kirletmesin).

### İki İhtiyacı Birden Karşılar
- **Testnet'te**: bu çağrılar susturuldu, loglar temiz, gereksiz
  istek yok (Seçenek 1).
- **Canlıya geçince**: IS_TESTNET otomatik False olur, iki özellik
  de kendiliğinden geri gelir — elle bir şey yapmana gerek yok
  (Seçenek 2).

### Etkilenen Dosyalar
- `config.py` — IS_TESTNET otomatik tespit bayrağı
- `data/market_data.py` — likidasyon testnet guard
- `data/binance_futures_client.py` — L/S ratio testnet guard + JSON hata yakalama

### Test
- IS_TESTNET: testnet URL→True, canlı URL→False ✅
- 74 dosya syntax temiz ✅

### Kalan Notlar (bu turda DOKUNULMADI)
- WS stale uyarısı: testnet WebSocket kararsızlığı, v34'te eşik 30s
  yapıldı. Tamamen bitmeyebilir ama bot çalışmaya devam eder.
- FAILOVER mesajları: normal toparlanma davranışı, hata değil.
- HMM "Convergence=True": normal, model başarıyla eğitildi.
- ⚠️ Telegram token'ı loglarda görünmüştü — kullanıcı kendi
  değiştirecek (@BotFather /revoke). Koda dokunulmadı.
