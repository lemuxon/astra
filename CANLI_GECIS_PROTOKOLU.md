# ASTRA — GERÇEK PARAYA GEÇİŞ DOĞRULAMA PROTOKOLÜ

> Bu belge kod değil, **süreçtir**. Finansal riski azaltmada kod
> kalitesinden daha etkilidir. Her adımı atlamadan uygulayın.

---

## NEDEN BU PROTOKOL?

Kod artık sağlam: 47 otomatik test, çok katmanlı risk yönetimi, SL
zorunluluğu, fail-safe doğrulamalar. **Ama sağlam kod, kârlı strateji
demek değildir.**

Gerçek finansal risk şu üç yerde:
1. **Sinyal doğruluğu %52** — işlem maliyetleri (komisyon + slippage +
   funding) çıktıktan sonra bu marj kâr garantisi vermez.
2. **Gerçek para performans verisi yok** — tüm veriler testnet/paper'dan.
3. **Yeterli örneklem yok** — 20-40 işlem istatistiksel olarak anlamsızdır.

Bu protokol, bu üç boşluğu kapatmadan gerçek paraya geçmeni engeller.

---

## AŞAMA 0 — ÖN KOŞULLAR (hepsi ZORUNLU)

| # | Koşul | Nasıl doğrularım |
|---|---|---|
| 0.1 | Tüm testler geçiyor | `python testleri_calistir.py` → "TÜM TESTLER BAŞARILI" |
| 0.2 | Preflight temiz | Bot başlarken sağlık kontrolü hatasız |
| 0.3 | Sunucu saati senkron | `timedatectl` → "System clock synchronized: yes" |
| 0.4 | Token/API yenilendi | Eski sızmış anahtarlar iptal edildi |
| 0.5 | Panel korumalı | `PANEL_USER`/`PANEL_PASS` dolu VEYA firewall kısıtlı |
| 0.6 | Log rotasyonu aktif | `baslat.sh` kullanılıyor |
| 0.7 | API'de para çekme izni KAPALI | Binance API ayarlarından doğrula |

**Herhangi biri eksikse DEVAM ETME.**

---

## AŞAMA 1 — PAPER TRADING DOĞRULAMASI (minimum 3 hafta)

### 1.1 Bot gerçekten işlem açıyor mu?
```
/paper
```
**Beklenen:** İşlem sayısı > 0 ve düzenli artıyor.

**0 işlem görüyorsan:**
- `/neden` ile veto dağılımına bak
- Eşikleri kontrol et: `MIN_CONFIDENCE=62`, `MIN_AI_SCORE_BUY=4`
- Piyasa sakinse normal olabilir — 48 saat daha bekle
- Hâlâ 0 ise: **canlıya GEÇME**, önce bu çözülmeli

### 1.2 Toplanması gereken minimum veri
| Metrik | Minimum eşik | Neden |
|---|---|---|
| Toplam paper işlem | **≥ 100** | 100 altında istatistik anlamsız |
| Gözlem süresi | **≥ 3 hafta** | Farklı piyasa rejimleri görülmeli |
| Kapanmış işlem | **≥ 80** | Açık pozisyonlar sonuç vermez |

### 1.3 Değerlendirme kriterleri (100+ işlem sonrası)

> ⚠️ **BU TABLO 2026-08-26'DA YENİDEN KALİBRE EDİLDİ.**
> Objektif hüküm için: **`python karar_kurali.py`**
>
> Aşağıdaki tablo, ~1:1 risk/ödül varsayan bir sistem için yazılmıştı.
> Ölçülen gerçek R/R **~4.5:1** (kazanç %1.40, kayıp %0.31) ve bu yapıda
> **başabaş win rate %18**. Tablodaki "%42 altı = KIRMIZI" kuralı, %30
> win rate'li fazlasıyla kârlı bir sistemi reddederdi.
>
> Ayrıca "ard arda kayıp < 6 = yeşil" ulaşılamaz: %57 kayıp oranında
> 100 işlemde beklenen en uzun seri **~7**. Normal davranış sarıya düşerdi.
>
> **Yeni ana ölçüt: BEKLENTİ + istatistiksel anlamlılık.**
> Win rate yalnızca bilgi amaçlı. Tablo tarihsel referans olarak duruyor.


| Metrik | Yeşil ışık | Sarı (dikkat) | Kırmızı (GEÇME) |
|---|---|---|---|
| Win rate | > %48 | %42-48 | < %42 |
| Toplam PnL | Pozitif | Hafif negatif | Belirgin negatif |
| Maks. drawdown | < %10 | %10-20 | > %20 |
| Ard arda kayıp | < 6 | 6-9 | ≥ 10 |
| Ort. kazanç/kayıp oranı | > 1.3 | 1.0-1.3 | < 1.0 |

**KRİTİK NOT:** Win rate %48 altındaysa bile, kazanç/kayıp oranı yüksekse
(örn. 2.0) sistem kârlı olabilir. İkisine BİRLİKTE bak. Ama ikisi de
kırmızıysa strateji çalışmıyor demektir — kod sorunu değil, strateji sorunu.

### 1.4 Zarar dönemini gözlemleme (atlanmamalı)
Botun **kaybettiği** bir dönemi mutlaka gör. Sadece kazandığını görüp
geçmek, ilk gerçek zararda panik yapmana yol açar. Şunu sor:
- Ard arda kayıplarda kill switch devreye girdi mi?
- Drawdown limitleri çalıştı mı?
- Bot mantıklı davrandı mı, yoksa çılgınca işlem mi açtı?

---

## AŞAMA 2 — MİKRO CANLI TEST (minimum 2 hafta)

Paper yeşil ışık verdiyse, **en küçük tutarla** gerçek paraya geç.

