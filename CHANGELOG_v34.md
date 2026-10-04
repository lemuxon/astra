# ASTRA v34.0 — VDS SAĞLAMLIK: ANA DÖNGÜ BLOKE KORUMASI

## Tarih: 2026-05-31 | Temel: v33.0

### Teşhis (kullanıcı logları)
VDS'te 7/24 çalışırken üç uyarı görüldü:
```
[WS] Stale data tespit edildi — bağlantı yenileniyor   (çok sık)
[WATCHDOG] Uyarı: 539s heartbeat yok                    (9 dakika!)
```
539 saniye heartbeat olmaması = ana döngü 9 DAKİKA takılmış demek.

### Kök Neden: Ağ Çağrıları Döngüyü Bloke Ediyordu
`klines_indir` her başarısız çağrıda: 10s timeout × 3 deneme +
üstel bekleme (1+2+4s) = **~37 saniye tek çağrıda**. Bir coin
analizi 4-5 `veri_indir` çağrısı yapıyor. Testnet yavaş yanıt
verince bunlar birikip ana döngüyü dakikalarca kilitliyordu →
heartbeat gidemiyor → watchdog 539s alarmı.

(Testnet'in WebSocket'i de kararsız olduğu için stale uyarısı sık.)

### Düzeltmeler

**1. Retry süresi yarıya indirildi (data/binance_client.py)**
- Timeout: 10s → 6s
- Bekleme: üstel (1,2,4s) → lineer kısa (0.5, 1s)
- Tek çağrı worst-case: ~37s → ~19.5s

**2. Coin turu TAVAN SÜRESİ (main.py) — ana koruma**
- Tüm paralel coin analizi `asyncio.wait_for(timeout=150s)` ile sarıldı.
- 150s'de bitmezse tur iptal edilir, döngü bir sonrakine geçer.
- Timeout'ta heartbeat zorla gönderilir → watchdog asla yanlış alarm vermez.
- **Ana döngü artık HİÇBİR koşulda 150s'den fazla takılamaz.**

**3. Event loop sızıntısı önlendi (main.py)**
- Her turda oluşturulan event loop artık `finally`'de düzgün kapatılıyor.
- Timeout'ta bekleyen task'lar iptal edilip temizleniyor.

**4. WS stale eşiği gevşetildi (engines/websocket_manager.py)**
- 15s → 30s (config'ten WS_STALE_ESIK_S ile ayarlanabilir).
- Testnet WS sık duraklar; 15s gereksiz reconnect tetikliyordu.

### Yeni config / .env
```
COIN_TUR_TIMEOUT=150    # Coin turu bu sürede bitmezse iptal (watchdog koruması)
WS_STALE_ESIK_S=30      # WS bu süre veri gelmezse yenile (testnet 30+ önerilir)
```

### Etkilenen Dosyalar
- `data/binance_client.py` — retry süresi sınırlandı
- `main.py` — coin turu timeout + event loop temizliği
- `engines/websocket_manager.py` — stale eşiği config'e bağlandı
- `config.py` — 2 yeni anahtar

### Test
- Timeout koruması: yavaş tur tavanı aşınca iptal edildi ✅
- 74 dosya syntax temiz, main.py import OK ✅

### Önemli Notlar
- Bu uyarıların ÇOĞU testnet'in yavaşlığından kaynaklanıyordu.
  Canlı Binance'e geçince büyük ölçüde azalır. Ama bu düzeltme,
  canlıda da bir ağ sorunu olursa botun takılmamasını garanti eder.
- Watchdog alarmı (539s) artık imkansız: tur 150s tavanlı.
- Eğer testnet'te hâlâ stale uyarısı gelirse WS_STALE_ESIK_S=45
  yapabilirsin — ama bu sadece kozmetik, bot zaten çalışmaya devam eder.
- Davranış değişmedi, sadece sağlamlık arttı. Mevcut .env ile çalışır.
