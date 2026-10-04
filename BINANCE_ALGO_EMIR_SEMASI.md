# Binance USDⓈ-M Futures — Algo (Koşullu) Emir Şeması

> **2026-08-26'da testnet üzerinde deneyerek çıkarıldı ve tam yaşam döngüsü
> doğrulandı.** Bu belge tahmin içermiyor; her satır gözlenmiş yanıta dayanıyor.
>
> Bu, `DEVAM_NOTLARI.md` §3 ENGEL 1'in (v55'ten beri açık) çözümüdür.

---

## Sorun neydi

Koşullu emirler klasik `/fapi/v1/order` endpoint'inden **Algo Service**'e
taşınmış. Eski endpoint artık şunu dönüyor:

```
POST /fapi/v1/order   type=STOP_MARKET
→ {"code":-4120,"msg":"Order type not supported for this endpoint.
                       Please use the Algo Order API endpoints instead."}
```

`exchangeInfo` hâlâ `STOP_MARKET`'i "destekleniyor" diye beyan ediyor —
çelişki buradan geliyordu.

---

## Endpoint'ler

| İşlem | Endpoint |
|---|---|
| Koy | `POST /fapi/v1/algoOrder` |
| İptal (tek) | `DELETE /fapi/v1/algoOrder` |
| İptal (tümü) | `DELETE /fapi/v1/algoOpenOrders` |
| Sorgu (tek) | `GET /fapi/v1/algoOrder` |
| Açık olanlar | `GET /fapi/v1/openAlgoOrders` |
| Tümü | `GET /fapi/v1/allAlgoOrders` |

Hepsi **hem testnet'te hem production'da** mevcut (anahtarsız probe ile
doğrulandı: var olmayan endpoint `-5000 "Path ... is invalid"` dönüyor,
bunlar `-2014` kimlik hatası dönüyor).

---

## Parametreler — ESKİDEN FARKLI OLANLAR

| Eski (`/fapi/v1/order`) | Yeni (`/fapi/v1/algoOrder`) |
|---|---|
| — | **`algoType=CONDITIONAL`** (ZORUNLU, yeni) |
| `type=STOP_MARKET` | `type=STOP_MARKET` (aynı kaldı) |
| **`stopPrice`** | **`triggerPrice`** ⚠️ isim değişti |
| yanıt: `orderId` | yanıt: **`algoId`** ⚠️ |

Değişmeyenler: `symbol`, `side`, `positionSide`, `quantity`,
`closePosition`, `workingType`, `priceProtect`, `reduceOnly`.

### Şema keşif sırası (hata mesajları yol gösterdi)

```
{}                                  → -1102 'symbol' eksik
{symbol}                            → -1117 Invalid side
{symbol,side}                       → -1102 'algotype' eksik
{...,algoType=STOP_MARKET}          → -4500 Invalid algoType
{...,algoType=CONDITIONAL}          → -1102 'type' eksik
{...,type=STOP_MARKET}              → -1102 'triggerprice' eksik
{...,triggerPrice=...}              → ✅ HTTP 200
```

`algoType` yazımı duyarsız (`algotype`/`algoType`/`ALGOTYPE` hepsi çalışıyor).

---

## Doğrulanmış çalışan çağrı

```python
POST /fapi/v1/algoOrder
{
  "symbol":       "BTCUSDT",
  "side":         "SELL",            # LONG'un stop-loss'u
  "algoType":     "CONDITIONAL",
  "type":         "STOP_MARKET",
  "triggerPrice": "70877.6",         # SELL stop → piyasanın ALTINDA
  "quantity":     "0.002",
  "workingType":  "MARK_PRICE",
  "priceProtect": "true"
}
```

Yanıt (HTTP 200):
```json
{"algoId":1000000181546843, "clientAlgoId":"oxMjqEdmCXfe7DoW6Z1uez",
 "algoType":"CONDITIONAL", "orderType":"STOP_MARKET", "algoStatus":"NEW",
 "triggerPrice":"70877.60", "quantity":"0.0020", ...}
```

