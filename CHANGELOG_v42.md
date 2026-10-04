# ASTRA v42.0 — WATCHDOG TEŞHİSİ + GÜVENLİ BAŞLATMA

## Tarih: 2026-06-24 | Temel: v41.0

## Sorun
Kullanıcı: "Uzun süre çalışınca (1-2 saat) watchdog alarmı veriyor.
Botu doğrudan PuTTY'de çalıştırıyorum. Alarm gelince ne oluyor bilmiyorum."

## İki Olası Sebep (ayırt edilmesi gerek)
1. **PuTTY/bağlantı**: Bot doğrudan PuTTY oturumunda çalışıyor. Oturum
   koparsa/uyursa (1-2 saat sonra SSH timeout, internet kopması, bilgisayar
   uykusu) terminal ölür → process takılır → watchdog alarmı. EN OLASI.
2. **Kod**: Zamanla biriken bir kaynak veya askıda kalan ağ çağrısı ana
   döngüyü kilitliyor olabilir.

Bu sürüm İKİSİNİ DE ele alır: biri çözüm, biri kesin teşhis.

## 🔬 YENİ: Watchdog Thread Dump Teşhisi
Watchdog alarm verdiğinde artık TÜM thread'lerin o anki stack trace'ini
loglar. "Hangi işlem takıldı" sorusunu KESİN cevaplar:
```
[WATCHDOG TEŞHİS] 305s donma — thread durumları:
  [MainThread] binance_client.py:142 içinde 'klines_indir' → r=requests.get(...)
  [AstraOrderEngine] execution_engine.py:88 içinde '_process_loop' → ...
```
Böylece bir dahaki alarmda tahmin değil, kanıt olur — ana döngünün hangi
satırda/ağ çağrısında/kilitte asılı kaldığı net görülür.

## 🆕 YENİ: Güvenli Başlatma Betiği (baslat.sh)
Tek komutla (./baslat.sh) botu screen'de, PuTTY'den BAĞIMSIZ başlatır:
- Sunucu saatini kontrol eder/düzeltir (-1021 önleme)
- screen kurulu değilse kurar
- Zaten çalışan oturum varsa uyarır
- venv kontrolü yapar
- Bot'u arka planda başlatır → PuTTY kapatılabilir

Bu, en olası sebebi (PuTTY bağımlılığı) tek adımda çözer ve manuel
screen komutlarındaki hata riskini ortadan kaldırır.

## Kullanıcının Yapması Gereken
1. **En olası çözüm**: Botu artık `./baslat.sh` ile başlat (veya systemd).
   Doğrudan `python main.py bot` ÇALIŞTIRMA — PuTTY'e bağımlı kalır.
2. **Eğer alarm yine gelirse**: Loglardaki [WATCHDOG TEŞHİS] satırlarını
   paylaş — hangi thread'in takıldığını göreceğiz ve kodu düzelteceğiz.

## Etkilenen Dosyalar
- `engines/watchdog.py` — alarm anında thread dump teşhisi
- `baslat.sh` (YENİ) — güvenli screen başlatma betiği
- `config.py` — v42.0

## Test
- 78 dosya syntax temiz ✅
- 30/30 test geçti (watchdog değişikliği bozmadı) ✅
- Thread dump teşhisi çalışıyor (simülasyonla doğrulandı) ✅
- baslat.sh sözdizimi geçerli ✅

## Not
Bu sürüm sorunu KESİN çözmek yerine, kesin TEŞHİS koymayı hedefler.
En olası sebep (PuTTY) için çözüm hazır; değilse, bir sonraki alarmda
thread dump tam olarak neyin takıldığını gösterecek. Tahmin yok, kanıt var.
