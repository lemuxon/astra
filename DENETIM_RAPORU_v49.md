# ASTRA — KAPSAMLI KOD DENETİM RAPORU
**Denetim tarihi:** 2026-07-05 | **Sürüm:** v48 → v49 | **Denetçi rolü:** Staff Engineer / Security Engineer / Software Architect

---
## ÖZET

| Metrik | Değer |
|---|---|
| Toplam dosya | 121 |
| İncelenen dosya | 121 (%100) |
| Atlanan dosya | 0 |
| Bulunan sorun | 14 |
| Kritik (Critical) | 2 |
| Yüksek (High) | 3 |
| Orta (Medium) | 5 |
| Düşük (Low) | 4 |
| Bu turda düzeltilen | 5 |

---
## 1. İNCELENEN DOSYALAR

### Kök (7)
main.py, config.py, requirements.txt, baslat.sh, testleri_calistir.py, ENTEGRASYON.md, CHANGELOG.md

### core/ (8)
preflight.py, http_guard.py, teshis.py, indicators.py, market_regime.py, feature_store.py, hmm_regime.py, __init__.py

### data/ (9)
binance_client.py, binance_futures_client.py, market_data.py, database.py, db_manager.py, multi_exchange.py, onchain_data.py, sentiment.py, __init__.py

### engines/ (21)
model_engine.py, model_registry.py, risk_manager.py, kill_switch.py, paper_trading.py, watchdog.py, websocket_manager.py, backtest_engine.py, walk_forward_advanced.py, adaptive_sizing.py, online_learner.py, shadow_model.py, strategy_validator.py, performance_tracker.py, trade_journal.py, ab_test.py, edge_engine.py, exchange_failover.py, futures_trade_engine.py, portfolio_optimizer.py, __init__.py

### execution/ (5)
execution_engine.py, order_ack.py, order_reconciler.py, smart_execution.py, __init__.py

### risk/ (4), api/ (2), analytics/ (3), simulation/ (4), strategy/ (3), monitoring/ (3), nodes/ (3), utils/ (3), bootstrap/ (2), models/ (2), tests/ (3)
Tümü incelendi.

### Yapılandırma (5)
.env (KRİTİK BULGU), docker/Dockerfile, docker/docker-compose.yml, docker/prometheus.yml, docker/watchdog.sh

### Dokümantasyon (35)
CHANGELOG_v17 … CHANGELOG_v48 — sürüm geçmişi tutarlı, tespit edilen sorun yok.

---
## 2. KRİTİK HATALAR (Severity: Critical)

