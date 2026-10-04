# ASTRA v43.0 — OI TESTNET DÜZELTMESİ + KOMUT TIMEOUT

## Tarih: 2026-06-24 | Temel: v42.0

Canlı log analizinden çıkan iki gerçek sorun düzeltildi.

## 🔴 Sorun 1: OI Geçmiş Hatası (her turda tekrarlıyordu)
### Loglardaki belirti
```
[FUTURES] OI geçmiş hatası XRPUSDT: Expecting value: line 1 column 1 (char 0)
```
Her tarama turunda 5 coin için tekrarlıyordu → gereksiz log + ağ yükü.

### Kök Neden (iki katmanlı)
1. Testnet `openInterestHist` endpoint'ini desteklemiyor → boş yanıt.
2. `except` sadece RequestException yakalıyordu ama hata aslında
   ValueError (JSON parse) → yanlış kategoride loglanıyordu.
Bu, v35'te likidasyon + L/S ratio için düzelttiğimiz sorunun AYNISI —
o zaman bu endpoint gözden kaçmış.

### Düzeltme
- IS_TESTNET kontrolü: testnet'te çağrı hiç yapılmaz, boş DataFrame döner.
- except artık ValueError + KeyError de yakalıyor (JSON hatası dahil).
- log.warning → log.debug (gürültü azaltma).
Sonuç: testnet'te OI hataları tamamen susar, ağ turu hızlanır.

## 🔴 Sorun 2: /btc Komutu Takılıyordu (10dk cevapsız)
### Belirti
Kullanıcı /btc yazdı, 10 dakika cevap gelmedi. Loglarda:
```
[PARALEL] Coin turu 150s tavanını aştı — ağ yavaş olabilir
```
### Kök Neden
cmd_btc/cmd_coin, coin_analiz'i run_in_executor ile çağırıyordu AMA
timeout yoktu. Ağ yavaşken (testnet kararsız) analiz sonsuza kadar
bekliyordu → komut takılı kalıyordu. v34'teki 150s tavan ana tarama
döngüsünü koruyordu ama Telegram komut yolunu kapsamıyordu.

### Düzeltme
Yeni `_analiz_timeout_ile` yardımcısı: coin_analiz'i asyncio.wait_for
ile 90s timeout'la sarar. Süre aşılırsa kullanıcıya "ağ yavaş, tekrar
deneyin" mesajı gider — sonsuza kadar takılmaz. cmd_btc ve cmd_coin
bu güvenli yolu kullanıyor.

## Not: Bot Aslında Sağlıklı Çalışıyor
Canlı log analizi gösterdi ki:
- Sinyal üretimi çalışıyor (ETH için ULTRA STRONG SELL, AI:-9, edge ✅)
- 150s tavan koruması devrede (donma yerine turu iptal edip devam)
- 0 işlem normal çünkü LIVE_TRADING=false (test modu)
- Model accuracy %53-59 (v33 sonrası dürüst değerler)
Bu sürüm "bozuk bir şeyi tamir" değil, gürültü + komut takılması giderme.

## Etkilenen Dosyalar
- `data/binance_futures_client.py` — OI testnet guard + JSON hata yakalama
- `main.py` — komut timeout yardımcısı (cmd_btc, cmd_coin)
- `config.py` — v43.0

## Test
- 78 dosya syntax temiz ✅
- 30/30 test geçti ✅
- 38 komut sağlam ✅
- OI testnet guard doğrulandı (ağ çağrısı yapmıyor) ✅
- Timeout yardımcısı tanımlı ✅

## Kullanıcı Notu
Bu sürümden sonra: OI hataları kaybolacak, ağ turları hızlanacak,
/btc gibi komutlar ağ yavaşken bile en geç 90s'de cevap verecek.
Hatırlatma: sunucu saatini NTP ile senkron tutmayı unutmayın
(timedatectl set-ntp true).
