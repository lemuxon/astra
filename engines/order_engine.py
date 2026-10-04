# =========================================================
# ASTRA v30.0 — ORDER ENGINE (Production Grade)
# - Sessiz except yok
# - Async-ready kuyruk
# - Fill verification entegre
# - Position state güncelleme
# - Slippage takibi
# =========================================================
import logging, time, threading, json, os
from datetime import datetime, timezone
from typing import Optional
from queue import Queue, Empty
import sys; sys.path.append("..")
from config import (LIVE_TRADING, FUTURES_LEVERAGE,
                    FUTURES_TRAILING_STOP, FUTURES_TRAILING_CALLBACK,
                    FUTURES_PARTIAL_TP, FUTURES_PARTIAL_TP_PCT)
from engines.event_bus import get_bus, Event, EventMessage

log = logging.getLogger("ASTRA.ORDER_ENGINE")

class OrderRequest:
    def __init__(self, sembol: str, yon: str, usdt: float,
                 emir_tipi: str = "MARKET", kaynak: str = "AUTO",
                 ai_score: int = 0, confidence: int = 0,
                 sl: float = 0, tp1: float = 0, tp2: float = 0,
                 kaldirac: int = 5, rejim: str = "RANGE"):
        self.sembol    = sembol.upper()
        self.yon       = yon.upper()
        self.usdt      = usdt
        self.emir_tipi = emir_tipi
        self.kaynak    = kaynak
        self.ai_score  = ai_score
        self.confidence= confidence
        self.sl        = sl
        self.tp1       = tp1
        self.tp2       = tp2
        self.kaldirac  = kaldirac
        self.rejim     = rejim
        self.ts        = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        self.id        = f"{sembol}_{yon}_{int(time.time()*1000)}"

