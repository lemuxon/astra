# ASTRA v30.0 — VERSİYON TUTARLILIĞI + TELEGRAM AKIŞI + SAĞLAMLAŞTIRMA

## Tarih: 2026-05-30 | Temel: v29.0

Kullanıcı isteği: v29'u detaylı incele, oluşabilecek bug'ları düzelt,
paneldeki versiyonları güncelle, Telegram akışını düzelt, tüm dosyaları
kontrol edip sağlam rötuşları yap.

---

## 🔴 Telegram Akışı Düzeltildi (en önemli)

### Kök Neden
Tüm komut yanıtları (`/risk`, `/bakiye`, `/btc` ...) `telegram_gonder`'i
varsayılan `tip="genel"` + `force=False` ile çağırıyordu. `telegram_gonder`
aynı `tip` için rate-limit uyguluyor (varsayılan 30s+). Sonuç:
**kullanıcı arka arkaya komut yazınca ikinci/üçüncü komutun yanıtı
rate-limit'e takılıp HİÇ gitmiyordu.** "Komuta cevap gelmiyor" şikayetinin
sebebi buydu.

### Düzeltme
18 komut yanıtının tamamı `force=True` ile gönderiliyor — komut yanıtları
artık her zaman gider, rate-limit'i bypass eder. Otomatik bildirimler
(sinyal, rejim, A/B raporu) hâlâ rate-limited kalır (spam önleme korunur).

---

## 🟠 Versiyon Tutarlılığı (panel + her yer)

### Sorun
Kod tabanında v13, v15, v16, v25, v26, v27, v29 gibi karışık versiyon
string'leri vardı. Kullanıcıya görünen yerler tutarsızdı:
- Telegram coin raporu: "ASTRA v15"
- Konsol banner: "ASTRA v16.0 PRODUCTION"
- Dashboard başlığı: "ASTRA v27 Dashboard"
- Dashboard footer: "v26.0"
- LIVE MODE log: "ASTRA v13"
- Telegram bot log: "v27"

### Düzeltme: Tek Kaynak (Single Source of Truth)
- `config.py`'ye merkezi sabit eklendi:
  `ASTRA_VERSION = "v30.0"` + `ASTRA_SURUM_ETIKET`
- main.py'deki 6 kullanıcıya görünen string bu sabite çevrildi.
- Dashboard HTML'i servis edilirken `__ASTRA_VERSION__` placeholder'ı
  config'ten dinamik olarak doldurulur (title + footer + log).
- 51 dosyanın başlık banner'ı v30.0'a güncellendi.

**Artık sürüm değişince tek yer (`config.ASTRA_VERSION`) güncellenir,
her yer otomatik tutarlı olur.** Bu sorun bir daha yaşanmaz.

---

## 🔍 Detaylı Bug Taraması (sorun bulunmadı — doğrulandı)

Sistematik kontroller yapıldı:
- **Telegram komut bütünlüğü**: 36 komut kayıtlı, hepsinin fonksiyonu
  tanımlı ✅ (v27'deki "eksik fonksiyon → bot çöküyor" hatası tekrarlamadı)
- **Modüller-arası importlar**: tüm `from X import Y` çözümleniyor ✅
- **config importları**: import edilen tüm config anahtarları tanımlı ✅
- **Bare except**: 0 adet (hepsi spesifik exception) ✅
- **KeyError riski**: `sonuc[...]` doğrudan erişimler güvenli bağlamda ✅
- **Fonksiyon tanım sırası**: `giris_gecikme_ozet` modül seviyesinde,
  runtime çağrıda sorun yok ✅
- **74 dosya syntax temiz** ✅

---

## Etkilenen Dosyalar
| Dosya | Değişiklik |
|-------|-----------|
| `config.py` | Merkezi ASTRA_VERSION sabiti |
| `main.py` | 6 versiyon string'i merkezileştirildi + 18 komut force=True |
| `api/dashboard.py` | Versiyon placeholder enjeksiyonu (title/footer/log) |
| 51 dosya | Başlık banner versiyonu → v30.0 |

---

## Not
Bu sürüm davranışı değiştirmez (Telegram komut yanıtları hariç — artık
güvenilir gider). Mevcut `.env` ayarlarınla doğrudan çalışır. v29'daki
thread güvenliği, v28'deki gecikme çözümü, v27'deki dampening düzeltmeleri
korunur.
