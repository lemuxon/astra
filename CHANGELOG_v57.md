# ASTRA v57.0 — TEST İZOLASYONU + SESSİZ TAM ÖLÜM

## Tarih: 2026-08-20 … 08-23 | Temel: v56.0
Kaynak: v56 sonrası doğrulama oturumu (K-1, K-2) + 08-23 canlı çalıştırma
gözlemi (K-3, K-4). İkisi de aynı desenin farklı yüzleri: **ölçüm ve
çalışma sürekliliği, kodun kendisi kadar kritik.**

---

## ÖZET

| | |
|---|---|
| Düzeltilen kök neden | **10** |
| Temizlenen sahte kayıt | **270** |
| Değiştirilen üretim dosyası | 3 |
| Test sayısı | 147 → **206** |
| Yeni test dosyası | `test_izolasyon.py` (10), `test_ana_thread.py` (7), `test_sl_dolum.py` (8), `test_watchdog_uyku.py` (6) |
| Paper işlem sayacı | 33 (sahte) → **0 (gerçek)** |

---

## 🔴 KRİTİK

### K-1 Test paketi ÜRETİM durum dosyalarına yazıyordu

**Belirti:** `DEVAM_NOTLARI.md` "0 / 100 kapanmış paper işlem" diyordu, ama
sayaç 2026-08-20'de **33** gösteriyordu. Arada bot hiç çalışmamıştı.

**Kök neden:** `tests/test_cekirdek.py` ve `tests/test_execution.py` gerçek
`PaperTrader`'ı ve gerçek `ExecutionEngine`'i **üretim veritabanlarına karşı**
çalıştırıyordu. `test_cekirdek.py:539` ve `:573` `data.database`'i doğrudan
import ediyor, hiçbir yönlendirme yapmıyordu. (İlk testte `import tempfile, os`
satırı vardı ama **hiç kullanılmıyordu** — izolasyon yarım bırakılmış.)

**Ölçülen kirlilik — her `python testleri_calistir.py` koşusunda:**

| Hedef | Delta |
|---|---|
| `data/astra.db::trades` | +11 |
| `data/astra.db::performance` | +2 |
| `data/journal.db::journal` | +12 (**biri `mod='LIVE'`**) |
| `data/model_registry.db::model_versions` | +2 |
| `data/ab_test.json` | üzerine yazılıyor |

**Neden en tehlikelisi:** Canlıya geçiş kararı (`CANLI_GECIS_PROTOKOLU.md`
Aşama 1) "100 kapanmış paper işlem" sayacına dayanır. Sayaç yalnızca test
koşularıyla doluyordu. Ayrıca `PaperTrader._bakiye_hesapla()` restart
bakiyesini DB'den türettiği için sahte PnL **paper bakiyesine de** sızıyordu.
Sayaç 100'e ulaşsaydı, tamamen sentetik veriyle gerçek paraya geçilecekti.

**Sahte verinin kanıtı (silmeden önce doğrulandı):**
- 67 işlemin **en uzun süresi 0.255 saniye** (gerçek işlem dakikalar sürer)
- 67 işlemde yalnızca **3 farklı giriş fiyatı**: 63018.9 / 2000.6 / 0.50015
- `performance` tablosunun 10 satırının tamamı `RANDUSDT` / `TESTUSDT`
- `journal`'daki 6 `LIVE` satırı: hepsi giriş 50000.0, miktar 0.04,
  `cikis_ts=NULL` → journal'da **hiç kapanmamış 6 sahte canlı pozisyon**
- `ab_test.json`: yalnızca sentetik 0.26/-0.44 döngüsü, `b_pnl` boş

