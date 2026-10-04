# ASTRA — NEDEN KAYBEDİYORUZ? (kanıta dayalı analiz)

> Tarih: 2026-09-02 · Veri: 21 kapanmış paper işlemi + 23.742 sinyal
> Referans fiyat: Binance **futures gerçek piyasa 1m barları** (12 gün,
> 5 sembol, 18.372 bar/sembol) — bot verisinden bağımsız kaynak.
>
> Bu belge `DEVAM_NOTLARI.md` §0'daki teşhisi **kısmen doğruluyor,
> kısmen düzeltiyor.** Özet: VOLATILE çarpanları gerçekten kötü, ama
> asıl sorun onlar değil.

---

## 0. TEK CÜMLELİK SONUÇ

**Giriş sinyalinin, işlem yaptığı eşikte ölçülebilir bir öngörü gücü yok.**
Beklenti (%−0.171/işlem) neredeyse tam olarak gidiş-dönüş işlem
maliyetine (%0.11) eşit. Sistem, yazı-tura atıp komisyon ödüyor.

Bunun üstüne binen 3 ayrı kodlama hatası kaybı büyütüyor ama
düzeltilmeleri sistemi kârlı yapmaz.

---

## 1. VOLATILE ÇARPANLARININ GEREKÇESİ — **YOK**

Arandı: 45 changelog dosyası + tüm `.md` belgeleri.

| Arama | Sonuç |
|---|---|
| `VOLATILE` (tüm .md) | 2 isabet: biri v19'da HMM override, biri v57'de paper↔canlı karşılaştırma **tablosu** |
| `sl_mult` / `tp1_mult` / `ATR_MULT` gerekçesi | **0 isabet** |
| `1.3` / `0.75` çarpanları için açıklama | **0 isabet** |

`CHANGELOG_v57.md:331` sadece `| Rejim ayarı | VOLATILE ×1.3 | yok |`
diyor — bu bir **gözlem**, gerekçe değil.

➡️ **Hüküm: sorgulanmamış varsayılan.** Hiçbir belgede "stop'u genişletirken
hedefi neden daralttığımız" yazmıyor. Git geçmişi de yok. Bu kombinasyonu
savunan bir kayıt bulunmadığı için korunması gereken bir tasarım kararı
değil.

### Notlardaki hesap hafif iyimser

§0 "%57 win rate gerekiyor" diyor — bu **brüt** hesap. Maliyet dahil
gerçek rakam:

| | Brüt | Net (maliyet %0.11 dahil) |
|---|---|---|
| TP | %0.750 | **%0.64** |
| SL | %0.975 | **%1.09** |
| R/R | 0.77 | **0.587** |
| Başabaş WR | %57 | **%63** |

Gerçekleşen: %33.

---

## 2. ÜÇ MANTIK HATASI (test edildi, kanıtlandı)

### K-A — Çıkış kapısı, giriş kapısından ZAYIF ⛔ ana kod hatası

`engines/paper_trading.py::sinyal_isle` zıt sinyalde pozisyonu
kapatırken **hiçbir eşik uygulamıyor.** Kapatma bloğu `_filtre_gec()`
çağrısından ÖNCE çalışıyor; `_filtre_gec` yalnızca AÇILIŞ yolunda.

```
AÇILIŞ  : |ai| >= 4  VE  conf >= 62   (+ canlıda rejim eşiği |ai| >= 6)
KAPANIŞ : karar metninde "BUY"/"SELL" geçmesi YETERLİ
```

Yani **ai=3 / conf=55 bir sinyal pozisyon AÇAMAZ ama AÇIK pozisyonu
KAPATABİLİR.**

**Kanıt — 11 işlemin 11'i:** Zıt sinyalle kapanan her işlemin kapanış
anındaki sinyali açılış eşiğinin altındaydı:

