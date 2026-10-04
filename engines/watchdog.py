# =========================================================
# ASTRA v30.0 — WATCHDOG (Auto-restart & Health Monitor)
# Ana döngü donarsa sistemi yeniden başlatır.
# Kritik hataları Telegram'a bildirir.
# =========================================================
import logging, time, threading, os, signal, sys
from datetime import datetime, timezone
from typing import Optional, Callable
import requests

log = logging.getLogger("ASTRA.WATCHDOG")

class Watchdog:
    """
    Sistemin canlılığını izler.
    - Her N saniyede 'heartbeat' alınmazsa alarm verir
    - Kritik exception'larda Telegram bildirir
    - Opsiyonel: process'i yeniden başlatır (systemd ile kullanım)
    """

    def __init__(self, max_silent: int = 300,
                 check_interval: int = 60,
                 telegram_fn: Callable = None):
        self._son_heartbeat  = time.time()
        self._max_silent     = max_silent     # bu kadar sessiz kalırsa alarm
        self._check_interval = check_interval
        self._telegram       = telegram_fn
        self._running        = False
        self._thread: Optional[threading.Thread] = None
        self._uyari_sayisi   = 0
        self._kritik_hatalar: list = []

    def heartbeat(self, kaynak: str = ""):
        """Her başarılı döngüde çağrılır."""
        self._son_heartbeat = time.time()
        if self._uyari_sayisi > 0:
            log.info(f"[WATCHDOG] Sistem normal, uyarı sıfırlandı (kaynak={kaynak})")
            self._uyari_sayisi = 0

    def hata_bildir(self, hata: Exception, kaynak: str = "", kritik: bool = False):
        """Exception yakalandığında çağrılır."""
        mesaj = f"{'🚨 KRİTİK' if kritik else '⚠️ HATA'}: {kaynak}\n{type(hata).__name__}: {hata}"
        log.error(f"[WATCHDOG] {mesaj}")
        self._kritik_hatalar.append({
            "ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "kaynak": kaynak,
            "hata": str(hata),
            "tip": type(hata).__name__,
            "kritik": kritik
        })
        if len(self._kritik_hatalar) > 100:
            self._kritik_hatalar = self._kritik_hatalar[-100:]

        if kritik and self._telegram:
            try:
                self._telegram(mesaj)
            except (OSError, ValueError, RuntimeError):
                pass   # Telegram gönderilemezse log'a zaten yazdı

    def start(self):
        # v29: çift başlatma koruması
        if getattr(self, "_thread", None) and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="AstraWatchdog"
        )
        self._thread.start()
        log.info(f"[WATCHDOG] Başlatıldı (max_silent={self._max_silent}s)")

    def stop(self):
        self._running = False

    # v57: Bir tik bu katsayıdan uzun sürdüyse sistem askıya alınmış demektir.
    # Normal jitter saniyeler mertebesinde; uyku saatler. Aradaki uçurum
    # ayrımı güvenli kılıyor.
    ASKIYA_ALMA_KATSAYI = 3

    def _loop(self):
        onceki_tik = time.time()
        while self._running:
            time.sleep(self._check_interval)
            simdi     = time.time()
            tik_gecen = simdi - onceki_tik
            onceki_tik = simdi

            # ── v57: UYKU / HAZIRDA BEKLETME TESPİTİ ─────────────
            # Watchdog duvar saati sessizliğini ölçüyordu ve "thread dondu"
            # ile "makine uyudu"yu AYIRT EDEMİYORDU.
            #
            # Ölçülen vaka (2026-08-24): laptop 22s 24dk uyudu, uyanınca
            # watchdog "80678s sessiz" diye CRITICAL alarm + Telegram
            # bildirimi üretti. Bot donmamıştı; 25 saniye sonra normale döndü.
            #
            # İki ayrı zarar:
            #   1. Her sabah sahte CRITICAL alarm → kullanıcı watchdog
            #      alarmlarını ciddiye almamayı öğrenir, GERÇEK donma kaçar.
            #   2. 3 alarm sonrası aşağıdaki SIGTERM yolu botu ÖLDÜRÜR.
            #      Uyanış 3 dakikadan uzun sürerse (yavaş ağ, model yükleme)
            #      bot kendini kapatır. Windows'ta systemd yok; geri gelmesi
            #      zamanlanmış göreve kalır (10 dk'ya kadar veri kaybı).
            #
            # AYRIM: Gerçek donmada watchdog thread'i tıklamaya DEVAM eder
            # (tik_gecen ≈ check_interval) ama heartbeat eskir. Askıya almada
            # time.sleep() duvar saatinde saatlerce sürer → tik_gecen patlar.
            # Bu imza kesin ve birbirine karışmaz.
            if tik_gecen > self._check_interval * self.ASKIYA_ALMA_KATSAYI:
                log.warning(
                    f"[WATCHDOG] Sistem askıya alınmış görünüyor: tek tik "
                    f"{tik_gecen:.0f}s sürdü (beklenen ~{self._check_interval}s). "
                    f"Heartbeat sayacı sıfırlanıyor — alarm VERİLMİYOR, "
                    f"bu bir donma değil."
                )
                self._son_heartbeat = simdi
                self._uyari_sayisi  = 0
                continue

            gecen = simdi - self._son_heartbeat

            if gecen > self._max_silent:
                self._uyari_sayisi += 1
                uyari_mesaj = (
                    f"🚨 <b>WATCHDOG ALARMI</b>\n"
                    f"Son heartbeat: {gecen:.0f}s önce\n"
                    f"Uyarı #{self._uyari_sayisi}\n"
                    f"systemd restart bekleniyor..."
                )
                log.critical(f"[WATCHDOG] ALARM! {gecen:.0f}s sessiz")

                # v42 TEŞHİS: Alarm anında TÜM thread'lerin ne yaptığını logla.
                # Bu, "hangi işlem takıldı" sorusunu kesin cevaplar.
                try:
                    self._thread_dump_logla(gecen)
                except Exception as _e:
                    log.error(f"[WATCHDOG] Thread dump hatası: {_e}")

                if self._telegram:
                    try:
                        self._telegram(uyari_mesaj)
                    except (OSError, ValueError, RuntimeError):
                        pass

                # systemd "Restart=always" kullandığı için
                # process'i öldürmek yeterli — systemd yeniden başlatır
                if self._uyari_sayisi >= 3:
                    log.critical("[WATCHDOG] 3 uyarı → process yeniden başlatılıyor")
                    os.kill(os.getpid(), signal.SIGTERM)

            elif gecen > self._max_silent * 0.7:
                log.warning(f"[WATCHDOG] Uyarı: {gecen:.0f}s heartbeat yok")

    def _thread_dump_logla(self, gecen: float):
        """v42: Alarm anında tüm thread'lerin stack trace'ini logla.
        'Hangi işlem takıldı' sorusunu kesin cevaplar — özellikle ana
        döngünün hangi satırda/ağ çağrısında asılı kaldığını gösterir."""
        import sys
        import traceback
        import threading as _th
        cerceveler = sys._current_frames()
        thread_isimleri = {t.ident: t.name for t in _th.enumerate()}
        log.critical("=" * 60)
        log.critical(f"[WATCHDOG TEŞHİS] {gecen:.0f}s donma — thread durumları:")
        for tid, cerceve in cerceveler.items():
            isim = thread_isimleri.get(tid, f"thread-{tid}")
            # Sadece ana döngü ve işçi thread'lerini detaylı göster
            yigin = traceback.extract_stack(cerceve)
            if yigin:
                son = yigin[-1]   # en üstteki (o an çalışan) satır
                # v55: os.path.basename — eskiden split('/') kullanılıyordu,
                # Windows'ta ters bölü nedeniyle tam yol basılıyordu.
                log.critical(f"  [{isim}] {os.path.basename(son.filename)}:"
                             f"{son.lineno} içinde '{son.name}' → {son.line}")
        log.critical("=" * 60)
        log.critical("[WATCHDOG TEŞHİS] Yukarıdaki satırlardan hangi thread'in "
                     "takıldığı görülür. Genelde bir ağ çağrısı (requests.get) "
                     "veya kilit (lock) beklemesidir.")

    @property
    def durum(self) -> dict:
        gecen = time.time() - self._son_heartbeat
        return {
            "son_heartbeat_once": f"{gecen:.0f}s",
            "saglikli": gecen < self._max_silent,
            "uyari_sayisi": self._uyari_sayisi,
            "kritik_hata_sayisi": len(self._kritik_hatalar),
            "son_hatalar": self._kritik_hatalar[-5:],
        }

