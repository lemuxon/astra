# ASTRA v53.0 — ÇİFT EMİR ÖNLEME + KELLY/BOYUT KORUMALARI

## Tarih: 2026-08-11 | Temel: v52.0
`binance_futures_client.py` (627 satır) ve `risk_manager.py` kalan
bölümleri SATIR SATIR okundu.

---
## 🔴🔴 BUG 1 (EN KRİTİK): ÇİFT EMİR RİSKİ — retry emirleri tekrarlıyordu
**Dosya:** `data/binance_futures_client.py:_futures_istek`

### Sorun
Retry döngüsü POST (emir gönderme) isteklerinde de çalışıyordu:
```
1) POST emir gönderilir → Binance emri ALIR ve İŞLER
2) Yanıt dönerken timeout (ağ koptu)
3) Kod timeout yakalar → emri TEKRAR gönderir
4) İKİ POZİSYON AÇILIR — sistem sadece birini bilir
```
`duplicate_kontrol()` emir gönderilmeden ÖNCE çalıştığı için bu
senaryoyu yakalayamıyordu. Risk 2 katına çıkar, ikinci pozisyon
"hayalet" olur (SL/TP'siz, sistemin haberi yok).

### Çözüm: Idempotency (endüstri standardı)
- Her emre benzersiz `newClientOrderId` üretilir (retry'dan ÖNCE).
- Tüm denemelerde AYNI ID kullanılır → Binance ikinci isteği
  "duplicate" diye reddeder → emir İKİ KEZ İŞLENMEZ.
- Duplicate yanıtı geldiğinde emrin GERÇEK durumu borsadan sorgulanır
  (`_futures_istek_sorgu`) → "emir gitti mi?" belirsizliği biter.
- GET isteklerine eklenmez (gereksiz).

### Test kanıtı
`test_retry_ayni_client_order_id_kullanir`: 2 timeout + 1 başarı
senaryosunda 3 denemede de AYNI ID kullanıldığı doğrulandı.

---
## 🔴 BUG 2: Negatif Kelly'de Yine İşlem Açılıyordu
**Dosya:** `engines/risk_manager.py:370`

Negatif Kelly = o coinde matematiksel kazanç beklentisi YOK.
Kod uyarı basıyor ama `return 5.0` ile yine pozisyon öneriyordu.
(v52'de adaptive_sizing'de düzeltilen aynı desen.)
→ `return 0.0` (işlem açma).

---
## 🔴 BUG 3: Minimum Boyut Kontrolü Hiçbir Yerde Yoktu
**Dosya:** `execution/execution_engine.py:pozisyon_ac`

`main.py` akışında Kelly → MVO → damp çarpanları uygulanıp doğrudan
`pozisyon_ac`'a gidiliyordu; **0 veya çok küçük boyut kontrolü YOKTU**.
0 USDT'lik emir borsaya gidip hata alırdı.

→ `pozisyon_ac` başına tek noktadan minimum kontrolü eklendi.
Bu, 3 çağıranın (main.py, futures_trade_engine, execution_node)
hepsini birden korur.

---
## 🔧 BUG 4: v52'de KENDİ EKLEDİĞİM Hata Düzeltildi (dürüstlük notu)
**Dosya:** `execution/execution_engine.py:315`

v52'de eklediğim kısmi dolum kontrolünde `usdt`'yi MARJİN varsayıp
kaldıraçla çarpmıştım. Oysa kod tabanında `usdt` = NOTIONAL
(`futures_market_ac`: `miktar = usdt/fiyat`).

Etki: her işlemde sahte "kısmi dolum" uyarısı (oran = 1/kaldıraç = %20).
Düzeltildi: `beklenen_miktar = usdt / exec_fiyat`.
Doğrulama: hatalı hesap %20 oran veriyordu, doğru hesap %100.

---
## Test Paketi: 51 → 55 test
- `test_retry_ayni_client_order_id_kullanir` (BUG 1 — en kritik)
- `test_get_istekleri_client_id_almaz` (yan etki kontrolü)
- `test_kucuk_boyut_islem_acmaz` (BUG 3)
- `test_negatif_kelly_islem_acmaz` (BUG 2)

## Doğrulama
- 80 dosya syntax temiz
- **55/55 test geçiyor** (26 çekirdek + 23 execution + 6 validator)
- main.py tam import OK

## Kümülatif Durum (v52 + v53)
Satır satır incelenen: execution_engine.py, risk_manager.py,
adaptive_sizing.py, binance_futures_client.py, paper_trading.py
Bulunan finansal bug: **8** (hepsi düzeltildi + teste bağlandı)
