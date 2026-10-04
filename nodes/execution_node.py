# =========================================================
# ASTRA v30.0 — EXECUTION NODE
# Signal node'dan gelen sinyalleri işler.
# Ayrı process — signal node'dan bağımsız çalışır.
# python nodes/execution_node.py
# =========================================================
import sys, os, time, logging, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from config import (LIVE_TRADING, REDIS_ENABLED, REDIS_HOST, REDIS_PORT,
                    REDIS_DB, BALANCE, FUTURES_LEVERAGE, TRADE_USDT)
from engines.event_bus import get_bus, Event
from utils.exceptions import (
    NetworkError, FatalExchangeError, RetryableExchangeError,
    RiskError, ExecutionError, StopLossFailedError, SlippageExceededError,
    InsufficientBalanceError,
)

log = logging.getLogger("ASTRA.EXECUTION_NODE")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EXEC] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/execution_node.log", encoding="utf-8"),
    ]
)

# Kuyruk
try:
    if REDIS_ENABLED:
        import redis
        _redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
                              decode_responses=True, socket_timeout=3)
        _redis.ping()
        QUEUE_BACKEND = "redis"
        log.info(f"[EXEC NODE] Redis: {REDIS_HOST}:{REDIS_PORT}")
    else:
        raise ImportError
except (ImportError, Exception):
    QUEUE_BACKEND = "memory"
    log.info("[EXEC NODE] Memory queue (in-process ile çalışır)")

# Global bileşenler
from engines.risk_manager import RiskManager
from engines.position_state import get_state_manager
from execution.execution_engine import get_execution_engine
from execution.fill_reconciler import FillReconciler
from execution.state_audit import get_audit
from execution.failsafe_liquidation import get_failsafe_guard
from engines.watchdog import get_watchdog
from engines.exchange_failover import get_failover
from monitoring.prometheus_metrics import get_metrics

risk_manager    = RiskManager(BALANCE)
state_manager   = get_state_manager()
exec_engine     = get_execution_engine(risk_manager, state_manager)
reconciler      = FillReconciler(state_manager)
state_audit     = get_audit()
failsafe_guard  = get_failsafe_guard()
failover        = get_failover()
metrics         = get_metrics()
reconciler.start()
# v30: fabrika artık otomatik başlatmıyor — açıkça başlat
state_audit.start()
failsafe_guard.start()
failover.start()


def _sinyal_oku() -> dict:
    """Kuyruktan sinyal oku. Bloklanır (polling)."""
    if QUEUE_BACKEND == "redis":
        try:
            sonuc = _redis.brpop("astra:signals", timeout=2)
            if sonuc:
                _, veri = sonuc
                return json.loads(veri)
        except (json.JSONDecodeError, ValueError) as e:
            log.warning(f"[EXEC NODE] Sinyal parse hatası: {e}")
        except Exception as e:
            log.error(f"[EXEC NODE] Redis okuma hatası: {e}")
            time.sleep(1)
    else:
        # Memory queue için signal_node ile aynı process olmalı
        # Standalone kullanımda signal_node ile birlikte main.py kullan
        time.sleep(2)
    return {}