| # | yön | pnl% | kapatan sinyal | ai | conf | açabilir miydi? |
|---|---|---|---|---|---|---|
| 1 | SHORT | −0.20 | WEAK BUY | +3 | 80 | ❌ ai<4 |
| 2 | LONG | +0.05 | WEAK SELL | −3 | 55 | ❌ ai + conf |
| 3 | SHORT | −0.00 | WEAK BUY | +3 | 70 | ❌ ai<4 |
| 4 | SHORT | −0.12 | WEAK BUY | +3 | 70 | ❌ ai<4 |
| 5 | LONG | −0.33 | WEAK SELL | −4 | 55 | ❌ conf<62 |
| 6 | SHORT | −0.14 | WEAK BUY | +3 | 70 | ❌ ai<4 |
| 7 | LONG | −0.25 | WEAK SELL | −3 | 55 | ❌ ai + conf |
| 9 | SHORT | +0.03 | WEAK BUY | +3 | 70 | ❌ ai<4 |
| 14 | SHORT | −0.21 | WEAK BUY | +3 | 80 | ❌ ai<4 |
| 15 | LONG | −0.20 | WEAK SELL | −4 | 65 | ❌ rejim eşiği |
| 16 | SHORT | −0.25 | WEAK BUY | +3 | 80 | ❌ ai<4 |