class OrderEngine:
    MAX_ORDERS_PER_SEC = 5
    MAX_RETRY          = 3
    RETRY_DELAY        = 1.5
    # v57: bkz. main.py logging blogu — testler uretim logunu kirletiyordu.
    LOG_FILE           = os.path.join(
        os.getenv("ASTRA_LOG_DIR", "logs"), "order_engine.jsonl")

    def __init__(self):
        self._queue: Queue    = Queue(maxsize=200)
        self._running         = False
        self._thread: Optional[threading.Thread] = None
        self._son_emir_zamanları: list = []
        self._islenen_ids: set = set()
        self._bus              = get_bus()
        self._state_manager    = None  # lazy import (circular önlemi)
        self._istatistik       = {
            "toplam":0,"basarili":0,"basarisiz":0,
            "duplicate":0,"rate_limited":0,"slippage_red":0
        }
        os.makedirs("logs", exist_ok=True)

    def _get_state(self):
        if self._state_manager is None:
            from engines.position_state import get_state_manager
            self._state_manager = get_state_manager()
        return self._state_manager

    def start(self):
        # v29: çift başlatma koruması — iki paralel loop çift emir gönderebilir
        if getattr(self, "_thread", None) and self._thread.is_alive():
            log.warning("[ORDER ENGINE] Zaten çalışıyor — tekrar başlatılmadı")
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._process_loop, daemon=True, name="AstraOrderEngine"
        )
        self._thread.start()
        log.info("[ORDER ENGINE] Başlatıldı")

    def stop(self):
        self._running = False
        log.info("[ORDER ENGINE] Durduruldu")

    def submit(self, request: OrderRequest) -> bool:
        if request.id in self._islenen_ids:
            log.warning(f"[ORDER ENGINE] Duplicate: {request.id}")
            self._istatistik["duplicate"] += 1
            return False
        try:
            self._queue.put_nowait(request)
            self._bus.publish(Event.ORDER_REQUESTED, vars(request), "OrderEngine")
            log.info(f"[ORDER ENGINE] Kuyruğa: {request.sembol} {request.yon} {request.usdt:.2f}USDT")
            return True
        except Exception as e:
            log.error(f"[ORDER ENGINE] Kuyruğa eklenemedi: {e}")
            return False

    def _process_loop(self):
        while self._running:
            try:
                req = self._queue.get(timeout=0.5)
                self._rate_limit()
                self._islenen_ids.add(req.id)
                if len(self._islenen_ids) > 1000:
                    self._islenen_ids = set(list(self._islenen_ids)[-500:])
                self._isle(req)
                self._istatistik["toplam"] += 1
            except Empty:
                continue
            except Exception as e:
                # Process loop'u ölüme bırakma — ama her zaman logla
                log.critical(f"[ORDER ENGINE] Process loop kritik hata: "
                             f"{type(e).__name__}: {e}", exc_info=True)

    def _rate_limit(self):
        now = time.time()
        self._son_emir_zamanları = [t for t in self._son_emir_zamanları if now-t < 1.0]
        if len(self._son_emir_zamanları) >= self.MAX_ORDERS_PER_SEC:
            bekleme = 1.0 - (now - self._son_emir_zamanları[0])
            if bekleme > 0:
                self._istatistik["rate_limited"] += 1
                time.sleep(bekleme)
        self._son_emir_zamanları.append(time.time())

    def _isle(self, req: OrderRequest):
        if not LIVE_TRADING:
            log.info(f"[ORDER ENGINE] PAPER: {req.sembol} {req.yon} {req.usdt:.2f}USDT")
            self._logla(req, "PAPER", {})
            self._bus.publish(Event.ORDER_PLACED,
                              {"sembol":req.sembol,"yon":req.yon,"mod":"PAPER"}, "OrderEngine")
            self._istatistik["basarili"] += 1
            return

        from data.binance_futures_client import (
            futures_market_ac, futures_market_kapat,
            futures_stop_loss_koy, futures_partial_tp_koy,
            futures_take_profit_koy, futures_trailing_stop_koy,
            kaldirac_ayarla, FuturesAPIError
        )

        try:
            if req.yon in ("CLOSE_LONG","CLOSE_SHORT"):
                yon_kapat = "LONG" if req.yon == "CLOSE_LONG" else "SHORT"
                order = futures_market_kapat(req.sembol, yon_kapat)
                if order and order.get("orderId"):
                    self._basarili(req, order)
                    self._get_state().pozisyon_kapat(req.sembol, "ORDER_ENGINE")
                else:
                    log.error(f"[ORDER ENGINE] {req.sembol} kapatma başarısız: {order}")
                    self._basarisiz(req)
                return

            # Açma emri
            kaldirac_ayarla(req.sembol, req.kaldirac)
            order = futures_market_ac(req.sembol, req.yon, req.usdt)

            if order and order.get("orderId"):
                exec_fiyat = float(order.get("avgPrice", 0))
                self._basarili(req, order)

                # Position state'e kaydet
                self._get_state().pozisyon_ac(
                    req.sembol, req.yon, exec_fiyat,
                    float(order.get("executedQty", 0)),
                    req.sl, req.tp1, req.kaldirac,
                    str(order.get("orderId",""))
                )

                # SL/TP emirleri
                time.sleep(0.4)
                if req.sl > 0:
                    # v55: SL yerleştirme artık YENİDEN DENENİYOR.
                    # MAX_RETRY/RETRY_DELAY sabitleri tanımlıydı ama hiç
                    # kullanılmıyordu; tek denemede başarısız olunca pozisyon
                    # bir sonraki periyodik sl_tp_dogrula taramasına (300s)
                    # kadar KORUMASIZ kalıyordu.
                    sl_order = None
                    for _sl_deneme in range(self.MAX_RETRY):
                        try:
                            sl_order = futures_stop_loss_koy(req.sembol, req.yon, req.sl)
                        except Exception as _sl_e:
                            log.warning(f"[ORDER ENGINE] {req.sembol} SL deneme "
                                        f"{_sl_deneme+1}/{self.MAX_RETRY} hata: {_sl_e}")
                            sl_order = None
                        if sl_order and sl_order.get("orderId"):
                            break
                        if _sl_deneme < self.MAX_RETRY - 1:
                            time.sleep(self.RETRY_DELAY)

                    if sl_order and sl_order.get("orderId"):
                        self._get_state().sl_aktif_isaretle(
                            req.sembol, str(sl_order["orderId"]))
                    else:
                        # v55: SL hiç konamadıysa pozisyonu AÇIK BIRAKMA —
                        # korumasız kaldıraçlı pozisyon en büyük risktir.
                        log.critical(f"[ORDER ENGINE] {req.sembol} SL {self.MAX_RETRY} "
                                     f"denemede KOYULAMADI → pozisyon kapatılıyor")
                        self._bus.publish(Event.ALERT,
                                          {"mesaj": f"🚨 {req.sembol} SL konamadı — "
                                                    f"pozisyon zorla kapatılıyor!"}, "OrderEngine")
                        try:
                            from data.binance_futures_client import futures_market_kapat
                            kapat = futures_market_kapat(req.sembol, req.yon)
                            if kapat and kapat.get("orderId"):
                                log.info(f"[ORDER ENGINE] {req.sembol} korumasız pozisyon kapatıldı")
                                self._get_state().pozisyon_kapat(req.sembol, "SL_KONAMADI")
                            else:
                                log.critical(f"[ORDER ENGINE] {req.sembol} KAPATILAMADI — "
                                             f"MANUEL MÜDAHALE GEREKLİ!")
                                self._bus.publish(Event.ALERT,
                                                  {"mesaj": f"🚨🚨 {req.sembol} SL yok ve "
                                                            f"kapatılamadı — MANUEL!"}, "OrderEngine")
                        except Exception as _ke:
                            log.critical(f"[ORDER ENGINE] {req.sembol} acil kapatma hatası: "
                                         f"{_ke} — MANUEL MÜDAHALE!", exc_info=True)

                time.sleep(0.3)
                if req.tp1 > 0:
                    if FUTURES_PARTIAL_TP:
                        tp_order = futures_partial_tp_koy(
                            req.sembol, req.yon, req.tp1, FUTURES_PARTIAL_TP_PCT)
                    else:
                        tp_order = futures_take_profit_koy(
                            req.sembol, req.yon, req.tp2 or req.tp1)
                    if tp_order and tp_order.get("orderId"):
                        self._get_state().tp1_aktif_isaretle(
                            req.sembol, str(tp_order["orderId"]))
                    else:
                        log.warning(f"[ORDER ENGINE] {req.sembol} TP koyulamadı")

            else:
                log.error(f"[ORDER ENGINE] {req.sembol} {req.yon} emir başarısız veya fill doğrulaması geçemedi")
                self._basarisiz(req)

        except FuturesAPIError as e:
            log.error(f"[ORDER ENGINE] {req.sembol} API hatası: {e}")
            self._basarisiz(req)
            self._bus.publish(Event.ORDER_FAILED,
                              {"sembol":req.sembol,"yon":req.yon,"hata":str(e)}, "OrderEngine")
        except Exception as e:
            log.critical(f"[ORDER ENGINE] {req.sembol} beklenmedik hata: "
                         f"{type(e).__name__}: {e}", exc_info=True)
            self._basarisiz(req)

    def _basarili(self, req: OrderRequest, order: dict):
        self._istatistik["basarili"] += 1
        self._logla(req, "OK", order)
        self._bus.publish(Event.ORDER_FILLED, {
            "sembol":req.sembol,"yon":req.yon,
            "order_id":order.get("orderId"),
            "exec_fiyat":float(order.get("avgPrice",0)),
            "kaynak":req.kaynak
        }, "OrderEngine")

    def _basarisiz(self, req: OrderRequest):
        self._istatistik["basarisiz"] += 1
        self._logla(req, "FAIL", {})
        self._bus.publish(Event.ORDER_FAILED,
                          {"sembol":req.sembol,"yon":req.yon,"kaynak":req.kaynak}, "OrderEngine")

    def _logla(self, req: OrderRequest, durum: str, order: dict):
        kayit = {
            "ts":durum and datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),"durum":durum,
            "sembol":req.sembol,"yon":req.yon,"usdt":req.usdt,
            "kaynak":req.kaynak,"ai_score":req.ai_score,
            "sl":req.sl,"tp1":req.tp1,"rejim":req.rejim,
            "order_id":order.get("orderId",""),"req_id":req.id
        }
        try:
            with open(self.LOG_FILE,"a",encoding="utf-8") as f:
                f.write(json.dumps(kayit,ensure_ascii=False)+"\n")
        except OSError as e:
            log.error(f"[ORDER ENGINE] Log yazma hatası: {e}")

    @property
    def istatistik(self) -> dict:
        return {**self._istatistik,"kuyruk_boyutu":self._queue.qsize()}

# Singleton
_engine_instance: Optional[OrderEngine] = None

_engine_lock = threading.Lock()   # v55: singleton yarış koruması

def get_order_engine(otomatik_baslat: bool = False) -> OrderEngine:
    global _engine_instance
    # v55: Kilitsizken iki thread ayrı OrderEngine kurabiliyordu; kaybeden
    # örnek start() edilmişse kendi kuyruğuyla ÖKSÜZ thread olarak kalıyordu.
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _yeni = OrderEngine()
                if otomatik_baslat:
                    _yeni.start()
                _engine_instance = _yeni
    return _engine_instance