**Çözüm:** `tests/izolasyon.py` — proje modülleri import edilmeden ÖNCE tüm
kalıcı durum yollarını geçici dizine yönlendiren önyükleyici. 7 test dosyasının
tamamına bağlandı (kirletmeyen 5'i de gelecekteki regresyona karşı).

Sıra kritik: `config.py` yolları **import anında** okur (`config.py:140`,
`:230`). Geç çağrı sessizce etkisiz kalırdı — bu yüzden `izole_et()` config
zaten yüklüyse `stderr`'e uyarı basıyor (§5.2 sessiz başarısızlık kuralı).

### K-2 `get_journal()` `JOURNAL_DB_PATH` ayarını yok sayıyordu (ÜRETİM HATASI)

Bu, K-1'i düzeltirken ortaya çıktı ve **testlerden bağımsız bir üretim hatası**.

`engines/trade_journal.py`'de yol iki yerde **sabit koduydu**:
```python
def __init__(self, db_path: str = "data/journal.db")   # satır 60
def get_journal(db_path="data/journal.db")             # satır 248
```

`get_journal()` bir singleton ve **ilk çağrıya göre sabitleniyor**. 6 çağrı
yerinin 5'i argümansız çağırıyordu:
`bootstrap/app_init.py:58`, `engines/paper_trading.py:211`, `:321`,
`execution/execution_engine.py:524`, `:652`.
Yalnızca `main.py:485` ve `:1664` yolu geçiyordu.

**Sonuç:** `.env`'de `JOURNAL_DB_PATH` değiştirilirse (Docker volume senaryosu
— `core/preflight.py:134` tam bundan endişeleniyor), **hangi çağrı önce
çalışırsa o kazanıyordu**. `bootstrap/app_init.py` önce çalıştığı için ayar
sessizce yok sayılıyor, journal yanlış dosyaya yazıyordu.

**Çözüm:**
- Her iki varsayılan `None` yapıldı, `config.JOURNAL_DB_PATH`'ten çözülüyor
- Singleton farklı bir yolla tekrar istenirse artık `log.error` basıyor
  (eskiden sessizce eski instance dönüyordu → journal iki dosyaya bölünürdü)

---

### K-3 Ana thread ölünce trading motoru da ölüyordu (ÜRETİM HATASI)

**2026-08-23'te canlı çalıştırmada bulundu** — statik analizde değil (§4.2).

`bot` modu şöyleydi:
```python
threading.Thread(target=_denetimli_dashboard, daemon=True).start()
telegram_bot_baslat()
```

`telegram_bot_baslat()` hatayı **kendi içinde yutup `return` eder**. Dönünce
ana thread biter, Python çıkar ve `AstraEngine` thread'i **DAEMON olduğu için
öldürülür**. Yani motorun v55'te eklenen koruyucu `while True` döngüsü
tamamen etkisizdi: onu öldüren kendi istisnası değil, ana thread'in bitmesiydi.

**Gerçekleşen senaryo:** Oturum açılışında ağ/DNS henüz hazır değilken
Telegram `getaddrinfo failed` alıyor → **bot komple ölüyor**.

**Ölçülen sonuç:** Bot 2026-08-21 13:01 ile 08-23 21:03 arasında **2+ gün
hiç veri toplamadı**. Log kanıtı: 8022 `getaddrinfo failed`, 325
`telegram.error.NetworkError`, `main.py:2747 telegram_bot_baslat`.

**Çözüm:** `telegram_denetimli_calistir()` — ana thread'i hiçbir koşulda
bitirmeyen denetim katmanı:
- Telegram kasıtlı kapalıysa (paket yok / `BOT_TOKEN` boş) yalnızca motoru
  canlı tutar, boşuna çağrı yapmaz
- Geçici hatada üstel artan beklemeyle (60s → en fazla 15 dk) yeniden dener
- **Hiçbir koşulda return etmez**

### K-4 Zamanlanmış görev yalnızca oturum açılışında tetikleniyordu

K-3'ün üzerini örten ikinci sorun. Görev `AtLogOn` tetikleyicisiyle
kurulmuştu; kullanıcı oturumu kapatıp açmadığı sürece **hiç çalışmıyordu**.
Bot ölünce onu ayağa kaldıran hiçbir şey yoktu.

