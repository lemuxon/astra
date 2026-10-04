# ASTRA v29.0 — EŞZAMANLILIK (THREAD) SAĞLAMLAŞTIRMASI

## Tarih: 2026-05-29 | Temel: v28.0

### Sorunun teşhisi (kullanıcı raporundan)
Projede 18 Thread oluşturma noktası var (Online Learner, Retrain, Order
Engine, Position State, Reconciler, Dashboard, Websocket...). Bunların
hepsi `daemon=True` ve çoğu isimli — bu iyi. AMA hepsi **paylaşılan
state'e** (model dosyaları, pozisyonlar, veritabanı, bakiye) dokunuyor.
Kilitsiz erişimde race condition, bozuk model dosyası, çift emir ve
"database is locked" hataları oluşabilir. Bu sürüm o riskleri kapatır.

---

## 🔴 Risk 1: Eşzamanlı Retrain Aynı Model Dosyasını Bozuyor

### Kök Neden
`_self_train_tetikle` hiçbir koruma olmadan retrain thread'i açıyordu.
Aynı coin için 3 farklı yerden tetikleniyor (pozisyon kapanışı, drift,
adaptif). Senaryo: pozisyon kapandı→retrain başladı (30sn sürer), 5sn
sonra drift→**ikinci retrain thread'i** başladı. İkisi aynı `.pkl`
dosyasına yazınca → bozuk model → bir sonraki okuma EOFError → model silinir.

### Düzeltme
- **Per-coin retrain guard**: Bir coin retrain edilirken (`_retrain_aktif`
  seti) aynı coin için ikinci tetikleme atlanıyor. `finally` ile serbest
  bırakılıyor. (Test: 5 ardışık tetikleme → 1 retrain çalışıyor.)
- Aynı koruma **TFT retrain** (model_engine) ve **RL retrain**
  (rl_environment) için de eklendi — her biri kendi dosyasına yazıyor.

---

## 🔴 Risk 2: Model Dosyası Yazma Atomik Değildi

### Kök Neden
`model_kaydet` / `scaler_kaydet` doğrudan hedef dosyaya yazıyordu. Ana
döngü o sırada yarı yazılmış dosyayı okursa → bozuk model.

### Düzeltme
- Atomik yazma: önce `.tmp` dosyasına yaz, sonra `os.replace()` (atomik
  rename). Yarı yazılmış dosya asla okunmaz.
- `_model_io_lock` ile dosya I/O serialize edildi.

---

## 🔴 Risk 3: Servislerde Çift Başlatma Koruması Yok

### Kök Neden
`order_engine.start()`, reconciler, watchdog, fill_reconciler, state_audit,
failsafe, failover, websocket — hiçbirinde "zaten çalışıyor mu" kontrolü
yoktu. İki kez çağrılırsa (mimaride hem `futures_dashboard` hem
`bootstrap/app_init` başlatma yolu var) iki paralel loop → **çift emir
gönderme** riski (order_engine'de en tehlikelisi).

### Düzeltme
8 servisin `start()` metoduna çift-başlatma guard'ı eklendi:
`if self._thread and self._thread.is_alive(): return`.
Websocket'e de `_ws_thread.is_alive()` kontrolü eklendi.

---

## 🟠 Risk 4: SQLite Eşzamanlı Yazımda Kilitlenme

### Kök Neden
Reconciler + ana döngü + position_state + journal aynı anda SQLite'a
yazıyor. WAL mode olmadan "database is locked" hatası riski.

### Düzeltme
- `trade_journal`, `model_registry`, `db_manager` bağlantılarına:
  - `PRAGMA journal_mode=WAL` (eşzamanlı okuma+yazma)
  - `PRAGMA busy_timeout=5000` (kilitliyse 5sn bekle, hata fırlatma)
  - `check_same_thread=False` + `timeout=10` (eksik olanlara eklendi)

---

## ✅ Doğrulanan (sorun bulunmadı)
- **İç içe lock yok** → deadlock riski düşük (otomatik tarama ile doğrulandı).
- **position_state** zaten tam lock korumalı (okuma+yazma+sync).
- **db_manager** tek bağlantı ama `self._lock` ile tüm erişim serialize.
- Tüm 18 thread `daemon=True` → ana süreç ölünce temiz kapanır.
- `bot` modu başlangıç akışı tek seferlik (guard'lar ekstra güvence).

---

## Etkilenen Dosyalar
| Dosya | Düzeltme |
|-------|----------|
| `main.py` | Retrain guard (Risk 1) |
| `engines/model_engine.py` | Atomik yazma + TFT guard (Risk 1,2) |
| `simulation/rl_environment.py` | RL retrain guard (Risk 1) |
| `engines/order_engine.py` | Çift başlatma guard (Risk 3) |
| `engines/order_reconciler.py`, `watchdog.py`, `exchange_failover.py` | Çift başlatma guard |
| `execution/fill_reconciler.py`, `state_audit.py`, `failsafe_liquidation.py` | Çift başlatma guard |
| `engines/websocket_manager.py` | Çift başlatma guard |
| `engines/trade_journal.py`, `model_registry.py`, `data/db_manager.py` | WAL mode (Risk 4) |

---

## Test Sonuçları
- Retrain guard: 5 eşzamanlı tetikleme → 1 retrain ✅
- Atomik yazma: tmp temizleniyor, hedef dosya bütün ✅
- İç içe lock taraması: 0 bulundu ✅
- 74 Python dosyası syntax temiz ✅

## Not
Bu değişiklikler davranışı değiştirmez, yalnızca **eşzamanlılık
güvenliğini** artırır. Race condition'lar seyrek ve rastgele oluştuğu için
("bazen model bozuluyor", "ara sıra database locked") en sinsi hatalardır;
bu sürüm onları kaynağında engeller.
