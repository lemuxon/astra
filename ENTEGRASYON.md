# ASTRA v15.0 — Üretim Kılavuzu

## v15'te Düzeltilen 22 Sorun

### KRİTİK (6 sorun)
| Sorun | Düzeltme |
|-------|---------|
| İki reconciler çakışıyordu | FillReconciler kaldırıldı, OrderReconciler tek |
| Import sırasında Binance sync | `get_state_manager(auto_sync=False)` — lazy init |
| FillReconciler module-level start | `futures_dashboard()` içinde başlatılıyor |
| BACKUP_FUTURES_URL testnet'e yanlış | `FUTURES_BASE_URL` ile eşleştirildi |
| recvWindow=5000ms çok kısa | 10000ms'ye yükseltildi |
| Async Telegram komutları blocking | `run_in_executor` ile non-blocking |

### YÜKSEK (7 sorun)
| Sorun | Düzeltme |
|-------|---------|
| `_son_analizler` race condition | `threading.Lock()` ile korundu |
| Telegram rate limiter memory leak | 1 saatlik TTL temizleme eklendi |
| Feedback JSONL her döngüde okunuyor | mtime-based disk cache |
| MTF confluence 25 API isteği/döngü | 60s TTL cache eklendi |
| Log dosyası rotation yok | `RotatingFileHandler` 10MB×5 |
| Model pkl sklearn uyumsuzluğu | Yükleme sırasında test + otomatik silme |
| Version string karışık v12/v13/v14 | Hepsi v15.0 |

### ORTA (6 sorun)
| Sorun | Düzeltme |
|-------|---------|
| SCAN_INTERVAL döngü süresini saymıyor | `time.sleep(max(1, SCAN-elapsed))` |
| Trade journal sadece paper'da | `execution_engine.py`'de LIVE için de kayıt |
| Chop Index yanlış formül | log10 bazlı standart Chop Index |
| `bare except: pass` 8 adet | `log.debug` ile hatalar görünür |
| Kill switch reset yarım | Tüm sayaçlar ve kill sebepleri sıfırlanıyor |
| `.env`'de eksik değerler | `FUTURES_TP2_ATR_MULT` eklendi |

## Kurulum

```bash
rm -f data/astra.db data/journal.db
pip install -r requirements.txt
python main.py bot
```

## .env Zorunlu Değerler

```env
BOT_TOKEN=...
CHAT_ID=...
BINANCE_API_KEY=...      # testnet.binancefuture.com'dan
BINANCE_API_SECRET=...
FUTURES_BASE_URL=https://testnet.binancefuture.com
LIVE_TRADING=true        # demo emirler için
SCAN_INTERVAL=60
TRADE_USDT=20
```

## Demo Binance (testnet.binancefuture.com)
API key oluştururken **IP kısıtlaması OLMADAN** (Unrestricted) seçin.
Bot başlarken Telegram'a bağlantı durumunu bildirecek.

## Komutlar
```
/btc /coin ETH /scan     — analiz
/fpoz /fkapat BTC LONG   — pozisyon
/bakiye /paper /journal  — raporlar
/risk /watchdog /engine  — sistem
/killswitch              — kill switch durumu
/killswitch_reset        — işlemleri yeniden başlat
/edge BTC /selflearn     — AI durumu
```
