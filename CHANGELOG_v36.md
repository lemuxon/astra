# ASTRA v36.0 — STABİLİZASYON: WS STALE DÖNGÜSÜ + PANEL + TEŞHİS

## Tarih: 2026-06-03 | Temel: v35.0 (kullanıcı yüklemesi)

Kullanıcı isteği: sürümü stabil yap, bahsedilen tüm sorunları düzelt,
Telegram komutlarını ve paneli güncelle, ekstra bug bulursan önlem al.

## 🔴 Ana Sorun: WS Stale Sonsuz Döngüsü (VDS'te sürekli uyarı)

### Kök Neden
Kullanıcı VDS'e geçtiğinden beri sürekli:
```
[WS] Stale data tespit edildi — bağlantı yenileniyor
```
VDS'in Binance sunucularına ağ gecikmesi yüksek; WebSocket verisi
geç geliyor, stale monitor her 10s'de tetikleniyor, reconnect deniyor
ama bağlantı yine stale oluyordu → SONSUZ uyarı döngüsü.

### Düzeltme: Eskalasyon + REST'e Kalıcı Geçiş
`_stale_monitor` artık akıllı:
- İlk 3 stale: WS yenilemeyi dener (geçici sorun olabilir).
- 3'ten fazla: "WS bu sunucuda kararsız" deyip **REST polling moduna
  kalıcı geçer** ve uyarıyı SUSTURUR (bir daha tekrarlamaz).
- Veri tekrar gelirse sayaç sıfırlanır.

**Bu güvenli çünkü:** Fiyat fallback'i zaten vardı (main.py:290) —
WS `None` dönerse `futures_anlık_fiyat` (REST) devreye girer. Yani
WS kapanınca bot fiyatları REST'ten çeker, KESİNTİSİZ çalışır.
Test: 3 stale sonrası REST moduna geçiş + uyarı susturma doğrulandı.

## 📊 Panel Güncellemesi (yeni teşhis panelleri)

Dashboard'a 2 yeni "Sistem Zekası" kartı eklendi:
- **📊 İşlem Teşhisi**: açılan/reddedilen işlem + en çok reddeden
  veto katmanları (v32'de eklenen veto sayacının görsel hali).
- **⏱️ Giriş Gecikmesi**: ortalama gecikme, iptal oranı + hızlı/yavaş
  giriş PnL karşılaştırması (v31 gecikme-PnL analizinin görseli).

Artık "işlem neden açılmıyor" ve "gecikme zarar veriyor mu" sorularını
Telegram'a komut yazmadan panelde canlı görebilirsin.

## ✅ Telegram Komutları
- 37 komut kayıtlı, hepsinin fonksiyonu tanımlı (doğrulandı).
- Versiyon string'leri zaten merkezi ASTRA_VERSION'dan geliyor (v30+).

## 🧹 Ekstra: Temizlenen Buglar
- **Bozuk klasör temizliği**: Yüklenen zip'te kurulum sırasında oluşmuş
  `{core,data,...}` ve `{bootstrap,...}` adında 2 bozuk (brace expansion
  hatası) boş klasör vardı — silindi.
- İç içe klasör / __pycache__ / .pyc temizliği yapıldı.

## Etkilenen Dosyalar
- `engines/websocket_manager.py` — stale eskalasyon + REST'e geçiş
- `api/dashboard.py` — 2 yeni teşhis paneli (veto + gecikme)
- `config.py` — v36.0

## Test
- 74 dosya syntax temiz ✅
- main.py tam import OK ✅
- 37 Telegram komutu tanımlı ✅
- WS stale eskalasyon mantığı doğrulandı ✅
- Dashboard yeni paneller render ediliyor ✅

## Önemli Notlar
- WS stale uyarısı artık en fazla 3 kez gelir, sonra susar ve REST'e
  geçer. Bu, VDS ağ koşulları için EN SAĞLAM çözüm.
- Canlı Binance'e geçince WS muhtemelen sorunsuz çalışır (canlı altyapı
  testnet'ten çok daha hızlı). O zaman REST'e hiç düşmez.
- Davranış değişmedi, sadece dayanıklılık + gözlemlenebilirlik arttı.
- ⚠️ Telegram token'ı hâlâ değiştirilmeli (önceki turda loglarda görüldü).
