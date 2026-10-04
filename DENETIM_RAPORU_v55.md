# ASTRA — KAPSAMLI KOD DENETİM RAPORU v55

**Denetim tarihi:** 2026-08-12 | **Sürüm:** v55.0 | **Denetçi rolü:** Staff Engineer / Security Engineer / Software Architect
**Önceki denetim:** DENETIM_RAPORU_v49.md (2026-07-05)

---

## ÖZET

| Metrik | Değer |
|---|---|
| Toplam dosya | 132 |
| İncelenen dosya | 132 (%100) |
| Atlanan dosya | 0 |
| İncelenen Python satırı | ~20.800 |
| **Bulunan sorun** | **58** |
| **Kritik (Critical)** | **8** |
| Yüksek (High) | 16 |
| Orta (Medium) | 21 |
| Düşük (Low) | 13 |

### ⚠️ EN ÖNEMLİ SONUÇ

**v55 changelog'unda "düzeltildi" denen `duplicate_guard` fail-safe davranışı GERÇEKTE DÜZELTİLMEMİŞ.**
Düzeltme bir katman yukarıya yazılmış, ancak alttaki fonksiyon hatayı yutup `False` döndürdüğü için
üstteki fail-closed kodu **ölü kod**. Daha kötüsü: bunu test eden `test_guard_sorgu_hatasinda_engeller`
testi **yanlış katmanı mock'ladığı için geçiyor** ve sahte güven veriyor.

Bu, raporun geri kalanı için de geçerli bir uyarıdır: **testlerin yeşil olması bu kod tabanında
doğruluk kanıtı değildir.**

---

## 1. İNCELENEN DOSYALAR (132/132)

### Kök dizin (6)
`main.py` (2922 satır), `config.py` (259), `requirements.txt`, `baslat.sh`, `testleri_calistir.py`, `.env.example`

### Yapılandırma (2)
`.gitignore`, `.dockerignore`

### core/ (6)
`__init__.py`, `http_guard.py` (59), `teshis.py` (116), `preflight.py` (209), `market_regime.py` (404), `indicators.py` (417)

### data/ (8)
`__init__.py`, `binance_client.py` (540), `binance_futures_client.py` (697), `database.py` (297), `db_manager.py` (436), `market_data.py` (358), `multi_exchange.py` (255), `onchain_data.py` (170)

### engines/ (25)
`__init__.py`, `ab_test.py` (241), `adaptive_sizing.py` (158), `backtest_engine.py` (204), `edge_analytics.py` (177), `event_bus.py` (193), `exchange_failover.py` (137), `futures_trade_engine.py` (355), `kill_switch.py` (232), `model_engine.py` (791), `model_registry.py` (289), `monte_carlo.py` (195), `online_learner.py` (242), `order_engine.py` (252), `order_reconciler.py` (216), `paper_trading.py` (301), `performance_tracker.py` (122), `position_state.py` (273), `risk_manager.py` (474), `shadow_model.py` (147), `strategy_engine.py` (207), `strategy_validator.py` (400), `trade_journal.py` (252), `walk_forward_advanced.py` (158), `watchdog.py` (166), `websocket_manager.py` (203)

### execution/ (8)
`__init__.py`, `duplicate_guard.py` (165), `execution_engine.py` (696), `failsafe_liquidation.py` (153), `fill_reconciler.py` (342), `order_ack.py` (254), `smart_execution.py` (245), `state_audit.py` (307)

### risk/ (3)
`__init__.py`, `correlation_engine.py` (94), `volatility_circuit_breaker.py` (112)

### analytics/ (3)
`__init__.py`, `portfolio_optimizer.py` (223), `risk_analytics.py` (482)

### api/ (2)
`__init__.py`, `dashboard.py` (900)

### monitoring/ (2)
`__init__.py`, `prometheus_metrics.py` (140)

### strategy/ (3)
`__init__.py`, `edge_engine.py` (237), `regime_adapter.py` (197)

### nodes/ (3)
`__init__.py`, `execution_node.py` (200), `signal_node.py` (224)

### simulation/ (3)
`__init__.py`, `exchange_simulator.py` (369), `rl_environment.py` (369)

### bootstrap/ (2)
`__init__.py`, `app_init.py` (100)

### utils/ (2)
`__init__.py`, `exceptions.py` (269)

### models/ (1), saved_models/ (1)
`__init__.py` (ikisi de boş placeholder — dizinler boş, model dosyası yok, doğrulandı)

### tests/ (4)
`__init__.py`, `test_cekirdek.py` (378), `test_execution.py` (702), `test_validator.py` (93)

### docker/ (4)
`Dockerfile`, `docker-compose.yml`, `prometheus.yml`, `watchdog.sh`

### Dokümantasyon (43)
`CHANGELOG.md`, `CHANGELOG_v17` … `CHANGELOG_v48` (v30_1 dahil, 33 dosya), `CHANGELOG_v50` … `CHANGELOG_v55` (6 dosya), `DENETIM_RAPORU_v49.md`, `ENTEGRASYON.md`, `CANLI_GECIS_PROTOKOLU.md`

---

## 2. KRİTİK HATALAR (Severity: Critical)

### [C-1] DuplicateGuard fail-safe'i GERÇEKTE fail-OPEN — v55 düzeltmesi ölü kod ✅DOĞRULANDI

- **Dosya:** `execution/duplicate_guard.py:130-139` (hata), `:99-105` (ölü kod)
- **Sorun:** `_binance_pozisyon_var()` kendi içinde `except Exception` ile hatayı yutup `return False`
  ("pozisyon yok") döndürüyor. Bu yüzden çağıran taraftaki fail-closed bloğu (satır 101-105,
  `pozisyon_var = True`) **hiçbir zaman çalışmaz** — istisna oraya asla ulaşmaz.

```python
# duplicate_guard.py:130-139 — MEVCUT (HATALI)
def _binance_pozisyon_var(self, sembol, yon) -> bool:
    try:
        from data.binance_futures_client import acik_futures_pozisyonlar
        pozlar = acik_futures_pozisyonlar()
        return any(...)
    except Exception as e:
        log.warning(f"[DUPLICATE GUARD] Binance kontrol hatası: {e} — izin verildi")
        return False   # ← FAIL-OPEN! Üstteki fail-closed kodunu ölü bırakıyor
```

- **Etki:** Binance'e erişilemediği anda (ağ kesintisi, timeout, rate-limit) guard "pozisyon yok" der
  ve **işleme İZİN VERİR**. Aynı sembolde ikinci pozisyon açılabilir → **çift teminat, çift risk, gerçek para.**
  v55 changelog'unun "fail-safe: işleme İZİN VERİLMEZ" iddiası gerçekleşmiyor.
- **Yeniden üretim:** `acik_futures_pozisyonlar`'ı `raise ConnectionError` atacak şekilde mock'la,
  `guard.isle("BTCUSDT","LONG")` çağır → `True` (izin) döner, `False` beklenirdi.
- **Test neden yakalamıyor:** `tests/test_execution.py:666-673` (`test_guard_sorgu_hatasinda_engeller`)
  doğrudan `g._binance_pozisyon_var`'ı mock'layıp hata fırlatıyor — yani **hatalı fonksiyonun kendisini
  atlıyor.** Test geçiyor, bug duruyor. Bu testin varlığı aktif olarak zararlı (sahte güven).
