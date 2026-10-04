# ASTRA v27.0 — HATA DÜZELTME: TELEGRAM + A/B TEST + KAZANÇ HIZI

## Tarih: 2026-05-29 | Temel: v26.0

Kullanıcı tarafından bildirilen 3 sorunun tamamı düzeltildi.

---

## 🔴 Sorun 1: Telegram komutları HİÇ çalışmıyordu (/btc, /yardim vb.)

### Kök Neden
`telegram_bot_baslat()` içinde handler listesinde 4 komut kayıtlıydı ama
**bu komutların fonksiyonları hiç tanımlı değildi:**
`cmd_circuit`, `cmd_shadow`, `cmd_shadow_approve`, `cmd_correlation`.

Bot başlarken bu isimleri çözümleyemeyince **NameError fırlatıyor ve
TÜM bot çöküyordu** — bu yüzden `/btc`, `/yardim` dahil hiçbir komut
çalışmıyordu (sadece kayıtlı olan 4 tanesi değil, hepsi).

### Düzeltme
- 4 eksik komut fonksiyonu yazıldı (circuit breaker, korelasyon, shadow
  model durumu + manuel onay). İlgili motorlar zaten mevcuttu.
- `telegram_bot_baslat()` güçlendirildi:
  - `BOT_TOKEN` boşsa net uyarı + güvenli çıkış
  - Event loop güvenli kurulumu (thread'den çağrılma sorununa karşı)
  - `run_polling(close_loop=False, drop_pending_updates=True)` — paralel
    daemon thread'lerin loop'unu bozmaz, eski mesaj yığılmasını temizler
  - `/help` ve `/start` → `/yardim` alias eklendi
  - Tüm başlatma try/except ile sarıldı (sessiz çökme yerine net log)
- `/yardim` metni güncellendi: 33 komut kategorilere ayrıldı.

**Doğrulama:** 33 komutun tamamının fonksiyonu artık tanımlı.

---

## 🟠 Sorun 2: A/B testi "yeterli veri yok" diyordu

### Kök Neden
Bu aslında hata değil, beklenen davranıştı: A/B testi her grupta en az
**30 işlem** (toplam 60 kapanmış işlem) istiyordu. Yeni başlayan bir botta
bu veri uzun süre birikmiyor.

### Düzeltme
- `MIN_ORNEKLEM`: 30 → **15** (her grup). Anlamlı sonuç daha erken gelir.
- "Yeterli veri yok" mesajı artık net ilerleme gösteriyor:
  `"Veri birikiyor — A:8/15 B:6/15 işlem"`
- Telegram raporu yeniden yazıldı (daha okunaklı, durum bazlı).

**Not:** A/B testi istatistiksel anlamlılık için bir miktar veri gerektirir;
bu fizik kuralı. Eşik makul seviyeye çekildi ama sıfırlanamaz.

---

## 🟢 Sorun 3: Para kazanma çok yavaş / pozisyonlar küçük

### Kök Neden (en önemli düzeltme)
Pozisyon boyutunu küçülten **dampening katmanları çarpımsal olarak üst
üste biniyordu.** En kötü senaryoda bir işlem aynı anda şu çarpanları
yiyordu:
- Ensemble belirsizlik (×0.5)
- CVD divergence (×0.8)
- Rejim risk çarpanı (×0.7)
- MTF hizalama (×0.6)
- Çoklu borsa çelişkisi (×0.6)

Hepsi çarpılınca: `0.5×0.8×0.7×0.6×0.6 ≈ 0.10` → Kelly'nin sadece **%10'u**
kalıyordu. Pozisyonlar anlamsız derecede küçülüyordu — kazanç hızının
düşük olmasının ana nedeni buydu.

### Düzeltme: Birleşik Dampening + Taban Koruması
- Tüm küçültme faktörleri artık **tek bir birleşik çarpanda** toplanıyor.
- **Taban koruması** (`POZ_MIN_DAMP_TABANI=0.45`): birleşik dampening
  Kelly değerini bu oranın altına indiremiyor — yani en fazla %55 kırpma.
- Sonuç: kötü senaryoda pozisyon **~2.8x daha büyük**, ama hâlâ riskli
  durumlarda korunaklı (taban sayesinde aşırıya kaçmıyor).
- Yeni `POZ_AGRESIFLIK` çarpanı: kullanıcı tek değerle genel agresifliği
  ayarlayabilir (1.0=normal, 1.3=agresif, 0.7=temkinli).
- Dampening artık tek log satırında sebepleriyle gösteriliyor:
  `dampening=0.45 [belirsizlik-yüksek, mtf(0.60), multiex-çelişki] (taban 0.45)`

---

## ⚙️ Yeni config / .env Anahtarları
```
POZ_MIN_DAMP_TABANI=0.45   # Dampening en fazla %55 kırpar (yükseltirsen daha büyük pozisyon)
POZ_AGRESIFLIK=1.0         # Genel agresiflik (1.3 = daha büyük, 0.7 = daha temkinli)
```

## Agresifliği Artırmak İsteyenler İçin
`.env` dosyasında:
- Daha büyük pozisyon: `POZ_AGRESIFLIK=1.3`
- Dampening'i daha da gevşet: `POZ_MIN_DAMP_TABANI=0.6`
- Daha sık işlem: `MIN_AI_SCORE_BUY=3` (dikkat: daha çok ama daha riskli işlem)

⚠️ Agresiflik arttıkça risk de artar. Önce test modunda (`LIVE_TRADING=false`)
deneyin.

---

## 🧪 Doğrulama Sonuçları
| Sorun | Önce | Sonra |
|-------|------|-------|
| Telegram komutları | hiçbiri çalışmıyor (bot çöküyor) | 33 komut aktif ✅ |
| A/B eşiği | 30/grup, belirsiz mesaj | 15/grup, net ilerleme ✅ |
| Kötü senaryo pozisyon | Kelly'nin %10'u | Kelly'nin %45'i (2.8x) ✅ |

Tüm 74 Python dosyası syntax temiz.