**Çözüm (ilk deneme YANLIŞTI):** Tekrar `LogonTrigger`'a bağlandı. Windows'ta
logon tetikleyicisinin tekrar penceresi **yalnızca logon olayı ateşlendiğinde**
başlar. Görev logon'dan sonra kurulduğu için tetikleyici hiç ateşlenmedi;
`NextRunTime` boş kaldı, yani hiçbir çalışma planlanmadı.

Bu, canlı testte yakalandı: bot 21:19:36'da kasten öldürüldü, **8.5 dakika
geri gelmedi**. Görev "Running → Ready" geçişini doğru yapıyordu — durum
makinesi hakkındaki çıkarım doğruydu, ama oradan "demek ki tekrar tetiklenecek"
sonucu YANLIŞTI.

**Çalışan çözüm:** Logon tetikleyicisine ek olarak **zamana dayalı** ikinci bir
tetikleyici (`MSFT_TaskTimeTrigger`, `PT10M`). Logon olayından bağımsız çalışır.

**Gözlemlenerek doğrulandı:** plan 21:38:04 → bot fiilen 21:38:05'te başladı
(yeni PID 30560), bakiye `10000 − 2.64 − 22.58 = 9974.78` doğru devredildi,
açık BNBUSDT pozisyonu korundu, `NextRunTime` 21:48:04'e ilerledi.

Periyodik tetikleme güvenli, çünkü `baslat_bot.bat` çalışan bir bot varsa
hemen çıkıyor (çift-çalıştırma koruması her iki yönde test edildi).

**Kalıcı kontrol:** `(Get-ScheduledTaskInfo -TaskName ASTRA_Bot).NextRunTime`
boşsa watchdog YOKTUR — görev "Ready" görünse bile.

---

### K-5 SL/TP dolum modeli canlıdan farklıydı (paper + backtest)

**Bulunuş:** İlk gerçek paper işlemleri kapanınca zarar beklenenin çok
üstündeydi — canlı gözlem, statik analiz değil.

Paper (`stop_tp_kontrol`) ve backtest (`backtest_engine`) pozisyonu
`guncel_fiyat`tan (bar kapanışından) kapatıyordu. Canlıda ise:
- **SL** = borsada DURAN `STOP_MARKET` → seviyeye değince tetiklenir,
  stop'a yakın dolar; **bot kapalı olsa bile**
- **TP** = limit emri → TP seviyesinden dolar, daha iyisinden değil

Eski model **iki tarafı da abartıyordu**: seviyeyi aşan hareketin tamamı
zarar/kâr olarak yazılıyordu.

**Ölçülen vaka (2026-08-23):** BNBUSDT SHORT giriş 678.4264, SL 685.2127.
Bot 2 gün 8 saat kapalı kaldı (K-3), fiyat 700.06'ya çıktı:

| Model | Kapanış | PnL |
|---|---|---|
| Eski (`guncel_fiyat`) | 700.06 | **−%3.27** |
| Yeni (seviye + slippage) | ≈685.42 | **≈−%1.09** |

**3 kat fark.** 100 işlemlik veri seti sistematik olarak kötümser oluyordu
ve canlıya geçiş kararı buna dayanıyor.

**Çözüm:** Tetikleyen SEVİYEDEN dolum; slippage üzerine ALEYHTE uygulanır.
Paper ve backtest aynı modeli kullanır (§5.3 tutarlılığı).

**Dürüstlük notu:** Gerçek bir fiyat boşluğunda (gap) canlı dolum stop'tan
DAHA KÖTÜ olabilir. Yeni model bunu yakalamaz — yani hafif iyimser. Ama
eski modelin sınırsız kötümserliğinden çok daha gerçekçi; bot kesintisi
uzadıkça eski model saçmalıyordu.

