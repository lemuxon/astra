# Binance `-4120` — Destek/Dokümantasyon Sorusu

> **Bu belge sizin göndermeniz için hazırlandı.** Aşağıdaki İngilizce metni
> Binance API desteğine (veya developer forumuna / GitHub `binance-docs`
> issue'suna) olduğu gibi yapıştırabilirsiniz.
>
> Neden İngilizce: Binance API desteği İngilizce çalışıyor.

---

## Neden bu soru kritik (Türkçe özet)

`CANLI_GECIS_PROTOKOLU.md` gereği bot, pozisyon açar açmaz borsaya bir
stop-loss emri yerleştirmek zorunda. Yerleştiremezse pozisyonu **derhal
kapatıyor** (testnet'te 6/6 doğrulandı) — yani **zarar riski yok**, ama
sistem hiç işlem açamaz.

Testnet tüm koşullu emirleri `-4120` ile reddediyor. Production'ın kabul
edip etmediği **bilinmiyor** ve gerçek parayla denenmedi. Bu, gerçek paraya
geçişin önündeki **tek teknik engel**.

Öğrenmek istediğimiz tek şey: **bu bir testnet kısıtı mı, yoksa API
genelinde bir değişiklik mi?**

---

## ⚠️ Göndermeden önce

1. **Aşağıdaki metinde API anahtarı YOK** — kontrol edin, eklemeyin.
   Destek talebine asla anahtar/secret/imza yapıştırmayın.
2. `<<<...>>>` ile işaretli yerleri doldurun (tam hata çıktısı, tarih).
   Tam çıktıyı almak için: `python testnet_emir_dogrula.py`
3. Sorular spesifik — "çalışmıyor" demek yerine "şu koşulda şu dönüyor,
   beklenen bu mu?" diye soruyor. Destek talepleri böyle daha hızlı
   sonuçlanıyor.

---

## Gönderilecek metin (İngilizce)

**Subject:** USDⓈ-M Futures Testnet: all conditional order types rejected with `-4120`, while `exchangeInfo` advertises them

Hello,

I am building an automated trading system against the USDⓈ-M Futures API and
I need to clarify whether a behaviour I observe on **testnet** also applies to
**production**, before I risk real funds.

### Environment

- Endpoint: `POST /fapi/v1/order`
- Base URL: `https://testnet.binancefuture.com`
- Symbol: `BTCUSDT` (also reproduced on `ETHUSDT`)
- Mode: USDⓈ-M Futures, one-way position mode
- Date observed: 2026-08 <<<gözlemi tekrarladığınız tarihi yazın>>>

### What works

Unconditional orders are accepted and fill normally:

- `MARKET`
- `LIMIT`

So the API key, signing (HMAC SHA256), `timestamp`/`recvWindow`, and the
endpoint itself are all working correctly.

### What fails

**Every** conditional order type is rejected with error code `-4120`:

| Order type | Result |
|---|---|
| `STOP_MARKET` | rejected, `-4120` |
| `STOP` | rejected, `-4120` |
| `TAKE_PROFIT_MARKET` | rejected, `-4120` |
| `TRAILING_STOP_MARKET` | rejected, `-4120` |

I tried **6 different parameter combinations**, including:

- with and without `closePosition=true`
- with and without `reduceOnly=true`
- `workingType=MARK_PRICE` and `workingType=CONTRACT_PRICE`
- `priceProtect` on and off
- `stopPrice` both above and below the mark price (correct side for the
  position direction in each case)
- `quantity` explicitly set vs omitted (when using `closePosition`)

All six combinations returned `-4120`.

Full request/response (secrets removed):

```
<<<buraya `python testnet_emir_dogrula.py` çıktısındaki tam istek
parametrelerini ve tam hata cevabını yapıştırın —
API anahtarı ve signature ALANLARINI SİLİN>>>
```

### The contradiction

`GET /fapi/v1/exchangeInfo` **advertises** these types as supported for the
same symbol. For `BTCUSDT`, the `orderTypes` array includes `STOP_MARKET`.

So `exchangeInfo` says the type is available, but `/fapi/v1/order` rejects
it. Either `exchangeInfo` is inaccurate on testnet, or `-4120` means
something other than "order type not supported" in this context.

### My questions

1. **Is `STOP_MARKET` still supported on `POST /fapi/v1/order` in
   production?** Or has conditional order placement moved to a different
   endpoint?
2. **What exactly does `-4120` mean?** The public error-code documentation
   does not list it clearly. What condition triggers it?
3. **Is this a testnet-only restriction?** If testnet no longer accepts
   conditional orders, that is important to document — it makes it
   impossible to validate risk-management logic before going live, which
   is exactly what testnet exists for.
4. If conditional orders are restricted on testnet, **what is the
   recommended way to test stop-loss placement logic** without using real
   funds?

Thank you.

---

## Nereye gönderilir

| Kanal | Not |
|---|---|
| Binance API desteği (hesap → Destek → API) | En doğrudan yol |
| `github.com/binance/binance-spot-api-docs` issues | Futures için de yanıt alınıyor |
| Binance Developer topluluğu (Telegram/Discord) | Genelde en hızlı ilk yanıt |

---

## Cevap gelince

`DEVAM_NOTLARI.md` §3 ENGEL 1'i güncelleyin. Üç olasılık:

- **"Production'da çalışıyor, testnet kısıtı"** → canlıya geçiş yolu açılır,
  ama SL yerleştirme ilk gerçek işlemde dikkatle izlenmeli (bot SL
  konulamazsa pozisyonu zaten kapatıyor — güvenlik ağı yerinde).
- **"API değişti, yeni endpoint var"** → `execution/` katmanında emir
  gönderme yolu güncellenmeli; `tests/test_imza_retry.py` ve
  `tests/test_guvenlik_agi.py` bu yolu koruyor.
- **"Koşullu emirler artık desteklenmiyor"** → mimari karar gerekir:
  stop-loss'u bot tarafında yönetmek, borsa tarafında duran emir olmadığı
  için bot kapalıyken korumasız bırakır. Bu, mevcut risk modelini
  temelden değiştirir.