- **Çözüm:**
```python
def _binance_pozisyon_var(self, sembol: str, yon: str) -> bool:
    """Binance'ten gerçek pozisyon durumunu sorgular.
    NOT: Hata YAKALAMAZ — fail-closed kararı çağıran katmana aittir."""
    from data.binance_futures_client import acik_futures_pozisyonlar
    pozlar = acik_futures_pozisyonlar()
    return any(p["sembol"] == sembol.upper() and p["yon"] == yon.upper()
               for p in pozlar)
```
  Testi de gerçek zinciri test edecek şekilde düzelt (`acik_futures_pozisyonlar`'ı mock'la,
  `_binance_pozisyon_var`'ı değil).

---

### [C-2] `acik_futures_pozisyonlar()` hata durumunda `[]` dönüyor — "sıfır pozisyon" ile "sorgulayamadım" ayırt edilmiyor

- **Dosya:** `data/binance_futures_client.py:326-343`; en tehlikeli tüketici `execution/fill_reconciler.py:100-195`
- **Sorun:** Fonksiyon `FatalExchangeError | RetryableExchangeError | NetworkError` yakalayıp `[]` dönüyor.
  Tüm çağıranlar bunu "kesinlikle sıfır açık pozisyon var" olarak yorumluyor.
- **Etki (en ağır senaryo):** `fill_reconciler._pozisyon_sync` geçici bir Binance kesintisinde boş liste alır
  → **takip edilen TÜM pozisyonları iç state'te "kapandı" olarak işaretler** ve her biri için
  `POSITION_CLOSED` event'i yayınlar. Pozisyonlar borsada canlı ve kaldıraçlı durmaya devam eder,
  ama bot artık onları izlemiyor: `_sl_tp_dogrula` bu pozisyonları kontrol etmeyi bırakır.
  SL'i düşen/hiç konmamış bir pozisyonu artık **hiçbir şey korumuyor.**
- **Yeniden üretim:** Reconciler döngüsü sırasında ağı kes (5 sn yeterli) → logda tüm pozisyonlar için
  `RECONCILER_SYNC` kapanış kaydı; Binance arayüzünde pozisyonlar hâlâ açık.
- **Çözüm:** "Boş" ile "bilinmiyor"u ayır. En temizi hatayı yükseltmek:
```python
# binance_futures_client.py
def acik_futures_pozisyonlar(sessiz_hata: bool = False):
    try:
        ...
        return [...]
    except (FatalExchangeError, RetryableExchangeError, NetworkError) as e:
        log.error(f"[POZİSYON] Sorgu başarısız: {e}")
        if sessiz_hata:
            return []
        raise            # ← varsayılan: çağıran karar versin
```
  `fill_reconciler._pozisyon_sync` içindeki mevcut `try/except ... return` bloğu böylece
  gerçekten çalışır hale gelir (şu anda ölü kod).

---

### [C-3] `failsafe_liquidation` watchdog thread'i tek bir beklenmedik istisnada kalıcı olarak ölüyor

- **Dosya:** `execution/failsafe_liquidation.py:41-51`
- **Sorun:** Döngü yalnızca `FatalExchangeError`, `RetryableExchangeError`, `NetworkError`,
  `threading.ThreadError` yakalıyor. Genel `except Exception` **yok** — oysa `fill_reconciler._loop`
  ve `state_audit._loop` bunu doğru yapıyor. `_kontrol()` içinde korumasız `poz["sembol"]`,
  `poz["giris"]` dict erişimleri ve `1/kaldirac` bölmesi var (`kaldirac=0` kontrolü yok).
- **Etki:** Tek bir `KeyError` / `ZeroDivisionError` / `TypeError` daemon thread'i sonlandırır.
  Python daemon thread'i yeniden başlatmaz. **Likidasyon koruması sessizce ölür**, bot normal
  çalışmaya devam eder, operatöre hiçbir uyarı gitmez. "Son savunma hattı" için mümkün olan en kötü
  başarısızlık modu: görünmez ve kalıcı.
- **Yeniden üretim:** Binance yanıtında `kaldirac: 0` olan bir pozisyon → `ZeroDivisionError` → thread ölür.
- **Çözüm:**
```python
def _loop(self):
    while self._running:
        try:
            self._kontrol()
        except (FatalExchangeError, RetryableExchangeError) as e:
            log.error(f"[FAILSAFE] Borsa hatası: {e}")
        except NetworkError as e:
            log.warning(f"[FAILSAFE] Ağ hatası: {e}")
        except Exception as e:                              # ← EKLE
            log.critical(f"[FAILSAFE] Beklenmedik hata (thread YAŞIYOR): "
                         f"{type(e).__name__}: {e}", exc_info=True)
        time.sleep(CHECK_INTERVAL)
```
  Ayrıca `state_audit` içinden bir heartbeat kontrolü ekle: `kontrol_sayisi` N dakikadır artmıyorsa alarm ver.

---

### [C-4] Çapraz-borsa fiyat manipülasyonu vetosu her cache isabetinde `AttributeError` ile devre dışı ✅DOĞRULANDI

- **Dosya:** `data/multi_exchange.py:139-140`
- **Sorun:** `cached` bir `FiyatKarsilastirma` **dataclass** örneği (satır 49-63) ama üzerinde
  `.get()` çağrılıyor — dataclass'ın `.get()` metodu yok.

```python
# multi_exchange.py:135-140 — MEVCUT (HATALI)
cached = c["sonuc"]                      # FiyatKarsilastirma dataclass
return self._yeniden_hesapla(sembol, binance_fiyat,
                             cached.bybit, cached.okx,
                             cached.get("bybit_onceki"),   # ← AttributeError
                             cached.get("okx_onceki"))     # ← AttributeError
```

- **Etki:** `MULTIEX_CACHE_TTL` (3 sn) içinde aynı sembol ikinci kez sorgulandığında `AttributeError`.
  `main.py:1467-1482` bunu `except Exception → log.debug` ile yutuyor, dolayısıyla:
  1. Hata normal log seviyesinde **görünmüyor**,
  2. İstisna `try` bloğunu iptal ettiği için `if not mex.guvenilir: ... return` **veto kontrolü hiç çalışmıyor**,
  3. İşlem **çapraz-borsa fiyat doğrulaması olmadan** ilerliyor.
  Modülün tek varlık sebebi olan "Binance fiyatı diğer borsalardan saparsa işlemi engelle" koruması
  fiilen kapalı. Kötü tick / manipüle fiyat üzerinden emir gidebilir.
- **Çözüm:** Doğru değişken cache dict'i (`c`), dataclass değil:
```python
cached = c["sonuc"]
return self._yeniden_hesapla(sembol, binance_fiyat,
                             cached.bybit, cached.okx,
                             c.get("bybit_ham"), c.get("okx_ham"))
```
  Ayrıca `main.py:1467-1482`'deki `log.debug`'ı `log.error` yap — güvenlik kontrolünün çökmesi
  debug seviyesinde saklanmamalı. (Not: `_yeniden_hesapla`'nın `bybit_onceki`/`okx_onceki`
  parametreleri fonksiyon gövdesinde hiç kullanılmıyor — yarım kalmış momentum mantığı; temizlenmeli.)

---

### [C-5] EventBus dispatcher thread'i ölebiliyor + `queue.Full` hiç yakalanmıyor ✅DOĞRULANDI

- **Dosya:** `engines/event_bus.py:7` (import), `:162-165` (publish), `:114-122` ve `:147-151` (dispatch)
- **Sorun A:** `from queue import Queue, Empty` — **`Full` import edilmemiş.** `put_nowait()` kuyruk
  dolduğunda `queue.Full` fırlatır, ama yakalanan tuple `(ValueError, AttributeError, TypeError)`.
  Yani "kuyruk dolu, event atlandı" mesajı asla basılmaz; bunun yerine **yakalanmamış `queue.Full`**
  çağırana kadar yükselir (`risk_manager.py:239,261,338` ve `order_engine.py:202,222` — bazılarında
  try/except yok).
- **Sorun B:** `_dispatch` handler'ları yalnızca `(ValueError, AttributeError, TypeError)` ile sarıyor.
  Bir handler `KeyError` (event payload'ında eksik alan — çok olası), `ZeroDivisionError` veya bir DB
  hatası fırlatırsa istisna `_memory_dispatcher`'a çıkar; oradaki `except` de
  `(ValueError, AttributeError, RuntimeError)` — `KeyError` yok. İstisna döngüden çıkar,
  **daemon dispatcher thread'i sonlanır.**
- **Etki:** Thread öldükten sonra `publish()` çağrıları başarılı görünmeye devam eder (event kuyruğa
  girer) ama **hiçbir event dağıtılmaz.** Kodun kendi yorumuna göre `POSITION_CLOSED` abonesi
  Kelly/performans/kill-switch güncellemesinin **tek noktası.** Yani tek bozuk event ile:
  - `risk_manager.pnl_guncelle()` (Kelly geçmişi, Sharpe, **günlük zarar limiti**) durur
  - `kill_switch.trade_sonucu_bildir()` (ard arda kayıp koruması) durur
  - Bot **normal şekilde işlem açmaya devam eder.**
- **Çözüm:**
```python
from queue import Queue, Empty, Full          # ← Full eklendi
...
try:
    self._queue.put_nowait(msg)
except Full:                                   # ← doğru tip
    log.warning(f"[EVENT_BUS] Queue dolu, event atlandı: {event_type}")
...
# _dispatch ve _memory_dispatcher içinde:
except Exception as e:                         # ← genişlet
    log.error(f"[EVENT_BUS] Handler hatası ({msg.event_type}): {e}", exc_info=True)
```
  Altyapı döngüleri handler bug'ından ölmemelidir — buradaki dar `except` tipleri
  geçmişteki "sessiz except temizliği" sırasında yanlışlıkla daraltılmış görünüyor.

---

### [C-6] `execution_node.py` ilk istisnada `NameError` ile tüm node'u çökertiyor ✅DOĞRULANDI (pyflakes)

- **Dosya:** `nodes/execution_node.py:153` (hata), `:14-17` (eksik import)
- **Sorun:** `except (FatalExchangeError, InsufficientBalanceError) as e:` — `InsufficientBalanceError`
  bu dosyada **import edilmemiş** (`utils/exceptions.py:74`'te tanımlı, ama import bloğunda yok).
  Python bir `except (...)` demetindeki her ismi çözmek zorunda olduğundan, `try` bloğunda **herhangi
  bir** istisna oluştuğunda önce `NameError: name 'InsufficientBalanceError' is not defined` fırlar.
- **Etki:** Bu `NameError` sonraki hiçbir handler tarafından yakalanmıyor ve `execution_node_calistir()`
  (satır 178-196) de çıplak `Exception` yakalamıyor → `while True` döngüsünden çıkar,
  **execution node process'i ölür.** İronik olarak en olası tetikleyici, bu handler'ın zarifçe ele
  alması gereken durumun ta kendisi: yetersiz teminat.
- **Doğrulama:** `python -m pyflakes nodes/execution_node.py` →
  `nodes/execution_node.py:153:33: undefined name 'InsufficientBalanceError'`
- **Çözüm:**
```python
from utils.exceptions import (
    NetworkError, FatalExchangeError, RetryableExchangeError,
    RiskError, ExecutionError, StopLossFailedError, SlippageExceededError,
    InsufficientBalanceError,          # ← EKLE
)
```

---

### [C-7] `CorrelationLimitError` iki kez tanımlanmış — istisna hiyerarşisi sessizce bozuluyor ✅DOĞRULANDI

- **Dosya:** `utils/exceptions.py:150` ve `utils/exceptions.py:243`
```python
# satır 150
class CorrelationLimitError(RiskError): ...
# satır 243 — AYNI İSMİ YENİDEN TANIMLIYOR
class CorrelationLimitError(AstraError): ...
```
- **Sorun:** Python ikinci tanımı kabul eder; modül genelinde geçerli olan sınıf `AstraError`
  alt sınıfıdır, **`RiskError` DEĞİL.**
- **Etki:** Tüm risk ihlallerini tek noktada yakalamak için yazılmış `except RiskError:` blokları
  korelasyon limiti ihlalini **artık yakalamaz.** İstisna yakalanmadan yükselir → risk katmanının
  "işlemi engelle ve devam et" akış kontrolü baypas edilir veya worker thread çöker.
- **Çözüm:** İkinci tanımı (satır 243-245) sil. Regresyon testi ekle:
```python
def test_istisna_hiyerarsisi():
    from utils.exceptions import CorrelationLimitError, RiskError
    assert issubclass(CorrelationLimitError, RiskError)
```

---

### [C-8] `model_engine.py:767` — kaçak `adaylar.append()` ensemble'a `None` model enjekte edebiliyor ✅DOĞRULANDI

- **Dosya:** `engines/model_engine.py:767`
- **Sorun:** Satır 767 `else:` bloğunun içinde ama `with _tft_retrain_lock:` bloğunun **dışında**,
  ve kullandığı `model, acc, meta, prefix` değişkenleri TFT'ye ait değil — satır 675-694'teki
  **klasik model döngüsünden artakalan** değerler (son iterasyon: `gb_egit`).

```python
752	            with _tft_retrain_lock:
753	                if sembol in _tft_retrain_aktif: ...
755	                else:
756	                    _tft_retrain_aktif.add(sembol)
                        ... _thr.Thread(target=_tft_retrain, ...).start()
767	            adaylar.append((model,acc,meta,prefix))   # ← döngü artığı değişkenler
```

- **Etki (iki senaryo):**
  1. `gb_egit` başarılıysa ve zaten satır 694'te eklenmişse → **aynı model `adaylar`'a iki kez girer**,
     `stacking_ensemble_olustur` içinde çift ağırlık alır.
  2. `gb_egit` başarısızsa (`(None, 0, {})` döner, örn. `len(X) < 60`) → **`(None, 0, {}, "gb_...")`
     listeye eklenir.** Bu tek aday ise, satır 769'daki `if not adaylar:` fallback'i baypas edilir
     (liste boş değil) ve satır 789'daki `max(adaylar, key=lambda x: x[1])` **`model=None` döndürebilir**
     → çağıran tarafta `AttributeError: 'NoneType' object has no attribute 'predict'`.
- **Çözüm:** Satır 767'yi **sil.** Klasik modeller döngü içinde (satır 694) zaten doğru şekilde ekleniyor;
  burada yeniden eklenecek bir şey yok.

---

## 3. YÜKSEK ÖNCELİKLİ (Severity: High)

### [H-1] `main.py:518` — Strateji Dayanıklılık Doğrulayıcı hiç çalışmamış ✅DOĞRULANDI (pyflakes)

- **Dosya:** `main.py:518`; ilgili: `main.py:1827` (fonksiyon-içi import)
- **Sorun:** `get_journal(JOURNAL_DB_PATH)` — `JOURNAL_DB_PATH` modül düzeyinde import edilmemiş.
  Tek import `main.py:1827`'de, **`futures_dashboard()` fonksiyonunun içinde** → yerel isim, global olmuyor.
- **Etki:** `_strateji_dayaniklilik_dogrula()` her çağrıda `NameError` alıyor, `except → log.debug`
  ile yutuluyor (normal logda görünmez). Sonuç: `_strateji_onay` **hiç dolmuyor** →
  `main.py:1485-1491`'deki "istatistiksel olarak geçersizlenmiş coin'de yeni pozisyon açma"
  güvenlik kapısı **hiç tetiklenmiyor** (varsayılan: izin ver). `/validate` komutu da her zaman
  "yeterli işlem geçmişi yok" diyor. v24'ten beri ölü bir risk kontrolü.
- **Çözüm:** `JOURNAL_DB_PATH`'i dosya başındaki `from config import (...)` bloğuna taşı.
  Ayrıca validator init hatasını `log.debug` değil `log.error` yap.

### [H-2] `main.py:1076,1077,2472` — TFT tahmin özelliği hiç çalışmıyor ✅DOĞRULANDI (pyflakes)

- **Sorun:** `LOOKBACK` (config.py:88'de tanımlı) `main.py`'a hiç import edilmemiş.
- **Etki:** Her `coin_analiz()` çağrısında `NameError` → `log.debug` ile yutuluyor → v21 TFT tahmini
  hiçbir coin için çalışmıyor. `/tft` komutu ise `❌ TFT hatası: name 'LOOKBACK' is not defined` veriyor.
- **Çözüm:** `LOOKBACK`'i config import bloğuna ekle.

### [H-3] `main.py:2198` — periyodik sistem durumu raporu hiç gönderilmiyor ✅DOĞRULANDI (pyflakes)

- **Sorun:** `rc = reconciler.istatistik` — `reconciler` diye bir global yok; doğru isim
  `order_reconciler` (bkz. `main.py:1759, 2387`).
- **Etki:** Her 30 döngüde bir "⚙️ SİSTEM DURUMU" bloğu `NameError` alıp `log.error`'a düşüyor;
  operatör periyodik execution/reconciler/failsafe sağlık görünürlüğünü kaybediyor.
- **Çözüm:** `rc = order_reconciler.istatistik if order_reconciler else {}`

### [H-4] `risk_manager.py` — paylaşılan sayaçlarda hiç kilit yok

- **Dosya:** `engines/risk_manager.py` (dosya genelinde `threading.Lock` kullanımı **sıfır**)
- **Sorun:** `gunluk_pnl`, `toplam_pnl`, `zirve_bakiye`, `gunluk_islem_sayisi`, `kelly_engine._gecmis`
  birden fazla thread'den mutasyona uğruyor. `kill_switch.py` (v54'te açıkça race fix'lendi) ve
  `position_state.py` kilitli; `risk_manager` aynı muameleyi görmemiş.
- **Etki:** `self.gunluk_pnl += pnl_usdt` atomik değil. İki coin worker'ı aynı anda zararla kapanırsa
  bir güncelleme kaybolabilir → `gunluk_limit_kontrol()` **olduğundan düşük zarar** görür →
  **günlük zarar limiti aşılmasına rağmen işlem devam eder.**
- **Ek TOCTOU:** `tum_kontroller()` çağıranın verdiği `acik_pozisyonlar` anlık görüntüsüne bakıyor.
  İki worker aynı bayat görüntüyle `MAX_OPEN_POSITIONS` kontrolünü geçip birlikte limiti aşabilir;
  emir gönderim anında yeniden doğrulama yok.
- **Çözüm:** `RiskManager`'a `threading.Lock` ekle (kill_switch v54 desenini kopyala) ve
  `OrderEngine._isle()` içinde emir göndermeden hemen önce pozisyon/teminat limitlerini yeniden doğrula.

### [H-5] Chandelier trailing-stop state'i borsa taraflı kapanışlarda temizlenmiyor

- **Dosya:** `engines/futures_trade_engine.py:82-88` (`_pozisyon_state_temizle`), çağrı yalnızca `:122`
- **Sorun:** State temizliği sadece `futures_pozisyon_kapat()` (motor kaynaklı kapanış) içinde çağrılıyor.
  Oysa pozisyonların normal kapanış yolu Binance'in SL/TP/trailing emrini doldurmasıdır; bu
  `position_state.binance_ile_sync()` tarafından asenkron tespit edilir ve o modül
  `_pozisyon_state_temizle`'yi **hiç çağırmaz.**
- **Etki:** BTCUSDT LONG trailing stop 61.000'de dolar → `_chandelier_state["BTCUSDT_LONG"]["stop"]=61000`
  kalır. Kısa süre sonra yeni bir BTCUSDT LONG açılırsa (giriş 60.000),
  `_chandelier_stop_hesapla()` `max(state["stop"], yeni_stop)` yaptığı için **eski işlemin 61.000
  stop'undan başlar** — yeni giriş fiyatının ÜSTÜNDE. İlk `futures_pozisyon_izle()` turunda
  `guncel < chandelier_stop` → **anında yanlış stop-out.** Kodun kendi v23 yorumunun "tehlikeli"
  dediği senaryonun ta kendisi; düzeltme iki kapanış yolundan yalnızca birini kapsıyor.
- **Çözüm:** `Event.POSITION_CLOSED`'a abone ol ve `_pozisyon_state_temizle(sembol, yon)`'u oradan
  çağır — kapanış nasıl olursa olsun tek noktadan temizlensin.

### [H-6] Kapanış PnL'i gerçek fill'den değil, kapanış ÖNCESİ fiyat anlık görüntüsünden hesaplanıyor

- **Dosya:** `engines/futures_trade_engine.py:103-135`
- **Sorun:** `pnl_pct` satır 104'teki `guncel` (emir gönderilmeden ÖNCEKİ fiyat) ile hesaplanıyor.
  Satır 109'da gerçek `exec_fiyat = float(order.get("avgPrice",0))` hesaplanıyor ama
  **hiç kullanılmıyor** (ölü değişken — kasıtsız olduğunun güçlü kanıtı). `pnl_usdt` de
  kapanış öncesi `poz["pnl"]` snapshot'ından geliyor, gerçekleşen PnL'den değil.
- **Etki:** Bu event `risk_manager.pnl_guncelle()`'nin tek beslemesi (Kelly, Sharpe/Sortino ve
  kritik olarak **günlük zarar limiti**). Market emirlerinde slippage nedeniyle gerçek çıkış fiyatı
  farklıdır; zararlar **olduğundan az** kaydedilir — hem de tam olarak slippage'ın büyüdüğü
  volatil koşullarda, yani doğruluğun en çok gerektiği anda.
- **Çözüm:** `pnl_pct`'yi `exec_fiyat` ile hesapla; `pnl_usdt` için
  `(exec_fiyat - poz["giris"]) * miktar * (1 if yon=="LONG" else -1)` kullan.

### [H-7] `backtest_engine.py:130-138` — likidasyon zararı bakiyeden İKİ KEZ düşülüyor ✅DOĞRULANDI

- **Dosya:** `engines/backtest_engine.py:127-140`
- **Sorun:** Girişte teminat zaten düşülüyor (`:123` `bakiye -= (maliyet + giris_kom)`).
  Normal kapanışta doğru şekilde iade ediliyor (`:165` `bakiye += maliyet + pnl`).
  Likidasyonda ise `kayip = pozisyon * giris_fiyat / kaldirac` — **girişteki `maliyet` ile birebir
  aynı formül** — bir kez daha çıkarılıyor.
- **Etki:** Örnek: `bakiye=1000, kaldirac=5`, teminat=200 → giriş sonrası 799,6.
  Likidasyonda `kayip=200` → bakiye 599,6. **200'lük teminat için 400 zarar kaydediliyor.**
  Likidasyon içeren her backtest'te drawdown, win rate, Sharpe ve toplam getiri sistematik olarak
  **iki kat kötümser.** Bu motor strateji seçimini/parametre ayarını beslediği için iyi stratejiler
  reddedilebilir.
- **Çözüm:**
```python
if fiyat <= likit:
    kayip = pozisyon * giris_fiyat / kaldirac   # sadece raporlama için
    islemler.append({"pnl": -kayip, "sebep": "LİKİDASYON"})
    pozisyon = 0; continue                       # bakiye'ye DOKUNMA
```

### [H-8] `preflight._kontrol_binance_baglanti()` asla başarısız olamıyor ✅DOĞRULANDI

- **Dosya:** `core/preflight.py:140-163`
- **Sorun:** Üç dönüş yolunun **üçü de** `gecti=True`; `kritik` hiç set edilmiyor. Binance tamamen
  erişilemezken bile `except` bloğu `True` dönüyor.
- **Etki:** Ağ/DNS/firewall sorunuyla Binance'e hiç erişilemezken preflight yeşil
  "✅ Binance bağlantı: Erişilemedi..." (çelişkili ikon/metin) basıyor ve genel sonuç
  "✅ Tüm kontroller geçti — bot sağlıklı" oluyor. Bot **canlı modda** başlıyor ve derinlerde
  öngörülemez şekilde başarısız oluyor; hızlı ve gürültülü başarısızlık fırsatı kaçırılıyor.
- **Çözüm:**
```python
except Exception as e:
    kritik = LIVE_TRADING          # canlı modda erişilemeyen borsa başlatmayı ENGELLE
    return PreflightSonuc("Binance bağlantı", not kritik,
                          f"Erişilemedi: {type(e).__name__}", kritik=kritik)
```

### [H-9] `preflight` veritabanı bütünlüğünü HİÇ kontrol etmiyor

- **Dosya:** `core/preflight.py:122-137`
- **Sorun:** `_kontrol_dosya_sistemi()` yalnızca `MODEL_DIR`'in yazılabilirliğine bakıyor.
  `DB_PATH`, `JOURNAL_DB_PATH`, `STATE_FILE` veya `data/` dizininin yazılabilirliği için
  **hiçbir kontrol yok** — modül başlığının "kapsamlı sağlık kontrolü" iddiasına rağmen.
- **Etki:** `data/` eksik/yazılamaz durumdayken (örn. hatalı Docker volume mount) bot preflight'ı geçer,
  sonra ilk trade/journal kaydında patlar → **denetim izi kaybı veya işlem ortasında çökme.**
- **Çözüm:** `_kontrol_veritabani()` ekle: `DB_PATH`'i aç, `PRAGMA integrity_check` çalıştır, test yazımı yap.

### [H-10] `order_ack.py` tamamen ölü kod — canlı emir yolunda kullanılmıyor

- **Dosya:** `execution/order_ack.py` (254 satırın tamamı)
- **Sorun:** `OrderAckVerifier` / `order_ack` yalnızca kendi dosyasında ve changelog markdown'larında
  geçiyor; `execution_engine.py` veya `main.py` tarafından **hiç import edilmiyor.** Canlı yol bunun
  yerine `data/binance_futures_client.py:408-437`'deki `fill_verify()`'ı kullanıyor — aynı kavramın
  ayrı, daha basit bir uygulaması (aynı %80 min-fill eşiği, ama `AckDurum` enum'u yok,
  `SLIPPAGE_ASIM`/`kritik_hata` ayrımı yok).
- **Etki:** "Emir gerçekten doldu mu" için iki senkronize olmayan uygulama. Birine yapılan düzeltme
  (örn. `MIN_FILL_PCT` ayarı, slippage işaret hatası) diğerine yansımaz. Kod tabanını inceleyen biri
  daha titiz olan `order_ack.py`'ın canlı işlemleri koruduğunu sanabilir — **korumuyor.**
- **Çözüm:** Ya `OrderAckVerifier`'ı canlı yola bağla ve `fill_verify()`'ı emekliye ayır, ya da
  terk edilmiş bir refactor ise dosyayı sil. Sahte kapsam hissi en kötü seçenek.

### [H-11] Likidasyon fiyatı üç yerde elle hesaplanıyor — Binance'in kendi değeri atılıyor

- **Dosya:** `execution/failsafe_liquidation.py:73-78`, `execution/state_audit.py:114-119`,
  `engines/risk_manager.py:300-341`
- **Sorun:** Üçü de bağımsız olarak `likit = giris * (1 - 1/kaldirac + 0.004)` hesaplıyor.
  Bu basitleştirilmiş yaklaşım, Binance'in notional büyüklüğe göre kademelenen gerçek
  maintenance-margin oranlarını, cross-margin paylaşımını ve gerçekleşmiş PnL düzeltmelerini yok sayıyor.
  Oysa `acik_futures_pozisyonlar()`'ın zaten çağırdığı `/fapi/v3/positionRisk` yanıtında
  **`liquidationPrice` alanı var** — ama `binance_futures_client.py:332-339`'daki dict comprehension
  bu alanı atıyor.
- **Etki:** "Son savunma hattı", var olma sebebi olan hesaplama için borsanın kendi rakamını kullanmıyor.
  Üç ayrı elle yazılmış formül birbirinden ve gerçeklikten sessizce sapabilir → failsafe **çok geç**
  tetiklenebilir (gerçek likidasyon %3/%6 eşiklerinden önce olur) veya **sağlıklı bir pozisyonu
  gereksiz kapatabilir.**
- **Çözüm:** `acik_futures_pozisyonlar()`'a `"likidasyon_fiyat": float(p.get("liquidationPrice", 0))`
  ekle ve üç tüketicide de doğrudan bunu kullan.

### [H-12] `db_manager.py` — SQLite şeması ile `trade_ac`/`trade_kapat` sütunları uyuşmuyor

- **Dosya:** `data/db_manager.py:137-199` (şema) vs `:306-318` (`trade_ac`), `:320-329` (`trade_kapat`)
- **Sorun:** `_init_sqlite_schema()` `trades` tablosunu `giris_fiyat, cikis_fiyat, pnl, pnl_yuzde, ...`
  ile oluşturuyor. Ama `trade_ac()` `(ts_ac, sembol, yon, giris, miktar, kaldirac, strateji)`
  sütunlarına insert ediyor — `giris`, `kaldirac`, `strateji` **SQLite şemasında yok**
  (bunlar Postgres şemasına ait, `:211-218`). `trade_kapat()` de `cikis, pnl_usdt, pnl_pct, sebep`
  güncelliyor — hiçbiri SQLite tablosunda yok.
- **Etki:** `DB_BACKEND` varsayılanı `"sqlite"` (config.py:120) ve psycopg2 yoksa/Postgres
  erişilemezse otomatik SQLite'a düşülüyor. Bu fonksiyonlar tipik bir kurulumda çağrılırsa
  `sqlite3.OperationalError: table trades has no column named giris` fırlatır.
- **Durum:** Şu an **uykuda** — grep ile doğrulandı: `db_manager.trade_ac`/`trade_kapat`'ı hiçbir yer
  çağırmıyor; canlı yol `data/database.py`'ınkileri kullanıyor. Ama modülün kendi docstring'i
  ("Backend-agnostic API") ile doğrudan çelişiyor ve gelecekteki Postgres migrasyonunda
  (tam da bu modülün var olma sebebi) ilk günde patlayacak bir mayın.
- **Çözüm:** CRUD SQL'ini `_init_sqlite_schema()`'nın gerçek sütun adlarıyla hizala; SQLite fallback'ini
  özellikle test eden entegrasyon testi ekle.

### [H-13] `db_manager.py` — her CRUD fonksiyonu yakalaması gereken istisnaları yakalamıyor

- **Dosya:** `data/db_manager.py:303, 317, 328, 346, 361, 376, 392, 401, 408, 418` (10 fonksiyon)
- **Sorun:** Hepsinde `except (OSError, ValueError) as e:` deseni var. Ancak `sqlite3.OperationalError`,
  `sqlite3.IntegrityError`, `sqlite3.ProgrammingError` ve `psycopg2.Error` Python'da **`OSError`
  veya `ValueError` alt sınıfı DEĞİL** — doğrudan `Exception`'dan türerler.
- **Etki:** Savunulmak istenen tam da bu hata sınıfı — kilitli SQLite dosyası, şema uyumsuzluğu (H-12),
  kısıt ihlali, kopan Postgres bağlantısı — **yakalanmıyor.** Fonksiyonların vaat ettiği
  "None/False dön, çökme" sözleşmesi üretimde en çok önemli olan senaryolarda bozuluyor;
  istisna `main.py`'ın canlı döngüsüne (satır 1030, 2137 doğrudan çağrı) yükseliyor.
- **Çözüm:** `except Exception as e:` (bu dış kolaylık katmanında niyet zaten "DB hıçkırığı çağıranı
  çökertmesin") veya en azından `sqlite3.Error` ve `psycopg2.Error`'ı tuple'a ekle.

### [H-14] HTTP 429/418 rate-limit yanıtları hiç sınıflandırılmıyor — özel backoff dalı ölü kod

- **Dosya:** `data/binance_futures_client.py:184-198`; `utils/exceptions.py:205-220` ve `:223-233`
- **Sorun:** `_futures_istek`'in çağırdığı tek sınıflandırıcı `exchange_hata_siniflandir()`
  yalnızca sabit bir `fatal` kod kümesini özel işliyor; Binance'in gerçek rate-limit kodu `-1003`
  ve ham HTTP `429`/`418` durumları `RetryableExchangeError`'a düşüyor. **Hiçbir zaman
  `RateLimitError` dönmüyor.** `429`→`RateLimitError` eşlemesini doğru yapan
  `http_hata_siniflandir()` ise tanımlı ama **hiç çağrılmıyor.**
- **Etki:** `if isinstance(exc, RateLimitError):` dalı (satır ~190) **erişilemez.** Gerçek bir
  rate-limit/IP-ban yanıtı sıradan geçici ağ hatası gibi 3 deneme/~10,5 sn generic backoff alıyor;
  **`Retry-After` başlığı hiç okunmuyor.** Binance'in 418 IP-ban pencereleri dakikalarca sürebilir;
  ban süresine saygı göstermeden yeniden denemek **banı uzatabilir** — çok sembollü bir botta
  tekrarlayan ihlallere dönüşebilir.
- **Çözüm:** `_futures_istek`'te `exchange_hata_siniflandir`'a düşmeden önce
  `r.status_code in (429, 418)` kontrolü yap, `r.headers.get("Retry-After")` değerini oku ve ona uy;
  `-1003`'ü de rate-limit dalına ekle.

### [H-15] `main.py` `bot` modunda trading thread'inin çökme denetimi yok

- **Dosya:** `main.py:2886-2888`
- **Sorun:** `threading.Thread(target=futures_dashboard, daemon=True).start()` — `futures_dashboard()`'ın
  kurulum kodu (satır 1774-1890: `tablolari_olustur()`, `state_manager.binance_ile_sync()`,
  `orphan_sl_tp_temizle()`) koruyucu `while True: try/except`'in (satır 1892) **ÖNCESİNDE** ve büyük
  ölçüde korumasız. Herhangi bir istisna thread'i sessizce öldürür. Yeniden başlatma yok, uyarı yok.
- **Karşılaştırma:** `mod == "live"` (satır 2905-2919) `futures_dashboard()`'ı dış `while True` +
  `try/except` + otomatik yeniden deneme ile sarıyor — `bot` modunda olmayan tam da bu koruma.
- **Etki:** `python main.py bot` (Telegram kontrol botunu da çalıştıran, gerçekçi üretim modu) ile
  başlatıldığında, açılıştaki geçici bir hata **trading döngüsünü, pozisyon izlemeyi ve sinyal
  yürütmeyi kalıcı olarak durdurur** — ama Telegram botu ön planda çalışmaya devam ettiği için
  `/btc`, `/risk` gibi komutlar normal yanıt verir. **Her şey yolundaymış gibi görünür.**
- **Çözüm:**
```python
def _guarded_dashboard():
    while True:
        try:
            futures_dashboard()
        except Exception as e:
            log.critical(f"[ENGINE THREAD] öldü: {e}", exc_info=True)
            try: telegram_gonder(f"🛑 Trading motoru çöktü: {e}", force=True)
            except Exception as te: log.error(f"alarm gönderilemedi: {te}")
        time.sleep(SCAN_INTERVAL)

elif mod == "bot":
    threading.Thread(target=_guarded_dashboard, daemon=True).start()
    telegram_bot_baslat()
```

### [H-16] `docker-compose.yml` — sabit zayıf şifreler + kimlik doğrulamasız Redis host portunda

- **Dosya:** `docker/docker-compose.yml:42, 66, 161` (şifreler), `:61-62, 124-125, 128` (portlar)
- **Sorun:**
  - `DB_PASSWORD=astra2024`, `POSTGRES_PASSWORD=astra2024`, `GF_SECURITY_ADMIN_PASSWORD=astra2024`
    — tahmin edilebilir, paylaşılan, dosyaya gömülü.
  - Postgres `5432:5432` ve Redis `6379:6379` **host arayüzüne** publish edilmiş.
  - Redis komutunda `requirepass` **yok** → tamamen kimlik doğrulamasız.
- **Etki:** Bu compose dosyası host firewall'ı olmayan bir VPS'te deploy edilirse (çok yaygın ihmal),
  6379 açık Redis fırsatçı taramaların bilinen hedefi (config tabanlı RCE, cron injection,
  cryptomining payload); 5432 tahmin edilebilir şifreyle doğrudan DB ele geçirme vektörü
  (işlem geçmişi + journal verisi).
- **Çözüm:** Şifreleri `env_file`/Docker secrets'a taşı (compose'da varsayılan bırakma);
  `redis`/`timescaledb` host port publish'ini kaldır (yalnızca internal compose ağı) veya
  `127.0.0.1:5432:5432` yap; Redis'e `--requirepass ${REDIS_PASSWORD}` ekle.

---

## 4. ORTA ÖNCELİKLİ (Severity: Medium)

### [M-1] `.env.example:49` — dağıtılan şablonda `LIVE_TRADING=true`
`config.py:71` kod düzeyinde doğru şekilde `false` varsayıyor ve bu test ediliyor
(`test_live_trading_varsayilan_kapali`). Ancak yeni operatörün kopyaladığı dosya
(`cp .env.example .env`, dosyanın kendi başlığındaki talimat) **canlı işlem açık** geliyor.
API anahtarlarını doldurup bu satırı atlayan biri açık bir onay adımı olmadan gerçek parayla başlar.
**Çözüm:** `.env.example`'da `LIVE_TRADING=false` yap.

### [M-2] Dashboard varsayılan olarak kimlik doğrulamasız ve `0.0.0.0`'a bağlanıyor ✅DOĞRULANDI
`api/dashboard.py:840` — `if not PANEL_USER: return True`. `PANEL_USER`/`PANEL_PASS` varsayılanı
boş (`.env.example:131-132`), sunucu yine de `HTTPServer(("0.0.0.0", DASHBOARD_PORT))` (satır 892,
varsayılan 8080). Auth mekanizmasının kendisi doğru yazılmış (`hmac.compare_digest` ile timing-safe,
`do_GET`'in ilk satırında hem `/api/state` hem HTML için uygulanıyor — korumasız endpoint yok),
ama **varsayılan fail-open** ve çalışma anında hiçbir uyarı loglanmıyor.
`.env.example`'da Türkçe uyarı var, fakat okumayan operatör canlı bakiye, açık pozisyon, PnL ve
strateji verisini porta erişebilen herkese açıyor.
**Çözüm:** Başlangıçta `log.critical("PANEL_USER/PANEL_PASS ayarlı değil — panel KİMLİK
DOĞRULAMASIZ 0.0.0.0:8080'de")` bas; `PANEL_USER` yoksa varsayılan olarak `127.0.0.1`'e bağlan.

### [M-3] `PANEL_PASS` boşken herhangi bir boş şifre kabul ediliyor
`api/dashboard.py:851-852` — Operatör `PANEL_USER` set edip `PANEL_PASS`'i unutursa,
`Authorization: Basic base64(user:)` gönderen herkes doğrulanır.
**Çözüm:** Başlangıçta biri dolu diğeri boşsa başlatmayı reddet.

### [M-4] Prometheus metrikleri kimlik doğrulamasız, tüm arayüzlerde
`monitoring/prometheus_metrics.py:120-126` — `start_http_server(PROMETHEUS_PORT)`
`prometheus_client`'ın varsayılan `0.0.0.0` bağlanmasını kullanıyor;
`astra_futures_balance_usdt`, `astra_daily_pnl_usdt`, `astra_drawdown_pct`, `astra_var_usdt`
metriklerini **hiç auth olmadan** yayınlıyor (dashboard'un aksine opsiyonel Basic Auth bile yok).
`PROMETHEUS_ENABLED` varsayılanı `false` olduğu için hafifletilmiş, ama Grafana bağlamak için
açan operatör 9090'ı firewall'lamazsa hesap finansalları herkese okunur olur.
**Çözüm:** Varsayılan `127.0.0.1` bağlanma ve/veya bu portun mutlaka firewall'lanması gerektiğini belgele.

### [M-5] `order_engine.py` — SL yerleştirme başarısızlığı yeniden denenmiyor
`engines/order_engine.py:44-45` (`MAX_RETRY=3`, `RETRY_DELAY=1.5` tanımlı ama **hiç kullanılmıyor**),
`:171-177`. SL konamazsa sadece log + alert, sonra **TP denemeye devam ediyor** ve dönüyor —
canlı, korumasız (stop-loss'suz) gerçek para pozisyonu bırakarak. Bir sonraki periyodik
`sl_tp_dogrula()` taraması (varsayılan 300 sn) fark edene kadar çıplak kalıyor.
**Çözüm:** Zaten tanımlı `MAX_RETRY`/`RETRY_DELAY` ile anında sınırlı yeniden deneme uygula;
tekrarlı başarısızlıkta pozisyonu kapat.

### [M-6] `position_state.sl_tp_dogrula()` `TRAILING_STOP_MARKET`'i geçerli SL saymıyor
`engines/position_state.py:220-228` — Yalnızca `("STOP_MARKET","STOP")` tiplerine bakıyor.
Chandelier mantığı tetiklendiğinde `futures_trailing_stop_koy` ile `TRAILING_STOP_MARKET` konuyor.
Doğrulayıcı bunu "SL eksik" sanıp **pozisyon açılışındaki bayat `poz["sl"]` fiyatına statik SL
yeniden koyuyor.** En iyi ihtimalle gereksiz/kafa karıştırıcı çift emir; en kötüsünde aktif trailing
stop'tan daha kötü bir seviyede statik SL. Operatöre de yanlış "SL kayıptı" alarmı gidiyor.
**Çözüm:** `"TRAILING_STOP_MARKET"`'i tip listesine ekle; chandelier stop'u değiştirdiğinde
`_state[sembol]["sl"]`'i güncelle.

### [M-7] `futures_trade_engine.py:184-217` — teminat kontrolü emrin gerçek değerleriyle yapılmıyor
Satır 186'daki `marjin_kontrol` **statik** `FUTURES_LEVERAGE` ve **geçici** `sonuc["trade_usdt"]`
ile hesaplanıyor. Birkaç satır sonra gönderilen emir ise `dinamik_kaldirac_hesapla()`
(drawdown/negatif Sharpe döneminde kaldıracı **düşüren**) ve Kelly türevli `usdt` kullanıyor.
Gerekli teminat = notional/kaldıraç olduğundan, gerçek kaldıraç varsayılandan düşükse
işlem kontrol edilenden **daha fazla teminat** tüketir — `MAX_MARGIN_PCT` kontrolü geçerken
gerçek emir sınırı aşabilir; hem de dinamik kaldıraç sisteminin korumak için var olduğu
volatil/drawdown koşullarında.
**Çözüm:** Önce `kaldirac` ve nihai `usdt`'yi hesapla, sonra `tum_kontroller`/`marjin_kontrol`'ü
bu nihai değerlerle `submit()` hemen öncesinde çalıştır.

### [M-8] `order_reconciler.py` — TP kaybı hiç onarılmıyor
Docstring (satır 19-23) "TP kaybı"nı bu modülün çözdüğü sorunlar arasında sayıyor ve
`_istatistik["tp_onarim"]` sayacı mevcut, ancak `sync_open_orders()` (satır 125-169) yalnızca
eksik `STOP_MARKET`/`STOP` (SL) arıyor; `TAKE_PROFIT*` tiplerine **hiç bakmıyor** ve
`tp_onarim` dosyada **hiçbir yerde artırılmıyor.** TP emrini kaybeden pozisyon sonsuza dek
take-profit'siz çalışır; rapor `tp_onarim: 0` göstererek "sorun yok" izlenimi verir —
oysa gerçek anlamı "uygulanmadı".
**Çözüm:** SL bloğunu aynalayan bir `tp_tipler = {"TAKE_PROFIT_MARKET","TAKE_PROFIT"}` kontrolü ekle.

### [M-9] `performance_tracker.py:37-54` — sinyal doğruluğu TERS yönde hesaplanıyor
`son_sinyaller()` (`data/database.py:236-244`) `ORDER BY id DESC` (en yeni önce) dönüyor.
Dolayısıyla `sinyaller[i+1]` — kodda `s_sonra` ("sonraki") diye adlandırılan — aslında
**kronolojik olarak ÖNCEKİ** sinyal. Doğruluk kontrolü, her sinyalin tahminini **o sinyalden
önce çoktan gerçekleşmiş** fiyat hareketiyle karşılaştırıyor — öngörü doğruluğu ölçümünün tam tersi.
Yürütmeyi etkilemiyor (yalnızca `/tam_rapor`), ama modelin gerçekten öngörücü olup olmadığı
konusunda kullanıcıyı sistematik olarak yanıltıyor — ki bu da shadow-model onayı gibi kararları besliyor.
**Çözüm:** Eşleştirmeden önce `sinyaller = list(reversed(sinyaller))`.

### [M-10] Üç farklı pozisyon boyutlandırma algoritması; canlı yolda sessiz %15 fallback
`strategy/strategy_engine.py:207` düz `bakiye * 0.15` dönüyor (kaldıraç/güven/volatilite/kayıp
serisi farkındalığı yok). `main.py:1567` ve `futures_trade_engine.py:214-217` bunu
`risk_manager.pozisyon_buyuklugu_hesapla()` ile eziyor — **ancak `_risk_manager` falsy ise
ezilmiyor.** O durumda canlı emir, risk_manager'ın tüm korumaları olmadan bakiyenin düz %15'iyle
boyutlanır. Ayrıca `paper_trading.py:91` **üçüncü** bir motoru (`AdaptiveSizing`) kullanıyor —
yani paper sonuçları canlının gerçekte yapacağını temsil etmiyor.
**Çözüm:** `AdaptiveSizing`'i canlı yola da bağla veya `strategy_engine.karar_ver`'in ölü `usdt`
alanını kaldır; fallback'i fail-closed yap (işlemi atla).

### [M-11] `risk_manager.py:412` — sabit 5.0 USDT tabanı dampening'i eziyor
`if dd >= DRAWDOWN_REDUCE_THRESHOLD*1.5: damp=0.3`, `if sharpe < -0.5: damp*=0.7` →
en kötü koşulda `damp=0.21`. Ancak `return max(round(usdt,2), 5.0)` — damping sonrası 5.0'ın altına
düşen boyut yeniden 5.0'a çekiliyor. Yani **dampening'in korumak için var olduğu tam koşullarda**
pozisyon risk modelinin hesapladığından büyük olabiliyor.
**Çözüm:** Damped boyut borsa minimumunun altındaysa işlemi tamamen atla (fonksiyonun negatif Kelly
için zaten yaptığı `return 0.0` gibi).

### [M-12] `websocket_manager.py:71-74` — kill-switch WS bildirimi tamamen sessiz `except`'te
`get_kill_switch().ws_disconnect_bildir()` çağrısı `except Exception: pass` ile sarılı,
**hiçbir loglama yok.** Bu çağrı başarısız olursa (geçici circular import, ilk çağrıda config hatası)
WS-disconnect kill-switch koruması sıfır teşhis iziyle sessizce devre dışı kalır.
**Çözüm:** En azından `except Exception as e: log.error(f"[WS] kill switch bildirim hatası: {e}")`.

### [M-13] `websocket_manager.ws_baslat()` — "zaten çalışıyor" durumunda callback sessizce değişiyor
Satır 139'daki `_disconnect_cb = disconnect_callback` koşulsuz; satır 148-150'deki
"zaten çalışıyor → return" kontrolünden **önce**. İkinci bir çağrı farklı (veya `None`) callback
geçerse, çalışan bağlantının disconnect/reconnect kablolaması sessizce değişir/silinir.
**Çözüm:** Atamayı erken-return guard'ının altına taşı.

### [M-14] `execution_engine.py:404-410, 455-461` — en kritik iki alarmda sessiz `except Exception: pass`
"Hayalet pozisyon" ve "kapatılamayan SL'siz pozisyon" — motorun üretebileceği en kötü iki sonuç.
`self._bus.publish` kendisi hata verirse operatörün tek bildirimi önceki `log.critical` satırı olur.
`state_audit` ve `fill_reconciler`'ın periyodik kontrolleri sonunda yakalar, ama kod tabanındaki
en yüksek önem dereceli alarmda kaçınılabilir sessiz bir pencere var.
**Çözüm:** `except Exception as be: log.critical(f"Alarm yayınlanamadı: {be}")`.

### [M-15] İki bağımsız, tutarsız korelasyon kontrolü
`execution_engine.py:212` → `RiskManager.korrelasyon_kontrol` (basit aynı-yön sayacı);
`main.py:1493-1497` → `CorrelationEngine.pozisyon_acilabilir_mi` (MAJORS/ALTCOINS ayrımlı).
İkisi de çalışıyor (savunma derinliği), ama birbirinden farklı karar verebilirler ve biri
diğeri güncellenmeden değiştirilirse sessiz koruma boşluğu oluşur. Ayrıca `korrelasyon_kontrol`
`acik_futures_pozisyonlar()` beslemesi nedeniyle **[C-2]'deki fail-open sorununu miras alıyor.**
**Çözüm:** Tek korelasyon otoritesine (`CorrelationEngine`) indir.

### [M-16] `model_engine.py:692` — eğitim çağrıları korumasız, tek hata tüm sembolü iptal ediyor
`model,acc,meta=egitim_fn()` etrafında try/except yok. `gb_egit`/`lgb_egit` iç istisna yönetimine
sahip değil; `xgb_egit`'in calibration except'i (`(ValueError, TypeError)`) `rf_egit`'inkinden
(`Exception`) dar. Tuple dışı bir istisna (örn. `CalibratedClassifierCV`'den `RuntimeError`)
`en_iyi_model_yukle_veya_egit()`'i o sembol için tamamen iptal eder — zaten eğitilmiş modellere
graceful fallback olmadan.
**Çözüm:** Satır 692'yi `try/except Exception` ile sar.

### [M-17] Kilitsiz singleton getter'ları (5 modül)
`event_bus.get_bus()`, `kill_switch.get_kill_switch()`, `position_state.get_state_manager()`,
`order_engine.get_order_engine()`, `model_registry.get_model_registry()` — hepsi kilitsiz
`if _instance is None: _instance = ...` deseni. İki thread ilk çağrıyı eşzamanlı yaparsa iki ayrı
örnek oluşabilir; `OrderEngine(otomatik_baslat=True)` gibi arka plan thread'i başlatan durumlarda
**öksüz thread kendi kuyruğuyla çalışmaya devam eder.**
**Çözüm:** Getter'ları `threading.Lock` ile koru veya worker thread'ler doğmadan önce
tek-thread'li başlangıç fazında hepsini initialize et.

### [M-18] `paper_trading.py:216-239` — kill-switch/adaptive-sizing geri bildiriminde olası çift sayım
`futures_trade_engine.py:110-112`'nin kendi yorumu, PnL/Kelly güncellemesinin kapanış noktasında
**kasıtlı olarak yapılmadığını**, merkezi `POSITION_CLOSED` abonesinin tek noktadan hallettiğini,
"aksi halde PnL çift sayılırdı" diyor. `paper_trading.py` ise hem aynı event'i yayınlıyor
**hem de** doğrudan `kill_switch.trade_sonucu_bildir()` / `adaptive_sizing.sonuc_bildir()` çağırıyor.
`main.py`'ın abonesi kaynağa göre filtrelemiyorsa, paper modda kill switch sayaçları **iki kat**
artar — yani paper modda kill switch, futures motorunun tasarımının varsaydığından yaklaşık
iki kat hassas olur.
**Çözüm:** `main.py`'ın `POSITION_CLOSED` handler'ının mod filtresi olup olmadığını doğrula;
yoksa `paper_trading.py`'daki doğrudan çağrıları kaldır.

### [M-19] `risk_analytics.py:134` — hot path'te global `np.random.seed(42)`
`var_hesapla()` içinde (sembol başına, potansiyel olarak her analiz turunda çağrılıyor)
NumPy'ın **global** legacy RNG'si yeniden tohumlanıyor. İki sorun: (1) Monte Carlo VaR bacağı
fiilen deterministik hale geliyor, üç yöntemi birleştirmenin çeşitlendirme değeri azalıyor;
(2) aynı process'teki **başka her kod** için RNG state'i sessizce sıfırlanıyor (backtest, simülasyon),
çağrı sırasına bağlı ince yanlılık/tekrarlanamazlık doğuruyor.
**Çözüm:** Global state'i değiştirmek yerine fonksiyona özel `np.random.default_rng(42)` kullan.

### [M-20] HTTP `Session` yeniden kullanımı yok — her çağrı yeni TCP+TLS el sıkışması
`binance_client.py`, `binance_futures_client.py`, `market_data.py`, `multi_exchange.py`,
`onchain_data.py` — hepsi modül düzeyi `requests.get/post/delete` kullanıyor, paylaşılan
`requests.Session()` yok. Sızıntı değil ama gerçek gecikme maliyeti; en görünür yeri
`binance_futures_client.py:408-437`'deki `fill_verify()` sıkı polling döngüsü —
tam da eklenen gecikmenin **doğrudan slippage'a dönüştüğü** an.
**Çözüm:** `HTTPAdapter` + connection pooling ile paylaşılan modül düzeyi `Session`.

### [M-21] `core/http_guard.py` — global timeout yaması yalnızca `requests`'i kapsıyor
Yama (satır 32-50) `requests.Session.request` ve `requests.api.request`'i sarıyor. Kapsamadıkları:
- **WebSocket** bağlantıları (`websocket-client`) — takılan bir WS okuması tamamen farklı bir
  başarısızlık modu ve bu yama tarafından hiç dokunulmuyor.
- **`python-telegram-bot>=20.0`** — v20+ dahili olarak `httpx` kullanıyor, `requests` değil.
  Yani **Telegram çağrıları korunmuyor.**
- `global_timeout_uygula()` çalışmadan **önce** bound method referansı yakalayan kodlar.
**Çözüm:** Modül başlığında yamanın gerçek kapsamını (yalnızca requests) belgele; WS
connect/recv'e açık timeout ekle; `global_timeout_uygula()`'nın herhangi bir HTTP isteğinden
önce çağrıldığını başlangıçta doğrula.

---

## 5. DÜŞÜK ÖNCELİKLİ (Severity: Low)

| # | Dosya:Satır | Sorun |
|---|---|---|
| L-1 | `utils/exceptions.py:24-30` | Özel `TimeoutError`/`ConnectionError` Python builtin'lerini gölgeliyor. `except ConnectionError:` yazan kod, `socket`/`requests`'in fırlattığı gerçek istisnaları yakalamaz. `AstraTimeoutError`/`AstraConnectionError` olarak yeniden adlandır. |
| L-2 | `utils/exceptions.py:52-61` vs `:205-220` | `FATAL_CODES` iki yerde bağımsız tanımlı (biri hiç kullanılmıyor). Şu an eşleşiyorlar ama senkron kalmalarını sağlayan bir şey yok → gelecekte retryable/fatal yanlış sınıflandırması. |
| L-3 | `api/dashboard.py:46-88` | `_db_gecmisini_yukle()` ham `sqlite3.connect()` açıyor, `try/finally` yok. `conn.close()` (satır 64) yalnızca öncesindeki her şey başarılıysa çalışır. Yalnızca başlangıçta bir kez çalıştığı için etki dar. Ayrıca `config.DB_PATH` yerine `os.environ.get("DB_PATH", ...)` okuyor. |
| L-4 | `api/dashboard.py:561-822` | JS `innerHTML` şablonlarına `sembol`/`karar`/`rejim`/`sebep` HTML-escape edilmeden yazılıyor. Şu an bu değerler yalnızca botun kendi sabit sembol listesinden geldiği için sömürülebilir değil; savunma derinliği için `esc()` yardımcısı önerilir. |
| L-5 | `data/binance_client.py` | Spot emir fonksiyonları (`market_al`, `market_sat`, `emir_iptal`) futures client'taki idempotency (`newClientOrderId`), retry ve fill-verify korumalarına sahip değil. Şu an **hiç çağrılmıyor** (ölü kod), ama ileride bağlanırsa v53'te bilinçli düzeltilen çift-emir riskini geri getirir. |
| L-6 | `core/indicators.py:113-129` | `hesapla_supertrend` — `direction.iloc[0]` hiç set edilmiyor, döngü `i=1`'den başlıyor. İlk bar "bantlar arası" durumdaysa geçersiz `0` yönü yayılabilir. `direction.iloc[0] = 1` ile başlat. |
| L-7 | `core/indicators.py:139-154` | `mumlar_hesapla` Doji kontrolü tamamen düz mumu (`O==H==L==C`) kaçırıyor: `Candle_Range=0` → `0 < 0` = `False`. |
| L-8 | `core/market_regime.py:104-111` | `chikou = close.shift(-26)` — grafik çizimi için standart, ama model özelliği olarak kullanılırsa **doğrudan look-ahead bias** (`chikou.iloc[i] == close.iloc[i+26]`). Tüketici kodu kapsam dışıydı; doğrulanmalı. |
| L-9 | `engines/backtest_engine.py:79` | `atr = tr.rolling(14).mean().fillna(tr.mean())` — `tr.mean()` **tüm seri** üzerinden; ilk ~13 bar geleceğe ait veriyle dolduruluyor (sınırlı ama gerçek leakage). |
| L-10 | `engines/backtest_engine.py:186` | Sharpe **işlem başına** PnL'i sanki her işlem bir gün gibi `sqrt(252)` ile yıllıklandırıyor — genelde şişiriyor; `overfitting_skoru`/strateji karşılaştırmasını besliyor. |
| L-11 | `engines/watchdog.py:128` | `son.filename.split('/')[-1]` POSIX yolu varsayıyor; Windows'ta tam yol basılıyor (kozmetik). |
| L-12 | `docker/watchdog.sh:14` | `logs/watchdog.log` hiç rotate edilmiyor (`baslat.sh` astra.log için 50MB×5 rotasyon yapıyor). 7/24 çalışmada sınırsız büyür. |
| L-13 | `.env.example:57-58, 66-67` | `WATCHDOG_MAX_SILENT` ve `WATCHDOG_INTERVAL` iki kez tanımlı (zararsız, kafa karıştırıcı). |

**Ek düşük öncelikli notlar:**
- `simulation/exchange_simulator.py` — `emir_sim()` (gerçekçi gecikme/slippage/kısmi dolum simülatörü)
  kod tabanında **hiç çağrılmıyor**; `main.py` yalnızca `senaryo_testi()` kullanıyor. Paper işlemleri
  `paper_trading.py`'ın kendi mantığından geçiyor → modülün docstring'inin vaat ettiği "gerçekçi paper
  execution" katmanı bağlı değil.
- `model_engine.py`, `online_learner.py`, `shadow_model.py`, `model_registry.py` — `pickle.load()`
  kullanıyor. Dosyaları botun kendisi yazdığı için somut saldırı yolu yok; yine de
  `model_registry.rollback_yap()` geçmiş bir `.pkl`'i bütünlük doğrulaması olmadan canlıya kopyalıyor.
- `model_engine.py:117-129` — Windows'ta `os.replace()`, başka bir thread dosyayı açık tutuyorsa
  `PermissionError` (WinError 32) verebilir; geniş `except` bunu yutar ve **yeni eğitilmiş model
  sessizce kaybolur** (eski model bozulmaz, "bayat model"e degrade olur).
- `position_state.py:249` — `time.sleep(ORPHAN_CHECK_INTERVAL - STATE_SYNC_INTERVAL)`; yanlış
  yapılandırmada negatif → `ValueError` → dış `except` → **gecikmesiz sıkı yeniden deneme döngüsü**
  (Binance API'yi döver). `max(0, ...)` guard'ı ekle.
- `websocket_manager.py:177` — `attempt = 0` `run_forever()` normal döndüğünde koşulsuz sıfırlanıyor;
  bu disconnect'te tipik çıkış yolu olduğundan `RECONNECT_BKFF=[5,10,30,60]` kademeli backoff'u
  pratikte devreye girmiyor — uzun kesintide ~5 sn'de bir yeniden deneme.
- `execution/duplicate_guard.py:37-46` — `_islem_altinda`/`_tamamlanan` yalnızca bellekte;
  process yeniden başlarken sıfırlanıyor. [C-1]/[C-2] ile birleşince, açık pozisyon varken yapılan
  bir restart sonrası ilk turda koruma beklenenden zayıf.
- `execution/fill_reconciler.py:152-155` — `self._state._lock` / `self._state._state` private
  attribute'larına doğrudan erişiyor (encapsulation ihlali, refactor kırılganlığı).
- `analytics/portfolio_optimizer.py:31-32` — `_MIN_AGIRLIK=0.05` + `sum(w)=1` yalnızca ~20 sembole
  kadar uygulanabilir; üstünde optimizasyon yakınsamaz (Risk Parity'ye graceful fallback var, ama
  örtük tavan belgelenmemiş).
- `execution/execution_engine.py:109` — `pozisyon_var_mi, duplicate_kontrol` import edilmiş ama
  bu dosyada hiç çağrılmıyor (gerçek çağrı `binance_futures_client.futures_market_ac` içinde).
- `main.py` — ~18 kullanılmayan import, `main.py:1699`'da hiç kullanılmayan `bakiye = futures_bakiye()`
  (boşa ağ çağrısı), `main.py:1592,1594,2578,2621,2626,2629`'da placeholder'sız f-string'ler,
  `main.py:149,1529`'da her zaman doğru olan `if _strategy_engine:` kontrolü.

---

## 6. GÜVENLİK DENETİMİ (OWASP Top 10 odaklı)

| Kontrol | Sonuç | Not |
|---|---|---|
| **A01 — Bozuk Erişim Kontrolü** | ⚠️ **AÇIK** | Dashboard varsayılan fail-open + `0.0.0.0` [M-2]; boş `PANEL_PASS` bypass [M-3]; Prometheus tamamen auth'suz [M-4] |
| **A02 — Kriptografik Hatalar** | ✅ TEMİZ | HMAC-SHA256 imza üretimi doğru sırada (timestamp/recvWindow önce, signature sona); `hmac.compare_digest` ile timing-safe panel karşılaştırması |
| **A03 — Injection (SQL)** | ✅ **TEMİZ** | `database.py` ve `db_manager.py`'daki **her** sorgu `?`/`%s` parametreli; hiçbir yerde değişken içeren f-string/format ile SQL kurulmuyor |
| **A03 — Injection (XSS)** | 🟡 DÜŞÜK | Dashboard JS `innerHTML`'e escape'siz yazıyor ama tüm değerler botun kendi sabit listesinden [L-4] |
| **A03 — Injection (Command)** | ✅ TEMİZ | `baslat.sh`/`watchdog.sh`'de shell injection veya tırnaksız değişken yok |
| **A04 — Güvensiz Tasarım** | ⚠️ **AÇIK** | Fail-open deseni sistemik: [C-1] duplicate guard, [C-2] pozisyon sorgusu, [H-8] preflight. `marjin_kontrol`'ün fail-closed olması (risk_manager:279-298) ekibin doğru deseni bildiğini gösteriyor — tutarlı uygulanmamış |
| **A05 — Güvenlik Yanlış Yapılandırması** | ⚠️ **AÇIK** | `docker-compose.yml` sabit `astra2024` şifreleri, auth'suz Redis 6379 host'ta, Postgres 5432 host'ta [H-16]; kaynak limiti yok; `.env.example` `LIVE_TRADING=true` [M-1] |
| **A06 — Güvenlik Açıklı Bileşenler** | 🟡 ORTA | `requirements.txt` üst sınırsız `>=` kullanıyor; `python:3.11-slim` digest ile pinlenmemiş (tedarik zinciri tekrarlanabilirliği) |
| **A07 — Kimlik Doğrulama Hataları** | ⚠️ AÇIK | Telegram tarafı **TEMİZ** (`_yetkili_komut` dekoratörü tüm komutlara kayıt anında uygulanıyor); panel tarafı [M-2]/[M-3] |
| **A08 — Yazılım/Veri Bütünlüğü** | 🟡 ORTA | `pickle.load()` model dosyalarında (bot'un kendi yazdığı dosyalar, somut saldırı yolu yok); `model_registry.rollback_yap()` bütünlük doğrulaması olmadan geçmiş `.pkl` kopyalıyor |
| **A09 — Loglama/İzleme Hataları** | ⚠️ **AÇIK** | **En ciddi mimari zayıflık.** 33 sessiz `except: pass`; güvenlik kontrollerinin çöküşü `log.debug`'da saklanıyor ([C-4], [H-1], [H-2]); [C-3]/[C-5]'te koruma thread'leri **sessizce ölebiliyor** |
| **A10 — SSRF** | ✅ TEMİZ | Tüm giden URL'ler sabit borsa/API host'ları (Binance, Bybit, OKX, CoinGecko, Glassnode, alternative.me); kullanıcı/sinyal türevli URL yok |
| **Path Traversal** | ✅ TEMİZ | Kullanıcı girdisinden dosya yolu oluşturulmuyor |
| **CSRF** | ✅ UYGULANAMAZ | Durum değiştiren HTTP endpoint yok (yalnızca GET) |
| **CORS** | ✅ TEMİZ | `PANEL_CORS_ORIGIN` boşken hiç `Access-Control-Allow-Origin` başlığı gönderilmiyor — güvenli varsayılan doğru uygulanmış |
| **Secret sızıntısı (repo)** | ✅ **TEMİZ** | **`.env` dosyası mevcut DEĞİL** (doğrulandı: `ls .env` → yok). Ağaçta `.env`, `*.key`, `*.pem`, `credentials.json`, `.db`, `.pkl` yok. `.gitignore`/`.dockerignore` doğru kapsıyor (`.env.example` açıkça un-ignore edilmiş). v49'un C-1 bulgusu **gerçekten kapatılmış** |
| **Secret sızıntısı (log)** | ✅ TEMİZ | httpx/telegram logları WARNING'e çekilmiş; kodda gömülü anahtar yok, hepsi `os.getenv` |
| **Container güvenliği** | ✅ İYİ | `Dockerfile` non-root `USER astra` (uid 1000), slim base, `.env` kopyalamıyor |

---

## 7. PERFORMANS DENETİMİ

### İyi durumda
- Klines TTL önbelleği + `exchange_info` önbelleği mevcut
- Sayısal kararlılık: `core/indicators.py` ve `core/market_regime.py`'de bölme koruması
  (`.replace(0, 1e-10)`) **sistematik olarak** uygulanmış (RSI, Stoch RSI, Williams %R, CCI,
  Bollinger, VWAP, ATR/ADX, chop index) — bilinçli bir sağlamlaştırma turu olduğu belli
- Bellek: `event_bus._history` 500 ile sınırlı; deque maxlen / `[-N:]` disiplini genel olarak korunmuş
- `newClientOrderId` idempotency'si (v53) doğru uygulanmış ve test edilmiş — timeout→retry→çift pozisyon
  senaryosuna karşı gerçek bir savunma

### Bulgular
| # | Sorun | Etki |
|---|---|---|
| P-1 | v49'da düzeltilen **yinelenen `futures_bakiye()` regresyona uğramış** — `main.py:1133&1137` (`coin_analiz`, coin başına her turda) ve `main.py:1530&1565` (`_execution_isle`) | N coin için tur başına en az N fazla REST çağrısı; `futures_bakiye()` cache'siz. Rate-limit bütçesini tüketiyor → SL kontrolü gibi kritik çağrıları geciktirebilir |
| P-2 | `main.py:1699` — `bakiye = futures_bakiye()` hesaplanıyor, **hiç kullanılmıyor** | Her `/analytics` çağrısında ve 24 turda bir tamamen boşa ağ round-trip'i |
| P-3 | HTTP `Session` yeniden kullanımı yok [M-20] | Her çağrıda yeni TCP+TLS; `fill_verify()` polling döngüsünde doğrudan slippage'a dönüşüyor |
| P-4 | `main.py:1856` — `heartbeat_loop` thread'i `futures_dashboard()` her yeniden başladığında yeniden spawn ediliyor | `live` modda crash/restart döngüsünde **thread sızıntısı**; her biri kalıcı `while True`, 300 sn'de bir log + `bus.publish`. Aylarca çalışmada birikir |
| P-5 | `websocket_manager.py:177` | Kademeli backoff pratikte devreye girmiyor; uzun kesintide ~5 sn'de bir yeniden bağlanma denemesi |
| P-6 | İki eşzamanlı SQLite erişim deseni aynı dosyaya [L-3 ilgili] | `database.py` çağrı başına yeni bağlantı (busy_timeout=5000'e güveniyor), `db_manager.py` kilitli kalıcı bağlantı. Sürekli yazma yükünde `database is locked` olasılığı artıyor — ve [H-13] nedeniyle bu hata graceful wrapper'dan kaçıyor |

---

## 8. MİMARİ DEĞERLENDİRME

### Güçlü yönler
- Katmanlı yapı net: `data/` → `engines/` → `execution/` → `api/`
- **Circular dependency: 0** (statik analizle doğrulandı — v49'dan beri korunmuş)
- Çok katmanlı savunma tasarımı (preflight → global timeout → watchdog → reconciler → failsafe → kill switch)
- Opsiyonel bağımlılıklar zarif ele alınmış (river/RL/TF yoksa özellik kapanıyor, bot çalışıyor)
- `position_state.py` **tek doğru örnek**: ağ çağrılarını kilit dışında tutuyor (snapshot al → kilidi bırak → I/O yap)
- `tests/test_execution.py` gerçekten güçlü: paper modda gerçek emir gitmediği, SL konamayınca
  pozisyonun zorla kapandığı, ters/sıfır SL'in borsaya gitmeden reddedildiği, retry idempotency'si
  ve kill switch sayacının thread-safety'si anlamlı assertion'larla test ediliyor

### Zayıf yönler
1. **Fail-open deseni sistemik.** [C-1], [C-2], [H-8] aynı kök nedeni paylaşıyor: "bilmiyorum"
   durumu "sorun yok" olarak kodlanmış. Finansal risk taşıyan bir sistemde varsayılan
   **fail-closed** olmalı. `risk_manager.marjin_kontrol`'ün doğru yapması, bunun bilgi eksikliği
   değil tutarsız uygulama olduğunu gösteriyor.
2. **Sessiz başarısızlık kültürü.** 33 `except: pass` + güvenlik kontrolü çöküşlerinin `log.debug`'a
   yazılması, üç ayrı `NameError`'ın ([H-1], [H-2], [H-3]) fark edilmeden aylarca yaşamasına izin verdi.
   Bunlardan biri gerçek bir risk kontrolünü ([H-1] dayanıklılık doğrulayıcı) tamamen ölü bıraktı.
   **Öneri:** Ağ/borsa çağrısı DIŞINDAKİ her `except Exception → log.debug` bloğunu gözden geçir;
   ya istisna tipini daralt ya da log seviyesini yükselt.
3. **Koruma thread'leri denetimsiz.** [C-3] ve [C-5] aynı sınıf: arka plan güvenlik thread'i ölür,
   kimse fark etmez. Hiçbir heartbeat/liveness kontrolü yok.
4. **`main.py` 2922 satır** (v49'da 2877'ydi — **büyümüş**). En az 6 farklı sorumluluk tek modülde.
   Üç `NameError` bu yapının doğrudan semptomu: fonksiyonlar, başka fonksiyonların yan etkisi olarak
   import edilen isimlere bağımlı.
5. **Bağımlılık enjeksiyonu yok.** 5 global singleton, hepsi kilitsiz getter'la [M-17].
   `_execution_isle()` veya `coin_analiz()`'i izole birim testine sokmak mümkün değil.
6. **Kod ikilikleri:** `database.py`/`db_manager.py` (v49'dan beri, hâlâ), `order_ack.py`/`fill_verify()`
   [H-10], iki korelasyon motoru [M-15], üç pozisyon boyutlandırma algoritması [M-10],
   üç likidasyon formülü [H-11]. Her biri "birini düzeltip diğerini unutma" riski taşıyor.
7. **Ölü kod, canlı kod gibi görünüyor.** `order_ack.py` (254 satır), `exchange_simulator.emir_sim()`,
   `binance_client.py` spot emir fonksiyonları, `order_engine.MAX_RETRY`, `order_reconciler.tp_onarim`.
   Bunlar yalnızca israf değil — kod tabanını inceleyen birine **var olmayan koruma** izlenimi veriyor.

---

## 9. TEKNİK BORÇLAR (öncelik sırasıyla)

1. **Fail-open → fail-closed dönüşümü** ([C-1], [C-2], [H-8]) — en yüksek finansal risk/çaba oranı
2. **Koruma thread'lerine catch-all + heartbeat** ([C-3], [C-5])
3. **6 tanımsız isim düzeltmesi** ([C-6], [H-1], [H-2], [H-3]) — `pyflakes` ile 1 dakikada bulunur, dakikalar içinde düzelir
4. **`risk_manager`'a kilit** ([H-4]) — kill_switch v54 deseni zaten mevcut, kopyalanacak
5. **CI kurulumu yok** — `pyflakes`/`ruff` bu raporun 6 bulgusunu otomatik yakalardı.
   GitHub Actions'da `pyflakes + testleri_calistir.py` en yüksek getirili tek adım
6. Test kapsamının gerçekten anlamlı hale getirilmesi (bkz. bölüm 10)
7. `main.py` modülerleştirmesi (Telegram komutları → `telegram/commands.py`)
8. `database.py`/`db_manager.py` birleştirmesi (v49'dan beri açık)
9. Ölü kod temizliği ([H-10], L-5, `emir_sim`)
10. Tip ipuçları + `mypy` entegrasyonu
11. `requirements.txt` üst sınırları, Docker base image digest pinning

---

## 10. TEST KAPSAMI EKSİKLERİ

### ⚠️ Kritik: Var olan testlerin bir kısmı yanıltıcı

| Test | Sorun |
|---|---|
| `test_execution.py:666-673` `test_guard_sorgu_hatasinda_engeller` | **Yanlış katmanı mock'luyor** — `_binance_pozisyon_var`'ı doğrudan değiştirip hata fırlatıyor, böylece [C-1]'deki gerçek hatalı kodu tamamen atlıyor. Test geçiyor, bug yaşıyor. **Aktif olarak zararlı: sahte güven veriyor.** |
| `test_cekirdek.py:122-135` `test_paper_dusuk_skor_reddedilir` | **Totolojik** — son assertion'ı kelimenin tam anlamıyla koşulsuz `assert True`. Docstring'i düşük AI skorlu sinyallerin reddedildiğini doğruladığını iddia ediyor; **bu test başarısız olamaz.** |

### Kapsam dışı kritik modüller

| Modül | Risk | Öncelik |
|---|---|---|
| `nodes/execution_node.py` | [C-6] hiçbir test yakalamadı; node komple çöküyor | **1** |
| `utils/exceptions.py` hiyerarşisi | [C-7] tek satır `issubclass` assertion'ı ile yakalanırdı | **2** |
| `engines/event_bus.py` | [C-5] dispatcher thread ölümü — hiç test yok | **3** |
| `data/multi_exchange.py` | [C-4] cache yolu hiç test edilmemiş | **4** |
| `core/indicators.py` / `market_regime.py` | RSI/MACD/ADX/chop değerlerinin sayısal doğruluğu test edilmiyor — doğrudan giriş kararlarını sürüyor | 5 |
| `core/preflight.py` | Yalnızca `bool` döndüğü test ediliyor; [H-8]'in "asla başarısız olamaz" davranışı test edilmiyor | 6 |
| `engines/backtest_engine.py` | [H-7] likidasyon çift düşümü — test yok | 7 |
| `api/dashboard.py` | Auth mantığı için test yok | 8 |
| `data/db_manager.py` | SQLite fallback yolu hiç çalıştırılmamış ([H-12] bu yüzden gizli kalmış) | 9 |

**Test/üretim oranı:** ~1.173 satır test vs ~19.650 satır üretim kodu (**%6**).
v49'un iddia ettiği "%28 kapsam" satır bazında değil, dokunulan modül sayısı bazında görünüyor.
Execution ve kill-switch yolları iyi kapsanmış; gösterge/rejim matematiği, config/preflight
doğrulama mantığı ve yeni bulunan tüm kritik yollar kapsanmamış.

---

## 11. İNCELENEMEYEN DOSYALAR

**Yok.** 132 dosyanın tamamı incelendi.

Notlar:
- `saved_models/` — yalnızca `__init__.py` + boş `online/`, `rl/`, `shadow/` alt dizinleri.
  `.pkl`/`.keras` dosyası yok. Yapı doğrulandı, içerik olmadığı için inceleme gerektirmedi.
- `logs/` — boş. Yapı doğrulandı.
- `models/` — yalnızca `__init__.py`.
- 15 adet `__init__.py` dosyasının tamamı boş (0 bayt) olarak doğrulandı — hiçbirinde
  gizli import/yan etki yok.
- `.env` — **mevcut değil** (doğrulandı). v49'un C-1 kritik bulgusu bu tarafta kapatılmış.

---

## 12. DOĞRULAMA YÖNTEMİ

Bu denetimde iddialar iki aşamalı doğrulandı:
1. **6 paralel derin inceleme** — her dosya baştan sona, örnekleme yapılmadan okundu
2. **Bağımsız teyit** — kritik bulguların tamamı raporlayandan bağımsız olarak doğrudan kod
   okuması ve statik analizle teyit edildi

`python -m pyflakes` çıktısı (tüm proje, 80 Python dosyası):
```
main.py:518:31: undefined name 'JOURNAL_DB_PATH'
main.py:1076:46: undefined name 'LOOKBACK'
main.py:1077:59: undefined name 'LOOKBACK'
main.py:2198:57: undefined name 'reconciler'
main.py:2472:59: undefined name 'LOOKBACK'
nodes/execution_node.py:153:33: undefined name 'InsufficientBalanceError'
```

Raporda **✅DOĞRULANDI** işaretli bulgular bu ikinci turdan geçmiştir:
[C-1], [C-4], [C-5], [C-6], [C-7], [C-8], [H-1], [H-2], [H-3], [H-7], [H-8], [M-2].
İşaretsiz bulgular tek turluk inceleme sonucudur ve uygulamadan önce teyit edilmelidir.

---

## 13. ÖNCEKİ DENETİMİN (v49) DOĞRULANMASI

| v49 bulgusu | İddia | Gerçek durum |
|---|---|---|
| C-1 `.env` sırlarla dağıtımda | Düzeltildi | ✅ **DOĞRU** — `.env` yok, `.gitignore`/`.dockerignore` doğru kapsıyor |
| C-2 Dockerfile sırları imaja gömüyor | Düzeltildi | ✅ **DOĞRU** — `.dockerignore` mevcut, non-root user doğru |
| H-1 DB bağlantı sızıntısı (11 fonksiyon) | Düzeltildi | ✅ **DOĞRU** — `@contextmanager baglanti()` 11 fonksiyonun **tamamında** tutarlı kullanılıyor, `finally`'de kapatılıyor. (Tek istisna: `api/dashboard.py:46-88` bu deseni izlemiyor — [L-3]) |
| H-2 Dashboard auth yok | Uygulanmadı | 🟡 **KISMEN** — v50'de Basic Auth eklenmiş ve **doğru yazılmış** (timing-safe, tüm endpoint'lerde). Ancak varsayılan fail-open ve `0.0.0.0` bağlanma sürüyor [M-2] |
| M-1 Yinelenen `futures_bakiye()` | Düzeltildi | ⚠️ **REGRESYON** — `main.py:2133`'te düzeltilmiş, ama aynı anti-pattern `coin_analiz` ve `_execution_isle`'de mevcut [P-1] |
| M-2 `database.py`/`db_manager.py` ikiliği | Bilinçli ertelendi | ⚠️ **KÖTÜLEŞMİŞ** — ikilik sürüyor, üstelik `db_manager.py`'ın **kendi içinde** şema/SQL uyumsuzluğu var [H-12] |
| M-3 32 sessiz exception | Kısmen düzeltildi | ⚠️ **33'e ÇIKMIŞ** — üstelik [C-5]'te "temizlik" sırasında `except` tipleri yanlışlıkla daraltılmış ve dispatcher'ı kırılgan hale getirmiş |
| M-5 Log rotasyonu yok | Öneri verildi | ✅ **UYGULANMIŞ** — `baslat.sh` 50MB×5 rotasyon yapıyor (`docker/watchdog.sh` hariç, [L-12]) |
| L-2 `main.py` çok büyük | 2877 satır | ⚠️ **BÜYÜMÜŞ** — 2922 satır |
| "Circular dependency: 0" | Temiz | ✅ **DOĞRU** — hâlâ asiklik |
| "SQL Injection: TEMİZ" | Temiz | ✅ **DOĞRU** — bağımsız olarak yeniden doğrulandı, tüm sorgular parametreli |

---

## 14. v55 CHANGELOG İDDİALARININ DOĞRULANMASI

| v55 iddiası | Gerçek durum |
|---|---|
| BUG 1: `duplicate_guard` lock içinde ağ çağrısı | 🟡 **YARIM** — Kilit/ağ ayrımı **doğru yapılmış** (paralellik gerçekten sağlanmış). Ama iddia edilen "sorgu başarısızsa işleme İZİN VERİLMEZ" fail-safe'i **çalışmıyor** — bkz. [C-1]. Testi de yanlış katmanı mock'luyor |
| BUG 2: Acil SL kaldıraçtan bağımsızdı | ✅ **DOĞRU DÜZELTİLMİŞ** — `order_reconciler.py:150-158`'de `min(0.05, (1.0/_kald)*0.5)` mevcut ve matematiksel olarak doğru |
| BUG 3: Reconciler hataları DEBUG'da gizleniyordu | ✅ **DOĞRU DÜZELTİLMİŞ** — `:119-123, 164-169` artık `log.error` ve açık "koruma doğrulanamadı" mesajı |
| BUG 4: FAILOVER log spam | ✅ **DOĞRU DÜZELTİLMİŞ** — `exchange_failover.py:63-64, 80-81` `backup == primary` durumunda sessizce çıkıyor |
| "60/60 test geçiyor" | ✅ Doğru, **ama** en az 2 test anlamsız/yanıltıcı (bkz. bölüm 10) |

---

## 15. ACİL AKSİYON LİSTESİ

### Bugün (kod değişikliği, ~1-2 saat)
1. **[C-6]** `nodes/execution_node.py` — `InsufficientBalanceError` import et *(1 satır)*
2. **[C-7]** `utils/exceptions.py:243-245` — yinelenen sınıf tanımını sil *(3 satır)*
3. **[C-8]** `engines/model_engine.py:767` — kaçak `adaylar.append()`'i sil *(1 satır)*
4. **[H-1][H-2][H-3]** `main.py` — `JOURNAL_DB_PATH`, `LOOKBACK` import et; `reconciler` → `order_reconciler` *(3 satır)*
5. **[C-4]** `data/multi_exchange.py:139-140` — `cached.get(...)` → `c.get("bybit_ham"/"okx_ham")` *(2 satır)*
6. **[C-5]** `engines/event_bus.py` — `Full` import et, dispatcher `except`'lerini genişlet *(4 satır)*
7. **[C-3]** `execution/failsafe_liquidation.py` — catch-all `except Exception` ekle *(3 satır)*

> Bu 7 madde toplam **~20 satır** değişiklik ve kod tabanındaki kritik hataların çoğunu kapatıyor.

### Bu hafta
8. **[C-1]** `duplicate_guard._binance_pozisyon_var` fail-open'ı kaldır **+ testi düzelt**
9. **[C-2]** `acik_futures_pozisyonlar()` — "boş" ile "bilinmiyor"u ayır
10. **[H-7]** `backtest_engine.py` likidasyon çift düşümü (tüm geçmiş backtest sonuçları etkilenmiş)
11. **[M-1]** `.env.example` → `LIVE_TRADING=false`
12. **[M-2]** Dashboard: auth yoksa başlangıçta `CRITICAL` uyarı bas, `127.0.0.1`'e bağlan
13. **[H-16]** `docker-compose.yml`: şifreleri secrets'a taşı, Redis/Postgres host portlarını kaldır

### Bu ay
14. **[H-4]** `risk_manager`'a threading kilidi
15. **[H-5]** Chandelier state temizliğini `POSITION_CLOSED` event'ine bağla
16. **[H-8][H-9]** `preflight`: Binance erişilemezse canlı modda başlatmayı engelle + DB bütünlük kontrolü ekle
17. **CI kur:** `pyflakes` + `testleri_calistir.py` (bu raporun 6 bulgusunu otomatik yakalardı)
18. **[H-10]** `order_ack.py`: ya bağla ya sil
19. Yanıltıcı testleri düzelt (`test_guard_sorgu_hatasinda_engeller`, `test_paper_dusuk_skor_reddedilir`)

### `CANLI_GECIS_PROTOKOLU.md` için not
Protokolün Aşama 0 ön koşullarına şunlar eklenmelidir:
- `python -m pyflakes *.py */*.py` **temiz çıktı vermeli** (şu an 6 tanımsız isim var)
- [C-1] ve [C-2] düzeltilmiş olmalı — bunlar olmadan duplicate/pozisyon koruması ağ kesintisinde çalışmıyor
- `PANEL_USER`/`PANEL_PASS` **dolu olmalı** (protokolde 0.5 maddesi bunu zaten istiyor, ancak
  boş bırakılırsa hiçbir uyarı verilmediği için doğrulanabilir değil)

---

## SONUÇ

| Metrik | Değer |
|---|---|
| **Toplam dosya sayısı** | **132** |
| **İncelenen dosya sayısı** | **132** |
| **Atlanan dosya sayısı** | **0** |
| **Bulunan hata sayısı** | **58** |
| **Kritik hata sayısı** | **8** |

İncelenen dosya sayısı toplam dosya sayısına eşittir — analiz tamamlanmıştır.

**Genel değerlendirme:** Bu kod tabanı ciddi mühendislik emeği taşıyor — katmanlı mimari,
sıfır circular dependency, sistematik bölme koruması, idempotent emir gönderimi, çok katmanlı
risk savunması ve gerçekten anlamlı execution testleri mevcut. Ancak **koruma katmanlarının
birçoğu, korumak için var oldukları durumda sessizce devre dışı kalıyor.** Sekiz kritik bulgunun
altısı aynı iki kök nedene indirgeniyor: *(a)* belirsizliğin "sorun yok" olarak kodlanması (fail-open)
ve *(b)* başarısızlıkların görünmez kılınması (sessiz `except`, `log.debug`, denetimsiz thread'ler).

En rahatsız edici tekil bulgu [C-1]: bir güvenlik düzeltmesinin uygulanmış *görünmesi*, testinin
*geçmesi*, ama korumanın gerçekte olmaması. Bu kod tabanında **testlerin yeşil olmasına
doğruluk kanıtı olarak güvenilmemelidir.**

İyi haber: kritik bulguların çoğu tek satırlık düzeltmeler. Yukarıdaki "Bugün" listesindeki
7 madde ~20 satır değişiklikle kritik yüzeyin büyük kısmını kapatıyor.
