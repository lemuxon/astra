# ASTRA v48.0 — TAM TARAMA + YAPISAL OPTİMİZASYON

## Tarih: 2026-06-24 | Temel: v47.0
Kullanıcı isteği: tüm kodu tara, düzelt, yapıyı optimize et.

## ⚡ OPTİMİZASYON 1: Klines Önbelleği (EN BÜYÜK KAZANÇ)
### Sorun (loglardan kanıtlı)
Aynı coin'in aynı timeframe verisi aynı döngüde 2-4 kez indiriliyordu
(analiz + MTF + HMM + market_data ayrı ayrı istiyordu). Kullanıcının
loglarında görülüyordu: "BTCUSDT 5m → 576 bar" birkaç saniye arayla
iki kez. Yavaş ağda bu, turların 150s tavanını aşmasının önemli sebebi.
### Çözüm
veri_indir'e 20s TTL thread-güvenli önbellek. Döngü içi tekrarlar
ağa gitmiyor; 20s TTL döngüler arası (60s) tazeliği koruyor. Önbellek
50 anahtarla sınırlı (bellek şişmesi yok).
### Test: 4 istek → 2 gerçek indirme (cache doğrulandı) ✅
### Beklenen etki: tur süreleri kısalır → 150s iptalleri azalır →
paper işlemler + sinyaller daha güvenilir işlenir.

## ⚡ OPTİMİZASYON 2: Sıcak Yolda 2 Gereksiz DB Sorgusu Kaldırıldı
sinyal_isle her sinyalde acik_tradeler("PAPER")'ı 3 kez çağırıyordu.
Mantık analizi: BUY sadece SHORT kapatır (LONG listesi değişmez),
tersi de öyle → ilk sorgunun sonucu yeniden kullanılabilir.
3 DB sorgusu → 1'e indi. Davranış birebir aynı.

## 🧹 TEMİZLİK 3: 12 Kullanılmayan Import Kaldırıldı
10 dosyada ölü import (numpy, pandas, json, math, pickle, threading).
Her biri iki aşamada doğrulandı (takma ad kontrolü dahil — as np/as pd).
Başlangıç süresi ve bellek ayak izi hafifledi.

## 🧹 TEMİZLİK 4: Fonksiyon İçi Config Import'ları Modül Seviyesine
IS_TESTNET, 3 sıcak fonksiyonun içinde her çağrıda import ediliyordu.
Modül seviyesine taşındı — sadeleşme + mikro performans.

## ✅ Tarama Sonuçları (temiz alanlar)
- Syntax: 79 dosya temiz
- 30/30 test geçiyor (tüm optimizasyonlar sonrası)
- main.py tam import OK
- Eşzamanlılık: lock kullanımı dengeli
- Bellek: sınırsız büyüyen yapı yok

## Bilinçli YAPILMAYAN
database.py bağlantı havuzlaması değerlendirildi ama yapılmadı:
paylaşılan SQLite bağlantısı thread-lock disiplini gerektirir, mevcut
aç-kapat düzeni güvenli ve WAL'lı. Kazanç/risk oranı olumsuz.

## Etkilenen Dosyalar
- data/binance_client.py — klines TTL önbelleği
- engines/paper_trading.py — DB sorgu optimizasyonu
- data/binance_futures_client.py, data/market_data.py — import düzeni
- 10 dosya — ölü import temizliği
- config.py — v48.0
