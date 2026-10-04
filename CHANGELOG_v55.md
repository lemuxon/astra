# ASTRA v55.0 — EŞZAMANLILIK + RECONCILER + LOG SPAM

## Tarih: 2026-08-11 | Temel: v54.0
Satır satır incelenen: `duplicate_guard.py` (144), `order_reconciler.py` (200),
`exchange_failover.py` (119), `state_audit.py`, `fill_reconciler.py`

---
## 🔴 BUG 1: DuplicateGuard Lock İçinde Ağ Çağrısı (thread tıkanması)
**Dosya:** `execution/duplicate_guard.py:85`

### Sorun
`_binance_pozisyon_var()` (HTTP isteği, yavaş ağda 15s'e kadar)
**LOCK İÇİNDE** çağrılıyordu. Bu süre boyunca aynı guard'ı kullanan
TÜM thread'ler bloklanıyordu → ana döngü tıkanması → watchdog alarmı.
Klasik eşzamanlılık anti-pattern'i.

**Bu, kullanıcının yaşadığı "bot takılıyor" sorununa katkıda bulunmuş olabilir.**

### Düzeltme
Akış yeniden düzenlendi: (1) lock al → hızlı kontroller + kilit → lock bırak,
(2) ağ sorgusu LOCK DIŞINDA, (3) sonuca göre kilidi bırak.
Atomiklik korunur (kilit ağ sorgusundan ÖNCE alınıyor).
Ayrıca sorgu başarısızsa fail-safe: işleme İZİN VERİLMEZ.

### Test kanıtı
3 farklı sembol, her biri 1s ağ gecikmesi → toplam **1.0s** (paralel).
Eski kodda 3.0s (seri) olurdu. Duplicate koruması hâlâ çalışıyor
(5 eşzamanlı istekten 1'i geçti).

---
## 🔴 BUG 2: Acil SL Kaldıraçtan Bağımsızdı
**Dosya:** `engines/order_reconciler.py:142`

### Sorun
SL'siz pozisyon tespit edilince acil SL **sabit %5** mesafeye konuyordu.
Kaldıraç dikkate alınmıyordu:

| Kaldıraç | %5 SL → sermaye kaybı |
|---|---|
| 5x | %25 |
| 10x | %50 |
| 20x | **%100 (likidasyon!)** |

### Düzeltme
Mesafe = `min(%5, (1/kaldıraç) × 0.5)` → likidasyona olan mesafenin
en fazla YARISI. 20x'te %2.5 → maks %50 kayıp. Doğrulandı.

---
## 🔴 BUG 3: Reconciler Hataları DEBUG'da Gizleniyordu
**Dosya:** `engines/order_reconciler.py:120,152`

`sync_open_positions` ve `sync_open_orders` hataları `log.debug` ile
yutuluyordu. Bu fonksiyonlar SL güvenlik ağıdır — sessizce çökerse
kullanıcı korumasız olduğunu BİLMEZ. Yanlış güven, korumasızlıktan
daha tehlikelidir.
→ `log.error` ile görünür yapıldı.

---
## 🔴 BUG 4: FAILOVER Log Spam'inin Kök Nedeni (kullanıcı semptomu çözüldü)
**Dosya:** `engines/exchange_failover.py:_recover`

### Kullanıcının gözlemi
Loglarda sürekli `[FAILOVER] ✅ Birincil tekrar aktif` mesajı.

### Kök neden
Config'de `BACKUP_FUTURES_URL` varsayılanı `FUTURES_BASE_URL` ile AYNI
(testnet için doğal). Bu durumda `_aktif == _backup` **HER ZAMAN doğru**
→ `_recover()` her sağlık kontrolünde çalışıp mesajı tekrar basıyordu.
Hem gürültü hem GERÇEK failover olaylarını maskeliyor.

### Düzeltme
`_failover()` ve `_recover()` artık `backup == primary` ise sessizce
çıkıyor (failover zaten anlamsız). Ayrıca hata sayacı thread-güvenli.

### Test: 10 `_recover()` çağrısı → **0 log mesajı** ✅

---
## Test Paketi: 57 → 60 test
- `test_guard_lock_agda_bloklamaz` (paralellik kanıtı)
- `test_guard_ayni_sembol_duplicate_engeller` (regresyon koruması)
- `test_guard_sorgu_hatasinda_engeller` (fail-safe)

## Doğrulama
- 80 dosya syntax temiz
- **60/60 test geçiyor** (26 çekirdek + 28 execution + 6 validator)
- main.py tam import OK

## Kümülatif (v52→v55)
Satır satır incelenen: 14 dosya (~4300 satır)
Bulunan ve düzeltilen bug: **14**