**Mutasyon doğrulaması:** Her iki motor da v56 davranışına döndürüldü →
8 testin 5'i kırmızı, gerçek vaka birebir yeniden üretildi
(`Çıkış 700.2700, beklenen ≈685.4183`, `Zarar %-3.30`).

### K-6 Testler ÜRETİM loguna yazıyordu (teşhis kaydı kirliliği)

K-1 DB yollarını izole etmişti ama **log yolu sabit koduydu**
(`main.py`, `engines/order_engine.py`). Testler `logs/astra.log`'a sentetik
fikstür satırları yazıyordu (BTCUSDT @ 63018.9 gibi). Veriyi bozmuyordu ama
teşhis kaydını güvenilmez yapıyordu — bu oturumda logu inceleyen bir
denetim bu satırları neredeyse gerçek işlem sandı.

**Çözüm:** `ASTRA_LOG_DIR` env değişkeni + izolasyon önyükleyicisinde
yönlendirme. Doğrulandı: test koşusu üretim loguna **0 satır** ekledi
(`63018.9` sayısı 520 → 520).

**Kalıntı:** 2026-08-23 öncesi ~520 fikstür satırı logda DURUYOR (tarihsel
kayıt, silinmedi).

---

### K-7 Watchdog uyku ile donmayı ayırt edemiyordu

**Bulunuş:** 2026-08-24 21:11'de CRITICAL alarm + tam thread dump geldi:
`[WATCHDOG] ALARM! 80678s sessiz`. Bot donmamıştı.

Windows Power-Troubleshooter kaydı kesin: laptop **22 saat 24 dakika**
uyudu (08-23T19:47:52Z → 08-24T18:11:39Z). Log boşluğunun sınırları
saniyesine kadar uyuşuyor (son satır 22:47:54, ilk satır 21:11:37).
Bot uyanınca kendiliğinden toparlandı; heartbeat 25 saniye sonra normale
döndü. Gerçek bir deadlock kendiliğinden çözülmez.

**İki ayrı zarar:**
1. Laptop her uyuduğunda sahte CRITICAL + Telegram alarmı → kullanıcı
   watchdog alarmlarını ciddiye almamayı öğrenir ve **gerçek bir donma
   kaçar**. (Sessiz başarısızlığın aynadaki hâli: gürültülü yanlış alarm.)
2. `_uyari_sayisi >= 3` olunca watchdog `os.kill(getpid(), SIGTERM)` ile
   **botu öldürüyor**. Uyanış 3 dakikayı aşarsa (yavaş ağ, model yükleme)
   bot kendini kapatır. Windows'ta systemd yok; geri gelmesi zamanlanmış
   göreve kalır → 10 dk'ya kadar veri kaybı. Bu vakada 1 alarmda toparlandı,
   yani kıl payı kaçırıldı.

**Ayrım (kesin imza):** Gerçek donmada watchdog thread'i tıklamaya DEVAM
eder (`tik ≈ check_interval`) ama heartbeat eskir. Askıya almada
`time.sleep(60)` duvar saatinde saatlerce sürer → tik patlar. İkisi
birbirine karışmaz.

**Çözüm:** `_loop` artık tik süresini ölçüyor; `check_interval`ın 3 katını
aşarsa askıya alma sayıp heartbeat tabanını sıfırlıyor ve **alarm vermiyor**
(WARNING ile açıklıyor).

**Mutasyon doğrulaması:** Tespit devre dışı bırakıldı → 3 muhafız kırmızı,
gerçek olay birebir yeniden üretildi (`ALARM! 80678s sessiz`). Kontrol
testleri yeşil kaldı — donma tespiti ve SIGTERM yolu korunuyor.

---

### K-7 Koşullu emirler Algo Service'e taşınmış (ENGEL 1'in kökü)

