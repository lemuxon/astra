# ASTRA AI TRADER v17.0 — CHANGELOG

## v17.0 (2026-05-29) — KRİTİK BUG FIX + AKILLI ÖĞRENME SİSTEMİ

### 🔴 Kritik Bug Düzeltmeleri

**BUG-1: `_execution_isle` → `yon` UnboundLocalError [CRASH]**
- `correlation_eng.pozisyon_acilabilir_mi(sembol, yon, ...)` çağrısında `yon`
  değişkeni henüz tanımlanmamıştı → canlı işlem sırasında `UnboundLocalError` crash.
- Düzeltme: `yon = "LONG" if is_buy else "SHORT"` satırı correlation bloğunun ÖNÜNE taşındı.

**BUG-2: `_self_train_tetikle` — Model öğrenemiyordu [SESSİZ HATA]**
- Pozisyon kapandığında `_self_train_tetikle` çağrılıyordu ama `feedback_ekle` hiç çağrılmıyordu.
  Model kapanan işlemin sonucunu (win/loss) öğrenemiyordu. Self-training tamamen pasifti.
- Düzeltme: `feedback_ekle(sembol, son_features, gercek_sonuc, pnl_pct)` eklendi.
- `RETRAIN_MIN_FEEDBACK` eşik kontrolü eklendi — az veriyle gereksiz retrain önlendi.

**BUG-3: Feedback çift yükleme — 2x veri şişmesi [VERİ BÜTÜNLÜĞÜ]**
- `coin_analiz` içinde `feedback_veri_yukle` çağrılıyor, ardından
  `en_iyi_model_yukle_veya_egit` kendi içinde tekrar çağırıyordu.
  Her eğitimde feedback verisi 2 kat büyük görünüyordu → overfitting riski.
- Düzeltme: `coin_analiz`'den gereksiz çağrı kaldırıldı.

**BUG-4: `rl_reward_kaydet` — ai_score katkısı sıfır [ÖĞRENME KALİTESİ]**
- RL reward hesabında ai_score hiç kullanılmıyordu. Güçlü bir tahmin yapıp
  kazanmak ile zayıf bir tahminle kazanmak aynı reward'ı alıyordu.
- Düzeltme: Güçlü + doğru tahmin bonusu (+0.5), güçlü + yanlış tahmin cezası (-0.5).

**BUG-5: `cmd_selflearn` feedback path hatası [KOMUT BOZUK]**
- Feedback dosyası aranırken `sembol.replace('-','_')` yapılmıyordu.
  Bazı semboller için feedback sayısı hep 0 görünüyordu.
- Düzeltme: Tüm feedback path'lerinde `replace('-','_')` standardize edildi.

---

### 🟢 Yeni Özellikler

**Feature Drift Dedektörü**
- Her analiz döngüsünde son 50 feature snapshot saklanır.
- RSI, MACD, ATR_pct, Volume_Ratio, ADX için Z-score analizi yapılır.
- Ortalama z-score > 2.5 sigma → drift uyarısı + otomatik background retrain tetiklenir.
- `_ogrenme_metrikleri[sembol]["drift_uyari"]` flag'i set edilir.

**Adaptif Öğrenme Hızı (Adaptive Retrain Scheduling)**
- Son 25 işlemin win rate'ine göre retrain sıklığı otomatik ayarlanır:
  - Win rate < %40 → 15 dakikada bir retrain (KRİTİK mod)
  - Win rate < %50 → 30 dakikada bir retrain (UYARI modu)
  - Win rate ≥ %50 → 60 dakikada bir retrain (NORMAL mod)
- Her ana döngü iterasyonunda `_adaptif_retrain_gerekli_mi()` çağrılır.

**Gelişmiş `/selflearn` Raporu**
- Telegram komutu artık per-coin şunları gösteriyor:
  - Toplam win/loss sayısı ve oran
  - Son 25 işlem penceresi win rate
  - Feature drift uyarı durumu (⚠️ veya ✅)
  - RL reward ortalaması (son 20 işlem)
  - Feedback kayıt sayısı (disk)

---

> Önceki sürüm geçmişi için orijinal CHANGELOG.md dosyasına bakın.
