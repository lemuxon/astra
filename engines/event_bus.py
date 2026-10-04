# =========================================================
# ASTRA v30.0 — EVENT BUS (Event-Driven Architecture)
# Redis varsa Redis Queue, yoksa in-memory queue kullanır.
# Tüm bileşenler bu bus üzerinden haberleşir.
# =========================================================
import logging, json, threading, time
from queue import Queue, Empty, Full
from datetime import datetime, timezone
from typing import Callable, Optional
import sys; sys.path.append("..")
from config import REDIS_ENABLED, REDIS_HOST, REDIS_PORT, REDIS_DB

log = logging.getLogger("ASTRA.EVENT_BUS")

# ── Event Tipleri ─────────────────────────────────────────
class Event:
    # Sinyal olayları
    SIGNAL_GENERATED   = "signal.generated"    # coin_analiz tamamlandı
    SIGNAL_FILTERED    = "signal.filtered"      # filtreden geçti
    # Order olayları
    ORDER_REQUESTED    = "order.requested"      # işlem isteği
    ORDER_PLACED       = "order.placed"         # emir gönderildi
    ORDER_FILLED       = "order.filled"         # emir doldu
    ORDER_FAILED       = "order.failed"         # emir başarısız
    ORDER_CANCELLED    = "order.cancelled"      # emir iptal
    # Pozisyon olayları
    POSITION_OPENED    = "position.opened"      # pozisyon açıldı
    POSITION_CLOSED    = "position.closed"      # pozisyon kapandı
    POSITION_SL_HIT    = "position.sl_hit"      # stop loss tetiklendi
    POSITION_TP_HIT    = "position.tp_hit"      # take profit tetiklendi
    # Risk olayları
    RISK_LIMIT_HIT     = "risk.limit_hit"       # günlük limit aşıldı
    RISK_DRAWDOWN      = "risk.drawdown"        # drawdown eşiği
    RISK_LIQUIDATION   = "risk.liquidation"     # likidasyon tehlikesi
    # Model olayları
    MODEL_RETRAINED    = "model.retrained"      # model yeniden eğitildi
    MODEL_DEGRADED     = "model.degraded"       # model doğruluğu düştü
    # Sistem olayları
    EXCHANGE_ERROR     = "exchange.error"       # borsa hatası
    EXCHANGE_FAILOVER  = "exchange.failover"    # yedek borsaya geçildi
    HEARTBEAT          = "system.heartbeat"     # sistem sağlık darbesi
    ALERT              = "system.alert"         # genel uyarı

class EventMessage:
    def __init__(self, event_type: str, data: dict, source: str = ""):
        self.event_type = event_type
        self.data       = data
        self.source     = source
        self.ts         = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        self.id         = f"{event_type}_{int(time.time()*1000)}"

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.event_type,
                "data": self.data, "source": self.source, "ts": self.ts}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, s: str) -> "EventMessage":
        d = json.loads(s)
        msg = cls(d["type"], d["data"], d.get("source",""))
        msg.ts = d.get("ts",""); msg.id = d.get("id","")
        return msg