def _isle(sinyal: dict):
    """
    Gelen sinyali işle.
    Tüm execution katmanları buradan geçiyor.
    """
    if not LIVE_TRADING:
        log.info(f"[PAPER] {sinyal.get('sembol')} {sinyal.get('karar')} atlandı")
        return

    sembol   = sinyal.get("sembol","")
    karar    = sinyal.get("karar","")
    is_buy   = "BUY" in karar
    is_sell  = "SELL" in karar
    if not is_buy and not is_sell: return

    yon      = "LONG" if is_buy else "SHORT"
    fiyat    = sinyal.get("son_close", 0)
    atr      = sinyal.get("son_atr", fiyat * 0.01)
    rejim    = sinyal.get("rejim","RANGE")
    ai_score = sinyal.get("ai_score", 0)

    try:
        from data.binance_futures_client import futures_bakiye, pozisyon_var_mi
        bakiye = futures_bakiye()

        # Dinamik parametreler
        kaldirac = risk_manager.dinamik_kaldirac_hesapla(fiyat, atr)
        win_rate = sinyal.get("yukselis_guveni", 55) / 100
        usdt     = risk_manager.pozisyon_buyuklugu_hesapla(
            bakiye, fiyat, atr, win_rate)
        usdt     = min(usdt, bakiye * 0.9)

        from engines.futures_trade_engine import sl_tp_hesapla
        levels = sl_tp_hesapla(fiyat, yon, atr, rejim)

        # Zıt pozisyon kapat
        kapat_yon = "SHORT" if is_buy else "LONG"
        if pozisyon_var_mi(sembol, kapat_yon):
            sonuc = exec_engine.pozisyon_kapat(sembol, kapat_yon, "ZIT_SINYAL")
            if sonuc.basarili:
                log.info(f"[EXEC NODE] Zıt pozisyon kapatıldı: {sembol} {kapat_yon}")
            time.sleep(0.5)

        if pozisyon_var_mi(sembol, yon):
            log.debug(f"[EXEC NODE] {sembol} {yon} zaten açık")
            return

        # Pozisyon aç
        sonuc = exec_engine.pozisyon_ac(
            sembol=sembol, yon=yon, usdt=usdt,
            sl=levels["sl"], tp1=levels["tp1"], tp2=levels["tp2"],
            kaldirac=kaldirac, rejim=rejim,
            ai_score=ai_score,
            kaynak=sinyal.get("strateji", "SIGNAL"),
        )

        if sonuc.basarili:
            log.info(f"[EXEC NODE] ✅ {sonuc}")
            metrics.emir_sayisi.labels(
                sembol=sembol, yon=yon, durum="filled").inc()
        else:
            log.warning(f"[EXEC NODE] ❌ {sembol}: {sonuc.hata}")

    except (FatalExchangeError, InsufficientBalanceError) as e:
        log.error(f"[EXEC NODE] {sembol} fatal exchange hatası: {e}")
        metrics.hata_sayisi.labels(kaynak=sembol, tip="fatal_exchange").inc()

    except (RetryableExchangeError, NetworkError) as e:
        log.warning(f"[EXEC NODE] {sembol} geçici hata: {e}")

    except (StopLossFailedError, SlippageExceededError) as e:
        log.critical(f"[EXEC NODE] {sembol} execution kritik: {e}")
        metrics.hata_sayisi.labels(kaynak=sembol, tip="execution_critical").inc()

    except RiskError as e:
        log.warning(f"[EXEC NODE] {sembol} risk engeli: {e}")

    except ExecutionError as e:
        log.error(f"[EXEC NODE] {sembol} execution hatası: {e}")

    except Exception as e:
        # v55: Beklenmedik hata bu sinyali atlar ama node'u ÖLDÜRMEZ.
        log.error(f"[EXEC NODE] {sembol} beklenmedik hata: "
                  f"{type(e).__name__}: {e}", exc_info=True)


def execution_node_calistir():
    """Execution node ana döngüsü."""
    os.makedirs("logs", exist_ok=True)
    watchdog = get_watchdog()

    log.info(f"🟢 EXECUTION NODE başlatıldı | LIVE:{LIVE_TRADING} | Queue:{QUEUE_BACKEND}")

    while True:
        try:
            sinyal = _sinyal_oku()
            if sinyal:
                log.info(f"[EXEC NODE] Sinyal alındı: "
                          f"{sinyal.get('sembol')} {sinyal.get('karar')}")
                _isle(sinyal)
                watchdog.heartbeat("execution_node")

        except (FatalExchangeError, RetryableExchangeError) as e:
            log.error(f"[EXEC NODE] Exchange hatası: {e}")
            watchdog.hata_bildir(e, "execution_node")

        except NetworkError as e:
            log.warning(f"[EXEC NODE] Ağ hatası: {e}")

        except (ValueError, KeyError, TypeError) as e:
            log.error(f"[EXEC NODE] Veri hatası: {type(e).__name__}: {e}")
            watchdog.hata_bildir(e, "execution_node")

        except Exception as e:
            # v55: Ana döngü HİÇBİR hatada ölmemeli — node process'i
            # düşerse sinyaller sessizce işlenmeden kalır.
            log.critical(f"[EXEC NODE] Beklenmedik döngü hatası (node YAŞIYOR): "
                         f"{type(e).__name__}: {e}", exc_info=True)
            watchdog.hata_bildir(e, "execution_node")
            time.sleep(1)


if __name__ == "__main__":
    execution_node_calistir()
