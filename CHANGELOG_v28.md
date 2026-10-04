# ASTRA v28.0 — SAĞLAMLAŞTIRMA + GİRİŞ GECİKMESİ ÇÖZÜMÜ

## Tarih: 2026-05-29 | Temel: v27.0

### Sorunun teşhisi (kullanıcı raporundan)
Model doğruluğu artıyordu (%63) AMA paper trading kazanç oranı %25 ve
PnL negatifti. Bu kopukluk net bir işarettir: **sorun tahmin motorunda
değil, tahmin ile işlem arasındaki gecikmede.** Model "yukarı gidecek"
diyor, doğru diyor — ama o fiyattan giremiyoruz, hareket başladıktan
sonra geç giriyoruz, tepede alıp dönüşte stop yiyoruz.

---

## 🎯 Ana Düzeltme: Stale Fiyat → Canlı Fiyat + Slippage Guard

### Kök Neden
`_execution_isle` işlem fiyatı olarak `sonuc["son_close"]` kullanıyordu —
bu, **kapanmış 5 dakikalık mumun fiyatı (stale).** Sinyal doğduktan sonra
analiz + 8 kontrol katmanı + tarama aralığı saniyeler/dakikalar alıyordu.
İşlem bu eski fiyatla açılınca gerçekte çok geç giriliyordu.

### Çözüm
- İşlem anında **canlı fiyat** (`futures_anlık_fiyat`) çekiliyor, stale
  `son_close` yerine ondan giriliyor.
- **Slippage Guard**: Sinyal anından bu ana kadar fiyat, işlem yönünün
  ALEYHİNE `MAX_GIRIS_KAYMA_PCT` (varsayılan %0.35) fazla kaçtıysa giriş
  **iptal** edilir. Mantık: "Geç kaldık, artık iyi giriş değil — fiyatı
  kovalama." Bu, tam olarak "tepede alma" sorununu hedefler.
- Canlı fiyat alınamazsa güvenli şekilde stale fiyata düşer.

---

## 📊 Giriş Gecikme Ölçümü (kanıtlama)

Artık her giriş denemesinde ölçülüyor ve loglanıyor:
- Sinyalin doğduğu an → emrin gittiği an arası **gerçek gecikme (saniye)**
- Bu sürede fiyatın ne kadar kaydığı (%)
- Geç giriş yüzünden iptal edilen işlem sayısı

**`/gecikme`** komutu: ortalama/medyan/maks gecikme, ortalama kayma,
iptal oranı. Sinyal dict'ine `sinyal_ts` zaman damgası eklendi.

Bu sayede "gecikme gerçekten azaldı mı?" sorusunu tahminle değil
**veriyle** cevaplayabilirsin.

---

## ⚡ Hızlı Tarama (HIZLI_TARAMA)

Güçlü sinyal (|AI| ≥ 5) aktifken tarama aralığı otomatik kısalır:
60s → 20s. Sinyalin doğması ile bir sonraki kontrol arası gecikme azalır.
Sakin piyasada normal aralıkta kalır (gereksiz API yükü yok).

---

## 🛡️ Sağlamlaştırma / Recovery (canlıya hazırlık)

### Açılış Pozisyon Güvenlik Kontrolü (STATE_RECOVERY)
Bot her başladığında borsadaki açık pozisyonları kontrol eder:
- Her açık pozisyonun **SL koruması gerçekten borsada var mı?**
- Bot çökmüşken bir pozisyon SL'siz kalmışsa → **kritik Telegram uyarısı**
  ("korumasız pozisyon: X — /fpoz ile kontrol et").

Bu, canlı işlemde en tehlikeli senaryoyu (bot çöktü, pozisyon korumasız,
kontrolsüz risk) yakalar. Mevcut `binance_ile_sync` ve
`orphan_sl_tp_temizle` üzerine eklenir.

---

## ⚙️ Yeni config / .env Anahtarları
```
MAX_GIRIS_KAYMA_PCT=0.35   # Sinyal sonrası fiyat aleyhe bu %'den kaçarsa giriş iptal
HIZLI_TARAMA=true          # Güçlü sinyalde tarama 60s→20s
STATE_RECOVERY=true        # Açılışta korumasız pozisyon kontrolü
```

### Ayar önerileri
- Çok işlem iptal oluyorsa (volatil piyasa): `MAX_GIRIS_KAYMA_PCT=0.5`
- Daha sıkı (sadece mükemmel girişler): `MAX_GIRIS_KAYMA_PCT=0.2`

---

## 🧪 Doğrulama
| Senaryo | Sonuç |
|---------|-------|
| Lehe fiyat hareketi | giriş yapılır ✅ |
| Hafif aleyhe (eşik altı) | giriş yapılır ✅ |
| Çok aleyhe (geç kalındı) | giriş İPTAL ✅ |
| 36 Telegram komutu | hepsi tanımlı ✅ |
| 74 Python dosyası | syntax temiz ✅ |

---

## Beklenen Etki
Bu değişiklikler doğrudan "model doğru ama işlem kötü" kopukluğunu
hedefler. **Ancak gerçek etkiyi `/gecikme` raporuyla ve birkaç günlük
paper trading sonrası win-rate değişimiyle ölçmek gerekir** — bu bir
varsayım değil, ölçülebilir bir hipotez. Önce `LIVE_TRADING=false` ile
çalıştırıp `/gecikme` ve `/paper` raporlarını karşılaştır.
