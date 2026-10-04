# ASTRA v56.0 — DENETİM DÜZELTMELERİ + PAPER MALİYET MODELİ

## Tarih: 2026-08-13 | Temel: v55.0
Kaynak: `DENETIM_RAPORU_v55.md` (132/132 dosya, 58 bulgu) + paper modu runtime testi

---

## ÖZET

| | |
|---|---|
| Denetimde bulunan ve düzeltilen | 58 |
| Düzeltme sırasında bulunan yeni | 3 |
| **Paper modu çalıştırınca bulunan yeni** | **3** |
| **Panel canlı testinde bulunan** | **5** |
| **Telegram incelemesinde bulunan** | **2** |
| **Canlı çalıştırmada bulunan** | **3** |
| **Toplam düzeltilen** | **77** |
| Değiştirilen üretim dosyası | 38 |
| Test sayısı | 60 → **76** |

---

## 🔴 KRİTİK (denetim)

### C-1 DuplicateGuard fail-safe'i gerçekte fail-OPEN'dı
`execution/duplicate_guard.py:130-139` — `_binance_pozisyon_var()` hatayı kendi
içinde yutup `return False` ediyordu; v55'te eklenen fail-closed bloğu
**ulaşılamaz ölü koddu**. Binance'e erişilemediği anda guard "pozisyon yok"
deyip işleme İZİN VERİYORDU → çift pozisyon riski.
Testi de yanlış katmanı mock'ladığı için geçiyordu (sahte güven).

### C-2 `acik_futures_pozisyonlar()` hata durumunda `[]` dönüyordu
"Sıfır pozisyon" ile "sorgulayamadım" ayırt edilmiyordu. Geçici bir kesintide
`fill_reconciler` TÜM açık pozisyonları state'ten siliyor, pozisyonlar borsada
canlı ve izlenmeden kalıyordu. → `strict=True` parametresi eklendi, 6 güvenlik-kritik
çağrı ona geçirildi.

### C-3 `failsafe_liquidation` thread'i tek istisnada kalıcı ölüyordu
Catch-all `except` yoktu. `ZeroDivisionError`/`KeyError` daemon thread'i
sonlandırıyor, likidasyon koruması sessizce ve kalıcı olarak devre dışı
kalıyordu. → catch-all + `saglikli_mi()` liveness kontrolü.

### C-4 Çapraz-borsa fiyat vetosu her cache isabetinde atlanıyordu
`data/multi_exchange.py:139` — dataclass üzerinde `.get()` → `AttributeError`
→ `log.debug`'da yutuluyor → manipülasyon vetosu hiç çalışmıyordu.

### C-5 EventBus dispatcher thread'i ölebiliyordu
`queue.Full` import edilmemişti (yakalanamıyordu) + handler `KeyError`'ı
dispatcher'ı öldürüyordu. Ölünce `publish()` başarılı görünmeye devam ediyor
ama Kelly/PnL, günlük zarar limiti ve kill-switch güncellemeleri duruyordu.

### C-6 `execution_node.py:153` — eksik import ilk istisnada node'u çökertiyordu
`InsufficientBalanceError` import edilmemişti.

### C-7 `CorrelationLimitError` iki kez tanımlıydı
İkinci tanım hiyerarşiyi bozup `except RiskError` bloklarının korelasyon
ihlalini yakalamasını engelliyordu.

### C-8 `model_engine.py:767` kaçak `append` ensemble'a `None` model sokabiliyordu

---

## 🟠 YÜKSEK (seçilmiş)

