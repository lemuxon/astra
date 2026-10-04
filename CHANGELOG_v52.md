# ASTRA v52.0 — SATIR SATIR İNCELEME: 5 KRİTİK FİNANSAL BUG

## Tarih: 2026-08-11 | Temel: v51.0
En yüksek finansal riskli 5 dosya SATIR SATIR okundu (2107 satır):
execution_engine.py, risk_manager.py, adaptive_sizing.py,
binance_futures_client.py, paper_trading.py

---
## 🔴 BUG 1: Minimum Pozisyon Boyutu TÜM Risk Limitlerini Eziyordu
**Dosya:** `engines/adaptive_sizing.py:114-115`

### Sorun
```python
usdt = min(usdt, self.max_usdt, max_by_balance, bakiye * 0.9)
usdt = max(usdt, 5.0)   # ← minimum, limitlerden SONRA
```
Minimum zorlaması bakiye ve risk limitlerinden sonra uygulanıyordu.

### Kanıtlanan etki (gerçek testle ölçüldü)
| Senaryo | Olması gereken | Gerçekleşen |
|---|---|---|
| Bakiye 8$ (limit %15 = 1.20$) | 1.20$ | **5.00$ (4.2x AŞIM)** |
| 4 ard arda kayıp, bakiye 30$ | 4.50$ | **5.00$ (streak koruması EZİLDİ)** |

İkincisi özellikle tehlikeli: bot kaybederken pozisyonu küçültme
koruması (streak_mult=0.3) minimum tarafından geçersiz kılınıyordu.
Yani **kaybederken riski artıran** bir hata.

### Düzeltme
Boyut minimumun altındaysa `0.0` dönülüyor → işlem AÇILMIYOR.
Çağıran taraf zaten `if usdt_boyut < 5.0: return` ile bunu doğru
ele alıyor (doğrulandı). Normal işlemler etkilenmedi (test edildi).

---
## 🔴 BUG 2: Hayalet Pozisyon (slippage kapatma hatası yutuluyordu)
**Dosya:** `execution/execution_engine.py:285-289`

### Sorun
Slippage aşıldığında pozisyon kapatılıyordu ama:
```python
try: futures_market_kapat(sembol, yon)
except Exception: pass      # ← sessizce yutuluyor
return ExecutionSonuc(basarili=False, ...)
```
Kapatma başarısız olursa fonksiyon "işlem başarısız" döner AMA
pozisyon borsada **AÇIK** kalır — üstelik SL/TP henüz koyulmamış.
Sistem "işlem yok" sanır, borsada korumasız pozisyon durur.

### Düzeltme
3 kez kapatma denemesi + başarısızsa kritik log + RISK_LIQUIDATION
olayı + hata mesajında "MANUEL MÜDAHALE" uyarısı.

---
## 🔴 BUG 3: Sıfır Dolum Kontrolü Yoktu
**Dosya:** `execution/execution_engine.py:258-267`

### Sorun
Sadece `orderId` varlığı kontrol ediliyordu. Emir gönderilip HİÇ
dolmamışsa (`executedQty=0`) kod devam edip var olmayan pozisyona
SL koymaya çalışıyordu → v51 mantığı "pozisyonu kapat" derken
kapatılacak pozisyon yoktu.

### Düzeltme
`exec_miktar <= 0` → emir iptal edilir, işlem başarısız döner.
Ayrıca **kısmi dolum tespiti** eklendi: beklenenin %90'ından azı
dolduysa uyarı loglanır (SL/TP gerçek miktara göre koyulur).

---
## 🔴 BUG 4: Marjin Kontrolü Fail-Safe İhlali
**Dosya:** `engines/risk_manager.py:281`

### Sorun
```python
if toplam_bakiye <= 0: return False   # ← "limit aşılmadı" = İZİN VER
```
Bakiye bilinmiyorsa/sıfırsa marjin oranı hesaplanamaz. Kod bu durumda
işleme **izin veriyordu**. Ağ hatasında bakiye 0 dönerse marjin
koruması tamamen devre dışı kalıyordu.

### Düzeltme
Bakiye bilinmiyorsa `True` (ENGELLE) dönülüyor. "Şüphede işlem yapma."

---
## ✅ DOĞRULAMA: Paper Trading Çalışıyor
Kullanıcının loglarındaki GERÇEK sinyal (ETHUSDT, AI=-9, güven %75,
"ULTRA STRONG SELL") uçtan uca test edildi:
```
Sonuç: 1 açık paper pozisyon
  ✅ İŞLEM AÇILDI: ETHUSDT SHORT @ 1660.16
```
Paper trading mantığında bug YOK. v47'de düzeltilen sıralama hatası
(sinyal_isle'nin grafik çiziminden sonra çağrılması) tek engelmiş.
Sunucuda artık paper işlemler birikmeye başlamalı.

---
## 📌 TESPİT EDİLEN TASARIM RİSKİ (düzeltilmedi, bilinçli)
**Smart execution slippage korumasını atlıyor** (`execution_engine.py:278`).
v23'te TWAP ortalamasının yanlış tetiklenmemesi için eklenmiş — mantıklı,
ancak büyük emirlerde hiç slippage koruması kalmıyor. Değiştirmek
TWAP davranışını bozabileceğinden dokunulmadı, ancak bilinmeli.

---
## Test Paketi: 47 → 51 test
Yeni testler:
- `test_minimum_boyut_limitleri_ezmez` (BUG 1)
- `test_normal_boyut_bozulmadi` (regresyon koruması)
- `test_sifir_dolum_pozisyon_acmaz` (BUG 3)
- `test_slippage_kapatilamazsa_uyarir` (BUG 2)

## Doğrulama
- 80 dosya syntax temiz
- **51/51 test geçiyor** (26 çekirdek + 19 execution + 6 validator)
- main.py tam import OK
- Her düzeltme somut senaryoyla ölçülerek doğrulandı