**Ölçülen bedel:** Bu 11 işlem toplam **%−1.62**. Gerçek 1m barlarla
karşı-olgusal (SL/TP'ye kadar tutulsalardı): **%−0.83**.
➡️ Erken kesme **0.79 puan** kaybettiriyor — toplam zararın **%22'si**.

**Muhafız testi:** `tests/test_cikis_kapisi.py` (7 test).
Yazıldığında **4 kırmızı / 3 yeşil**'di — kırmızılar bu hatayı
gösteriyordu, yeşiller kontrol testleriydi (§4.1: "hiç kapatma" da
muhafızları geçerdi). **Düzeltme sonrası 7/7 yeşil** (§7).

---

### K-B — Paper ↔ canlı ÇIKIŞ yolu ayrışması ⛔ eşitlik ihlali

| | Zıt pozisyonu kapatmadan önce geçilen kapılar |
|---|---|
| **Canlı** (`main.py:1441-1449`) | chop → MTF cascade → MTF hizalama → EdgeEngine → strateji motoru → `sinyal_gecerli_mi` (conf + rejim eşiği) |
| **Paper** (`main.py:1829`) | **hiçbiri** — ham `coin_analiz` çıktısıyla, veto zincirinin DIŞINDA çağrılıyor |

`paper_trader.sinyal_isle(sonuc)` satırı `_execution_isle(sonuc)`
satırından ÖNCE ve ondan bağımsız çalışıyor.

➡️ **Sonuç: 21 işlemin tamamı canlı davranışı temsil etmiyor.** Canlı
bu 11 kesmenin hiçbirini yapmazdı. Bu, §5.3'te "düzeltildi" denen
hastalığın çıkış yolunda hâlâ duran hâli.

---

### K-C — Anında ters dönüş, bekleme yok

`sinyal_isle` aynı çağrıda pozisyonu kapatıp **ters yönde yenisini
açıyor**. Gerçek veride:

| | |
|---|---|
| #15 XRPUSDT LONG kapandı | 04:07:50 |
| #16 XRPUSDT SHORT açıldı | **04:07:50** (aynı saniye) |
| ikisinin toplamı | **%−0.45** (saf maliyet) |

Kapanış→açılış boşluğu **medyan 92 saniye, minimum 0**. Stop yiyen
işlemden 1 saniye sonra yeni pozisyon açılıyor (#12→#13, #19→#20).
Ard arda maliyet ödeniyor.

Bu davranış test yazarken de yeniden üretildi — kontrol testi önce
"kapatmadı" sandı, çünkü aynı sembolde ters pozisyon açılmıştı.

---

### K-D — Hayalet kâr (küçük ama gerçek)

> ⚠️ **TEŞHİS DÜZELTİLDİ (2026-09-03).** Bu bölüm önce "bayat fiyat"
> diyordu. Düzeltme sırasında gerçek mekanizma bulundu: fiyat bayat
> DEĞİLDİ, **testnet'e özgüydü**. Aşağısı düzeltilmiş hâlidir.

**#21 SOLUSDT**: bot 99.89'dan SHORT açtı; o an gerçek piyasa **98.47**.
İşlem anındaki 5m barlar:

| Kaynak | O | H | C |
|---|---|---|---|
| **Testnet** | 98.79 | **99.94** | 98.47 |
| **Gerçek** | 98.55 | 98.63 | 98.47 |

Testnet'te gerçek piyasada **olmayan** bir sıçrama vardı. Bot henüz
KAPANMAMIŞ bara baktığı için o anki "close" 99.92 okudu. TP 99.14 zaten
piyasanın altında kaldı → **2.9 dakikada "TP"**, +%0.64. **5 kazançtan
biri gerçek piyasada hiç var olmayan bir fiyattan geliyordu.**

Sebep: testnet spot likiditesi ince — tek bir test emri fiyatı %1.5
oynatabiliyor. Kline'da boşluk YOK (kontrol edildi), yani tazelik
sorunu değil.

Tüm sinyaller üzerinden ölçüm (22.007 eşleşme):

| | medyan sapma | >%0.5 | >%1 |
|---|---|---|---|
| genel | **%0.031** | %2.3 | %0.54 |

➡️ Besleme genelde sağlam; sapmalar testnet'in ince likiditesinden
gelen geçici sıçramalar. §5.3.1'deki "testnet≈gerçek" ölçümü ANLIK
fiyatları karşılaştırmıştı ve bu sınıfı kaçırmıştı: ortalama yakınlık,
tekil sıçrama yokluğu anlamına gelmiyor.

**Düzeltildi (K-15):** piyasa verisi artık gerçek borsadan okunuyor,
emirler testnet'te kalıyor.

---

## 3. ASIL SORUN: SİNYALDE EDGE YOK

Yukarıdaki 3 hata düzeltilse bile sistem kârlı olmuyor. Üç bağımsız test:

### Test 1 — SL/TP çarpan ızgarası (42 kombinasyon, gerçek 1m bar)

Her işlem, kayıtlı ATR'sinden türetilen alternatif SL/TP seviyeleriyle
yeniden simüle edildi (maliyet dahil, 48 saat ufuk):

| SL× | TP× | R/R | toplam |
|---|---|---|---|
| 2.50 | 2.50 | 1.00 | **+0.51%** ← en iyi |
| 1.00 | 3.00 | 3.00 | +0.41% |
| **1.95** | **1.50** | **0.77** | **−2.72%** ← mevcut |
| 1.95 | 4.00 | 2.05 | −5.46% ← en kötü |

**42 kombinasyonun tamamı sıfır civarında.** En iyisi 21 işlemde
+%0.51 → işlem başına +%0.028, gürültüden ayırt edilemez.

➡️ Mevcut ayar ızgaranın **en kötü bölgesinde** (notlar haklı), ama
**hiçbir ayar kurtarmıyor.** Edge olsaydı ızgaranın geniş bir bölgesi
kârlı olurdu; düz ve negatif.

### Test 2 — Yön ters çevrilse?

| | toplam | ort | WR |
|---|---|---|---|
| Orijinal yön | −2.72% | −0.136% | %55 |
| **Ters yön** | **−3.37%** | −0.177% | %53 |

➡️ Ters de kaybediyor. Sinyal **ters** değil, **yok**. Maliyet iki yönü
de yiyor.

### Test 3 — Sinyal → ileri getiri (23.742 sinyal, drift düzeltilmiş)

Sembol bazlı koşulsuz sürükleme çıkarıldı; örtüşen pencereler için
**blok bootstrap** (2000 tekrar) kullanıldı.

| Filtre | n | excess 60dk | t | p |
|---|---|---|---|---|
| Tüm sinyaller | 20801 | −0.026% | −1.5 | 0.14 |
| \|ai\|≥4 (giriş eşiği) | 8571 | −0.010% | −0.3 | 0.72 |
| **\|ai\|≥4 & conf≥62 (gerçek kapı)** | **6087** | **+0.003%** | **0.1** | **0.93** |
| \|ai\|≥6 (VOLATILE eşiği) | 2820 | −0.038% | −0.9 | 0.32 |
| \|ai\|≥7 (STRONG) | 1283 | −0.107% | −2.0 | 0.039 |
| \|ai\|≥8 | 446 | −0.211% | −2.1 | 0.006 |

➡️ **Botun fiilen kullandığı eşikte edge tam olarak sıfır** (p=0.93).

➡️ Uçta (|ai|≥7) hafif **ters** eğilim var (p=0.04) — en güçlü sinyaller
en kötü performansı gösteriyor. Örtüşmeyen örneklemde t=−1.13, yani
**zayıf kanıt**; iddia edilemez ama izlenmeli. (Gerçek veride #18
ETHUSDT ai=−9 ile açıldı ve stop yedi.)

> ⚠️ **İlk taramada t=−9.9 gibi değerler çıkmıştı — o rakamlar örtüşen
> 60dk pencerelerinden şişmişti.** Blok bootstrap sonrası doğru tablo
> yukarıdaki. "Sinyal sistematik ters" demek için kanıt yeterli değil;
> "edge yok" demek için fazlasıyla yeterli.

### Aritmetik tutarlılık

| | |
|---|---|
| Gidiş-dönüş maliyet (ölçülen) | %0.11 |
| Edge sıfırsa beklenti | **−%0.11 / işlem** |
| Gerçekleşen beklenti | **−%0.171 / işlem** |
| Fark | K-A/K-C'nin yarattığı ek sürtünme |

---

## 4. "AZ İŞLEM YAPIYORUZ, DEMEK Kİ SEÇİCİYİZ" — HAYIR

12 günde **23.742 sinyal**, **22 işlem**. Bu seçicilik gibi görünüyor
ama kaynağı sinyal kalitesi değil:

- Darboğaz **`MAX_OPEN_POSITIONS=1`** (186 red) — slot doluyken her şey
  reddediliyor.
- Slot boşalınca bot **medyan 92 saniyede** yeni pozisyon açıyor.
- Birden fazla uygun aday olduğu 12 turda: 7'sinde en güçlü sinyal,
  6'sında zamanca ilk gelen seçildi — **tutarlı bir seçim kuralı yok**.
- 22 turun 10'unda zaten tek aday vardı.

➡️ Sistem "en iyi fırsatı bekleyen" bir filtre değil, **slot boşalınca
sıradakini alan bir kuyruk.** Az işlem yapması kalite göstergesi değil;
tek slotun mekanik sonucu.

---

## 5. YÖN DOĞRUYDU, YİNE DE KAYBEDİLDİ

Ölçüm penceresinde piyasa her sembolde düştü ve bot 17/21 SHORT'tu:

| Sembol | piyasa (ilk giriş→son çıkış) | bot PnL |
|---|---|---|
| SOLUSDT | **−5.37%** | +1.01% |
| XRPUSDT | **−3.98%** | −2.06% |
| ETHUSDT | **−3.05%** | −1.20% |
| BTCUSDT | −1.81% | +0.43% |
| BNBUSDT | −1.14% | −1.78% |

Düşen piyasada short'ta olup para kaybetmek, **çıkış mekaniğinin
girişteki isabeti yok ettiğinin** en net göstergesi. (Uyarı: bu
"trendi yakalayamadı" demek; §3'e göre girişlerin kendisi de rastgele,
yani bu tablo şanslı bir hizalanma da olabilir.)

---

## 6. NE YAPILMALI (öncelik sırası)

1. **Önce edge, sonra parametre.** SL/TP çarpanlarını ayarlamak
   (§3 Test 1) ölçülebilir bir fayda getirmiyor. Sinyalin |ai|≥4 &
   conf≥62 eşiğinde neden sıfır bilgi taşıdığı araştırılmalı.
2. **K-A/K-B/K-C düzeltilmeli** — kârlılık getirmez ama olmadan
   toplanan veri canlıyı temsil etmiyor, yani **ölçüm geçersiz.**
3. **Düzeltme yapılırsa sayaç sıfırlanır** (5. sıfırlama). Mevcut 21
   işlem zaten K-B nedeniyle canlıyı temsil etmiyordu.
4. **Karar kuralı değiştirilmeyecek** (`karar_kurali.py`, §0 madde 4).
   Bu analiz eşikleri gevşetmek için gerekçe DEĞİLDİR — tam tersi.
5. **Bayat fiyat muhafızı** (K-D): sinyal fiyatı ile son bar arasında
   %0.5+ sapma varsa işlem açılmamalı.

---

## 7. DURUM GÜNCELLEMESİ (2026-09-03)

**K-A, K-B, K-C, K-D düzeltildi; ayrıca K-16 (kapanmamış bar)** —
`DEVAM_NOTLARI.md` §0.1'de K-12..16 olarak kayıtlı.

Bot 2026-09-03 14:04'te yeniden başlatıldı; beş düzeltme de aktif.
K-11'den sonra toplanan 2 işlem **silindi** (yedek:
`data/_yedek_v58_20260903_135138/`) — eski çıkış mantığıyla
toplanmışlardı ve biri doğrudan K-12 kusuruyla kesilmişti (ai=3 < 4).
Sayaç 0/100'den temiz başlıyor.

| | Durum |
|---|---|
| K-A çıkış kapısı | ✅ `_cikis_gecerli()` — giriş barının aynısı |
| K-B paper↔canlı | 🟡 kısmi — `sinyal_gecerli_mi` eklendi, veto zinciri hâlâ paper'da yok (§6.0) |
| K-C ters dönüş | ✅ `YENIDEN_GIRIS_BEKLEME_SN=300`, paper VE canlı |
| K-D hayalet kâr | ✅ K-15 — piyasa verisi gerçek borsadan (teşhis düzeltildi: bayat değil, testnet artefaktı) |
| K-16 kapanmamış bar | ✅ göstergeler kapanmış bara, SL/TP anlık fiyata bakıyor |
| Test | 239 (20 dosya), hepsi yeşil; 26 yeni test mutasyonla doğrulandı |

⚠️ **Bu düzeltmeler §3'ü değiştirmiyor.** Ölçülen kayıp sürücülerini
kaldırdılar, ama sinyalin işlem eşiğinde edge'i hâlâ sıfır (p=0.93).
Beklenen etki: kaybın küçülmesi, kâra geçmesi DEĞİL.

### §3 BAĞIMSIZ OLARAK DOĞRULANDI (2026-09-03)

Model tarafı incelendiğinde §3'teki sonuç ikinci bir yöntemle çıktı.
"Accuracy %99 ama canlıda yazı tura" bilmecesinin cevabı: **ölçüm
sahteydi** (DEVAM_NOTLARI §0.2, K-17..21).

| BTCUSDT 14g/1h | test_acc | test'te target=1 |
|---|---|---|
| feedback YOK | **0.516** | 0.484 |
| feedback VAR (bot gibi) | **0.963** | **0.000** ← tek sınıf |

Feedback kayıtlarının %96'sı uydurmaydı (drift retrain'in yazdığı
`target=0` satırları) ve `shuffle=False` split yüzünden test setinin
tamamını oluşturuyorlardı.