# ── Event Bus ─────────────────────────────────────────────
class EventBus:
    """
    Merkezi event bus.
    - Redis varsa: kalıcı, multi-process arası iletişim
    - Redis yoksa: thread-safe in-memory queue
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()
        self._history: list[EventMessage] = []
        self._max_history = 500
        self._redis = None
        self._redis_thread: Optional[threading.Thread] = None
        self._running = False

        if REDIS_ENABLED:
            self._init_redis()
        else:
            self._queue: Queue = Queue(maxsize=1000)
            self._start_memory_dispatcher()

    def _init_redis(self):
        try:
            import redis
            self._redis = redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
                decode_responses=True, socket_timeout=3
            )
            self._redis.ping()
            self._running = True
            self._redis_thread = threading.Thread(
                target=self._redis_dispatcher, daemon=True, name="AstraRedisDispatcher"
            )
            self._redis_thread.start()
            log.info(f"[EVENT_BUS] Redis bağlandı: {REDIS_HOST}:{REDIS_PORT}")
        except (ValueError, AttributeError, RuntimeError) as e:
            log.warning(f"[EVENT_BUS] Redis bağlanamadı ({e}), memory queue kullanılıyor")
            self._redis = None
            self._queue = Queue(maxsize=1000)
            self._start_memory_dispatcher()

    def _start_memory_dispatcher(self):
        self._running = True
        t = threading.Thread(target=self._memory_dispatcher, daemon=True, name="AstraEventDispatcher")
        t.start()

    def _memory_dispatcher(self):
        # v55: Bu thread ASLA ölmemeli. Ölürse publish() sessizce başarılı
        # görünmeye devam eder ama hiçbir event dağıtılmaz — Kelly/PnL,
        # günlük zarar limiti ve kill switch güncellemeleri durur.
        while self._running:
            try:
                msg = self._queue.get(timeout=0.1)
                self._dispatch(msg)
            except Empty:
                continue
            except Exception as e:
                log.error(f"[EVENT_BUS] Dispatch hatası (dispatcher YAŞIYOR): "
                          f"{type(e).__name__}: {e}", exc_info=True)

    def _redis_dispatcher(self):
        CHANNEL = "astra:events"
        pubsub = self._redis.pubsub()
        pubsub.subscribe(CHANNEL)
        while self._running:
            try:
                msg = pubsub.get_message(timeout=0.1)
                if msg and msg["type"] == "message":
                    event = EventMessage.from_json(msg["data"])
                    self._dispatch(event)
            except Exception as e:
                log.error(f"[EVENT_BUS] Redis dispatcher hatası (YAŞIYOR): "
                          f"{type(e).__name__}: {e}", exc_info=True)
                time.sleep(1)

    def _dispatch(self, msg: EventMessage):
        """Subscriber'lara event'i ilet."""
        with self._lock:
            self._history.append(msg)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            handlers = list(self._subscribers.get(msg.event_type, []))
            handlers += list(self._subscribers.get("*", []))  # wildcard

        for handler in handlers:
            try:
                handler(msg)
            except Exception as e:
                # v55: eskiden yalnızca (ValueError, AttributeError, TypeError)
                # yakalanıyordu; handler'dan gelen bir KeyError dispatcher
                # thread'ini komple öldürüyordu.
                log.error(f"[EVENT_BUS] Handler hatası ({msg.event_type}): "
                          f"{type(e).__name__}: {e}", exc_info=True)

    def publish(self, event_type: str, data: dict, source: str = "") -> EventMessage:
        """Event yayınla."""
        msg = EventMessage(event_type, data, source)
        if self._redis:
            try:
                self._redis.publish("astra:events", msg.to_json())
                return msg
            except (ValueError, AttributeError, RuntimeError) as e:
                log.warning(f"[EVENT_BUS] Redis publish hatası, fallback: {e}")
        try:
            self._queue.put_nowait(msg)
        except Full:
            # v55: eskiden (ValueError, AttributeError, TypeError) yakalanıyordu;
            # put_nowait() queue.Full fırlattığı için bu blok hiç çalışmıyor ve
            # yakalanmamış Full çağırana (risk_manager/order_engine) yükseliyordu.
            log.warning(f"[EVENT_BUS] Queue dolu, event atlandı: {event_type}")
        except Exception as e:
            log.error(f"[EVENT_BUS] publish hatası ({event_type}): {e}")
        return msg

    def subscribe(self, event_type: str, handler: Callable):
        """Event tipine abone ol. '*' ile tüm eventleri dinle."""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)
        log.debug(f"[EVENT_BUS] Abone: {event_type} → {handler.__name__}")

    def son_eventler(self, event_type: str = None, limit: int = 20) -> list:
        with self._lock:
            history = list(self._history)
        if event_type:
            history = [m for m in history if m.event_type == event_type]
        return [m.to_dict() for m in history[-limit:]]

    def stop(self):
        self._running = False

# Singleton
_bus_instance: Optional[EventBus] = None

_bus_lock = threading.Lock()   # v55: singleton yarış koruması

def get_bus() -> EventBus:
    global _bus_instance
    # v55: Kilitsiz `if None` iki thread'in aynı anda ayrı örnek kurmasına
    # izin veriyordu; kaybeden örnek arka plan thread'iyle birlikte öksüz
    # kalıp kendi kuyruğuna event dağıtmaya devam ediyordu.
    if _bus_instance is None:
        with _bus_lock:
            if _bus_instance is None:
                _bus_instance = EventBus()
    return _bus_instance