`/fapi/v1/order` koşullu emirleri artık reddediyor:
```
-4120 "Order type not supported for this endpoint.
       Please use the Algo Order API endpoints instead."
```
`exchangeInfo` hâlâ "destekliyor" diye beyan ettiği için çelişki
görünüyordu. Şema testnet'te deneyerek çıkarıldı →
**`BINANCE_ALGO_EMIR_SEMASI.md`**.

Kilit farklar: `algoType=CONDITIONAL` (yeni, zorunlu) ·
`stopPrice` → **`triggerPrice`** · yanıtta `orderId` → **`algoId`**.

**Sadece endpoint değiştirmek YETMEZ — üç tuzak:**

1. **Algo emirleri klasik `openOrders` listesinde GÖRÜNMÜYOR.**
   SL varlığı kontrol eden 7 yer bunu göremezdi → reconciler her turda
   gereksiz acil SL koyar, failsafe pozisyonu korumasız sanıp kapatır,
   orphan temizliği eski emirleri hiç silmez.
   Çözüm: `koruma_emirleri()` — klasik + algo birleşik, algo kaydını
   normalize eder (`orderType`→`type`, `algoId`→`orderId`, `_algo` bayrağı).

2. **`TRAILING_STOP_MARKET` + `closePosition` reddediliyor** (`-4136`).
   `quantity` kullanılmalı. Naif taşıma trailing korumayı sessizce
   öldürürdü — her çağrı hata döner, üst katman `None` görüp devam eder.

3. **Çift-emir koruması algo yolunda devre dışıydı.**
   `"/order" in "/fapi/v1/algoOrder"` **FALSE** döner. v53 idempotency'si
   algo emirlerinde hiç çalışmıyordu → ağ timeout'u + retry İKİ stop-loss
   koyabilirdi. `clientAlgoId` ile kapatıldı (testnet: `-4116`).

**Doğrulama:** `testnet_emir_dogrula.py` **9/9** — projede ilk kez.

### K-8 Bot açtığı pozisyonu state'ine kaydetmiyordu

`execution_engine.pozisyon_ac()` içinde:
```python
self._state.pozisyon_ekle({...})   # StateManager'da BÖYLE BİR METOT YOK
```
Doğrusu `pozisyon_ac(...)` — isim de imza da farklı. Her açılışta
`AttributeError` fırlıyor, `except Exception` yutuyordu.

**Sonuç:** `sl_tp_dogrula()` boş state üzerinde dönüyor, gerçek
pozisyonların SL/TP'si **hiç doğrulanmıyordu**; `pozisyon_var_mi()`
hep `False`.