| Yöntem | Sonuç |
|---|---|
| Dürüst model accuracy | **0.516** (taban çizgisi 0.518) |
| Sinyal → ileri getiri (§3 Test 3) | excess **+%0.003, p=0.93** |

İki bağımsız yöntem aynı yere varıyor. Düzeltme sonrası canlı log:
`[XGB/BNBUSDT] test_acc=0.527 WF=0.527±0.045` (öncesi `1.000`).

**Feature engineering'de sızıntı YOK** — feature'lar geriye dönük,
hedef doğru (`shift(-1)`), split zaman sıralı. Sorun oradaydı sanılıyordu.

**Yanlış çıkan hipotez:** "Zehirli etiketler modeli SELL'e yatırıyor"
diye düşünüldü (7293 SELL vs 524 BUY sinyali). Ölçüldü — **doğru değil**:
feedback'li ve feedback'siz modeller aynı dağılımı veriyor (negatif
katkı %50.3 vs %50.3). SELL yanlılığının kaynağı ayrıca araştırılmalı.

### Yapılmayanlar (bilinçli)

- SL/TP çarpanlarına **dokunulmadı** — R/R kapısı (K-11) zaten
  VOLATILE'i engelliyor; çarpanları da değiştirmek iki bilinmeyeni
  aynı anda oynatırdı.
- `karar_kurali.py` eşiklerine dokunulmadı.
- **Veto zinciri** ortak modüle çıkarılmadı — K-13 bu yüzden kısmi
  kaldı (DEVAM_NOTLARI §6.0).
- Üretim verisi kirletilmedi: `trades` içinde 0 sentetik kayıt,
  0 fikstür fiyatı, logda 0 sentetik satır (§4.6).