# Singleton
_watchdog_instance: Optional[Watchdog] = None

def get_watchdog(telegram_fn: Callable = None) -> Watchdog:
    global _watchdog_instance
    if _watchdog_instance is None:
        from config import WATCHDOG_INTERVAL, WATCHDOG_MAX_SILENT, SCAN_INTERVAL, COINS
        # WATCHDOG_MAX_SILENT en az SCAN_INTERVAL + (coin sayısı * 45s analiz) kadar olmalı
        # Aksi halde normal çalışmada bile alarm verir
        min_silent = SCAN_INTERVAL + len(COINS) * 45 + 60  # buffer
        effective_silent = max(WATCHDOG_MAX_SILENT, min_silent)
        if effective_silent > WATCHDOG_MAX_SILENT:
            log.warning(f"[WATCHDOG] WATCHDOG_MAX_SILENT={WATCHDOG_MAX_SILENT}s yetersiz, "
                        f"{effective_silent}s'ye ayarlandı (SCAN={SCAN_INTERVAL}s, {len(COINS)} coin)")
        _watchdog_instance = Watchdog(
            max_silent=effective_silent,
            check_interval=WATCHDOG_INTERVAL,
            telegram_fn=telegram_fn
        )
        _watchdog_instance.start()
    return _watchdog_instance
