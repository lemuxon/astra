# =========================================================
# ASTRA v30.0 — EXCHANGE FAILOVER
# Spesifik exception tipleri — broad except yok
# =========================================================
import logging, time, threading, requests
from typing import Optional
import sys; sys.path.append("..")
from config import FUTURES_BASE_URL, BACKUP_FUTURES_URL, EXCHANGE_TIMEOUT, FAILOVER_ENABLED
from engines.event_bus import get_bus, Event
from utils.exceptions import NetworkError, AstraTimeoutError

log = logging.getLogger("ASTRA.FAILOVER")

class ExchangeFailover:
    HEALTH_CHECK_INTERVAL = 30
    RECOVERY_CHECK        = 120

    def __init__(self):
        self._primary    = FUTURES_BASE_URL
        self._backup     = BACKUP_FUTURES_URL
        self._aktif      = self._primary
        self._saglik     = {"primary": True, "backup": True}
        self._son_hata   = 0
        self._hata_sayisi= 0
        self._sayac_lock = threading.Lock()   # v55: sayaç thread güvenliği
        self._running    = False
        self._thread: Optional[threading.Thread] = None
        self._bus        = get_bus()

    def start(self):
        if not FAILOVER_ENABLED: return
        # v29: çift başlatma koruması
        if getattr(self, "_thread", None) and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._health_loop, daemon=True, name="AstraFailover")
        self._thread.start()
        log.info(f"[FAILOVER] Başlatıldı. Primary: {self._primary}")

    def stop(self):
        self._running = False

    @property
    def aktif_url(self) -> str:
        return self._aktif

    def hata_bildir(self):
        # v55: Sayaç thread-güvenli (eşzamanlı hata bildirimleri kaybolmasın)
        with self._sayac_lock:
            self._hata_sayisi += 1
            self._son_hata = time.time()
            tetikle = (self._hata_sayisi >= 3 and self._aktif == self._primary)
        if tetikle:
            self._failover()

    def basari_bildir(self):
        with self._sayac_lock:
            self._hata_sayisi = 0

    def _failover(self):
        # v55: Yedek URL birincil ile aynıysa failover anlamsızdır
        if not self._backup or self._backup == self._primary:
            return
        if self._aktif == self._primary:
            self._aktif = self._backup
            log.error(f"[FAILOVER] ⚠️ Birincil DOWN → {self._backup}'e geçildi")
            self._bus.publish(Event.EXCHANGE_FAILOVER,
                              {"from": self._primary, "to": self._backup}, "Failover")
            with self._sayac_lock:
                self._hata_sayisi = 0

    def _recover(self):
        # ── v55 LOG SPAM DÜZELTMESİ ──
        # Testnet'te BACKUP_FUTURES_URL varsayılanı FUTURES_BASE_URL ile
        # AYNI. Bu durumda `_aktif == _backup` HER ZAMAN doğru oluyordu →
        # _recover() her sağlık kontrolünde çalışıp "✅ Birincil tekrar
        # aktif" mesajını sürekli basıyordu (kullanıcı loglarındaki spam).
        # Bu hem gürültü yaratıyor hem GERÇEK failover olaylarını maskeliyordu.
        if not self._backup or self._backup == self._primary:
            return
        if self._aktif == self._backup:
            self._aktif = self._primary
            log.info(f"[FAILOVER] ✅ Birincil tekrar aktif: {self._primary}")
            with self._sayac_lock:
                self._hata_sayisi = 0

    def _saglik_kontrol(self, url: str) -> bool:
        try:
            r = requests.get(f"{url}/fapi/v1/ping", timeout=EXCHANGE_TIMEOUT)
            return r.status_code == 200
        except requests.exceptions.Timeout:
            log.debug(f"[FAILOVER] Ping timeout: {url}")
            return False
        except requests.exceptions.ConnectionError:
            log.debug(f"[FAILOVER] Ping bağlantı hatası: {url}")
            return False
        except requests.exceptions.RequestException as e:
            log.debug(f"[FAILOVER] Ping istek hatası {url}: {e}")
            return False

    def _health_loop(self):
        while self._running:
            try:
                primary_ok = self._saglik_kontrol(self._primary)
                self._saglik["primary"] = primary_ok

                if not primary_ok and self._aktif == self._primary:
                    self._failover()
                elif primary_ok and self._aktif == self._backup:
                    if time.time() - self._son_hata > self.RECOVERY_CHECK:
                        self._recover()

                if self._backup:
                    self._saglik["backup"] = self._saglik_kontrol(self._backup)

            except threading.ThreadError as e:
                log.error(f"[FAILOVER] Thread hatası: {e}")
            time.sleep(self.HEALTH_CHECK_INTERVAL)

    @property
    def durum(self) -> dict:
        return {"aktif_url": self._aktif,
                "primary_ok": self._saglik["primary"],
                "backup_ok":  self._saglik.get("backup", True),
                "failover_on": self._aktif != self._primary,
                "hata_sayisi": self._hata_sayisi}

_failover_instance: Optional[ExchangeFailover] = None

def get_failover(otomatik_baslat: bool = False) -> ExchangeFailover:
    global _failover_instance
    if _failover_instance is None:
        _failover_instance = ExchangeFailover()
        if otomatik_baslat:
            _failover_instance.start()
    return _failover_instance
