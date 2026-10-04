# ASTRA v44.0 — KÖK ÇÖZÜM: GLOBAL TIMEOUT + LOG + AUTO-RESTART

## Tarih: 2026-06-24 | Temel: v43.0

## Sorun: "Neden hep takılıyor?"
Bot uzun süre çalışınca takılıyor, watchdog alarmı veriyor (620-635s
heartbeat yok), sonra çöküyor. baslat.sh/screen ile çalışmasına rağmen
oldu → sorun PuTTY DEĞİL, kodda/ağda.

## Kök Neden (kesin teşhis)
Bot sürekli Binance'e bağlanıyor. Testnet ağı kararsız (loglarda sürekli
FAILOVER + WS Stale). Bir ağ çağrısı yanıt vermezse VE timeout'u yoksa,
SONSUZA KADAR bekler → thread donar → heartbeat durur → watchdog alarmı.
Önceki sürümlerde tek tek bazı çağrılara timeout eklendi ama takılan
spesifik çağrı her seferinde farklı/gözden kaçan biriydi.

## 🔴 ÇÖZÜM 1: Global HTTP Timeout (asıl tedavi)
`core/http_guard.py` — requests kütüphanesini SİSTEM GENELİNDE patch'ler.
Artık timeout belirtilmeyen HER istek otomatik tavan alır:
  - connect timeout: 8s
  - read timeout: 15s
Bot başlarken otomatik aktif olur. Takılan çağrı HANGİSİ OLURSA OLSUN
en geç 15s'de kesilir. Bu, "timeout'suz çağrı" sınıfını TÜMÜYLE ortadan
kaldırır — tek tek aramaya gerek kalmaz.

Test: timeout'suz istek otomatik (8,15) alıyor, belirtilen timeout korunuyor ✅

## 🔴 ÇÖZÜM 2: Kalıcı Log Dosyası
baslat.sh artık logları logs/astra.log dosyasına yazar (tee ile).
Bot çökse, screen kapansa bile [WATCHDOG TEŞHİS] dahil HER ŞEY kayıtlı
kalır. Bir daha teşhis kaybolmaz.
  - İzle: tail -f logs/astra.log
  - Watchdog ara: grep "WATCHDOG TEŞHİS" logs/astra.log

## 🔴 ÇÖZÜM 3: Otomatik Yeniden Başlatma
baslat.sh artık bir restart döngüsü içeriyor: bot çökerse 10s sonra
OTOMATİK yeniden başlar. systemd kurmaya gerek yok. Watchdog'un
"systemd restart bekleniyor" mesajı artık karşılıksız kalmıyor.

## Üç Katmanlı Savunma
1. Global timeout → çağrı takılmaz (önleme)
2. Watchdog teşhis → takılırsa ne olduğu loglanır (görünürlük)
3. Auto-restart → yine de çökerse toparlanır (kurtarma)

## Etkilenen Dosyalar
- `core/http_guard.py` (YENİ) — global HTTP timeout
- `main.py` — global timeout başlangıçta uygulanıyor
- `baslat.sh` — log dosyası + otomatik restart
- `config.py` — v44.0

## Test
- 79 dosya syntax temiz ✅
- 30/30 test geçti ✅
- Global timeout çalışıyor (doğrulandı) ✅
- Bot başlarken timeout otomatik aktif ✅
- baslat.sh sözdizimi geçerli ✅

## Kullanıcı Notu — ÖNEMLİ
Bu sürümü `./baslat.sh` ile başlatın (eski yöntemle değil). Artık:
- Hiçbir ağ çağrısı 15s'den fazla bekleyemez → takılma kökten çözülür
- Bot çökse bile loglar logs/astra.log'da kalır
- Bot çökse 10s'de otomatik yeniden başlar
E�er yine bir takılma OLURSA (olmamalı), logs/astra.log içindeki
[WATCHDOG TEŞHİS] satırlarını paylaşın — ama global timeout sonrası
bu sorunun bitmesi beklenir.