Düzeltildi; state kaydı hatası artık `log.critical`. Ayrıca
`get_execution_engine()` singleton'ı, sonradan `state_manager` istenirse
sessiz kalmak yerine uyarıp bağlıyor (K-2'nin aynısı).

**194 testin hiçbiri bunu yakalamamıştı** — yalnızca gerçek emir döngüsü
çalıştırılınca göründü (§4.2).

---

### K-9 Paper SL/TP canlıdan ayrışıyordu — LONG'lar sistematik kaybediyordu

**20 işlemlik veride yakalandı** (§4.2: çalıştırınca görünen hata):

| Yön | n | Kazanan | Stop mesafesi |
|---|---|---|---|
| **LONG** | 8 | **0** | %0.11–0.83 (dağınık) |
| SHORT | 12 | 5 | %1.00–1.03 (tutarlı) |

8 LONG'un 8'i de kaybetti. Şanssızlık değil — **kod**.

`paper_trading.py` stop'u iki FARKLI kaynaktan alıyordu:
```python
if yon == "LONG":
    stop = risk.get("stop_loss") or (fiyat - atr*2)   # risk_hesapla çıktısı
else:
    stop = fiyat + atr*2                              # tabanlı atr
```
`risk_hesapla()` **yön parametresi almıyor** (core/sinyal_skor.py:181) ve
yukarıdaki `atr = max(son_atr, fiyat*0.005)` **%0.5 tabanını BYPASS**
ediyordu. Ölçüm: 8/8 LONG tabanı atladı, bir stop **%0.11**'e indi
(ima edilen ATR: fiyatın %0.056'sı). Gürültü o stop'u kesin vurur.

**Ayrışma LONG'la sınırlı değildi:**

| | Canlı | Paper (eski) |
|---|---|---|
| SL | 1.5×ATR (config) | 2×ATR / tabansız |
| TP1 | 2.0×ATR | 3×ATR |
| Rejim ayarı | VOLATILE ×1.3 | yok |

Yani **20 işlemin tamamı** canlıda çalışmayacak bir sistemin verisiydi.
R/R bile farklıydı (paper 1.5:1, canlı 1.33:1).

**Çözüm:** Paper artık canlının `sl_tp_hesapla()` fonksiyonunu kullanıyor —
tek kaynak, üç ayrım birden kapandı, yeniden ayrışmaları imkânsız.

**Muhafız:** `tests/test_paper_canli_sl.py` (8 test).
İlk yazımda 7 testin 6'sı mutasyonu KAÇIRDI — çünkü `sl_tp_hesapla`'nın
kendi özelliklerini ölçüyorlardı, paper'ın onu KULLANDIĞINI değil.
Gerçek paper pozisyonu açıp DB'deki SL'i ölçen davranışsal test eklendi;
mutasyonda hatayı birebir yeniden üretiyor
(`LONG stop %0.130, SHORT %1.000`).

**Veri:** 20 işlem + 1 açık pozisyon SİLİNDİ (yedek:
`data/_yedek_v57sl_20260829_205150/`). Sayım düzeltilmiş modelle
sıfırdan başladı.

---

### K-10 Telegram grafikleri bozuluyordu — pyplot thread-safe değil

**Kullanıcı bildirimi (2026-09-02):** "Telegram'da oluşan resimler bazen
simsiyah, bazen beyaz kalıyor."

`main.py::_grafik_olustur` pyplot'un **global durumunu** kullanıyordu:
```python
fig, axes = plt.subplots(...)   # global "current figure"
plt.tight_layout()
plt.savefig(yol); plt.close()
```

Ama coin analizi 5 sembol için **gerçek thread havuzunda** eşzamanlı
çalışıyor (`main.py:1777` `loop.run_in_executor(None, coin_analiz, ...)`
+ `asyncio.gather(...)`). pyplot'un figür kaydı thread-safe DEĞİL:

```
Thread A: plt.subplots()  → figür A "current"
Thread B: plt.subplots()  → figür B "current" oldu
Thread A: plt.savefig()   → B'yi / yarım tuvali kaydeder
Thread A: plt.close()     → B'yi KAPATIR
Thread B: plt.savefig()   → figür yok → BOŞ görüntü
```

Belirtiyle birebir uyuşuyor:
- **simsiyah** = `facecolor="#0d1117"` basılmış, içerik çizilmemiş
- **bembeyaz** = hiç figür yok, varsayılan boş tuval

**ÖLÇÜLDÜ (5 eşzamanlı üretim, PNG renk çeşitliliği):**

| Kod | Renk sayıları | Bozuk |
|---|---|---|
| Eski (`plt` global) | `[1, 1, 1, 1, 670]` | **4/5** |
| Yeni (`Figure` OO) | `[1630 × 5]` | **0/5** |

**Çözüm:** `matplotlib.figure.Figure` + `FigureCanvasAgg` — pyplot'a hiç
dokunulmuyor. Global kayıt yok, `plt.close()` gerekmiyor (çöp toplayıcı
halleder) ve thread'ler birbirinin figürünü göremiyor.

**Muhafız:** `tests/test_grafik_thread.py` (4 test). Mutasyonda eski kod
geri konunca `4/5 grafik BOZUK (renk sayıları: [1,1,1,1,64])` ile kırmızıya
dönüyor.

**Not:** Kaynak kontrolü testi ilk yazımda YANLIŞ ALARM verdi — docstring'de
eski kodu *açıklarken* geçen `plt.savefig` metnini gerçek çağrı sandı.
AST ile ayrıştırıp docstring'i atlayacak şekilde düzeltildi.

---

## 🟡 DESTEKLEYİCİ DEĞİŞİKLİKLER

### D-1 Sabit kodlu yollar env'e açıldı
`config.py` konvansiyonuna uyduruldu:
- `engines/model_registry.py:21` → `MODEL_REGISTRY_DB`, `MODEL_VERSIONS_DIR`
- `engines/ab_test.py:23` → `AB_DATA_PATH`

Bunlar sabit kodlu kaldığı sürece test izolasyonu **eksik** kalıyordu.

### D-2 `temizle_test_artefakti.py` (tek seferlik)
Geçmiş kirliliği temizler, kendi yedeğini alır. Çalıştırıldı:

| Hedef | Önce | Sonra |
|---|---|---|
| `astra.db::trades` | 67 | **0** |
| `astra.db::performance` | 10 | **0** |
| `journal.db::journal` | 73 | **0** |
| `model_registry::model_versions` | 130 | **70** |
| `saved_models/versions` | — | 60 sahte `.pkl` silindi |
| `ab_test.json` | sentetik | sıfırlandı |

`model_registry`'de **gerçek** eğitim kayıtları korundu:
BTCUSDT 27, BNBUSDT 18, ETHUSDT 10, SOLUSDT 9, XRPUSDT 6 = 70 satır.
Yedek: `data/_yedek_v57_20260820_222326/`

---

## 🧪 TESTLER — `tests/test_izolasyon.py` (9 test)

§4.1 kuralı gereği muhafız testlerinin yanına **kontrol testleri** yazıldı.
"Üretim dosyasına yazılmadı" iddiası, yazma yolunun tamamen ölü olmasıyla da
sağlanır — kontrol testleri geçici dizine **gerçekten** yazıldığını kanıtlar.

| Test | Ne kanıtlıyor |
|---|---|
| `test_tum_yollar_gecici_dizine_yonlendirildi` | 5 env değişkeninin tamamı yönlendirilmiş |
| `test_config_gecici_yollari_okudu` | `izole_et()` config'ten ÖNCE çalışmış |
| `test_paper_islemi_uretim_dosyalarina_dokunmaz` | **MUHAFIZ** — 10 işlem, üretim parmak izi sabit |
| `test_kontrol_paper_islem_gecici_dbye_yaziliyor` | **KONTROL** — yazma yolu canlı |
| `test_kontrol_journal_gecici_dosyaya_yaziliyor` | **KONTROL** — journal yazma yolu canlı |
| `test_get_journal_varsayilani_configten_gelir` | K-2 regresyonu |
| `test_journal_yol_catismasi_sessiz_kalmaz` | Çatışma sessiz kalmıyor |
| `test_izole_et_idempotent` | Önyükleyici tekrar çağrılabilir |
| `test_uretim_yol_listesi_eksiksiz` | Koruma listesi eksiksiz |

### Mutasyon doğrulaması (testin kırmızıya dönebildiğinin kanıtı)
§4.1'in ana dersi "yeşil test kanıt değil" olduğu için muhafız testi
kasten bozuldu: `izole_et()` geçici olarak etkisizleştirildi.

```
[HATA] test_paper_islemi_uretim_dosyalarina_dokunmaz
  → ÜRETİM verisi test tarafından değiştirildi: ['data/astra.db', 'data/journal.db']
[HATA] test_tum_yollar_gecici_dizine_yonlendirildi
  → JOURNAL_DB_PATH ayarlanmamış — izolasyon eksik
```

Muhafız gerçekten ateşliyor. Mutasyon geri alındı, kalıntı kontrol edildi.

**Not:** Kontrol testi ilk yazımda alfabetik koşu sırasına bağımlıydı ve
yanlış sebeple kırmızıydı; kendi işlemini açacak şekilde düzeltildi.
(§4.3 — hata iddia etmeden önce doğrula.)

---

## 🧪 TESTLER — `tests/test_ana_thread.py` (7 test)

| Test | Ne kanıtlıyor |
|---|---|
| `test_telegram_donerse_ana_thread_bitmez` | **MUHAFIZ** — K-3 regresyonu |
| `test_telegram_kapaliyken_de_ana_thread_bitmez` | `BOT_TOKEN` boşken de motor yaşar |
| `test_paket_yoksa_da_ana_thread_bitmez` | Paket yokken de motor yaşar |
| `test_kontrol_telegram_gercekten_yeniden_deneniyor` | **KONTROL** — sadece uyumuyor, deniyor |
| `test_kontrol_yeniden_deneme_backoff_uyguluyor` | **KONTROL** — backoff var, üst sınırlı |
| `test_kontrol_telegram_kapaliyken_bosuna_denemiyor` | Kapalıyken boşuna çağrı yok |
| `test_bot_modu_denetimli_katmani_cagiriyor` | Kaynak düzeyinde: doğrudan çağrı geri gelmemiş |

**Kontrol testleri neden şart:** "Asla dönmeyen" bir fonksiyon muhafız
testlerini de geçer — sonsuza kadar uyusa bile. Kontrol testleri Telegram'ın
gerçekten yeniden çağrıldığını ve beklemenin makul olduğunu ayrıca kanıtlıyor.

### Mutasyon doğrulaması
`telegram_denetimli_calistir()` kasten v56 davranışına (doğrudan çağır + dön)
döndürüldü:

```
SONUÇ: 1 geçti, 6 başarısız (toplam 7)
  [HATA] test_telegram_donerse_ana_thread_bitmez
    → telegram_denetimli_calistir() DÖNDÜ — ana thread biter ve daemon
      trading motoru öldürülür (v56 hatası geri gelmiş)
```

Mutasyon geri alındı, kalıntı kontrol edildi.

---

## ✅ DOĞRULAMA

```
python testleri_calistir.py     → 178 test, 0 başarısız
```
Snapshot → koşu → diff ile ölçülen kirlilik: **YOK**.
`main.py` import zinciri temiz (17.1s, hata yok), dashboard "0 kapalı işlem".
`JOURNAL_DB_PATH` özel bir yola ayarlandığında journal artık o dosyayı
kullanıyor (fiilen doğrulandı — dosya oluştu).

---

## ⚠️ DAVRANIŞ DEĞİŞİKLİKLERİ

1. **Paper sayacı sıfırlandı.** 33 → 0. Önceki değer sahteydi; 3 haftalık
   hedef bugünden itibaren sayılmalı.
2. **`get_journal()` artık `JOURNAL_DB_PATH`'e uyuyor.** Bu ayarı `.env`'de
   değiştirmiş olan bir kurulumda journal **yeni** dosyaya yazmaya başlar;
   eski `data/journal.db` içeriği taşınmalıdır.
3. **Yol çatışması artık `log.error` basıyor.** Bu log görünürse journal'ın
   bölünme riski var demektir — yeni hata değil, görünür hale gelen eski hata.
4. **Testler artık üretim verisine yazmıyor.** Test koşusundan sonra paper
   sayacının artmaması **beklenen** davranıştır.
5. **Telegram hatası artık botu öldürmüyor.** Ağ koptuğunda Telegram geçici
   olarak sessizleşir ama trading motoru çalışmaya devam eder. Logda
   `[TELEGRAM] Polling durdu (deneme #N)` görürsen bu **beklenen** davranış —
   motor etkilenmez.
6. **Zamanlanmış görev 10 dakikada bir çalışır.** Bot ayaktaysa `.bat` hemen
   çıkar (logda tek satır). Bu watchdog davranışıdır, hata değildir.
