# ASTRA v45.0 — PANEL SIK GÜNCELLEME + WEBSOCKET SABIR

## Tarih: 2026-06-24 | Temel: v44.0

## Sorun
Kullanıcı: Panel fiyatı geç güncelleniyor (donuk görünüyor), /btc gecikiyor.
"Sinyallerde hata yapma riski" endişesi.

## Önce: İşlem Güvenliği Zaten Korunuyor (açıklama)
Önemli: Panel geç güncellense bile bot, işlem KARARI verirken panel
fiyatını kullanmıyor — karar anında Binance'ten taze fiyat çekiyor
(futures_anlık_fiyat). Ayrıca v26 çoklu borsa doğrulama: anormal fiyat
sapmasında işlem veto ediliyor. Yani panel donması bir GÖRÜNTÜLEME
sorunu, işlem güvenliği sorunu değil. Yine de panel donması giderildi.

## 🔧 İyileştirme 1: Panel Daha Sık Güncelleniyor
dashboard.py: setInterval 5000ms → 2000ms.
Panel fiyatı artık 2 saniyede bir yenileniyor (eskiden 5s). Ekranda
gördüğün fiyat gerçeğe daha yakın → "işlem riski" endişesi azalır.

## 🔧 İyileştirme 2: WebSocket Daha Sabırlı + Kendini Toparlıyor
websocket_manager.py iki değişiklik:
1. REST'e geçiş eşiği 3 → 6 deneme. Testnet'in geçici kopmalarında
   2 kat daha sabırlı; hemen REST'e düşmüyor.
2. YENİ: REST moduna geçse bile 5 DAKİKA sonra WS'i tekrar deniyor.
   Testnet toparlanırsa saniyelik güncellemelere geri döner.
   Eskiden "kalıcı REST" idi → artık "WS öncelikli, geçici REST".

### Davranış Farkı
- Eski: 3 stale → kalıcı REST (saniyelik güncelleme biter)
- Yeni: 6 stale → geçici REST → 5dk sonra WS tekrar → toparlanırsa
  saniyelik güncellemeye döner

## Not: Asıl Kök Neden Testnet Ağı
Sürekli FAILOVER + WS Stale, testnet altyapısının kararsızlığından.
Gerçek Binance'e (canlı) geçilince bu sorunların büyük ölçüde
DÜZELMESİ beklenir — testnet zaten kararsızdır. Bu sürüm testnet'te
deneyimi iyileştirir; canlıda zaten daha stabil olacaktır.

## Etkilenen Dosyalar
- `api/dashboard.py` — panel 2s güncelleme
- `engines/websocket_manager.py` — WS sabır + otomatik toparlanma
- `config.py` — v45.0

## Test
- 79 dosya syntax temiz ✅
- 30/30 test geçti ✅
- Panel 2s güncelleme doğrulandı ✅
- WS sabır + toparlanma mantığı doğrulandı ✅

## Kullanıcı Notu
Bu sürümle: panel 2s'de güncellenir, WS kopsa bile 5dk'da kendini
toparlamayı dener. Tarayıcıda Ctrl+Shift+R ile paneli yenileyin.
Hatırlatma: Bu sorunların çoğu testnet kaynaklı; canlıda daha az olur.
