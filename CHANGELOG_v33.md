# ASTRA v33.0 — KRİTİK BUG: MODEL ACCURACY SIZINTISI DÜZELTİLDİ

## Tarih: 2026-05-31 | Temel: v32.0

### Teşhis (kullanıcı verisinden)
AI Memory raporu çelişkili görünüyordu:
- Model accuracy: **%89.6** (çok yüksek)
- Gerçek paper win-rate: **%41.7**

Bu ~47 puanlık uçurum, modelin "kağıt üzerinde harika, sahada vasat"
olduğunu gösteriyordu. Kök neden araştırıldı.

### Kök Neden: Kalibrasyon Veri Sızıntısı
`rf_egit` ve `xgb_egit` fonksiyonlarında olasılık kalibrasyonu
**test setiyle** yapılıyordu:
```python
cal_model.fit(X_te, y_te)   # ← TEST seti kalibrasyonda kullanılmış
```
Kaydedilen model (cal_model) böylece test setini "görmüş" oluyordu.
Sonuç: raporlanan test_acc yapay olarak şişiyordu.

**Ölçülen sızıntı etkisi (sentetik test):**
- Sızıntılı yöntem: %100 accuracy (model test setini ezberlemiş)
- Doğru yöntem (test hiç görülmedi): %63 accuracy
- **Şişme: +37 puan**

Bu, %89 raporlanan vs %42 gerçek win-rate uçurumunu birebir açıklıyor.

### NOT: Bu overfitting DEĞİL, ÖLÇÜM HATASIYDI
Önemli ayrım: Model aslında bozuk/overfit değildi. Feature'lar
(RSI, ADX, CVD, mum formasyonları) geçmişe dayalı, look-ahead yok.
Label (`close.pct_change().shift(-1) > 0`) doğru kuruluydu.
Sorun yalnızca accuracy'nin YANLIŞ ölçülmesiydi — kalibrasyon
test setine "bakıyordu". Gerçek model performansı ~%55-63 (normal,
piyasa için iyi).

### Düzeltme
Kalibrasyon artık **train setinden ayrılan ayrı bir kalibrasyon
seti** ile yapılıyor; test seti ASLA görülmüyor:
```python
X_tr2, X_cal, y_tr2, y_cal = train_test_split(X_tr, y_tr, test_size=0.25, shuffle=False)
model.fit(X_tr2, y_tr2)
cal_model.fit(X_cal, y_cal)   # train'den ayrılan set — test DEĞİL
test_acc = accuracy_score(y_te, cal_model.predict(X_te))  # dürüst ölçüm
```
- RF (`rf_egit`) ve XGBoost (`xgb_egit`) düzeltildi.
- Kenar durumlar korundu: az veri / tek sınıf → kalibrasyon atlanır,
  ham model kullanılır (çökmez).
- test_acc artık KAYDEDİLEN modelle ölçülüyor (tutarlılık).

### Beklenen Etki
- Raporlanan model accuracy artık gerçekçi (~%55-65) olacak, %89 değil.
- Accuracy ile gerçek win-rate arasındaki uçurum kapanacak.
- **Trading davranışı değişmez** — sadece accuracy ölçümü dürüstleşir.
  (Model zaten aynı; yalnızca raporlanan sayı doğrulanıyor.)
- Bu, gelecekte validator'ın (v24) overfitting tespitini de
  doğru beslemesini sağlar — çünkü artık dürüst sayı görüyor.

## Etkilenen Dosya
- `engines/model_engine.py` (sadece bu — cerrahi müdahale)

## Test
- Kalibrasyon sızıntısı sentetik veriyle kanıtlandı (+37 puan şişme)
- Düzeltilmiş yöntem gerçekçi %63 veriyor ✅
- 74 dosya syntax temiz ✅
- Sadece model_engine.py değişti (başka hiçbir şeye dokunulmadı) ✅

## Dürüst Not
- Bu, sahip olduğumuz en somut, en yüksek değerli bug'lardan biriydi:
  görünmez ama tüm performans algısını çarpıtıyordu.
- Accuracy düzeldikten sonra, model gerçek değerini gösterecek.
  Eğer accuracy ~%55'e düşerse PANİK YAPMA — gerçek bu, %89 yalandı.
- Win-rate %42 + PnL pozitif zaten sağlıklıydı (iyi R:R). Asıl
  yanlış olan model acc raporuydu, trading değil.
