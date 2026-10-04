# ASTRA v31.0 — VERİYE DAYALI İNCE AYAR: GECİKME-PnL ANALİZİ

## Tarih: 2026-05-30 | Temel: v30.1

Kullanıcı paper verisi: win-rate %25→%46, PnL negatiften +0.92'ye
(v28 gecikme düzeltmesi işe yaramış). Ama örneklem küçük (13 işlem),
Sharpe +6.6 gibi şişmiş değerler var. Bu turda gecikmenin etkisini
TAHMİNLE değil VERİYLE ölçecek altyapı kuruldu.

## ⚠️ Önemli İlke: Aşırı-Optimizasyondan Kaçınma
13 işlemle eşik "optimize etmek" overfitting olur — geçmişe uyar,
geleceği bozar. Bu yüzden bu sürüm eşikleri OTOMATİK DEĞİŞTİRMEZ;
bunun yerine yeterli veri birikince VERİYE DAYALI ÖNERİ sunar.

## 🔬 Gecikme-PnL Korelasyonu (ana özellik)
Artık her giriş gecikmesi, o işlemin SONUCUYLA (PnL) eşleniyor:
- Pozisyon açılınca gecikme + fiyat kayması kaydedilir
- Pozisyon kapanınca PnL o kayda yazılır (`gecikme_pnl_esle`)
- Yeterli veri (≥6 kapanmış işlem) birikince analiz yapılır:
  **"Hızlı giren işlemler, yavaş girenlere göre daha mı kârlı?"**

`/gecikme` raporu artık şunu gösterir:
```
🔬 GECİKME-PnL ANALİZİ (8 işlem)
Hızlı giriş (≤12s) ort PnL: +0.360%
Yavaş giriş (>12s) ort PnL: -0.233%
⚠️ Hızlı girişler %0.593 daha iyi → gecikme ZARAR veriyor.
   Eşiği sıkılaştırmayı düşün (MAX_GIRIS_KAYMA_PCT düşür).
```
veya fark yoksa "✅ Hız ile PnL arasında belirgin fark yok" der.

**Bu, eşik ayarını körlemesine değil kanıtla yapmanı sağlar.**

## 🎯 Uyarlanabilir Slippage Eşiği
Sabit %0.35 eşik, volatil coinde (BTC pump) gereksiz işlem iptal
ediyordu. Artık ATR'ye uyarlanıyor:
- Sakin coin (ATR %0.5): eşik %0.43
- Volatil coin (ATR %3): eşik %0.70 (taban×2 ile sınırlı — güvenlik)

Volatil coinde gereksiz iptal azalır, ama aşırı kayma yine engellenir.

## Etkilenen Dosyalar
- `main.py`: gecikme-PnL eşleme + uyarlanabilir slippage + zengin /gecikme raporu
- `config.py`: v31.0

## Test Sonuçları
- Gecikme-PnL analizi: 8 işlemli senaryoda "gecikme zarar veriyor"
  tespitini doğru yaptı (hızlı +0.36% vs yavaş -0.23%) ✅
- Uyarlanabilir eşik: sakin %0.43, volatil %0.70 ✅
- 74 dosya syntax temiz, main.py import OK ✅

## Dürüst Not
- Bu altyapı eşik ayarını KOLAYLAŞTIRIR ama hâlâ veri gerektirir.
  En az 15-20 kapanmış işlem birikmeden /gecikme analizine güvenme.
- Şişmiş Sharpe (+6.6) küçük örneklem yanılgısıdır; birkaç yüz işleme
  kadar performans sayılarına temkinli yaklaş.
- Gerçek para öncesi LIVE_TRADING=false ile veri toplamaya devam et.