### [C-1] .env dosyası gerçek sırlarla birlikte dağıtım paketinde — DÜZELTİLDİ
- **Dosya:** `.env` (paket kökü)
- **Sorun:** Gerçek `BOT_TOKEN`, `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `CHAT_ID` değerleri zip içinde dağıtılıyordu.
- **Etki:** Paketi alan herkes Telegram botunu ele geçirebilir, Binance hesabına API erişimi kazanabilir. **Satış senaryosunda felaket.**
- **Yeniden üretim:** `unzip -l astra_v48.zip | grep .env` → dosya listede görünür.
- **Çözüm (uygulandı):** `.env.example` üretildi (sır alanları boş), `.gitignore` ve `.dockerignore` eklendi, paketleme `.env`'i hariç tutuyor.
- **KULLANICI AKSİYONU ZORUNLU:** Mevcut token/anahtarlar sızmış kabul edilmeli → @BotFather `/revoke` + Binance'te API anahtarlarını sil ve yeniden oluştur.

### [C-2] Dockerfile `COPY . .` ile sırları imaja gömüyordu — DÜZELTİLDİ
- **Dosya:** `docker/Dockerfile:16`
- **Sorun:** `.dockerignore` yoktu; `COPY . .` `.env`'i imaja dahil ediyordu.
- **Etki:** İmaj paylaşımı = anahtar sızıntısı. `docker history` ile katmanlardan okunabilir.
- **Çözüm (uygulandı):** `.dockerignore` eklendi (sırlar, veri, model, log, test hariç tutuldu).
- **Not:** Dockerfile'ın `USER astra` (non-root) kullanımı DOĞRU — bu konuda sorun yok.

---
## 3. YÜKSEK ÖNCELİKLİ (Severity: High)

### [H-1] Veritabanı bağlantı sızıntısı — DÜZELTİLDİ
- **Dosya:** `data/database.py`, 11 fonksiyon (sinyal_kaydet, trade_ac, trade_kapat, performans_kaydet, backtest_kaydet, son_sinyaller, acik_tradeler, toplam_pnl, win_rate_hesapla, model_gecmisi, tablolari_olustur)
- **Sorun:** `conn.close()` `try/finally` DIŞINDAydı. `execute()`/`commit()` exception fırlatırsa (disk dolu, DB kilitli, bozuk veri) bağlantı hiç kapanmıyordu.
- **Etki:** 7/24 çalışmada dosya tanıtıcıları birikir → `OSError: too many open files` → bot çöker. Sinsi, çünkü normal koşulda görünmez.
- **Yeniden üretim:** DB'yi salt-okunur yap, `sinyal_kaydet()` çağır; exception sonrası `/proc/PID/fd` sayısı artar.
- **Çözüm (uygulandı):** `@contextmanager baglanti()` eklendi; 11 fonksiyon `with baglanti() as conn:` yapısına dönüştürüldü.
- **Doğrulama:** 60 ardışık DB işlemi → dosya tanıtıcısı artışı **0**. Tüm fonksiyonlar fonksiyonel testten geçti.

### [H-2] Dashboard kimlik doğrulaması yok
- **Dosya:** `api/dashboard.py:857`
- **Sorun:** `HTTPServer(("0.0.0.0", 8080))` — tüm arayüzlerde dinliyor, auth katmanı yok.
- **Etki:** Sunucu IP'sini bilen herkes bakiye, pozisyon, strateji ve performans verilerini görebilir. Bilgi ifşası; rekabet/gizlilik riski.
- **Yeniden üretim:** Başka bir ağdan `http://SUNUCU_IP:8080` → panel açılır.
- **Önerilen çözüm:** (a) Kısa vade: firewall ile IP kısıtla — `ufw allow from SENIN_IP to any port 8080` ve `ufw deny 8080`. (b) Orta vade: Basic Auth ekle:
```python
# api/dashboard.py — do_GET başına
import base64
PANEL_USER = os.getenv("PANEL_USER", "")
PANEL_PASS = os.getenv("PANEL_PASS", "")
def _auth_ok(self):
    if not PANEL_USER: return True   # ayar yoksa kısıtlama yok
    h = self.headers.get("Authorization", "")
    if not h.startswith("Basic "): return False
    try:
        kullanici, sifre = base64.b64decode(h[6:]).decode().split(":", 1)
    except Exception:
        return False
    return kullanici == PANEL_USER and sifre == PANEL_PASS
# do_GET içinde ilk satır:
if not self._auth_ok():
    self.send_response(401)
    self.send_header("WWW-Authenticate", 'Basic realm="ASTRA"')
    self.end_headers(); return
```
- **Durum:** Bilinçli olarak UYGULANMADI — panel davranışını değiştirmek çalışan sistemi etkileyebilir; kullanıcı onayı gerekir. Firewall çözümü hemen uygulanabilir.

### [H-3] Test kapsamı %28 — kritik modüller test dışı
- **Dosya:** `tests/` (2 dosya, 30 test)
- **Sorun:** 61 modülün 17'sine dokunuluyor. Test EDİLMEYEN kritik modüller: `execution/execution_engine.py` (emir gönderimi!), `execution/order_ack.py`, `risk/*`, `engines/exchange_failover.py`, `engines/watchdog.py`, `core/http_guard.py`, `api/dashboard.py`.
- **Etki:** Emir yürütme yolunda regresyon fark edilmeden geçebilir — gerçek parada doğrudan zarar riski.
- **Önerilen çözüm:** Öncelik sırası: execution_engine → order_ack → http_guard → watchdog. Mock borsa yanıtlarıyla emir yaşam döngüsü testi yazılmalı.

---
## 4. ORTA ÖNCELİKLİ (Severity: Medium)

### [M-1] Yinelenen ağ çağrısı — DÜZELTİLDİ
- **Dosya:** `main.py:2133-2134` (eski)
- **Sorun:** Aynı blokta `futures_bakiye()` iki kez çağrılıyordu → iki ayrı Binance isteği, aynı veri için.
- **Etki:** Gereksiz gecikme + rate-limit tüketimi. Yavaş ağda tur süresini uzatır.
- **Çözüm (uygulandı):** Tek çağrı, sonuç değişkende tutuluyor.

### [M-2] `database.py` / `db_manager.py` işlev çoğaltması
- **Dosya:** İkisinde de `sinyal_kaydet, trade_ac, trade_kapat, performans_kaydet, backtest_kaydet, toplam_pnl, win_rate_hesapla, tablolari_olustur` (8 fonksiyon)
- **Sorun:** Farklı imzalar, farklı bağlantı yönetimi; çağıranlar karışık kullanıyor (`main.py` db_manager'dan, `model_engine.py` database'den).
- **Etki:** Bakım riski — biri güncellenip diğeri unutulursa veri tutarsızlığı.
- **Durum:** Birleştirme BİLİNÇLİ olarak yapılmadı (onlarca çağrı noktası, farklı imzalar → yüksek regresyon riski). Bunun yerine ikisi de aynı WAL + timeout korumasına kavuşturuldu (v40, v49).
- **Öneri:** Uzun vadede tek modüle indirilmeli, ancak kapsamlı test yazıldıktan SONRA.

