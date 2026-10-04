# ASTRA AI Trader — CHANGELOG

## [v16.0.0] — 2026-05-28

### 🔴 KRİTİK GÜVENLİK
- **127 `except Exception` → spesifik exception taxonomy** — `OrderRejectError`, `DBWriteError`, `VolatilityCircuitBreakerError` vb. yeni tipler
- **63 `except: pass` → `log.debug` ile görünür** — production'da hiçbir hata gizlenmiyor
- **Tüm version string'leri v16.0 standardına alındı** — v4/v7/v8/v9/v11/v14 karmaşası giderildi

### 🆕 YENİ MODÜLLER
- **`risk/volatility_circuit_breaker.py`** — ATR spike, funding rate, spread genişlemesinde otomatik işlem duraklama (5dk)
- **`risk/correlation_engine.py`** — BTC+ETH+SOL aynı yönde exposure korelasyon filtresi
- **`engines/shadow_model.py`** — Canlı model güvenli retrain: shadow → validation → approve → deploy
- **`engines/edge_analytics.py`** — Expectancy, Profit Factor Decay, Regime WinRate, Sharpe by Volatility
- **`bootstrap/app_init.py`** — main.py God Object yerine temiz başlatma katmanı

### 🔧 İYİLEŞTİRMELER
- **Self-training güvenlik** — `shadow_model.py` ile canlı model direkt overwrite edilmiyor
- **Circuit breaker entegrasyonu** — `_execution_isle` + `coin_analiz` içinde ATR kontrolü
- **Correlation filtresi** — Aynı yönde MAJORS max 1, ALTCOINS max 2
- **Edge analytics otomatik besleme** — her kapanan pozisyon `edge_analytics.islem_ekle` çağırıyor
- **Yeni Telegram komutları** — `/circuit`, `/shadow`, `/shadow_approve`, `/correlation`

### 📁 MİMARİ
- `bootstrap/` dizini oluşturuldu — uygulama başlatma katmanı
- `risk/` dizini oluşturuldu — bağımsız risk modülleri
- `utils/exceptions.py` genişletildi — 8 yeni spesifik exception tipi

---

## [v15.0.0] — 2026-05-28
- Dashboard v15: sekme yapısı, işlem geçmişi, win rate KPI
- İşlem geçmişi panele akıyor (pozisyon_kapandi_bildir)
- Telegram grafik rate limiter eklendi
- Demo bakiye: API hata verince paper_bakiye göster
- 22 kritik bug düzeltmesi (recvWindow, reconciler birleşme, async blocking vb.)

## [v14.0.0] — 2026-05-28
- Hard Kill Switch, Trade Journal, Adaptive Sizing
- Order Reconciler (Binance↔Bot↔DB 3-yönlü)
- Volatility Circuit Breaker (temel)
- Market Regime Detection v2 (Chop Index)
- Realistic Backtest (komisyon + slippage + likidasyon)

## [v13.0.0] — 2026-05-28
- Dashboard thread-safe, JS polling 5s
- NaN/Inf JSON sanitization
- XGBoost early_stopping_rounds fix
- Stacking pickle fix

## [v12.0.0] — 2026-05-28
- EdgeEngine + RegimeAdapter entegrasyonu
- Self-training: feedback_ekle + rl_reward_kaydet
- ExecutionEngine: ACK + Fill Verify + SL validation

---

## Semantic Versioning
`MAJOR.MINOR.PATCH`
- **MAJOR**: Mimari değişiklik / API break
- **MINOR**: Yeni özellik (geriye uyumlu)
- **PATCH**: Bug fix

