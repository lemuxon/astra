# ASTRA v37.0 — 3 KRİTİK DÜZELTME: -1021, TELEGRAM KOMUTLARI, PANEL v15

## Tarih: 2026-06-04 | Temel: v36.0

Kullanıcı bildirimi: Telegram komutları çalışmıyor, panel hâlâ v15
gösteriyor, loglarda -1021 timestamp hataları.

## 🔴 Sorun 1: -1021 "Timestamp ahead" hataları (kök sorun)
```
[FUTURES] Geçici hata -1021: Timestamp for this request was 1000ms
ahead of the server's time
```
### Kök Neden
VDS saati Binance sunucu saatinden ileri kaymış. recvWindow=10000 olsa
da "ileri" timestamp'leri tolere etmiyor. positionRisk, balance,
openOrders çağrıları başarısız oluyordu.

### Düzeltme (data/binance_futures_client.py)
- **Sunucu saati senkronizasyonu**: `/fapi/v1/time`'dan Binance saati
  çekilip yerel saatle fark (offset) hesaplanıyor, her isteğin
  timestamp'ine uygulanıyor. 5 dakikada bir güncelleniyor.
- **-1021 anında zorla yeniden senkronizasyon**: Hata gelirse offset
  cache'i geçersiz kılınıp tekrar hesaplanıyor, istek düzeltilmiş
  timestamp ile tekrar deneniyor.
- Not: Sunucu saatini OS düzeyinde de düzeltmek en sağlamı
  (`timedatectl set-ntp true`), ama bu kod artık saat kaysa bile çalışır.

## 🔴 Sorun 2: Telegram komutları çalışmıyor
### Kök Neden
Komut handler'ları (coroutine içinde) `asyncio.get_event_loop()`
kullanıyordu. Python 3.10+'da bu deprecated ve coroutine içinde yanlış/
kapalı loop döndürüp `run_in_executor`'ı patlatabiliyor. Hata da
python-telegram-bot tarafından sessizce yutuluyordu → komut cevapsız.

### Düzeltme (main.py)
- Komut handler'larındaki 5 `get_event_loop()` → `get_running_loop()`
  (coroutine içinde çalışan loop'u kesin döndürür). Ana döngüdeki
  (coroutine dışı) kullanım korundu.
- **Global hata yakalayıcı eklendi**: Komut handler'ında hata olursa
  artık sessizce yutulmuyor — loglanıyor + kullanıcıya "⚠️ Komut
  hatası" bildiriliyor. Böylece gelecekte sessiz başarısızlık olmaz.

## 🔴 Sorun 3: Panel hâlâ v15 gösteriyor
### Kök Neden
v30'da versiyonları merkezi ASTRA_VERSION'a çevirirken dashboard
HEADER'ındaki sabit `<span class="ver">v15.0</span>` GÖZDEN KAÇMIŞ.
Title ve footer düzelmişti ama header'daki bu rozet v15 kalmıştı —
kullanıcının gördüğü tam buydu.

### Düzeltme (api/dashboard.py)
- Header'daki `v15.0` → `__ASTRA_VERSION__` placeholder'ı (servis
  anında ASTRA_VERSION ile doldurulur). Artık tüm panel v37.0 gösterir.

## Etkilenen Dosyalar
- `data/binance_futures_client.py` — sunucu saati senkronizasyonu
- `main.py` — get_running_loop + global Telegram hata yakalayıcı
- `api/dashboard.py` — header versiyon düzeltmesi
- `config.py` — v37.0

## Test
- 74 dosya syntax temiz ✅
- main.py tam import OK ✅
- Panelde v15 kalmadı, hepsi merkezi versiyon ✅
- get_running_loop coroutine içinde doğru çalışıyor ✅

## KULLANICININ YAPMASI GEREKEN (sunucuda)
1. **Saat senkronizasyonu** (en sağlam çözüm — koda ek olarak):
   ```
   timedatectl set-ntp true
   systemctl restart systemd-timesyncd
   timedatectl   # "System clock synchronized: yes" görmeli
   ```
2. **Yeni sürümü çalıştırdığından emin ol**: Eğer hâlâ panel eski
   görünüyorsa, eski klasörü (astra_v36 vb.) çalıştırıyor olabilirsin.
   v37'yi çıkar, systemd/screen yolunu güncelle, tarayıcıda Ctrl+Shift+R.
3. **Telegram token'ı hâlâ değiştirilmeli** (önceki loglarda görüldü).

---

## v37.1 EK DÜZELTME: "Bazı komutlar çalışmıyor" çözüldü

### Teşhis
Kullanıcı: "bazı komutlar çalışıyor bazıları çalışmıyor". Bu, Telegram
altyapısının çalıştığını ama bazı komutların İÇİNDE hata olduğunu gösterdi.

### Kök Neden (2 ayrı sorun)
1. **Sessiz başarısızlık**: 7 komut (cmd_bakiye, cmd_risk, cmd_paper,
   cmd_ai_rapor, cmd_fpoz, cmd_engine, cmd_selflearn) `await reply_text`
   YERİNE sadece `telegram_gonder()` kullanıyordu ve try/except yoktu.
   - Binance bağımlı olanlar (-1021 saat hatası varken) exception fırlatıp
     `telegram_gonder`'e hiç ulaşamıyordu → kullanıcı hiç cevap görmüyordu.
   - `telegram_gonder` rate-limit'e takılırsa da sessizce kayboluyordu.
2. **cmd_engine operatör bug'ı**: `a + b if kosul else "" + c + d`
   ifadesi operatör önceliği yüzünden yanlış değer üretiyordu (if/else
   tüm + zincirini kapsıyordu). Rapor bozuk/eksik dönüyordu.

### Düzeltme
- 7 komut `await u.message.reply_text()` + try/except ile yeniden yazıldı.
  Artık Binance/ağ hatası olsa bile kullanıcı MUTLAKA cevap alır
  ("⚠️ ... hatası: ... Binance bağlantısını kontrol edin").
- cmd_engine operatör bug'ı düzeltildi (parça parça liste + join).
- Doğrulama: 35 komuttan HİÇBİRİ artık cevapsız kalmıyor (hepsi reply_text).

### Neden bazıları çalışıp bazıları çalışmıyordu
- Çalışanlar: zaten `reply_text` kullanan basit komutlar (cmd_yardim,
  cmd_market, cmd_circuit...).
- Çalışmayanlar: `telegram_gonder`-only + Binance bağımlı olanlar.
  Saat hatası (-1021) bunları sessizce öldürüyordu.

İki katman birden düzeldi: (1) v37 saat senkronizasyonu -1021'i çözdü,
(2) v37.1 komutları hataya dayanıklı yaptı. Artık bir komut başarısız
olsa bile sessiz kalmaz, kullanıcıya nedenini söyler.