### [M-3] 32 adet sessiz exception yutma (`except Exception: pass`)
- **Dosya:** Çeşitli (paper_trading, execution_engine, main.py vb.)
- **Sorun:** Hata sessizce yutuluyor; iz kalmıyor.
- **Etki:** Üretimde teşhis zorluğu; sorunlar görünmez şekilde birikebilir.
- **Kısmi düzeltme:** Kritik olanlar (execution_engine'de 3 adet) v39'da `log.debug`'a çevrildi. Kalanların çoğu gerçekten zararsız (opsiyonel özellik yokluğu).
- **Öneri:** Kalan geniş yutmalar kademeli olarak `log.debug` ile izlenebilir yapılmalı.

### [M-4] Bağlantı havuzu yok (SQLite her işlemde aç/kapat)
- **Dosya:** `data/database.py`
- **Sorun:** Her sorgu yeni bağlantı açıyor.
- **Etki:** Yüksek frekansta ölçekleme sınırı. Mevcut yükte (5 coin, 60s tur) sorun DEĞİL.
- **Durum:** Bilinçli yapılmadı — paylaşılan bağlantı thread-lock disiplini gerektirir; kazanç/risk oranı olumsuz.

### [M-5] `logs/` klasörü sınırsız büyüyor
- **Dosya:** `baslat.sh` (tee ile astra.log'a yazıyor)
- **Sorun:** Log rotasyonu yok.
- **Etki:** Aylar içinde disk dolabilir.
- **Öneri:** `logrotate` yapılandırması veya `RotatingFileHandler`:
```bash
# /etc/logrotate.d/astra
/root/astra_v49/logs/astra.log {
    daily
    rotate 7
    compress
    missingok
    copytruncate
}
```

---
## 5. DÜŞÜK ÖNCELİKLİ (Severity: Low)

### [L-1] 35 adet CHANGELOG dosyası kök dizinde
- Bakım/okunabilirlik: `docs/changelog/` altına taşınmalı.

### [L-2] `main.py` 2877 satır — tek dosyada çok sorumluluk
- SOLID (SRP) ihlali. v41'de teşhis modülü ayrıldı; Telegram komutları da `telegram/commands.py`'ye taşınabilir.

### [L-3] Tip ipuçları (type hints) kısmi
- Bazı fonksiyonlarda yok. `mypy` ile statik kontrol mümkün değil.

### [L-4] `requirements.txt` üst sınır (upper bound) yok
- `>=` kullanılıyor; bir bağımlılığın büyük sürümü kırıcı değişiklik getirebilir. `pandas>=2.0.0,<3.0.0` gibi sınırlar önerilir.

---
## 6. GÜVENLİK DENETİMİ (OWASP odaklı)

| Kontrol | Sonuç |
|---|---|
| SQL Injection | **TEMİZ** — 61 execute çağrısı; parametreli (`?`). `trade_journal.py:102` f-string kullanıyor ancak sütun adları dataclass'tan geliyor (kullanıcı girdisi değil), değerler parametreli → güvenli |
| Hardcoded secret | **TEMİZ** — kodda gömülü anahtar yok, hepsi `os.getenv` |
| Loglarda secret | **TEMİZ** — v38'de httpx/telegram logları WARNING'e çekilerek token sızıntısı önlenmiş (iyi uygulama) |
| Yetkilendirme (Telegram) | **TEMİZ** — `_yetkili_komut` dekoratörü kayıt anında 38 komutun TÜMÜNE uygulanıyor (`main.py:2849`); yetkisiz CHAT_ID reddediliyor |
| Path Traversal | **TEMİZ** — kullanıcı girdisinden dosya yolu oluşturulmuyor |
| XSS | **DÜŞÜK RİSK** — dashboard salt-okunur, kullanıcı girdisi DOM'a yazılmıyor |
| CSRF | **UYGULANAMAZ** — durum değiştiren HTTP endpoint yok (sadece GET /api/state) |
| SSRF | **TEMİZ** — dış URL'ler config'ten, kullanıcı girdisinden değil |
| Kimlik doğrulama (Panel) | **AÇIK** — bkz. [H-2] |
| Container güvenliği | **İYİ** — non-root `USER astra`, slim base image |
| Secret dağıtımı | **DÜZELTİLDİ** — bkz. [C-1], [C-2] |

---
## 7. PERFORMANS DENETİMİ

**İyi durumda:**
- Klines TTL önbelleği (v48) — döngü içi tekrar indirmeleri engelliyor
- `exchange_info` önbelleği mevcut
- Global HTTP timeout (v44) + Telegram/WS timeout (v46) — asılı kalma yok
- Sayısal kararlılık: 113 bölme işlemi guard'lı, sıfıra bölme yok
- Bellek: sınırsız büyüyen yapı yok (deque maxlen / [-N:] disiplini)
- matplotlib `plt.close()` mevcut — figür sızıntısı yok

**Bulgular:**
- [M-1] Yinelenen `futures_bakiye()` — düzeltildi
- 16 adet döngü içi I/O tespit edildi; incelendi, çoğu kaçınılmaz (coin başına veri çekimi). Kritik olan tekrarlar önbellekle çözülmüş.
- [M-4] DB bağlantı havuzu yok — mevcut ölçekte sorun değil

---
## 8. MİMARİ DEĞERLENDİRME

**Güçlü yönler:**
- Katmanlı yapı net: `data/` (erişim) → `engines/` (iş mantığı) → `execution/` (emir) → `api/` (sunum)
- **Circular dependency: 0** — bağımlılık grafiği asiklik (statik analizle doğrulandı)
- Çok katmanlı savunma: preflight → global timeout → watchdog → auto-restart
- Risk katmanları ayrıştırılmış (kill_switch, circuit_breaker, validator, korelasyon)
- Opsiyonel bağımlılıklar zarif şekilde ele alınmış (river/RL/TF yoksa özellik kapanıyor, bot çalışıyor)

**Zayıf yönler:**
- [L-2] `main.py` çok büyük (2877 satır) — SRP ihlali
- [M-2] Veri katmanında ikilik (`database.py` / `db_manager.py`)
- Bağımlılık enjeksiyonu yok — modüller doğrudan global singleton'lara bağlı; birim testi zorlaştırıyor ([H-3] ile ilişkili)

---
## 9. TEKNİK BORÇLAR

1. `main.py` modülerleştirmesi (kısmen başlandı: v41 teshis.py)
2. `database.py` / `db_manager.py` birleştirmesi (test ağı gerekiyor)
3. Test kapsamı %28 → hedef %60+
4. Log rotasyonu
5. Tip ipuçlarının tamamlanması + mypy entegrasyonu
6. CI yapılandırması yok (GitHub Actions ile test otomasyonu önerilir)

---
## 10. TEST KAPSAMI EKSİKLERİ

| Modül | Risk | Öncelik |
|---|---|---|
| execution/execution_engine.py | Emir gönderimi — gerçek para | **1** |
| execution/order_ack.py | Emir doğrulama | **2** |
| core/http_guard.py | Timeout garantisi | **3** |
| engines/watchdog.py | Donma tespiti | 4 |
| engines/exchange_failover.py | Borsa geçişi | 5 |
| risk/*.py | Risk limitleri | 6 |
| api/dashboard.py | Veri sunumu | 7 |

---
## 11. İNCELENEMEYEN DOSYALAR

**Yok.** 121 dosyanın tamamı incelendi.

Not: `saved_models/` ve `logs/` klasörleri boştu (paketleme sırasında temizleniyor) — içerik olmadığı için inceleme gerektirmedi, yapıları doğrulandı.

---
## 12. BU TURDA UYGULANAN DÜZELTMELER (v49)

| # | Düzeltme | Dosya |
|---|---|---|
| 1 | `.gitignore` eklendi (sır sızıntısı önleme) | `.gitignore` (yeni) |
| 2 | `.dockerignore` eklendi (imaja sır gömülmesi önlendi) | `.dockerignore` (yeni) |
| 3 | `.env.example` üretildi (sırlar temizlendi) | `.env.example` (yeni) |
| 4 | DB bağlantı sızıntısı — 11 fonksiyon context manager'a çevrildi | `data/database.py` |
| 5 | Yinelenen `futures_bakiye()` ağ çağrısı kaldırıldı | `main.py` |

**Doğrulama:** 79 dosya syntax temiz · 30/30 test geçiyor · main.py tam import OK · DB sızıntı testi: 60 işlemde 0 tanıtıcı artışı

---
## 13. KULLANICI İÇİN ACİL AKSİYON LİSTESİ

1. **ŞİMDİ:** Telegram token'ını iptal et → @BotFather → `/revoke` → yeni token al
2. **ŞİMDİ:** Binance API anahtarlarını sil ve yeniden oluştur (para çekme izni KAPALI)
3. **ŞİMDİ:** Yeni `.env` dosyanı oluştur (`cp .env.example .env` + değerleri gir)
4. **BUGÜN:** Panel portunu kısıtla: `ufw allow from SENIN_IP to any port 8080 && ufw deny 8080`
5. **BU HAFTA:** Log rotasyonu kur (bkz. [M-5])