- **H-1/H-2/H-3** `main.py`'da 3 tanımsız isim → strateji dayanıklılık
  doğrulayıcısı ve TFT tahmini **hiç çalışmamıştı** (v24/v21'den beri).
- **H-4** `risk_manager`'da hiç kilit yoktu → günlük zarar limiti eksik sayabiliyordu.
- **H-5** Chandelier state'i yalnızca motor kaynaklı kapanışta temizleniyordu;
  borsa SL/TP dolumunda temizlenmediği için yeni pozisyon **eski stop'u miras
  alıp anında hatalı stop-out** tetikleyebiliyordu. → `POSITION_CLOSED` aboneliği.
- **H-6** Kapanış PnL'i gerçek fill yerine kapanış öncesi fiyattan hesaplanıyordu.
- **H-7** Backtest'te likidasyon zararı **iki kez** düşülüyordu (2× kötümser sonuç).
- **H-8/H-9** Preflight'ın Binance kontrolü **asla başarısız olamıyordu**;
  DB bütünlüğü hiç kontrol edilmiyordu.
- **H-11** Likidasyon fiyatı 3 ayrı yerde elle hesaplanıyordu; borsanın kendi
  `liquidationPrice` değeri atılıyordu. → tek kaynağa indirildi.
- **H-12/H-13** `db_manager` SQLite şeması ile CRUD sütunları uyuşmuyordu;
  `except (OSError, ValueError)` sqlite3/psycopg2 hatalarını hiç yakalamıyordu.
- **H-14** HTTP 429/418 hiç sınıflandırılmıyordu, `Retry-After` okunmuyordu.
- **H-15** `bot` modunda trading thread'i denetimsizdi — çökerse Telegram botu
  çalışmaya devam edip "her şey yolunda" izlenimi veriyordu.
- **H-16** `docker-compose.yml`: sabit `astra2024` şifreleri, auth'suz Redis ve
  Postgres host portunda. → secrets + `expose` + `requirepass`.

---

## 🆕 PAPER MODU ÇALIŞTIRINCA BULUNAN (statik analizin göremediği)

### P-1 Paper bakiyesinde sessiz sızıntı — `engines/paper_trading.py`
Açılışta bakiyeden **yuvarlanmamış** `usdt_boyut` düşülüyor, kapanışta
**yuvarlanmış** `miktar` üzerinden iade ediliyordu. Fark her işlemde sessizce
kayboluyor, PnL'de hiç görünmüyordu.

| İşlem boyutu | Kayıp |
|---|---|
| 20 USDT | **%0.145** |
| 51 USDT | %0.035 |
| 1000 işlem | ~18 USDT |

Sonuç: `bakiye` ile `toplam_pnl` zamanla ayrışıyor, paper sonuçları kötümser
çıkıyordu — canlıya geçiş kararının dayandığı sinyal bozuluyordu.
→ Borçlandırma ve iade artık aynı değeri kullanıyor.

### P-2 Paper trading işlem maliyetini HİÇ modellemiyordu
`backtest_engine` komisyon (0.0004) ve slippage (3 bps) modelliyor, paper
**ikisini de modellemiyordu**. Aynı fiyattan kapanan işlem tam `0.000000` PnL
veriyordu. Canlıda round-trip maliyet ≈ %0.08.

Bu, `CANLI_GECIS_PROTOKOLU.md`'nin paper↔canlı karşılaştırmasını doğrudan
bozuyordu: paper sıfır maliyetle çalıştığı için canlı **her zaman** kötü
görünecek ve kullanıcı "strateji bozuldu" sanacaktı.
→ `PAPER_KOMISYON` + `PAPER_SLIPPAGE_BPS` eklendi (varsayılanlar backtest ile
aynı), giriş ve çıkışta aleyhte slippage uygulanıyor.

### P-3 `testleri_calistir.py` Windows'ta hiç çalışmıyordu
Alt süreç çıktısı cp1254 ile geliyor, `text=True` UTF-8 sanıp
`UnicodeDecodeError` fırlatıyor, `stdout` None kalıyor ve
`AttributeError: 'NoneType' object has no attribute 'split'` ile çöküyordu.
Yani protokolün Aşama 0.1 maddesi ("tüm testler geçiyor") Windows'ta
**doğrulanamıyordu**. → UTF-8 zorlandı, stderr gösterimi eklendi.

Ek: `test_validator.py`'ın çıktı formatı filtreye takılmadığı için o paketin
sonucu ekranda hiç görünmüyordu.

---

## 🖥️ PANEL — CANLI TARAYICI TESTİYLE BULUNANLAR

Panel gerçek tarayıcıda açılıp negatif değerlerle beslendi.

### PN-1 Panel HİÇBİR zarara eksi işareti koymuyordu (4 ayrı yer)
`pnlSign`, `pnlSignPct`, toplam PnL, günlük PnL, açık PnL — hepsi
`Math.abs()` + koşulsuz `'+'` kalıbı kullanıyordu. **12.34$ zarar, panelde
`$12,34` olarak (kâr gibi) görünüyordu.** Yalnızca CSS rengi ayırt ediyordu;
ekran görüntüsü paylaşımında veya renk körü kullanıcıda kâr/zarar
**ayırt edilemezdi.** → Tek `pnlSignUsd` yardımcısına bağlandı, hepsi `−` gösteriyor.

### PN-2 Açık pozisyon PnL yüzdesi her satırda ±%100
Yüzde `(p.cikis||p.guncel||0)` üzerinden hesaplanıyordu ama `main.py` açık
pozisyonlarda ne `cikis` ne `guncel` gönderiyor → ifade daima
`(0-giris)/giris*100 = -100` veriyordu; işaret ise PnL'den alındığı için
kârlı pozisyonda `+100%`, zararlıda `−100%` yazıyordu. Tamamen anlamsız.
→ PnL / (giriş×miktar) oranına çevrildi. `main.py`'da eksik `miktar` alanı eklendi
(iki kurulum noktasından biri gönderiyor, diğeri göndermiyordu — tutarsızlık).

### PN-3 `/api/state` dışındaki HER yol HTTP 200 + panel HTML'i dönüyordu
`/olmayan`, `/admin`, `/.env` — hepsi 200. → Yol eşleştirmesi sıkılaştırıldı
(404), `POST` 405 ile reddediliyor, `/saglik` liveness endpoint'i eklendi.

### PN-4 Güvenlik başlığı yoktu
→ `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
`Content-Security-Policy` eklendi (CSP tarayıcıda doğrulandı, panel sorunsuz render oluyor).

### PN-5 Bot çökünce panel bayat veriyi güncelmiş gibi gösteriyordu
Yalnızca küçük bağlantı göstergesi kırmızıya dönüyor, BAKİYE/PNL/POZİSYON
ekranda aynen kalıyordu. Panele şöyle bir bakan operatör "her şey yolunda"
sanabilirdi. → Kırmızı uyarı bandı + veriler soluklaştırılıyor + kaç saniyedir
bayat olduğu yazıyor. **Bot öldürülerek canlı doğrulandı.**

---

## 💬 TELEGRAM — DERİN İNCELEME

### TG-1 4096 karakter sınırı hiçbir yerde gözetilmiyordu
60 gönderim noktasının **hiçbiri** uzunluk kontrolü yapmıyordu. Telegram
4096'yı aşan mesajı reddeder (`400: message is too long`) → veriye göre büyüyen
raporlar (`/neden`, `/registry`, `/journal`, `/ai_rapor`, çok coinli özetler)
üretimde kullanıcıya **hiç ulaşmıyordu**.
→ `_tg_parcala()` + `_yanitla()` eklendi; 59 çağrı dönüştürüldü,
`telegram_gonder()` de aynı korumaya alındı. Sınır/kenar durumları test edildi.

### TG-2 3 komut event loop'u kilitliyordu
`cmd_risk`, `cmd_bakiye`, `cmd_correlation` bloklayan REST çağrısını doğrudan
async handler içinde yapıyordu. Yavaş ağda (HTTP timeout 15s) bu süre boyunca
**hiçbir Telegram komutu yanıt vermiyordu.** → `run_in_executor`'a taşındı.

### Temiz çıkanlar
- Yetkilendirme: `_yetkili_komut` dekoratörü **38 komutun tamamına** kayıt
  anında uygulanıyor — atlanan komut yok, doğrulandı.
- Global hata yakalayıcı mevcut; komut hatası botu düşürmüyor.

---

## TEST PAKETİ: 60 → 76

**Düzeltilen yanıltıcı testler:**
- `test_guard_sorgu_hatasinda_engeller` — yanlış katmanı mock'luyordu, gerçek
  hatayı atlıyordu. Artık gerçek zinciri test ediyor. *(Eski kodda `izin=True`,
  yeni kodda `izin=False` olarak doğrulandı.)*
- `test_paper_dusuk_skor_reddedilir` — `assert True` ile bitiyordu, başarısız
  OLAMAZDI. Artık `_pozisyon_ac`'ın çağrılmadığını doğruluyor.

**Eklenen regresyon testleri (11):**
istisna hiyerarşisi · `RateLimitError` örneklenebilirliği · tanımsız isim
taraması · backtest likidasyon · SuperTrend yön geçerliliği · EventBus
dispatcher dayanıklılığı · multi_exchange cache yolu · pozisyon boyutu tabanı ·
guard `strict` parametresi · `strict=True` hata yükseltmesi · paper bakiye/PnL
tutarlılığı · paper maliyet modellemesi · filtre kontrol testi

---

## DOĞRULAMA

```
pyflakes tanımsız isim : 0   (v55'te 6 vardı)
Derleme                : 80/80 dosya temiz
main.py tam import     : OK
Test paketi            : 76/76 geçiyor
Preflight (paper)      : tüm kontroller geçti
Paper modu runtime     : 1 tur tamamlandı, 0 traceback, 0 çökme
Bakiye/PnL tutarlılığı : 30 round-trip sonrası sapma 0.00000000
```

---

## ⚠️ DAVRANIŞ DEĞİŞİKLİKLERİ (canlıya geçmeden önce okuyun)

Bu düzeltmelerin bir kısmı savunma değil, **davranış değişikliğidir**:

1. **`order_engine`** — SL 3 denemede konamazsa pozisyonu **zorla kapatır**.
   Geçici API sorununda sağlıklı pozisyon kapanabilir.
2. **`preflight`** — Binance erişilemezse veya kaldıraç >50 ise canlı modda
   **botu başlatmaz**.
3. **`risk_manager`** — minimum altındaki boyutta 5 USDT yerine **0** döner;
   bazı işlemler artık hiç açılmaz.
4. **`config.py` / `docker-compose.yml`** — eksik yapılandırmada başlatmayı reddeder.
5. **Panel ve Prometheus** — varsayılan olarak yalnızca `127.0.0.1`'e bağlanır.
6. **Paper sonuçları artık maliyetli** — v55 öncesi paper sonuçlarıyla
   **karşılaştırılamaz**. Paper doğrulama sayacı sıfırdan başlatılmalıdır.
7. **Backtest** — ATR ısınma barları atlandığı için eski sonuçlarla
   karşılaştırılabilir değil.

## ⚠️ LOG GÜRÜLTÜSÜ ARTACAK

Eskiden `log.debug`'da saklanan gerçek hatalar artık `log.error`/`log.critical`.
İlk çalıştırmada log hacminin artması **beklenen ve bilgi vericidir** —
oradaki mesajlar gerçek sorunlardır, yeni hata değil.

## SONRAKİ ADIM

`CANLI_GECIS_PROTOKOLU.md` Aşama 1: **paper modda ≥3 hafta, ≥100 işlem.**
Maliyet modeli eklendiği için bu sayaç sıfırdan başlamalıdır.

---

## 🔬 CANLI ÇALIŞTIRMADA BULUNANLAR (testnet + gerçek Telegram)

### R-1 `futures_bakiye()` hatayı yutup 0.0 dönüyordu
`-2015 Invalid API-key` hatası "bakiye 0" gibi görünüyor, teşhisi tamamen
yanlış yöne saptırıyordu. `acik_futures_pozisyonlar` için düzeltilen aynı
sınıf hata (C-2) burada gözden kaçmıştı. → `strict=True` parametresi eklendi.

### R-2 `TRADE_USDT` min_notional'ı karşılamıyordu
Binance min_notional sembole göre değişir (BTCUSDT=50, ETHUSDT=20, SOL/XRP=5).
Protokolün Aşama 2 ayarı `TRADE_USDT=10` ile **BTC ve ETH hiç işlem göremez** —
sadece bir `log.warning` basılıp sessizce atlanıyordu.
→ Preflight kontrolü eklendi (`_kontrol_islem_boyutu`), `.env` 60'a çekildi.

### R-3 Paper trading portföy risk limitlerini HİÇ uygulamıyordu
`MAX_OPEN_POSITIONS=1` ayarlıyken paper **3 eşzamanlı SHORT** açtı; canlı yol
`risk_manager.tum_kontroller` ile 1'e sınırlıyordu. Paper işlem sayısı, PnL,
drawdown ve korelasyon riski canlıyı TEMSİL ETMİYORDU — protokolün paper↔canlı
karşılaştırmasını bozan **üçüncü** hata (diğerleri: maliyet modeli yok,
bakiye sızıntısı). → `_filtre_gec`'e limit kontrolleri eklendi (fail-closed).

### R-4 `CHAT_ID` boşken Telegram yetkilendirmesi no-op'tu
`if CHAT_ID and gelen_id != str(CHAT_ID)` — CHAT_ID boşsa koşul hiç çalışmaz,
token'ı bilen herkes `/fkapat`, `/killswitch_reset` çalıştırabilir.
Dekoratör 38 komuta uygulanıyordu (bu doğruydu) ama bu durum atlanmıştı.
→ Başlangıçta `CRITICAL` uyarı + `telegram_chat_id_bul.py` yardımcısı.

---

## ✅ CANLI DOĞRULANANLAR (kod okumasıyla değil, çalıştırarak)

| Ne | Nasıl |
|---|---|
| SL başarısızlığında pozisyon zorla kapanıyor | Testnet, **6/6 turda sıfır sızıntı** |
| DuplicateGuard 300s cooldown churn'ü önlüyor | 6 denemede borsaya **1** emir gitti |
| Market emri + slippage | Gerçek dolum, **%0.006** slippage |
| Round-trip maliyet | Ölçüldü: **%0.089** (model %0.08 — yakın) |
| Panel bayat-veri uyarısı | Bot öldürülerek doğrulandı |
| Panel CSP + güvenlik başlıkları | Gerçek tarayıcıda, konsol hatası yok |
| Telegram 4096 bölme | Gerçek API'de **9.959 karakter → 3 parça** |
| Telegram 38 komut + yetkilendirme | Canlı bot, komutlar yanıt verdi |

## ⛔ DOĞRULANAMAYAN

**Stop-loss yerleştirmenin başarılı yolu.** Binance Futures **testnet** tüm
koşullu emir tiplerini `-4120` ile reddediyor (STOP_MARKET, STOP,
TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET); koşulsuz emirler çalışıyor.
Production'ın kabul edip etmediği **bilinmiyor** ve gerçek parayla test edilmedi.

Bu, gerçek paraya geçişin önündeki tek teknik engeldir.

---

## 🧩 main.py MODÜLERLEŞTİRME (aşamalı)

`main.py` 3079 satır, 74 üst-düzey fonksiyondu. Riske göre sıralanıp
**düşük riskliden** başlandı; her aşamadan sonra tam doğrulama yapıldı.

### Yapılan

| Aşama | Ne taşındı | Nereye | Satır |
|---|---|---|---|
| 1 | Telegram gönderim katmanı | `core/telegram_gonderim.py` | 110 |
| 2 | Feature üretimi + skorlama | `core/sinyal_skor.py` | 142 |

**main.py: 3079 → 2827 satır**

Taşınan fonksiyonlar: `telegram_gonder`, `telegram_grafik_gonder`,
`_tg_parcala`, `_yanitla`, `feature_olustur`, `ai_score_hesapla`,
`karar_ver`, `risk_hesapla`.

Seçilme kriteri: **saf olmaları**. `ai_score_hesapla` ve `karar_ver`'in
hiç dış bağımlılığı yok; Telegram katmanı yalnızca config + requests'e bağlı.

### Doğrulama (her aşamada)

- Refactor ÖNCESİ 119 üst-düzey ismin tamamı hâlâ `main.X` olarak erişilebilir
  (AST snapshot ile karşılaştırıldı) → **0 kayıp isim**
- `main.py` bu isimleri yeniden dışa verir; hiçbir çağrı noktası değişmedi
- pyflakes: 0 tanımsız isim
- 132/132 test geçiyor
- **Bot paper modda gerçekten çalıştırıldı**: 0 hata, 5 coin analizi,
  AI skorları ve kararlar normal üretiliyor

### Yapılmayan — ve nedeni

| Bölüm | Satır | Neden bekliyor |
|---|---|---|
| `futures_dashboard` | 496 | Ana döngü; global durumu `global` ile yeniden bağlıyor |
| `_execution_isle` | 290 | Emir yolu — gerçek para, kapsam düşük |
| `coin_analiz` | 360 | 15+ modüle ve global cache'lere bağlı |
| Telegram komutları | 475 | 36 fonksiyon, onlarca global singleton'a bağlı |

Bu 1621 satır, `main.py`'ın kalanının %57'si. Mekanik taşıma değil —
`risk_manager`, `exec_engine`, `state_manager` gibi global singleton'lara
bağımlılar. Doğru çözüm bir bağlam nesnesi (context/DI) tasarlamak;
bu, davranış değiştirme riski taşır.

`main.py` kapsamı %17 olduğu için bu bölümlerde refactor hatası testlerle
YAKALANAMAZ. Önce kapsam yükseltilmeli, sonra taşınmalı.

### Bilinen sorun (taşımada kasıtlı düzeltilmedi)

`risk_hesapla()` yön parametresi almıyor; her zaman LONG mantığıyla SL'i
aşağı, TP'yi yukarı koyuyor → SELL sinyallerinde Telegram raporu ters
görünüyor. **Emirler etkilenmez** (gerçek yol `sl_tp_hesapla` kullanıyor),
yalnızca raporlama hatası. Taşıma ile düzeltmeyi aynı adımda yapmak, sorun
çıkarsa kaynağını belirsizleştirirdi — ayrı ele alınmalı.
