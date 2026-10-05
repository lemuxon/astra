# ASTRA — DEVAM NOTLARI

> **Bu belge, sohbet geçmişi kaybolsa bile çalışmanın kaldığı yerden
> sürmesi için yazıldı.** Son güncelleme: 2026-09-13
>
> Önce bunu oku, sonra `CHANGELOG_v57.md` → `CHANGELOG_v56.md`
> (hataların detayı orada).

---

## 0. ⚠️ ÖNCE BUNU OKU — STRATEJİ DURUMU

**2026-09-03: Kârsızlığın SEBEBİ bulundu ve bir kapı eklendi.**

### Bulgu: kayıp sinyalden değil, ARİTMETİKTEN geliyordu

21 işlemlik veri ikiye ayrıldığında tablo netleşti:

| Grup | n | Win rate | Gerçekleşen R/R | Gereken R/R | Beklenti |
|---|---|---|---|---|---|
| **TP/STOP ile kapanan** | 10 | **%50** | **0.64** | 1.00 | −%0.197 |
| Sinyal dönüşüyle kapanan | 11 | %18 | 0.20 | 4.50 | −%0.147 |

**Sinyal kötü değil** — TP'ye mi SL'e mi önce değeceği konusunda %50 isabet.
Ama sistem yazı turada bile kaybediyordu çünkü **hedef stop'tan yakındı**.

### Kök neden: VOLATILE çarpanları R/R'ı ters çeviriyor

`engines/futures_trade_engine.py::sl_tp_hesapla`:
```python
elif rejim == "VOLATILE":
    sl_mult  = FUTURES_SL_ATR_MULT * 1.3    # 1.5 → 1.95×ATR  (stop GENİŞLER)
    tp1_mult = FUTURES_TP_ATR_MULT * 0.75   # 2.0 → 1.50×ATR  (hedef DARALIR)
```

| Rejim | R/R | Gereken win rate |
|---|---|---|
| RANGE / TREND | 1.33 | %43 |
| **VOLATILE** | **0.77** | **%57** |

Piyasa **%92 VOLATILE** (1917 gözlem vs 138 TREND, 19 RANGE);
21 işlemin 14'ü bu ters oranla açılmıştı.

**Bu çarpanların HİÇBİR GEREKÇESİ YOK** — changelog'larda ve denetim
raporlarında açıklama bulunamadı, çıplak sabitler. Stop'u genişletmek
mantıklı (gürültü artar) ama hedefi AYNI ANDA daraltmak R/R'ı 1'in
altına indiriyor. Bilinçli tasarım gibi durmuyor.

### Yapılan: MİNİMUM R/R KAPISI (v57 K-11)

`sl_tp_hesapla` R/R'ı zaten hesaplayıp döndürüyordu ama **hiçbir yer
kontrol etmiyordu** — sistem "0.77" diye hesaplayıp yine de açıyordu.

- `config.MIN_RR = 1.2` (env ile ayarlanabilir)
- `rr_yeterli_mi()` — **paper VE canlı** yollarının ikisinde de (§5.3)
- Etki: VOLATILE (0.77) engellenir, RANGE/TREND (1.33) geçer
- Eşik matematikle seçildi: R/R > (1-p)/p, p=%50 → başabaş 1.0, 1.2 pay bırakır
- Muhafız: `tests/test_rr_kapisi.py` (7 test), mutasyonla doğrulandı

**Sayaç 4. kez sıfırlandı** (yedek: `data/_yedek_rr_20260903_013254/`).

### ⚠️ SIRADAKİ OTURUMUN YÜZLEŞECEĞİ SORU

Piyasa %92 VOLATILE ve kapı VOLATILE'i engelliyor. Yani bot **çok az
işlem açacak** — belki günlerce hiç.

Bu, üç olasılıktan birini gösterecek:

1. **RANGE/TREND işlemleri kârlıysa** → strateji çalışıyor, sadece
   VOLATILE'de çalışmıyor. Kapı doğru çözüm. Veri yavaş birikir.
2. **Hiç işlem açılmıyorsa** → strateji bu piyasa rejiminde kullanılamaz.
   VOLATILE çarpanları yeniden tasarlanmalı (TP'yi daraltmak yerine
   stop'la orantılı tutmak) — ama bu STRATEJİ kararı, kod değil.
3. **RANGE işlemleri de kaybediyorsa** → sorun R/R'da değil, sinyalde.
   O zaman model/eşik çalışması gerekir.

**Önce 1-2 hafta veri bekle, sonra karar ver.** Aceleyle çarpan
değiştirmek dördüncü sıfırlamayı beşinci yapar.

---

## 0.1 v58 — BEŞ KÖK NEDEN DÜZELTİLDİ (2026-09-03)

Tam analiz: **`ANALIZ_KAYIP_NEDENI.md`** (21 işlem + 23.742 sinyal,
gerçek Binance 1m barlarıyla doğrulandı).

**Sayaç 0'da.** Bu beş değişiklik davranışı değiştiriyor; veri
toplanmaya başlamadan önce yapıldıkları için şanslıyız. K-16 sonrası
bot 14:04'te yeniden başlatıldı ve o ana kadar hiç işlem açılmamıştı,
yani ek sıflama gerekmedi.

### K-12 — Çıkış kapısı, giriş kapısından ZAYIFTI

`paper_trading.py::sinyal_isle` zıt sinyalde kapatırken hiçbir eşik
uygulamıyordu (kapatma bloğu `_filtre_gec`'ten ÖNCE çalışıyor):

```
AÇILIŞ  : |ai| >= 4 VE conf >= 62
KAPANIŞ : karar metninde "BUY"/"SELL" geçmesi YETERLİ
```

ai=3 / conf=55 bir sinyal pozisyon **açamaz** ama açık pozisyonu
**kapatabiliyordu**. Ölçüm: zıt sinyalle kapanan **11 işlemin 11'i** de
açılış eşiğinin ALTINDAKİ sinyalle kesilmişti. Karşı-olgusal (gerçek
1m barlar): tutulsalardı %−0.83, kesilince %−1.62 → **0.79 puan**,
toplam zararın %22'si.

**Düzeltme:** `_sinyal_kalitesi_gecer()` ayrı metoda çıkarıldı, çıkış
`_cikis_gecerli()` üzerinden aynı barı uyguluyor.

### K-13 — Paper ↔ canlı ÇIKIŞ yolu ayrışması (§5.3)

Canlı, zıt pozisyonu ancak chop → MTF → Edge → strateji →
`sinyal_gecerli_mi` zincirini geçtikten sonra kapatıyor
(`main.py:1441`). Paper ise ham `coin_analiz` çıktısıyla veto
zincirinin **dışında** çağrılıyordu (`main.py:1829`).

**Düzeltme:** `_cikis_gecerli()` artık `sinyal_gecerli_mi()`'yi de
çağırıyor (rejim eşiği dahil), hata halinde fail-closed.

⚠️ **TAM EŞİTLİK DEĞİL:** chop/MTF/EdgeEngine/strateji vetoları hâlâ
paper'da yok — onlar `_execution_isle` içine gömülü. Paper çıkışı
canlıdan hâlâ bir miktar GEVŞEK. Tam eşitlik için veto zincirinin
ortak modüle çıkarılması gerekir (§6'ya eklendi).

### K-14 — Kapanış sonrası bekleme yoktu

Motor kapattığı sembolde **aynı saniye** ters pozisyon açabiliyordu
(#15 LONG kapanış 04:07:50 → #16 SHORT açılış 04:07:50; ikisi toplam
%−0.45 saf maliyet). Kapanış→açılış boşluğu medyan 92 sn, **minimum 0**.

Bu bir paper hatası DEĞİLDİ — canlı yol da aynısını yapıyordu
(kapat → `sleep(0.5)` → aç). Düzeltme bu yüzden **iki yolda birden**.

- `config.YENIDEN_GIRIS_BEKLEME_SN = 300` (env ile ayarlanabilir)
- **Sembol bazlı**, yalnızca AÇILIŞI engeller — kapanış her zaman serbest
- Global olsaydı (%92 VOLATILE + R/R kapısı) veri toplama tamamen dururdu
- 300 sn = bir 5m bar. Seni yeni stop'lamış barın içinde tekrar girmek
  yeni bilgi değil. Veriye bakılarak değil ilkeyle seçildi.

**TUZAK (yakalandı):** `ts_kapat` NAIVE UTC yazılıyor. Yaş hesabında
`datetime.now()` (yerel) kullanılsaydı bu makinede yaş 3 saat şişer,
kapı **hiç tetiklenmez ve hata sessiz kalırdı** (§5.2). Muhafız:
`test_kapanis_yasi_utc_olceginde_hesaplanir`.

### K-15 — Piyasa verisi TESTNET'ten geliyordu

Analizdeki "bayat fiyat" teşhisi **YANLIŞTI** — düzeltirken gerçek
mekanizma bulundu. Paper işlemi #21 anındaki 5m barlar:

| Kaynak | O | H | C |
|---|---|---|---|
| **Testnet** | 98.79 | **99.94** | 98.47 |
| **Gerçek** | 98.55 | 98.63 | 98.47 |

Testnet'te gerçek piyasada **olmayan** bir sıçrama vardı. Bot henüz
KAPANMAMIŞ bara baktığı için o anki "close" 99.92 okundu ve oradan
SHORT açıldı. TP 99.14 zaten piyasanın altında kaldı → **2.9 dakikada
"TP"**, +%0.64. 21 işlemdeki 5 kazançtan biri, gerçek piyasada hiç var
olmayan bir fiyattandı.

**Fiyat bayat değildi — tazeydi ama testnet'e özgüydü.** Testnet spot
likiditesi ince; tek bir test emri fiyatı %1.5 oynatıyor. Ölçüm:
sinyallerin %2.3'ü gerçek piyasadan >%0.5, %0.54'ü >%1 sapmış.

**Düzeltme:** `config.BINANCE_DATA_URL` (varsayılan gerçek borsa).
Halka açık piyasa verisi (klines, ticker) gerçek borsadan; hesap ve
emir işlemleri `BINANCE_BASE_URL`'de kalıyor. Klines anahtar
gerektirmediği için ek risk yok.

⚠️ `exchangeInfo` **bilerek** taşınmadı — o, emrin gideceği borsanın
kurallarıdır (min_notional, lot adımı). Kontrol testi bunu kilitliyor.

**Not:** WebSocket zaten gerçek endpoint'i (`stream.binance.com`)
kullanıyordu. Yani kline'lar testnet, WS gerçekti — bu tutarsızlık da
kapandı.

**Bot 2026-09-03 13:52'de yeniden başlatıldı** — dört düzeltme de aktif.
(Değişiklikler `config.py` okuma anında etkili olur; çalışan süreç eski
değerleri kullanmaya devam ederdi.)

### 5. SIFIRLAMA — 2 kirli işlem silindi (2026-09-03 13:51)

K-11 sonrası bot 01:33'te başlamış ve 2 paper işlemi toplamıştı. İkisi
de **eski çıkış mantığı + testnet verisiyle** toplandı:

| # | sonuç | kapanış | not |
|---|---|---|---|
| 1 | −%0.86 | STOP | — |
| 2 | −%0.56 | BUY_SİNYALİ | **ai=3 < 4** → K-12 kusurunun 12. vakası |

Silindi (yedek: `data/_yedek_v58_20260903_135138/`). §5.3 gereği:
toplanan tüm veri TEK bir yapılandırmayı yansıtmalı.

### K-16 — Göstergeler KAPANMAMIŞ barla hesaplanıyordu

Binance'in döndürdüğü SON mum, içinde bulunulan periyodun **henüz
kapanmamış** barıdır; `Close` alanı o andaki fiyattır ve her saniye
değişir. Tüm göstergeler (RSI, MACD, ATR, Bollinger) bu yarım barla
hesaplanıyordu — sinyal, bar ilerledikçe **kendi altından değişen** bir
zemine dayanıyordu.

K-15 testnet sıçramalarını kapattı ama gerçek piyasada da geçici
fitiller olur; kök sorun veri kaynağı değil, yarım bar kullanmaktı.

**#21 vakası ikisinin birleşimiydi:** oluşan barın anlık close'u 99.92
gösterdi, bar 98.47'de kapandı. Kapanmış bar kullanılsaydı o sinyal
hiç doğmayacaktı.

**Düzeltme:** `klines_indir` oluşan barı atıyor.

- Tespit `close_time` ile: "son barı hep at" YANLIŞ olurdu — geçmiş
  aralık istendiğinde (backtest, `endTime`) son bar kapanmıştır ve
  atılırsa veri sessizce kaybolur. Yalnızca `close_time` GELECEKTEyse atılır.
- `limit+1` isteniyor → çağıran taraf yine aynı sayıda KAPANMIŞ bar alır
  (canlı doğrulama: 576 → 576, 481 → 481)

**İKİ AYRI İHTİYAÇ, karıştırılmadı:**

| | Kaynak | Neden |
|---|---|---|
| Göstergeler / sinyal | **kapanmış bar** | kararlı zemin |
| SL/TP kontrolü | **anlık fiyat** | canlıda SL borsada duran `STOP_MARKET`'tir, her tick'te tetiklenir; bar kapanışını beklemez (§5.3) |

Oluşan bar `df.attrs["olusan_bar"]` ile taşınıyor, `sonuc["anlik_fiyat"]`
olarak `stop_tp_kontrol`'e gidiyor. Bu ayrım yapılmasaydı paper, canlının
çoktan tetiklediği stop'u 5 dakikaya kadar geç görecekti.

Muhafız: `tests/test_kapanmis_bar.py` (6 test), üç yönde mutasyonla
doğrulandı (barı atma / koşulsuz at / SL-TP'yi bar kapanışına döndür).

### Muhafızlar

| Dosya | Test |
|---|---|
| `tests/test_cikis_kapisi.py` | 7 (K-12/K-13) |
| `tests/test_yeniden_giris.py` | 7 (K-14) |
| `tests/test_veri_kaynagi.py` | 6 (K-15) |
| `tests/test_kapanmis_bar.py` | 6 (K-16) |

Üçü de **mutasyonla doğrulandı** (§4.1): koruma kasten bozuldu,
testler kırmızıya döndü, mutasyon geri alındı. K-15'te iki yön birden
denendi (klines'ı testnet'e geri al / exchangeInfo'yu yanlışlıkla
taşı) — ikisi de yakalandı.

### ⚠️ Test fikstürlerinde ortaya çıkan sorun

4 mevcut test kırmızıya döndü. Sebep **kod değil fikstürdü**:
`karar="SELL"` verirken `ai_score=+8` bırakıyorlardı. Üretimde `karar`
doğrudan `ai_score`'dan türer (`karar_ver`), yani bu kombinasyon
**imkânsızdır** — yeni çıkış kapısı haklı olarak reddetti.
Fikstürler tutarlı hale getirildi, iddialar zayıflatılmadı.

Ayrıca tutarlı fikstürle kapanış sonrası meşru ters pozisyon açılıyor;
açık kalanlar `MAX_OPEN_POSITIONS=1` üzerinden SONRAKİ testleri sessizce
engelliyordu. Testler artık sonunda düzleştiriyor (`_paper_sahne`).

**Ders:** Gerçekçi olmayan test fikstürü, gerçek bir kapıyı test
edilemez kılar. Fikstür üretimdeki üretim kuralına uymalı.

---

## 0.2 v58 — SAHTE ACCURACY BULUNDU (2026-09-03)

**"Kağıt üzerinde %99, canlıda yazı tura" bilmecesi çözüldü.**
Sorun model ya da feature'larda DEĞİL, **ölçümün kendisindeydi.**

### Zincir

1. **K-17 — uydurma etiketler.** `_self_train_tetikle(sembol, 0.0)`
   drift tespitinde çağrılıyordu (ortada kapanmış işlem yokken).
   İçerideki `gercek_sonuc = 1 if pnl_pct > 0 else 0` kuralı her
   çağrıda bir `target=0` kaydı yazıyordu.
   **Ölçüm: 954 feedback kaydının 917'si (%96) uydurma.**
   `feedback_BTCUSDT.jsonl` → target dağılımı `{0: 221, 1: 1}`,
   222 kaydın 214'ünde `pnl_pct=0.0`.

2. **K-18 — bu kayıtlar TEST setini oluşturuyordu.**
   `feedback_veri_yukle` onları verinin SONUNA ekliyordu; her eğitici
   `train_test_split(..., shuffle=False)` ile SON %20'yi test yapıyordu.
   Sonuç: test seti tamamen feedback ve **tek sınıflı**.

| BTCUSDT 14g/1h | test_acc | test'te target=1 |
|---|---|---|
| feedback YOK | **0.516** | 0.484 (dengeli) |
| feedback VAR | **0.963** | **0.000** ← tek sınıf |

   Model %96'yı, tek sınıflı sette "0" diyerek alıyordu.
   Dürüst 0.516 = çoğunluk sınıfı taban çizgisi (0.518).

3. **K-19 — parametre seçimi test setine bakıyordu.**
   `rf_optimize(X_tr,y_tr,X_te,y_te)` Optuna'ya 25 denemede TEST
   setindeki f1'i maksimize ettiriyordu; LGB'de `eval_set=[(X_te,y_te)]`
   ile early stopping aynısını yapıyordu; XGB'de her ikisi de vardı.
   **Ölçülen şişme: +2.6 puan.**

### İki bağımsız yöntem aynı sonuca varıyor

| Yöntem | Sonuç |
|---|---|
| Dürüst model accuracy | **0.516** (taban çizgisi 0.518) |
| Sinyal → ileri getiri (23.742 sinyal, blok bootstrap) | excess **+%0.003, p=0.93** |

**Modelin öngörü gücü sıfır.** Bu, `ANALIZ_KAYIP_NEDENI.md` §3'teki
sonucu bağımsız olarak doğruluyor.

### Yapılanlar

- **K-17:** `_self_train_tetikle(..., gercek_islem=False)` varsayılan;
  feedback YALNIZCA gerçek kapanışta yazılıyor. 917 uydurma kayıt
  silindi (yedek: `saved_models/_yedek_feedback_20260903_142316/`),
  37 gerçek kayıt kaldı.
- **K-18:** `egitim_test_bol()` — böl, sonra feedback'i YALNIZCA train'e
  ekle. **Test seti artık yalnızca piyasa verisi.**
- **K-19:** Optuna/early-stopping train'den ayrılan doğrulama setini
  kullanıyor; XGB'de `eval_set` tamamen kaldırıldı (early stopping yoktu
  ama ileride açılırsa sessiz sızıntı olurdu).
- **K-20:** Model seçimi artık **walk-forward** ile. `test_acc` hâlâ
  loglanıyor ve registry'ye yazılıyor ama SEÇMİYOR. Her aday için
  `[ADAY/...] test_acc=… WF=…` satırı basılıyor.
- **K-21:** `MODEL_DIR` env ile yönlendirilebilir + `izole_et()`'e
  eklendi. Öncesinde sabit koduydu; testler ÜRETİM `saved_models/`
  dizinine yazıyordu (kanıt: `rf_TESTUSDT.pkl` kalıntısı). Feedback
  dosyaları modelin EĞİTİM VERİSİDİR — korumasız kalmaları §4.6'nın
  tam olarak uyardığı durumdu.

### Canlı doğrulama (bot 14:38'de yeni kodla başlatıldı)

```
ÖNCE:  [XGB/BNBUSDT] test_acc=1.000
       [LGB/SOLUSDT] test_acc=0.989
SONRA: [XGB/BNBUSDT] test_acc=0.527 WF=0.527±0.045
       [LGB/BNBUSDT] test_acc=0.427 WF=0.525±0.065
       [MODEL/BNBUSDT] seçildi: xgb_BNBUSDT test_acc=0.527 WF=0.527
```

Zehirli feedback'le eğitilmiş 28 model dosyası silindi
(yedek: `saved_models/_yedek_model_20260903_143833/`).

Muhafız: `tests/test_model_olcum.py` (11 test), üç yönde mutasyonla
doğrulandı.

### ⚠️ BUNUN ANLAMI

WF değerleri 0.51–0.57, std ±0.04–0.08. Yani **hiçbiri 0.5'ten
istatistiksel olarak ayırt edilemiyor.** `MIN_USEFUL_ACC = 0.52`
eşiğini bazı modeller kıl payı geçiyor — bu bir edge kanıtı değil,
gürültü.

**Bu eşiği YÜKSELTME ya da düşürme.** Sonuç beğenilmediği için eşik
oynatmak, `karar_kurali.py` için konan kuralın (§0) aynısını ihlal eder.

**Yeni durum:** Artık dürüst bir metrik var. Bundan sonraki her feature
/ model denemesi ÖLÇÜLEBİLİR. Öncesinde bu mümkün değildi — her
değişiklik 0.99 gösteriyordu.

### 🔍 KARAR BEKLEYEN: sonraki adım strateji, kod değil

R/R optimizasyonu ikinci sırada: 42 SL/TP kombinasyonu denendi,
tamamı sıfır civarında (en iyi +%0.51 → işlem başına +%0.028).
Edge yokken geometri kurtarmıyor.

Asıl soru: **bu feature seti fiyat yönünü öngörebilir mi?**
Şu an cevap hayır. Denenebilecekler (hiçbiri denenmedi):
- Farklı hedef: "sonraki bar yönü" yerine "N bar içinde TP'ye mi SL'e mi
  değer" (üçlü bariyer) — işlem mantığıyla uyumlu tek etiket budur
- Daha uzun ufuk (1 bar çok gürültülü)
- Rejim bazlı ayrı modeller
- Feature azaltma (42 feature / ~970 satır aşırı öğrenmeye açık)

---

## 0.3 v58 — ÜÇLÜ BARİYER DENENDİ, İŞE YARAMADI (2026-09-03)

**Hipotez:** Model "bir sonraki mum yeşil mi" tahmin ediyordu. Ama bot
mumun rengine göre değil SL/TP seviyelerine göre kazanıyor. Hedefi
işlemin gerçek sonucuna bağlarsak (López de Prado üçlü bariyer) daha
öğrenilebilir bir problem olur.

**Sonuç: HAYIR.** Hipotez ölçüldü ve reddedildi.

### Ölçüm — 60 gün, 5m, 5 sembol, ÖRTÜŞMEYEN örneklem

| yön | n | model P(TP) | taban | fark | p | beklenti |
|---|---|---|---|---|---|---|
| SHORT | 1259 | 0.4376 | 0.4332 | +0.0044 | **0.386** | %−0.094 |
| LONG  | 1390 | 0.4518 | 0.4483 | +0.0035 | **0.406** | %−0.069 |

Maliyet dahil başabaş P(TP) = 0.4914. İkisi de uzak.

### Baş başa (aynı ekonomik yargıç ile, 7 gün)

| eğitim hedefi | seçilen | P(TP\|model=1) | taban | fark | p |
|---|---|---|---|---|---|
| sonraki_bar | 2636 | 0.4215 | 0.4098 | +0.0117 | 0.115 |
| ucgen_bariyer | 2295 | 0.4031 | 0.4098 | **−0.0067** | 0.75 |

Üçlü bariyer eski hedeften **hafif kötü**.

### ⚠️ ARADA YAPILAN İKİ HATA (ders niteliğinde)

1. **Sembol bazında precision ORTALAMASI aldım** → "+5.24 puan edge"
   çıktı. Havuzlanmış (doğru ağırlıklı) hesapta **−0.0067**'ye döndü.
   Küçük katmanlar eşit ağırlık alınca yanıltıcı sonuç doğuyor.
2. **Örtüşen etiketlerle binom testi** → SHORT tarafında p=0.0002
   göründü. Örtüşmeyen örneklemde p=0.062'ye, 60 günde **p=0.386**'ya
   düştü. Üçlü bariyer etiketleri 24 bar örtüşür; bağımsızlık varsayan
   her test p'yi şişirir.

**Ders:** §10'un aynısı — küçük örneklemde temiz görünen desen altıncı
gözlemde çöker. Bu sefer 57 gözlemlik bir "keşif" 1259 gözlemde yok oldu.

### VARSAYILAN DEĞİŞTİRİLMEDİ

`HEDEF_TIPI = "sonraki_bar"` (eski davranış). Kanıt değişikliği
desteklemiyor; varsayılanı "kavramsal olarak daha doğru" diye
değiştirmek, VOLATILE çarpanlarını buraya getiren hatanın aynısı olurdu.

Makine duruyor ve test edilmiş: `HEDEF_TIPI=ucgen_bariyer` yeterli.
Muhafız: `tests/test_ucgen_bariyer.py` (10 test), üç yönde mutasyonla
doğrulandı. Testlerin işi hedefin İYİ olduğunu değil, DOĞRU
HESAPLANDIĞINI kanıtlamak.

### Yan ürün — K-22: EĞİTİM/SERVİS ZAMAN DİLİMİ UYUŞMAZLIĞI

Bu iş sırasında bulundu ve **düzeltildi** (hedeften bağımsız gerçek hata):

- Ana döngü `coin_analiz(period="2d", interval="5m")` → modeli **5m**
  feature'larıyla eğitip çalıştırıyor
- Drift retrain ise `veri_indir(period="14d", interval="1h")` kullanıp
  **AYNI model dosyasını** (rf_BTCUSDT.pkl) 1h ile eğitilmiş olanla
  eziyordu

`ATR`, `Momentum_5`, `Volatility_10`, `MA20` gibi feature'ların ölçeği
1h ve 5m'de tamamen farklı — model, eğitildiği dağılımdan bambaşka bir
girdi görüyordu. Retrain artık `period="7d", interval="5m"` kullanıyor
(servisle aynı zaman dilimi, eğitim için daha uzun pencere).

### Ayrıca eklendi: embargo

`walk_forward_cv(embargo=N)` ve `egitim_test_bol` — üçlü bariyer
kullanılırsa train'in son `HEDEF_MAX_BAR` satırı atılıyor. Bu olmadan
üçlü bariyer eski hedeften **daha iyi** görünüyordu; sebebi sızıntıydı.
Varsayılan `embargo=0`, yani mevcut çağıranların davranışı değişmedi.

### 🔍 SIRADAKİ ADAY FİKİRLER (hiçbiri denenmedi)

Hedef değişikliği tükendi. Geriye kalanlar:
- **Feature azaltma** — 42 feature / ~970 satır aşırı öğrenmeye çok açık
  (train accuracy 0.999, test 0.516). Önce bunu denemek mantıklı.
- **Daha uzun eğitim penceresi** — 60 günlük 5m verisi (17k bar) var,
  bot yalnızca 2 gün (576 bar) kullanıyor.
- **Rejim bazlı ayrı modeller**
- **Farklı ufuk** (HEDEF_MAX_BAR 24 dışında değerler)

---

## 0.4 v58 — EĞİTİM PENCERESİ ÖLÇÜLDÜ, UZATILMADI (2026-09-03)

**Hipotez:** Train accuracy 0.999 / test 0.516 klasik aşırı öğrenme.
42 feature'a karşılık yalnızca ~576 satır var. Pencereyi uzatmak
oranı düzeltir.

**Sonuç: uzunluk fark etmiyor.** Ama yolda İKİ GERÇEK HATA çıktı.

### Ölçüm — 60 gün 5m, 5 sembol, sabit 1 günlük test pencereleri

40 ölçüm (5 sembol × 8 katman). `fark` = accuracy − çoğunluk sınıfı
taban çizgisi:

| gün | eğitim barı | ort_fark | std | p | süre |
|---|---|---|---|---|---|
| 2 | 576 | −0.0039 | 0.0370 | 0.51 | 20 sn |
| 7 | 2016 | −0.0043 | 0.0379 | 0.48 | 107 sn |
| 15 | 4320 | +0.0017 | 0.0292 | 0.71 | 387 sn |
| 30 | 8640 | −0.0001 | 0.0306 | 0.99 | 776 sn |

**Hiçbiri edge üretmiyor** (p ≥ 0.48). Tek kazanç varyansın düşmesi
(std 0.037 → 0.029) ve o da 15 günden sonra, **19× hesap maliyetiyle**.
Retrain zaten sembol başına dakikalar sürüyor (Optuna 25 deneme + TFT).

➜ **Pencere 2 günde bırakıldı.** Kanıt uzatmayı desteklemiyor.
Denemek için `MODEL_EGITIM_PERIOD` yeterli.

### K-24 — 1000 BAR SESSİZ KIRPMASI (gerçek hata)

Binance tek istekte en fazla 1000 mum döner. `_period_to_limit` bunu
**sessizce kırpıyordu**:

```
istenen "7d/5m"  = 2016 bar  →  alınan 1000 (≈3.5 gün)
istenen "30d/5m" = 8640 bar  →  alınan 1000 (≈3.5 gün)
```

Hiçbir uyarı yoktu. **K-22'de retrain'i "7d/5m"e çevirmem de gerçekte
1000 bar getiriyordu** — yani o düzeltmenin yarısı sessizce etkisizdi.
"Eğitim penceresini uzat" diyen her değişiklik aynı duvara çarpardı.

§5.2'nin ("istenen ≠ yapılan olduğu her yerde sesli ol") ihlaliydi.

**Düzeltme:** `_period_to_limit` artık kırpmıyor; `klines_indir`
1000'den fazlası istendiğinde `endTime` ile **geriye doğru sayfalıyor**.
Doğrulandı: 2d→576, 7d→2017, 30d→8641 bar; kronolojik ve tekrarsız.

⚠️ Sayfalı ve tek-istekli yol **ortak `_klines_df()`** kullanıyor. İki
kopya olsaydı K-16'nın (oluşan barı at) yalnızca birinde çalışması
kaçınılmazdı. Muhafız testi bunu kilitliyor.

### K-25 — Eğitim penceresi TEK KAYNAK

İki yol iki farklı pencereyle **aynı model dosyasına** yazıyordu:

| yol | pencere | bar |
|---|---|---|
| ana döngü | `coin_analiz(2d/5m)` | 576 |
| drift retrain | `14d/1h` | 336 (üstelik farklı TF — K-22) |

Modelin neyle eğitildiği, hangi yolun son çalıştığına bağlıydı.
Artık ikisi de `MODEL_EGITIM_PERIOD` / `MODEL_EGITIM_INTERVAL`
kullanıyor.

### Muhafız

`tests/test_sayfalama.py` (7 test), üç yönde mutasyonla doğrulandı
(kırpmayı geri getir / sayfalamayı kapat / retrain'i 1h'e döndür).

### 🔍 GERİYE KALAN FİKİRLER

Hedef değişikliği (§0.3) ve pencere uzatma tükendi. Denenmemiş:
- **Feature azaltma** — 42 feature / 576 satır hâlâ kötü oran.
  Pencere uzatmak oranı düzeltmedi; feature azaltmak diğer yön.
- **Rejim bazlı ayrı modeller**
- **Farklı ufuk / eşik ayarları**

⚠️ Bu üçü de denenirse ölçüm ŞART: son üç hipotez (üçlü bariyer,
uzun pencere, ve öncesinde R/R optimizasyonu) mantıklı görünüp
ölçümde reddedildi.

---

## 0.5 v58 — FEATURE AZALTMA DENENDİ (2026-09-03)

**Hipotez:** Train accuracy 0.999 / test 0.516 aşırı öğrenme.
42 feature çok fazla; azaltmak genelleme sağlar.

**Sonuç: azaltmak edge üretmiyor.** Ama yolda YAPISAL bir kusur bulundu.

### Ölçüm — 60 gün 5m, 5 sembol, 40 eşli katman

`fark` = accuracy − çoğunluk sınıfı taban çizgisi.
Feature seçimi HER KATMANDA yalnızca train ile yapıldı (seçim sızıntısı yok):

| varyant | kol | ort_fark | std | p |
|---|---|---|---|---|
| A. Tüm 42 (mevcut) | 42 | −0.0039 | 0.0370 | 0.51 |
| **B. Ham seviye atıldı** | 35 | **+0.0011** | **0.0311** | 0.82 |
| C. Top-5 | 5 | −0.0032 | 0.0310 | 0.52 |
| C. Top-10 | 10 | −0.0021 | 0.0372 | 0.73 |
| C. Top-15 | 15 | +0.0007 | 0.0351 | 0.90 |
| C. Top-20 | 20 | −0.0089 | 0.0337 | 0.11 |

**Top-k seçimi yardımcı olmuyor** → sorun feature SAYISI değil.

### K-26 — HAM FİYAT SEVİYESİ FEATURE DEĞİLDİR

Feature setinde fiyat birimli 11 kolon vardı:

| kolon | sorun | durağan karşılığı |
|---|---|---|
| MA20, EMA9, EMA21, EMA50, EMA200 | ham fiyat seviyesi (ort ≈ 67.383 = BTC'nin kendisi) | Price_EMA50, Price_EMA200, EMA9_21_cross |
| OBV, OBV_MA20 | kümülatif, sınırsız büyür | OBV_Diff |
| MACD, MACD_Hist | EMA farkı → fiyat birimi | (yok — fiyata bölündü) |
| ATR | fiyat birimi | ATR_pct (zaten vardı) |
| Candle_Strength | mum gövdesi → fiyat birimi | (yok — fiyata bölündü) |

Ağaç modelleri **mutlak eşikte** böler ve eğitim aralığının dışına
**ekstrapole edemez**. BTC ölçüm penceresinde 67k → 77k gitti; 67k'da
öğrenilen "EMA50 > 67.234" kuralı 77k'da hiçbir şey ifade etmez.

**Yapılan:** 7'si atıldı (durağan karşılıkları zaten vardı), 4'ü
fiyata bölünerek yüzdeye çevrildi. **42 → 34 feature.**
Doğrulama: fiyatı 1000x yapınca kayan feature KALMADI.

⚠️ **GEREKÇE PERFORMANS DEĞİL, DOĞRULUK.** Eşli fark +0.0050 ama
**p=0.347** — anlamlı değil. Ölçümün işi "daha iyi mi" değil, "zarar
veriyor mu" idi; vermiyor. Yan fayda: varyans %16 düşük, eğitim %25 hızlı.

**Denendi ve REDDEDİLDİ:** "atmak yerine büyüklüğü durağanlaştırıp ekle"
(Price_MA20, EMA9_21_dist, OBV_Norm) → eşli fark −0.0046 (p=0.153),
yani daha kötü. O büyüklük bilgisi değersiz.

**Etki (canlı log):** Top feature listesi anlamlı hale geldi —
öncesinde `Price_EMA200`/`EMA9`/`MA20` üstteydi, şimdi
`ADX`, `Williams_R`, `Taker_Ratio`, `Momentum_20`, `CVD_Norm`.

Eski 27 model dosyası silindi (42 feature ile eğitilmişlerdi, uyumsuz).
Yedek: `saved_models/_yedek_feat_20260903_233616/`

### K-27 — WF SEÇİMİ ÇOĞU ZAMAN DEVREDE DEĞİLDİ

K-20 model seçimini walk-forward'a bağlamıştı. Ama WF yalnızca
**eğitim anında** hesaplanıyordu; önbellekten yüklenen modelin meta'sı
boş geldiği için `WF=0` oluyor ve seçim sessizce `test_acc`e düşüyordu.

Modeller 1 saat taze kaldığından bu, çağrıların **çoğunluğuydu** —
üretim logunda **229 kez** `"hiçbir adayda WF yok"` uyarısı.

➜ **Uyarıyı sesli yazmasaydım bu boşluk görünmezdi** (§5.2 tam da
bunun için var).

**Düzeltme:** WF artık modelin yanına `wf_<isim>.json` olarak
kaydediliyor ve yüklenirken geri okunuyor.

### Muhafızlar

| Dosya | Test |
|---|---|
| `tests/test_feature_duraganlik.py` | 6 (K-26) |
| `tests/test_model_olcum.py` | 14 (K-17..21, K-27) |

Mutasyonla doğrulandı. K-26'da ölçek testi **isim listesine değil
ÖLÇEĞE** bakıyor — yarın `SMA100` eklenirse isim listesi bilmez ama
1000x testi yakalar.

### ⚠️ TEST FİKSTÜRÜ SINIRI (kayda değer)

"Hiçbir feature sabit olmasın" testi yazdım, `SuperTrend_Dir`'de
kırmızıya döndü. Gerçek veride kontrol ettim: sağlıklı (−1/+1, std
0.99). Yani kod kusuru değil, sentetik serinin rejim döndürmemesiydi.
Testin iddiası daraltıldı ve sebebi docstring'e yazıldı.

### 🔍 DURUM: DÖRT HİPOTEZ, DÖRT RET

| # | hipotez | sonuç |
|---|---|---|
| 1 | R/R optimizasyonu | 42 kombinasyon, hepsi ≈0 |
| 2 | Üçlü bariyer hedefi | p=0.386 / 0.406 |
| 3 | Uzun eğitim penceresi | hepsi p≥0.48 |
| 4 | Feature azaltma | hepsi p≥0.10 |

**Kalıp net:** sorun tek tek ayarlarda değil. Bu feature seti 5m
ufukta fiyat yönü hakkında ölçülebilir bilgi taşımıyor.

Denenmemiş tek yön: **farklı BİLGİ KAYNAĞI**. Mevcut 34 feature'ın
tamamı fiyat/hacim türevi. Order book derinliği, funding rate, açık
pozisyon (open interest), likidasyon akışı hiç kullanılmıyor —
`market_data.py` bunların bir kısmını zaten çekiyor ama feature
setine girmiyor.

---

## 0.6 v58 — PİYASA YAPISI FEATURE'LARI DENENDİ (2026-09-04)

**Hipotez:** Mevcut 34 feature'ın tamamı fiyat/hacim türevi. Fiyat
dışı bilgi (order book, funding, open interest, konumlanma) yeni bir
sinyal kaynağı olabilir.

**Sonuç: REDDEDİLDİ.** Ama içinde kritik bir metodoloji dersi var.

### Önce veri gerçeği — ORDER BOOK EKLENEMEZ

| veri | granülarite | geçmiş | eğitilebilir mi |
|---|---|---|---|
| **Order book derinliği** | anlık | **YOK** | ❌ |
| Open interest | 5m | 30 gün | ✅ |
| Long/short oranı | 5m | 30 gün | ✅ |
| Taker buy/sell | 5m | 30 gün | ✅ |
| Funding rate | **8 saat** | aylar | ⚠️ 5m'de basamak |

Binance geçmiş order book snapshot'ı **sunmuyor**. Feature ancak
geçmişi varsa eğitilebilir. Kullanmak için şimdiden kaydetmeye başlayıp
haftalarca beklemek gerekir — ayrı bir karar.

⚠️ Bu, inşaata BAŞLAMADAN önce kontrol edildi. Sonra fark edilseydi
boşa emek olurdu.

### Ölçüm — 29 gün 5m, 5 sembol, 40 eşli katman

Eklenen 8 feature (hepsi K-26 dersine uygun, ham seviye YOK):
`OI_Degisim_5/20`, `LS_Ratio`, `LS_Degisim`, `Taker_BuySell`,
`Taker_Degisim`, `Funding`, `Funding_Degisim`

| varyant | kol | ort_fark | std | p |
|---|---|---|---|---|
| A. Mevcut | 34 | +0.0002 | 0.0290 | 0.970 |
| B. + piyasa yapısı | 42 | −0.0021 | 0.0336 | 0.701 |

**Eşli fark B−A: −0.0023, t=−0.44, p=0.665.**

### ⚠️ ÖNEMLİ DERS: FEATURE ÖNEMİ ≠ TAHMİN GÜCÜ

Yeni feature'lar önem sıralamasında **üst sıralara çıktı**:

```
en önemli 8: ADX 0.056 | Volume_Ratio 0.056 | Taker_BuySell 0.053
             Taker_Degisim 0.050 | Candle_Strength 0.049
             OI_Degisim_5 0.048 | LS_Ratio 0.046 | Price_EMA200 0.038
```

Model bunları **yoğun kullanıyor** (3., 6., 7. sırada) ama örneklem
dışı doğruluk düşüyor. Bu, gürültüye aşırı uyumun ders kitabı tanımı:
model onlarda yapı buluyor, ama o yapı geleceğe taşınmıyor.

➜ **`feature_importances_` bir feature'ın değerli olduğunun KANITI
DEĞİLDİR.** Sadece modelin onu kullandığını söyler. Karar için
örneklem dışı ölçüm şart. (Log satırındaki "Top features" çıktısı da
bu gözle okunmalı.)

**Funding tahmin edildiği gibi değersiz** (önem 0.010 ve 0.002) —
8 saatlik veri 5m ufukta 96 barda bir değişiyor.

### EKLENMEDİ

Kanıt desteklemiyor. Önem sıralaması cazip diye eklemek, tam olarak
yukarıdaki dersin ihlali olurdu.

Veri indirme altyapısı duruyor (`scratchpad/indir.py`), tekrar denemek
isteyen için hazır.

### 🐛 Yan bulgu — sonsuz döngü (ölçüm betiğinde)

İlk indirme betiği 27 dakika çalışıp sıfır çıktı verdi. Sebep: sayfalama
döngüsünde **ilerleme kontrolü yoktu**; veri sonuna gelince aynı
pencereyi sonsuza kadar istiyordu. Yeni sürümde `son <= cur` kilidi var
ve indirme 3 dakikada bitiyor.

Bu üretim kodunda değil ölçüm betiğindeydi, ama kalıp aynı: **döngü
ilerlemesi doğrulanmayan her sayfalama sonsuza gidebilir.**
`data/binance_client.py::_klines_sayfali` (K-24) bu açıdan kontrol
edildi — orada `len(d) < ...` ile kırılma var, güvenli.

---

## 0.7 BEŞ HİPOTEZ, BEŞ RET — DURUM DEĞERLENDİRMESİ

| # | hipotez | sonuç | p |
|---|---|---|---|
| 1 | R/R optimizasyonu | 42 kombinasyon ≈ 0 | — |
| 2 | Üçlü bariyer hedefi | ret | 0.386 / 0.406 |
| 3 | Uzun eğitim penceresi | ret | ≥0.48 |
| 4 | Feature azaltma | ret | ≥0.10 |
| 5 | Piyasa yapısı feature'ları | ret | 0.665 |

**Yorum:** Sorun tek tek ayarlarda değil. Beş bağımsız yön denendi,
beşi de aynı yere çıktı: bu kurulum 5 dakikalık ufukta fiyat yönü
hakkında ölçülebilir bilgi üretmiyor.

### Aritmetik — hedefe uzaklık

| | değer |
|---|---|
| Gidiş-dönüş maliyet | %0.11 |
| TP / SL | %1.00 / %0.75 |
| Başabaş isabet | **%49.1** |
| %20/yıl için gereken (≈1000 işlem) | **%50.3** |
| Modelin ulaştığı | **%40–45** |

### ➜ ÖNERİLEN SONRAKİ YÖN: UFUK DEĞİŞİKLİĞİ

5m kripto yön tahmini, piyasadaki en rekabetçi alandır (colocation,
emir akışı, milisaniye). Halka açık göstergelerle orada rekabet
yapısal olarak zor — beş retin ortak açıklaması bu olabilir.

**Öneri:** 5m yerine **4h/günlük bar**, günde 3 işlem yerine haftada
2-3. Maliyet sabit kalır (%0.11) ama hedef büyür: %1'lik hedefte
maliyet ağırken %5'lik hedefte önemsizleşir.

Mevcut altyapının çoğu aynen çalışır — risk yönetimi, SL/TP, R/R
kapısı, ölçüm zinciri. Değişecek olan `MODEL_EGITIM_INTERVAL`,
`SCAN_INTERVAL` ve `coin_analiz` çağrılarındaki `interval`.

⚠️ **Bu da bir hipotezdir.** Aynı disiplinle ölçülmeli: uygulamadan
önce 4h barlarla walk-forward, sonra karar.

---

## 0.8 v58 — UFUK ÖLÇÜMÜ: BEŞ RETİN ORTAK AÇIKLAMASI BULUNDU (2026-09-04)

**Bu, oturumun en önemli ölçümü.** Beş hipotezin neden reddedildiğini
tek bir sayı açıklıyor.

### Gereken BECERİ FARKI (3 yıl, 5 sembol, 1h/4h/1d + 60 gün 5m)

`beceri farkı = başabaş P(TP) − ölçülen taban oran`
→ "sistemin kazanması için modelin taban oranı NE KADAR geçmesi gerek"

| ufuk | ATR% | maliyet/TP | başabaş | SHORT taban | **BECERİ FARKI** |
|---|---|---|---|---|---|
| **5m** | 0.148 | **%37.2** | 0.6412 | 0.4350 | **+20.6 puan** |
| 1h | 0.846 | %6.5 | 0.4657 | 0.4363 | +2.9 puan |
| 4h | 1.788 | %3.1 | 0.4462 | 0.4332 | **+1.3 puan** |
| 1d | 4.806 | %1.1 | 0.4351 | 0.4328 | **+0.2 puan** |

### ➜ 5m YAPISAL OLARAK İMKÂNSIZ

5 dakikalık barda ATR medyanı **%0.148**. TP = %0.30, SL = %0.22.
Gidiş-dönüş maliyet %0.11 → **hedefin %37'si maliyete gidiyor.**

Başabaş için gereken isabet **%64.1**. Taban oran %43.5.
Yani model taban oranı **20.6 puan** geçmeli. Böyle bir tahmin gücü
finansal piyasalarda yoktur.

**Bu, beş retin ortak açıklaması.** R/R, hedef, pencere, feature
sayısı, veri kaynağı — hiçbiri 20 puanlık açığı kapatamaz.
Sorun modelde değil, **oynanan oyunda**.

Ufuk uzadıkça gereklilik çöküyor: 5m'de 20.6 puan, 4h'de 1.3, 1d'de 0.2.
**~16× (4h) ve ~90× (1d) daha kolay bir problem.**

### ⚠️ BOĞA PİYASASI TUZAĞI — YAKALANDI

İlk hesapta 1d'de beceri farkı **NEGATİF** (−0.0075) çıktı; bu
"rastgele işlem kâr eder" demek olurdu. Doğrulandı:

```
Örneklem 2023-08 → 2026-09:  BTC +198%  ETH +45%  SOL +409%
                              BNB +218%  XRP +164%   ORT +207%
```

Negatiflik edge değil, **yukarı sürüklenme**. LONG taban oranı ufukla
birlikte şişiyor (0.4384 → 0.4525), SHORT tarafı ise sabit
(0.4350 → 0.4328). Tablodaki rakamlar bu yüzden **SHORT tarafından**
alındı — sürüklenmeden arınık tek ölçü.

➜ **Bu örneklemle long-only bir sistem kurulmamalı.** Ayı piyasasında
ters döner.

### Model tarafı: HİÇBİR UFUKTA BECERİ YOK

Aynı 34 feature, bar sayısı sabit (train 1000 / test 100):

| ufuk | accuracy − taban | p |
|---|---|---|
| 5m | −0.0297 | 0.001 |
| 1h | −0.0333 | 0.000 |
| **4h** | **−0.0205** | 0.015 |
| 1d | −0.0542 | 0.000 |

Hepsi **anlamlı biçimde NEGATİF** — model sabit tahminciden kötü.
Yani ufuk değiştirmek tek başına kâr getirmez.

### ➜ SONUÇ: İKİ AYRI PROBLEM

| | durum |
|---|---|
| **Maliyet yapısı** | 5m'de imkânsız → 4h/1d'de çözülüyor ✅ |
| **Tahmin gücü** | her ufukta yok ❌ |

Ufuk değişikliği **gerekli ama yeterli değil**. 5m'de mükemmel bir
model bile kaybeder; 4h'de vasat bir model kazanabilir.

**Öneri:** Önce ufku 4h'e taşı (imkânsız problemi zor probleme çevir),
sonra model üzerinde çalış. Tersi sırayla çalışmak boşa emek —
son beş denemenin gösterdiği gibi.

### Denenmemiş, artık daha anlamlı yönler (4h zemininde)

- Ufuk 4h olunca eğitim verisi 3 yıla çıkıyor (6599 bar) — 5m'de
  yalnızca 60 gün geriye gidilebiliyordu
- Rejim bazlı ayrı modeller (3 yılda birden çok rejim var)
- Basit kural tabanlı stratejiler (4h'de maliyet %3, deneme ucuz)

---

## 0.9 v58 — BOT 4h UFKUNA TAŞINDI (K-29, 2026-09-04)

§0.8'deki ölçümün gereği yapıldı. **Sayaç 6. kez sıfırlandı.**

### Değişenler

| ayar | eski | yeni |
|---|---|---|
| `ANA_INTERVAL` / `ANA_PERIOD` | 5m / 2d | **4h / 180d** (yeni, tek kaynak) |
| Ana döngü `coin_analiz` | sabit `2d/5m` | `ANA_PERIOD/ANA_INTERVAL` |
| `MODEL_EGITIM_*` | 2d / 5m | ANA_* ile aynı |
| Eğitim barı | 576 | **1081** |
| MTF hiyerarşisi | sabit 4h/1h/15m/5m | **türetilen 1w/1d/4h** |
| MTF ana trend | sabit `"1h"` | tabanın bir üstü (**1d**) |
| Yeniden giriş beklemesi | sabit 300 sn | **bar-göreli → 4 saat** |
| `HEDEF_MAX_BAR` | 24 (=2 saat) | 6 (=1 gün) |

### ⚠️ TAŞIMADA YAKALANAN İKİ SESSİZ ÖLÜM

Bunlar taşımanın "yarım" kalmasına yol açardı ve **hiçbir hata
vermezdi**:

**1. MTF cascade vetosu ölürdü.** `ana_trend_yon` kodda `"1h"`e
SABİTTİ. 4h tabanda hiyerarşide "1h" hiç bulunmaz → `ana_trend_yon`
her zaman `"NÖTR"` → `bloklu` asla `True` olmaz. Bir güvenlik kapısı
sessizce devre dışı kalırdı. Aynı şekilde `elif tf in ("5m",)`
tetikleyici kontrolü de ölü kalırdı. İkisi de hiyerarşiden türetildi.

**2. Yeniden giriş beklemesi anlamsızlaşırdı.** Sabit 300 sn, 5m barda
"bir bar"dı; 4h barda **aynı barın içinde 48 kez** yeniden girmeye
izin verirdi. Artık `ANA_BAR_DK * 60` ile türüyor.

➜ **Ders:** Ufuk değişikliği yalnızca bir `interval` düzenlemesi değil.
Zaman dilimine bağlı HER sabit gözden geçirilmeli; bunlar tip hatası
vermez, sadece sessizce yanlış olur.

### Canlı doğrulama (bot 01:29'da yeniden başlatıldı)

```
Binance klines: BTCUSDT 4h → 1081 kapanmış bar      (ana analiz)
Binance klines: BTCUSDT 4h →  181 kapanmış bar      (MTF bağlamı)
[MODEL/ETHUSDT] seçildi: gb_ETHUSDT test_acc=0.548 WF=0.537
[MODEL/XRPUSDT] seçildi: lgb_XRPUSDT test_acc=0.569 WF=0.498
ERROR: 0
```

SL/TP ölçekleri kontrol edildi (BTCUSDT, ATR %1.34):

| rejim | SL | TP | R/R | R/R kapısı |
|---|---|---|---|---|
| TREND/RANGE | %2.00 | %2.67 | 1.33 | GEÇER |
| VOLATILE | %2.61 | %2.00 | 0.77 | **RED** |

### Muhafız

`tests/test_ufuk_tutarlilik.py` (8 test) — ufka bağlı ayarların TEK
KAYNAKTAN türediğini kilitliyor. Mutasyonla doğrulandı.

⚠️ **Mutasyon testi kendi testimdeki kusuru buldu:** MTF hiyerarşisini
`mtf_confluence_skoru` içinde yeniden sabit kodlayan mutasyon
YAKALANMADI, çünkü test yalnızca `_tf_hiyerarsi()` yardımcısını
doğruluyordu — TÜKETİCİNİN onu kullandığını değil. §4.1'deki "yanlış
katmanı doğrulayan test" tuzağının birebir örneği. Test düzeltildi.

### Sayaç ve yedekler

| | |
|---|---|
| Silinen | 2 paper işlemi (1 kapanmış +%0.89, 1 açık) |
| DB yedeği | `data/_yedek_4h_20260904_012918/` |
| Model yedeği | `saved_models/_yedek_4h_20260904_012918/` |
| 5m modelleri | silindi (feature ölçekleri uyuşmaz — K-22) |

### ⚠️ BEKLENTİ YÖNETİMİ

**Bu değişiklik kârlılık getirmez, MÜMKÜN kılar.** §0.8'de ölçüldü:
model 4h'de de taban oranın altında (−0.0205, p=0.015).

Beklenen fark:
- Maliyet baskısı 12× azaldı (hedefin %37'si → %3.1'i)
- Gereken beceri 20.6 puandan 1.3 puana düştü
- Eğitim verisi 60 günden 3 yıla çıkabilir (şu an 180 gün)

**İşlem sıklığı düşecek:** günde ~3 yerine haftada ~2-3. 100 işlem
hedefi aylar sürer. Bu bir kusur değil, ufkun doğal sonucu.

### 📅 İLK GÖZLEM (2026-09-04 02:16, geçişten 24 dk sonra)

**İşlem yok — ama tıkanma değil.** 4h barlar 00/04/08/12/16/20 UTC'de
kapanıyor; restart'tan bu yana tek bar bile kapanmamıştı. Bot aynı barı
tekrar tekrar değerlendiriyordu (logda fiyatlar birebir aynı).

**Günde 6 kez yeni bilgi** geliyor (5m'de 288'di).

#### ⭐ BEKLENMEYEN İYİ HABER: VOLATILE REJİMİ KAYBOLDU

| rejim | 5m (eski, ~2000 gözlem) | 4h (ilk gözlem) |
|---|---|---|
| **VOLATILE** | **%92** | **0** |
| TREND_UP | 138 toplam | 13 |
| RANGE | 19 | 10 |
| TREND_DOWN | | 4 |

Bu, tüm hikâyenin başladığı yerdi: VOLATILE çarpanları R/R'ı 0.77'ye
düşürüyor, K-11 kapısı da onları engelliyordu. 5m'de piyasa %92
VOLATILE olduğu için kapı neredeyse HER ŞEYİ bloke ediyordu.

4h'de TREND ve RANGE hâkim → R/R 1.33 → **kapıdan geçiyorlar.**
Bir tıkanma kaynağı ufuk değişikliğiyle kendiliğinden ortadan kalktı.

#### O anki durum
```
ETHUSDT  AI:3  %90  TREND_UP  WEAK BUY   ← eşik 4, kıl payı altında
BTCUSDT  AI:0  %65  TREND_UP  WAIT
```
Açılmama sebebi basit: AI skorları eşiğin altında. Chop filtresi de
birkaç coini eliyor. Hata yok, watchdog planlı.

### 🔧 SAĞLIK KONTROL BETİĞİ (yeni)

```bash
python kontrol_4h.py
```

Başlangıç noktası `data/4h_baslangic.json`'a kaydedildi; betik ondan
bu yana FARKI gösteriyor — tempo, işlem listesi, SL/TP yüzdeleri.

**Hüküm VERMEZ** (o `karar_kurali.py`'nin işi, 100 işlem gerekiyor).
İşi artefakt avlamak:
- 10 dakikadan kısa işlem → 4h'de olmamalı
- SL < %1 → 4h'de %2-4 beklenir
- 24 saatte 0 işlem → bir kapı tıkıyor demektir

### 🔴 K-30 — TUR TAVANI: v47 HATASININ TEKRARI (2026-09-04 10:48)

`kontrol_4h.py` ilk çalıştırmada 8.3 saatte **0 işlem** gösterdi.
Teşhis, tıkanmanın sinyal kalitesinde DEĞİL altyapıda olduğunu buldu:

```
tamamlanan tur : 0
zaman aşımı    : 96
[PAPER] satırı : 5   (110 WEAK BUY sinyaline karşılık)
```

**Her coin turu 150 sn'de iptal ediliyordu.** `coin_analiz` 4h'de çok
ağırlaştı (1081 bar + 1w MTF çekimi + 1081 barlık model eğitimi:
Optuna 25 deneme × 4 model + 8 katman walk-forward + TFT). asyncio
görevleri iptal edilince `sinyal_isle` sonuçlara **hiç ulaşmıyordu**.

⚠️ **Bu, v47 hatasının BİREBİR tekrarı:** *"150s tur iptali ...
sinyal_isle hiç çalışmıyordu → 42 sinyal ama 0 paper işlem."*
O sefer sebep grafikti, bu sefer model eğitimi. **Ortak kök: tur
tavanı, turun İÇİNDEKİ işten bağımsız sabit bir sayıydı.**

**Düzeltme:** `COIN_TUR_TIMEOUT` bar-göreli — `max(150, bir_bar/24)`.

| ufuk | tavan | değişim |
|---|---|---|
| 5m | 150 sn | aynı |
| 1h | 150 sn | aynı |
| **4h** | **600 sn** | 4× |
| 1d | 3600 sn | 24× |

**Doğrulandı (10:52):** tur **213.8 sn**'de tamamlandı, 0 zaman aşımı.
Eski tavanın üstünde, yenisinin altında — yani tam da kaybedilen bant.
`[PAPER]` satırları artık görünüyor (`AI skor 3 < 4 → ATLANDI`), yani
sinyal işleme zinciri çalışıyor.

Muhafız: `test_tur_tavani_bar_goreli` + kontrol testi
(`test_tur_tavani_bir_bardan_KISA` — tavan sınırsız da olmamalı).
Mutasyonla doğrulandı.

### ⚠️ ÜÇÜNCÜ KEZ AYNI SINIF

Bu, 4h taşımasında yakalanan **üçüncü** "5m için ayarlanmış sabit":

| sabit | 5m'de anlamı | 4h'de olacaktı |
|---|---|---|
| `ana_trend_yon = "1h"` | tabanın bir üstü | MTF vetosu sessizce ölür |
| `YENIDEN_GIRIS = 300 sn` | bir bar | aynı barda 48 kez giriş |
| `COIN_TUR_TIMEOUT = 150 sn` | bardan hızlı tur | **her tur iptal** |

İlk ikisi taşıma sırasında kod okunarak bulundu; üçüncüsü ancak
**çalıştırınca** ortaya çıktı (§4.2 — "statik analiz yetmiyor").

➜ Ufuk değişikliğinde kural: **zaman dilimine bağlı her sabiti ara,
sonra da çalıştırıp doğrula.**

### 🔍 SIRADAKİ

1. **24 saat sonra `python kontrol_4h.py`.** Gerçek tempoyu ancak
   birkaç bar kapandıktan sonra görebiliriz.
2. **Birkaç hafta veri bekle.** 4h zemininde ilk gerçek ölçüm.
2. Model çalışması artık anlamlı — ama §0.8'deki uyarı geçerli:
   ufuk gerekli, yeterli değil.
3. ✅ **YAPILDI: `MAX_OPEN_POSITIONS` 1 → 3** (2026-09-04 01:52).

   Değer tahminle değil ÖLÇÜMLE seçildi. 4h'de gerçek maruziyet
   (risk_manager ile hesaplanan boyutlar, TREND/RANGE çarpanı):

   | pozisyon | hepsi stop olursa | marj | günlük limit %2 |
   |---|---|---|---|
   | 1 | %0.051 | %0.7 | güvenli |
   | 3 | **%0.152** | **%2.0** | güvenli |
   | 5 | %0.253 | %3.3 | güvenli |

   5 pozisyon bile finansal olarak güvenli, ama **asıl koruma
   `MAX_SAME_DIRECTION=2`**: kripto yüksek korelasyonlu olduğu için
   aynı yönde en fazla 2 pozisyon açılabiliyor. Yani pratik tavan
   zaten 3-4; 3 seçildi (config'in kendi varsayılanı, .env 1'e
   indirmişti).

   Veri toplama hızı ~3× artar. Paper ve canlı yolların İKİSİ de bu
   limiti uyguluyor (§5.3 — `_filtre_gec` ve `risk_manager`).

---

## 0.10 K-31 — BAYAT GİRİŞ FİYATI: KENDİ AÇTIĞIM DELİK (2026-09-05)

**`kontrol_4h.py` ikinci çalıştırmada gerçek bir para kaybı buldu.**
31.6 saat sonra: 2 kapanmış / 2 açık, tempo 3.0 işlem/gün — ama sağlık
kontrolü kırmızı yandı:

```
❌ 10 dk'dan kısa işlem: 1   (4h'de olmamalı — artefakt işareti)
```

### Vaka: paper #7, XRPUSDT LONG, **59 milisaniyede** stop

| | değer |
|---|---|
| Son KAPANMIŞ 4h bar kapanışı (08:00–12:00) | 1.45070 |
| Bot giriş fiyatı | **1.45114** ← bayat |
| O anki GERÇEK fiyat | **1.39120** |
| Sapma | **%−4.13** |
| SL | 1.40440 |
| Sonuç | açılır açılmaz stop, **−%3.33** |

Piyasada var olmayan bir fiyattan girilip anında stop olundu.

### Kök neden — K-16'nın yan etkisi

K-16'da `son_close` KAPANMIŞ barın kapanışına çevrildi (göstergeler için
DOĞRU). Ama **giriş fiyatı da ondan okunuyordu ve güncellenmedi.**
Öncesinde `son_close` zaten oluşan barın anlık fiyatıydı, bu yüzden
sorun görünmüyordu.

- 5m'de bayatlık ≤ 5 dakika → fark edilmez
- **4h'de bayatlık 4 saate kadar** → yıkıcı

➜ K-16 kendi başına doğruydu; **ufuk değişince zararlı hale geldi.**
"5m için ayarlanmış varsayım" sınıfının DÖRDÜNCÜ üyesi.

### Paper ↔ canlı eşitliği de ihlal ediliyordu (§5.3)

Canlı yol (v28, `main.py::_execution_isle`) bunu **zaten doğru
yapıyordu**:
1. `futures_anlık_fiyat()` ile CANLI fiyattan girer
2. Fiyat sinyalin ALEYHİNE çok kaçtıysa işlemi **İPTAL eder**
   ("geç giriş — kovalama yapma", `MAX_GIRIS_KAYMA_PCT`)

Paper'da **ikisi de yoktu** → paper, canlının REDDEDECEĞİ işlemleri
açıyordu.

### Düzeltme

`PaperTrader._giris_fiyati()`:
- Giriş **anlık fiyattan** yapılır
- Fiyat aleyhe kaçmışsa işlem **açılmaz** (canlıyla aynı formül:
  `min(taban + ATR%×0.15, taban×2)`)
- Zıt-sinyal kapanışı da anlık fiyattan

### Veri: CERRAHİ SİLME (tam sıfırlama DEĞİL)

Dört işlemin giriş bayatlığı ölçüldü:

| # | sembol | sapma | karar |
|---|---|---|---|
| 5 | BTCUSDT | +%0.06 | **korundu** |
| 6 | BNBUSDT | +%0.05 | **korundu** |
| **7** | **XRPUSDT** | **+%4.31** | **SİLİNDİ** |
| 8 | ETHUSDT | +%0.04 | **korundu** |

Yeni kodla #5/#6/#8 **birebir aynı** açılırdı (sapma slippage
gürültüsünün altında, iptal eşiğinin çok altında). #7 ise **hiç
açılmazdı**. Bu yüzden yalnızca #7 silindi — temiz veriyi atmak, zaten
yavaş olan toplamayı gereksiz geciktirirdi.

⚠️ **Dikkat:** #7'nin silinmesi PnL'i iyileştiriyor (−%3.33 gidiyor).
Bu, sonucu beğendiğim için değil; o zarar **sahteydi** (var olmayan
fiyattan girildi). Bırakmak ölçümü ters yönde bozardı.
Yedek: `data/_yedek_k31_20260905_100347/`

### Muhafız

`tests/test_giris_fiyati.py` (7 test). Üç yönde mutasyonla doğrulandı:
girişi `son_close`'a döndür / geç giriş iptalini kapat / **her girişi
reddet** (aşırı düzeltme — kontrol testleri yakalıyor).

### 📊 İLK GERÇEK TEMPO

`COIN_TUR_TIMEOUT` düzeltmesinden (K-30) sonra bot gerçekten işlem
açıyor:

| | |
|---|---|
| Tempo | **3.0 işlem/gün** |
| 100 işlem | **≈ 33 gün** |
| SL aralığı | %2.0–%3.2 ✅ (4h'de beklenen) |

---

## 0.11 SKOR BİLEŞENLERİ ÖLÇÜLDÜ — 6. RET (2026-09-05)

**Soru:** "Sürekli STRONG BUY vermesi normal mi?"
36 saatte **723 alış / 14 satış** (52:1) — üstelik piyasa o sürede
%2–4 DÜŞERKEN.

### Önce: yönü normal, şiddeti tasarımdan

Piyasa 30 günde %24 (BTC) / %41 (SOL) yükseldi → trend takip eden sistem
uzun yönlü olmalı. **Kodda yapısal alış yanlılığı YOK** (3 yıl, 4h):

| bileşen | tetiklenme |
|---|---|
| MACD > sinyal | %50.7 (dengeli) |
| RSI / Stoch / Williams / CCI | %40.5 / %53.0 / %24.6 / %17.9 |

Şiddetin sebebi: skor **birbiriyle örtüşen üç trend bileşenine** kilitli.

| bileşen | ağırlık |
|---|---|
| MACD | ±2 |
| MA pozisyonu | ±1 |
| MTF | ±2 |

MACD ile MA yönü 3 yılda **%79.8 aynı** (korelasyon 0.598); MTF ise aynı
serinin üst zaman dilimleri. Trendde üçü birden ±5 veriyor, osilatörler
(±4 ama uç eşikler) dengeleyemiyor. **Aynı bilgi üç kez sayılıyor.**

### 🔴 ÖLÇÜMDE İLERİYE BAKMA YAKALANDI

İlk koşuda **tüm varyantlar** +%3–8 edge gösterdi. Şüphelendim çünkü
önceki beş ölçüm tersini söylüyordu. Sebep:

```python
mtf_seri.reindex(4h_open_time, method="ffill")   # YANLIŞ
```
1d bar **00:00'da açılır, 24:00'da KAPANIR.** `ffill` onu aynı günün
04:00/08:00/12:00 4h barlarına da atıyordu — yani henüz kapanmamış
günün göstergeleri. Aynısı 1w için.

**Düzeltme:** üst TF serisi KAPANIŞ zamanıyla indekslenip 4h barının
kapanış anına göre ffill ediliyor.

⚠️ Üretim kodunda bu sızıntı **YOK** — `mtf_confluence_skoru` analiz
anında `veri_indir` çağırıyor ve K-16 oluşan barı zaten atıyor.
Sızıntı yalnızca benim geriye dönük yeniden üretimimdeydi. Ama
düzeltilmeseydi "bulduk!" diye yanlış bir yola girecektik.

### Sızıntı düzeltildikten sonra — HİÇBİR VARYANT KAZANMIYOR

3 yıl, 4h, 5 sembol, üçlü bariyer yargıcı (TP mi SL mi önce):

| varyant | BUY fark | p | SELL fark | p |
|---|---|---|---|---|
| **A. MEVCUT** | **−0.0081** | 0.814 | **−0.0066** | 0.743 |
| B. MACD ±1 | −0.0175 | 0.904 | +0.0133 | 0.212 |
| C. MA atıldı | −0.0214 | 0.952 | +0.0179 | 0.126 |
| D. MACD nötr bandı | +0.0060 | 0.327 | −0.0114 | 0.786 |
| E. MTF atıldı | +0.0179 | 0.169 | −0.0032 | 0.589 |
| F. Osilatör gevşek | −0.0132 | 0.922 | −0.0005 | 0.528 |

Hepsi p ≥ 0.12. **Dekorelasyon işe yaramıyor.**

### ⚠️ İKİNCİ TUZAK: "pozitif beklenti" ≠ edge

| | P(TP) | beklenti |
|---|---|---|
| Başabaş | 0.4457 | %0 |
| **Taban oran (RASTGELE giriş)** | **0.4853** | **%+0.248** |
| A. MEVCUT (BUY) | 0.4773 | %+0.198 |

Rastgele giriş bile "kârlı" görünüyor — çünkü örneklem boğa piyasası
(2023–2026, +%207). Mevcut skor tabanın **ALTINDA** kalıyor.

➜ **Beklenti rakamına değil, `P(TP) − taban` farkına bakılmalı.**
Aynı tuzak §0.8'de 1d ufkunda da çıkmıştı.

### DEĞİŞİKLİK YAPILMADI

Kanıt desteklemiyor. Skor bileşenlerine dokunmak, önceki beş retin
tekrarı olurdu.

---

## 0.12 K-32/K-33 — PANEL ve TELEGRAM ÇELİŞİYORDU (2026-09-05)

**Kullanıcı iki kaynağın farklı sayı verdiğini fark etti.** İkisi de
gerçek hataydı.

### K-32 — Panel işlemleri ÇİFT SAYIYORDU

| kaynak | işlem | win rate |
|---|---|---|
| Telegram (DB'den okur) | 2 | %50.0 ✅ |
| **Panel** | **3** | **%66.7** ❌ |

Canlı panel çıktısı sorunu doğrudan gösterdi:
```
kapanan_islemler: BNBUSDT TP · BNBUSDT TP · BTCUSDT STOP
                  ^^^^^^^^^^^^^^^^^^^^^^^ AYNI İŞLEM İKİ KEZ
```

**Kök neden — iki bildirim yolu:**
`paper_trading._kapat_ve_bakiye_guncelle` HEM `pozisyon_kapandi_bildir()`
doğrudan çağırıyor HEM DE event bus'a `POSITION_CLOSED` yayınlıyordu.
`main.py::_on_position_closed` dinleyicisi de aynı fonksiyonu çağırıyor
→ her paper kapanışı panele **iki kez** gidiyordu.

**Düzeltme (üç katman):**
1. `paper_trading`'deki doğrudan çağrı KALDIRILDI — event bus tek yol.
   (Event yükü dashboard'ın ihtiyacı olan tüm alanları taşıyor ve canlı
   yol da aynı olaydan geçiyor.)
2. `pozisyon_kapandi_bildir` artık **tekrar koruması** yapıyor: aynı
   (sembol, yön, çıkış, pnl) 60 sn içinde tekrar gelirse yoksayılıyor.
   Kök neden düzeltildi ama "iki yol aynı şeyi yapıyor" bu kod tabanında
   TEKRAR EDEN bir sınıf — savunma katmanı bırakıldı.
3. `_db_gecmisini_yukle` sayaçları artık **sıfırlıyor**. Eskiden `+= 1`
   ile birikiyordu; ikinci kez çalışsa tüm istatistik ikiye katlanırdı.

### K-33 — Bakiye ETİKETİ yanıltıcıydı

| kaynak | değer | gerçekte ne |
|---|---|---|
| Telegram `/pozisyon` | 5k | futures **testnet** hesabı (4999.60) |
| Panel | 10000 | gerçek paper bakiyesi (9819.16) |

**İkisi de doğruydu ama FARKLI ŞEYİ ölçüyordu** ve rapor bunu
söylemiyordu. Paper modda bot futures'ta HİÇ işlem yapmıyor — o rakam
tamamen alakasızdı.

**Düzeltme:** `futures_pozisyon_raporu` artık moda bakıyor:
- canlı → `futures_bakiye()`, etiket "Futures Bakiye"
- paper → `paper_trader.bakiye`, etiket "Paper Bakiye"

### Doğrulama (bot 16:33'te yeniden başlatıldı)

```
PANEL   : {'toplam_islem': 2, 'kazanan': 1, 'kaybeden': 1, 'win_rate': 50.0}
DB/TELE : {'toplam_islem': 2, 'kazanan': 1, 'kaybeden': 1, 'win_rate': 50.0}
kapanan_islemler: BNBUSDT TP · BTCUSDT STOP     ← tekrar YOK
UYUŞUYOR: EVET ✅
```

### Muhafız

`tests/test_rapor_tutarlilik.py` (7 test), üç yönde mutasyonla
doğrulandı (tekrar korumasını kapat / doğrudan bildirimi geri getir /
bakiyeyi koşulsuz futures yap).

### 💡 DERS

Bu iki hata **kod çalışırken hiçbir belirti vermiyordu** — testler
yeşildi, log temizdi. Ortaya çıkmalarının tek sebebi kullanıcının iki
farklı ekrana bakıp **sayıları karşılaştırmasıydı**.

➜ Aynı büyüklüğü raporlayan her iki kaynak, düzenli olarak
karşılaştırılmalı. §10'daki "garip bir şey görürsen ciddiye al"
kuralının somut hali.

---

## 0.13 SAĞLIK KONTROLÜ + ÜÇ KUSUR + REJİM ÖLÇÜMÜ (2026-09-05 akşam)

Oturum `kontrol_4h.py` ile başladı. **Sağlık yeşil**, ama betiğin
kendisi çöktü ve iki kusur daha ortaya çıktı.

### Sağlık durumu (39.5 saat)

```
Kapanmış: 2   Açık: 2   |  Tempo 2.4 işlem/gün → 100 işlem ≈ 41 gün
✅ 10 dk'dan kısa işlem: 0        ✅ SL < %1: 0
```

| id | sembol | yön | SL% | TP% | pnl% | durum |
|---|---|---|---|---|---|---|
| 5 | BTCUSDT | LONG | 1.99 | 2.65 | −2.10 | STOP |
| 6 | BNBUSDT | LONG | 2.02 | 2.69 | +2.58 | TP |
| 8 | ETHUSDT | LONG | 2.81 | 3.75 | — | AÇIK |
| 9 | BTCUSDT | LONG | 2.06 | 2.75 | — | AÇIK |

**İki kaynak uyuşuyor** (K-32/33 tutuyor): panel `{2,1,1,%50}` /
9819.17 — DB `{2,1,1,%50}` / +0.48. Bot PID 20724, 16:33'ten beri
ayakta; zamanlanmış görev `Running`, `NextRunTime` dolu.

Darboğaz dağılımı (4h geçişinden beri):
```
216 AI skor eşiği · 200 yeniden giriş beklemesi
171 korelasyon (aynı yönde 2/2 LONG) · 130 güven eşiği
```

---

### K-34 — GRAFİK YOLU SABİT KODLUYDU (izolasyon deliği)

`logs/` dizininde test artefaktları bulundu: `astra_TESTC0..4.png`,
`astra_TESTTEK.png`.

`main.py::_grafik_olustur`:
```python
yol = f"logs/astra_{sembol}.png"      # SABİT — _LOG_DIR'i atlıyor
```
Aynı dosyanın logging kurulumu `_LOG_DIR` (`ASTRA_LOG_DIR`) kullanıyor;
`izole_et()` onu yönlendiriyor. **Grafik yazımı bu korumanın dışındaydı.**

Bugünkü zarar kozmetikti (sentetik semboller), ama delik şuydu: gerçek
bir sembolle çağrılan bir test, botun Telegram'a gönderdiği grafiği
SESSİZCE ezerdi — kullanıcıya fikstür verisi gerçek piyasa diye giderdi.
§4.6'nın "yeni kalıcı dosya eklersen yolunu env ile yönlendirilebilir
yap" kuralının ihlali.

**Düzeltme:** `os.path.join(_LOG_DIR, ...)`. Artefaktlar silindi.
Muhafız: `tests/test_grafik_thread.py` +3 test (7 toplam). Mutasyonla
doğrulandı — ve **mutasyon 1 (sabit yolu geri getir) üretim `logs/`
dizinine PNG yazdı**, yani deliğin gerçekliği ayrıca kanıtlandı.

⚠️ **Aynı sınıftan kalan:** `nodes/signal_node.py` ve
`nodes/execution_node.py` da `logs/*.log` sabit kodluyor. İkisi de
HİÇBİR yerden import edilmiyor (ölü kod, §6.5) — bu yüzden
dokunulmadı. Canlandırılırlarsa önce bu düzeltilmeli.

---

### K-35 — SAĞLIK BETİĞİ cp1254 KONSOLDA ÇÖKÜYORDU

```
python kontrol_4h.py
UnicodeEncodeError: 'charmap' codec can't encode character '→'
```

§1'in "yeni sohbette İLK bunu çalıştır" dediği betik, Windows'un
varsayılan konsol kodlamasında **çöküyordu**. Bot
`python -X utf8 main.py bot` ile başlatıldığı için üretimde hiç
görünmedi; ancak elle çalıştırılınca çıktı.

Etkisi görünenden büyük: K-31'i (bayat giriş fiyatı, %−4.13) bulan
betik buydu. Erişilemezse artefakt avı yapılamaz.

**Düzeltme:** `SetConsoleOutputCP(65001)` + `stdout.reconfigure(utf-8)`.
İkisi birden gerekli — yalnızca akışı UTF-8 yapmak **çökmeyi** önler
ama konsol cp1254 çözerse Türkçe karakterler mojibake olur.
"Çökmüyor" ile "okunabiliyor" ayrı iddialardır (§5.2).

Muhafız: `tests/test_kontrol_betigi.py` (4 test) — cp1254 alt sürecinde
çalıştırıp raporun SON satırının basıldığını doğruluyor (çökme çıktının
ortasında oluyordu; yalnızca exit koduna bakan test yarım rapora da
yeşil verirdi). Mutasyonla doğrulandı.

---

### REJİM ÖLÇÜMÜ — "sınıflandırıcı bozuk mu?" sorusu CEVAPLANDI

Üretim logunda rejim dağılımı **%93.6 TREND_UP**, RANGE ve BEAR
**hiç yok**. §0.9'un ilk gözlemi (27 örnek) bunu zaten göstermişti.
İki açıklama mümkündü: (a) boğa piyasası, (b) sınıflandırıcı dejenere.

**Ölçüm — 3 yıl, 4h, 5 sembol, 31.855 gözlem (havuzlanmış):**

| rejim | 3 yıl | son 30 gün | **botun gördüğü 45 bar** |
|---|---|---|---|
| TREND_UP | %25.5 | %33.0 | **%100** |
| BEAR | %23.6 | %8.1 | 0 |
| RANGE | %20.8 | %23.9 | 0 |
| TREND_DOWN | %18.5 | %23.6 | 0 |
| VOLATILE | %11.7 | %11.4 | 0 |

➜ **Sınıflandırıcı sağlam.** 3 yılda dengeli dağılıyor. Çevrimdışı
sınıflandırıcı, botun gördüğü 45 barın **45'ine de TREND_UP** diyor —
yani üretimle birebir uyuşuyor. %93.6 gerçek bir piyasa durumu.

⚠️ **AMA ÖRNEKLEM SORUNU GERÇEK.** Toplanan 4 işlemin 4'ü de LONG ve
pencere %100 TREND_UP. Tarihsel olarak barların **%42.1'i düşüş
rejimi** (BEAR %23.6 + TREND_DOWN %18.5) — örneklemde **%0**.

5 sembol 5 bağımsız çekiliş DEĞİL: 171 red "aynı yönde 2/2 pozisyon"
diyor, yani coinler birlikte hareket ediyor. Pencere ne kadar uzarsa
uzasın, hepsi aynı rejimi görüyor.

➜ **AÇIK KARAR (kod değil protokol):** 100 işlem bu tempoda ~41 günde
dolar, ama tamamı tek rejimden gelirse `karar_kurali.py`'nin hükmü
"bu strateji boğa piyasasında kârlı mı" sorusunu cevaplar — "kârlı mı"
sorusunu değil. §0.8'in "bu örneklemle long-only sistem kurulmamalı"
uyarısının somut hâli. **Eşiklere dokunulmadı** (§0 kuralı); karar
kullanıcıya bırakıldı.

---

### K-36 — HMM YÖNSÜZ ETİKETTEN YÖN UYDURUYORDU

Rejim ölçümü sırasında bulundu. `core/market_regime.py`:

```python
if hmm_rejim == "TRENDING" and kural_rejim == "RANGE":
    return "TREND_UP"       # yön UYDURMASI
```

`_DURUM_ETIKETLERI = {0: CALM, 1: TRENDING, 2: STRESSED}` — etiketler
volatilite/hacimden türer. **"TRENDING" bir trend OLDUĞUNU söyler,
YÖNÜNÜ söylemez**; düşen bir trend de aynı durumu üretir.

Canlanırsa her RANGE barı sessizce TREND_UP olur:
- `ai_score_hesapla`: RANGE cezası (−1) kalkar → **alış yönünde**
- `sl_tp_hesapla`: RANGE yerine TREND çarpanları → **alış yönünde**

**Ölçüm (3 yıl, 1500 örnek):** HMM etiketleri CALM %78.1 ·
STRESSED %21.8 · **TRENDING %0.1**. Yani dal bugün pratikte ÖLÜ;
birleştirmenin asıl işi STRESSED → VOLATILE (%18.5, 277 kez).

⚠️ **GEREKÇE PERFORMANS DEĞİL DOĞRULUK** (K-26'nın aynısı). Kazanç
iddiası YOK. Yönsüz sinyalden yön üretmek yapısal hatadır ve HMM
yeniden eğitilince canlanır.

**Ayrıca §5.2 ihlali düzeltildi:** birleştirmeyi saran
`except Exception → log.debug` yerel hesaplamayı sarıyordu. Her turda
çökse iz kalmazdı; rejim sessizce kural-bazlıya düşer ve "HMM
doğruluyor" sanılırdı. Artık `log.warning`.

Muhafız: `tests/test_rejim_birlestirme.py` (7 test), üç yönde
mutasyonla doğrulandı (yön uydurmayı geri getir / birleştirmeyi
tamamen kapat / olasılık eşiğini kaldır).

---

### ⚠️ BU OTURUMDA YAPILAN İKİ ÖLÇÜM HATASI (ders niteliğinde)

1. **Log regex'ine `BEAR` yazmayı unuttum.** İlk rejim sayımı sessizce
   BEAR gözlemlerini düşürüyordu. "%95.6 TREND_UP" rakamı bu yüzden
   yanlıştı (doğrusu %93.6). Küçük fark, ama **eksik alternasyon sessiz
   veri kaybıdır** — §5.2'nin ölçüm betiklerindeki karşılığı.
2. **"Sınıflandırıcı dejenere" hipotezine erken inandım.** RANGE=0
   görünce kodda bir hata aradım ve K-36'yı buldum — ama K-36 bunun
   SEBEBİ DEĞİL (%0.1 tetikleniyor). Gerçek sebep piyasanın kendisiydi.
   §4.3'ün ("hata iddia etmeden önce kodu oku") ölçüm hâli:
   **hata iddia etmeden önce ÖLÇ.** K-36 gerçek bir kusur çıktı, ama
   aradığım kusur değildi.

---

## 0.14 K-37/K-38 — ÖLÇÜM KATMANI DÜZELTİLDİ, 7. RET (2026-09-05 gece)

**Soru:** "programı çok iyi ve gelişmiş yap." Bariz yol — daha çok
feature/model — altı kez denenip reddedilmişti. Bunun yerine §0.8'deki
bir çelişkiden gidildi:

> model accuracy − taban: 5m −0.0297 (p=0.001) · 1h −0.0333 (p=0.000)
> 4h −0.0205 (p=0.015) · 1d −0.0542 (p=0.000)

Dört bağımsız ufukta **tutarlı ve anlamlı NEGATİF**. Gerçek "beceri yok"
sıfır etrafında saçılırdı; tutarlı negatiflik gürültü değil **hata
imzasıdır**. §10: "kör nokta kodun içinde değil, ölçüldüğü yerde."

Kod okununca üç ayrı kusur çıktı — hepsi de MODELİN İYİLİĞİNİ değil
**HANGİ MODELİN SEÇİLDİĞİNİ** bozuyordu.

---

### K-37 — SEÇİM KATMANINDA ÜÇ KUSUR

**1. f1 için ayarlanıp accuracy ile yargılanıyordu.**
```python
return f1_score(y_te, m.predict(X_te), average="weighted")  # AYAR
test_acc = accuracy_score(y_te, cal_model.predict(X_te))    # YARGI
```
Dengesiz sınıfta ağırlıklı f1 için ayarlanan model çoğunluk sınıfından
uzaklaşır → accuracy taban çizgisinin altına **tasarım gereği** düşer.
§0.8'in negatif beceri bulgusu en azından kısmen bundan.

**2. Sabit eşik yanlış büyüklüğü ölçüyordu.**
`MIN_USEFUL_ACC = 0.52` sabit; taban çizgisi ise oynuyor.
Ölçüm (4h, 3 yıl, 5 sembol, 40 katman):

| | değer |
|---|---|
| taban çizgisi ortalaması | **0.5151** |
| aralık | 0.5007 – 0.5351 |
| taban > 0.52 olan katman | **10/40 (%25)** |

Katmanların dörtte birinde 0.52 accuracy **sabit tahminciden kötüdür**
ve yine de "faydalı" sayılıyordu. Üretim logu: 4h geçişinden beri
**4037 kez** `[SKIP] acc<0.52 → yeniden eğit` — sistem eşiği geçen bir
model çıkana kadar yeniden eğitiyordu, yani **gürültünün üst kuyruğunu
arıyordu**.

**3. Seçim ham accuracy'ye bakıyordu.** K-20 seçimi WF'ye bağlamıştı ama
WF'nin HAM ortalamasına. Taban 0.5351 olan katmanda 0.54 accuracy
neredeyse hiçbir şey; taban 0.5007 olan katmanda aynı sayı gerçek
beceri. Ham accuracy ile seçmek **beceriyi değil sınıf dengesizliğini**
ödüllendirir.

Üretim kanıtı (4h geçişinden beri, 2802 seçim kaydı):

| | |
|---|---|
| Seçilenlerin test_acc ort. | 0.5441 |
| Seçilenlerin WF ort. | 0.5366 |
| **WF < 0.52 olan SEÇİLMİŞ model** | **913/2802 (%33)** |
| Tüm adaylar: test_acc − WF | **+0.0165** |

### Yapılan

- `walk_forward_cv` artık katman başına **beceri = accuracy − çoğunluk
  sınıfı tabanı** hesaplıyor (`beceri_ort`, `beceri_std`, `taban_ort`).
  Ham alanlar raporlama için KORUNDU (registry + eski testler).
- Nihai seçim `_wf_beceri` ile. Eski format WF dosyası varsa ham
  ortalamaya düşülüyor ama **sesli** (§5.2).
- **`guven_notrle()` — asıl değişiklik.** En iyi adayın becerisi kendi
  standart hatasından büyük değilse `yukselis_guveni = 50.0`.
  ai_score'da 40–60 bandı puan eklemez/çıkarmaz → model kararı
  ETKİLEMEZ. Diğer bileşenler (MACD, MA, MTF, osilatörler) çalışmaya
  devam eder; sinyal susturulmuyor, modelin sahte katkısı kalkıyor.
  Hata hâlinde **fail-closed** (nötr).

⚠️ **Eşik uydurma bir sabit DEĞİL:** "tahmin kendi standart hatasından
büyük mü" istatistiksel ifadesi. §0'ın "veri görülmeden konan eşikler
oynatılmaz" kuralına yeni bir ayar noktası eklemiyoruz.

Bu, §5.1'deki fail-open deseninin **aynası**:

| | |
|---|---|
| §5.1'de | "bilmiyorum" → "sorun yok" |
| Burada | "ölçülebilir beceri yok" → "işte güvenilir olasılık" |

### Canlı doğrulama (bot 21:27'de yeni kodla başladı)

```
[MODEL/BTCUSDT] beceri anlamlı değil (+0.0000 ≤ 0.0000) → güven 48.5 → 50.0
[MODEL/SOLUSDT] ...                                     → güven 46.2 → 50.0
[MODEL/BNBUSDT] ...                                     → güven 42.0 → 50.0
```
7 model "anlamlı=HAYIR", 5 güven nötrlendi. BNBUSDT'de güven 42.0 idi →
ai_score'a **−1** olarak giriyordu; model gürültüye dayanarak SELL
yönünde baskı yapıyormuş.

### 🎯 SIFIRLAMA SONRASI CANLI KANIT (21:38, yeni format modeller)

Sıfırlama eski modelleri sildi; bot yeniden eğitince **gerçek beceri
değerleri** göründü — ve teşhisi birebir doğruladılar:

```
[MODEL/BTCUSDT] seçildi: gb_BTCUSDT  test_acc=0.545  beceri=-0.0395±0.0604  anlamlı=HAYIR
[MODEL/XRPUSDT] seçildi: lgb_XRPUSDT test_acc=0.536  beceri=-0.0491±0.0573  anlamlı=HAYIR
[MODEL/ETHUSDT] seçildi: gb_ETHUSDT  test_acc=0.597  beceri=-0.0257±0.0798  anlamlı=HAYIR
[MODEL/SOLUSDT] seçildi: gb_SOLUSDT  test_acc=0.526  beceri=-0.0385±0.0704  anlamlı=HAYIR
```

**ETHUSDT en çarpıcı vaka:** `test_acc=0.597` mükemmel görünüyor ve eski
kapıyı (0.52) rahatça geçiyordu — ama gerçek becerisi **−0.0257**, yani
sabit tahminciden 2.6 puan KÖTÜ. Eski kodda bu model seçilir, güveni
`ai_score`'a girer ve bot ona göre işlem açardı.

| 17 seçim kaydı | değer |
|---|---|
| beceri ortalaması | **−0.0158** |
| std ortalaması | 0.1018 |
| **beceri > std olan (anlamlı)** | **0 / 17** |
| nötrlenen güven | 32 |
| ERROR | 0 |

➜ Ham accuracy modelleri **sistematik olarak abartıyordu**; hiçbiri taban
çizgisini geçmiyor. Bu, §0.8'in "her ufukta negatif beceri" bulgusunu
bağımsız olarak doğruluyor — ve neden hiçbir hipotezin tutmadığını
açıklıyor: seçim katmanı en iyi modeli değil, en dengesiz sınıfı olanı
seçiyordu.

Muhafız: `tests/test_model_beceri.py` (15 test), dört yönde mutasyonla
doğrulandı.

### 🔴 MUTASYON TESTİ KENDİ TESTLERİMDE İKİ KUSUR BULDU

Bunlar kayda geçiyor çünkü §4.1'in neden var olduğunu gösteriyorlar:

1. **Nötrlemeyi kaldıran mutasyon YAKALANMADI** (testler 12/12 yeşil
   kaldı). Testim kaynakta string arıyordu, TÜKETİCİNİN onu kullandığını
   doğrulamıyordu — K-29'daki tuzağın birebir tekrarı. Mantık
   `guven_notrle()`'ye çıkarıldı; artık davranışsal test + AST ile
   `yukselis_guveni = guven_notrle(...)` ATAMASI aranıyor.
2. **Fail-open mutasyonu YAKALANMADI.** İstisna testim `_PatlayanMeta()`
   boş bir `dict` alt sınıfıydı; kod `(meta or {}).get(...)` yazdığı için
   boş sözlük FALSY olup düz `{}` ile değişiyordu ve benim `get`'im hiç
   çağrılmıyordu. Test istisna yolunu tetiklediğini **sanıyordu**.

➜ **Yeni kural: mutasyonun UYGULANDIĞINI da doğrula.** Bir kez hedef
string tutmadı, mutasyon hiç uygulanmadı ve test boşuna yeşil kaldı.
Artık `assert s.count(hedef)==1` ile kontrol ediliyor.

---

### 7. RET — ÇALIŞMA EŞİĞİNDE DE EDGE YOK

Asıl soru şuydu: bot her barda değil, model güveni yüksek olan barlarda
işlem açıyor. Doğru metrik genel accuracy değil, **o eşikteki
precision**. Yargıç ekonomik (üçlü bariyer: TP'ye mi SL'e mi önce değer).

**3 yıl, 4h, 5 sembol, 27.000 örneklem-dışı bar, walk-forward + embargo:**

| güven eşiği | n | P(TP) | − taban | p |
|---|---|---|---|---|
| ≥ 0.50 | 14713 | 0.4802 | −0.0001 | 0.311 |
| ≥ 0.55 | 7145 | 0.4833 | +0.0030 | 0.151 |
| ≥ 0.60 | 2414 | 0.5012 | +0.0210 | 0.228 |
| **≥ 0.62 (üretim kapısı)** | **1425** | **0.4912** | **+0.0110** | **0.800** |
| ≥ 0.65 | 572 | 0.5262 | +0.0460 | 0.773 |
| ≥ 0.70 | 121 | 0.5537 | +0.0735 | 0.797 |

Taban oran 0.4803. **Hiçbir eşikte anlamlılık yok** (p 0.15–0.80).

Daha da açık olan: üst yüzdelik dilimler **monotonik değil** —
en iyi %30: +0.0021 · en iyi %20: **−0.0017** · en iyi %10: +0.0153 ·
en iyi %5: +0.0042. Gerçek sıralama gücü olsaydı güven arttıkça P(TP)
düzenli artardı. Artmıyor: gürültü imzası.

⚠️ **SÜRÜKLENME TUZAĞI YİNE ÇIKTI** (§0.8, §0.11 ile aynı): taban oran
0.4803, maliyetli başabaş ≈0.446. Yani bu örneklemde **rastgele LONG
girmek bile "kârlı"** görünüyor — üçlü bariyer yargıcı long yönlü ve
örneklem +%207 boğa piyasası. Mutlak beklenti rakamları anlamsız;
yalnızca `P(TP) − taban` farkı okunmalı.

⚠️ **Ölçüm betiğinin raporlama kusuru:** tabloda P(TP) TAM alt kümeden,
p değeri ise SEYRELTİLMİŞ (örtüşmeyen) alt örneklemden hesaplanıyor.
İkisi farklı örneklem, dolayısıyla büyük fark + büyük p birlikte
görülebiliyor. Sonucu değiştirmiyor (hiçbiri anlamlı değil) ama
tekrar kullanılırsa düzeltilmeli.

➜ **Bu ölçüm K-37'yi DOĞRULUYOR:** üretim kapısında model hiçbir şey
eklemiyor (p=0.800), dolayısıyla güveninin ai_score'u oynatması saf
gürültü katkısıydı. Nötrleme onu kaldırıyor.

---

### K-38 — ORDER BOOK KAYDI BAŞLADI

§0.6'da ölçülmüştü: Binance **geçmiş order book snapshot'ı sunmuyor**.
Bir feature ancak geçmişi varsa eğitilebilir. Order book, denenmemiş
tek gerçek yeni bilgi kaynağı — mevcut 34 feature'ın TAMAMI fiyat/hacim
türevi.

**Beklemenin kendisi maliyet olan tek iş bu.** Bugün başlatılmazsa üç
hafta sonra da veri olmaz.

`orderbook_kaydedici.py` + `baslat_orderbook.bat`:
- 60 sn'de bir, 5 sembol × 20 seviye, gzip'li JSONL (`data/orderbook/`)
- **Ham seviyeler DE** saklanıyor — bugün hangi türetmenin işe
  yarayacağını bilmiyoruz, snapshot geri alınamaz
- Durağan türetmeler (K-26 dersi): `imbalance`, `spread_pct`, mid'in
  %0.1 / %0.5 içindeki likidite. Ham fiyat seviyesi YOK.
- Bota DOKUNMAZ: ayrı süreç, ayrı dosya, salt-okunur halka açık API,
  çift-çalıştırma korumalı, `ORDERBOOK_DIR` ile yönlendirilebilir (§4.6)

⚠️ **YAPILMADI: zamanlanmış görev kaydı yönetici izni istedi.**
Kaydedici şu an elle başlatıldı ama **makine yeniden başlarsa ölür.**
Yönetici PowerShell'de:
```powershell
$kok="C:\Users\<KULLANICI>\Desktop\astra_v55"; $act=New-ScheduledTaskAction -Execute "$kok\baslat_orderbook.bat" -WorkingDirectory $kok; $t1=New-ScheduledTaskTrigger -AtLogOn; $t2=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 10); $set=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable; Register-ScheduledTask -TaskName "ASTRA_OrderBook" -Action $act -Trigger $t1,$t2 -Settings $set -Force
```
Doğrulama: `(Get-ScheduledTaskInfo -TaskName ASTRA_OrderBook).NextRunTime` **dolu** olmalı.

---

### ⏳ 7. SIFIRLAMA — BEKLİYOR

K-37 davranış değişikliğidir (model katkısı ±2 puandı, giriş eşiği
|ai| ≥ 4), §5.3 gereği sayaç sıfırlanmalı. `sifirla_k37.py` yazıldı ve
gözden geçirilmeye hazır; **henüz çalıştırılmadı.**

```powershell
Stop-ScheduledTask -TaskName ASTRA_Bot
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*main.py bot*' } | Stop-Process -Force
python sifirla_k37.py
.\baslat_bot.bat
```

Betik: yedek alır (data + saved_models), PAPER işlemleri siler,
K-37 öncesi format model/WF dosyalarını siler (feedback'e DOKUNMAZ —
o gerçek kapanışlardan gelen eğitim verisi), `4h_baslangic.json`'u
tazeler, bot çalışıyorsa REDDEDER.

⚠️ Sıfırlamaya kadar biriken işlemler de silinecek — kayıp yok, sadece
o süre boşa gider.

---

### 🟡 K-39 (AÇIK) — MODEL SÜRÜMLERİ SINIRSIZ BÜYÜYOR

7. sıfırlamanın yedeği **22 GB** çıkınca bulundu.

`saved_models/versions/` — model kayıt defteri her yeniden eğitimde bir
sürüm arşivliyor ve **hiçbir saklama politikası yok**:

| | |
|---|---|
| Dosya | **6431** (`rf_BNBUSDT_v1662.pkl` — 1662. sürüm) |
| Boyut | **22.7 GB** |
| Büyüme | 378 dosya/gün · **1.33 GB/gün** · aylık ~40 GB |
| Başlangıç | 2026-08-13 (17 gün) |

Diskte 321 GB boş → ~8 ayda dolar. Acil değil ama sınırsız.

⚠️ **SÜRÜMLER KULLANILIYOR, hepsini silme.** `rollback_yap()` performans
düşünce eski sürümü geri yüklüyor (`main.py:477`). Doğru çözüm saklama
politikası: (sembol, model_tipi) başına son N sürüm + `aktif=1` olan +
`en_iyi_versiyon()`'un işaret ettiği korunur, gerisi silinir. N=20 bile
diski ~%98 küçültür.

**YAPILMADI** — registry davranış değişikliği, ayrı ele alınmalı
(§4.5: refactor ve bugfix aynı adımda yapılmaz).

**Yan ders:** `sifirla_k37.py`'nin ilk sürümü `versions/`'ı da
yedekliyordu — dokunmadığı bir dizini. 22 GB'lık kopya silindi, betiğe
`ignore_patterns(..., "versions")` eklendi. **Yedeklemeden önce "bu
betik bu dizine dokunuyor mu?" diye sor.**

### 🔴 YENİ CANLI GEÇİŞ RİSKİ: `-1021` SAAT KAYMASI

Bulundu: `logs/astra.log` içinde **127 kez**, 09-04'ten beri **35 farklı
saatte** (benim ağır işlerimden bağımsız — onlardan önce de var).
Offset yenileniyor ama 3 denemede başarısız oluyor:

```
[FUTURES] /fapi/v3/positionRisk — 3 denemede başarısız. [-1021] Timestamp
          for this request is outside of the recvWindow.
```

Paper modda zararsız (K-33'ten sonra futures bakiyesi kullanılmıyor).
**Canlıda ciddi:** pozisyon sorgusu başarısız olursa koruma döngüsü
durumu doğrulayamaz. §5.1'in `strict=True` deseni istisna yükseltiyor,
yani sessiz değil — ama sıklığı bu hâlde canlıya geçilmemeli.
**§3'e engel olarak eklenmeli.**

---

## 0.15 ENVANTER — SİSTEMDE NE VAR, NE YOK (2026-09-05)

Altı ay sonra "acaba şunu denemiş miydik" sorusuna tek bakışta cevap
versin diye çıkarıldı.

### Telegram — güçlü (36 komut)

```
abtest ai_rapor analytics audit bakiye btc circuit coin correlation edge
engine fkapat fpoz gecikme market mc multiex neden onchain paper registry
risk saglik scan selflearn senaryo shadow shadow_approve sim smartexec
state sync tft validate watchdog yardim
```

### Panel — ince (3 endpoint)

`api/dashboard.py`: `/` · `/api/state` · `/saglik`. Telegram tarafına
göre çok sınırlı. K-32/33'ten sonra Telegram ile UYUŞUYOR.

### Veri tutarlılığı — sağlam

`execution/`: `duplicate_guard` · `fill_reconciler` · `state_audit` ·
`failsafe_liquidation` · `order_ack` · `smart_execution`
`core/`: `preflight` · `http_guard`
`tests/izolasyon.py`: üretim verisi korumalı (K-1/K-6/K-21/K-34)

### Ölçüm terimleri — zengin

`win_rate`(66) · `sharpe`(50) · `VaR`(27) · `max_drawdown`(21) ·
`embargo`(21) · `accuracy`(16) · `beceri_ort`(15) · `kelly`(13) ·
`overfitting_skoru`(9) · `f1`(7) · `expectancy`(7) · `bootstrap`(7) ·
`sortino`(5) · `profit_factor`(5) · `calmar`(5) · `CVaR`(5)

Metodoloji: walk-forward · embargo/purging · binom testi ·
blok bootstrap · örtüşmeyen alt örneklem · eşli katman testi.

---

### 🔴 FEATURE SETİ: 34 TANE, HEPSİ FİYAT/HACİM TÜREVİ

```
Price_EMA50 · Price_EMA200 · EMA9_21_cross · SuperTrend_Dir
RSI · Stoch_RSI · Williams_R · CCI
MACD · MACD_Hist · MACD_Cross
Momentum_5 · Momentum_20 · ATR_pct · Volatility_10 · BB_Width
OBV_Diff · Taker_Ratio · Volume_Ratio
ADX · Plus_DI · Minus_DI · DI_Diff · Candle_Strength
Bullish_Engulfing · Bearish_Engulfing · Doji · Hammer · Shooting_Star
Morning_Star · Three_White_Soldiers
CVD_Norm · CVD_Momentum · CVD_Divergence
```

**Otuz dördünün tamamı aynı iki seriden türüyor: fiyat ve hacim.**
Gösterge eklemek bilgi eklemez, aynı bilgiyi yeniden şekillendirir.

### Bot TOPLUYOR ama modele GİRMİYOR

| veri | toplanıyor | modele giriyor | not |
|---|---|---|---|
| Fear & Greed | ✅ | ❌ | yalnızca `edge_engine` |
| On-chain / whale | ✅ proxy | ❌ | yalnızca `/onchain` raporu |
| Open interest | ✅ | ❌ | §0.6'da test → **reddedildi** |
| Long/short oranı | ✅ | ❌ | §0.6'da test → **reddedildi** |
| Likidasyon haritası | ✅ | ❌ | yalnızca SL/TP yerleşimi (`magnet_seviye`) |
| Funding rate | ✅ | kısmen | `ai_score`'a ±1/±2, feature değil |
| Order book derinliği | ✅ anlık | ❌ | geçmiş yoktu; **K-38 ile kayıt başladı** |

### Şirketlerin kullandığı, botta HİÇ OLMAYAN veriler

- **Opsiyon verisi** — implied vol yüzeyi, skew, gamma exposure (Deribit)
- **Gerçek tick / emir akışı** — saldırgan taraf tick bazında
  (botta yalnızca kline'dan türetilmiş yaklaşım: Taker_Ratio, CVD)
- **L2/L3 order book geçmişi** — K-38'den itibaren birikiyor
- **Borsalar arası** — arbitraj spreadleri, lead-lag
- **Perp basis / vade yapısı** çoklu borsada
- **Makro** — DXY, faiz, hisse korelasyonu
- **Haber / NLP / ölçekli sosyal duygu**
- **Stablecoin akışları, ölçekli borsa netflow'u** (yalnızca proxy)

### ⚠️ AMA VERİ EKLEMEK ÇÖZÜM DEĞİL — BU DA ÖLÇÜLDÜ

§0.6'da tam olarak bu denendi: OI + long/short + taker + funding feature
olarak eklendi → **eşli fark −0.0023, p=0.665** (daha kötü). Model
onları yoğun kullandı (önem sıralamasında 3./6./7.) ama örneklem-dışı
doğruluk düştü. **Feature önemi ≠ tahmin gücü.**

Profesyonel firmaları ayıran şey esas olarak veri değil:

| | firma | bu bot |
|---|---|---|
| Komisyon | maker iadesi, VIP kademe | perakende taker ~%0.11 gidiş-dönüş |
| Evren | yüzlerce varlık | **5 coin** |
| Gecikme | colocation, mikrosaniye | ev interneti |

§0.8: 5m'de kazanmak için taban oranı **20.6 puan** geçmek gerekiyordu.
O açığı hiçbir feature kapatmaz.

### "Botun ürettiği başarılı analizler" — TUZAK

Bot logda "Top features" ve `test_acc=0.597` gibi rakamlar basıyor.
Bunlar başarı kanıtı DEĞİL:
- §0.6: `feature_importances_` yalnızca modelin o feature'ı KULLANDIĞINI
  söyler, değerli olduğunu değil.
- §0.14: ETHUSDT `test_acc=0.597` — gerçek becerisi **−0.0257**, yani
  sabit tahminciden kötü.


---

### 🔬 KLASİK KURALLARIN DOĞRUDAN ÖLÇÜMÜ (9. RET)

**Soru:** "Day trader'lar RSI, MACD, MA'ya bakıyor. Bot neden tahmin
edemiyor?" — Model katmanı TAMAMEN devre dışı bırakılıp ders kitabı
kurallarının kendisi ölçüldü. 3 yıl, 4h, 5 sembol, üçlü bariyer yargıcı.

Taban oran: LONG 0.4857 · SHORT 0.4656 (her barda girseydin).
Her kural KENDİ yönünün tabanıyla kıyaslandı (sürüklenme tuzağı, §0.8).

| kural | yön | n | P(TP) | −taban | p |
|---|---|---|---|---|---|
| MACD aşağı kesişim | SHORT | 1283 | 0.4832 | +0.0176 | 0.121 |
| SuperTrend aşağı | SHORT | 13373 | 0.4730 | +0.0074 | 0.141 |
| Williams %R < −80 | LONG | 4932 | 0.4909 | +0.0052 | 0.803 |
| CCI < −100 | LONG | 5990 | 0.4902 | +0.0045 | 0.741 |
| SuperTrend yukarı | LONG | 19412 | 0.4888 | +0.0031 | 0.303 |
| RSI > 70 | SHORT | 4890 | 0.4685 | +0.0029 | 0.253 |
| MACD > sinyal | LONG | 16607 | 0.4843 | −0.0014 | 0.621 |
| Golden cross | LONG | 17351 | 0.4841 | −0.0016 | 0.942 |
| Death cross | SHORT | 15434 | 0.4635 | −0.0022 | 0.551 |
| Fiyat > MA20 | LONG | 16922 | 0.4810 | −0.0047 | 0.852 |
| Stoch RSI < 20 | LONG | 9955 | 0.4785 | −0.0072 | 0.921 |
| **RSI < 30 (aşırı satım)** | LONG | 3780 | 0.4738 | **−0.0119** | 0.946 |
| **MACD yukarı kesişim** | LONG | 1281 | 0.4606 | **−0.0251** | 0.946 |
| **Bollinger alt bant** | LONG | 1823 | 0.4591 | **−0.0265** | 0.944 |
| **Bollinger üst bant** | SHORT | 2155 | 0.4357 | **−0.0299** | 0.939 |

*(21 kuralın tamamı; yer için 15'i gösterildi)*

```
21 kural · ortalama fark −0.0038 · pozitif olan 8/21
p < 0.05 olan kural: 0/21
```

➜ **HİÇBİR KLASİK KURAL TABAN ORANI ANLAMLI ÖLÇÜDE GEÇMİYOR.**
Örneklem büyük (n = 1281–19412), yani bu bir güç sorunu değil.

⚠️ **En ünlü kurallar en kötüler arasında:** RSI<30 (−0.0119),
MACD yukarı kesişim (−0.0251), Bollinger bant teması (−0.0265/−0.0299).
Klasik ortalamaya-dönüş sinyalleri sistematik olarak taban çizgisinin
ALTINDA.

**Bu ölçümün önemi:** "model kötü" açıklamasını ortadan kaldırıyor.
Model yok, makine öğrenmesi yok, sadece göstergelerin kendisi.
Göstergeler geçmişi doğru tarif ediyor ama **geleceği tarif etmiyor.**

**Neden:** RSI/MACD/MA'nın hepsi geçmiş fiyatın deterministik
fonksiyonudur — yeni bilgi eklemezler, aynı bilgiyi yeniden şekillendirirler.
Geçmiş fiyat geleceği öngörmüyorsa, onun hiçbir dönüşümü de öngörmez.
Üstelik bu kurallar herkese açık ve basit; arbitraj edilecek ilk şey onlar.

### Özet tablo

| alan | durum |
|---|---|
| Telegram | ✅ güçlü |
| Panel | 🟡 ince |
| Veri tutarlılığı | ✅ sağlam |
| Ölçüm metodolojisi | ✅ güçlü |
| **Tahmin gücü** | ❌ **ölçüldü, yok** |
| **Profesyonel veri kaynakları** | ❌ **yok** — ama eklemek de işe yaramadı |

➜ Mühendislik iyi, ölçüm iyi, **girdi perakende seviyesinde ve o
girdilerden çıkarılabilecek bilgi tüketilmiş.**

---

## 0.16 K-40/K-41/K-42 — KULLANICI BİLDİRİMLİ ÜÇ HATA (2026-09-05 gece)

Üçü de **kullanıcı fark etti**, log hiçbirini söylemiyordu. §0.12'deki
dersin tekrarı: *"kod çalışırken hiçbir belirti vermeyen hatalar, ancak
insan iki ekranı karşılaştırınca ortaya çıkıyor."*

---

### 🔴 K-40 — TELEGRAM GRAFİKLERİ SESSİZCE KESİLMİŞTİ

**Bildirim:** "Bayadır resim atmıyor."

Grafik gönderimi `abs(ai_score) >= 7` koşuluna bağlıydı (grafik ÜRETİMİ
ayrıca sabit `>= 5`). Sorun: skorun ulaşabildiği aralık ufka ve model
katkısına bağlı, sabit bir sayı değil.

| dönem | \|AI\| ≥ 7 oranı | en yüksek \|AI\| |
|---|---|---|
| 5m dönemi (23.659 sinyal) | %6.10 | 11 |
| 4h dönemi (3.332 sinyal) | %2.64 | 8 |
| **K-37 sonrası** | — | **4** |

K-37 model güvenini nötrlediği için `ai_score`'un ±2'lik bileşeni gitti
ve eşik **ULAŞILAMAZ** hale geldi — bir daha asla grafik gönderilmezdi.
Hiçbir hata, hiçbir uyarı.

**Düzeltme:** `_RAPOR_ESIGI = max(|MIN_AI_SCORE_BUY|, |MIN_AI_SCORE_SELL|)`.
Rapor ve grafik üretimi artık GİRİŞ eşiğiyle aynı kaynaktan: bot işlem
açacak kadar güçlü bulduysa raporluyor. Ufuk/model değişse de kendini korur.

➜ **K-29/K-30'un ÜÇÜNCÜ tekrarı:** zaman dilimine *veya skor ölçeğine*
bağlı her sabit, ölçek değişince sessizce yanlış olur.

**Gönderim altyapısı ayrıca doğrulandı** — `telegram_grafik_gonder`
elle çağrıldı, grafik ulaştı. Sorun yalnızca tetikleyicideydi.

---

### 🔴 K-41 — PANELDE `�` (WEAK BUY rozetinde)

**Bildirim:** "Panelde � işareti var Weakbuy'da, logoları görünsün."

`api/dashboard.py`:
```js
const cleanKarar = s => (s||'').replace(/[🚀✅📈💀🔴📉⏳⚠️]/g,'').trim();
```

İki hata birden:
1. **Listede `📊` YOK** — WEAK BUY/SELL kararları onu kullanıyor.
2. **`u` bayrağı olmadan astral emoji karakter sınıfı BOZUKTUR.**
   Bu emoji'ler vekil çiftiyle temsil edilir; `u` yokken sınıf çiftleri
   ayrıştıramaz ve tek tek vekil kodlarına dağılır. `📊` ile `🚀` AYNI
   yüksek vekili paylaşır → `📊`'nın yüksek vekili siliniyor, geriye
   YALNIZ KALAN düşük vekil kalıyor. Yalnız vekil ekranda `�`.

Simülasyonla birebir üretildi:
```
ESKİ: '📊 WEAK BUY' → '� WEAK BUY'      (diğerleri temiz siliniyordu)
YENİ: '📊 WEAK BUY' → '📊 WEAK BUY'
```
Bu yüzden sorun **yalnızca WEAK BUY/SELL'de** görünüyordu.

**Düzeltme:** emoji artık silinmiyor (kullanıcı görünmesini istedi),
sadece boşluk normalize ediliyor. Emoji silmek gerekirse doğru yol
`/\p{Extended_Pictographic}/gu`.

⚠️ **Uygulama sırasında hata yapıldı:** heredoc bir kaçış seviyesi yiyip
`\uD83D` dizisini GERÇEK vekil karaktere çevirdi; Python dosyayı
truncate edip yazarken çöktü ve `dashboard.py` 0 bayta düştü. Önceden
yedek alınmıştı, geri yüklendi ve Edit ile temiz uygulandı.
**Ders: çok satırlı kaçış içeren metni heredoc ile yazma.**

---

### 🔴 K-42 — KOMİSYON HİÇ SAKLANMIYORDU

Kullanıcı "para optimizasyonu" isteyince ortaya çıktı.

`trades` tablosunda **`komisyon` kolonu YOKTU**. Komisyon kapanışta
hesaplanıp PnL'den düşülüyor, sonra kayboluyordu. Yani *"ne kadar
komisyon ödedim"* sorusunun geriye dönük cevabı yoktu — maliyet
optimizasyonunun ilk gereği tam olarak bu bilgi.

**Yapılanlar:**
- `trades.komisyon` kolonu + idempotent `ALTER TABLE` migrasyonu
- Eski kayıtlar `NULL` kalıyor (**0 değil** — 0 yazmak "komisyon
  ödenmedi" diye okunur ve eksik toplamı gizlerdi)
- `trade_kapat(..., komisyon=...)` yazıyor
- `PaperTrader.para_dokumu()` — nakit / bağlı sermaye / toplam varlık /
  brüt PnL / ödenen komisyon / net PnL / komisyonun brütteki payı
- `_para_blogu()` Telegram raporuna, `para_dokumu` panel state'ine bağlı
- Eksik komisyonlu (K-42 öncesi) kayıt varsa rapor **UYARIYOR** (§5.2)

**`brut_pnl = gerceklesen_pnl + odenen_komisyon` özdeşliği teste
bağlandı** — muhasebe kaçağı dedektörü. v56'da tam bu sınıftan hata
olmuştu (bakiye net, DB brüt tutuyordu, ikisi yavaşça ayrışıyordu).

Muhafız: `tests/test_para_dokumu.py` (9 test), dört yönde mutasyonla
doğrulandı (komisyonu yazma / hep 0 yaz / eksik uyarısını kaldır /
bağlı sermayeyi 0 say).

---

### 💰 MALİYET TABLOSU (ölçüldü, henüz optimize EDİLMEDİ)

| kalem | mevcut model | Binance VIP0 gerçeği |
|---|---|---|
| Komisyon/taraf | %0.04 (`PAPER_KOMISYON`) | taker %0.05 · **maker %0.02** |
| Slippage/taraf | %0.03 (3 bps) | ölçülen %0.006 (§5.4) |
| **Gidiş-dönüş** | ~%0.14 modelleniyor | taker ~%0.11 · **maker ~%0.04** |

Maker'a geçiş kazancı: işlem başına **~%0.06–0.07**.
Bağlam: 4h'de TP ≈ %3.58, maliyet hedefin %3.1'i (§0.8) → %1.5'e iner.
**Gerçek ama küçük.** (5m'de maliyet hedefin %37'siydi; orada hayati
olurdu ama 5m başka sebeple imkânsız.)

⚠️ **Maker'a geçiş DAVRANIŞ DEĞİŞİKLİĞİDİR:**
- `MARKET` → `LIMIT` + post-only (`GTX`), doğrulanmış emir yolu değişir
- Paper'da "limit dolar mıydı" modellenmeli (§5.3 eşitliği)
- Dolmayan emir = kaçan sinyal
- **8. sıfırlama gerektirir**

**KARAR: ertelendi.** Önce birkaç işlem birikip para dökümünün gerçek
rakamlarla çalıştığı görülecek. Ölçüm zemini olmadan emir yolunu
değiştirmek, sonucu doğrulayamamak demek.

### Kullanıcının seçtiği diğer "para optimizasyonu" kalemleri (BEKLİYOR)

| kalem | durum | not |
|---|---|---|
| Maliyet (maker) | ⏸ ertelendi | ~%0.06/işlem, 8. sıfırlama gerekir |
| Bakiye/PnL raporlaması | ✅ **YAPILDI** (K-42) | — |
| Sermaye tahsisi | ⏸ bekliyor | vol-paritesi / korelasyon-farkında |
| Pozisyon boyutlandırma | ⏸ bekliyor | ⚠️ edge yokken beklenen kaybı BÜYÜTÜR |

---

## 0.17 K-43/K-44 + "NEDEN HEP WEAK BUY" (2026-09-06)

Kullanıcı iki soru sordu, ikisi de gerçek hataya çıktı.

---

### ⚠️ ÖNCE: ZAMAN DİLİMİ OKUMA HATASI (benim hatam, kayda değer)

Kullanıcı "11 saat oldu işlem açmadı" dedi. DB'ye baktım: `ts_ac` =
`04:01:29`. Log'da o saatte açılış yoktu → "başka bir yol pozisyon
açıyor" diye yanlış bir teşhise başladım.

**Gerçek:** `ts_ac` **naive UTC** yazılıyor (K-14'te de aynı tuzak
işaretlenmişti), log ise YEREL saatte. 04:01 UTC = **07:01 yerel**.
İşlemler 4 saat önce, kapılardan düzgün geçerek açılmıştı:

```
07:01:28  [BNBUSDT] AI:4 | %100 | TREND_UP | 📊 WEAK BUY | ✅ EDGE
07:01:29  [TRADE AÇILDI] #1 BNBUSDT LONG @ 765.10
07:02:14  [TRADE AÇILDI] #2 ETHUSDT LONG @ 2510.67
07:02:19  [PAPER] SOLUSDT | Aynı yönde 2/2 (LONG) → korelasyon riski
```

➜ **Ders: DB zamanları UTC, log zamanları YEREL. Karşılaştırmadan önce
dönüştür.** Bu belgede daha önce de tökezlenen bir yer.

Ayrıca **tempo tahminim yanlış çıktı:** §0.16'da K-37 sonrası için
"0.13–0.27 işlem/gün, 1-2 yıl" demiştim (n=99'luk 20 dakikalık
örnekleme dayanıyordu, zayıf olduğunu belirtmiştim). Gerçek ölçüm:
**3.4–3.6 işlem/gün → 100 işlem ≈ 28-29 gün.**

---

### 🔴 K-43 — DRIFT DEDEKTÖRÜ z=10¹⁵ ÜRETİYORDU

Üretim logu:
```
[DRIFT/ETHUSDT] Feature drift tespit edildi! z=717347997812664.62
```

**Ölçüm (4h dönemi):** 162 alarm · **53'ü (%33) z > 1000** · en yüksek
**1.9×10¹⁵** · medyan 4.36. Bu alarmlar **165 gereksiz retrain**
tetikledi — kullanıcının CPU şikâyetinin somut kaynağı.

**İki ayrı hata:**

1. `std = float(np.std(gecmis_degerler)) or 1.0`
   `or` yalnızca std **TAM 0** iken devreye girer. `std=1e-15` geçip
   bölmeyi patlatıyordu.

2. **KÖK NEDEN — ufka bağlı sessiz varsayım.** 4h'de bar 6 saatte bir
   kapanıyor ama analiz ~60 sn'de bir çalışıyor. AYNI kapanmış barın
   feature'ları geçmişe **~240 kez** ekleniyor → son 20 kayıt
   birbirinin aynısı → std ≈ 0. 5m'de bar 5 dk'da kapandığı için
   sorun GÖRÜNMÜYORDU.
   ➜ **K-29/K-30/K-40 ile aynı sınıf: dördüncü tekrar.**

**Düzeltme (iki katman):**
- `_drift_ayni_bar()` — aynı bar geçmişe tekrar EKLENMİYOR
- Ölçek-göreli std eşiği: `std < max(|ortalama|,1e-9) * 1e-6` ise o
  feature **ATLANIYOR**. (1.0 ile ikame etmek yanlıştı: sabit bir
  feature'ı sahte drift kaynağına çevirirdi.)

Muhafız: `tests/test_drift_dedektoru.py` (8 test), üç yönde mutasyonla
doğrulandı.

⚠️ **Mutasyon testi yine kendi testimin kusurunu buldu:** dedupe'u
kaldıran mutasyon ilk turda YAKALANMADI, çünkü std eşiği patlamayı
zaten önlüyordu — iki düzeltme birbirini örtüyordu. Ayırt edici test
yazdım ama ilk sürümünde bar başına **12 tekrar** kullandım; üretimde
~240. Pencere (20) birden çok barı kapsayınca std sıfıra inmiyor ve
test dedupe'suz kodu da geçiriyordu. **25 tekrara** çıkarınca yakalandı.
➜ *Ders: tekrar sayısı pencereden BÜYÜK olmalı, yoksa test üretim
koşulunu taklit etmiyor.*

---

### 🔴 K-44 — TELEGRAM GÖNDERİMİ GÖRÜNMEZDİ

Başarılı gönderim **hiçbir log yazmıyordu** (yalnızca hata ve
rate-limit debug'a). Sonuç: *"mesaj gitti mi?"* sorusunun logdan cevabı
YOKTU — K-40 teşhisinde tam bu duvara çarpıldı.

**Düzeltme:** `telegram_gonder` ve `telegram_grafik_gonder` başarıda da
`[TG]` satırı yazıyor. Yeniden başlatmadan **80 saniye sonra** kanıt:
```
[TG] gönderildi: tip=sinyal_SOLUSDT (1 parça, 218 karakter)
[TG] grafik gönderildi: astra_SOLUSDT.png (393 KB) — SOLUSDT | AI:4 | 📊 WEAK BUY
```
Bu aynı zamanda **K-40'ı da doğruladı**: AI:4 eşiği geçti; eski kodda
7 gerekiyordu ve hiç gitmezdi.

**Not:** 4h'de analiz fiyatı barlar arasında aynı kaldığı için mesaj da
aynı oluyor ve tekrar-bastırma sürekli devreye giriyor. İlk gönderim
geçer, sonrakiler bastırılır — istenen davranış, artık logda görünür.

---

### 📊 "NEDEN HEP WEAK BUY?" — ÖLÇÜLDÜ, NORMAL

| karar | K-37 öncesi (3077) | K-37 sonrası (2854) |
|---|---|---|
| ⏳ WAIT | %46.3 | %58.2 |
| 📊 **WEAK BUY** | %20.2 | **%33.1** |
| 📈 BUY | %16.9 | %7.0 |
| 📊 WEAK SELL | %12.2 | %1.8 |
| ✅ STRONG BUY | %2.9 | **%0** |
| 📉 SELL | %1.5 | **%0** |

**Sebep: skor aralığı büzüldü.**
```
K-37 öncesi:  AI ∈ [−6, +8]
K-37 sonrası: AI ∈ [−3, +6]   (+6 yalnızca 1 kez)
```
Model güveni `ai_score`'a ±2 katkı veriyordu; nötrlenince iki uç da
kayboldu. `karar_ver` eşikleri sabit (WEAK BUY ≥3, BUY ≥5, STRONG ≥7,
ULTRA ≥9) → üst iki etiket ULAŞILAMAZ, skorlar 3–4 bandında yığılıyor.

➜ **Etiket aslında dürüst:** sistem "güçlü kanaat" ifade edemiyor,
çünkü o kanaatin kaynağı olan bileşen ölçüldü, tahmin gücü bulunmadı
ve susturuldu. Kalan sinyal gerçekten zayıf.

---

### 🔴 ENGEL 4 (YENİ) — REJİM EŞİKLERİ YENİ SKOR ÖLÇEĞİNE KALİBRE DEĞİL

`engines/futures_trade_engine.py::sinyal_gecerli_mi` rejime göre HAM
skor eşiği uyguluyor. K-37 ölçeği değiştirdi, eşikler sabit kaldı:

| rejim | eşik | K-37 sonrası ulaşılabilirlik |
|---|---|---|
| TREND | 3 | ✅ |
| RANGE | 5 | ✅ (198 gözlem) |
| VOLATILE | 6 | ⚠️ 2854'te **1 kez** |
| BEAR | 7 | ❌ **hiç** |

**Bugün zararsız — ÖLÇÜLDÜ:**
```
paper eşiğini (|AI|>=4) geçen : 694
bunlardan canlının reddedeceği:   3  (%0.4)
```
Çünkü piyasa TREND ve orada canlı eşiği (3) paper'ınkinden (4) GEVŞEK.
Paper şu an canlıdan daha katı.

⚠️ **Ama yapısal olarak canlı geçişi engelliyor:** 3 yıllık ölçümde
BEAR %23.6 + VOLATILE %11.7 = **barların %35'i**. Piyasa oraya kayarsa
**canlı yol donar, paper işlem açmaya devam eder** → toplanan 100 işlem
canlıyı temsil etmez (§5.3'ün tam ihlali) ve protokol geçersiz olur.

✅ **K-69 (2026-09-06): paper-canlı ayrışması kapandı.** Paper'ın
`_filtre_gec` yolu artık `sinyal_gecerli_mi` ile ortak değerlendirici
üzerinden aynı rejim eşiğini kullanıyor. Mevcut sapma artık %0; paper
toplanan örneklem, canlıda verilecek aynı giriş kararını temsil eder.

⚠️ **Kalibrasyon kararı hâlâ açık:** BEAR `7` eşiği yeni skor ölçeğinde
ulaşılamıyor, VOLATILE `6` çok seyrek. Bunlar değiştirilecekse bu yeni
bir strateji hipotezidir ve sıfırlama gerektirir; veriyle ölçmeden
oynanmamalı.

**İzleme koşulu:** rejim dağılımı TREND dışına kayarsa (`kontrol_4h.py`
ya da logdaki rejim sayımı), paper↔canlı sapmasını YENİDEN ÖLÇ.

---

## 0.18 DENETİM — 6 GERÇEK HATA (2026-09-06)

Kullanıcı istedi: *"Kodda ve ölçümlerde mantık hataları var mı? AB
testini, öğrenme ve Kelly'yi, Monte Carlo'yu, paneldeki tüm göstergeleri
kontrol et — bazıları bir türlü veri alamıyor."*

**Altı gerçek hata çıktı.** Beşi aylardır sessizce kırıktı.

---

### 🔴 K-45 — ONLINE ÖĞRENME HİÇ ÇALIŞMAMIŞ

```
AttributeError: module 'river.ensemble' has no attribute
                'AdaptiveRandomForestClassifier'
```

`river` (kurulu: **0.21.2**) bu sınıfı `river.forest.ARFClassifier`'a
taşımış. `OnlineLearner.__init__` **her çağrıda** çöküyordu ve istisna
`main.py`'da şu satırla yutuluyordu:
```python
except Exception as _ol_e:
    log.debug(f"[ONLINE BLEND] {sembol}: {_ol_e}")     # SESSİZ
```

Sonuçlar:
- Online öğrenme hiç devreye girmedi
- "Online blend" (batch + online tahmin birleştirme) hiç çalışmadı
- Panelde `online_learning: {}` görünüyordu ve **"henüz veri yok"
  sanılıyordu** — oysa kırıktı

**Düzeltme:** sürümden bağımsız import (`river.forest` → fallback
`ensemble`), ve `log.debug` → `log.warning` (§5.2: ağ çağrısı olmayan
istisna sessiz geçilmez).

### 🔴 K-50 — AYNI KÖKTEN İKİNCİ HATA (ilkini düzeltince ortaya çıktı)

K-45 düzeltilip bot yeniden başlatılınca **yeni** bir hata görünür oldu:
```
[ONLINE/BTCUSDT] Hata: 'NoneType' object has no attribute 'transform_one'
```

`engines/online_learner.py:161`:
```python
x_scaled = self._scaler.learn_one(x).transform_one(x)
```
river 0.15+'ta `learn_one()` artık `self` DEĞİL **`None`** döndürüyor
(yerinde değiştiriyor) → zincirleme çağrı patlıyor.

➜ **Bu hata ancak K-45 + K-48 hatayı GÖRÜNÜR kıldıktan sonra
bulunabildi.** Sessiz yutma, tek bir hatayı değil ARKASINDAKİ HER ŞEYİ
gizliyor.

**Doğrulama (düzeltmeden sonra):**
```
1. tur: prob=0.5000 egitim=0
2. tur: prob=1.0000 egitim=1
3. tur: prob=0.3642 egitim=2      ← gerçekten öğreniyor
```

⚠️ **Ders:** "kuruluyor" ile "öğreniyor" AYRI iddialardır. K-45'in
kurulum testi K-50'yi yakalamıyordu; ikisi ayrı test gerektirdi.

---

### 🔴 K-46 — MONTE CARLO RİSKİ ~5 KAT DÜŞÜK GÖSTERİYORDU

`monte_carlo_raporu` **saatlik** veri çekiyordu:
```python
df = veri_indir(sembol, period="30d", interval="1h")   # SAATLİK
...
var = self.var_hesapla(getiriler, bakiye)              # gun=1
```
ve çıktı **"1G VaR"** diye raporlanıyordu. Yani ekrandaki rakam
1 SAATLİK riskti.

**Ölçüm (BTCUSDT, 3 yıl, aynı fonksiyon):**

| girdi | 1-birim VaR |
|---|---|
| 4 saatlik getiri | 157.86 USDT (%1.58) |
| **GÜNLÜK getiri** | **377.63 USDT (%3.78)** |

2.38× fark; saatlik girdide ~√24 ≈ **4.9×**.

⚠️ **Daha sinsi yanı:** `pozisyon_icin_tam_analiz` risk seviyesini
`var_pct > 3 → YÜKSEK` ile belirliyor. Bu eşik günlük VaR için kalibre;
saatlik değer 3'ü neredeyse hiç geçmediği için **risk seviyesi
PRATİKTE HEP "DÜŞÜK"** çıkıyordu.

**Düzeltmeden sonra gerçek değerler:**
```
1G VaR : 386.71 USDT (%3.87)
30G DD : %23.75
Risk   : YÜKSEK          ← eskiden "DÜŞÜK"
```

➜ K-29/K-30/K-40/K-43 ile aynı sınıf: **birime bağlı sabit**. Beşinci
tekrar. `var_hesapla` docstring'ine artık açık birim sözleşmesi yazıldı.

---

### 🔴 K-47 — A/B SHARPE ANLAMSIZ

```python
return float(np.mean(self._pnl_list) / self.std_pnl * np.sqrt(252))
```
`√252` her kaydın **günlük getiri** olduğunu varsayar; oysa kayıtlar
**işlem başına PnL** ve bot 4h'de günde ~3 işlem yapıyor. Panelde
`sharpe: -28.356` yazıyordu (−1.786 × √252 = −28.36).

Ayrıca eşik `n < 5` idi — **5 örnekle Sharpe raporlamak gürültü
ölçmektir.**

**Düzeltme:** yıllıklandırma kaldırıldı (işlem/yıl oranı rejime göre
değişir, sabit çarpan doğru olamaz), eşik **30**'a çıkarıldı.

---

### 🔴 K-48 — PANEL METRİKLERİ SESSİZCE ÇÖKÜYORDU

`main.py::_gelismis_state_topla` içindeki **11 blok**:
```python
try:
    g["kelly"] = ...
except Exception: pass          # ← 11 kez
```

Sonuç: bir metrik çökerse panel `{}` gösteriyor ve **"veri yok" ile
"çöktü" AYIRT EDİLEMİYOR.** K-45'in aylarca görünmemesinin sebebi
tam olarak buydu.

11'i de `log.warning` ile sesli hale getirildi.

---

### 🔴 K-49 — A/B VERİSİ SIFIRLAMADAN SAĞ ÇIKIYORDU

`data/ab_test.json` **2026-08-27** tarihliydi — 4h geçişinden VE
K-37'den önce. Panelde güncel gibi gösteriliyordu:
```json
{"a_pnl": [-1.142, -0.13, -1.109, -0.373, -1.109],
 "b_pnl": [-0.259, 0.13, -0.156, -1.112, -1.109],
 "ts": "2026-08-27T14:04:25"}
```
`sifirla_k37.py` bu dosyayı yedekliyor ama **silmiyordu**.
§5.3: toplanan tüm veri TEK yapılandırmayı yansıtmalı — A/B
karşılaştırması da veridir. Silindi, betiğe eklendi.

---

### 📊 PANEL GÖSTERGELERİ — TEŞHİS

| gösterge | durum |
|---|---|
| `online_learning` | 🔴 **KIRIKTI** → K-45 + K-50 ile düzeltildi |
| `kelly` | ✅ meşru boş — `kelly_fraksiyon()` n=0 döner, kapanan işlem yok |
| `validator` | ✅ meşru boş — sembol başına **≥30 işlem** gerekiyor (`_strateji_dayaniklilik_dogrula`), altındaysa cache'e HİÇ yazmıyor |
| `portfolio` | ✅ meşru boş — MVO yalnızca pozisyon boyutlandırılırken çalışıyor, `_yontem="Başlatılmadı"` |
| `kapanan_islemler` / `gunluk_pnl` / `toplam_pnl` | ✅ meşru boş — henüz kapanan işlem yok |

Son üçü veri biriktikçe dolacak. Artık çökerlerse **logda görünecek**
(K-48).

---

### ⚠️ YİNE KENDİ TESTLERİMİN KUSURUNA DÜŞTÜM

İlk yazdığım 10 denetim testinin **5'i yanlış alarm verdi**: ham
kaynakta metin arıyorlardı ve **düzeltmeyi açıklayan YORUMLARIMI** eski
kod sanıyorlardı. Örnek:
```
"except Exception: pass" → 11 eşleşme … hepsi benim yorum metnimde
"interval=\"1h\""        → "Eskiden interval='1h' idi" yorumunda
"np.sqrt(252)"           → "Eskiden * np.sqrt(252) vardı" yorumunda
```

Bu tuzak bu kod tabanında **zaten belgeli** — `test_grafik_thread.py`:
*"İlk sürüm satır bazlı okuyordu ve DOCSTRING'deki `plt.savefig`
açıklamasını gerçek çağrı sanıp yanlış alarm veriyordu."*
Belgeye rağmen aynısını yaptım.

**Düzeltme:** `_kod()` yardımcısı — `tokenize` ile yorum ve string
literalleri ayıklıyor. Yapısal kontroller (sessiz `except`, `interval`
argümanı) **AST** ile yapılıyor.

➜ **Kural: kaynak düzeyi testler ham metinde ARAMA YAPMAZ.**
tokenize veya AST kullan; aksi halde test kendi açıklamasını yakalar.

Muhafız: `tests/test_denetim_duzeltmeleri.py` (12 test), beş yönde
mutasyonla doğrulandı.

---

## 0.19 TELEGRAM KOMUT DENETİMİ + VERİ TUTARLILIĞI (2026-09-06)

Kullanıcı istedi: *"Tüm telegram komutlarını tek tek kontrol et,
VARSAYIM YAPMADAN test et. Veriler tutarlı ve eşleşiyor mu?"*

**Yöntem:** 36 komutun her biri sahte Update/Context ile GERÇEKTEN
çağrıldı. Dış etki kesildi (telegram_gonder + emir fonksiyonları
mock'landı). Durum değiştiren ikisi (`cmd_fkapat`,
`cmd_shadow_approve`) hiç çalıştırılmadı.

### Sonuç

| | adet |
|---|---|
| ✅ Çalışıyor | **33** |
| ⏱ Zaman aşımı | 1 (`/scan`, 150s) |
| ⏭ Atlandı (mutasyon) | 2 |
| ❌ Bozuk | **0** |

### ⚠️ ÖNCE KENDİ ÖLÇÜMÜM YANILDI

İlk koşu **9 komutu "BOŞ YANIT"** gösterdi. Bozuk diye raporlamak
üzereydim. Kanal başına takip ekleyip yeniden çalıştırınca ortaya
çıktı: o komutlar `_yanitla` yerine **`telegram_gonder`** kullanıyor —
dokuzunun da çıktısı VAR.

➜ **Ders:** "yanıt yakalayamadım" ≠ "yanıt yok". Ölçüm aracının
kapsamadığı bir kanal, sessiz bir yanlış negatif üretir. Kullanıcı
"varsayım yapmadan test et" dediği için ikinci kez bakıldı; yoksa
9 sağlam komut "bozuk" diye rapor edilecekti.

---

### 🔴 K-52 — 11 KOMUTTA SEMBOL BOZULMASI

Komut çıktılarında görüldü:
```
🌐 <b>MARKET — BTCUSDTUSDT</b>
⛓️ <b>ON-CHAIN — BTCUSDTUSDT</b>
```

Kök neden — **11 komutta aynı desen**:
```python
sembol = f"{c.args[0].upper()}USDT" if c.args else "BTCUSDT"
```

| girdi | sonuç |
|---|---|
| `/market BTC` | BTCUSDT ✓ |
| **`/market BTCUSDT`** | **BTCUSDTUSDT** ✗ |

⚠️ **En olası kullanım tam da bozulan girdi:** bot her yerde sembolleri
TAM hâliyle gösteriyor (`BTCUSDT`), yani kullanıcının tam sembolü
yazması beklenen davranış.

⚠️ **SESSİZ:** geçersiz sembol gerçek API çağrısına gidiyor ve
`market_veri_topla("BTCUSDTUSDT")` hata vermek yerine **SIFIR DOLU**
sözlük döndürüyor (funding %0.0000, OI 0.00, F&G 0). Kullanıcı bunu
gerçek piyasa verisi sanar — §5.1 fail-open deseninin yeni yüzü.

**Düzeltme:** `_sembol_normalize()` tek kaynak, **12 yerde** bağlandı.
```
BTC → BTCUSDT · btcusdt → BTCUSDT · BTC/USDT → BTCUSDT
BTC-USDT → BTCUSDT · ETHUSDC → ETHUSDC (teminat korunur)
```
Muhafız: `tests/test_komut_sembol.py` (9 test), iki yönde mutasyonla
doğrulandı. Kaynak testi AST ile (ham metin araması §0.18'de yanlış
alarm vermişti).

---

### 🔴 K-51 — VERİ TUTARLILIĞI ARTIK OTOMATİK

Canlı sistemde 10 bağımsız karşılaştırma yapıldı: **10 uyuşuyor,
0 çelişki.**

| büyüklük | karşılaştırılan kaynaklar |
|---|---|
| Kapanan işlem | panel · `win_rate_hesapla` · `para_dokumu` · SQL COUNT |
| Açık pozisyon | panel · `para_dokumu` · `durum_raporu` · `acik_tradeler` · SQL |
| Paper bakiye | `panel.paper_bakiye` · `panel.para_dokumu` · `para_dokumu` · `durum_raporu` |
| Toplam PnL | `toplam_pnl()` · `para_dokumu` · `durum_raporu` · SQL SUM |
| Win rate | panel · DB |

Muhasebe özdeşlikleri de tutuyor:
```
brüt PnL      = net PnL + ödenen komisyon      ✓
toplam varlık = nakit + bağlı sermaye           ✓
bağlı sermaye = Σ(giriş fiyatı × miktar)        ✓
nakit         = başlangıç − bağlı + net         ✓
```

**Tek seferlik betik olarak bırakılmadı** — `tests/test_veri_tutarliligi.py`
(9 test) kendi sahne verisini kurar (üretime bakmaz, §4.6: bot
çalışırken rastgele kırmızıya dönmesin). İki yönde mutasyonla
doğrulandı.

**Değeri:** K-32/K-33'te panel ile Telegram çelişiyordu ve İKİSİ DE
yeşil testlerden geçiyordu; hata ancak kullanıcı iki ekrana bakıp
sayıları karşılaştırınca ortaya çıktı. §0.12 o zaman şunu yazmıştı:
*"Aynı büyüklüğü raporlayan her iki kaynak, düzenli olarak
karşılaştırılmalı."* Artık bunu test paketi yapıyor, insan değil.

⚠️ **Bugünkü sınır:** kapanan işlem 0 olduğu için canlı kontrollerin
bir kısmı `0 == 0` şeklinde önemsiz geçti. İzole testler gerçek
sahne verisiyle çalıştığı için onlar güçlü; canlı karşılaştırma
işlemler kapandıkça anlamlanacak.

---

### 🔴 K-53 — PANEL PERİYODİK OLARAK 56 SANİYE DONUYORDU

Komut denetimi sırasında tutarlılık betiği panele bağlanamadı
(`ReadTimeout 15s`). Kovalayınca gerçek bir hata çıktı.

**Ayırt edici ölçüm (25 çift istek):**

| uç nokta | kilit alır mı | iş yapar mı | süre |
|---|---|---|---|
| `/saglik` | ❌ | sabit 14 bayt | **56.4s ve 58.3s** |
| `/api/state` | ✅ | JSON üretir | hep milisaniye |

➜ **HİÇBİR İŞ YAPMAYAN uç nokta donuyordu, kilidi alan hep hızlıydı.**
Bu, sorunun kilit çekişmesi ya da handler gövdesi OLMADIĞINI kanıtladı
— takılma bağlantı/kuyruk seviyesindeydi.

**Kök neden:** `HTTPServer` aynı anda TEK bağlantı işler. Bir bağlantı
takılınca ardındaki her istek bekler (head-of-line blocking). Tarayıcı
paneli saniyede bir yokladığı için bu pratikte panelin donması demek.

Yavaşlama penceresinde (41.7s) logda **23 saniyelik tam sessizlik**
vardı, ardından `[ORPHAN CHECK]` / `[SL/TP VERIFY]` / `[AUDIT]`.
23s, `http_guard`'ın `connect=8s + read=15s` toplamıyla örtüşüyor —
tıkanan bir Binance çağrısı olabilir.

**Düzeltme:** `ThreadingHTTPServer` + `daemon_threads=True`.
**Ölçüm:** 30 çift istekte (60 istek) **0 yavaşlama**.

⚠️ **DÜRÜST SINIR:** bu düzeltme takılmanın KÖK NEDENİNİ ÇÖZMÜYOR —
hangi işlemin ~56s tuttuğu belirlenemedi. Yaptığı şey, tek bir
takılmanın DİĞER istekleri de kilitlemesini engellemek. Kök neden
ayrıca aranmalı; §5.2 gereği burada kayıtlı.

Muhafız: `tests/test_panel_esszamanlilik.py` (4 test). Davranışsal
test gerçek bir sunucu kurup yavaş/hızlı istek yarıştırıyor; KONTROL
testi tek iş parçacıklı sunucunun GERÇEKTEN bloke ettiğini kanıtlıyor
(ölçüt bozuksa asıl test anlamsız olurdu).

### 🟡 AÇIK KALAN İKİ GÖZLEM

**1. `/scan` 150 saniyede bitmiyor.** 5 coini sırayla analiz ediyor,
her biri model eğitimi tetikliyor. Gerçek Telegram'da kullanıcı yanıt
alamadan bekler. K-30 ile aynı sınıf (sabit tavan, içindeki iş ağır)
ama komut yolunda. `_analiz_timeout_ile` 90s kullanıyor; `/scan`
için ayrı bir tavan yok.

**2. İki farklı yanıt kanalı.** Komutların bir kısmı `_yanitla`
(isteyen sohbete cevap verir), bir kısmı `telegram_gonder(mesaj, cid)`
kullanıyor. İkincisi `cid`'i doğru geçiyor → şu an zararsız. Ama
"iki yol aynı işi yapıyor" bu kod tabanında TEKRAR EDEN hata sınıfı
(K-13 paper/canlı çıkış, K-32 çift bildirim). Birleştirilmesi §6.0'daki
veto zinciri işiyle birlikte ele alınmalı.

---

## 0.20 KOMUT DENETİMİ — 7 HATA (2026-09-06)

Kullanıcı `/yardim` çıktısını verip *"tüm komutları tek tek test et,
kodlarına bak, doğru çalıştıklarını doğrula"* dedi. Sonra `/fpoz`'un
panelle çeliştiğini fark etti.

**Sonuç: 35/35 komut çalışıyor, 7 gerçek hata bulundu.**

### Yöntem

Her komut sahte Update/Context ile GERÇEKTEN çağrıldı, **kayıtlı
handler üzerinden** (yetki sarmalayıcısı dahil). Dış etki kesildi:
`telegram_gonder`, `telegram_grafik_gonder`, tüm futures emir
fonksiyonları, `order_engine.submit`, `shadow_manager.manuel_onayla`
mock'landı.

**Yetki katmanı ayrıca test edildi:** yanlış `chat_id` → reddedildi ve
`[GÜVENLİK] Yetkisiz komut denemesi` loglandı. ✓

---

### 🔴 K-52 — 11 KOMUTTA SEMBOL BOZULMASI

```
/market BTCUSDT  →  🌐 MARKET — BTCUSDTUSDT
```
```python
sembol = f"{c.args[0].upper()}USDT" if c.args else "BTCUSDT"
```
Bot her yerde sembolleri TAM gösteriyor, yani **en olası kullanım tam
da bozulan girdi.** Ve sessiz: `market_veri_topla("BTCUSDTUSDT")` hata
yerine SIFIR DOLU sözlük döndürüyor — kullanıcı gerçek veri sanar.

`_sembol_normalize()` tek kaynağa çıkarıldı, **12 yerde** bağlandı.
Muhafız: `tests/test_komut_sembol.py` (9 test).

### 🔴 K-53 — PANEL PERİYODİK 56 SANİYE DONUYORDU

**Ayırt edici ölçüm (25 çift istek):**

| uç nokta | kilit | iş | süre |
|---|---|---|---|
| `/saglik` | ❌ almaz | sabit 14 bayt | **56.4s / 58.3s** |
| `/api/state` | ✅ alır | JSON üretir | hep ms |

➜ HİÇBİR İŞ YAPMAYAN uç nokta donuyordu → sorun kilit ya da handler
DEĞİL, bağlantı/kuyruk seviyesinde. `HTTPServer` tek iş parçacıklı.

`ThreadingHTTPServer` + `daemon_threads`. **60 istekte 0 yavaşlama.**

⚠️ Kök neden ÇÖZÜLMEDİ — hangi işlemin ~56s tuttuğu belirlenemedi
(yavaşlama penceresinde 23s log sessizliği var, `http_guard`'ın
8+15s'iyle örtüşüyor). Düzeltme yalnızca head-of-line blocking'i
kaldırıyor. Muhafız: `tests/test_panel_esszamanlilik.py` (4 test).

### 🔴 K-54 — KAYIT BÜTÜNLÜĞÜ DENETLENMİYORDU

Bir komut çalışsın diye ÜÇ şey birden doğru olmalı: TANIMLI, KAYITLI,
İLAN EDİLMİŞ. Üçü ayrı yerde ve elle senkron tutuluyor.

Denetim **temiz** çıktı (36 fonksiyon, 36'sı kayıtlı, ölü kod yok) ama
kontrol edilmiyordu. Muhafız: `tests/test_komut_kaydi.py` (7 test).

### 🔴 K-55 — KOMUTLARI YAVAŞLATAN ASIL SEBEP

`/btc` **75.2 sn**, `/scan` 180 sn'de bitmiyordu. O 75 saniyede:
**11 `[SKIP]`, 11 model kaydı, 8 Optuna, 4 stacking, 1 TFT.**
Son 2 saatte toplam **525 `[SKIP]`**.

Kök neden: `MIN_USEFUL_ACC = 0.52` kapısı, eşiği geçemeyen modeli
TAZE OLSA BİLE atıp yeniden eğitiyordu. Yeni model de gürültü olduğu
için yine geçemiyor → **her çağrıda eğitim döngüsü.**

**Kaldırmak neden güvenli — ÖLÇÜLDÜ:** K-37'den beri **634 model
seçiminin 0'ında** beceri anlamlı (1284 nötrleme). Model katkısı her
zaman 50.0 olduğundan HANGİ modelin seçildiği sinyali ETKİLEMİYOR.
Eşik koruma sağlamıyor, yalnızca maliyet üretiyordu.
➜ **Davranış değişmediği için SIFIRLAMA GEREKMEDİ.**

| komut | önce | sonra |
|---|---|---|
| `/btc` | 75.2s | **13.1s** |
| `/coin ETH` | 66.8s | **6.8s** |
| `/scan` | >180s ✗ | **79.2s** ✅ |

Kullanıcının CPU şikâyetinin kaynağı da buydu.
Muhafız: `tests/test_model_onbellek.py` (6 test).

⚠️ Testim düzeltmenin EKSİK olduğunu buldu: TFT ve stacking dallarında
iki kapı daha vardı, onlar da kaldırıldı.

---

### 🔴 K-56 / K-57 — `/fpoz` PANELLE ÇELİŞİYORDU

**Kullanıcı bildirimi:** *"Açık pozisyon yok diyor /fpoz ama panelde
2 tane açık?"*

**K-56:** rapor pozisyonları KOŞULSUZ `acik_futures_pozisyonlar()`'dan
okuyordu. Paper modda bot futures'ta hiç işlem yapmadığı için liste
hep boş → "📭 AÇIK POZİSYON YOK".

⚠️ **K-33'ün YARIM KALMIŞ hâli:** o düzeltme aynı raporun BAKİYESİNİ
paper'a çevirmiş ama VERİ KAYNAĞINI çevirmemişti. Sonuç: PAPER
bakiyesini FUTURES pozisyonlarıyla gösteren, ve **tutarlı GÖRÜNEN**
bir rapor. Tek raporda iki kaynak.

Ayrıca paper→futures şema eşlemesi main.py'da **iki ayrı yerde**
duplikeydi ve `/fpoz` hiçbirini kullanmıyordu → `acik_pozisyonlar_birlesik()`
tek kaynağına çıkarıldı.

**K-57 (ilkini düzeltince ortaya çıktı):**
```
Giriş:765.0995  Güncel:758.2000  ✅ PnL:+0.0000USDT
```
Pozisyon zararda, rapor kârda gösteriyor. Rapor `guncel` fiyatı TAZE
çekiyor ama PnL'i BAŞKA kaynaktan (analiz cache'i) alıyordu; cache
boşsa PnL sessizce 0 kalıyor ve ✅ işareti çıkıyordu. Artık aynı
satırdaki `guncel` ile hesaplanıyor.

**Düzeltmeden sonra panel ile eşleşiyor:**

| | panel | /fpoz |
|---|---|---|
| Pozisyon | 2 | 2 |
| BNBUSDT PnL | −0.8965 | −0.8874 |
| ETHUSDT PnL | −0.3482 | −0.3490 |

(Küçük fark beklenen: panel kapanmış bar fiyatını, `/fpoz` anlık
tick'i kullanıyor.)

Muhafız: `tests/test_pozisyon_kaynagi.py` (8 test), üç yönde mutasyonla
doğrulandı.

### 🔴 K-58 — TUTARLILIK TESTİ BU HATAYI YAKALAYAMAZDI

Kritik ders: K-51'de yazdığım tutarlılık testi K-56'yı **yakalayamadı**.
Çünkü yalnızca paper kaynaklarını (panel, DB, `para_dokumu`)
karşılaştırıyordu ve hepsi doğruydu. `/fpoz` FARKLI bir kaynaktan
okuduğu için karşılaştırma kümesinin **DIŞINDAYDI**.

➜ *"Aynı büyüklüğü raporlayan her kaynak"* ifadesindeki **her**,
kullanıcının GÖRDÜĞÜ her yüzeyi kapsamalı — panel **ve** Telegram.

`tests/test_veri_tutarliligi.py` genişletildi (9 → 12 test): `/fpoz`
ve `/paper` raporlarının ürettiği sayılar da artık karşılaştırılıyor.
Mutasyonla doğrulandı: `/fpoz`'u koşulsuz futures'a döndürmek testi
kırıyor.

---

### ⚠️ KENDİ TESTLERİMİN KUSURLARI — BUGÜN BEŞ KEZ

Hepsinin kökü aynı: **kaynak METNİNDE arama yapan test kırılgandır.**

1. §0.18: yorumlarımı eski kod sandı (5/10 test yanlış alarm)
2. İlan listesi kaynak metninden çıkarılıyordu; tırnak yüzünden 38'de
   22 buluyordu → `test_ilan_edilen_her_komut_kayitli` sessizce zayıftı,
   mutasyon yakaladı
3. `[SKIP]` testi `"yeniden eğit"` metnini arayıp kendi docstring'ime
   takıldı
4. K-27 muhafızı `"if acc >= MIN_USEFUL_ACC:"` satırına çapalıydı;
   K-55 o satırı kaldırınca **davranış bozulmadığı hâlde** kırıldı
5. Komut testi 9 komutu "boş yanıt" gösterdi — o komutlar `_yanitla`
   yerine `telegram_gonder` kullanıyordu; kanal takibi eklenince
   dokuzunun da çıktısı olduğu görüldü

**KURAL: kaynak düzeyi testler ham metinde arama YAPMAZ.**
`tokenize` (yorum/string ayıklama) veya `ast` (yapısal) kullan.

### 🟡 AÇIK GÖZLEM

Komutların bir kısmı `_yanitla`, bir kısmı `telegram_gonder(mesaj, cid)`
kullanıyor. İkincisi `cid`'i doğru geçiyor → şu an zararsız. Ama "iki
yol aynı işi yapıyor" bu kod tabanında tekrar eden hata sınıfı
(K-13, K-32, K-56). §6.0'daki veto zinciri işiyle birlikte
birleştirilmeli.

---

## 0.21 BAKİYE BÜTÜNLÜĞÜ + PANEL (2026-09-06 akşam)

Kullanıcı üç şey bildirdi, üçü de gerçek hataya çıktı. Ayrıca dört
denetim istedi — **onlar YAPILMADI, §0.22'de bekliyor.**

---

### 🔴 K-59 — BAKİYE TABANI SAHTE PARA ÜRETİYORDU

**Kullanıcı şüphesi:** *"Çektiği para ile eksilen para, veya kazanılan
parayla yansıyan para aynı olmamasından şüpheliyim."*

Uçtan uca ölçüldü (açılış · kapanış · 40 işlem · restart · DB):

**Temel muhasebe SAĞLAM çıktı.** Artımlı bakiye ile DB'den türetilen
bakiye farkı **0.000000**. DB toplam PnL birebir tutuyor. Yani ana
şüphe normal işleyişte doğrulanmadı.

**AMA üç gerçek kusur bulundu:**

**1. `max(bakiye, baslangic * 0.05)` — SAHTE PARA.**
```
%99 zarar senaryosu:
  gerçek olması gereken : 100.00 USDT
  _bakiye_hesapla döndü : 500.00 USDT   ← 400 USDT YOKTAN VAR
```
Yalnızca **yeniden başlatmada** devreye giriyordu → çalışan bakiye ile
yeniden başlatılan bakiye ayrışıyordu. Bot bugün ~12 kez yeniden
başlatıldı.

⚠️ **Bu, 100 işlemlik protokolün görmek istediği şeyi GİZLİYORDU:**
kill switch davranışı ve zarar dönemi (§3 ENGEL 2). Felaket zararı
sessizce %5 tabanına yuvarlıyordu.

**2. `round(bakiye, 2)`** — her restart'ta 0.0027$ sapma. Kaldırıldı,
artımlı bakiye tam hassasiyette.

**3. `max(geri_gelen, 0)`** — zarar pozisyon maliyetini aşarsa fark
sessizce yutuluyordu (1x kaldıraçta oluşmaz ama muhasebe kaçağı).

**Düzeltmeden sonra:** tüm farklar **tam sıfır**, taban para uydurmuyor.
Bakiye tükenirse `log.critical` + 0.0 döner.

Muhafız: `tests/test_bakiye_butunlugu.py` (7 test).

---

### 🔴 K-60 — PANEL SAATİ 3 SAAT GERİDEYDİ

**Kullanıcı bildirimi:** *"saati yanlış gösterdiklerini fark ediyorum."*

Panel İKİ zaman tabanını karıştırıyordu:
```
son_guncelleme   = datetime.now(timezone.utc)…"%H:%M:%S UTC"   ← UTC
sinyal_gecmisi ts= datetime.now()                               ← YEREL
kapanan_islem ts = datetime.now()                               ← YEREL
```
Ölçüm:
```
YEREL saat           : 16:01:14
panel son_guncelleme : 13:00:37 UTC   ← 3 saat geride
panel sinyal ts      : 16:00:37       ← yerel
```

**Düzeltme:** `son_guncelleme_ts` (epoch) gönderiliyor, **tarayıcı
kendi yerel saatinde** biçimlendiriyor (`yerelSaat()`). Epoch tek doğru
kaynak; biçimlendirme istemcide.

➜ Bu, DB'nin naive UTC yazması (K-14) ile aynı sınıf. **Ders: zaman
değerini metin olarak taşıma, epoch taşı.**

### 🔴 K-61 — "CANLI ANALİZLER BAZEN DURUYOR"

Kullanıcı gözlemi doğruydu ve sebebi ölçüldü: `son_guncelleme` **HER**
state güncellemesinde ilerliyordu (bakiye, risk, kill switch…), ama
`son_analiz` yalnızca analiz turu bitince yenilenir.

Sonuç: **saat akarken coin verisi donabiliyordu** ve kullanıcı bunu
ayırt edemiyordu.

**Düzeltme:** `son_analiz_ts` ayrı damga — yalnızca `son_analiz`
geldiğinde ilerler. Panel artık analiz **yaşını** gösteriyor:
`16:04:11 · 155 sn önce`, 5 dk sonra sarı, 10 dk sonra kırmızı.
(4h barda tur ~1 dk sürer; 10 dk sessizlik analiz durmuş demektir.)

### ✅ K-62 — COİN KARTINDAN BINANCE'E GİT

Kullanıcı isteği. Kart artık `<a>` — tıklayınca
`binance.com/tr/futures/<SEMBOL>` yeni sekmede açılıyor.
`rel="noopener noreferrer"` (açılan sayfa `window.opener`'a erişemesin),
sembol `encodeURIComponent` ile kaçırılıyor.

---

## 0.48 GITHUB'A HAZIRLANDI — PUSH BEKLIYOR (2026-10-05)

### DURUM

```
git deposu : KURULDU (main dali)
commit     : 47ceab5 ilk commit · 30217ea README · dc21499 notlar
dosya      : 211 · 2.46 MB   (8.3 GB'den indi)
yazar      : lemuxon <lemuxon@users.noreply.github.com>  (YEREL ayar, global DEGIL)
remote     : https://github.com/lemuxon/astra.git  (tanimli, HENUZ push EDILMEDI)
hedef      : PRIVATE repo
```

**KALAN TEK ADIM (kullanici yapacak):** GitHub'da bos private repo ac →
`git push -u origin main`. Credential Manager kurulu, tarayicidan giris
yeterli — token gerekmiyor.

> Push'u asistan YAPMAZ: makinede kimlik yok, kimlik girmek §4.4 ihlali.

### GUVENLIK DENETIMI — BULUNAN VE DUZELTILENLER

**EN CIDDISI:** `sunucu/PUTTY_ADIMLARI.md` satir 27/73/116'da Contabo
sunucusunun GERCEK public IP'si + port 22 + root acikca yaziliydi. Belge
ayrica parola ile root girisinin acik oldugunu anlatiyordu. Kardes dosya
`KURULUM.md` dogru sekilde `<SUNUCU_IP>` kullaniyordu — tutarsizlik sadece
o dosyadaydi. **Duzeltildi** (yedek: `/tmp/putty_yedek.md`).

➜ **SUNUCU HALA AYAKTAYSA:** IP bir suredir o dosyada yaziliydi. Parola ile
SSH girisini kapat (`PasswordAuthentication no`).

**`.gitignore` yeniden yazildi. Kok neden tek ve ogretici:**
Eski desenler `saved_models/*.pkl`, `data/*.db` gibi ICINDE "/" olan
yollardi. Git'te icinde "/" gecen desen **repo kokune SABITLENIR**, alt
dizinleri kapsamaz.

Olculen sonuc — bunlar commit edilecekti:
```
data/_yedek_*/ altinda 2188 .pkl + 36 .db   ~4.5 GB
data/orderbook/*.jsonl.gz                    172 MB
st.json (kokte)      gercek bakiye + acik pozisyonlar
astra_kurulum.tar.gz icinde astra.db-wal
```
➜ Cozum: dosya TURU icin ciplak desen (`*.pkl`), dizin icin izin listesi
(`data/*` + `!data/*.py` — data/ icinde 8 gercek modul var).

Ayrica temizlendi: `C:\Users\Casper` yollari (kod + notlar + .bat).

### DOGRULANDI (iddia degil, olcum)

- `git check-ignore` ile tek tek: `.env`, `st.json`, tarball, tum .db/.pkl/.gz
- Commit edilecek 211 dosyada sir taramasi: Binance anahtar deseni **0**,
  Telegram token **0**, ozel anahtar blogu **0**, e-posta **0**, public IP **0**
- Testlerdeki `API_KEY`/`SECRET` atamalari `.env`'deki GERCEK degerlerle
  karsilastirildi → hepsi sahte fikstur (`test_key`, `test_secret`)
- Tam test paketi: **554 test, 0 basarisiz**

⚠️ Ara kontrolde ".env'deki her uzun deger" aramasi YANLIS ALARM verdi —
eslesenler `FUTURES_BASE_URL` (public Binance adresi) ve `DB_PATH`'ti.
**Olcumun kendisi de olculmeli**; bu oturumun tekrar eden dersi.

### README EKLENDI

Giris DURUST durumla aciliyor: *"Bu bot henuz kar ettigini kanitlamadi —
9 hipotez denendi, 9'u reddedildi, sayac 0/100."* Kaldirac riski uyarisi,
veto zinciri akisi, dizin haritasi ve **"Degismez kurallar"** (§5.3 paper
esitligi · fail-open · yesil test kanit degildir · metin aramasi davranisi
kilitlemez · suruklenme ≠ edge) dahil.

Tum sayisal iddialar olculerek yazildi.

---

## 0.47 ✅ CMD PENCERESİ DURDURULDU — yetkisiz çözüm (2026-09-21)

Kullanıcı üç kez bildirdi: *"hâlâ kendi kendine cmd açılıyor,
C:\WINDOWS\SYSTEM32\cmd.exe diye."*

### Neden `gorevi_gizle.bat` işe yaramadı

Çalıştırılmamıştı — görev eylemi hâlâ `.bat`'ı gösteriyordu. Ve o betik
YÖNETİCİ yetkisi istiyor; kullanıcı projeden uzaklaşıyor, ek adım
istemek doğru değildi.

⚠️ `ASTRA_OrderBook` görevine yetkisiz HİÇBİR ŞEKİLDE dokunulamıyor:
`Set-ScheduledTask`, `Disable-ScheduledTask`, `Start-ScheduledTask` —
hepsi "Erişim engellendi". (`ASTRA_Bot`'tan farkı: o kullanıcı
tarafından, bu yönetici olarak oluşturulmuş.)

### Yapılan — göreve dokunmadan

```
baslat_orderbook.bat  →  _baslat_orderbook_ASIL.bat   (yeniden adlandırıldı)
```
Görev var olmayan bir dosyayı çağırıyor ➜ süreç HİÇ oluşmuyor ➜ pencere
açılmıyor. Göreve dokunmak gerekmedi.

**DOĞRULANDI (iddia değil, ölçüm):** 17:57:01 doğal tetiklemesi ateşledi,
`LastTaskResult` sıfırdan farklı, ve `orderbook_yasam_dongusu.log`
**2414 baytta SABİT kaldı** — yani bat hiç çalışmadı.

### Ayrıca ortaya çıkan: desen "10 dakikada bir" DEĞİLDİ

```
kaydedici PID: 2112 (18.09 23:07)  →  7396 (21.09 17:37)
```
Kaydedici arada bir kendiliğinden yeniden başlıyor. Görev instance'ı
python'u beklerken "Running" kalıyor ve o sırada gelen tetiklemeler
REDDEDİLİYOR (0x800710E0). Pencere yalnızca kaydedici öldüğünde ve
watchdog gerçekten yeni bir instance başlattığında açılıyordu.
➜ Kullanıcının "arada bir" demesi tam olarak bununla uyumlu; benim
"10 dakikada bir pencere" varsayımım fazla kabaydı.

### Şu anki durum

```
kaydedici : PID 7396 ÇALIŞIYOR, hâlâ topluyor (log 17:57:29)
görev     : tetikleniyor ama başlatamıyor → pencere YOK
sonuç     : kaydedici kendiliğinden durduğunda toplama biter,
            ama bir daha pencere açılmaz
```

### GERİ ALMAK

`gorevi_gizle.bat` güncellendi: artık önce `_baslat_orderbook_ASIL.bat`'ı
eski adına geri koyuyor, sonra görevi gizli sarmalayıcıya yönlendiriyor.
Yani ileride order book toplamayı düzgün biçimde geri istersen **tek
dosya** yeterli (yönetici olarak çalıştır).

Elle geri almak için: `_baslat_orderbook_ASIL.bat` → `baslat_orderbook.bat`

---

## 0.46 ⏸️ UZUN ARA — DÖNÜNCE BURADAN BAŞLA (2026-09-21)

Kullanıcı bir süre projeden uzak kalacak. Bu bölüm, aylar sonra
dönüldüğünde bile tek başına yeterli olacak şekilde yazıldı.

### MAKİNEDE NE ÇALIŞIYOR, NE ÇALIŞMIYOR

```
ASTRA_Bot        → Disabled   · bot DURUYOR, işlem açmıyor
ASTRA_OrderBook  → Ready      · 10 dk'da bir watchdog (KAYDEDİCİ ÇALIŞIYOR)
```

⚠️ **Order book kaydedici hâlâ veri topluyor** ve bu BİLEREK böyle:
§0.6'da ölçüldü — Binance geçmiş order book snapshot'ı SUNMUYOR, yani
"bugün toplamazsak üç hafta sonra da elimizde olmaz". Denenmemiş tek
gerçek yeni bilgi kaynağı (mevcut 34 feature'ın tamamı fiyat/hacim
türevi). Disk maliyeti küçük, bot'a dokunmuyor.

✅ **CMD PENCERESİ SORUNU ÇÖZÜLDÜ** (§0.47, 2026-09-21).
`baslat_orderbook.bat` kenara alındı (`_baslat_orderbook_ASIL.bat`);
görev tetikleniyor ama artık hiçbir şey başlatamıyor → pencere YOK.
Göreve dokunulmadı (yetkisiz dokunulamıyor).
Geri almak için: `gorevi_gizle.bat` (yönetici olarak çalıştır) —
asıl dosyayı geri koyar ve görevi gizli sarmalayıcıya yönlendirir.

⚠️ **Testnet'te iki pozisyon açık kaldı** (ADAUSDT, APTUSDT SHORT).
Koruma emirleri borsada duruyor; bot kapalı olduğu için zaman stop
işlemez. Test parası — aciliyeti yok, istenirse testnet arayüzünden
elle kapatılır.

### DÖNÜNCE İLK ÜÇ ADIM

1. **`DEVAM_NOTLARI.md` §0.44'ü oku** — orada duran AÇIK SORU:
   *paper 0 işlem açarken canlı 5 açtı; ayrışma tersine döndü.*
   APTUSDT vakası saniyesi saniyesine kayıtlı. **Ölçmeden düzeltme.**
2. `python testleri_calistir.py` → 554 test geçmeli (54 dosya).
3. Botu başlatmadan önce: `Enable-ScheduledTask -TaskName ASTRA_Bot`
   **UNUTMA** — Disabled bırakıldı. (§2: 2026-08-21'de tam bu yüzden
   14 saat veri kaybedilmişti.)

### NEREDE KALINDI — DÜRÜST ÖZET

**Kazanılan:** ölçüm zinciri artık güvenilir. Boru hattı uçtan uca
çalıştı — sinyal → veto zinciri → Binance testnet'te emir → SL+TP
borsada. İlk canlı emir 2026-09-15 00:17'de açıldı, ilk kapanış
ETHUSDT STOP −%1.81. Paper ile canlı aynı kapılardan geçiyor (§6.0
kapandı).

**Kazanılmayan:** stratejinin kâr ettiği. Sayaç 0/100 ve
**9 hipotez ölçülüp reddedildi** (§0.3–0.11, §0.15). 100 işlem "edge
yok" diyebilir — bu da geçerli bir sonuç olur. Fark şu ki artık o
sonuca İNANILABİLİR; iki hafta önce inanılamazdı (sayaç sahteydi,
örneklem canlıyı temsil etmiyordu, yedekler eksikti).

**Hedef hakkında:** günde $200, 10.000 USDT ile günde %2 demek —
sürdürülebilir değil. Ulaşılabilir ama sermaye sorusu (%30/yıl ile
~$240.000). Ayrıntı: hafızadaki `astra-kullanici-hedefi`.

### BU OTURUMUN KALICI DERSİ

20 kök neden çıktı (K-84…K-103) ve çoğu kodun içinde değil, **kodun
ÖLÇÜLDÜĞÜ yerde**ydi: kırmızıya dönemeyen testler, yanlış sebeple geçen
testler, dolu görünüp eksik olan yedekler (13'ünün hepsi), var olan ama
hiç kapanmayan kapılar, 29 kat şişik sayaçlar, borsa hesabı boş olduğu
için geçen testler.

§10 bunu zaten öngörmüştü: *"kör nokta genellikle kodun içinde değil,
kodun ölçüldüğü yerde duruyor."*

---

## 0.45 🔴 İKİNCİ GÖREV ATLANMIŞTI — `ASTRA_OrderBook` (2026-09-18)

Kullanıcı: *"Arada kendi kendine cmd açılıyor."*

### Bulgu

§0.44'te proje durdurulurken **yalnızca `ASTRA_Bot` devre dışı
bırakılmıştı.** Sistemde İKİNCİ bir zamanlanmış görev var:

```
ASTRA_OrderBook · Ready · LogonType=Interactive
  eylem   : baslat_orderbook.bat
  tetikler: logon + PT10M (10 DAKİKADA BİR)
```

`LogonType=Interactive` olduğu için her tetiklemede ekranda **cmd
penceresi açılıp kapanıyor.** `baslat_orderbook.bat` zaten "zaten
çalışıyor mu" kontrolü yapıp çıkıyor — pencere çoğu zaman boşuna.

⚠️ **DÜZELTME (2026-09-19) — YUKARIDAKİ ÖLÇÜMÜM YANLIŞTI.**
"Kaydedici sürekli çalışmıyor, her tetikleme bir tur toplayıp çıkıyor"
demiştim. YANLIŞ. Ölçümü bir BOŞLUKTA almışım (süreç yeni ölmüş,
watchdog henüz başlatmamıştı) ve tek bir anlık sayımdan yapısal sonuç
çıkarmıştım.

Gerçek (ölçüldü 2026-09-19 00:31):
```
PID 2112 · başlangıç 18.09 23:07:02 · hâlâ çalışıyor (1.5 saat)
orderbook.log son yazma: 00:27:49
```
➜ **Kaydedici UZUN ÖMÜRLÜ bir döngü.** 10 dakikalık görev yalnızca
WATCHDOG: her tetiklemede "zaten çalışıyor" deyip çıkıyor — yani
pencereyi BOŞUNA açıyor. Görevi kapatmak toplamayı DURDURMAZ; sadece
çökerse yeniden başlatan kalmaz.

💡 **DERS: tek anlık süreç sayımından yapısal sonuç çıkarma.** İki
farklı anda ölçseydim (veya süreç başlangıç zamanına baksaydım) hata
anında görünürdü. Bu oturumun tekrar eden dersi — ölçümün kendisi de
ölçülmeli.

### Yapılan

`baslat_orderbook_gizli.vbs` — `WScript.Shell.Run(..., 0, False)` ile
pencereyi hiç göstermeden aynı .bat'ı çalıştırır. Davranış değişmez.
**Test edildi:** kaydedici süreci 1 oldu, yaşam döngüsü log'u büyüdü,
ekranda hiçbir şey belirmedi.

### ⚠️ GÖREVİ YÖNLENDİRMEK YÖNETİCİ YETKİSİ İSTİYOR

`Set-ScheduledTask` (Principal ve Action için) **ve `Disable-ScheduledTask`**
— hepsi "Erişim engellendi" veriyor. `ASTRA_Bot`'tan FARKLI: o görev
kullanıcı tarafından oluşturulmuş, bu ise yönetici olarak. Yani bu
göreve yetkisiz HİÇBİR ŞEKİLDE dokunulamıyor.

**Kullanıcının YÖNETİCİ PowerShell'de çalıştırması gereken:**

```powershell
$a = New-ScheduledTaskAction -Execute "wscript.exe" `
     -Argument '"C:\Users\<KULLANICI>\Desktop\astra_v55\baslat_orderbook_gizli.vbs"' `
     -WorkingDirectory "C:\Users\<KULLANICI>\Desktop\astra_v55"
Set-ScheduledTask -TaskName ASTRA_OrderBook -Action $a
```

(Alternatif, yetkisiz: `Disable-ScheduledTask -TaskName ASTRA_OrderBook`
— pencere durur, order book toplama da durur.)

### 💡 DERS — "PROJEYİ DURDUR" DEDİĞİNDE TÜM GÖREVLERİ SAY

§0.44'te tek görevi durdurup "proje durduruldu" dedim. İkincisi 10
dakikada bir çalışmaya devam etti ve kullanıcı fark etti.

➜ Sonraki durdurmada projeye ait TÜM görevleri listele: `Get-ScheduledTask`
çıktısını eylem satırında "astra" geçenlere filtrele. K-91'in ("listeye
eklenmeyen test sessizce atlanır") işletim sistemi tarafındaki karşılığı.

---

## 0.44 ⏸️ PROJE DURDURULDU (2026-09-17 22:46) + 🔴 YENİ AYRIŞMA

Kullanıcı kararı: *"Projeyi şimdilik durduralım."*

### DURDURMA DURUMU

```
bot            : DURDURULDU · görev ASTRA_Bot = Disabled
zamanlanmış kontrol : devre dışı (astra-uc-olcum)
paper işlem    : 0/100
journal LIVE   : 11  (3 eski + 8 bu turda)
testnet bakiye : 5000 → 4947.27 USDT
```

⚠️ **TESTNET'TE İKİ POZİSYON AÇIK KALDI** — koruma emirleri BORSADA
duruyor, yani korumasız değiller. Ama bot kapalı olduğu için **zaman
stop işlemeyecek**; yalnızca SL/TP tetiklenirse kapanırlar.

```
ADAUSDT SHORT  -207.0 @ 0.19590  PnL -1.14  SL 0.2065  TP 0.1882
APTUSDT SHORT   -77.9 @ 0.55800  PnL -1.74  SL 0.5911  TP 0.5327
```
➜ Devam edilmeyecekse bunlar testnet arayüzünden elle kapatılabilir
(test parası, aciliyeti yok).

⚠️ `ASTRA_Bot` görevi **Disabled** bırakıldı. Devam ederken
`Enable-ScheduledTask` UNUTULMAMALI (§2: 2026-08-21'de tam bu yüzden
14 saat veri kaybedilmişti).

---

### 🔴 AÇIK KALAN EN ÖNEMLİ SORU — AYRIŞMA TERSİNE DÖNDÜ

13. sıfırlamadan (09-16 01:46) durdurmaya kadar ~45 saat:

```
canlı açılan : 5 emir   (SUIUSDT, TRUMPUSDT, DOGEUSDT, ADAUSDT, APTUSDT — hepsi SHORT)
paper açılan : 0
```

**Bütün oturum boyunca uğraştığımız ayrışmanın TERSİ.** Önce paper
canlıdan gevşekti (K-97/K-98/K-103 ile kapatıldı); şimdi paper canlıdan
SIKI ve hiç işlem açmıyor.

**KARAKTERİZE EDİLDİ (henüz çözülmedi):**

APTUSDT canlıda 09-17 03:30:08'de açıldı:
```
03:30:00  [EXEC ISLE] APTUSDT sinyal→emir gecikme=1.6s
03:30:08  [EXEC ISLE] ✅ ✅ APTUSDT SHORT @ 0.5580 SL:✓
```
Aynı turda paper'ın APTUSDT için **HİÇ LOG SATIRI YOK.** O aralıkta 124
`[PAPER]` satırı var ama hiçbiri APT değil.

➜ Paper yalnızca REDDEDERKEN veya AÇARKEN log yazıyor. Satır hiç yoksa
`sinyal_isle` ya çağrılmadı ya da **sessizce erken döndü** — §5.2'nin
tarif ettiği desen.

Paper'ın genel red dağılımı (395 satır, hata YOK):
```
132  AI skor -4 > -5 (VOLATILE) → ATLANDI
131  AI skor -3 > -5 (VOLATILE) → ATLANDI
 66  Güven %55 < %62 → ATLANDI
 33  mtf_cascade → ATLANDI
```

### ➜ SONRAKİ OTURUMUN İLK İŞİ

**`paper_trader.sinyal_isle()` neden bazı sembollerde sessizce dönüyor?**

`main.py`'de sıra: `sinyal_isle(sonuc)` → `stop_tp_kontrol(...)` →
`_execution_isle(sonuc)` — ikisi de AYNI `sonuc` nesnesini alıyor.
Aynı girdiyle canlı açıp paper açmıyorsa, paper'da canlıda olmayan bir
erken dönüş var.

Aday yerler (ölçülmedi, tahmin):
- `sinyal_isle` başındaki karar/yön ayrıştırma
- `MAX_SAME_DIRECTION` (aynı yön 7) — 5 SHORT'ta bağlamamalı ama kontrol et
- `yeniden_giris_beklemesi`
- `_pozisyon_ac` içinde sessiz `return`

⚠️ **ÖLÇMEDEN DÜZELTME.** Bu oturumun tekrar eden dersi: tahminle
değiştirilen her şey ya yanlış yeri düzeltti ya da yeni ayrışma doğurdu.
Önce APTUSDT gibi somut bir vakada `sinyal_isle`'ı adım adım sür.

⚠️ Ve unutma: örneklem ŞU AN GEÇERSİZ. Paper 0 işlem açtığı için
100 işlemlik hüküm hiç ilerlemiyor; canlı ise 5 işlem açtı ama
`karar_kurali.py` yalnızca `mod='PAPER'` okuyor (§0.39).

---

## 0.43 🔴 K-102 — STRATEJİ SEÇİMİ GİRİŞ KOŞULUNA BAKIYOR (2026-09-15)

§0.42'nin düzeltmesi. **Kullanıcı kararı**: *"36 gün çok uzun ve kazanç
da kesin değil, bu yüzden yapalım."*

### İLKE — ne değiştirildi, ne değiştirilmedi

**Giriş koşulunun sağlanamayacağı BİLİNEN bir strateji seçilmez.**

⚠️ **MR FİLTRESİNİN MANTIĞINA DOKUNULMADI.** O, mean reversion için
DOĞRU: aşırı satımda al, aşırı alımda sat. Yanlış olan, momentum
setup'ına onu DAYATMAKTI. Bu yüzden eşikler oynatılmadı, filtre
gevşetilmedi — yalnızca **SEÇİM** düzeltildi.

Bu ayrım önemli: §0 protokolü "sonuca bakıp eşik oynatma" der. Burada
sonuca bakılmadı; iki bileşenin yapısal uyumsuzluğu ölçüldü.

### Yapılan

`strateji_sec(rejim, mtf_skor, funding, sonuc=None)` — MEAN_REVERSION
seçilmeden önce `mean_reversion_uygun_mu(sonuc)` kontrol ediliyor.
Sağlanmıyorsa TREND_FOLLOW.

⚠️ **RANGE DALINA DA UYGULANDI.** Aynı hata orada da vardı; yalnızca
VOLATILE'i düzeltmek, bu oturumda K-97'yi K-98'in izlemek zorunda
kalmasının birebir tekrarı olurdu.

⚠️ **EŞİKLER TEK KAYNAK** (`MR_RSI_ALT/UST` modül sabiti): hem filtre
hem uygunluk kontrolü aynı değeri okuyor. Ayrı yazılsalardı seçici
"uygun" der, filtre reddeder ve sinyal yine ölürdü — bu kod tabanının
en sık tekrar eden hatası. Muhafızı eşiği DEĞİŞTİREREK doğruluyor
(§0.36'nın dersi: mevcut değerle tesadüfen eşleşen iddia ayırt etmez).

⚠️ `sonuc` opsiyonel — verilmezse eski davranış (geriye dönük uyum).

### ÖLÇÜLEN ETKİ (50 coin, anlık)

```
ESKİ: 14 MEAN_REVERSION +  2 TREND_FOLLOW  →  filtreyi geçen 0/16
YENİ:  0 MEAN_REVERSION + 16 TREND_FOLLOW  →  filtreyi geçen 4/16
```
`TREND_FOLLOW` reddetme sebepleri: hacim 8 · mtf 3 · adx 1 — yani
filtre hâlâ eliyor, kapı açılmadı, sadece DOĞRU kapıya yönlendirildi.

### Muhafız

`tests/test_strateji_secimi.py` (8 test). Kontrol testleri dahil:
gerçek MR setup'ında MR HÂLÂ seçilir (MR öldürülmedi) · diğer rejimler
değişmedi · GRID hâlâ çalışıyor · filtre mantığı aynı.
**Mutasyon 4/4** (eski hataya dön · MR'ı öldür · RANGE kontrolünü
kaldır · eşikleri filtrede sabitle).

**Koşucu: 543 → 551 test.**

### ✅ K-103 — `coklu_borsa` DA ORTAK (aynı turda kapatıldı)

Kullanıcı ilkeyi netleştirdi: *"sadece Binance verileri önemli; paper
dediğimiz şey aslında Binance futures için HAZIRLIK."*

⚠️ **KAPI YANLIŞ ANLAŞILMAYA AÇIK — ne yaptığı ölçüldü:**
Binance + Bybit + OKX fiyatlarının MEDYANI alınıyor; Binance ondan
>%1 sapıyorsa veto. Yani *"başka borsada işlem yap"* DEMİYOR —
**kimsenin görmediği bir Binance fiyatına güvenmiyor.** K-15'te tam bu
yaşanmıştı: testnet'te gerçek piyasada OLMAYAN sıçrama sahte "TP"
üretmişti. Diğer borsalara erişilemezse doğrulama atlanıyor.
➜ Kapı "sadece Binance önemli" ilkesiyle çelişmiyor, onu KORUYOR.

`futures_trade_engine.coklu_borsa_gecerli_mi()` — paper + canlı ortak.

⚠️ **FAIL-OPEN korundu** (canlının mevcut davranışı): OKX'in API'si
bozuk diye tüm işlemleri durdurmak yanlış olurdu; erişilemeyen borsa
durumu `karsilastir` içinde zaten ele alınıyor.
⚠️ Ama SESSİZ değil: canlıda `log.debug` ile yutuluyordu (§5.2 deseni),
`warning`'e yükseltildi.
⚠️ Ağ yükü yok: `multi_exchange` 3 sn önbellekli, paper ve canlı aynı
sembolde saniyeler içinde çalışıyor.

### ⚠️ TAKLİT NOKTASI ÜÇÜNCÜ KEZ KAYDI

Kapı ortak modüle taşınınca `Ortam` (canlı) ve `_paper_sahne` +
`test_izolasyon` (paper) koşum ortamları eski yeri taklit etmeye devam
etti → **6 test kırmızı, ikisi KONTROL testi** ("tüm kapılar açıkken
emir gönderilir").

Bu oturumda üçüncü tekrar (K-98 strateji motoru, K-103 çoklu borsa).
➜ **KURAL: bir kapıyı ortak modüle taşırken, onu taklit eden TÜM koşum
ortamları aynı commit'te güncellenmeli.** Aksi hâlde kontrol testleri
yanlış sebeple kırmızıya döner ve "kod bozuldu" sanılır.

**Koşucu: 551 → 554 test.**

### 🔴 SIFIRLAMA GEREKİYOR

Giriş davranışı değişti. Mevcut 2 işlem eski seçimle açıldı.

    Disable-ScheduledTask -TaskName ASTRA_Bot
    Stop-ScheduledTask    -TaskName ASTRA_Bot
    python sifirla_k37.py
    Enable-ScheduledTask  -TaskName ASTRA_Bot
    Start-ScheduledTask   -TaskName ASTRA_Bot

---

## 0.42 🔴 ÖLÇÜM — MEAN REVERSION FİLTRESİ AI İLE TERS ÇALIŞIYOR (2026-09-15)

Kullanıcı *"saatler geçti, işlem hâlâ 2"* dedi. 17.1 saatlik veri:
**2 işlem açıldı (2.8/gün), 9647 red, slotların 1/10'u dolu, 0 hata.**

⚠️ **YAVAŞLAMA DOĞRU VE BEKLENENDİ.** paper 2 · canlı 2 — TAM YAKINSADILAR
(journal LIVE 3→5). K-98 öncesi paper çok açıyor, canlı hiç açmıyordu.
Eski hızlı tempo paper'ın YANLIŞ olmasıydı; 2.8/gün botun gerçek hızı.

### Veto dağılımı (17.1 saat)

```
strateji_red   2690  %28   ← en büyük;  717'si "Mean reversion koşulu sağlanmadı"
edge_engine    2098  %22
guven_dusuk    1577  %16
ai_skor_dusuk  1379  %14
coklu_borsa     347  %4    ← CANLI-ÖZEL (aşağıda)
```

### 🔴 BULGU: FİLTRE, AI'IN ÜRETTİĞİNİN TERSİNİ İSTİYOR

`strategy_engine.py:50` — VOLATILE rejimde KOŞULSUZ `MEAN_REVERSION`
seçiliyor. Piyasa **48/50 VOLATILE**, yani neredeyse her sinyal tek bir
filtreye giriyor:

```python
if "BUY"  in karar and rsi < 30:  return True
if "SELL" in karar and rsi > 70:  return True
return False
```

**ÖLÇÜLDÜ — 1824 gerçek reddin RSI dağılımı:**
```
min 29.0 · medyan 36.9 · max 51.1 · ortalama 37.8

RSI > 70 (SELL şartı) :    0 / 1824   %0.0    ← HİÇ OLMADI
RSI < 30 (BUY şartı)  :  478 / 1824   %26.2
30-70 arası           : 1346 / 1824   %73.8
```

**SELL dalı 1824 vakada BİR KEZ BİLE sağlanabilir olmadı** — RSI 51.1'i
hiç aşmadı, 70'i geçmek şöyle dursun.

**Anlık kesit de aynı yöne işaret ediyor (50 coin):**
```
AI BUY  derken RSI ortalama 53.9  → eşik <30   (ters yönde, 24 puan uzak)
AI SELL derken RSI ortalama 40.8  → eşik >70   (ters yönde, 29 puan uzak)
AI kararı ile RSI şartının KESİŞTİĞİ coin: 0/50
```

### ➜ YORUM: İKİ FARKLI FELSEFE ÇARPIŞIYOR

- **AI momentum modeli**: güç görünce BUY, zayıflık görünce SELL.
  (SELL sinyallerinin RSI'si DÜŞÜK — 478'i 30'un altında.)
- **Filtre mean reversion**: aşırı satımda BUY, aşırı alımda SELL.

İkisi **taban tabana zıt.** Filtre "nadiren geçiyor" değil, düşen
piyasada SELL tarafı **yapısal olarak imkânsız**: AI zayıflıkta SELL
diyor, filtre ise aşırı alım istiyor.

➜ 478 sinyal (RSI<30) momentum mantığıyla SELL olarak geçerdi;
mean reversion mantığıyla 0'ı geçti.

**K-11 ile aynı sınıf:** gerekçesi yazılmamış bir tasarım tercihi,
sistemin davranışını yapısal olarak tersine çeviriyor.

### 🟡 İKİNCİ BULGU — `coklu_borsa` AYRIŞMASI GERİ GELDİ

K-98'de *"0 ateşleme"* diye paper'a eklenmemişti. Artık **347 kez**
ateşliyor (%4) → paper hâlâ %4 daha gevşek. Gerekçem geçersizleşti.
*"Şu an ateşlemiyor" kalıcı bir gerekçe değilmiş* — koşullar değişince
ayrışma geri geliyor.

### ⚠️ HİÇBİR ŞEY DEĞİŞTİRİLMEDİ

§0 protokolü: 100 işlem dolmadan eşik/mantık değiştirmek hükmü geçersiz
kılar. Bu bir ÖLÇÜM kaydıdır.

**Karar bekleyen seçenekler:**

| seçenek | gerekçe | risk |
|---|---|---|
| VOLATILE'de strateji seçimini gözden geçir | %96 piyasa tek filtreye giriyor | strateji kararı + sıfırlama |
| MR filtresini AI'ın yönüyle hizala | AI momentum, filtre MR — ters | aynı |
| `coklu_borsa`'yı paper'a ekle | §5.3 ayrışması | küçük, sıfırlama |
| Dokunma, 36 gün bekle | protokole sadık | 2.8/gün → 100 işlem ~36 gün |

⚠️ Bu bulgu "edge yok" sonucunun erken habercisi OLABİLİR — ama olmayabilir
de: filtre AI'ı sistematik olarak engelliyorsa, ölçtüğümüz şey stratejinin
becerisi değil, iki bileşenin uyumsuzluğudur. **Ayırt etmek için filtre
düzeltilmeden toplanan 100 işlem yanıltıcı olur.**

---

## 0.41 🎉 İLK CANLI EMİR AÇILDI + K-99/K-100/K-101 (2026-09-15)

### 🎉 SAHADA İLK CANLI EMİR — 00:17:27

```
[EXEC ISLE] ✅ ETHUSDT LONG @ 2552.2375  slip:%0.002  (15.2s)

TESTNET hesabı (kullanıcı arayüzden TEYİT ETTİ):
  ETHUSDT LONG · 0.036 · giriş 2552.2375 · 3x · likidasyon 1709.54
  STOP_MARKET        @ 2508.92  closePosition=true
  TAKE_PROFIT_MARKET @ 2609.79  qty 0.018 (kısmi)
  bakiye 5000 → 4968.92 USDT
journal LIVE: 3 → 4
```

**Aynı anda paper da ETHUSDT açtı** (`[PAPER] ETHUSDT LONG @ 2549.19`).
İlk kez iki yol AYNI sinyalde AYNI kararı verdi — K-97/K-98'in amacı.

⚠️ Log'daki `TP:✗` anlık bayraktı; TP 1 sn sonra kondu, reconciler
"TP kayıp → yeniden koyuldu" deyip doğruladı. Pozisyon tam korumalı.

⚠️ **NE KANITLANDI, NE KANITLANMADI.** Kanıtlanan: boru hattı uçtan uca
çalışıyor (sinyal → veto zinciri → emir → borsada pozisyon → SL+TP
duruyor). Kanıtlanmayan: stratejinin kâr ettiği. O soru hâlâ 0/100.

⚠️ **KULLANICI "POZİSYON GÖRÜNMÜYOR" DEDİ — YANLIŞ HESABA BAKIYORDU.**
Bot `testnet.binancefuture.com`'da; gerçek `binance.com` hesabı bu işten
habersiz ve hep boş görünecek. Sonraki oturumda aynı soru gelirse önce
bunu sor. Teyit için: giriş 2552.24 · 3x · likidasyon 1709.54 · cüzdan
4968.92 eşleşmeli.

---

### 🔴 K-99 — RECONCILER OLMAYAN METODU ÇAĞIRIYORDU

Sahada 00:17:17'de patladı:
```
[ERROR] [RECONCILER] sync_open_positions BAŞARISIZ:
        'PositionStateManager' object has no attribute 'pozisyon_ekle'
        — pozisyon tutarlılığı doğrulanamadı!
```

`order_reconciler.py:108` `self._state.pozisyon_ekle({...})` çağırıyordu.
**K-8/v57 bu hatayı `execution/execution_engine.py`'de bulup düzeltmiş ve
doğru imzayı oraya yazmıştı — BURADAKİ kopya atlanmıştı.** "Bir yerde
düzeltilip diğerinde unutulan" deseninin kaçıncı tekrarı olduğu artık
sayılmıyor (K-13, K-69, K-78, K-86, K-89, K-95, K-97, K-98...).

Etkisi: borsada AÇIK ama state'te YOK olan pozisyon state'e HİÇ
eklenmiyordu → `sl_tp_dogrula()` onu görmüyor → SL/TP'si doğrulanmıyor.
Reconciler'ın tek işi yapılmıyordu. (v55 sayesinde en azından GÖRÜNÜR.)

**Düzeltme:** doğru API `pozisyon_ac(sembol, yon, giris, miktar, sl, tp1,
kaldirac, order_id)` — dict değil konumlu argümanlar.
⚠️ SL/TP **0.0** geçiliyor: orphan'ın koruma emirleri BİLİNMİYOR; uydurma
seviye yazmak olmayan korumayı VAR göstermek olurdu (§5.1).

**Muhafız:** `tests/test_reconciler_state.py` (4 test), mutasyon 1/1.

---

### 🔴 K-100 — `STATE_FILE` İZOLE EDİLMİYORDU

`data/position_state.json` `URETIM_YOLLARI` listesindeydi (kirlilik
denetimi onu sayıyordu) ama `izole_et()` env'ini KURMUYORDU.
`config.STATE_FILE` zaten `os.getenv(...)` idi — yönlendirilebilirdi,
sadece yönlendirilmemişti.

➜ **§4.6'nın YARIM uygulanmış hâli:** *"listeye ekle VE izole_et() içine
ekle"*. İlki yapılmış, ikincisi unutulmuş. Testler üretim pozisyon
state'ini okuyup YAZABİLİYORDU.

---

### 🔴 K-101 — TESTLER GERÇEK BORSAYI SORGULUYORDU

İlk canlı emir açılınca **6 test birden kırmızıya döndü**
("pozisyon yokken 1 döndü", "kaynak 'FUTURES' — paper modda PAPER olmalı").

Sebep: `test_pozisyon_kaynagi.py` ve `test_veri_tutarliligi.py`
`main.acik_pozisyonlar_birlesik()` çağırıyor, o da CANLI borsaya gidiyor
— ve bu dosyalarda **hiç taklit yoktu**. Yani testler sessizce
*"testnet hesabı BOŞ"* varsayımına dayanıyordu.

➜ **Testler kusurluydu, kod değil.** Borsa hesabı da ÜRETİM durumudur.
**Hesapta pozisyon varken kırılan test, guard değildir** — dış dünyanın
anlık hâline bağlı bir test ne koruduğunu bilmiyor demektir.

**Düzeltme:** `_borsayi_izole_et()` yardımcısı, iki dosyada da
`acik_futures_pozisyonlar` taklit ediliyor.

⚠️ Bu hata sınıfı bugün İKİ KEZ çıktı (K-100 state dosyası, K-101 borsa).
Yeni bir dış bağımlılık eklenirken §4.6 kontrol listesi baştan sona
uygulanmalı: *env ile yönlendirilebilir mi · URETIM_YOLLARI'nda mı ·
izole_et() kuruyor mu · testler onu taklit ediyor mu.*

**Koşucu: 539 → 543 test.**

---

## 0.40 🔴 K-98 — AYRIŞMA TAM KAPANDI (strateji + sinyal filtresi + kill switch)

K-97 üç kapıyı ortaklaştırdı ama ayrışma **bir kapı aşağıda sürüyordu.**
Kullanıcı *"PAXGUSDT'den pozisyon açılmış ama order history boştu"* dedi;
K-97 sonrası açılan İLK paper işlemi bunu ortaya çıkardı:

```
paper : PAXGUSDT SHORT açıldı (2026-09-14 19:21)
canlı : [EXEC ISLE] PAXGUSDT: Trend follow koşulu sağlanmadı  ← REDDEDİYOR
```

### ÖNCE TAM DENETİM — dördüncü tur olmasın

Canlı zincirdeki HER kapı tek tek ölçüldü (sıra + ateşleme sayısı +
paper'da karşılığı var mı):

| kapı | ateşleme | paper'da | karar |
|---|---|---|---|
| slippage_gec_giris | 215 | ✅ (K-95) | — |
| kill_switch | 0 | ❌ **besliyor ama OKUMUYOR** | **EKLENDİ** |
| circuit_breaker | 0 | ❌ | bırakıldı — gerçek emir hatalarını sayar, paper'da emir yok |
| coklu_borsa | 0 | ❌ | bırakıldı — ağ isteği gerektirir, 0 ateşleme |
| validator_dayaniklilik | 0 | ❌ | bırakıldı — `_strateji_onay` main.py durumu, 0 ateşleme |
| korelasyon | 0 | ✅ farklı uygulama (`MAX_SAME_DIRECTION`) | bırakıldı |
| MTF/edge | 1118 | ✅ (K-97) | — |
| **strateji_red** | **804** | ❌ | **TAŞINDI** |
| **sinyal_filtresi** | 0 (MASKELİ) | ❌ girişte | **TAŞINDI** |

⚠️ `sinyal_filtresi`'nin 0 olması "ateşlemiyor" DEĞİL **maskeleme**ydi:
zincirde `strateji_red`'den SONRA geliyor, sinyaller ona ulaşmadan
ölüyordu. Sayaç sıfırına bakıp "gereksiz" demek hata olurdu.

⚠️ Bırakılan dördü için gerekçe YAZILDI — sessizce atlanmadı. Hiçbiri
şu an ateşlemiyor; ateşlemeye başlarlarsa aynı sınıf ayrışma doğar.

### Yapılan

- `sinyal_veto_zinciri(sonuc, yon, bakiye_fn=None)` — sıra artık:
  **MTF cascade → MTF hizalama → EdgeEngine → strateji → sinyal filtresi**
- Paper'a **kill switch kontrolü** eklendi. Paper switch'i BESLİYORDU
  (`trade_sonucu_bildir`) ama hiç OKUMUYORDU: tetiklenince canlı durur,
  paper işlem açmaya devam ederdi. *Besleyip okumamak, sayaç tutup
  bakmamaktır.*

⚠️ **`bakiye_fn` TEMBEL.** Strateji motoru bakiye istiyor; peşinen
çekmek MTF/edge'de zaten ölecek her sinyal için REST isteği demekti
(v55'te bilerek kaldırılan maliyet, üstelik zaten HTTP 429 alıyoruz).
Çağrı strateji kapısına ULAŞILIRSA yapılıyor. Muhafızı var
(`test_bakiye_TEMBEL_cagriliyor`), mutasyonla doğrulandı.

⚠️ Bakiye okunamazsa **fail-CLOSED** — strateji kapısı atlanamaz.

### ⚠️ TEST KOŞUM ORTAMI KAYDI — 4 test kırıldı, ikisi KONTROL testiydi

`test_veto_zinciri.Ortam` `main._strategy_engine`'i taklit ediyordu; kapı
`futures_trade_engine`'e taşınınca **taklit noktası kaydı** ve gerçek
motor devreye girdi. Kırılanlar arasında §4.1'in çekirdek kontrol testi
vardı: *"tüm kapılar açıkken emir gönderilir"*.

**Kritik ayrıntı:** senkronizasyon `Ortam.__enter__`'ın SONUNA, kwargs
uygulandıktan SONRA konuldu. Önce yapılsaydı `Ortam(_strategy_engine=red)`
ile kurulan "strateji reddetti" testi varsayılan (izin veren) motorla
çalışır ve **yanlış sebeple** geçerdi.

Paper testleri için `_paper_sahne` motoru izin verir hâle getiriyor —
o testlerin konusu paper filtre zinciri, strateji motoru değil (canlı
tarafta `Ortam` da aynısını yapıyor).

### ⚠️ KENDİ TESTİMİN İKİ KUSURU

1. **`sinyal_gecerli_mi` mutasyonu KAÇTI** — tüm fikstürlerim
   ai=9/conf=95 ile o kapıdan zaten geçiyordu. *Bir kapıyı test etmek
   için o kapının TEK BAŞINA reddedeceği bir girdi gerekir;* aksi hâlde
   kapı silinse de testler yeşil kalır. Zayıf sinyal testi eklendi.
2. Fikstürüm minimal olduğu için yeni kapı 4 testi kırdı — kusur kodda
   değil fikstürdeydi (§0.1, bu oturumda üçüncü kez).

**Muhafız:** `tests/test_veto_zinciri_ortak.py` 11 → **17 test**,
mutasyon **5/5** (strateji öldür · sinyal filtresi öldür · bakiyeyi
erken çek · bakiye hatasında fail-open · paper kill switch atlasın).

**Koşucu: 533 → 539 test.**

### 🔴 SIFIRLAMA GEREKİYOR

Paper'ın giriş davranışı yine değişti. Mevcut 1 işlem (PAXGUSDT) eski
davranışla açıldı — canlının reddettiği işlemdi, yeni zincirden geçemezdi.

    Disable-ScheduledTask -TaskName ASTRA_Bot
    Stop-ScheduledTask    -TaskName ASTRA_Bot
    python sifirla_k37.py
    Enable-ScheduledTask  -TaskName ASTRA_Bot
    Start-ScheduledTask   -TaskName ASTRA_Bot

---

## 0.39 🔴 K-97 — VETO ZİNCİRİ ORTAK MODÜLE ÇIKARILDI (§6.0 KAPANDI)

Kullanıcı *"2 işlem açılmış ama Binance order kısmında göremedim"* dedi.
İnceleme §6.0'ın v58'den beri açık duran işini ortaya çıkardı.

### Kullanıcının sorusunun cevabı

İki işlem de `mod='PAPER'` — yerel simülasyon, borsaya hiç gitmedi.
Ama ASIL bulgu, canlı yolun AYNI sinyali reddetmiş olması:

```
07:15:13.392  [TRADE AÇILDI] #1 ASTERUSDT          ← paper AÇTI
07:15:14.640  [EXEC ISLE] ASTERUSDT MTF hizalama yok → atlandı
07:16:01.493  [TRADE AÇILDI] #2 AAVEUSDT           ← paper AÇTI
07:16:02.776  [EXEC ISLE] AAVEUSDT MTF hizalama yok → atlandı
```
**Aynı sembol, aynı saniye: paper açtı, canlı reddetti.**

(Veto sebebi doğruydu: her iki coinde de 1w/1d/4h ÜÇÜ DE NÖTR → skor 0.
K-96 bunu bilerek koruyor, `test_TUM_TF_NOTRSE_skor_0_KALIR` kilitliyor.)

### Kök neden

MTF cascade + MTF hizalama + EdgeEngine `main.py::_execution_isle`
içine gömülüydü; o fonksiyon `if not LIVE_TRADING: return` ile
başlıyor ➜ **bu üç kapı paper yolunda HİÇ ÇALIŞMIYORDU.**

➜ Paper, canlının REDDEDECEĞİ işlemleri açıyordu. Toplanan 100
işlemlik örneklem canlıyı TEMSİL ETMİYORDU — §5.3'ün tam olarak
önlemek için var olduğu durum, ve §6.0'ın işi.

### Yapılan

`futures_trade_engine.sinyal_veto_zinciri(sonuc, yon)` →
`(gecti, sebep, carpan)`. Paper ve canlı AYNI fonksiyonu çağırıyor.

⚠️ **CANLI DAVRANIŞ DEĞİŞMEDİ**: sıra (cascade → hizalama → edge),
eşikler ve varsayılanlar birebir taşındı. Loglama `[EXEC ISLE]`
etiketiyle canlıda kaldı.

⚠️ **VARSAYILANLAR KORUNDU**: `hizalama_skoru` yoksa 2 (veto YOK),
`edge_sonuc` yoksa `gecti=False` (VETO). İkisi de canlının eski
davranışı; birini çevirmek sessiz davranış değişikliği olurdu.

⚠️ **ÇARPAN DA EŞİTLENDİ**: zayıf hizalamada (skor 1) canlı pozisyonu
%60'a indiriyordu; paper da indiriyor. Vetoyu eşitleyip boyutu ayrık
bırakmak §5.3'ü yarım kapatmak olurdu.

⚠️ Paper tarafında zincir çağrısı **fail-CLOSED** sarılı: değerlendirme
patlarsa işlem AÇILMAZ (canlı bu kapıları uyguluyorken paper'ın
atlaması ihlalin ta kendisi olurdu).

### ⚠️ AYNI TUZAĞA ÜÇÜNCÜ KEZ: import satırı testi kandırdı

İlk muhafızım `"sinyal_veto_zinciri" in kod` arıyordu. Paper'ın
ÇAĞRISINI sabit `True` ile değiştiren mutasyon **YAKALANMADI** —
çünkü ad İMPORT SATIRINDA da geçiyor.

§0.29'da K-86 için birebir aynısı yazılmıştı: *"islem_kaldiraci
KELİMESİNİ arıyordu, import satırında da geçtiği için mutasyon
yakalanmadı."* Aynı hata deseni bu oturumda **dördüncü** kez.

**Düzeltme:** paper tarafı DAVRANIŞSAL teste çevrildi — gerçek
`_filtre_gec` sürülüyor, vetolu sinyalde `False` dönmeli. main.py
tarafında ad yerine **ATAMA** (`= sinyal_veto_zinciri(`) aranıyor.
Mutasyon sonra **6/6**.

### ⚠️ 7 MEVCUT TEST KIRILDI — ve kırılmaları DOĞRUYDU

Fikstürlerinde `edge_sonuc`/`mtf_confluence` yoktu; zincir fail-closed
davranınca hepsi vetolandı.

**Kapıyı değil FİKSTÜRÜ düzelttim.** Gerekçe ölçüldü: `coin_analiz`
ikisini de KOŞULSUZ üretiyor (canlı veride 50/50 coin). Yani o alanlar
olmadan bir `sonuc` **üretimde imkânsızdır** — fikstürler gerçek
olmayan bir durumu test ediyordu.

➜ §0.1'in dersi birebir: *"Gerçekçi olmayan test fikstürü, gerçek bir
kapıyı test edilemez kılar. Fikstür üretimdeki kurala uymalı."*

Düzeltilen: `test_cekirdek` (3), `test_izolasyon` (3),
`test_paper_canli_sl`, `test_yeniden_giris`, `test_giris_fiyati`.

### Muhafız

`tests/test_veto_zinciri_ortak.py` (11 test). Kontrol testleri dahil:
temiz sinyal GEÇER (zincir her şeyi kesmiyor) · eksik edge fail-closed ·
eksik hizalama eski varsayılanı korur · sıra cascade önce.
**Mutasyon 6/6** — cascade öldür · edge fail-open · çarpanı kaldır ·
hep veto · paper zinciri atlasın · paper çarpanı uygulamasın.

**Koşucu: 522 → 533 test.**

### ✅ 12. SIFIRLAMA YAPILDI (2026-09-14 14:20)

Paper'ın GİRİŞ davranışı değişti; mevcut 2 işlem (ASTERUSDT, AAVEUSDT)
eski davranışla açılmıştı — ikisi de yeni zincirden geçemezdi.

```
Yedek : data/_yedek_k37_20260914_142008   (2/2 işlem TAM — K-92 yine tuttu)
trades PAPER : 2 → 0   ·   journal LIVE 3 KORUNDU
```
Bot 14:20:36'da yeni kodla başlatıldı, 0 hata. Sayaç 0/100.

⚠️ Dünkü ders uygulandı: `Disable-ScheduledTask` ÖNCE (10 dk'lık tekrar
tetikleyicisi botu geri getiriyor), sonra `Enable` UNUTULMADI.

### ⚠️ BEKLENTİ: PAPER ARTIK DAHA YAVAŞ İŞLEM AÇACAK

Paper artık canlının reddettiği sinyalleri de reddediyor. 100 işlem
daha yavaş birikecek — ama biriken veri NİHAYET canlıyı temsil edecek.
Hükmün geçerli olması için şart olan buydu. Tempo düştü diye zinciri
gevşetmek, düzeltilen şeyi geri almak olur.

---

## 0.38 🔴 K-96 — MTF HİZALAMA SKORU DÜZELTİLDİ (2026-09-13)

§0.35 Bulgu 1'in düzeltmesi. **Kullanıcı kararı.**

### Hata

Referans KOŞULSUZ `ana_trend_yon` (taban+1, yani 1d) idi ve döngü
`if ana_trend_yon != "NÖTR" ...` ile korunuyordu. 1d NÖTR olduğunda
`hizali_tf` KOŞULSUZ boş kalıyor, skor **her zaman 0** çıkıyor ve
main.py bunu "MTF hizalama yok" diye VETO ediyordu.

```
ÖLÇÜLDÜ (50 coin): hizalama_skoru==0 : 17     ana_trend NÖTR : 17
                   ← BİREBİR AYNI KÜME
```
Veto "hizalama yok" değil **"1d'nin yönü yok"** demekti. Docstring
"kaç TF hizalı" diyordu; isim ve davranış ayrışmıştı.

### Düzeltme — hiyerarşik iniş

Ana trend TF'si susmuşsa referans HİYERARŞİDE AŞAĞI iner (bir sonraki
otorite: işlem barının kendisi). Ana trend yön bildiriyorsa DEĞİŞİKLİK YOK.

⚠️ **ÇOĞUNLUK OYU KULLANILMADI.** İlk aklıma gelen "yön bildiren TF'lerin
çoğunluğu" idi; ama `1w=LONG · 4h=SHORT` beraberliğinde
`Counter.most_common` EKLEME SIRASINA göre keyfi seçer — kararmış gibi
görünen bir rastgelelik olurdu. Ölçümde tam bu vaka çıktı (BTCUSDT).
Hiyerarşik iniş deterministik.

⚠️ **`bloklu` DOKUNULMADI** — cascade'in çekirdeği "üst TF'ye karşı işlem
açma"dır; üst TF'nin görüşü yoksa karşı çıkılacak şey de yoktur.

### SAHADA DOĞRULANDI (bot 19:42'de yeni kodla başladı)

```
ana_trend NÖTR olan coin : 5
bunlardan skoru 0        : 0      ← K-96 ÖNCESİ 5'i de 0 olurdu (veto)

PROMUSDT skor=2 {1w:LONG, 1d:NÖTR, 4h:LONG}   ← tam hizalama, TAM pozisyon
BTCUSDT  skor=1 {1w:LONG, 1d:NÖTR, 4h:SHORT}  ← çelişkili, %60 pozisyon
```
Hedeflenen davranış: gerçek confluence tam geçer, çelişkili olan veto
yerine YARIM pozisyona düşer.

### ⚠️ FİKSTÜR HATASI — üç test YANLIŞ SEBEPLE kırmızı döndü

İlk denemede sahte OHLCV üretip `_tf_analiz`'in ondan "NÖTR" çıkarmasını
ummuştum. Çıkarmadı: yatay+salınımlı serim RSI 100 ile **LONG** okundu.
Üç test birden patladı ama kusur KODDA DEĞİL, FİKSTÜRDEYDİ.

**Düzeltme:** `_tf_analiz` stub'landı. Doğru sınır bu: değiştirdiğim şey
`mtf_confluence_skoru`'nun HİZALAMA MANTIĞI; `_tf_analiz` onun ALTINDAKİ
katman. Mantık gerçek kodla sürülüyor, kontrol edemediğim gösterge
davranışı dışarıda kalıyor.

➜ §0.1'in dersi tekrar: *gerçekçi olmayan fikstür, gerçek bir kapıyı test
edilemez kılar.* Ama bu sefer tersi de doğru çıktı — **fikstür gerçeğe
UYDURULAMAYACAKSA doğru katmanı taklit et.**

### Muhafız

`tests/test_mtf_hizalama.py` (6 test), hepsi DAVRANIŞSAL. Kontrol testleri:
tüm TF nötrse skor 0 KALIR (kapı açılmadı) · ana trend yönlüyse davranış
DEĞİŞMEDİ · cascade bloğu hâlâ çalışıyor · ana trend nötrken blok atmaz.
**Mutasyon 4/4.**

### ✅ SIFIRLAMA GEREKMEDİ — maliyeti sıfır yakalandı

Davranış değişikliği, normalde §5.3 sıfırlaması gerektirirdi. Ama 11.
sıfırlamadan (19:31) beri **0 işlem** açılmıştı ve bot değişiklikten
11 dakika sonra yeniden başlatıldı. Geçersiz kılınacak veri yoktu.

➜ **Ders: davranış değişikliğini örneklem BOŞKEN yap.** Sıfırlamadan
hemen sonraki pencere bedavadır; 50 işlem sonra aynı değişiklik 50
işlemi çöpe atardı.

**Koşucu: 516 → 522 test.**

---

## 0.37 🔴 K-95 — SLİPAJ TAVANI ATR İLE ÖLÇEKLENDİ (2026-09-13)

§0.35 Bulgu 2'nin düzeltmesi. **Kullanıcı kararı** — protokol uyarısı
(sıfırlama + hükmü etkiler) verildikten sonra istendi.

### Değişen

```
ÖNCE : eşik = min(0.35 + ATR%×0.15,  0.70)          ← tavan MUTLAK
SONRA: eşik = min(0.35 + ATR%×0.15,  max(0.70, ATR%×SL_ÇARPAN×1/3))
```

**Tavan bir çalışma noktası değil, akıl-sağlığı sınırıdır.** Normal ATR
aralığında bağlayıcı olan asıl uyarlama terimidir; tavan yalnızca
bozuk/absürt ATR'ye karşı.

**ANKRAJ — sayı fitlenmedi:** stop mesafesi `FUTURES_SL_ATR_MULT × ATR`.
Girişten ÖNCE bu mesafenin en fazla **1/3'ünü** vermeyi kabul ediyoruz;
fazlası işlem daha açılmadan R/R'ı bozar (K-11 ile aynı mantık).
Tavan SL ÇARPANINDAN türüyor — SL politikası değişirse peşinden gelir
(K-82/K-83 sınıfı bayatlamayı önler).

### ÖLÇÜLEN ETKİ (gerçek log + anlık ATR)

```
tavana dayanan coin : 27/50 (%54)  →  0/33
97 geç-giriş iptali :  14'ü artık GEÇERDİ (%14) · 83'ü hâlâ reddedilir

PROMUSDT ATR%4.65 : 0.70 → 1.05  (+%50)
ZECUSDT  ATR%3.71 : 0.70 → 0.91  (+%29)
BTCUSDT  ATR%0.86 : 0.48 → 0.48  (değişmedi)
PAXGUSDT ATR%0.41 : 0.41 → 0.41  (değişmedi)
```
➜ Hedefli: yalnızca tavanın kırptığı oynak coinleri etkiliyor, sakin
coinlerde davranış AYNI. FORMUSDT'nin %2.07 kayması HÂLÂ reddediliyor —
bu "her şeyi kabul et" değil.

### ⚠️ PAPER'DA İKİNCİ KOPYA BULUNDU — az kalsın ayrışıyordu

`paper_trading.py:346` formülün AYNISINI ikinci kez yazıyordu ve
docstring'i *"Eşik canlıyla aynı formül"* diye SÖZ VERİYORDU. Yalnızca
canlı taraf değiştirilseydi iki yol ayrışır, o söz sessizce yalan
olurdu — K-13/K-69/K-78/K-85/K-86 deseninin yedinci tekrarı.

**Düzeltme:** hesap `futures_trade_engine.giris_kayma_esigi()`'ye
çıkarıldı; paper VE canlı aynı fonksiyonu çağırıyor. Ayrıca ayrı
fonksiyon olması DAVRANIŞSAL teste açtı — gömülü hâlde yalnızca kaynak
metni aranabiliyordu, ki bu oturum o yöntemin üç kez yetersiz kaldığını
gösterdi.

### ⚠️ MEVCUT BİR TEST KIRILDI — ve kırılması DOĞRUYDU

`test_paper_da_gec_giris_korumasi_var` (K-31) `paper_trading.py` içinde
**`MAX_GIRIS_KAYMA_PCT` metnini** arıyordu. Doğrudan import ortak
fonksiyonla değişince kırmızıya döndü — oysa koruma zayıflamadı,
GÜÇLENDİ (tek kaynak).

➜ Test uygulama DETAYINA bağlıydı, sözleşmeye değil. Sözleşme şu: eşik
ya ortak fonksiyondan ya config'ten gelmeli, ELDE SABİT YAZILMAMALI.
Öyle güncellendi. Mutasyonla doğrulandı: korumayı tamamen kaldırınca
3 test birden kırmızı (ikisi davranışsal).

**Ders:** "yeşil testi kırmayan değişiklik iyidir" kadar, "iyi bir
değişikliği kıran test gözden geçirilmelidir" de geçerli. Kırmızıyı
körü körüne düzeltmek kadar körü körüne kabul etmek de yanlış.

### Muhafız

`tests/test_giris_kayma_esigi.py` (8 test) — hepsi DAVRANIŞSAL.
Kontrol testleri dahil: düşük ATR'de DEĞİŞMEMELİ · eşik hâlâ SINIRLI ·
büyük kayma hâlâ reddedilir · paper ve canlı aynı kaynak.
**Mutasyon 4/4** (eski mutlak tavan · tavanı kaldır · SL çarpanını
sabitle · bozuk ATR'de tabanı kaldır).

⚠️ Bu testi de iki kez yanlış yazdım: (1) ATR=500 seçmiştim ama orada
tavan hiçbir çarpanda BAĞLAMIYOR — kusur testin ÖNCÜLÜNDEYDİ, kodda
değil. Tavanın fiilen bağladığı ATR=10 ile düzeltildi. (2) açıklama
metnim docstring dışında kalıp SyntaxError verdi.

**Koşucu: 508 → 516 test.**

### ✅ 11. SIFIRLAMA YAPILDI (2026-09-13 19:31)

```
Yedek : data/_yedek_k37_20260913_193115
trades PAPER  : 8 → 0   ·   journal PAPER : 8 → 0 (LIVE 3 KORUNDU)
452 model dosyası silindi · position_state.json silindi
4h_baslangic.json tazelendi
```

Sayaç 0/100. Bot 19:31:44'te yeni eşikle başlatıldı, 0 hata.

### 🟢 K-92 SAHADA DOĞRULANDI — WAL düzeltmesinden sonraki İLK yedek

```
yedekteki PAPER işlem : 8/8        ← hiç kayıp yok
yedekteki astra.db    : 19:31      ← yedeğin alındığı DAKİKA
karşılaştırma (10. sıfırlama, düzeltme ÖNCESİ):
   dizin 15:02'de oluştu, içindeki dosya 14:35 tarihliydi
```
Eski yöntemde dosya, yedekleme saatinden saatlerce eskiydi. Artık değil.

### 🔴 YENİ BULGU — `Stop-ScheduledTask` TEK BAŞINA YETMİYOR

Sıfırlama ilk denemede *"✗ BOT ÇALIŞIYOR"* ile reddedildi — oysa bot
durdurulmuştu. Sebep:

```
LastRunTime : 19:27:10
NextRunTime : 19:37:09     ← görevde 10 DAKİKALIK TEKRAR TETİKLEYİCİSİ
```

`ASTRA_Bot` görevi 10 dakikada bir kendini yeniden başlatıyor (oto-kurtarma,
§2). `Stop-ScheduledTask` yalnızca O ANKİ örneği durdurur; tetikleyici
botu geri getirir.

**DOĞRU SIRA:**
```powershell
Disable-ScheduledTask -TaskName ASTRA_Bot     # tetikleyiciyi sustur
Stop-ScheduledTask    -TaskName ASTRA_Bot
# (gerekirse süreci Stop-Process ile sonlandır)
python sifirla_k37.py
Enable-ScheduledTask  -TaskName ASTRA_Bot     # ⚠️ UNUTULURSA BOT HİÇ BAŞLAMAZ
Start-ScheduledTask   -TaskName ASTRA_Bot
```

⚠️ **`Enable` adımını atlamak sessiz veri kaybıdır.** §2'de kayıtlı:
2026-08-21'de bot yeniden başlamadığı için **14 saat** veri kaybedilmiş
ve kimse fark etmemişti.

🟢 **Yan fayda: K-93 düzeltmesi SAHADA İŞE YARADI.** Eski bozuk kapı
"bot yok" deyip çalışan botun altından veriyi silecekti — tam da
korumak için yazıldığı yarış durumu. Yeni kapı gerçek botu gördü,
reddetti, ve kullanıcı doğru sırayı uyguladıktan sonra izin verdi.

---

## 0.36 K-94 — MTF VETO MESAJI HİYERARŞİDEN TÜRETİLDİ (2026-09-13)

§0.35 Bulgu 3'ün düzeltmesi. Kullanıcı istedi (davranış değişmez,
sıfırlama gerekmez).

```
ÖNCE : "ZECUSDT MTF CASCADE BLOK: 5m yönü 1h ana trendi ile çelişiyor"
SONRA: "ZECUSDT MTF CASCADE BLOK: 4h yönü 1d ana trendi ile çelişiyor
        (1d=LONG 4h=SHORT)"
```

`mtf_confluence_skoru` artık `taban_tf` / `ana_trend_tf` de döndürüyor;
mesaj onlardan kuruluyor. Ad gelmiyorsa `"?"` basılıyor — UYDURULMUYOR
(§5.1). Sahada doğrulandı (18:48:31).

### ⚠️ BU TESTİ İKİ KEZ YANLIŞ YAZDIM — ikisi de öğretici

**1) Hep-kırmızı test.** Pencerem yalnızca log satırının SONRASINA
bakıyordu; `_taban`/`_ust` atamaları ÖNCE geldiği için test TEMİZ KODDA
da patlıyordu. Mutasyon koşusunda "temizde de kırmızı, mutasyonda da
kırmızı" görünce fark edildi.
➜ **Hep-kırmızı bir test, hep-yeşil kadar işe yaramaz** — neyi
yakaladığı bilinmez. Mutasyon testinde yalnızca "kırmızıya döndü mü"ye
değil, TEMİZ KODDA YEŞİL Mİ'ye de bak.

**2) Kendi yorumumu yakalayan test.** Pencere genişletilince bu kez
düzeltmeyi AÇIKLAYAN yorumumdaki `"5m yönü"` alıntısını yakaladı.
§0.29'un dersi üçüncü kez: **kaynak metni arayan test, kodu YORUMDAN
ayırt edemez.** Çözüm: yorum satırları ayıklanıyor. Sınır bilerek
kabul edildi — mesaj ŞABLONU çalıştırılmadan kilitlenemiyor; TF
adlarının DOĞRULUĞU ayrı testlerde `_tf_hiyerarsi()` ile davranışsal
olarak doğrulanıyor.

**Muhafız:** `tests/test_mtf_teshis_kaydi.py` (4 test), mutasyon 1/1
(eski sabit mesaja dönüş → kırmızı, temizde yeşil).

**Koşucu: 504 → 508 test.**

### 🔧 İZLEYİCİ DE DÜZELTİLDİ (oturum aracı, üretim değil)

İlk canlı emri bekleyen arka plan izleyicisi iki kusurla çalışıyordu:
- **HTTP 429 aldı** — 60 sn'de bir borsaya soruyordu; bot zaten 50 coinle
  rate limit sınırında (K-73/K-75). Artık 5 turda bir soruyor; log ve
  journal zaten yerel ve bedava.
- **Başarıyı log'dan yakalamıyordu** — yalnızca API/journal'a bakıyordu.
  `[EXEC ISLE] ✅` deseni eklendi (hem hızlı hem ağsız).
- **Yeniden başlatmada yanlış alarm riski** — "bot öldü" için artık ÜST
  ÜSTE İKİ ölçüm gerekiyor (yeniden başlatma penceresi ~10 sn).

---

## 0.35 VETO ZİNCİRİ İNCELENDİ — ÜÇ BULGU, HİÇBİRİ DEĞİŞTİRİLMEDİ (2026-09-13)

Kullanıcı ilk canlı emri beklerken istedi. Canlı moda geçişten (17:07)
sonraki **358 sinyalin 358'i** vetolandı, 0 emir açıldı. Sebep dağılımı:

| kapı | adet | pay |
|---|---|---|
| MTF hizalama yok | 128 | %35 |
| MTF cascade (taban ≠ ana trend) | 100 | %28 |
| geç giriş / slipaj | 65 | %18 |
| strateji (mean reversion) | 43 | %12 |
| EdgeEngine (AI skor < rejim eşiği) | 21 | %6 |

➜ **MTF tek başına %63.** 50 coinin ANLIK durumu da aynını veriyor:
31/50 (%62) MTF vetosunda.

---

### 🔴 BULGU 1 — "MTF hizalama yok" hizalamayı ÖLÇMÜYOR

`core/indicators.py` hizalama döngüsü:
```python
if ana_trend_yon != "NÖTR" and tf_yon != "NÖTR":
    if tf_yon == ana_trend_yon: hizali_tf.append(tf)
```
`ana_trend_yon` (= tabanın bir üstü, yani **1d**) NÖTR ise dış koşul
HER TF için False → `hizali_tf` koşulsuz BOŞ → `hizalama_skoru = 0`
→ main.py "MTF hizalama yok" deyip veto ediyor.

**KANIT (50 coin, anlık):**
```
hizalama_skoru == 0  : 17 coin
ana_trend_yon NÖTR   : 17 coin      ← BİREBİR AYNI KÜME
```

➜ Bu veto "hizalama yok" değil, **"1d'nin yönü yok"** demek.
Sonuç: `1w=LONG · 4h=LONG · 1d=NÖTR` durumunda işlem REDDEDİLİR —
görüşü olan iki TF hemfikir olmasına rağmen.

Docstring "hizalama_skoru: kaç TF hizalı" diyor; kod "referans TF ile
kaç TF aynı, referans nötrse sıfır" hesaplıyor. İsim ve davranış ayrışmış.

### 🔴 BULGU 2 — Slipaj kapısının ATR uyarlaması SÖNMÜŞ

```
eşik = min(MAX_GIRIS_KAYMA_PCT + ATR%×0.15,  MAX_GIRIS_KAYMA_PCT×2)
     = min(0.35 + ATR%×0.15,  0.70)
```
Tavan, ATR% > **2.33**'te devreye giriyor. **Medyan 4h ATR% = 2.43.**

```
tavana dayanan coin : 27/50  (%54)
ETHFIUSDT ATR%=6.81 → amaçlanan eşik %1.37, kırpılmış %0.70
```

➜ Uyarlama "oynaklığa göre esne" diye yazılmış ama 4h'de medyan coin
zaten tavanda. Gözlenen kaymalar: %0.71 · %0.95 · %2.07 · %1.95 —
hepsi tavanın üstünde.

**Kök neden aynı sınıf:** `MAX_GIRIS_KAYMA_PCT=0.35` 5m döneminde
kalibre edilmiş. 5m'de sinyal fiyatı en fazla 5 dk bayat; 4h'de
**4 SAATE kadar** bayat olabilir. K-78/K-82/K-83 ile birebir aynı
hata sınıfı: eski ufka göre kalibre edilmiş eşik, ufuk taşınırken
yeniden ölçeklenmemiş.

⚠️ Not: log `gecikme=0.9s` diyor — geciken ŞEY emir değil. Referans
fiyat kapanmış 4h barın close'u; kıyas "0.9 saniyede ne kadar kaydı"
değil, "bar kapanışından bu yana ne kadar kaydı".

### 🟡 BULGU 3 — MTF cascade log mesajı BAYAT

```
log: "MTF CASCADE BLOK: 5m yönü 1h ana trendi ile çelişiyor"
gerçek hiyerarşi: 1w / 1d / 4h   → kıyas 4h ile 1d arasında
```
K-29 mantığı düzeltmiş (`_tf_hiyerarsi()`), mesaj metnini düzeltmemiş.
**Bu incelemede beni bir süre yanlış yöne sürükledi** — "bot 4h'de ama
MTF 5m'e mi bakıyor?" diye kod okumak gerekti. Teşhis kaydının yanlış
büyüklük adı vermesi, §5.2'nin ölçüm tarafındaki karşılığı.

---

### ⚠️ PİYASA DURUMU — tıkanmanın hepsi kalibrasyon değil

```
1w : LONG 21 · NÖTR 22 · SHORT  7
1d : LONG 20 · NÖTR 17 · SHORT 13
4h : LONG  3 · NÖTR 15 · SHORT 32   ← kısa vadeli geri çekilme
```
4h'nin 32 coinde SHORT, 1d/1w'nin ağırlıkla LONG olması cascade
bloğunu (%28) şu an haklı olarak tetikliyor: uzun vadeli yükselişe
karşı short açmayı reddediyor. **Bu kısım tasarım gereği çalışıyor.**

### 🔍 KARAR BEKLİYOR — HİÇBİRİ DEĞİŞTİRİLMEDİ

| bulgu | seçenek | risk |
|---|---|---|
| 1 | referans NÖTR ise hizalamayı diğer TF'ler arasında say | giriş sayısı artar, kalite bilinmiyor |
| 2 | tavanı ATR ile ölçekle (örn. `max(0.70, ATR%×0.3)`) | geç girişe tolerans artar — K-31 bayat fiyat riski |
| 3 | log mesajını hiyerarşiden türet | risksiz, davranış değişmez |

1 ve 2 **strateji kararı** ve §5.3 gereği sıfırlama gerektirir.
§0 protokolü: 100 işlem dolmadan eşik oynatmak hükmü geçersiz kılar.
**3 risksiz ama ayrı adım (§4.5).**

---

## 0.34 🔴 K-93 — SIFIRLAMA KAPISI HİÇ ÇALIŞMIYORDU (2026-09-13)

İlk canlı emri izleyecek betiği yazarken, kendi "bot yaşıyor mu"
kontrolüm bot çalışırken **False** dedi. Sebebi aranınca aynı hatanın
**projede de** olduğu görüldü.

### PowerShell 5.1 tuzağı

```
(Get-CimInstance ... | Where-Object {...}).Count   ->  ''      ← BOŞ
@(Get-CimInstance ... | Where-Object {...}).Count  ->  '1'
```

PS 5.1 **tek nesneli** sonucu diziden çıkarır; `.Count` boş string
döner. `sifirla_k37.py::bot_calisiyor_mu()` bunu
`.strip() not in ("", "0")` ile okuyup **"bot yok"** sayıyordu.

**ÖLÇÜLDÜ:** bot PID 13760 ile ÇALIŞIRKEN fonksiyon `False` döndü.

### Neden ciddi

Bu kapının tek işi, sıfırlamayı bot açıkken çalıştırmayı ENGELLEMEK
("Çalışan bot sıfırlamadan sonra eski bakiyeyi geri yazabilir" — kendi
mesajı). Kapı, korumak istediği **NORMAL durumda** (tek bot çalışıyor)
tamamen etkisizdi. Sıfırlama sessizce devam eder ve K-59'un tarif ettiği
bakiye yarışını yaratırdı.

⚠️ `except` dalı da fail-OPEN'dı: kontrol patlarsa "bot çalışmıyor"
diyordu. Yıkıcı bir işlemi koruyan kapıda doğru varsayılan TERSİDİR.

➜ **Bu, §4.1'in "yeşil test kanıt değildir" dersinin kapı sürümü:
kapı VARDI, mesajı VARDI, ama hiç kapanmıyordu.**

### Düzeltme

`@()` dizi sarmalayıcı + iki yolda da **fail-CLOSED** (bilmiyorsak
"çalışıyor" say, sıfırlamayı reddet) + okunamayan durumda görünür uyarı.

### Muhafız

`tests/test_sifirlama_kapisi.py` (7 test). Kontrol testi dahil:
*bot gerçekten yokken sıfırlamaya İZİN VERİLİYOR* — yoksa "hep True dön"
mutasyonu diğer altısını da geçerdi.

**Mutasyon 4/4.** Biri önce kaçmış göründü (`if ham == "":` dalını
kaldırmak) — incelenince **davranışsal olarak eşdeğer** olduğu görüldü:
boş string zaten `ham != "0"` yolundan da True dönüyor. Dönüş değeri
kilitliydi, ama dalın asıl katkısı olan **UYARI** kilitsizdi (§5.2).
Onun için ayrı test eklendi; mutasyon o testle kırmızıya döndü.

**Ders:** "mutasyon kaçtı" demeden önce mutasyonun davranışı GERÇEKTEN
değiştirip değiştirmediğine bak. Eşdeğer mutasyonda kusur testte değil,
kilitlenmemiş bir YAN ETKİDE olabilir.

**Koşucu toplamı: 497 → 504 test.**

---

## 0.33 TESTNET CANLI MODA GEÇİLDİ + K-92 (2026-09-13)

Kullanıcı: *"Binance futures'ta geçmişe neden düşmüyor açılan pozisyonlar"*
→ ölçüldü → *"testnet'te canlıya al"*.

### Sorunun cevabı: emir hiç gönderilmiyordu

`LIVE_TRADING=false` · log'da emir gönderimi **0** · 8 işlemin hepsi
`mod='PAPER'`, yerel SQLite'ta simüle. Borsada geçmiş oluşmamasının
sebebi buydu — arıza değil, tasarım.

### ✅ SIFIRLAMA GEREKMEDİ — ölçülerek anlaşıldı

İlk refleks "§5.3, canlıya geçiş davranış değişikliği, sayaç sıfırlanmalı"
demekti. **Yanlış çıktı:**

| | |
|---|---|
| `trade_ac()` çağıran | YALNIZCA `paper_trading.py:479` |
| canlı yol `trades` tablosuna | **hiç yazmıyor** (journal'a yazıyor) |
| `karar_kurali.py:73` okuduğu | `WHERE mod='PAPER'` |
| `paper_trader.sinyal_isle()` | **koşulsuz** çağrılıyor (LIVE kapısı YOK) |

➜ İki yol PARALEL koşuyor, örneklemler `mod` sütunuyla zaten ayrı.
Sayaç 0/100 kaldığı yerden devam ediyor, 8 açık paper pozisyonu da
yönetilmeye devam ediyor. **Sıfırlama yapılmadı.**

**Ders:** "davranış değişti → sıfırla" refleksi ÖLÇÜLMEDEN uygulanırsa
gereksiz veri kaybı olur. Önce "hangi tablo, hangi mod, kim okuyor" diye bak.

### Yapılan

```
.env : LIVE_TRADING=false → true      (URL'ler zaten testnet)
FUTURES_BASE_URL = testnet.binancefuture.com   ← futures testnet
BINANCE_BASE_URL = testnet.binance.vision      ← spot testnet
```

Preflight tamamen yeşil — **"Koşullu emir: Algo Service erişilebilir"**
dahil (stop-loss yolu). Testnet futures bakiyesi doğrulandı: 4999.60 USDT.

⚠️ `.env`'deki *"testnet SL'i -4120 ile reddediyor, canlı mod işlem
tamamlayamıyor"* yorumu BAYATTI — ENGEL 1 bunu 2026-08-26'da çözmüştü.
Düzeltildi.

### Canlı yol doğrulandı (17:17–17:20)

```
[EXEC ISLE] ZENUSDT MTF CASCADE BLOK: 5m yönü 1h ana trendi ile çelişiyor
[EXEC ISLE] INJUSDT: Mean reversion koşulu sağlanmadı
[EXEC ISLE] FORMUSDT MTF hizalama yok → işlem atlandı
```
`_execution_isle` çalışıyor; emir henüz açılmadı çünkü veto zinciri
eliyor (beklenen — §0.28'de "red 8127 · açılan 7" ölçülmüştü).

⚠️ **CANLI, PAPER'DAN DAHA SEÇİCİ.** chop/MTF/EdgeEngine/strateji
vetoları `_execution_isle` içinde gömülü, paper'da YOK (§0.1 K-13,
§6.0 hâlâ açık). Yani testnet daha AZ pozisyon açacak. İki örneklemi
karşılaştırırken bu fark akılda tutulmalı.

---

### 🔴 K-92 — SIFIRLAMA YEDEĞİ WAL'İ KAÇIRIYORDU

Sıfırlamayı çalıştırmadan önce fark edildi (mutasyon testi için DB
kopyalarken çıkmıştı).

`sifirla_k37.py` yedeği `shutil.copy2("data/astra.db", ...)` ile alıyordu.
DB **WAL modunda** ve bot 7/24 açık bağlantı tuttuğu için checkpoint
kendiliğinden olmuyor — son saatlerin işlemleri `astra.db-wal`'de durur,
ana dosyada DEĞİLDİR.

**ÖLÇÜLDÜ (10. sıfırlamanın yedeği):**
```
yedek dizini oluşturuldu : 15:02
içindeki astra.db tarihi : 14:35     ← son checkpoint
içindeki en yeni işlem   : 12:43
-wal dosyası             : YOK
```
➜ Sıfırlama anında var olan **~2sa20dk'lık işlem hiçbir yerde yok**:
canlı DB'den silindi, yedeğe hiç girmedi. Aynı imza **13 yedeğin
HEPSİNDE** var (her birinin en yeni işlemi, alındığı saatten saatlerce geride).

**Düzeltme:** `_yedekle()` — `.db` için `sqlite3.Connection.backup()`
(WAL dahil tutarlı anlık görüntü), diğer dosyalar için `copy2`.

**Sentetik kanıt** (bot gibi açık bağlantı + 50 işlem WAL'de):
```
eski (shutil.copy2) : 0/50 işlem   → KAYIP 50
yeni (.backup)      : 50/50 işlem  → KAYIP 0
```

**Muhafız:** `tests/test_yedek_butunlugu.py` (4 test) — kontrol testi
dahil: *eski yöntemin gerçekten kaybettiğini* de doğruluyor, yoksa
"50 == 50" iddiası `copy2`'nin yeterli olduğu bir dünyada da geçerdi.
Mutasyon: `_yedekle` → `copy2` geri alındı → kırmızı.

⚠️ Yedek, sıfırlamanın TEK güvenlik ağıdır. Dolu görünüp eksik olması
§10'un tarif ettiği kör noktanın ta kendisi.

**Koşucu toplamı: 493 → 497 test.**

---

## 0.32 K-91 — YENİ TESTLER KOŞUCUDA HİÇ ÇALIŞMIYORDU (2026-09-13)

**En ciddi bulgu bu oturumun sonunda çıktı.**

K-89/K-90 için 14 muhafız yazıldı, `pytest` hepsini topluyordu, hepsi
yeşildi. Ama projenin KENDİ doğrulama komutu — §1'in "her değişiklikten
sonra çalıştır" dediği `python testleri_calistir.py` — toplamı hâlâ
**476** diyordu. Yeni dosyalar arasında YOKTU.

### Kök neden: sabit liste

`testleri_calistir.py` test dosyalarını **elle yazılmış bir listeden**
okuyor. Listeye eklenmeyen dosya sessizce atlanır: ne uyarı çıkar, ne
sayaç değişir, ne de koşu kırmızıya döner.

➜ **Çalıştırılmayan muhafız, olmayandan BETERDİR** — "yazdım, yeşil"
sanılır ve koruma sağladığı varsayılır.

§10'un birebir tarif ettiği sınıf: *kör nokta kodun içinde değil, kodun
ÖLÇÜLDÜĞÜ yerde duruyor.* v57'de "testler üretim verisini kirletiyordu
ve bunu hiçbir test yakalamıyordu" denmişti — bu onun kardeşi.

### İkinci kusur: dosyalar zaten çalışamazdı

Koşucu `python -X utf8 tests/test_x.py` ile ÇAĞIRIYOR (pytest ile
değil). Yeni dosyalarım `pytest` fixture'ları (`monkeypatch`,
`parametrize`) kullanıyordu ve `sys.path` kurulumu yoktu →
`ModuleNotFoundError: No module named 'tests'`. Listeye eklemek tek
başına yetmedi; proje geleneğine (sys.path + `__main__` bloğu +
fixture'sız) uyarlandılar. Üçü artık HEM pytest HEM tek başına çalışıyor.

### Muhafız

`tests/test_kosucu_kapsami.py` (3 test) — liste ile disk KARŞILAŞTIRILIR:
- diskte olup listede olmayan → kırmızı
- listede olup diskte olmayan (yanlış yazılmış yol da sessiz kapsama
  kaybıdır — koşucu "bulunamadı, atlanıyor" deyip GEÇİYOR) → kırmızı
- bu muhafızın KENDİSİ listede mi (değilse hiç çalışmaz, diğer ikisi
  anlamsız olur)

Mutasyon: kayıt satırı silindi → kırmızı, geri alındı → yeşil.

### Sonuç

    koşucu toplamı : 476 → 493 test  (atlanan dosya: 0)

---

## 0.31 K-90 — PANEL KORUMA SEVİYELERİNİ GÖSTERİYOR (2026-09-13)

Kullanıcı: *"evet yap"* — §0.30'un sonunda önerilen panel zenginleştirmesi.

### Bulgu: veri VARDI, panel okumuyordu

`trades` satırında `stop_loss`, `take_profit`, `tasfiye_fiyat`, `marjin`,
`funding_rate`, `ts_ac` ZATEN duruyordu. Panel yalnızca
sembol/yön/giriş/pnl/miktar/kaldıraç gösteriyordu — kaldıraçlı bir
pozisyonda bakılacak asıl sayıların HİÇBİRİ yoktu. "Güncel" sütunu bile
sabit `—` basıyordu.

### Eklenenler

Stop (SL) · Hedef (TP) · **Tasfiye** · Marjin · **Zaman stop ilerlemesi**
· Güncel fiyat. Her seviyenin yanında GÜNCEL fiyattan uzaklığı (%) —
"buradan ne kadar uzakta" sorusu girişten olan mesafeden kullanışlı.

### Üç tasarım kararı

1. **DUPLİKASYON KAPATILDI.** K-89'un kök nedeni `main.py`'daki üç ayrı
   eşleyiciydi. Yeni alanları üçüne birden eklemek aynı hatayı üçe
   katlardı — iki satır içi kurucu `_paper_pozlari_esle`'ye bağlandı.
   Artık tek yer (K-56'nın hedefi nihayet tamam).
   ⚠️ §4.5 gereği AYRI ADIM: K-89 saf hata düzeltmesiydi ve doğrulandı,
   birleştirme ondan SONRA yapıldı.

2. **ZAMAN STOP UFKU MOTORDAN.** `_zaman_stop_saat()` `config.ZAMAN_STOP_SN`
   okuyor — panelin `zaman_stop_doldu_mu()` ile aynı kaynağı. "24" diye
   sabit yazmak, ufuk değişince sessizce yalan söyleyen gösterge bırakırdı
   (K-82/K-83 sınıfı).

3. **EKSİK = `—`, 0 DEĞİL (§5.1).** Canlı futures yolu bu alanları
   göndermiyor. 0 basmak panelde "stop sıfırda" diye okunur ve korumasız
   pozisyonda YANLIŞ güvence verirdi.

### Muhafızlar — ve KENDİ TESTİMİN İKİ KUSURU

`tests/test_panel_koruma_alanlari.py` (8 test). **Mutasyon 4/4** — ama
İLK denemede 4'ten 2'si KAÇTI ve ikisi de gerçek kusurdu:

| mutasyon | neden kaçtı | düzeltme |
|---|---|---|
| ufku `return 24` diye sabitle | `ZAMAN_STOP_SN` şu an TAM 24 saat → `24 == 24.0` | config'i 12s/36s'e çevirip PEŞİNDEN GİTTİĞİNİ doğrula |
| hata hâlinde "doldu" uydur | `zaman_stop_doldu_mu()` bozuk tarihi KENDİ içinde yakalıyor → benim `except` bloğum hiç çalışmıyordu | çağrıyı `monkeypatch` ile gerçekten patlat |

**Ders 1:** Mevcut yapılandırmanın değeri, sabit kodlanmış değerle
ÇAKIŞIYORSA test ikisini ayırt edemez. "Config'i okuyor" iddiası ancak
config DEĞİŞTİRİLEREK kanıtlanır.

**Ders 2:** Bir `except` bloğunu test ettiğini sanmadan önce, o bloğun
FİİLEN çalıştığını doğrula. Alt katman hatayı kendi içinde yutuyorsa
senin fallback'in ölü koddur ve testi motorun davranışını ölçer.

(§0.30'un dersi de tekrar işe yaradı: her mutasyonun UYGULANDIĞI
eşleşme sayısıyla doğrulandı.)

### ⚠️ SIFIRLAMA GEREKMEZ

Görüntü katmanı — işlem, PnL, bakiye, muhasebe değişmedi. Sayaç 0/100.
**476 → 493 test**, tam paket yeşil (K-91: koşucuya kayıt de gerekti).

---

## 0.30 K-89 — K-86 GÖRÜNTÜ KATMANINDA HAYATTA KALMIŞ (2026-09-13)

Kullanıcı hedefini tarif etti: *"Tamamen Binance futures'ta kaldıraç
işlemini sahte parayla simüle etmesi… açtığı emirleri panelde göstermesi."*
Panelin ne gösterdiği ölçüldü ve **DB ile ÇELİŞTİĞİ** bulundu.

### ÖLÇÜM: panel 1x diyor, DB 3x

```
/api/state → acik_pozisyonlar[0]:  {"sembol":"XRPUSDT", ..., "kaldirac": 1}
DB trades  → id=1 XRPUSDT       :  kaldirac=3.0  marjin=17.47
```

### Kök neden: K-86 muhasebeyi düzeltti, GÖRÜNTÜYÜ değil

K-86 `paper_trading.py:486`'daki sabit kodu kaldırdı ve paper'ı
`islem_kaldiraci()`'ye bağladı. Ama `main.py` kaldıracı **ÜÇ AYRI YERDE**
kendisi yazıyordu ve üçü de `"kaldirac": 1` sabitiydi:

| yer | kimi besliyor |
|---|---|
| `main.py:1327` | panel (kol 1) |
| `main.py:2583` | panel (kol 2) |
| `main.py:1671` `_paper_pozlari_esle` | Telegram `/fpoz` |

Üçüncüsü ironik: **K-56 tam da bu duplikasyonu gidermek için** ortak
eşleyiciyi çıkarmıştı — ama `main.py`'daki iki kopya yerinde kaldı ve
K-86 uygulanırken üçü de atlandı.

**K-32/K-33 dersi birebir tekrar etti:** iki kaynak aynı büyüklüğü farklı
gösteriyorsa biri yalan söylüyordur. §2.5'teki "iki kaynağı KARŞILAŞTIR"
adımı panelin *kaldıraç* alanını kapsamıyordu.

### Düzeltme

Ortak `_kaldirac_goster(t)` (main.py:718) — üç yol da onu çağırıyor.

⚠️ **EKSİK DEĞER 1'E DÜŞÜRÜLMEDİ (§5.1).** K-86 öncesi kayıtlarda alan
yok; orada `1` yazmak "1x ile açıldı" İDDİASIDIR ve yanlıştır. `None`
dönüyor, panel `?` gösteriyor. `dashboard.py`'deki `${p.kaldirac||1}x`
de aynı fail-open'dı — o da kaldırıldı.

### Muhafız

`tests/test_kaldirac_gosterimi.py` (8 test) — **DAVRANIŞSAL**, kaynak
metninde "kaldirac" ARAMIYOR (§0.29'un dersi). Mutasyon **3/3**:
"sabit 1'e dön" · "eksiği 1'e düşür" · "hep sabit dön" — üçü de kırmızı.

⚠️ İlk mutasyon denemem "yakalanmadı" göründü; sebep testin zayıflığı
DEĞİL, **mutasyonumun uygulanmamış olmasıydı** (arama metnim araya giren
yorumu atlıyordu). Sayımı doğrulayınca (3 çağrı → 0 kaldı) test kırmızıya
döndü. **Ders: mutasyonun UYGULANDIĞINI de doğrula, yoksa "test zayıf"
diye yanlış sonuç çıkarırsın.**

### ⚠️ SIFIRLAMA GEREKMEZ

Bu bir GÖRÜNTÜ düzeltmesidir — işlem, PnL, bakiye, muhasebe değişmedi.
§5.3 sıfırlaması davranış değişikliği içindir. Sayaç 0/100 korunuyor.

⚠️ **Bot yeniden başlatılana kadar panel 1x göstermeye devam eder**
(çalışan süreç eski kodu tutuyor). 476 test + 8 yeni test yeşil.

---

## 0.29 "10 POZİSYON AÇIK, İLERLEMİYOR" — SIKIŞMA YOK, ÖLÇÜM YANLIŞ (2026-09-13)

Kullanıcı: *"Çok uzun süredir açık pozisyon 10 gösteriyor, neden
ilerlemiyor? Bir sıkışma olmuş olabilir mi?"*

### ✅ SIKIŞMA YOK — KANITLANDI

10 açık pozisyonun HER BİRİ için, açılış anından bugüne kadarki
gerçek 15dk kline aralığı çekilip SL/TP seviyeleriyle karşılaştırıldı:

| coin | yön | SL | TP | gerçek min | gerçek max | değdi mi |
|---|---|---|---|---|---|---|
| SOLUSDT | LONG | 99.474 | 106.677 | 99.97 | 103.10 | hayır |
| BNBUSDT | LONG | 717.76 | 757.31 | 719.11 | 739.89 | hayır |
| ETHUSDT | LONG | 2440.0 | 2612.3 | 2496.4 | 2548.3 | hayır |

**10/10 pozisyonun hiçbiri SL veya TP'ye DEĞMEMİŞ.** SOL ve BNB
stop'a %0.5 yaklaşmış ama dokunmamış. Piyasa aralıkta kaldı;
bekleme NORMAL davranış.

Fiyat kaynağı da doğrulandı: `guncel_fiyat_al()` gerçek piyasayı
veriyor (ETH 2499.56 vs gerçek 2498.07). SL/TP kontrolü bayat fiyatla
çalışmıyor.

---

### 🔴 K-84 — TEMPO YANLIŞ BÜYÜKLÜĞÜ ÖLÇÜYORDU (12 KAT SAPMA)

Kullanıcının sezgisi doğruydu, sadece sebep başkaydı.

`kontrol_4h.py:65` şöyleydi:
```python
Tempo: {(kapali+acik)*24/gecen} işlem/gün → 100 işlem ≈ N gün
```
**`(kapali + acik)` = AÇILAN işlemler.** Ama `karar_kurali.py`
`MIN_ISLEM=100`'ü **KAPANMIŞ** işlemler üzerinden uyguluyor —
kapanmamış pozisyonun PnL'i yoktur, hükme giremez.

**ÖLÇÜLEN SAPMA (37.4 saat, 11 açılan / 1 kapanmış):**

| | |
|---|---|
| gösterilen | 7.1 işlem/gün → **13 gün** |
| GERÇEK | 0.64 kapanış/gün → **156 gün** |

**12 kat iyimser.** Kullanıcı "ilerlemiyor" derken tam olarak bunu
fark etmişti: sayaç açılışları sayıyordu, hüküm ise kapanışları
bekliyor.

**Düzeltme:** iki hız ayrı ayrı gösteriliyor + slotlar dolduğunda
uyarı:
```
  Açılma  : 7.7 işlem/gün (11 işlem / 34.5 saat)
  KAPANMA : 0.70 işlem/gün → 100 KAPANMIŞ işlem ≈ 144 gün  ← hüküm buna bakar
  ⚠️  Açılma kapanmanın 11 katı — slotlar doluyor, akış KAPANIŞ hızıyla sınırlı.
```

⚠️ **Test çapası da güncellendi:** `test_cp1254te_tam_rapor_basiliyor`
raporun eksiksizliğini "Tempo" etiketiyle doğruluyordu; yeni etiketlere
(Açılma / KAPANMA) taşındı. Çapalar hâlâ raporun başından sonuna yayılı.

⚠️ **Kendi testimin kusuru:** ilk yazdığım `test_tempo_acilma_hizini_da_gosterir`
kaynakta "Açılma" KELİMESİNİ arıyordu — ama o kelime uyarı satırında da
geçtiği için mutasyonda YAKALANMADI. Etiketli satırın tamamını arayacak
şekilde sıkılaştırıldı.

---

### 🔴 YAPISAL SEBEP: ZAMAN-STOP YOK

Pozisyonlar neden 34 saat kapanmıyor?

- SL/TP **ATR tabanlı** (SL ≈ 1.5×ATR, TP ≈ 2×ATR) → %3-5 uzakta
- **Zaman-stop YOK.** `HEDEF_MAX_BAR=6` yalnızca model EĞİTİM etiketinde
  (üçlü bariyer) kullanılıyor; canlı pozisyonda karşılığı yok
- Yatay piyasada bu seviyeler günlerce tetiklenmeyebilir

➜ Sonuç: 10 slot dolar, akış durur. **Coin sayısı ve slot sayısı
değil, KAPANIŞ HIZI belirleyici.**

#### 🔍 KARAR BEKLİYOR — kapanış hızını artırma seçenekleri

| seçenek | etki | risk |
|---|---|---|
| **Zaman-stop** (örn. 12-18 bar sonra kapat) | kapanışı garanti eder | erken kesme; K-A'da ölçülen "erken kesme zararı" |
| TP çarpanını düşür | daha sık TP | R/R düşer — MIN_RR=1.2 kapısına takılabilir (§0 K-11) |
| Slot sayısını artır | daha çok eşzamanlı | kapanış hızı aynı kalırsa çözmez |

**Hiçbiri yapılmadı** — üçü de strateji kararı ve §5.3 gereği
sıfırlama gerektirir. Zaman-stop en doğrudan çözüm gibi duruyor ama
§0.14'te "erken kesme" ölçülmüş bir zarar kalemiydi.

---

### ✅ K-85 — ZAMAN STOP EKLENDİ (kullanıcı kararı)

§0.29'da sunulan üç seçenekten kullanıcı **zaman stop**'u seçti.

#### SÜRE KEYFİ DEĞİL — MODEL UFKUNDAN TÜRETİLDİ

`ZAMAN_STOP_BAR` varsayılanı **`HEDEF_MAX_BAR`** = 6 bar = **24 saat**.

Gerekçe: `HEDEF_MAX_BAR` üçlü bariyerin **dikey ufku** — model
etiketleri "önümüzdeki N bar içinde ne olacak" sorusuna göre
üretiliyor. O ufkun ÖTESİNDE pozisyon tutmak, modelin hakkında
**hiçbir iddiası olmayan** bir pozisyonu tutmaktır.

K-22 ile aynı ilke: eğitim ufku ile servis ufku ayrışmamalı.

Ölçüm de destekliyor: mevcut 10 pozisyonun hepsi 24-34 saattir açıktı,
yani hepsi modelin eğitildiği ufkun dışındaydı.

#### ÜÇ TASARIM KARARI

1. **ORTAK KURAL — tek kaynak.** `zaman_stop_doldu_mu()`
   `futures_trade_engine`'de; paper VE canlı yol aynı fonksiyonu
   çağırıyor. Ayrı yazılsaydı biri güncellenip diğeri unutulurdu —
   §5.3 bu kod tabanında tam olarak böyle kırılmıştı (K-13, K-69, K-78).

2. **SL/TP ÖNCE kontrol edilir.** Fiyat stop seviyesindeyse gerçekte
   stop dolmuştur; zaman stop onu ezerse zarar YANLIŞ fiyattan yazılır.
   Muhafız `test_sl_tp_zaman_stoptan_once_gelir` sırayı kilitliyor.

3. **DOLUM FİYATI FARKLI.** SL/TP seviyeden dolar (borsada duran emir);
   zaman stop botun PİYASA emriyle kapatmasıdır → `guncel_fiyat`
   kullanılır. Canlıda da öyle: `futures_pozisyon_kapat(...)`.

#### CANLI YOL

Canlıda SL/TP borsada duran emirler, zaman stop ise botun aktif
kapatması. `futures_pozisyon_izle` içinde uygulanıyor; açılış zamanı
borsadan gelmediği için botun KENDİ state'inden okunuyor
(`position_state.acilis_ts`). State yoksa zaman stop uygulanmaz ve bu
**log'da görünür** — sessizce atlanmaz (§5.2).

#### ⚠️ BEDELİ VAR — BU BİR DENEME

§0.14'te "erken kesme" ÖLÇÜLMÜŞ bir zarar kalemiydi: zıt sinyalle
kesilen 11 işlemde toplam zararın %22'si erken kesmeden geliyordu.
Zaman stop farklı bir mekanizma (sinyal değil süre) ama aynı riski
taşır — kazanmaya giden pozisyonu erken kesebilir.

Hüküm 100 işlemde `karar_kurali.py` ile verilir; sonuca bakılarak süre
değiştirilmez (§0 protokolü).

**Muhafızlar (5 test):** ufuk bağı · süre dolunca tetiklenme ·
KONTROL erken tetiklenmeme (bozuk/None zaman damgasında da işlem yok) ·
SL/TP önceliği · iki yolun aynı kaynağı kullanması.
Mutasyon 4/4 — "hep tetikle", "hiç tetikleme", "ufuktan kopar",
"SL/TP'yi ez" varyantlarının dördü de kırmızıya döndü.

⚠️ §5.3: davranış değişikliği — sıfırlama gerektirir.

---

### 🔴 K-86/K-87 — PAPER KALDIRAÇ UYGULAMIYORDU (§5.3 ihlali)

Kullanıcı: *"Amaç gerçek kaldıraç işlemi gibi davranması."*

#### BULGU: paper 1x SPOT gibi davranıyordu

| | canlı yol | paper yolu |
|---|---|---|
| kaldıraç | `dinamik_kaldirac_hesapla()` + rejim tavanı → `kaldirac_ayarla()` borsaya kurar | **`kaldirac=1` SABİT KODLU** (satır 486) |
| bakiyeden düşülen | marjin = notional/kaldıraç (satır 308'de yazılı) | **notional'in TAMAMI** |

Kapanmış işlemin rakamlarıyla doğrulandı:
```
pozisyon değeri 32.46 USDT · ham PnL -0.607 · PnL/pozisyon %-1.87
fiyat değişimi  %+1.87  →  ikisi AYNI → kaldıraç yok
```

➜ 100 işlemlik örneklem canlıyı temsil etmiyordu.

#### DÜZELTME — üç parça

**1. Kaldıraç TEK KAYNAKTAN (`islem_kaldiraci`).** Paper ve canlı aynı
fonksiyonu çağırıyor: dinamik kaldıraç + rejim tavanı. K-69/K-78/K-85
ile aynı desen.

**2. Marjin muhasebesi.** Açılışta `notional/kaldıraç` düşülüyor,
kapanışta `marjin + PnL` iade ediliyor. `kaldirac` ve `marjin`
kayıtta saklanıyor — kaldıraç ayarı sonradan değişse bile eski
pozisyonun iadesi AÇILIŞTAKİ marjinle hesaplanır.

⚠️ **`_bakiye_hesapla` de düzeltildi.** Restart'ta DB'den türetilen
bakiye hâlâ notional düşüyordu; açılışta marjin düşülürken restart'ta
notional düşülseydi iki bakiye AYRIŞIRDI — K-59'un birebir tekrarı.
Yakalandı.

**3. `pnl_yuzde` NOTIONAL tabanında BIRAKILDI — bilerek.**
`karar_kurali.py` beklentiyi bu alandan hesaplıyor ve `MIN_BEKLENTI_PCT
= 0.10` eşiği kaldıraçsız getiriye göre yazıldı. Tabanı marjine
çevirmek tüm değerleri kaldıraç katı büyütür, eşiği sessizce o kadar
kolaylaştırırdı → §0 protokolü geçersiz olurdu.

**Doğru ayrım:** kaldıraç PnL'in USDT tutarını DEĞİŞTİRMEZ; değiştirdiği
şey BAĞLANAN SERMAYEDİR. Uçtan uca doğrulandı:
```
notional 60 · 3x → marjin 20 bağlanır
%2 lehte hareket → PnL +1.20 USDT
  notional bazlı getiri %2.0   ← pnl_yuzde (karar kuralı)
  MARJİN bazlı getiri  %6.0   ← sermayenin gerçek getirisi = 3x ✅
bakiye özdeşliği: 10001.20 == 10001.20 ✅
```

---

### 🔴 K-87 — FONLAMA (FUNDING) HİÇ MODELLENMİYORDU

Perpetual futures 8 saatte bir fonlama öder/alır. Komisyon K-42'de
modellenmişti, **fonlama unutulmuştu**. K-85 ile pozisyonlar 24 saate
kadar tutuluyor → 3 fonlama dönemi.

**ÖLÇÜLEN GERÇEK ORANLAR** (2026-09-13, Binance premiumIndex):
```
BTC %0.0032 · ETH %0.0039 · ZEC %0.0057 · FET %0.0100  (8 saatte)
SOL %-0.0033  → NEGATİF oranda SHORT öder, LONG alır
yıllık karşılığı: %3.5 - %11
```

İşaret doğru modellendi: **LONG pozitif oranda ÖDER, SHORT ALIR.**
Giriş anındaki oran saklanıyor, kapanışta tutulan süreye oranlanıyor.

⚠️ **YAKLAŞIKLIK, bilerek:** gerçekte her 8 saatlik sınırda O ANKİ oran
kesilir. Giriş oranını kullanmak tam değil — ama SIFIR saymaktan
(eski davranış) çok daha gerçekçi ve iyimser tarafa kaçmıyor.

⚠️ **Para dökümü özdeşliği güncellendi:** `brut = net + komisyon + fonlama`.
Fonlama PnL'den düşülüp özdeşliğe eklenmeseydi rapor SAHTE kaçak
gösterirdi — o özdeşlik raporun kendi iç tutarlılık kontrolü.

Ayrıca `bagli_sermaye` artık marjin topluyor (notional değil).

---

### 🔴 K-88 — TASFİYE (liquidation) MODELLENDİ

Kaldıraç sadakatinin son parçası. Paper tasfiyeyi HİÇ uygulamıyordu;
`risk_manager` tasfiye MESAFESİNİ izliyordu (uyarı için) ama pozisyon
hiç tasfiye edilmiyordu — 1x muhasebesinde zaten olamazdı.

**Ortak fonksiyon** `tasfiye_fiyati(giris, yon, kaldirac)`:
```
aleyhte_oran = 1/kaldıraç − bakım_marjın_oranı(0.004)
LONG  → giriş × (1 − oran)      SHORT → giriş × (1 + oran)
```
Doğrulandı: 3x → %32.9 · 5x → %19.6 · 10x → %9.6 · **1x → tasfiye YOK**.
0.004 oranı `risk_manager.py:337` ile AYNI — iki yer ayrışmasın.

**Sıra: SL/TP → TASFİYE → ZAMAN STOP.** Tasfiye her zaman SL'den
UZAKTADIR (3x: %32.9 vs SL %3-5), yani normal işleyişte buraya hiç
gelinmez. Tasfiye, **SL'in dolmadığı durumun** (fiyat boşluğu)
karşılığıdır.

**Zarar marjinle SINIRLI.** Tasfiyede marjinin tamamı gider, bakiyeye
iade olmaz; hesaplanan zarar marjinden kötüyse marjine kırpılır.
İzole marjinde bakiye eksiye düşmez (borç oluşmaz).
➜ K-59'da "zarar pozisyon maliyetini aşarsa" diye bırakılan uyarının
gerçek karşılığı budur — artık sessiz kaçak değil, modellenmiş sonuç.

⚠️ **YAKLAŞIKLIK:** Binance kademeli bakım marjı uygular, büyük
notional'da oran yükselir. Tek oran kullanılıyor — küçük pozisyonlarda
yeterince doğru, dev pozisyonlarda iyimser.

---

### ⚠️ BU OTURUMUN TEKRAR EDEN DERSİ: KAYNAK METNİ ARAYAN TEST ZAYIF

**ÜÇ KEZ** aynı tuzağa düşüldü ve üçünde de mutasyon yakaladı:

| test | aradığı | neden kaçırdı |
|---|---|---|
| K-84 açılma hızı | "Açılma" kelimesi | uyarı satırında da geçiyordu |
| K-86 kaldıraç | "islem_kaldiraci" | import satırında da geçiyordu |
| K-85/K-88 sıra | "if not tetiklendi:" | iki blokta birden var |

Üçü de DAVRANIŞSAL teste çevrildi (sahte kapanış toplayıcı ile gerçek
`stop_tp_kontrol` sürülüyor). **Ders: `inspect.getsource` + `in` araması
bir davranışı kilitlemez; yalnızca metnin varlığını kilitler.**

---

### 🧪 MUHAFIZLAR + SIFIRLAMA

**7 yeni test** (kaldıraç sabit kodlanmasın · marjin düşülsün ·
restart'ta da marjin · pnl_yuzde tabanı korunsun · fonlama modellensin ·
fonlama işareti doğru · özdeşlik fonlamayı içersin).
**Mutasyon 36/36** — "notional bağla", "kaldıracı sabitle", "tabanı
marjine çevir", "fonlamayı atla", "işareti ters çevir" varyantlarının
hepsi kırmızıya döndü.

⚠️ Bir testim yine zayıf çıktı: `islem_kaldiraci` KELİMESİNİ arıyordu,
import satırında da geçtiği için mutasyon yakalanmadı. ATAMAYI arayacak
şekilde sıkılaştırıldı. (Bu oturumda ikinci kez — aynı hata deseni.)

**10. SIFIRLAMA YAPILDI** (2026-09-13 15:02) — kaldıraç/marjin/fonlama
davranış değişikliği; eski kayıtlar 1x spot muhasebesiyle tutulmuştu.
Yedek: `data/_yedek_k37_20260913_150222`.

---

## 0.28 İKİ GÜNLÜK DURUM İNCELEMESİ + K-83 (2026-09-12)

Kullanıcı "bot uzun süredir açık, durumunu incele" dedi. 50 coin +
10 slot yapılandırması 2 gündür sahada.

### ✅ ÇALIŞAN HER ŞEY ÖLÇÜLDÜ

| ölçüt | önce | şimdi |
|---|---|---|
| işlem (toplam / kapanmış) | 5 / 2 | **15 / 6** |
| tempo | 2.5/gün → 40 gün | **7.7/gün → 13 gün** |
| açık pozisyon | 3 (tavan 3) | **9** (tavan 10) |
| coin kapsaması | 39/50 (takılı) | **50/50** |
| tur süresi (bar içi) | — | **27-34 sn** (önbellekten) |
| tur süresi (bar sınırı) | 600+ → İPTAL | **948 sn** (tavan 1200, iptal YOK) |
| Telegram | 2303/gün | **23 / 14 saat** (5 sinyal + 5 grafik) |
| HTTP 418 | 279/gün | 25 (yalnız bar sınırında) |
| `-1021` | 74 | **0** |
| CB tetiklenme | 894 | **0** |
| ERROR / CRITICAL / Traceback | — | **0 / 0 / 0** (14 saat) |

**Para bütünlüğü TAM:** beklenen 9654.37 = gerçek 9654.37 (K-59 muhafızı
tutuyor).

**Veto sayaçları artık gerçek teşhis veriyor** (K-66 sayesinde):
```
red 8127 · açılan 7
  guven_dusuk       3441      max_acik_pozisyon 1041
  ai_skor_dusuk     2291      korelasyon         444
                              rr_yetersiz        388
```

➜ **Slotlar HÂLÂ darboğaz:** 10 slot doluyken 1041 sinyal reddedilmiş.
Daha fazla artırmak akışı daha da açar (risk kararı).

---

### 🔴 K-83 — WATCHDOG SAĞLIKLI BOTU ÖLDÜRÜYORDU

Yaşam döngüsü kaydında 10 saatte **iki SIGTERM** (çıkış kodu 15) vardı.
Sebep bulundu:

```
2026-09-11 00:00:14  [WATCHDOG] ALARM! 2424s sessiz
2026-09-11 00:02:17  [WATCHDOG] 3 uyarı → process yeniden başlatılıyor
```

**Ama bot DONMAMIŞTI.** O 40 dakika boyunca dakikada **25-55 satır log**
yazıyordu (REGISTRY model eğitimi, AUDIT, WS). Thread dump'ta da
kilitlenme yok — hepsi normal uyku/bekleme hâlinde.

**Kök neden:** `WATCHDOG_MAX_SILENT = 600` sn, 5 coinli dönemde kalibre
edilmişti (tur 66 sn). Heartbeat yalnızca **bir coinin analizi bitince**
atılıyor; 50 coinde ağır model eğitimi sırasında coin tamamlanmadığı
için sessizlik uzuyor. Bar sınırındaki tur zaten 948 sn — yani eşik
**turdan kısaydı** ve her bar sınırında sahte alarm garantiydi.

**K-82 ile TAM AYNI SINIF:** 5 coine göre kalibre edilmiş bir eşiğin
50 coinde yeniden ölçeklenmemesi.

**Zararı:** ısınma işi çöpe gidiyor, bot baştan başlıyor — yeniden
ısınma da uzun sürdüğü için **döngüye girme riski** var.

**Düzeltme:** eşik tur tavanından TÜRETİLİYOR —
`max(600, COIN_TUR_TIMEOUT * 2)` = **2400 sn**. Bir tur meşru olarak
`COIN_TUR_TIMEOUT` kadar sürebilir; iki tur pay tek yavaş turda sahte
alarmı önler, çok turluk gerçek donmayı yakalamayı sürdürür.
`.env`'deki sabit 600 geçersiz kılması kaldırıldı.

**Muhafızlar:** `test_watchdog_esigi_tur_suresinden_uzun` +
KONTROL `test_watchdog_hala_gercek_donmayi_yakalar` (eşik bir bardan
uzun olmamalı — aksi hâlde donma sessizce sürer). Mutasyon 2/2.

---

### ✅ 8. SIFIRLAMA YAPILDI (2026-09-12 01:10) — TEK YAPILANDIRMA

Kullanıcı kararı. Örneklem karışıktı (ilk 5 işlem 3 slotlu, sonrası
10 slotlu); artık 100 işlemin tamamı AYNI yapılandırmadan gelecek.

```
Yedek : data/_yedek_k37_20260912_010958
trades 15 → 0  ·  journal 15 → 0  ·  470 model dosyası silindi
position_state.json silindi  ·  4h_baslangic.json tazelendi
```

**KORUNANLAR ve gerekçesi:**

| korunan | neden |
|---|---|
| feedback (50 kayıt) | gerçek kapanışlardan gelen eğitim verisi |
| online model (50) | gerçek BAR sonuçlarından öğreniyor — yapılandırmadan bağımsız |
| `versions/` (1037) | `rollback_yap()` kullanıyor |

⚠️ **Geçen sıfırlamadan FARKLI:** o zaman online modeller SİLİNMİŞTİ,
çünkü K-64 öncesi uydurma etiketlerle zehirlenmişlerdi. Artık etiket
doğru (aşağıdaki doğrulamaya bak), o yüzden korundular.

🟢 **K-39 ETKİSİ GÖRÜLDÜ:** `versions/` 7174 → **1037 dosya**.
Saklama politikası çalışıyor.

**Sıfırlama sonrası etkin yapılandırma:**
```
coin 50 · slot 10 · aynı yön 7 · MaxATR %10
tur tavanı 1200s · watchdog 2400s · eşzamanlı 3
rejim eşikleri: TREND 3 · RANGE 4 · VOLATILE 5 · BEAR 5
Telegram: |AI|>=5 & güven>=70, rejim bildirimi kapalı
```

---

### ✅ K-64 NİHAYET SAHADA DOĞRULANDI

§0.24'ten beri "doğrulanmadı" diye açıktı. 2 günlük veriyle ölçüldü:

```
50 sembolde medyan eğitim adımı : 10
BEKLENEN (K-64 çalışıyorsa)     : ~12  (4h barda günde ~6 × 2 gün)
KIRIK OLSAYDI                   : ~2900 (dakikada ~1)
```

➜ Online öğrenme bar başına bir kez eğitiliyor, uydurma etiket yok.
K-65 (kalıcılık) de çalışıyor: 50 modelin hepsi diskte.

---

### 🟡 AÇIK KALANLAR

1. **HTTP 418 bar sınırında kümeleniyor** (25 olay, hepsi 00:32-00:59).
   50 coin aynı anda veri çekerken oluşuyor. Tur yine de tamamlanıyor —
   bozmuyor ama yavaşlatıyor. `ANALIZ_ESZAMANLI` düşürülebilir ya da
   bar sınırı işi zamana yayılabilir.
2. **Slot tavanı hâlâ bağlayıcı** (1041 red). Artırmak akışı açar.
3. ~~Örneklem karışık yapılandırmadan geliyor~~ → **8. SIFIRLAMA
   YAPILDI** (2026-09-12 01:10, yukarı bak). Sayaç 0/100, tek yapılandırma.

### 📊 PERFORMANS (n=6 — HÜKÜM DEĞİL)

```
6 kapanmış · 2 kazanan / 4 kaybeden · win rate %33
toplam PnL -2.113 USDT · komisyon 0.185 USDT
```
Karar kuralı 100 işlem istiyor. n=6'dan hiçbir sonuç çıkmaz.

---

## 0.27 K-79 — BREAKER 19 COİNİ SESSİZCE DEVRE DIŞI BIRAKMIŞ (2026-09-10)

Kullanıcı üç şey bildirdi: çok fazla circuit breaker mesajı, işlem
sayısının düşük ve sabit kalması, coin sayısının 50'yi bulmaması.
**Üçü de TEK sorunun belirtisiydi** — ve dördüncü, daha önemli bir
gerçek ortaya çıktı.

### Zincir

19 saatlik veri:

| belirti | ölçüm |
|---|---|
| CB tetiklenmesi | **894** (19 coin × ~47) |
| panelde görünen coin | **31 / 50** |
| açılan işlem | **5** (2 kapanmış) |

Eksik 19 coin ile breaker'ın tetiklediği coinler **birebir aynı liste**.
Yani breaker o coinleri her turda analizden atıyordu → evrenin %38'i
sessizce yok sayılıyordu.

### Kök neden: mutlak eşik, heterojen evren

`MAX_ATR_PCT = 4.0` beş büyük coin için kalibre edilmişti. 50 coinlik
evrende ATR ölçüldü (4h, ATR14):

```
TRX  %0.45 · PAXG %0.78 · BTC %1.05 · ETH %1.37 · XRP %1.96
                     medyan %3.65
DOT  %4.42 · NEAR %5.18 · PUMP %5.98 · COTI %8.17 · HEMI %9.04
                  SOPH %17.32 · IOST %29.51
```

**30 kat aralık.** Tek mutlak eşik burada anlamsız. Kanıt: her coin hep
AYNI değerle tetikleniyordu (medyan = maksimum) — bu acil durum değil,
o coinin normal hâli.

### Yapılan

1. **`MAX_ATR_PCT` 4.0 → 10.0.** Kalan en volatil coin HEMI %9.04, yani
   eşik artık gerçek bir tavan (SL ≈ %15), rutin kapı değil.
2. **IOSTUSDT ve SOPHUSDT evrenden ÇIKARILDI.** ATR %29.5 → SL %44 ve
   %17.3 → SL %26; bu volatilitede sağlıklı R/R kurulamaz. Yerlerine
   THEUSDT (%3.67) ve ETHFIUSDT (%4.91) eklendi. Yeni coin filtresine
   **ATR ≤ %8** koşulu eklendi.
3. Breaker'ın asıl dedektörü zaten `atr_spike` (s5/s20 > 2.5) — o coinin
   KENDİ geçmişine bakar, taban seviyeden bağımsızdır. Mutlak eşik
   yalnızca akıl-sağlığı tavanı olarak kaldı.

---

#### ✅ K-79 SAHADA DOĞRULANDI

| | ÖNCE (19 saat) | SONRA (20 dk) |
|---|---|---|
| ATR tetiklenmesi | 894 | **1** (FORMUSDT %11.5) |
| atlanan coin | 19 | **1** |

---

### 🔴 ASIL BULGU — İŞLEM HIZININ DARBOĞAZI COİN SAYISI DEĞİL

Kullanıcının 50 coin koyma amacı **100 işleme hızlı ulaşmaktı.**
Ölçüm bunun neden işe yaramadığını gösteriyor:

```
kapanan 2 işlemin ortalama tutuş süresi : 13.6 saat
MAX_OPEN_POSITIONS                      : 3
→ teorik tavan  = 3 × 24 / 13.6         = 5.3 işlem/gün
→ 100 işlem     = en iyi ihtimalle        19 gün
gözlenen (19 saat)                      : 2 kapanmış ≈ 2.5/gün → ~40 gün
```

**3 slot doluyken 50. coinin sinyali de 5. coinin sinyali de reddedilir.**
Coin sayısını artırmak SEÇİM kalitesini artırır (50 arasından seçmek),
ama AKIŞI artırmaz. Akışın tavanını `MAX_OPEN_POSITIONS` ve tutuş
süresi belirler.

Slot sayısına göre tavan:

| slot | tavan (işlem/gün) | 100 işlem |
|---|---|---|
| 3 (mevcut) | 5.3 | 19 gün |
| 6 | 10.6 | 9 gün |
| 10 | 17.6 | 6 gün |
| 15 | 26.5 | 4 gün |

⚠️ **Bu bir RİSK kararıdır, kod kararı değil:** eşzamanlı pozisyon
sayısı artınca aynı anda risk altındaki sermaye de artar.
`MAX_MARGIN_PCT=50` ve adaptif boyutlandırma sınırı ayrıca hesaba
katılmalı. §5.3 gereği değişiklik sayaç sıfırlaması gerektirir.

➜ **KULLANICI KARARI BEKLİYOR.**

---

### 🔴 K-80 — SLOT TAVANI 3 → 10 (kullanıcı kararı)

§0.27'de "karar bekliyor" diye bırakılan işlem hızı sorusuna kullanıcı
**10** dedi. Uygulandı — **ama tek başına 10 yazmak İŞE YARAMAZDI.**

#### ⚠️ YAN LİMİT SLOT ARTIŞINI YUTACAKTI

`MAX_SAME_DIRECTION = 2` idi. 10 slot + aynı yönde 2 tavanı = pratikte
en fazla **2 LONG + 2 SHORT = 4 pozisyon**. Yani artış sessizce
yutulurdu — K-78/K-79 ile aynı sınıf ("ayar var sanılıyor ama başka bir
tavan bastırıyor").

Kanıt: 5 coinli dönemde `Aynı yönde 2/2 → ATLANDI` günde **130 kez**
tetiklenmiş, en baskın red sebebiydi.

**Yeni değer 7, mevcut risk oranı KORUNARAK türetildi:** eski oran
2/3 ≈ %67; 10 × %67 ≈ 7. Yeni bir risk iştahı icat edilmedi, var olan
oran büyütüldü. Amacı korelasyon riski: kripto yüksek korelasyonlu,
tüm slotları tek yöne doldurmak tek bir yönlü bahistir.

#### SERMAYE BİND ETMİYOR (kontrol edildi)

```
pozisyon boyutu = min(TRADE_USDT=60, bakiye*0.20, bakiye-5) = 60 USDT
10 × 60 = 600 USDT / 10000 = %6      (MAX_MARGIN_PCT=50 çok uzak)
```

#### BEKLENEN ETKİ

| slot | tavan | 100 işlem |
|---|---|---|
| 3 (eski) | 5.3/gün | 19 gün |
| **10 (yeni)** | **17.6/gün** | **~6 gün** |

#### 🧪 MUHAFIZ — DEĞERİ DEĞİL İLİŞKİYİ KİLİTLER

- `test_ayni_yon_tavani_slot_artisini_yutmamali` — iki yönün toplam
  kapasitesi (2×MAX_SAME_DIRECTION) slot sayısını karşılamalı
- `test_yon_tavani_hala_koruma_sagliyor` — KONTROL: yön tavanı tamamen
  kalkmamalı (aksi hâlde korelasyon koruması yok)
- `test_slot_sayisi_sermaye_limitini_asmamali` — tüm slotlar dolunca
  marjin tavanı aşılmamalı, yoksa son slotlar sessizce açılamaz

Mutasyon 2/2: yön tavanı 2'ye ve 10'a çekildiğinde ikisi de kırmızı.

⚠️ §5.3: davranış değişikliği — eldeki 5 işlemlik örneklem geçersiz.

---

### 🔴 K-81 — REJİM BİLDİRİMİ 50 COİNDE TELEGRAM'I DOLDURUYORDU

K-80 sonrası yeniden başlatmadan **20 dakika sonra** ölçüldü:
15 Telegram mesajının **13'ü rejim bildirimiydi**.

K-71 rejimi sembol bazlı yapmıştı (doğru düzeltme). Ama 50 coinde her
sembolün **ilk ataması** da bir "değişim"dir → açılışta 50'ye kadar
bildirim. 5 coinde fark edilmezdi.

Kullanıcının açık isteği: Telegram'a yalnızca **çok emin sinyaller,
fotoğraflı**. FORMUSDT'nin RANGE→VOLATILE geçişi operasyonel gürültü.

**Düzeltme:** `TG_REJIM_BILDIRIMI=false` (varsayılan). Log HER değişimi
yazmaya devam ediyor, `rejim_guncelle` hâlâ `True` dönüyor (adaptasyon
çalışıyor) — yalnızca Telegram susturuldu.

Muhafız `test_rejim_degisimi_telegrama_gitmez` iki şeyi birden sınıyor:
bildirim gitmemeli AMA dönüş değeri korunmalı (aşırı düzeltme yakalanır).

---

### 🔴 K-82 — TUR İPTALİ 11 COİNİ KALICI OLARAK ANALİZ DIŞI BIRAKIYORDU

K-80'den sonra kapsama izlendi ve **39/50'de TAKILDI** (22:28 → 22:52,
10 dakika hiç ilerleme yok).

**Eksik 11 coinin 10'u listenin SON 10 coiniydi:**
`COTI · HBAR · ATOM · ETC · BCH · HEMI · JUP · ICP · THE · ETHFI`
(11.si FORMUSDT, o circuit breaker'daydı — ayrı konu.)

Yani tur 600 sn tavanını aşıp iptal ediliyor ve iptal **HEP AYNI
YERDE** vuruyordu: `asyncio.gather` coinleri liste sırasıyla işliyor,
semafor 3'lü ilerliyor, kuyruk hiç sıra alamıyor.

➜ O 10 coin **hiç sinyal üretemiyordu.** Kullanıcının 50 coin koyma
amacı (işlem hızı) tam da burada boşa çıkıyordu.

**İki düzeltme:**

1. **Tavan coin sayısıyla ölçekleniyor.** Eski formül yalnızca bar
   süresine bakıyordu (4h → 600 sn); 5 coinde tur 66 sn olduğu için
   yeterliydi. Yeni formül coin sayısı ve eşzamanlılığı da hesaba
   katıyor, ama barın yarısını aşmıyor: **600 → 1200 sn**.

2. **Tur sırası her turda KAYIYOR** (`_tur_sirasi`). Bu, kuyruk
   açlığını yapısal olarak imkânsız kılar: iptal devam etse bile her
   coin birkaç tur içinde başa gelir. Ölçüldü: 50 turda 50 farklı
   coin başa geçiyor.

⚠️ **Neden ikisi birden:** yalnızca tavanı büyütmek, ileride tur
yavaşlarsa aynı hatayı geri getirirdi. Kaydırma tavandan bağımsız
koruma sağlıyor.

**Muhafızlar:** `test_tur_sirasi_her_turda_kayar`,
`test_tur_sirasi_hicbir_coini_dusurmez` (KONTROL — kaydırma coin
düşürmemeli), `test_tur_tavani_coin_sayisiyla_olceklenir`.
Mutasyon 2/2.

---

### 🟡 KAYDA DEĞER

İlk iki kapanış da **zarar**: ZECUSDT −%5.97 (13.7 sa), XRPUSDT −%2.86
(13.5 sa). n=2, hüküm çıkmaz — yalnızca kayıt.

---

## 0.26 7. SIFIRLAMA YAPILDI + K-78 (2026-09-10)

Kullanıcı "botu yeniden başlat ve sıfırla" dedi. Yapıldı, ve **50 coine
geçiş 3 dakika içinde yeni bir hata ortaya çıkardı.**

### ✅ SIFIRLAMA

```
Yedek : data/_yedek_k37_20260910_021055
astra.db trades : 6 → 0        journal PAPER : 6 → 0
Model dosyası   : 47 silindi   position_state.json silindi
4h_baslangic.json tazelendi
```

**Betiğin dokunmadığı bir şey elle temizlendi:** `saved_models/online/`.
Beş online model `egitim=704` ile duruyordu → blend ağırlığı **0.35
(maksimum)**. Bu durum çoğunlukla **K-64 öncesi uydurma etiketlerle**
birikmişti (bot düzeltmeyi ancak 09-09 23:07'de aldı), yani zehirli bir
model güvene en yüksek ağırlıkla karışıyordu. Yedeklendi
(`_yedek_k37_20260910_021055/online_modeller/`) ve silindi.

**Feedback KORUNDU** (44 kayıt) — gerçek kapanışlardan geliyor.
**versions/ KORUNDU** (7174 dosya) — rollback kullanıyor.

⚠️ **Yedek boyutu:** betik `versions`'ı bilerek yedeklemiyor
(`ignore_patterns(..., "versions")`, §0.14 dersi) — aksi hâlde 26 GB
kopya çıkardı.

---

### 🔴 K-78 — BİR COİNİN ATR'Sİ TÜM EVRENİ DURDURUYORDU

50 coinle bot açıldıktan **3 dakika sonra** logda:
```
[CIRCUIT BREAKER] ATR çok yüksek PROMUSDT: %4.78 — 300s dur
[PROMUSDT] Circuit Breaker aktif — analiz atlandı
[SOLUSDT]  Circuit Breaker aktif — analiz atlandı   ← BAŞKA COİN
[XRPUSDT]  Circuit Breaker aktif — analiz atlandı   ← BAŞKA COİN
[BNBUSDT]  Circuit Breaker aktif — analiz atlandı   ← BAŞKA COİN
```
4 dakikada **17 tetiklenme**.

**K-71 ile TAM AYNI SINIF:** `VolatilityCircuitBreaker` tek bir
`_aktif` / `_sebep` / `_bekleme_bitis` alanı tutuyordu, ama TÜM
tetikleyiciler sembol bazlı (`atr_guncelle(sembol,…)`,
`funding_guncelle(sembol,…)`).

5 coinde nadirdi. **50 coinde volatil altcoin HER ZAMAN bulunur**
(PROM, NEAR, PUMP, SOPH…) → bot kalıcı olarak donardı. Yani 50 coin
bu düzeltme olmadan kullanılamazdı.

**Yan bulgu:** bildirim `force=True` ile gönderiliyordu — Telegram
throttle'ını ATLIYORDU. 17 mesajın sebebi buydu. Kaldırıldı; log her
tetiklenmeyi yazmaya devam ediyor (teşhis kaybolmaz).

**Düzeltme:** durum sembol bazlı sözlükte; `kontrol(sembol)`.
`durum` artık kaç coinin duraklatıldığını ve hangilerini özetliyor.

#### ✅ SAHADA DOĞRULANDI

| | tetikleyen | atlanan |
|---|---|---|
| coinler | ARB, DASH, DOT, IOST, NEAR, PROM, PUMP, SOPH, WLD | **birebir aynı 9 coin** |

Artık yalnızca tetikleyen coin duruyor.

⚠️ **Kendi testimin kusuru:** ilk yazdığım throttle testi kaynak
metninde `force=True` arıyordu — ve benim açıklama satırımdaki
"`force=True` KALDIRILDI" ifadesini yakalayıp yanlış yere kırmızı verdi.
Davranışsal teste çevrildi (sahte telegram fonksiyonuna geçen `force`
argümanına bakıyor).

⚠️ **İmza değişikliği iki testi kırdı:** `test_veto_zinciri.py`
fikstürleri `Sahte(kontrol=lambda: True)` kullanıyordu (parametresiz).
`*a, **kw` alacak şekilde güncellendi. **Not:** bunlardan
`test_circuit_breaker_engeller` "geçiyor" görünüyordu ama YANLIŞ
SEBEPLE — TypeError yüzünden emir gitmiyordu, kapı çalıştığı için değil.
§4.1'in tam örneği.

---

### 📊 SIFIRLAMA SONRASI İLK ÖLÇÜMLER

Yeni koşu (50 coin, tüm düzeltmeler devrede):

| ölçüt | ÖNCE (5 coin) | SONRA (50 coin) |
|---|---|---|
| HTTP 418 (IP ban) | **279/gün** | **0** |
| HTTP 429 | 30/gün | **0** |
| `-1021` | 74 → 0 | **0** |
| sahte rejim değişimi | **3446/gün** | **0** (yalnız ilk atamalar) |
| Telegram sinyal mesajı | 209 + 1137 grafik | **0** |
| tam tur süresi | 66 sn (5 coin) | **214 sn** (50 coin) |

#### ⚠️ TUR AŞIMLARI — TEK SEFERLİK ISINMA, KALICI SORUN DEĞİL

Sıfırlamadan sonra bazı turlar 600 sn tavanını aştı. Sebep ölçüldü:
sıfırlama **tüm model dosyalarını sildi** (47 tane), bot 50 coinin
modellerini SIFIRDAN eğitiyor.

```
03:12 ölçümü: bot 33 dakikada 4818 sn CPU harcamış (çok çekirdek)
              model eğitilen coin: 30 / 50
              kalan 20 coin ≈ 13 dk
```

**Bar önbelleği (K-73) bu durumu kendiliğinden çözüyor:** tamamlanan
coin o bar için önbelleğe giriyor ve sonraki turda ATLANIYOR, yani
iptal edilen turlar ilerlemeyi kaybetmiyor — birikiyor.

Isınma bitince tur süresi 214 sn civarına oturmalı (02:33'te ölçülen
değer). **Yine de sonraki oturumda doğrulanmalı;** kalıcı olarak
aşıyorsa `ANALIZ_ESZAMANLI` düşürülür.

---

### 🟡 SIRADAKİ OTURUM İÇİN

1. **Isınma bittikten sonra tur süresini doğrula** (yukarıdaki nota bak).
   Kalıcı olarak 600 sn'yi aşıyorsa `ANALIZ_ESZAMANLI` düşürülmeli.
2. **`PaperTrader başlatıldı | Min BUY skor: 4` log satırı YANILTICI** —
   gerçek kapı artık rejim bazlı (3/4/5/5, K-69/76/77). Kozmetik ama
   bu kod tabanının hastalığı tam olarak yanıltıcı gösterge.
3. **`orderbook_kaydedici.py` hâlâ eski 5 coini kaydediyor** (23:05'ten
   beri çalışıyor, COINS'i başlangıçta okumuş). 50 coine çıkarmak
   istek hacmini 10x artırır — ölçmeden yapma.
4. **Tempo yeniden ölçülmeli.** 50 coin + gevşetilen RANGE eşiği ile
   işlem sıklığı artmalı; 100 işleme kalan süre buradan hesaplanır.

---

## 0.25 KULLANICI BİLDİRİMLİ ÜÇ SORUN + 50 COİN (2026-09-10)

Kullanıcı dört şey istedi: panel "internet kesildi" uyarısı, Telegram
mesaj seli, tüm parametrelerin mantık denetimi, ve 5 → 50 coin.
Üçü de gerçek hataya çıktı; hepsinin ortak kökü **5m ufkundan kalma
kalibrasyon**.

⚠️ **ÖNCE SÖYLENDİ:** 50 coin, mevcut hâliyle botu tamamen durdururdu —
5 coinle bile günde 279 kez HTTP 418 (IP ban) alınıyordu. Bu yüzden
sıra şuydu: önce kapasite kökleri, sonra coin sayısı.

---

### 🔴 K-71 — REJİM TEK GLOBAL ALANDAYDI (3446 sahte değişim)

`RegimeAdapter` bir tane `_aktif_rejim` tutuyordu, ama
`rejim_guncelle()` **her sembol için** çağrılıyor ve coinler
**paralel thread'lerde** analiz ediliyor.

**ÖLÇÜM (2026-09-10, tek gün):**

| | |
|---|---|
| `REGIME SHIFT` satırı | **3446** |
| ardışık ikisi arası medyan | **2 saniye** |
| 60 sn'den kısa olanlar | 3293 |

Desen kusursuz alternatifti: `VOLATILE → TREND_UP → VOLATILE → …`
Piyasa 2 saniyede rejim değiştirmez; semboller birbirinin üstüne
yazıyordu.

**İki zarar:**
1. Her değişim Telegram'a ALERT gönderiyordu → günün **848 "rejim"
   mesajı** (toplam 2303 mesajın en büyük kalemi).
2. **Yarış durumu:** çağıranlar `rejim_guncelle(x); aktif_konfig()`
   diye okuyor. Paralel analizde araya başka sembol girince **A coini
   B coininin `kaldirac_max` değeriyle** işlem açabiliyordu.

**Düzeltme:** rejim sembol bazlı sözlükte; `aktif_konfig(sembol)`,
`efektif_kaldirac(raw, sembol)`. Uyarı yalnızca O SEMBOLÜN rejimi
değişince.

---

### 🔴 K-72 — TELEGRAM: 2303 MESAJ / GÜN

Rapor eşiği `_RAPOR_ESIGI` = **giriş eşiği** idi. Ama giriş bir kez
olur, rapor her turda atar. 4h ufkunda analiz sonucu bar boyunca
(4 saat) sabit, tur ise 60 sn → aynı sinyal bar başına ~48 kez.
`TG_MIN_ARALIK_SINYAL` yalnızca **30 saniye** idi (5m'den kalma).

**ÖLÇÜM:** 2303 mesaj = 1166 metin + 1137 grafik.

**Bar başına tekilleştirildiğinde ne kalırdı:**

| kapı | bildirim/gün |
|---|---|
| |AI|>=4 | 20 |
| |AI|>=4 & güven>=70 | 11 |
| **|AI|>=5 & güven>=70** | **2** ← seçilen |

**Düzeltme — iki katmanlı:**
1. `_tg_bildirilmeli()`: aynı (sembol, kapanmış bar) için **bir**
   bildirim. Karar değişirse (BUY→SELL) yeniden gönderilir — o
   gerçekten yeni bilgi.
2. Kalite kapısı `TG_MIN_AI_SINYAL=5`, `TG_MIN_CONF_SINYAL=70` —
   girişten DAHA yüksek ("çok emin"). Grafik de bu kapıya bağlandı;
   gönderilmeyecek grafik artık üretilmiyor (boşuna CPU).

📊 **Gözlenen en yüksek |AI| = 5**, `|AI|>=6` 4321 gözlemde **hiç**
görülmedi — yani 5 pratikte tavan.

---

### 🔴 K-73 — 4h BARDA 240 GEREKSİZ AĞIR ANALİZ

`ANA_BAR_DK=240` (14400 sn) iken `SCAN_INTERVAL=60` sn. Yani her
kapanmış bar için **240 kez** tam analiz. K-16'dan beri göstergeler
kapanmış bardan hesaplandığı için bu 240 analizin sonucu AYNI;
rakamlar yalnızca model sürümü ve online blend değiştiği için oynuyordu.

Not: yeniden giriş beklemesi 4h'e göre GÜNCELLENMİŞTİ
(`YENIDEN_GIRIS_BEKLEME_SN=14400`); tarama aralığı unutulmuştu.

**Bu tek parametre şunların hepsini besliyordu:**

| belirti | ölçüm |
|---|---|
| HTTP 418 (IP ban) | 279/gün · her biri 300 sn bekletiyor |
| sahte rejim değişimi | 3446/gün (K-71) |
| Telegram mesajı | 2303/gün (K-72) |
| model arşivi | ~0.7 GB/gün (K-39) |
| panel donması | isteklerin %43'ü 2 sn'yi aşıyor (K-74) |

**Düzeltme:** `_analiz_al()` — ağır analiz bar başına **bir** kez;
ara turlarda yalnızca **anlık fiyat** tazelenir.

⚠️ Anlık fiyat bilerek tazeleniyor: `stop_tp_kontrol` ve geç-giriş
iptali ondan besleniyor, bar içinde de çalışmak ZORUNDA. Fiyat
alınamazsa bayat fiyatla devam EDİLMEZ — tam analize düşülür (§5.1).

---

### 🔴 K-74 — PANEL "İNTERNET KESİLDİ" SAHTE ALARMI

Kullanıcının gördüğü uyarı `fetch('/api/state')` başarısız olunca
çıkıyordu. Panel **2 saniyede bir** yeniliyordu (v45'te 5s→2s
indirilmiş).

**ÖLÇÜM (7 dk, panelin kendi temposunda 86 istek):**
```
medyan 0.01s · p95 10.28s · max 13.50s
2 sn'yi AŞAN: 86 istekte 37  (%43)
tamamen başarısız: 2
```
Medyan anlık ama kuyruk 10+ saniye — analiz turunun CPU yükü
(model eğitimi) HTTP thread'ini aç bırakıyor. Yani bağlantı da bot da
SAĞLAMDI; panel sahte alarm veriyordu. Sahte alarm gerçek alarmı
değersizleştirir.

**Düzeltme (üç parça):**
- Yenileme aralığı 2 → **5 sn** (4h ufkunda 2 sn'nin bilgi değeri yok)
- **Tek uçuş:** önceki istek bitmeden yenisi başlamıyor (kuyruk
  büyütüp gecikmeyi artırıyordu)
- **Bayatlık eşiği:** tek yavaş yanıtta kırmızı YOK. Veri 30 sn'den
  tazeyse sarı "yanıt gecikti", gerçekten eskiyince kırmızı.

⚠️ Kendi eklediğim tek-uçuş bayrağını `finally` ile indirmeyi ilk
yazımda unutmuştum — panel ilk hatadan sonra kalıcı donardı. Yakalandı.

---

### 🔴 K-39 — MODEL ARŞİVİ SAKLAMA POLİTİKASI (nihayet)

§0.14'ten beri açıktı. **26.3 GB / 7174 dosya** (5 coinle ~0.7 GB/gün).
50 coinle ~7 GB/gün → boş 355 GB ~50 günde dolar.

⚠️ Sürümler `rollback_yap()` tarafından KULLANILIYOR, körü körüne
silinemez. Politika: (sembol, model_tipi) başına **son N** (varsayılan
20) + `aktif=1` olan + `en_iyi_versiyon()`in işaret ettiği korunur.
Yalnızca DOSYA silinir, DB kaydı durur — `gecmis()` ve raporlar bozulmaz.

---

### 🔴 K-75 — 50 COİN İÇİN EŞZAMANLILIK TAVANI

`asyncio.gather(*[... for s in COINS])` tüm coinleri aynı anda
başlatıyordu; gerçek tavanı varsayılan thread havuzu koyuyordu:
`min(32, cpu+4)` = bu makinede **20**.

5 coinle tavan zaten 5 idi. 50 coinle **20 coin aynı anda** analiz
edilir, her biri kline + funding + OI + order book + whale çağrısı
yapar → saniyeler içinde 100+ istek → 418.

**Düzeltme:** `ANALIZ_ESZAMANLI=3` semaforu. 50 coin × ~13 sn ÷ 3
≈ 220 sn; tur tavanı 600 sn (o zaten ufka göre türetilmişti).

---

### ✅ 50 COİN — ÖLÇEREK SEÇİLDİ

Elle liste uydurulmadı; Binance'ten çekilip elendi:

1. Futures **PERPETUAL + TRADING + USDT** olmalı (bot futures açıyor)
2. Sembol **ASCII** olmalı (URL/log/dosya adı güvenliği)
3. **Stablecoin olmamalı** — yönsüz enstrümanda trend stratejisi anlamsız
4. **>= 180 gün geçmiş** — model `ANA_PERIOD=180d` ile eğitiliyor
5. Kalanlar 24s hacme göre ilk 50

**Elenenler:** `USDCUSDT` (stablecoin, hacimde 1. sıradaydı),
2 ASCII dışı sembol, `MARSCOINUSDT` (6 gün), `XAUTUSDT` (168),
`KATUSDT` (176), `GRAMUSDT` (70).

356 aday → 50 seçildi (BTC, ETH, ZEC, PROM, SOL, XRP, BNB, NEAR,
DOGE, PUMP … ICP). Liste `.env` içinde gerekçesiyle duruyor.

---

### 🔴 K-76 — BEAR/VOLATILE EŞİKLERİ 7/6 → 5 (kullanıcı kararı)

§0.25'te "karar bekliyor" diye bırakılmıştı; kullanıcı **5** dedi ve
uygulandı. **Ama uygulanınca ölçüm önceki tavsiyeyi çürüttü.**

#### ⚠️ ÖNCEKİ TAVSİYEM EKSİK VERİYE DAYANIYORDU

§0.25'te "|AI| tavanı 5, o yüzden 5 mantıklı" demiştim. O, **tüm
rejimlerin birleşik** dağılımıydı. REJİM-İÇİ dağılıma bakınca tablo
değişti:

| rejim | n | eşik 3 | eşik 4 | **eşik 5** | max \|AI\| |
|---|---|---|---|---|---|
| RANGE | 1137 | %53 | %25 | **%0** | 4 |
| VOLATILE | 1031 | %65 | %2 | **%0** | 4 |
| TREND_DOWN | 1102 | %61 | %45 | %10 | 5 |
| TREND_UP | 1051 | %39 | %37 | %0 | 5 |

➜ **5, RANGE ve VOLATILE'de HÂLÂ ULAŞILAMAZ.** 7/6 → 5 değişikliği bu
iki rejimde davranışı DEĞİŞTİRMİYOR; yalnızca kanıtlanmış ölü bir
değeri kaldırıyor ve haritayı tutarlı yapıyor.

#### KÖK NEDEN: ÇİFT CEZA

`core/sinyal_skor.py` skoru rejime göre ZATEN düşürüyor:
```python
if rejim == "BEAR":       s -= 3
elif rejim == "VOLATILE": s -= 2
elif rejim == "RANGE":    s -= 1
```
Eşik haritası ise AYNI rejimler için bir kez daha yükseltiliyordu.
VOLATILE'de −2 cezayı yendikten sonra 5'e ulaşmak **ham +7** gerektirir;
gözlenen tavan ise 4.

#### BEAR ÖLÇÜLEMEDİ AMA ORADA ETKİLİ

Bugünkü logda BEAR hiç gözlenmedi. Yapısal olarak değişiklik orada
GERÇEK: −3 ceza nedeniyle SHORT için
- eşik 7 iken ham **−4** gerekiyordu
- eşik 5 iken ham **−2** yetiyor

Yani BEAR'da short açmak belirgin şekilde kolaylaştı.

#### 🔍 AÇIK KALAN SORU

RANGE/VOLATILE gerçekten açılsın isteniyorsa ilk anlamlı değer **4**
(RANGE %25, VOLATILE %2). Bu AYRI bir karar — kullanıcı 5 dedi, 5
uygulandı.

Not: VOLATILE'de **R/R kapısı zaten bağımsız olarak engelliyor**
(MIN_RR=1.2 vs ölçülen 0.77 — §0 K-11). Yani VOLATILE'i AI eşiğinden
açmak tek başına işlem üretmeyebilir.

#### 🧪 MUHAFIZ — DEĞERİ DEĞİL, İLİŞKİYİ KİLİTLER

`test_rejim_esigi_skor_cezasini_asmamali` — eşik + skor cezası, TREND
eşiğinin makul üstünü aşarsa kapı yapısal olarak ulaşılamaz demektir.
`test_hicbir_rejim_esigi_gozlenen_tavani_asmamali` — eşik ölçülen
tavanın üstüne kaçarsa yakalar.

Mutasyon 2/2: BEAR 7'ye ve VOLATILE 9'a geri alındığında ikisi de
kırmızıya döndü.

⚠️ Bu testler "eşik 5 olsun" DEMİYOR. Tavan değişirse ölçüm yenilenir;
amaç eşiğin sessizce ölü bir bölgeye kaymasını engellemek.

---

### 🔴 K-77 — RANGE EŞİĞİ 5 → 4 (kullanıcı kararı)

K-76'da "açık kalan soru" diye bırakılmıştı; kullanıcı RANGE için
**4** dedi. K-76'nın aksine bu **inert DEĞİL** — gerçek etkisi var.

**ÖLÇÜLEN ETKİ** (aynı gün, güven kapısı MIN_CONFIDENCE=62 DAHİL):

| rejim | gözlem | ÖNCE geçen | SONRA geçen |
|---|---|---|---|
| RANGE | 1137 | **0** | **92** |
| TREND_DOWN | 1102 | 279 | 279 |
| TREND_UP | 1051 | 418 | 418 |
| VOLATILE | 1031 | 0 | 0 |
| **toplam** | | **697** | **789** (+%13) |

⚠️ **%25 DEĞİL %8.** Yalnız AI eşiğine bakınca 295/1137 (%25) geçiyor,
ama güven kapısı da uygulanınca 92/1137 (%8) kalıyor — yani |AI|=4 olan
RANGE sinyallerinin çoğunun güveni zaten düşük. Gerçekleşecek olan bu.

**Neden bu sinyaller gerçekten işleme dönüşür:** RANGE'de R/R = 1.33 >
MIN_RR = 1.2 (§0), yani R/R kapısına TAKILMAZLAR. VOLATILE'den farkı
tam olarak budur.

**Çift ceza dengelendi, kaldırılmadı:** RANGE'de skora `−1` uygulanıyor,
yani eşik 4 için ham **5** gerekiyor (TREND'de ham 3). RANGE hâlâ
TREND'den seçici.

**VOLATILE bilerek 5'te bırakıldı.** 4'e çekmek yalnızca %2 açardı ve
orada R/R kapısı zaten bağımsız engelliyor (MIN_RR=1.2 vs ölçülen 0.77
— §0 K-11, kârsızlığın asıl sebebi olarak bulunan şey).

⚠️ **Bu bir DENEMEDİR.** Hüküm 100 işlemde `karar_kurali.py` ile
verilir; sonuca bakılarak eşik değiştirilmez (§0 protokolü).

---

### 🟡 DÜZELTİLMEDİ — KARAR BEKLİYOR

**1. ~~BEAR ve VOLATILE eşikleri~~ → KULLANICI KARARI: 5 YAPILDI (K-76).**
Ama ölçüm gösterdi ki 5 de RANGE/VOLATILE'de ulaşılamaz — ayrıntı
K-76'da. Aşağıdaki eski kayıt tavsiyenin nasıl eksik veriye
dayandığını göstermek için duruyor.

**1-eski. BEAR ve VOLATILE eşikleri ULAŞILAMAZ (veri var artık).**
`REGIME_BEAR_MIN_AI=7`, `REGIME_VOLATILE_MIN_AI=6`. Ama 4321
gözlemde `|AI|>=6` **HİÇ** görülmedi (tavan 5).

➜ Bot bu iki rejimde **hiçbir zaman işlem açamaz**. Bu artık bir
tahmin değil, ölçüm. Tarihsel olarak barların %35'i BEAR+VOLATILE.
K-69 eşitliği sağladı ama kalibrasyonu bilerek ellemedi.

**Neden kendiliğimden değiştirmedim:** hangi değere çekileceği
strateji kararıdır ve doğrudan işlem davranışını değiştirir.
Öneri: TREND=3 / RANGE=5 ölçeğiyle tutarlı olacak şekilde
VOLATILE=5, BEAR=5 — ama bu bir denemedir, ölçülmeli.

**2. 50 coinde "en iyi 3" değil "ilk 3" açılıyor.**
`MAX_OPEN_POSITIONS=3`. Bot coinleri sırayla tarayıp eşiği geçen
İLK üçünü açıyor — en iyi üçünü değil. 5 coinde fark küçüktü,
50 coinde belirleyici olur.

➜ Kullanıcının "daha çok coine bakıp daha karlı olsun" hedefi
asıl burada karşılanır. Bu §0.15'teki denenmemiş **kesitsel
(cross-sectional)** fikrin ta kendisi ve evren artık 50 coin.
Ayrı bir iş olarak ele alınmalı.

---

### 🧪 MUHAFIZLAR

`tests/test_kapasite_ve_bildirim.py` — **12 test**.
**Mutasyon: 11/11 sağlam.** Aşırı düzeltme yönü de sınandı
("hiç bildirme", "hepsini sil", "hiç değişim bildirme").

---

### ⚠️ SIFIRLAMA GEREKİYOR

K-71 (yanlış coinin kaldıracı), K-72/K-73 (güven artık bar boyunca
sabit) ve 50 coin evreni davranış değişiklikleridir. §5.3 gereği
eldeki paper örneklemi yeni yapılandırmayı temsil etmiyor.

**Bekleyen 7. sıfırlama ile BİRLİKTE yapılmalı.**

---

## 0.24 SAHA DOĞRULAMASI + K-70 (2026-09-09)

09-06'daki düzeltmeler üç gün üretimde kaldı. **Ölçülerek** doğrulandı —
"testler yeşil" değil, gerçek log ve dosyalarla.

### ✅ K-63 SAHADA DOĞRULANDI — `-1021` SIFIRLANDI

| dönem | `-1021` | HTTP 429 |
|---|---|---|
| 09-06 10:39 → 09-07 02:04 (eski kod) | **74** | 136 |
| 09-07 02:04 → 09-09 23:07 (yeni kod) | **0** | 30 |

Rate limit olayları SÜRERKEN `-1021` tamamen kayboldu. Bu, teşhisi
kanıtlıyor: sorun saat değil, uykudan sonra bayat timestamp'ti.

### ✅ K-65 SAHADA DOĞRULANDI — MODELLER DİSKE YAZILIYOR

`saved_models/online/` 08-11'den 09-06'ya kadar BOŞTU. Şimdi
5 sembolün her biri için ~267 KB'lık model dosyası var.

### 🔴 K-70 — TESTLER ÜRETİM ONLINE MODEL DİZİNİNE YAZIYORDU

Doğrulama sırasında ortaya çıktı: dizinde `online_TESTLEARN.pkl` vardı —
bunu `tests/test_denetim_duzeltmeleri.py:108` üretiyor.

**Kanıt (tahmin değil):** dosyanın tarihi alındı, test paketi
çalıştırıldı, tarih yenilendi (09-06 18:05 → 09-09 23:10).

Kök neden: `engines/online_learner.py` içinde
```
_ONLINE_MODEL_DIR = "saved_models/online"   # sabit kod
```
`tests/izolasyon.py` `MODEL_DIR`'i yönlendiriyor ama bu satır onu
GÖRMÜYORDU. **K-1 ve K-21 ile aynı sınıf** (testler üretim durumuna
yazıyor, §4.6).

⚠️ **K-65 bu sızıntıyı BÜYÜTTÜ:** eskiden yalnızca `egitim%100==0`
anında yazılıyordu, düzeltmeden sonra her adımda. Kendi düzeltmemin
yan etkisi.

**Düzeltme:** dizin `_online_dizin()` ile ÇAĞRI ANINDA `MODEL_DIR`'den
çözülüyor. Artefakt silindi; test tekrar çalıştırıldı, üretim dizinine
artık yazmıyor (doğrulandı).

Muhafız: `test_online_model_uretim_dizinine_yazmaz`.

### ⏳ K-64 SAHADA HENÜZ DOĞRULANMADI

Diskteki `egitim=704` değeri eski koddan mı yeni koddan mı geldiği
ayırt edilemedi (bot 09-06 16:03'ten 09-09 23:07'ye kadar tek örnekte
çalıştı; o örnek düzeltmeden ÖNCE başlamıştı). Yeniden başlatma sonrası
ölçüm **IP ban yüzünden sonuçsuz kaldı** (aşağı bkz).

➜ **Yapılacak:** bot düzgün tur atmaya başlayınca 10 dk boyunca
`online_learning.egitim` izlenmeli. 4h barda beklenen artış sembol
başına **günde ~6**; dakikada ~1 görülüyorsa K-64 üretimde çalışmıyor.

---

### ✅ KENDİ KENDİNİ EĞİTME DÖNGÜSÜ UÇTAN UCA ÇALIŞTI

§0.23'te "feedback fiilen durmuş (0 kapanmış işlem)" yazmıştım.
Kapanışlar gelince döngü işledi:

| | 09-06 | 09-09 |
|---|---|---|
| feedback kaydı | 41 | **44** |

Artan 3 kayıt, kapanan 3 işlemin TAM karşılığı (BNB, ETH, SOL) ve
üçü de doğru etiketlenmiş (`target=0`, hepsi zarardı). Log da
doğruluyor: `[FEEDBACK/BNBUSDT] 9 kayıt eğitime eklendi`.

➜ Yani mekanizma sağlam; tek engel işlem sayısı.
`RETRAIN_MIN_FEEDBACK=20` olduğu için feedback tabanlı retrain hâlâ
tetiklenmiyor (en yüksek sembol 15 kayıtta).

---

### 🔴 ACİL — HTTP 418 (IP BAN) BOTU DURDURUYOR

Doğrulama sırasında bulundu. **Bugün 279 kez HTTP 418**, her biri
**300 saniye** bekletiyor (429'lar yalnızca 30).

```
23:07:31  418 → 300s bekleniyor
23:09:05  WS 6 denemede düzelmedi → REST polling moduna geçildi
23:12:32  418 → 300s bekleniyor
23:14:29  WATCHDOG: 420s heartbeat yok        ← analiz TURU YOK
```

Saatlik dağılım patlamalı: 02:00'de 54, 04:00'te 44, 19:00'da 43.
Endpoint'ler: `/fapi/v1/klines`, `/fapi/v3/balance`, `/fapi/v3/positionRisk`.

**YENİ DEĞİL** — 09-02..09-04 logunda da 82 tane var. Benim
değişikliklerimden gelmiyor (onlar `api.binance.com`/spot kullanıyor).

**Şüphe (ölçülmedi):** WebSocket "Stale data" ile düşünce bot REST
polling'e geçiyor, istek hacmi katlanıyor, 418 geliyor, 300 sn her şey
duruyor — sonra döngü tekrarlıyor. §8.0'da "çözülmemiş" diye kayıtlı
WS sorunu artık YEREL makinede de var.

➜ **Bu, veri toplama hızını doğrudan vuruyor** (tempo 2.6 → 1.5
işlem/gün düştü). Sıradaki oturumun ilk işi olmalı.

---

### 📊 İLK ÜÇ KAPANIŞ — HEPSİ STOP

4h ufkunda ilk gerçek kapanışlar geldi:

| # | sembol | yön | pnl% | süre |
|---|---|---|---|---|
| 1 | BNBUSDT | LONG | **−2.55** | 10.3 sa |
| 2 | ETHUSDT | LONG | **−1.71** | 35.7 sa |
| 3 | SOLUSDT | LONG | **−2.55** | 23.8 sa |

3/3 stop, toplam ≈ **−%6.8**.

⚠️ **n=3'ten HİÇBİR SONUÇ ÇIKMAZ.** Karar kuralı 100 işlem istiyor ve
bu eşiğe dokunulmayacak (§0). Buraya kaydedilmesinin tek sebebi:
ilk kapanışların yönü kayda değer, hüküm değil.

🟢 **İyi haber:** artık SHORT pozisyonlar da var (BNBUSDT SHORT,
BTCUSDT SHORT). §0.13'ün "örneklem %100 TREND_UP / LONG" endişesi
kısmen dağıldı.

Tempo: **1.5 işlem/gün** → 100 işlem ≈ 68 gün (önceki tahmin 39 gündü).
418 sorunu çözülürse hızlanır.

---

## 0.23 DÖRT DENETİM YAPILDI — ALTI HATA (2026-09-06 akşam)

§0.22'de bekleyen dört denetimin **dördü de** yapıldı. Üçünde gerçek
hata çıktı, biri (Binance verisi) **temiz** çıktı. Ayrıca ENGEL 3'ün
teşhisi YANLIŞTI — kök neden bulundu.

Sağlık (denetimden önce): 18.7 saat çalışıyor, tempo 2.6 işlem/gün,
2 açık pozisyon (BNB+ETH, 9.3 saat), 0 kapanmış, 10 dk'dan kısa işlem 0,
SL<%1 olan 0. **Sağlık temiz.**

---

### ✅ DENETİM 4 — BINANCE VERİSİ GERÇEK (hata yok)

Bağımsız ham HTTP çekimiyle karşılaştırıldı (botun kodu kullanılmadan):

| | bot (panel) | bağımsız çekim |
|---|---|---|
| BNBUSDT son_close | 758.24 | **758.24** |
| bar kapanışı | — | 11:59 UTC (08-12 barı) |
| anlık fiyat | 751.94 | 751.09 |

Beş sembolde de kapanmış bar doğru, oluşan bar atılıyor (K-16 çalışıyor).
**Tek not:** veri SPOT'tan (`api.binance.com`), işlem FUTURES'ta.
Ölçülen fark **%0.05** — 4h'de SL %2.4 olduğu için gürültü içinde,
ama §5.3 sınıfından bir ayrışma; kayda geçti.

---

### 🔴 K-63 — `-1021` SAAT HATASI DEĞİLDİ (ENGEL 3 ÇÖZÜLDÜ)

§0.14 ve ENGEL 3 "Windows saat senkronunu düzelt (`w32tm /resync`)"
diyordu. **Ölçüldü: yerel saat Binance'ten yalnızca +25 ms sapıyor**
(5 örnek, orta-nokta yöntemi). Saat sağlam; `w32tm` bu hatayı çözmezdi.

Gerçek zincir logdan çıktı:
```
15:55:45  🚦 429 rate limit → 15s bekleniyor
15:55:46  🚦 429 → 14s bekleniyor   (×3)
15:56:01  -1021 "outside of recvWindow"   ← tam 15 sn sonra
```
İmza ve `timestamp` retry döngüsünden **ÖNCE bir kez** üretiliyordu.
429'da 15 sn uyunuyor, sonra **aynı timestamp** gönderiliyordu;
`recvWindow` 10 sn olduğu için Binance -1021 döndürüyordu.

Kanıt: bugünkü **25 `-1021` olayının 25'i de** dakikanın :00/:01
saniyesinde — yani 429 uykusunun bittiği an. Bugün 87 rate-limit var.

**Bot kendi ürettiği hatayı saat kayması sanıyordu.**

Yan bulgu — offset ölçümü de yanlıydı:
```python
r = requests.get(.../time)      # RTT ≈ 300 ms
yerel_ms = int(time.time()*1000)   # ← gidiş-dönüşten SONRA
offset = sunucu_ms - yerel_ms      # = −RTT/2 ≈ −150 ms
```
Log bunu doğruluyor: bot sürekli −123..−167 ms "düzeltme" yazıyordu.
Sağlıklı bir saatte sistematik 150 ms hata üretiliyordu.

**Düzeltme:**
- `_zamanla_ve_imzala()` — her denemede TAZE timestamp + imza
  (`newClientOrderId` DEĞİŞMEZ, çift emir koruması korunur)
- offset artık gidiş-dönüşün **ortasından** ölçülüyor
- -1021 dalı yalnızca offset cache'ini geçersiz kılıyor

➜ **ENGEL 3 kapandı.** Asıl mesele saat değil **rate limit**: 87 429/gün
ayrı bir konu (istek sıklığı), ama artık -1021 üretmiyor.

---

### 🔴 K-64 — ONLINE ÖĞRENME UYDURMA ETİKETLE EĞİTİLİYORDU (K-17'nin ikizi)

`/neden` denetimi yapılırken çıktı. Etiket şuydu:
```python
_onceki_fiyat = _son_analizler[sembol]["son_close"]
_gercek = 1 if son_close > _onceki_fiyat > 0 else 0 if _onceki_fiyat > 0 else None
```
Ama K-16'dan beri `son_close` **KAPANMIŞ barın** kapanışı — 4h ufkunda
**4 saat sabit**. Analiz turu ~1 dk'da dönüyor.

**ÖLÇÜM (canlı bot, 5 dk, 20 örnekleme):**

| | |
|---|---|
| `son_close` değişimi | **0** (5 sembolün hepsinde) |
| online eğitim adımı | **+6 / sembol** |
| → üretilen etiket | 6/6 uydurma **"0"** |

Oran: **~288 eğitim adımına 1 gerçek etiket.** Model "fiyat asla
yükselmez"i öğreniyor, `P(yükseliş)→0` veriyor ve bu `birlesik_tahmin`
ile güvene **%10–35 ağırlıkla** karışıyordu — güveni sistematik olarak
AŞAĞI çekiyordu. (§0.17 "neden hep WEAK BUY" sorusunun bir mekanizması.)

**Düzeltme:** `etiket_uret()` — yalnızca **bar kimliği** değiştiğinde
etiket üretir. Değerden değil kimlikten bakılır: iki bar aynı fiyattan
kapanabilir, o meşru "0" kaybolmamalı. Mantık satır içinden ayrı
fonksiyona çıkarıldı (K-37 dersi: satır içi mantık davranışsal test
edilemiyor).

---

### 🔴 K-65 — ONLINE MODEL DİSKE HİÇ YAZILMAMIŞ

`saved_models/online/` **2026-08-11'den beri BOŞ.** Kayıt koşulu
`egitim % 100 == 0` idi ama her yeniden başlatmada sayaç 0'dan
başlıyordu (yükleyecek dosya yok) ve 100'e ulaşmadan bot yeniden
başlıyordu (bugün ~12 kez).

Sonuç: blend ağırlığı `egitim < 50` dalında **0.1'e çakılı**, online
öğrenme hiçbir zaman birikmiyordu. K-45/K-50 motoru çalışır hale
getirmişti; bu, öğrendiğinin saklanmadığını gösteriyor.

**Düzeltme:** her gerçek eğitim adımında kaydediliyor. K-64'ten sonra
adım sayısı sembol başına günde ~6 olduğu için maliyet önemsiz.

---

### 🔴 K-66 — `/neden` PAPER MODDA KÖRDÜ (DENETİM 2)

Şüphe doğruydu. `_veto_kaydet` çağrılarının **tamamı**
`main.py::_execution_isle` içindeydi ve o fonksiyon şöyle başlıyor:
```python
if not LIVE_TRADING:
    return
```
Yani paper modda (bugünkü mod) **hiçbir red sayılmıyordu**. Panel ve
`/neden` kalıcı olarak "Henüz işlem denemesi yok" diyordu.

Oysa aynı dönemde logda **1347 gerçek red** vardı:

| red nedeni | sayı |
|---|---|
| AI skor eşiği (BUY) | 527 |
| Güven eşiği | 317 |
| Yeniden giriş beklemesi | 200 |
| R/R kapısı | 144 |
| Korelasyon (aynı yön 2/2) | 130 |
| AI skor eşiği (SELL) | 83 |
| Geç giriş (slippage) | 76 |

**Düzeltme:** paper yolunun 11 red noktası + başarılı açılış sayacı
teşhis modülüne bağlandı (`guven_dusuk`, `ai_skor_dusuk`, `rr_yetersiz`,
`yeniden_giris_beklemesi`, `max_acik_pozisyon`, `korelasyon`,
`slippage_gec_giris`, `bakiye_yetersiz`, `miktar_sifir` …).
`/neden` ve panel isim haritaları güncellendi.

⚠️ **Sayaç bellekte** — her yeniden başlatmada sıfırlanır. Kalıcı
sayaç ayrı bir iş (bkz. açık gözlem).

**Bugünkü tablo şunu söylüyor:** bot işlem açmıyor çünkü 2 LONG
pozisyon açık ve `MAX_SAME_DIRECTION=2`; her yeni LONG sinyali
korelasyon limitine takılıyor.

---

### 🔴 K-67 — BALİNA TESPİTİ ÖLÜ, AMA "AKTİF" GÖRÜNÜYORDU (DENETİM 3)

Canlı çağrıyla ölçüldü:
```
whale : {"whale_skoru": 0.0, "kaynak": "yok"}      ← Glassnode anahtarı YOK
skor  : +0.59  — BEŞ SEMBOLDE DE AYNI
```
Üç ayrı sorun:

1. **Balina tespiti diye bir şey yok.** Anahtar yoksa fonksiyon sabit
   `0.0` döndürüyor. Docstring "hacim-tabanlı proxy" diyordu — **kodda
   öyle bir yol yok.** Docstring düzeltildi.
2. **`aktif` bayrağı yanıltıcıydı:** `netflow != yok OR whale != yok`.
   Netflow proxy'si çalıştığı için balina tamamen ölüyken de `True`
   dönüyordu. §5.1: "bilmiyorum" ≠ "sorun yok".
3. **"netflow" aslında netflow değil:** CoinGecko `/global`'den
   `market_cap_change_percentage_24h_usd` alınıp `−1` ile çarpılıyor.
   Coine özgü DEĞİL, beş sembolde aynı. İşareti netflow semantiğinden
   miras: **piyasa düşerken skor +bullish** oluyor (bugün piyasa −%2.95,
   skor +0.59). Bu, `market_sentiment`'e ±2 katkı veriyor ve
   `sentiment != 0` olduğu için güvene **+5** ekliyor.

**Düzeltme (yalnızca DÜRÜSTLÜK, davranış DEĞİŞMEDİ):** `whale_aktif`,
`coine_ozgu`, `kaynak_sayisi` alanları eklendi; `/onchain` artık
"Whale: +0.00 KAPALI (Glassnode anahtarı yok)" ve "coine özgü DEĞİL"
yazıyor. **`aktif` mantığı bilerek AYNI bırakıldı** — sentiment
katkısını kesmek strateji kararıdır, §0.22'nin sorusu değil.

✅ **KARAR VERİLDİ (kullanıcı): DÜZELTİLDİ** — bkz. K-68 aşağıda.

---

### 🔴 K-68 — BALİNA TESPİTİ GERÇEK VERİYE BAĞLANDI (kullanıcı kararı)

K-67 sorunu **teşhis** etmişti; kullanıcı "kaldıralım mı düzeltelim mi"
sorusuna **düzeltelim** dedi. Yapılan üç şey:

**1. Balina proxy'si artık GERÇEK ve COİNE ÖZGÜ.**
Glassnode anahtarı yokken sabit `0.0` dönmek yerine, Binance'in
ÜCRETSİZ kline alanlarından hesaplanıyor:

```
ortalama_islem_boyu = quote_asset_volume / num_trades
buyukluk = z-skoru(son bar, önceki 47 bar) / 3, [0,1] arası
yon      = 2 × (taker_alis_payi − 0.5),        [-1,+1] arası
whale_skoru = buyukluk × yon
```

Mantık: aynı hacim 10.000 küçük emirle de gelebilir, 200 büyük emirle
de. İkincisi büyük katılımcı demektir; yönü taker alış payı verir.
Büyük işlem + alış = **birikim (+)**, büyük işlem + satış = **dağıtım (−)**.

⚠️ **Negatif taraf bilerek kırpıldı:** işlemlerin KÜÇÜLMESİ "ters
balina" değil, balina YOKLUĞUdur → 0 döner (§5.1).

⚠️ Bu alanlar (`quote_asset_volume`, `num_trades`, `taker_buy_quote`)
`_klines_df` tarafından ATILIYOR (yalnızca OHLCV tutuluyor), bu
yüzden ayrı çekiliyor.

**İLK ÖLÇÜM (2026-09-06, 5 sembol, 1h × 48 bar):**

| sembol | skor | işlem boyu z | taker alış | okuma |
|---|---|---|---|---|
| BNBUSDT | **−0.104** | **+1.91** | %41.8 | büyük işlemler, satış baskısı → **dağıtım** |
| BTCUSDT | 0.000 | −0.32 | %34.7 | işlem boyu olağan → bilgi yok |
| ETHUSDT | 0.000 | −0.45 | %42.6 | bilgi yok |
| SOLUSDT | 0.000 | −0.03 | %46.4 | bilgi yok |
| XRPUSDT | 0.000 | −0.26 | %43.1 | bilgi yok |

Çoğu zaman 0 çıkması **doğru davranıştır** — balina her saat ortaya
çıkmaz. Eskisi beş coine de sabit **+0.59** veriyordu.

**2. Sahte "netflow" katkısı skordan ÇIKARILDI (kaldırılmadı, ayrıldı).**
İki gerekçe:
- **Coine özgü değil:** CoinGecko `/global`'den gelen tek bir piyasa
  değeri değişimi; beş sembole de aynı sabit ekleniyordu. Aynı sabiti
  hepsine eklemek hiçbirini diğerinden ayırmaz (§0.8: ortak kayma ≠ edge).
- **İşareti tersti:** "borsadan çıkış = boğa" kuralı gerçek netflow
  semantiğinden miras, ama piyasa değeri değişimine uygulanıyordu.
  Sonuç: **piyasa düşerken skor boğa** oluyordu (o gün −%2.95 → +0.59).

Değer `global_piyasa_24s` alanında RAPORLANMAYA devam ediyor;
`/onchain` "sadece baglam, karara girmez" diye gösteriyor.

**3. `aktif` bayrağının anlamı düzeltildi.** Artık "sentiment'e
eklenebilir mi?" demek ve yalnızca COİNE ÖZGÜ ölçüm varsa True.
Global proxy'nin çalışıyor olması bunu True yapmıyor.

---

### ✅ K-69 — PAPER / CANLI REJİM KAPISI TEKLEŞTİ (2026-09-06)

ENGEL 4'ün iki ayrı parçası vardı:

1. **Eşitlik hatası:** paper girişi sabit `|ai| >= 4`, canlı giriş ise
   rejime göre `3 / 5 / 6 / 7` uyguluyordu. Aynı sinyal, rejime göre
   bir modda açılıp diğerinde reddedilebiliyordu.
2. **Kalibrasyon sorusu:** K-37 skor aralığını daralttı; özellikle
   BEAR `7` ve VOLATILE `6` eşiklerinin yeni ölçekteki stratejik
   karşılığı henüz ölçülmedi.

**K-69 yalnızca 1'i çözer; 2'yi tahminle çözmez.**

`engines/futures_trade_engine.py` içine iki ortak fonksiyon çıktı:
- `rejim_ai_esigi(rejim)` — tek eşik haritası,
- `sinyal_kalitesi_degerlendir(sonuc, yon)` — güven + rejim + yön
  değerlendirmesinin tek kaynağı.

Paper'ın `_sinyal_kalitesi_gecer()` metodu artık bu ortak fonksiyonu
çağırıyor. Böylece TREND'de `3`, RANGE'de `5`, VOLATILE'de `6`,
BEAR'da `7` eşiği **iki modda da aynıdır**. Çıkış yolu da zaten bu
kapıyı çağırıyordu.

**Muhafız:** `tests/test_rejim_esigi_essitligi.py` (3 test) her rejimde
LONG ve SHORT için tam eşikte / eşik altında paper-canlı eşitliğini
kontrol ediyor. Mutasyon: paper'a eski sabit ±4 kapısı geri konduğunda
`TREND_UP/LONG/ai=3` vakası beklenen biçimde kırmızı oldu.

⚠️ **ENGEL 4 kısmen açık:** artık örneklem canlı davranışıyla eşleşir;
ama BEAR'da `7` skorunun erişilemez olması "bu rejimde bilinçli olarak
işlem yok" anlamına mı geliyor, yoksa yanlış kalibrasyon mu — bunu veri
ile ölçmeden eşik değiştirmek yeni bir strateji denemesi olur.

---

#### 📊 ÖLÇÜLEN DAVRANIŞ ETKİSİ

`market_veri_topla` ile önce/sonra (2026-09-06):

| sembol | YENİ sentiment | ESKİ sentiment | ai_score etkisi |
|---|---|---|---|
| BTCUSDT | −0.50 | +0.09 | 0 |
| ETHUSDT | **0.00** | +0.59 | 0 |
| BNBUSDT | −0.60 | +0.09 | 0 |
| SOLUSDT | **0.00** | +0.59 | 0 |
| XRPUSDT | **0.00** | +0.59 | 0 |

- **`ai_score`'a etkisi bugün SIFIR** — katkı eşiği `|sentiment| > 1.5`
  ve hiçbir coin o eşiğe yaklaşmıyor.
- **AMA `conf` değişiyor:** `main.py:1044` → `if market_sentiment != 0:
  conf += 5`. ETH/SOL/XRP artık TAM 0 olduğu için bu bonus DÜŞMÜYOR.
  `MIN_CONFIDENCE=62` olduğundan sınırdaki bir sinyal (65 → 60) artık
  reddedilebilir.

⚠️ **Bu bonusun kendisi ayrı bir sorundur ve DOKUNULMADI:** sentiment'in
sıfırdan farklı olması — yönü ne olursa olsun, AYI bile — güveni
artırıyor. Eskiden uydurma sabit sayesinde HER BARDA veriliyordu.
Şimdi hak edilince veriliyor. Düzeltmek strateji kararıdır.

---

### ✅ DENETİM 1 — AI ÖĞRENME: NE ÖĞRENİYOR, NE ÖĞRENMİYOR

| katman | durum |
|---|---|
| **Batch retrain** | ✅ çok aktif — 378 model sürümü/gün. Ama piyasa verisinden öğreniyor, KENDİ işlem sonuçlarından değil |
| **Feedback (kendi işlemlerinden)** | ⛔ fiilen durmuş — 41 kayıt, hepsi silinmiş işlemlerden. `RETRAIN_MIN_FEEDBACK=20`, sembol başına 4–15 var. 0 kapanmış işlem olduğu için büyümüyor |
| **Online learning** | 🔴 K-64 + K-65 — çalışıyordu ama uydurma etiketle, ve öğrendiğini saklamıyordu |

Feedback kayıtlarının **41'i de gerçek**: etiket↔PnL tutarsızlığı **0**,
PnL aralığı −3.33..+2.58. K-17'nin uydurma kayıtları geri gelmemiş.

⚠️ **"Kendi kendini eğitiyor mu?" sorusunun dürüst cevabı:** modeli
sürekli yeniden eğitiyor (piyasa verisiyle), ama **kendi işlem
sonuçlarından öğrenmesi 0 kapanmış işlem yüzünden durmuş durumda.**
Bu, ENGEL 2'nin (100 işlem) bir yan etkisi.

⏳ **10. HİPOTEZ HÂLÂ ÖLÇÜLMEDİ:** online blend'li güven vs blend'siz.
K-64'ten önce ölçmek anlamsızdı (girdi çöptü). Artık ölçülebilir —
ama önce bar başına gerçek etiketlerin birikmesi gerekiyor.

---

### ⚠️ KENDİ DÜZELTMEMDE KUSUR — ÇIKIŞ REDLERİ GİRİŞ SAYACINA YAZIYORDU

K-66'yı yazdıktan SONRA fark edildi: `_sinyal_kalitesi_gecer` yalnızca
açılış yolundan değil, **çıkış yolundan da** çağrılıyor
(`_cikis_gecerli`, v58 K-A ile eklenmişti). Sayaç çağrısını oraya
koyunca "pozisyon KAPATILMADI" redleri "pozisyon AÇILMADI" diye
sayılıyordu → `/neden`in açılma oranı paydası şişerdi.

Bu, düzeltmeye çalıştığım hatanın (K-56: farklı olayı aynı kaynaktan
okumak) **aynısını üretmek** olurdu.

Düzeltme: `sayacli` parametresi; çıkış yolu `sayacli=False` geçiyor.

⚠️ İlk yazdığım kontrol testi de ZAYIFTI: `sayacli=False`'ı kendisi
geçirip mekanizmayı sınıyordu. Asıl risk `_cikis_gecerli`'nin bayrağı
geçirmeyi UNUTMASI (K-29 tuzağı). Test, çıkış yolunu DOĞRUDAN sürecek
şekilde yeniden yazıldı — ve mutasyonda (çağrıdan `sayacli=False`
silindiğinde) kırmızıya döndüğü doğrulandı.

**Bu oturumda kendi işimde bulunan ikinci kusur sınıfı** (ilki: ölçüm
betiğini kırpılmış çıktıyla okuyup "2 dosya çalıştı" sanmak).

---

### 🧪 MUHAFIZLAR

`tests/test_ogrenme_ve_teshis.py` — **21 test**, K-63..K-68'yi kilitler.
Her veto testinin yanında KONTROL testi var (§4.1).

`tests/test_rejim_esigi_essitligi.py` — **3 test**, K-69'u kilitler.

**Mutasyon doğrulaması: 12/12.** Her düzeltme tek tek geri alındı, ilgili
test kırmızıya döndü — "aşırı düzeltme" yönü dahil (etiket hep None
döndürülünce `test_yeni_bar_gercek_etiket_uretir` kırıldı).

---

### ⚠️ SIFIRLAMA GEREKİYOR — K-64 DAVRANIŞ DEĞİŞİKLİĞİDİR

K-64 güven hesabını değiştiriyor (online blend artık çöp etiketle
eğitilmiyor). §5.3 gereği bundan önceki paper verisi yeni yapılandırmayı
temsil etmiyor.

**Zaten bekleyen 7. sıfırlama (K-37) ile BİRLİKTE yapılmalı** —
`python sifirla_k37.py`. İki ayrı sıfırlama yapmanın anlamı yok.

⚠️ Bot şu an **eski kodla** çalışıyor (16:03'te başladı, düzeltmeler
sonra geldi). Yeniden başlatılana kadar K-63..K-69 devrede DEĞİL.

---

### 🟡 AÇIK GÖZLEMLER

1. **Veto sayacı bellekte** — her yeniden başlatmada sıfırlanıyor.
   Bot günde ~12 kez yeniden başlıyor, yani `/neden` hiçbir zaman
   günlük tabloyu göstermiyor. Kalıcı sayaç ayrı iş.
2. **Rate limit: 87 × 429 / gün.** Artık -1021 üretmiyor ama istek
   sıklığı yüksek demek; ölçülmedi.
3. **Analiz turu 66 sn** (`[PARALEL] 5 coin 66.0s'de tamamlandı`) —
   4h ufku için gereksiz sıklıkta. Rate limit'in muhtemel kaynağı.
4. **K-39 hâlâ açık:** `saved_models/versions/` 22.7 GB, 1.33 GB/gün.

---

## 0.22 ✅ DÖRT DENETİM — TAMAMLANDI (sonuçlar §0.23'te)

> **2026-09-06 akşam: dördü de yapıldı, sonuçlar §0.23'te.**
> Aşağıdaki liste denetimin KAPSAMINI gösterir, bekleyen iş değildir.

### 1. AI ÖĞRENME / KENDİ KENDİNİ EĞİTME
> *"Ne kadar ders alıyor, kendi kendini eğitebiliyor mu?"*

Bakılacaklar:
- `_self_train_tetikle` / `feedback_ekle` — K-17'de uydurma etiket
  sorunu düzeltilmişti (917 sahte kayıt silinmişti). **Şu an gerçek
  kapanış olmadığı için feedback birikmiyor** (0 kapanmış işlem).
  → `saved_models/feedback_*.jsonl` içeriğini say, gerçek mi kontrol et
- `engines/online_learner.py` — K-45/K-50'de İLK KEZ çalışır hale
  geldi. `egitim` sayacı artıyor mu? (panelde `online_learning`)
- `_adaptif_retrain_gerekli_mi` — retrain tetikleme mantığı
- **ÖLÇÜLECEK:** online blend'li güven vs blend'siz — 10. hipotez
  (§0.20 sonunda söz verildi). Ekonomik yargıçla, örneklem-dışı.

### 2. İŞLEM TEŞHİSİ — `/neden`
> *"İşlem teşhisinde ne kadar iyi?"*

Şu an "Henüz işlem denemesi yok" diyor. Bakılacak:
- Veto sayaçları gerçekten dolduruluyor mu? (`veto` state alanı var
  ama panelde `{'acilan_islem': 0, 'toplam_red': 0}`)
- Logdaki gerçek red dağılımıyla karşılaştır (§0.13'te ölçmüştüm:
  216 AI skor, 200 yeniden giriş, 171 korelasyon, 130 güven)
- **Şüphe:** `/neden` bu sayıları görmüyor olabilir — K-56 sınıfı
  (farklı kaynaktan okuma).

### 3. BALİNA / ON-CHAIN TESPİTİ
> *"Sistemdeki balina dalgalanmalarını anlayabiliyor mu?"*

- `data/onchain_data.py`: `whale_hareket_tespit`, `exchange_netflow_proxy`
- Glassnode API anahtarı var mı? Yoksa "proxy" moddadır (CoinGecko).
- §0.15'te ölçülmüştü: **on-chain modele HİÇ girmiyor**, yalnızca
  `/onchain` raporunda ve `edge_engine`'de.
- **ÖLÇÜLECEK:** whale skoru gerçek veriden mi geliyor, yoksa sabit
  fallback mi? (`aktif` alanı `False` ise proxy demektir)

### 4. BINANCE VERİSİ GERÇEKTEN GELİYOR MU
> *"Binance'den gelen verileri gerçekten sağlayabiliyor mu?"*

- K-15'te veri kaynağı gerçek borsaya çevrilmişti (`BINANCE_DATA_URL`)
- K-16: kapanmamış bar atılıyor
- **ÖLÇÜLECEK:** botun kullandığı kline'ları bağımsız bir çekimle
  karşılaştır (fiyat, zaman damgası, bar sayısı). §5.3.1'de spot için
  yapılmıştı, 4h/futures için tekrarlanmalı.
- `-1021` saat kayması (ENGEL 3) hâlâ açık.

---

### 📋 SIRADAKİ OTURUM İÇİN HAZIR KOMUTLAR

```bash
python kontrol_4h.py              # sağlık + tempo
python testleri_calistir.py       # 476 test / 43 dosya geçmeli
python orderbook_kaydedici.py --ozet
```

Canlı tutarlılık betiği (tek seferlik, scratchpad'de değil — yeniden
yazılmalı ya da `tests/test_veri_tutarliligi.py` kullanılmalı).

**Bot durumu:** paper, 4h, 2 açık pozisyon (BNBUSDT + ETHUSDT,
~9 saattir açık), 0 kapanmış. Tempo ~2.7 işlem/gün → 100 işlem ≈ 38 gün.

⚠️ **K-59 sonrası bakiye SIFIRLANMADI** — gerekmiyor: taban yalnızca
%5'in altına düşünce devreye giriyordu, mevcut bakiye 9800 (başlangıcın
%98'i), yani hiç tetiklenmemişti. Mevcut veri temiz.

---

## ⏭️ BİRKAÇ HAFTA SONRA BURADAN DEVAM ET

**Durum (2026-09-05 18:30'da bırakıldı):** bot 4h ufkunda sağlıklı
çalışıyor, veri biriktiriyor. Kod tarafında bekleyen iş YOK.

**Sürüm:** v58 · 76 kök neden düzeltildi (K-12..88) · 476 test / 43 dosya.

🔴 **§0.48 OKU** (GitHub durumu — push bekliyor), sonra §0.46 (makine) ve §0.44 (açık soru)

**Bu oturumda (2026-09-13) yapılanlar — K-84..K-88:**
- K-84 tempo ölçümü 12 kat yanlıştı (açılan işlem sayıyordu,
  hüküm KAPANMIŞ ister). Düzeltildi, ikisi ayrı gösteriliyor.
- K-85 **zaman stop** eklendi: 24 saat = modelin etiket ufku
  (HEDEF_MAX_BAR × 4h). Paper + canlı ortak fonksiyon.
- K-86 **paper kaldıraç uygulamıyordu** (1x spot gibi). Artık
  canlı ile aynı kaynak; bakiyeden MARJİN düşülüyor.
- K-87 **fonlama (funding)** modellendi — hiç yoktu.
- K-88 **tasfiye (liquidation)** modellendi — zarar marjinle sınırlı.

**10. SIFIRLAMA YAPILDI** (2026-09-13 15:02). Sayaç 0/100.
Yedek: `data/_yedek_k37_20260913_150222`

⚠️ **İLK İŞ — ÜÇ ŞEYİ ÖLÇ** (hepsi artık yeni davranış):
```
python kontrol_4h.py      # KAPANMA hızı (önce 0.70/gün idi)
```
1. **Kapanış hızı arttı mı?** Zaman stop kapanışı garantiliyor.
2. **Erken kesme bedeli ne?** §0.14'te zararın %22'siydi.
   `SELECT durum, COUNT(*), AVG(pnl_yuzde) FROM trades
    WHERE mod='PAPER' AND durum!='ACIK' GROUP BY durum`
   → ZAMAN_STOP ile kapananların ortalaması SL/TP'ye göre nasıl?
3. **Fonlama ne kadar yiyor?** `/para` komutu veya
   `SELECT SUM(funding_maliyet) FROM trades WHERE mod='PAPER'`

⚠️ **PROTOKOL:** eşiklere DOKUNMA. 100 işlem dolmadan
`karar_kurali.py` sonucuna göre parametre değiştirmek hükmü
geçersiz kılar (§0).

🔴 **SIRADAKİ İŞ — 7. SIFIRLAMA BEKLİYOR (§0.14).** K-37 davranış
değişikliğidir; `python sifirla_k37.py` çalıştırılana kadar sayaç
karışık yapılandırma içerir. Betik hazır, gözden geçirilmeyi bekliyor.

⚠️ **AÇIK KARAR BEKLİYOR:** toplanan örneklem %100 TREND_UP ve 4/4 LONG;
tarihsel olarak barların %42'si düşüş rejimi. 100 işlem tek rejimden
gelirse hüküm "boğa piyasasında kârlı mı" sorusunu cevaplar. Ayrıntı ve
seçenekler §0.13'te — **kod değil protokol kararı.**

### 0. YENİ SOHBETE BAŞLARKEN (önce bunu oku)

Bu belge oturumlar arası tek hafızadır. Yeni sohbette ilk mesaj:
> "DEVAM_NOTLARI.md'yi oku"

Sonra §0 → §0.22 sırasıyla bakılırsa son durumun tamamı çıkar.
**§0.23 = son denetim: 6 hata (online etiket, /neden körlüğü, balina, -1021)
ve K-69 paper/canlı rejim kapısı eşitliği.**
**§0.18 = denetim: 6 sessiz hata (online öğrenme, Monte Carlo, A/B).**
**§0.15 = envanter: sistemde ne var, ne yok.**
Kritik özet:

| | |
|---|---|
| **Kod tarafı** | sağlam; ölçüm zinciri güvenilir |
| **Eksik olan** | SİNYAL — **9** hipotez ölçüldü, 9'u reddedildi (§0.15: klasik kurallar da) |
| **Ufuk** | 5m → 4h taşındı (§0.8-0.9). İmkânsız problemi zor probleme çevirdi |
| **Bekleyen** | ~41 gün veri (100 işlem), sonra `karar_kurali.py` |
| **Açık karar** | örneklem tek rejimden geliyor (§0.13) — protokol sorusu |

⚠️ **Yeni sohbette sıfırdan hipotez denemeden önce §0.3–0.11'i oku.**
Reddedilen 6 fikir orada gerekçesiyle yazılı; tekrar denemek zaman kaybı.

### 1. Önce sağlık (30 saniye)

```bash
python kontrol_4h.py
```

| gördüğün | anlamı |
|---|---|
| Tempo ~2-3 işlem/gün | ✅ normal |
| `10 dk'dan kısa işlem: 0` | ✅ artefakt yok |
| `SL < %1: 0` | ✅ ufuk doğru |
| 24 saatte 0 işlem | 🔴 bir kapı tıkıyor — logdan bak |
| Kısa süreli işlem var | 🔴 K-31 türü bir sorun geri gelmiş |

### 2. Sonra hüküm (100 işlem gerekiyorsa bekle)

```bash
python karar_kurali.py
```

Eşikler: **100 işlem**, beklenti > %0.10, t > 2.0.
Bu eşiklere DOKUNMA — veri görülmeden yazıldılar (§0).

### 2.5 İki kaynağı KARŞILAŞTIR (K-32/33 dersi)

Panel ile Telegram aynı büyüklüğü farklı gösteriyorsa hata vardır.
İkisi de yeşil testlerden geçerken çelişebiliyorlar:

```bash
curl -s http://127.0.0.1:8080/api/state | python -c "import sys,json;d=json.load(sys.stdin);print(d['bot_istatistik'], round(d['paper_bakiye'],2))"
python -c "from data.database import win_rate_hesapla; print(win_rate_hesapla('PAPER'))"
```
İşlem sayısı ve win rate AYNI olmalı.

### 3. Kod değişikliği yaptıysan

```bash
python testleri_calistir.py     # 476 test / 43 dosya geçmeli
```

### ⚠️ HÜKMÜ OKURKEN İKİ TUZAK

Bu oturumda ikisine de yakalanmak üzereydik:

1. **Sürüklenme ≠ edge.** "Beklenti pozitif" yetmez; örneklem boğa
   piyasasıysa rastgele giriş bile pozitif çıkar. Doğru ölçü
   `P(TP) − taban oran`. (§0.8, §0.11)
2. **Küçük örneklemde temiz desen çöker.** 57 gözlemlik bir "keşif"
   1259 gözlemde yok oldu. (§0.3)

### 📌 BİLİNEN DURUM: EDGE HENÜZ YOK

Altı hipotez ölçüldü, altısı reddedildi (§0.3–0.11):
R/R optimizasyonu · üçlü bariyer · uzun eğitim penceresi ·
feature azaltma · piyasa yapısı feature'ları · skor dekorelasyonu

**Kod tarafı sağlam, ölçüm zinciri güvenilir. Eksik olan sinyal.**
4h'e geçiş bunu çözmedi — imkânsız problemi (5m'de 20.6 puanlık
beceri farkı) zor probleme (1.3 puan) çevirdi.

### 🔍 DENENMEMİŞ FİKİRLER

- ✅ **Order book derinliği**: KAYIT BAŞLADI 2026-09-05 (K-38, §0.14).
  Birkaç hafta biriktikten sonra denenebilir. `python orderbook_kaydedici.py --ozet`
- **Kesitsel (cross-sectional) formülasyon**: "hangi coin diğerlerinden
  iyi yapacak" — beta tanım gereği sadeleşir, sürüklenme tuzağı yapısal
  olarak imkânsız. Ölçüm betiği yazıldı (`scratchpad/kesitsel_olc.py`),
  ÇALIŞTIRILMADI. Sınır: evren yalnızca 5 coin.
- **Rejim bazlı ayrı modeller** (3 yıl veride birden çok rejim var)
- **1d ufku**: beceri farkı 0.2 puan (4h'de 1.3) — daha da kolay,
  ama işlem sıklığı çok düşer

---

## 1. DURUM ÖZETİ (30 saniyede)

| | |
|---|---|
| Sürüm | v58 (temel: v57) |
| Düzeltilen hata | 77 (v56) + 11 (v57) + **50 kök neden** (v58) |
| Test | **554** (54 dosya), hepsi geçiyor |
| Kod kapsamı | **%39** (başlangıç %34) |
| `main.py` | 2827 satır (başlangıç 3079) |
| pyflakes tanımsız isim | 0 |
| Çalışma modu | **TESTNET CANLI** (`LIVE_TRADING=true`, testnet URL'leri) + paper paralel |
| Paper işlem sayacı | 4h'de birikiyor — güncel değer için `python kontrol_4h.py` |
| v58 düzeltmeleri | K-12..36 — bot 2026-09-05 16:33'te yeniden başlatıldı |
| ⚠️ Yeniden başlatma | K-36 `core/market_regime.py`'yi değiştirdi — **etkili olması için bot yeniden başlatılmalı** |
| **Gerçek paraya hazır mı** | **HAYIR** — bkz. bölüm 3 |

### Doğrulama komutu (her değişiklikten sonra çalıştır)
```bash
python testleri_calistir.py
```
Beklenen: `✅ TÜM TESTLER BAŞARILI` (543 test, 53 dosya)

**v57:** Test koşusu artık üretim verisine YAZMIYOR. Koşudan sonra paper
sayacının artmaması **beklenen** davranıştır (eskiden her koşu 11 sahte
işlem ekliyordu — bkz. `CHANGELOG_v57.md` K-1).

---

## 2. ŞU AN NE ÇALIŞIYOR

Paper modda veri topluyor — **YEREL makinede** (Windows zamanlanmış görevi
`ASTRA_Bot`). 2026-08-25'te Contabo sunucusuna taşındı, 08-26'da kullanıcı
kararıyla yerele geri dönüldü. Sunucu kurulumu duruyor ama kapalı — bkz. §8.0.

```bash
python main.py bot          # elle başlatma (klasik yol)
baslat_bot.bat              # çift-çalıştırma korumalı başlatıcı
```
- `bot` modu = trading döngüsü + Telegram birlikte
- Panel: http://127.0.0.1:8080 (yalnızca localhost)
- Telegram: @Astrabrookerbot, 38 komut, yetkilendirme aktif

### Oto-başlatma (v57)
**Neden eklendi:** Bot yeniden başlatmadan sağ çıkmıyordu. 2026-08-20'de
başlatılan süreç makine kapanınca öldü; makine 08-21 09:22'de açıldı ama bot
12:50'ye kadar çalışmadı → **~14 saat veri kaybı**. 100 işlem / 3 hafta hedefi
sürekli çalışmayı gerektiriyor.

```powershell
Get-ScheduledTask -TaskName ASTRA_Bot          # durum
Start-ScheduledTask -TaskName ASTRA_Bot        # elle başlat
Stop-ScheduledTask  -TaskName ASTRA_Bot        # durdur
Unregister-ScheduledTask -TaskName ASTRA_Bot   # kaldır
```

Laptop için kritik iki ayar açıkça kapatıldı (varsayılanlar hedefi bozardı):
- `DisallowStartIfOnBatteries=False` → pilde de başlar
- `ExecutionTimeLimit=PT0S` → 3 günlük varsayılan öldürme limiti yok

### Güç ayarı — PRİZDE UYKU KAPALI (2026-08-24)
Makine 10 dakika boşta kalınca uyuyordu; bot yalnızca kullanıcı başındayken
çalışıyordu (ölçüm: ortalama **1.8 saat/gün**). Değiştirildi:

```powershell
powercfg /change standby-timeout-ac 0     # prizde uyku: ASLA
powercfg /change hibernate-timeout-ac 0   # prizde hazırda bekletme: ASLA
# Pilde 10 dk KORUNDU (pil boşalmasın)
# Geri almak için: powercfg /change standby-timeout-ac 10
```

⚠️ **Bot yalnızca makine PRİZDEYKEN kesintisiz çalışır.** Fişi çekilirse
10 dk sonra uyur ve veri toplama durur (watchdog artık bunu donma sanmıyor
— v57 K-7).

**Tetikleyici İKİ tanedir — ikisi de gerekli:**
1. `LogonTrigger` → yeni açılış/oturumda botu başlatır
2. `TimeTrigger` (başlangıç sabit, `PT10M` tekrar) → **watchdog**; bot ölürse
   10 dk içinde ayağa kaldırır

**TUZAK — repetition'ı LogonTrigger'a bağlama.** İlk kurulumda tekrar
`LogonTrigger`'a bağlanmıştı. Windows'ta logon tetikleyicisinin tekrar
penceresi ancak **logon olayı ateşlendiğinde** başlar; görev logon'dan SONRA
kurulduğu için tetikleyici hiç ateşlenmedi ve watchdog hiç planlanmadı.
Bot kasten öldürüldü, 8.5 dakika geri gelmedi. Zamana dayalı ayrı bir
tetikleyici eklenince 21:38:04 planına karşı 21:38:05'te geri geldi.

**Doğrulama yöntemi (kuruşuna kadar):** `NextRunTime` DOLU olmalı.
Boşsa hiçbir çalışma planlanmamıştır — görev "Ready" görünse bile watchdog
YOKTUR.
```powershell
(Get-ScheduledTaskInfo -TaskName ASTRA_Bot).NextRunTime   # boş olmamalı
```
Periyodik tetikleme güvenli, çünkü `baslat_bot.bat` çalışan bot varsa çıkıyor.

**Çift çalıştırma:** `baslat_bot.bat` çalışan bir `main.py bot` varsa çıkar.
Python tarafında tek-instance kilidi YOK — koruma yalnızca bu betikte.
Botu başka yolla başlatırsan aynı DB'ye iki bot yazabilir (sayaç ve bakiye
bozulur). Her iki yön de test edildi: bot varken engelliyor, yokken başlatıyor.

İlerleme kontrolü:
```bash
python -c "from data.database import win_rate_hesapla, toplam_pnl; w=win_rate_hesapla('PAPER'); print(f\"islem:{w['toplam'] or 0} winrate:%{w['win_rate']} pnl:{toplam_pnl('PAPER'):+.2f}\")"
```

**Hedef: 100 kapanmış işlem / 3 hafta** (`CANLI_GECIS_PROTOKOLU.md` Aşama 1).

⚠️ **Sayaç 2026-08-20'de GERÇEKTEN sıfırlandı.** Öncesinde 33 gösteriyordu ama
o 33 işlemin tamamı **test artefaktıydı** — test paketi üretim veritabanına
yazıyordu (v57 K-1). Kanıt: 67 kaydın en uzun süresi 0.255 saniye ve yalnızca
3 farklı giriş fiyatı vardı. Bot o dönemde hiç çalışmamıştı.
Sayım bugünden itibaren geçerli.

---

## 3. GERÇEK PARAYA GEÇİŞİN ÖNÜNDEKİ ENGELLER

### ✅ ENGEL 1 — ÇÖZÜLDÜ VE KODLANDI (2026-08-26)

**Sebep bulundu:** Koşullu emirler klasik `/fapi/v1/order`'dan **Algo
Service**'e taşınmış. Binance'in kendi hata mesajı artık bunu söylüyor:

```
-4120: "Order type not supported for this endpoint.
        Please use the Algo Order API endpoints instead."
```

**Testnet'te TAM YAŞAM DÖNGÜSÜ doğrulandı** (koy → listede gör → iptal et):
`POST /fapi/v1/algoOrder` HTTP 200, `algoId=1000000181546843`.
Projede stop-loss yerleştirmenin ilk kez doğrulanması bu.

**Şema `BINANCE_ALGO_EMIR_SEMASI.md`'de** — deneyerek çıkarıldı, tahmin yok.
Kilit farklar: `algoType=CONDITIONAL` (yeni, zorunlu), `stopPrice` →
**`triggerPrice`**, yanıtta `orderId` → **`algoId`**.

⚠️ **EN KRİTİK TUZAK:** Algo emirleri klasik `GET /fapi/v1/openOrders`
listesinde **GÖRÜNMÜYOR** (ayrı `openAlgoOrders` endpoint'i var). Yani
`order_reconciler` "SL var mı" kontrolünü klasik listeye yaparsa **SL'i
göremez** → korumasız pozisyon sanıp gereksiz kapatır, ya da
`futures_stop_loss_koy` eski SL'i iptal edemeyip **üst üste SL biriktirir**.
Bu, fail-open deseninin yeni yüzü (§5.1).

**KOD YAZILDI ve testnet'te UÇTAN UCA doğrulandı** (pozisyon aç → SL koy →
reconciler görüyor → temizle). Değişenler:

| Yer | Ne oldu |
|---|---|
| `futures_stop_loss_koy` / `_take_profit_` / `_partial_tp_` / `_trailing_` | algo endpoint'ine taşındı |
| `koruma_emirleri()` (YENİ) | klasik + algo listelerini BİRLEŞTİRİR, algo kaydını normalize eder |
| `acik_algo_emirler()`, `algo_emir_iptal()` (YENİ) | algo listeleme/iptal, `strict` destekli |
| `order_reconciler`, `failsafe_liquidation`, `position_state`, `fill_reconciler`, `state_audit`, `main.py` RECOVERY | hepsi `koruma_emirleri()` kullanıyor |
| `_futures_istek` | idempotency algo yoluna genişletildi (`clientAlgoId`) |
| `preflight` | `exchangeInfo` yerine algo endpoint erişimini kontrol ediyor |

**İki tuzak koda gömüldü (testnet'te ölçüldü):**
1. `TRAILING_STOP_MARKET` + `closePosition` → `-4136` ile REDDEDİLİYOR.
   `quantity` kullanılmalı. Naif taşıma trailing korumayı sessizce öldürürdü.
2. `"/order" in "/fapi/v1/algoOrder"` **FALSE** — v53 çift-emir koruması
   algo yolunda sessizce devre dışıydı. `clientAlgoId` ile kapatıldı
   (testnet: ikinci istek `-4116` ile reddediliyor).

**Production'da denenmedi** — endpoint'ler orada da var (probe ile
doğrulandı) ama emir yerleştirme gerçek para gerektirir. Aşama 2'de
doğrulanacak.

### ⛔ (ESKİ KAYIT) Stop-loss doğrulanamadı — çözülmeden önceki durum

Binance Futures **testnet** tüm koşullu emirleri `-4120` ile reddediyor:
`STOP_MARKET`, `STOP`, `TAKE_PROFIT_MARKET`, `TRAILING_STOP_MARKET`.
Koşulsuz emirler (MARKET/LIMIT) çalışıyor — yani anahtar ve endpoint sağlam.

6 farklı parametre kombinasyonu denendi, hepsi reddedildi.
`exchangeInfo` STOP_MARKET'i "destekliyor" diye beyan ediyor ama endpoint
reddediyor — testnet ile production ayrışmış.

**Production'ın kabul edip etmediği BİLİNMİYOR** (gerçek parayla test edilmedi).

**YAPILACAK:** Binance API dokümantasyonu/desteğine sor: `/fapi/v1/order`
üzerinden STOP_MARKET hâlâ destekleniyor mu? `-4120` yeni bir değişiklik mi?

➡️ **Gönderilecek metin HAZIR: `BINANCE_4120_SORUSU.md`** (2026-08-24).
İngilizce yazıldı (destek İngilizce çalışıyor), `<<<...>>>` işaretli iki yeri
doldurup göndermeniz yeterli. Tam hata çıktısı için:
`python testnet_emir_dogrula.py`. **Anahtar/secret yapıştırmayın.**
Belgede cevaba göre 3 senaryonun ne anlama geldiği de yazılı.

**İyi haber:** SL konulamazsa bot pozisyonu DERHAL kapatıyor
(testnet'te 6/6 doğrulandı, sıfır sızıntı). Yani zarar riski değil,
"işlem açılamıyor" durumu.

### ✅ ENGEL 3 — `-1021` ÇÖZÜLDÜ (2026-09-06, §0.23 K-63)

> **Teşhis YANLIŞTI: saat kayması değilmiş.** Ölçüldü — yerel saat
> Binance'ten yalnızca +25 ms sapıyor. Gerçek sebep: 429 rate-limit
> uykusundan sonra BAYAT timestamp gönderilmesi. Düzeltildi,
> muhafızı yazıldı (`tests/test_ogrenme_ve_teshis.py`).
> Aşağıdaki eski kayıt, teşhisin nasıl yanlış konduğunu göstermek
> için DURUYOR — `w32tm /resync` önerisi bu hatayı çözmezdi.

### ⛔ (ESKİ KAYIT) saat kayması sanılan sorun

`logs/astra.log`'da **127 kez**, 09-04'ten beri **35 farklı saatte**.
Saat offset'i yenileniyor ama 3 denemede başarısız oluyor:

```
[FUTURES] /fapi/v3/positionRisk — 3 denemede başarısız.
          [-1021] Timestamp for this request is outside of the recvWindow.
```

**Paper modda zararsız** (K-33'ten sonra futures bakiyesi kullanılmıyor).
**Canlıda ciddi:** pozisyon sorgusu başarısız olursa koruma döngüsü
durumu doğrulayamaz — order_reconciler / failsafe_liquidation hepsi
`koruma_emirleri()` üzerinden borsaya soruyor. §5.1'in `strict=True`
deseni istisna yükseltiyor (sessiz değil), ama bu sıklıkta canlıya
geçilmemeli.

**Yapılacak:** Windows saat senkronunu düzelt (`w32tm /resync`,
NTP kaynağı), sonra sıklığı yeniden ölç. Gerekirse `recvWindow`
büyütülür — ama önce KÖK NEDEN (saat kayması) bakılmalı; recvWindow
büyütmek belirtiyi gizler.

### 🟡 ENGEL 4 — KAPI EŞİTLİĞİ ÇÖZÜLDÜ, KALİBRASYON AÇIK (§0.17, K-69)

K-37 `ai_score` aralığını `[−6,+8]` → `[−3,+6]` daralttı ama
`REGIME_VOLATILE_MIN_AI=6` / `REGIME_BEAR_MIN_AI=7` sabit kaldı.
K-69'dan sonra paper ve canlı aynı ortak kapıyı kullanıyor; **paper
artık canlıdan farklı işlem açmayacak.** Bu nedenle 100 işlemlik
örneklem kapı davranışı açısından temsilîdir.

Ama BEAR+VOLATILE tarihsel barların **%35'i**. BEAR `7` eşiği yeni
skor ölçeğinde erişilemez, VOLATILE `6` çok nadir. Bu, botun o
rejimlerde bilinçli olarak susması mı, yoksa yanlış kalibrasyon mu?
Bu soru ölçülmeden cevaplanamaz; canlıya geçmeden önce strateji kararı
olarak ele alınmalı.

### ⛔ ENGEL 2 — Paper verisi yok (SÜREÇ)

**Karar kuralı YAZILDI (2026-08-26, n=7 iken): `python karar_kurali.py`**
Eşikler veri görülmeden belirlendi — sonradan değiştirmek protokolü
geçersiz kılar. Ana ölçüt **beklenti + t>2**, win rate değil
(bu sistemde başabaş win rate %18, protokolün %42 eşiği yanlıştı).

⚠️ **İstatistiksel anlamlılık ~19 işlemde gelebilir** (mevcut varyansla
n = (2·σ/μ)² ≈ 19). Ama **100 işlem yine de gerekli**: kill switch
davranışı, zarar dönemi ve rejim çeşitliliği ancak orada görülür.
Erken "t>2 oldu, geçelim" demeyin.

0 / 100 kapanmış işlem. Kısayol yok, beklemek gerekiyor.

**v57 uyarısı:** Bu sayaca güvenmeden önce kaynağını doğrula. 2026-08-20'ye
kadar sayaç test koşularıyla doluyordu; 100'e ulaşsaydı tamamen sentetik
veriyle gerçek paraya geçilecekti. Artık `tests/test_izolasyon.py` bunu
engelliyor. **Sayaç beklenmedik şekilde atlarsa** işlem sürelerine bak:
gerçek paper işlemi dakikalar sürer, artefakt milisaniyeler.

### ⏱️ "3 hafta" HEDEFİ GERÇEKÇİ DEĞİL — makine uyuyor

Ölçüm (2026-08-21…24, bot çalışma süresi log aktivitesinden):

| Gün | Botun çalıştığı süre |
|---|---|
| 08-21 | 340 dk (5.7 s) |
| 08-22 | **0 dk** (makine kapalı) |
| 08-23 | 83 dk (1.4 s) |
| 08-24 | 13 dk |

Windows uyku kaydı: 08-23 01:48→15:50 (14 s), 08-23 22:47→08-24 21:11 (22.4 s).
**Ortalama ~1.8 saat/gün.**

**Güç ayarı 08-24'te düzeltildi** (prizde uyku ASLA) ve makine gece boyunca
açık kaldı — yalnızca 3 dakikalık tek bir uyku oldu. Uyku artık darboğaz
değil.

### Ölçülen GERÇEK tempo (2026-08-25, kesintisiz koşu)

| | |
|---|---|
| Sayaç sıfırlandı | 08-24 21:31 |
| İlk pozisyon açıldı | 08-25 06:12 (**8.7 saat sonra**) |
| 12 saatte açılan | **1** |
| 12 saatte kapanan | **0** |

**100 işlem ≈ 50 gün (~7 hafta)** — makine 7/24 açıkken bile.

⚠️ **ÖNCEKİ TAHMİN YANLIŞTI.** 08-24'te "makine hiç uyumazsa ~10 gün"
yazmıştım; o hesap test artefaktı ve eski SL modeliyle kirlenmiş 3 işleme
dayanıyordu. Temiz ölçüm 5 kat daha yavaş.

### Darboğaz NEDİR (ölçüldü, tahmin değil)

Son 20k log satırındaki paper reddi dağılımı:

| Sebep | Adet |
|---|---|
| Max açık pozisyon (1/1) | 186 |
| AI skor eşiği | 112 |
| Güven eşiği | 52 |

Karar dağılımı: 440 WAIT, 150 SELL, 8 BUY.

İki bağlayıcı kısıt var:
1. **`MAX_OPEN_POSITIONS=1`** — bir pozisyon açıkken diğer tüm coinler
   reddediliyor. Pozisyonlar saatlerce açık kalıyor.
2. **Sinyal eşikleri** — slot boşken bile 8.7 saat giriş yapılmadı.

**Bu bir hata DEĞİL, stratejinin seçiciliği.** v56 notu zaten öngörmüştü:
"Bu tempoda 100 işlem haftalar sürer — normal."

### Hızlandırma seçenekleri ve BEDELİ

⛔ `MAX_OPEN_POSITIONS` veya sinyal eşiklerini **veriyi hızlandırmak için
değiştirme.** Paper, canlıda çalıştırılacak yapılandırmayı birebir
yansıtmalıdır (§5.3). Aksi halde 100 işlem, canlıda olmayacak bir
sistemin verisi olur ve tüm bekleyiş boşa gider.

**Doğru soru:** "Canlıda hangi yapılandırmayla çalışacağım?" Cevap neyse
paper ONU kullanmalı. Coin sayısını artırmak (şu an 5) işlem başına riski
değiştirmez ve tempoyu yükseltir — ama yalnızca canlıda da o evrenle
çalışacaksanız meşrudur.

**Seçenekler:** (a) bot çalışırken uykuyu kapat (`powercfg`), (b) her zaman
açık bir makinede/VPS'te çalıştır, (c) daha uzun takvimi kabul et.

### ⚠️ Not: Gözlemlenen seçicilik
10 dakikalık çalışmada 14 coin analizinin **11'i chop filtresiyle vetolandı**
(piyasa yatay). Bu tempoda 100 işlem haftalar sürer — normal.

---

## 4. ÇALIŞMA KURALLARI (bu oturumda oturmuş)

### 4.1 Testlerin yeşil olması bu kod tabanında KANIT DEĞİL
Bu, oturumun en önemli dersi.
- v55 changelog'u `duplicate_guard` fail-safe'inin düzeltildiğini yazıyordu.
  **Düzeltilmemişti.** Testi de yanlış katmanı mock'ladığı için geçiyordu.
- `test_paper_dusuk_skor_reddedilir` sonunda `assert True` vardı —
  başarısız OLAMAZ bir testti.
- `test_edge_engine_engeller` yanlış sebeple geçiyordu (mock yanlış yerdeydi).

**Kural:** Her veto/engelleme testinin yanına **kontrol testi** yaz.
"Hiçbir zaman izin verme" davranışı da veto testlerini geçer.
Örnek: `test_tum_kapilar_acikken_emir_gonderilir`.

**v57 eklemesi — testin kırmızıya dönebildiğini KANITLA.** Yeni bir muhafız
testi yazınca korumayı kasten boz ve testin gerçekten patladığını gör.
`test_paper_islemi_uretim_dosyalarina_dokunmaz` böyle doğrulandı: `izole_et()`
geçici olarak etkisizleştirildi, test beklenen mesajla kırmızıya döndü, mutasyon
geri alındı. Bu adım atlanırsa elde "hiç başarısız olamayan" bir test kalır.

### 4.2 Statik analiz yetmiyor — ÇALIŞTIR
77 hatanın **19'u** yalnızca çalıştırınca bulundu:
paper modu, panel tarayıcıda, testnet emirleri, gerçek Telegram API'si.

### 4.3 Hata iddia etmeden ÖNCE kodu oku
Bu oturumda 3 kez "hata buldum" sandım, üçünde de **kod doğruydu, testim yanlıştı**:
- `marjin_kontrol` parametre sırası
- `-1021` testinde sabit offset mock'u
- `_strateji_onay` dict yerine bool tutuyor

### 4.4 Kimlik bilgilerini asistan YAZMAZ
API anahtarı, bot token gibi değerleri `.env`'e kullanıcı kendi girer.
İzin verilse de değişmez. CHAT_ID gibi kimlik olmayan değerler yazılabilir.

**Sohbette paylaşılan her anahtar yanmış sayılır** — yenilenmeli.

### 4.5 Refactor ve bugfix AYNI adımda yapılmaz
Bir sorun çıkarsa hangisinden kaynaklandığı belirsizleşir.
Örnek: `risk_hesapla()` yön hatası taşınırken KASITLI düzeltilmedi.

### 4.6 Testler ÜRETİM durumuna yazmamalı (v57)
v56'ya kadar her test koşusu `astra.db`'ye 11 sahte işlem, `journal.db`'ye 12
satır (biri `mod='LIVE'`), `model_registry.db`'ye 2 versiyon ekliyor,
`ab_test.json`'u eziyordu. Sonuç: canlıya geçişi yöneten sayaç sahteydi.

**Kural:** Yeni test yazarken gerçek bir motoru (`PaperTrader`,
`ExecutionEngine`, `TradeJournal`) çağırıyorsan, dosyanın başındaki
`from tests.izolasyon import izole_et; izole_et()` satırının **proje modülleri
import edilmeden önce** olduğunu doğrula. `config.py` yolları import ANINDA
okur; geç çağrı sessizce etkisiz kalır.

**Yeni kalıcı dosya eklersen:** yolunu env ile yönlendirilebilir yap
(sabit kodlama), `tests/izolasyon.py`'deki `URETIM_YOLLARI` listesine ve
`izole_et()` içine ekle. Aksi halde o dosya sessizce korumasız kalır.

**Kirlilik ölçüm yöntemi — BOT ÇALIŞIRKEN parmak izi/satır sayısı KULLANMA.**
Bot 7/24 çalıştığı için `astra.db` ve `logs/astra.log` meşru şekilde sürekli
değişir. Önce/sonra hash karşılaştırması botun yazımlarını "test kirliliği"
sanar (bu oturumda bir kez yanlış alarm verdi).

Bunun yerine **sentetik imza say** — bot bunları asla üretmez:
```bash
grep -c '63018\.9' logs/astra.log                 # fikstür fiyatı
grep -cE 'RANDUSDT|TESTUSDT' logs/astra.log        # uydurma semboller
sqlite3 data/astra.db "SELECT COUNT(*) FROM trades WHERE giris_fiyat IN (63018.9,2000.6,0.50015)"
sqlite3 data/journal.db "SELECT COUNT(*) FROM journal WHERE mod='LIVE'"
```
Bu sayılar koşu öncesi ve sonrası AYNI kalmalı.

**Muhafız testi de aynı sebeple yeniden tasarlandı:** parmak izi yerine
kodun FİİLEN kullandığı yolları doğruluyor (`data.database.DB_PATH`,
`journal._db`, logging `baseFilename`). Bu deterministik — bot çalışsa da
çalışmasa da aynı sonucu verir. Rastgele kırmızıya dönen muhafız,
olmayan muhafızdan beterdir: görmezden gelinir.

**Log da izole edilir** (`ASTRA_LOG_DIR`). Öncesinde testler üretim
`logs/astra.log`'una sentetik satır yazıyordu; veri bozulmuyordu ama teşhis
kaydı güvenilmezdi. **Not:** 2026-08-23 öncesine ait ~520 satır fikstür
kalıntısı logda DURUYOR (silinmedi, tarihsel kayıt). Eski logu incelerken
63018.9 / RANDUSDT / TESTUSDT içeren satırları gerçek işlem sanma.

---

## 5. MİMARİ: BİLİNMESİ GEREKENLER

### 5.1 Fail-open deseni — bu kod tabanının ana hastalığı
"Bilmiyorum" durumu "sorun yok" olarak kodlanmıştı. Düzeltilen örnekler:
- `acik_futures_pozisyonlar()` hata → `[]` (= "hiç pozisyon yok")
- `futures_bakiye()` hata → `0.0` (= "param yok")
- `preflight` Binance kontrolü **asla başarısız olamıyordu**

**Çözüm deseni:** `strict=True` parametresi. Güvenlik-kritik çağrılar
bunu kullanmalı; hata durumunda istisna yükselir.

```python
acik_futures_pozisyonlar(strict=True)   # sync/guard için ZORUNLU
futures_bakiye(strict=True)             # teşhis/kurulum için
```

**Yeni kod yazarken:** "sıfır" ile "sorgulayamadım" ayrımını koru.

### 5.2 Sessiz başarısızlık
Güvenlik kontrolü çöküşleri `log.debug`'a yazılıyordu → 3 `NameError`
aylarca fark edilmedi (biri gerçek bir risk kapısını ölü bıraktı).

**Kural:** Ağ/borsa çağrısı DIŞINDAKİ `except Exception → log.debug`
kabul edilemez. Koruma thread'leri catch-all ile yaşamalı.

**v57 örneği — sessiz başarısızlık yalnızca `except` değil:** `get_journal()`
singleton'ı ilk çağrıya göre sabitleniyordu. İkinci bir çağrı FARKLI bir yol
isterse sessizce eski instance dönüyordu. Hiçbir istisna yok, hiçbir log yok —
ama journal iki dosyaya bölünüyordu. Artık `log.error` basıyor.
**Genel kural:** "istenen ≠ yapılan" olduğu her yerde sesli ol.

### 5.2.1 Koruyucu döngü, ana thread ölürse İŞE YARAMAZ (v57 K-3)
Trading motoru daemon thread'de kendi `while True` koruyucusuyla çalışıyordu.
Ama ana thread `telegram_bot_baslat()` dönünce bitiyor, Python çıkıyor ve
**daemon thread öldürülüyordu**. Motoru öldüren kendi istisnası değil,
başka bir thread'in sessizce sona ermesiydi.

**Kural:** Daemon thread'e güvenlik-kritik iş verdiysen, ana thread'in
o iş bitene kadar YAŞADIĞINI garanti et. "Ana thread ne zaman biter?"
sorusunu her `bot`/`live` giriş noktası için cevaplayabilmelisin.
Bu hata 2+ gün veri kaybettirdi ve hiçbir test yakalamadı — çünkü testler
fonksiyonları çağırıyor, süreç yaşam döngüsünü değil.

### 5.3 paper ↔ canlı eşitliği
Protokolün tamamı buna dayanıyor. Bu oturumda **3 hata** bunu bozuyordu:
1. Paper maliyet modellemiyordu (komisyon+slippage) → düzeltildi
2. Paper bakiyesi sessizce sızdırıyordu → düzeltildi
3. Paper risk limitlerini uygulamıyordu (3 pozisyon açtı, canlı 1'e izin verir) → düzeltildi
4. **(v57)** Paper VERİSİ test artefaktıyla karışıyordu → düzeltildi.
   Eşitliğin bozulması için kodun yanlış olması gerekmiyor; ölçüm verisinin
   kirlenmesi de yeter.
5. **(v57)** SL/TP dolum modeli canlıdan farklıydı → düzeltildi.
   Paper ve backtest pozisyonu `guncel_fiyat`tan (bar kapanışından)
   kapatıyordu; canlıda SL borsada duran `STOP_MARKET`'tir ve SEVİYEDE
   tetiklenir. Ölçülen vaka: BNBUSDT SHORT, bot 2 gün kapalıyken fiyat
   stop'u %2 aştı ve zarar **%3.27** yazıldı — olması gereken %1.09'un
   3 katı. Artık seviyeden (+aleyhte slippage) dolduruluyor.
   **Uyarı:** Gerçek gap'te canlı dolum stop'tan kötü olabilir; yeni model
   bunu yakalamaz, yani hafif iyimser.

**Yeni özellik eklerken sor:** Bu paper'da da canlıdaki gibi davranıyor mu?
**Ve:** Bu özelliğin ürettiği veri, ölçtüğüm veriye karışıyor mu?

### 5.3.1 Testnet fiyatları GERÇEK piyasayı izliyor (2026-08-25 doğrulandı)
`.env` hem spot hem futures için testnet'e ayarlı
(`testnet.binance.vision`, `testnet.binancefuture.com`). "Paper verisi
sahte piyasadan mı geliyor?" sorusu doğrudan ölçüldü:

| Sembol | Testnet | Gerçek | Fark |
|---|---|---|---|
| BTCUSDT | 80.872,70 | 80.866,00 | %0,008 |
| ETHUSDT | 2.513,88 | 2.513,14 | %0,03 |
| SOLUSDT | 101,67 | 101,64 | %0,03 |

Futures tarafında fark biraz daha yüksek (~%0,11) ama SL mesafelerine
(%1–3) göre önemsiz. **Sorun yok — bu soruyu tekrar araştırma.**

### 5.4 Ölçülen gerçek değerler (testnet)
- Round-trip maliyet: **%0.089** (model %0.08 — yakın, hafif iyimser)
- Market emri slippage: **%0.006**
- `min_notional`: BTCUSDT **50**, ETHUSDT **20**, SOL/XRP **5** USDT

---

## 6. YAPILMAYI BEKLEYEN İŞLER (öncelik sırasıyla)

### 6.0 ~~Veto zincirini ortak modüle çıkar~~ ✅ **YAPILDI (K-97, §0.39)**
`_execution_isle` içindeki chop / MTF / EdgeEngine / strateji vetoları
`main.py`'ye gömülü olduğu için paper onları çağıramıyor. Paper'ın
çıkışı bu yüzden canlıdan hâlâ GEVŞEK (K-13 kısmen çözüldü).
Zincir `core/veto_zinciri.py` gibi ortak bir modüle çıkarılıp iki
yoldan da çağrılmalı. `tests/test_veto_zinciri.py` (15 test) zaten
davranışı kilitliyor, yani taşıma nispeten güvenli.

### 6.1 ~~Binance `-4120` araştırması~~ ✅ **ÇÖZÜLDÜ (2026-08-26)**
Bkz. §3 ENGEL 1: Algo Order API'ye taşındı, testnet'te uçtan uca
doğrulandı. Bu satır bayat kalmıştı.

### 6.2 Telegram komutlarını taşı (475 satır, güvenli)
`main.py` 2350 civarına iner. Emir yolunda değil, para riski yok.
36 adet `cmd_*` fonksiyonu → `telegram/commands.py`
**Zorluk:** onlarca global singleton'a bağlılar (bağlam nesnesi gerekir).

### 6.3 `coin_analiz` / `futures_dashboard` / `_execution_isle` taşı
1146 satır. `_execution_isle`'ın veto zinciri artık test edildiği için
(15 test) taşınması eskisinden güvenli. Diğer ikisi hâlâ riskli.
**Önce test yaz, sonra taşı.**

### 6.4 Kapsamı yükselt
En zayıf: `market_data.py` %10, `db_manager.py` %18, `main.py` %24.

### 6.5 Ölü kod temizliği
- `execution/order_ack.py` — %0 kapsam, hiç import edilmiyor.
  Canlı yol `fill_verify()` kullanıyor. Ya bağla ya sil.
- `simulation/exchange_simulator.py::emir_sim()` — hiç çağrılmıyor.

### 6.6 Bilinen küçük sorun
`risk_hesapla()` yön parametresi almıyor → SELL sinyallerinde Telegram
raporunda SL/TP ters görünüyor. **Emirler etkilenmez**
(gerçek yol `sl_tp_hesapla` kullanıyor), yalnızca raporlama.

---

## 7. DOSYA HARİTASI (bu oturumda eklenenler)

| Dosya | Ne işe yarar |
|---|---|
| `CHANGELOG_v56.md` | 77 hatanın tam listesi ve gerekçeleri |
| `DENETIM_RAPORU_v55.md` | Orijinal denetim (132 dosya, 58 bulgu) |
| `testnet_emir_dogrula.py` | Emir yaşam döngüsü doğrulaması (9 adım) |
| `telegram_chat_id_bul.py` | CHAT_ID bulucu |
| `core/telegram_gonderim.py` | Telegram gönderim (main.py'dan taşındı) |
| `core/sinyal_skor.py` | Feature + skorlama (main.py'dan taşındı) |
| `tests/test_para_yolu.py` | Boyutlandırma, risk limitleri, yuvarlama (25) |
| `tests/test_guvenlik_agi.py` | SL zorla-kapat, reconciler (12) |
| `tests/test_imza_retry.py` | HMAC imza, idempotent retry, rate limit (19) |
| `tests/test_veto_zinciri.py` | `_execution_isle` 13 güvenlik kapısı (15) |

### v57'de eklenenler

| Dosya | Ne işe yarar |
|---|---|
| `CHANGELOG_v57.md` | Test izolasyonu + journal yol hatası, tam gerekçe |
| `tests/izolasyon.py` | **Önyükleyici** — durum yollarını geçici dizine yönlendirir |
| `tests/test_izolasyon.py` | Muhafız + kontrol testleri (9) |
| `temizle_test_artefakti.py` | Tek seferlik geçmiş kirlilik temizliği (çalıştırıldı) |
| `baslat_bot.bat` | Çift-çalıştırma korumalı başlatıcı (görev bunu çağırır) |
| `logs/bot_autostart.log` | Oto-başlatılan botun stdout/stderr çıktısı |
| `tests/test_ana_thread.py` | Ana thread ölürse motor da ölür — K-3 muhafızı (7) |
| `tests/test_sl_dolum.py` | SL/TP seviyeden dolmalı — K-5 muhafızı (8) |
| `tests/test_watchdog_uyku.py` | Uyku ≠ donma ayrımı — K-7 muhafızı (6) |
| `sayaci_sifirla.py` | Paper sayacını sıfırlar (2026-08-24'te çalıştırıldı) |
| `BINANCE_4120_SORUSU.md` | Binance'e gönderilecek hazır teknik metin |
| `sunucu/KURULUM.md` | Contabo sunucu kurulum kontrol listesi |
| `sunucu/PUTTY_ADIMLARI.md` | Windows/PuTTY tarafı: anahtar, transfer, tünel |
| `astra_kurulum.tar.gz` | Transfer arşivi (.env ve .db HARİÇ — doğrulandı) |
| `sunucu/astra.service` | systemd birimi (`Restart=always`) |
| `sunucu/dogrula.sh` | Sunucu sağlık doğrulaması (salt-okunur) |
| `BINANCE_ALGO_EMIR_SEMASI.md` | **Koşullu emir şeması — ENGEL 1'in çözümü** |
| `karar_kurali.py` | **Canlıya geçiş hükmü** — veri gelmeden yazıldı |
| `data/_yedek_v57_20260820_222326/` | Temizlik öncesi yedek (geri alma noktası) |

### v58'de eklenen muhafızlar (bu oturum)

| Dosya | Ne işe yarar |
|---|---|
| `tests/test_kontrol_betigi.py` | Sağlık betiği cp1254 konsolda çökmemeli — K-35 (4) |
| `tests/test_rejim_birlestirme.py` | HMM yönsüz etiketten yön uydurmamalı — K-36 (7) |
| `tests/test_grafik_thread.py` | +3 test: grafik `_LOG_DIR`'e yazılmalı — K-34 (7 toplam) |
| `tests/test_model_beceri.py` | Seçim beceriye baksın, beceri yoksa nötrle — K-37 (15) |
| `orderbook_kaydedici.py` | **Order book derinliği kaydı — K-38** (denenmemiş tek yeni bilgi kaynağı) |
| `baslat_orderbook.bat` | Kaydedici başlatıcı (çift-çalıştırma korumalı) |
| `sifirla_k37.py` | **7. sıfırlama — HENÜZ ÇALIŞTIRILMADI** (§0.14) |

---

## 8. TEHLİKELİ DAVRANIŞ DEĞİŞİKLİKLERİ (v56'da eklendi)

Bunlar savunma değil, **davranış değişikliği**. Canlıya geçmeden oku:

1. **`order_engine`** — SL 3 denemede konamazsa pozisyonu **zorla kapatır**
2. **`preflight`** — Binance erişilemezse veya kaldıraç >50 ise canlı modda
   **botu başlatmaz**
3. **`risk_manager`** — minimum altındaki boyutta 5 USDT yerine **0** döner
   (işlem açılmaz)
4. **`config.py`** — `PANEL_USER`/`PANEL_PASS`'tan yalnızca biri doluysa
   başlatmayı **reddeder**
5. **Panel + Prometheus** — varsayılan `127.0.0.1` (eskiden `0.0.0.0`)
6. **`docker-compose.yml`** — `.env`'de `DB_PASSWORD`/`REDIS_PASSWORD`/
   `GRAFANA_PASSWORD` yoksa **başlamaz**
7. **Paper sonuçları artık maliyetli** — v55 öncesiyle karşılaştırılamaz
8. **Backtest** — ATR ısınma barları atlanıyor, eski sonuçlarla kıyaslanamaz
9. **(v57) `get_journal()` artık `JOURNAL_DB_PATH`'e uyuyor.** Bu ayarı
   `.env`'de değiştirmiş bir kurulumda journal ARTIK yeni dosyaya yazar;
   eski `data/journal.db` içeriği elle taşınmalıdır. Öncesinde ayar sessizce
   yok sayılıyordu (çağrı sırasına bağlıydı).
10. **(v57) Paper sayacı 33 → 0.** Önceki değer sahteydi. 3 haftalık pencere
    2026-08-20'de yeniden başladı.

## 7.7 İZLENECEK HİPOTEZ: dar stop'lar kaybediyor (n=5, ERKEN)

İlk 5 kapanmış işlemde net bir ayrışma var:

| | SL mesafesi | Boyut | Sonuç |
|---|---|---|---|
| Kazananlar | **%1.01** | 57.86 USDT | 2/2 |
| Kaybedenler | **%0.44** | 92.88 USDT | 3/3 |

**Boyut farkı bir SORUN DEĞİL** — risk-bazlı boyutlandırmanın mekanik
sonucu: dar stop → büyük pozisyon (USDT riski sabit kalsın diye).
USDT cinsinden risk yakın: 0.58 vs 0.38. Erken bir turda
"boyutlandırma kaybedenleri kayırıyor" diye işaretlemiştim — **yanlıştı**,
nedensellik SL mesafesinde.

**Hipotez:** SL mesafesi ATR'den türüyor; piyasa sakinken ATR düşüyor,
SL %0.2-0.3'e kadar daralıyor ve normal gürültü onu vuruyor. İki BNBUSDT
işlemi tam böyle kaybetti (%0.21 ve %0.27 SL).

**Nasıl doğrulanır (20+ işlemde):**
```bash
python -c "
import sqlite3;c=sqlite3.connect('data/astra.db')
q=\"SELECT AVG(ABS(giris_fiyat-stop_loss)/giris_fiyat*100), COUNT(*) FROM trades WHERE durum!='ACIK' AND pnl%s0\"
for et,op in (('KAZANAN','>'),('KAYBEDEN','<=')):
    m,n=c.execute(q%op).fetchone(); print(f'{et}: SL %{m:.2f} (n={n})')"
```
### ⚠️ GÜNCELLEME (n=7): HİPOTEZ KIRILDI

7. işlem (ETHUSDT) **%1.00 stop mesafesiyle KAYBETTİ** — kazananlarla
aynı aralıkta. Yeni tablo:

| | Ortalama | Aralık |
|---|---|---|
| Kazananlar | %1.01 | %1.00–%1.02 |
| Kaybedenler | %0.58 | **%0.21–%1.00** |

Aralıklar **örtüşüyor**. "Dar stop kaybediyor" temiz bir kural DEĞİL.

Geriye kalan zayıf gözlem: en dar iki stop (%0.21, %0.27) `STOP` ile,
geniş stop'lu kayıplar `SİNYAL` dönüşüyle kapandı — farklı ölüm biçimleri.
Mantıklı ama 7 işlemle iddia edilemez.

**Ders:** İlk 5 işlemde ayrışma "çok temiz" görünüyordu (3/3 vs 2/2,
istisnasız). Altıncı gözlem onu bozdu. Küçük örneklemde temiz görünen
desenler böyle çöker — **bu yüzden n<20'de parametre değiştirilmez.**

**Şimdi değiştirme** — paper, canlıda çalışacak yapılandırmayı
yansıtmalı (§5.3).

---

## 7.8 ✅ EMİR DÖNGÜSÜ DOĞRULANDI — 9/9 (2026-08-26)

**Projede İLK KEZ** `testnet_emir_dogrula.py` tamamı geçti:

```
✅ [0] güvenlik kapısı   ✅ [3] pozisyon aç      ✅ [6] state ↔ borsa uyumu
✅ [1] kimlik/saat       ✅ [4] SL BORSADA VAR   ✅ [7] pozisyon kapat
✅ [2] sembol kuralları  ✅ [5] likidasyon fiyatı ✅ [8] orphan temizliği
```

Çalıştırma (testnet parası sahte, risk yok):
```bash
LIVE_TRADING=true python testnet_emir_dogrula.py
```
⚠️ `.env`'i DEĞİŞTİRME — yalnızca o sürece ver. `.env`'de `true` yaparsan
bir sonraki restartta bot paper yerine gerçek testnet emri açar ve paper
veri toplama BOZULUR.

### K-8 — Bot açtığı pozisyonu state'ine KAYDETMİYORDU (kritik)

`execution_engine.pozisyon_ac()` şunu çağırıyordu:
```python
self._state.pozisyon_ekle({...})     # ❌ BÖYLE BİR METOT YOK
```
Doğrusu `pozisyon_ac(sembol, yon, giris, miktar, sl, tp1, kaldirac, order_id)`
— isim de imza da farklı. Her açılışta `AttributeError` fırlıyor, alttaki
`except Exception` yutuyor, `log.error` kimsenin bakmadığı yere yazıyordu.

**Etkisi:**
- `position_state.sl_tp_dogrula()` boş state üzerinde dönüyor →
  gerçek pozisyonların SL/TP'si **hiç doğrulanmıyordu**
- `pozisyon_var_mi()` her zaman `False` → o katmanda duplicate koruması yok

Doğrulama betiğinin 6. adımı ("borsada AÇIK ama state'te YOK") yakaladı.
Düzeltildi + state kaydı başarısızlığı artık `log.critical`.
Muhafız: `tests/test_state_kayit.py` (6 test).

**Ders:** Bu hatayı 194 testin hiçbiri yakalamamıştı; ancak **gerçek emir
döngüsü çalıştırılınca** göründü (§4.2).

---

## 7.9 BOT ARA SIRA ÖLÜYOR — sebep bilinmiyor, ETKİSİ KÜÇÜK

**Ölçülen (2026-08-26):**

| Koşu | Süre | Kesinti |
|---|---|---|
| 04:20 → 04:28 | 8 dk | ~19 dk |
| 04:48 → 05:05 | 17 dk | ~2 dk |
| 05:07 → 05:40 | 33 dk | (elle durduruldu) |
| **05:47 → 17:44** | **~12 saat** | **~3 dk** |

Sabahki sık ölümler benim yoğun test/probe koşturduğum pencereye denk
geliyor — kanıtlayamam ama korelasyon güçlü. Normal çalışmada bot
**~12 saat** ayakta kalıyor ve watchdog **~3 dakikada** geri getiriyor
(**%0.4 kayıp**).

**Elde HİÇBİR iz yok:** traceback yok, Windows çökme kaydı yok, watchdog
alarmı yok, CRITICAL yok — ve `bot_yasam_dongusu.log`'a **`BITTI` satırı
da yazılmıyor**.

**`BITTI` olmaması bilgi taşıyor:** python tek başına çökseydi `.bat`'i
çalıştıran `cmd.exe` hayatta kalır ve çıkış kodunu yazardı. Yazmıyorsa
**süreç ağacı komple öldürülüyor** demektir. Elenenler: `ExecutionTimeLimit`
(PT0S = sınırsız), uyku (kayıt yok), yeniden başlatma (makine 04:14'ten
beri açık), RAM (600 MB / 31.7 GB).

**NEDEN PEŞİNE DÜŞMÜYORUZ:** %0.4 kayıp, 94 işlem toplanacakken kötü bir
öncelik. Ayrıca **canlı modda risk daha da küçük**: SL borsada duran bir
emir (v57 algo taşıması), yani ölü bot korumasız pozisyon demek değil.
Kesintide yalnızca yeni giriş ve TP/trailing yönetimi durur.

**Kötüleşirse ne yapılır:** Ölüm anını logdan bul (son satır zamanı),
başlangıçları `grep "WATCHDOG] Başlatıldı" logs/astra.log` ile listele.
Sıklık artarsa süreç ağacını dışarıdan izleyen ayrı bir kaydedici gerekir
(`.bat` içi yakalama tree-kill'de çalışmıyor).

**Sağlık kontrolü (tek satır):**
```powershell
(Get-CimInstance Win32_Process -Filter "name='python.exe'" | ? { $_.CommandLine -like '*main.py bot*' }) | % { "yasam: $((Get-Date) - $_.CreationDate)" }
```

---

## 8.0 SUNUCU DENEMESİ — GERİ ALINDI (2026-08-25/26)

**Sonuç: bot YERELDE çalışıyor.** Contabo sunucusuna kurulum yapıldı, çalıştı,
sonra kullanıcı kararıyla yerele dönüldü.

### Sunucuda ne yapıldı (duruyor, kapalı)
- `/opt/astra` kuruldu, venv + bağımlılıklar tam, **178 test sunucuda geçti**
- systemd servisi `astra.service` kurulu ama **`disable`** durumda
- Geri açmak için: `systemctl enable --now astra`
- `.env` orada mevcut, `LIVE_TRADING=false`

### Sunucuda BULUNAN ÖNEMLİ ŞEY
`/root/astra_v44` dizini Temmuz'da silinmiş ama **süreci 54 gündür çalışıyordu**
— 6.4 GB RAM (sunucunun %55'i) tutuyor, CPU %0, Binance bağlantısı YOK.
Yani hiçbir şey yapmadan kaynak yiyen bir zombi. Öldürüldü, RAM 304 MB'a düştü.

**Ders:** Bir sunucuda eski sürüm bıraktıysan, dizini silmek süreci durdurmaz.
`ps aux | grep main.py` ile kontrol et.

### Çözülmemiş: WebSocket "Stale data"
Sunucuda ve YERELDE aynı: WS bağlanıyor, 30 sn veri gelmiyor, 6 denemeden
sonra REST polling'e düşüyor. **Taşımanın yarattığı sorun değil** — yerelde de
oluyordu. En olası sebep: testnet'te işlem hacmi düşük, 30 sn tick gelmiyor
(`config.py` notu: *"testnet için 30+ önerilir"*). İşlevsel engel değil,
bot REST ile devam ediyor.

### İki bot AYNI ANDA ÇALIŞMASIN
Aynı Telegram token'ını kullandıkları için çakışırlar:
`telegram.error.Conflict: terminated by other getUpdates request`.
Ayrıca ayrı veritabanlarına yazıp veriyi ikiye bölerler.
Sunucuyu tekrar açarsan yereldeki görevi kaldır (veya tersi).

---

## 8.0.1 SUNUCUYA TAŞIMA KİTİ (hazır, kullanılmadı)

Bot Contabo VPS'e taşınacak. Kurulum kiti hazır: **`sunucu/KURULUM.md`**.

**Neden:** Laptop uptime'ı darboğazdı (ölçüm: 1.8 saat/gün). Sunucu bunu
bitirir — tempoyu hızlandırmaz ama kesintiyi sıfırlar. Ayrıca canlıya
geçiş için zaten gerekli.

**Beklenmedik kazanç:** `engines/watchdog.py` 3 alarmdan sonra kendini
`SIGTERM` ile öldürüp systemd'nin geri getirmesini bekliyor. Windows'ta
systemd yok, bu yüzden zamanlanmış görev + `.bat` ile çözüm uydurulmuştu
(10 dk'ya kadar kayıp). Linux'ta mekanizma **tasarlandığı gibi** çalışır.

**Taşımadan önce ZORUNLU:**
1. Root parolası değiştirilecek — sohbete yapıştırılan parola yanmış sayılır
   (§4.4). Public IP + root + parola SSH en çok saldırılan kombinasyondur.
2. Anahtar tabanlı SSH'e geçilecek, parola girişi kapatılacak.
3. `ufw` ile yalnızca SSH açık; **8080 AÇILMAYACAK** — `PANEL_USER`/
   `PANEL_PASS` boş olduğu için panelde kimlik doğrulama YOK. Panele
   erişim SSH tüneliyle: `ssh -L 8080:127.0.0.1:8080 ...`
4. API anahtarlarını sunucuda **kullanıcı** girer; asistan yazmaz.

**Çift çalıştırma uyarısı:** Sunucu ayağa kalkınca yereldeki zamanlanmış
görevi kaldırın, yoksa iki bot aynı stratejiyi ayrı DB'lerde çalıştırır
ve hangi verinin geçerli olduğu karışır:
```powershell
Unregister-ScheduledTask -TaskName ASTRA_Bot -Confirm:$false
```

**Asistan sunucuyu NASIL takip eder:** Oturumlar arasında **takip etmez** —
kalıcı varlığı yok. Üç kanal: (1) Telegram = sizin 7/24 kanalınız,
(2) SSH = oturumlarımız sırasında teşhis, (3) `logs/astra_onemli.log` +
DB = geriye dönük kayıt. Bu yüzden §8.1'deki kalıcı log kaydı sunucuda
yerelden daha kritik.

---

## 8.1 LOG SAKLAMA (v57, 2026-08-25)

`logs/astra.log` 10 MB'a ulaşınca dönüyor, 5 yedek tutuluyor.

**Ölçüm düzeltmesi (2026-08-26):** Önce "4 saatte bir döner, ~20 saat geçmiş
kalır" yazmıştım — o ölçüm K-3 kesintisindeki **8000 ağ hatasının** şişirdiği
bir pencereden alınmıştı. Normal çalışmada çok daha sessiz:
**~0.34 MB/saat → 10 MB'a ~29 saatte** ulaşıyor, 5 yedekle **~6 günlük**
geçmiş kalıyor.

Yine de veri toplama haftalar sürecek, yani tam geçmiş korunmuyor.

Bu oturumdaki teşhislerin **tamamı** log geçmişinden yapıldı: 22 saatlik
uyku, 2 günlük ölüm, SL dolum sapması, test kirliliği. O kayıt olmadan
§10'daki "garip bir şey görürsen ciddiye al" kuralı uygulanamaz.

**Eklendi:** `logs/astra_onemli.log` — yalnızca WARNING ve üstü,
20 MB × 10 yedek. Satırların ~%13'ü bu seviyede olduğu için **haftalarca**
geçmiş saklar. İşlem açılış/kapanışları INFO olduğundan onların kalıcı
kaydı zaten `data/astra.db` ve `journal.db`.

**Bir şey araştırırken önce buraya bak** — `astra.log` büyük ihtimalle
çoktan dönmüştür.

---

## 9. LOG GÜRÜLTÜSÜ

Eskiden `log.debug`'da saklanan gerçek hatalar artık `error`/`critical`.
İlk çalıştırmada log hacminin artması **beklenen** — yeni hata değil,
görünür hale gelen eski hata.

---

## 10. AÇIK DÜRÜSTLÜK NOTU

77 düzeltmenin çoğu tek kişi tarafından yazıldı ve bağımsız gözden
geçirilmedi. `main.py` kapsamı %24 — orada yapılacak bir refactor hatası
testlerle yakalanmayabilir.

Bu proje daha önce **6 tur denetimden** geçti ve her turda "temiz" dendi;
v56 turunda 8 kritik hata çıktı (biri bir önceki turda "düzeltildi" denen ama
düzeltilmemiş olan). Bu turun da kör noktaları olabilir.

**v57 bu tahmini doğruladı.** v56 "77 hata düzeltildi, 147 test yeşil" diye
kapandı — ama testlerin kendisi üretim verisini kirletiyordu ve bunu hiçbir
test yakalamıyordu. Canlıya geçişi yöneten sayaç sahteydi ve fark edilmesi
yalnızca "notlar 0 diyor, sayaç 33 diyor" tutarsızlığı sayesinde oldu.

**Alınacak ders:** Kör nokta genellikle kodun içinde değil, kodun
**ölçüldüğü yerde** duruyor. "Testler yeşil" ve "veri doğru" ayrı iddialardır;
ikincisi ayrıca doğrulanmalıdır.

Paper verisi biriktikçe garip bir şey görürsen ciddiye al. Özellikle:
sayaç beklenenden hızlı artıyorsa işlem sürelerine bak (gerçek işlem
dakikalar, artefakt milisaniyeler sürer).