İptal:
```python
DELETE /fapi/v1/algoOrder  {"symbol":"BTCUSDT", "algoId": 1000000181546843}
→ {"algoId":..., "code":"200", "msg":"success"}
```

---

## ⚠️ EN KRİTİK BULGU — algo emirleri klasik listede GÖRÜNMÜYOR

Emir açıkken:

```
GET /fapi/v1/openAlgoOrders?symbol=BTCUSDT  → [ {algoId:..., NEW} ]   ✅ var
GET /fapi/v1/openOrders?symbol=BTCUSDT      → []                       ❌ YOK
```

**Bu, projedeki fail-open deseninin yeni bir yüzü.** Etkilenen yerler:

1. **`engines/order_reconciler.py`** — açık emirlere bakıp "SL var mı"
   kontrolü yapıyor. Klasik listeye baktığı sürece **SL'i göremez** ve
   "korumasız pozisyon" sanıp gereksiz kapatma tetikleyebilir.

2. **`data/binance_futures_client.py::futures_stop_loss_koy`** — yeni SL
   koymadan önce eskisini iptal etmek için `acik_futures_emirler()`
   çağırıyor. Algo emirlerini göremezse **eski SL iptal edilmez** →
   aynı pozisyona birden fazla SL birikir.

3. **`core/preflight.py::_kontrol_kosullu_emir`** — `exchangeInfo`'ya
   bakıyor; o hâlâ "destekliyor" dediği için kontrol yanıltıcı.

**Kural:** SL/TP varlığı kontrol edilen HER yerde `openAlgoOrders` da
sorgulanmalı. Yalnızca `openOrders`'a bakmak, "SL yok" sonucunu sessizce
üretir — ve bu kod tabanında en pahalı hata türü budur.

---

## Testnet'te DOĞRULANANLAR (2026-08-26, uçtan uca)

Gerçek pozisyon açılarak test edildi (LONG 0.0007 BTC @ 78.895):

| Emir | Sonuç |
|---|---|
| `STOP_MARKET` + `closePosition=true` | ✅ algoId alındı, trigger 74.950 |
| `TAKE_PROFIT_MARKET` + `closePosition=true` | ✅ |
| `TRAILING_STOP_MARKET` + **`quantity`** | ✅ |
| `TRAILING_STOP_MARKET` + `closePosition=true` | ❌ **-4136** "Target strategy invalid" |
| `koruma_emirleri()` üçünü de görüyor | ✅ reconciler "SL var" diyor |

**`closePosition=true` açık pozisyon GEREKTİRİR** — pozisyonsuz denemede
`-4509 "TIF GTE can only be used with open positions"` döner. Bu beklenen
davranıştır, hata değildir.

**Idempotency:** `clientAlgoId` dışarıdan verilebiliyor; aynı id ile ikinci
istek `-4116 "ClientOrderId is duplicated."` ile reddediliyor.

---

## Bilinmeyenler (hâlâ denenmedi)

- Production davranışı testnet ile aynı mı? Endpoint'ler var ama emir
  yerleştirme production'da denenmedi (gerçek para gerekir).
- Algo emri tetiklendiğinde `actualOrderId` doluyor — dolum takibi
  (`fill_verify`) bu alanı kullanmalı mı?

---

## Sonraki adım

`data/binance_futures_client.py`'deki 4 fonksiyon güncellenmelidir:

| Fonksiyon | Satır | Emir tipi |
|---|---|---|
| `futures_stop_loss_koy` | 592 | STOP_MARKET |
| `futures_partial_tp_koy` | 611 | TAKE_PROFIT_MARKET |
| `futures_take_profit_koy` | 635 | TAKE_PROFIT_MARKET |
| `futures_trailing_stop_koy` | 651 | TRAILING_STOP_MARKET |

Ayrıca emir **listeleme** ve **iptal** yolları da algo endpoint'lerini
kapsamalı (yukarıdaki kritik bulgu).