### 2.1 Ayarlar
```
LIVE_TRADING=true
TRADE_USDT=10          # MİNİMUM. Kaybını göze alabileceğin tutar.
FUTURES_LEVERAGE=3     # Test için düşür (varsayılan 5)
MAX_OPEN_POSITIONS=1   # Tek pozisyonla başla
DAILY_LOSS_LIMIT_PCT=2.0
```

### 2.2 İlk 48 saat — sürekli izleme
- Her işlem sonrası `/fpoz` ve `/bakiye` kontrol et
- **SL emirlerinin borsada gerçekten göründüğünü** Binance arayüzünden doğrula
- Slippage'ı izle: `/gecikme` — paper'dakinden ne kadar farklı?

### 2.3 Paper vs Canlı karşılaştırması (en önemli adım)
2 hafta sonra karşılaştır:

| Metrik | Paper | Canlı | Fark kabul edilebilir mi? |
|---|---|---|---|
| Win rate | ___ | ___ | ±%5 içinde olmalı |
| Ort. slippage | ___ | ___ | Canlı daha yüksek olacak, %0.3'ü aşmamalı |
| Giriş gecikmesi | ___ | ___ | `/gecikme` ile ölç |
| İşlem/gün | ___ | ___ | Benzer olmalı |

**Büyük sapma varsa (win rate %10+ düşük, slippage %0.5+):** Strateji
gerçek piyasa koşullarında çalışmıyor. Tutarı ARTIRMA, geri dön.

---

## AŞAMA 3 — KADEMELİ ARTIŞ

Mikro test yeşilse, **yavaş** artır. Her adımda minimum 2 hafta bekle.

| Adım | TRADE_USDT | Kaldıraç | Max poz | Bekleme | Devam koşulu |
|---|---|---|---|---|---|
| 1 | 10 | 3x | 1 | 2 hafta | PnL ≥ 0 |
| 2 | 25 | 3x | 2 | 2 hafta | PnL ≥ 0, DD < %10 |
| 3 | 50 | 5x | 2 | 3 hafta | PnL > 0, DD < %12 |
| 4 | 100 | 5x | 3 | 4 hafta | PnL > 0, DD < %15 |

**Her adımda bir seferde SADECE BİR parametre artır.** İkisini birden
artırırsan, sorun çıkınca hangisinin sebep olduğunu bilemezsin.

---

## AŞAMA 4 — SÜREKLİ İZLEME (kalıcı)

### Günlük (2 dakika)
```
/saglik      → sistem sağlıklı mı
/bakiye      → beklenen aralıkta mı
```

### Haftalık (15 dakika)
```
/ai_rapor    → model doğruluğu düşüyor mu
/analytics   → PnL trendi
/neden       → veto dağılımı değişti mi
grep ERROR logs/astra.log | tail -20
```

### Aylık (1 saat)
- Paper vs canlı performans karşılaştırması
- Model accuracy trendi (sürekli düşüyorsa → yeniden eğitim/strateji gözden geçirme)
- Maks. drawdown geçmişi
- `python testleri_calistir.py` (güncelleme yaptıysan)

---

## ACİL DURDURMA KRİTERLERİ

Aşağıdakilerden **herhangi biri** olursa botu DERHAL durdur:

```
screen -X -S astra quit
```

| Durum | Neden acil |
|---|---|
| Drawdown > %20 | Sermaye erimesi hızlanıyor |
| Ard arda 10+ kayıp | Strateji piyasa rejimine uymuyor |
| SL'siz pozisyon uyarısı | Korumasız risk (v51 uyarı verir) |
| Beklenmedik pozisyon (senin açmadığın) | Güvenlik ihlali olabilir |
| Bakiye beklenenden %15+ düşük | Hesap kontrolü gerekli |
| Aynı hata logda 50+ tekrar | Sistem sağlıksız |
| Borsa/API kesintisi | Belirsizlikte işlem yapma |

Durdurduktan sonra: sebebi anla → paper moda dön → düzelt → yeniden doğrula.

---

## GERÇEKÇİ BEKLENTİ

Bu bölümü atlama.

- **%52 sinyal doğruluğu iyi bir değerdir** ama sihir değildir. Kâr,
  doğruluktan çok **risk yönetiminden** gelir: kazançları büyütmek,
  kayıpları küçük tutmak.
- **Aylık %10-30 getiri vaat eden sistemler gerçekçi değildir.** Profesyonel
  fonlar yıllık %15-25 hedefler.
- **Zarar eden aylar OLACAK.** Bu bir hata değil, normaldir. Önemli olan
  uzun vadeli beklenen değerin pozitif olması.
- **Bot para basmaz.** Disiplinli bir araçtır; disiplinsiz kullanılırsa
  disiplinli şekilde para kaybettirir.
- **Kaybetmeyi göze alamayacağın parayı ASLA kullanma.**

---

## PROTOKOL KONTROL LİSTESİ

Canlıya geçmeden önce hepsini işaretle:

```
[ ] Aşama 0: 7 ön koşulun tamamı sağlandı
[ ] Aşama 1: 3+ hafta paper, 100+ işlem toplandı
[ ] Aşama 1: Değerlendirme kriterleri yeşil/sarı (kırmızı yok)
[ ] Aşama 1: Zarar dönemi gözlemlendi, bot mantıklı davrandı
[ ] Aşama 2: TRADE_USDT=10, kaldıraç 3x ile başlandı
[ ] Aşama 2: SL emirleri Binance arayüzünde görüldü
[ ] Aşama 2: Paper vs canlı sapması kabul edilebilir
[ ] Acil durdurma kriterleri okundu ve anlaşıldı
[ ] Kaybını göze alabileceğim tutarla çalışıyorum
```

**Bir kutu bile boşsa, bir sonraki aşamaya geçme.**
