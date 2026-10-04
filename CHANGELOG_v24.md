# ASTRA v24.0 — DAYANIKLILIK & OTOMATİK STRATEJİ DOĞRULAMA KAPISI

## Tarih: 2026-05-29 | Temel: v23.0

Bu sürümün tek odağı: **yanlış/kırılgan bir stratejinin canlı paraya
ulaşmasını otomatik olarak engellemek.** Yeni bir "doğrulama kapısı"
(validation gate) eklendi — bir model/strateji, birbirinden bağımsız
çok katmanlı testlerin TÜMÜNDEN geçmeden yeni pozisyon açamaz.

Felsefe: *"Bir testten geçmek şans olabilir; hepsinden geçmek dayanıklılıktır."*
(Lopez de Prado — Advances in Financial Machine Learning)

---

## 🛡️ Yeni Modül: `engines/strategy_validator.py`

Dört bağımsız test katmanı + sert veto kuralları:

### 1. Deflated Sharpe Ratio (35 puan)
Ham Sharpe oranı, kaç strateji/parametre denendiğine göre düzeltilir.
Çok deneme yapınca "en iyi"nin Sharpe'ı şişer; DSR bu seçim yanlılığını
giderir. `deneme_sayisi` arttıkça eşik yükselir.

### 2. Walk-Forward Tutarlılık (25 puan)
Getiriler zaman pencerelerine bölünür; kaç pencerenin pozitif olduğu
ölçülür. Tek bir şanslı döneme bağımlı stratejiler düşük puan alır.

### 3. Bootstrap Stres Testi (25 puan)
Gerçek getiri dağılımından (Gaussian varsayımı YOK — fat-tail korunur)
binlerce alternatif gelecek üretilir. Worst-case drawdown, medyan DD ve
**iflas (ruin) olasılığı** hesaplanır.

### 4. Tarihsel Kriz Senaryoları (15 puan)
Strateji bilinen kripto şoklarında simüle edilir:
COVID (−%50), LUNA/UST (−%40), FTX (−%25), Flash crash (−%15).
Kaç senaryoda hayatta kaldığı ölçülür.

### Sert Veto Kuralları (skordan bağımsız)
- İflas olasılığı > %10 → otomatik RED
- Worst-case drawdown > %35 → otomatik RED

### Çıktı
`StratejiKarari(onay: bool, skor: 0-100, sebepler: [...])`
scipy bağımsız — kendi `_norm_cdf` / `_norm_ppf` (Acklam) implementasyonu var.

---

## 🔌 Entegrasyon (main.py)

- **`_strateji_dayaniklilik_dogrula()`**: Trade journal'dan her coin'in
  son 200 işleminin getiri serisini çekip kapıdan geçirir.
  - Yeterli veri yoksa (<30 işlem) → varsayılan izin (yeni botu engellemez).
- **Periyodik**: ~6 saatte bir (her 36 döngü) otomatik çalışır; reddedilen
  coin'ler Telegram'a bildirilir.
- **Execution gate** (`_execution_isle`): `_strateji_onay[sembol] is False`
  ise o coin'de YENİ pozisyon açılmaz (mevcut pozisyonlar etkilenmez).
- **Model rollback bağlantısı (YENİ)**: Bir coin dayanıklılık testinden
  kalırsa, modeli `model_registry` üzerinden son iyi versiyona otomatik
  geri alınır — dayanıklılık düşüşü genelde model bozulmasından gelir.
- **`/validate [coin]`** Telegram komutu: manuel doğrulama + detaylı rapor.

---

## 🆕 Yeni: `engines/trade_journal.py` → `getiri_serisi()`
Validator'ı beslemek için kapanan işlemlerin kronolojik % getiri serisini
döndüren metot eklendi (`cikis_ts IS NOT NULL`, en yeni `limit` işlem).

## 🆕 Yeni: `tests/test_validator.py`
Kapının regresyona uğramadığını doğrulayan 6 birim testi:
iyi strateji onaylanır, kötü reddedilir, yetersiz veri reddedilir,
yüksek iflas riski veto edilir, deneme sayısı DSR'ı düşürür, deploy kararı
tutarlıdır. `python tests/test_validator.py` ile çalışır (6/6 geçiyor).

---

## 🐛 Bu turda düzeltilen
- **Global RNG kirlenmesi**: `kriz_senaryolari` ve `bootstrap_stres` içindeki
  `np.random.seed(42)` / `np.random.choice` global RNG state'ini
  sıfırlıyordu (diğer modülleri ve birbirini etkileyebilirdi). İzole
  `np.random.default_rng()` üreteçlerine geçildi — tekrarlanabilir + temiz.
- **İç içe klasör temizliği**: Kopyalama sırasında v24 içine sızan
  yinelenen `astra_v23/` klasörü kaldırıldı.

---

## Yeni config Anahtarları (.env'den ayarlanabilir)
```
VALIDATOR_MIN_SKOR=60.0          # 100 üzerinden geçme eşiği
VALIDATOR_MIN_DSR=0.0            # Deflated Sharpe alt sınırı
VALIDATOR_MAX_DD_PCT=35.0        # Worst-case drawdown tavanı (%)
VALIDATOR_MIN_WF_TUTARLILIK=0.55 # Pozitif WF pencere oranı
VALIDATOR_BOOTSTRAP_N=2000       # Bootstrap simülasyon sayısı
```

## Davranış Notu
- Validator yalnızca **yeni pozisyonları** engeller; açık pozisyonlar
  normal SL/TP/trailing ile yönetilmeye devam eder.
- İlk çalıştırmada işlem geçmişi olmadığı için tüm coin'ler "varsayılan
  izinli" başlar; veri biriktikçe kapı sıkılaşır.
