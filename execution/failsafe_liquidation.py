# =========================================================
# ASTRA v30.0 — FAIL-SAFE LIQUIDATION GUARD
# Spesifik exception tipleri kullanılıyor
# =========================================================
import logging, threading, time
from typing import Optional
import sys; sys.path.append("..")
from engines.event_bus import get_bus, Event
from utils.exceptions import (FatalExchangeError, RetryableExchangeError,
                                NetworkError, LiquidationRiskError)

log = logging.getLogger("ASTRA.FAILSAFE_LIQ")

FAILSAFE_THRESHOLD_PCT = 6.0
EMERGENCY_THRESHOLD_PCT= 3.0
CHECK_INTERVAL         = 15


def likidasyon_fiyati(poz: dict) -> float:
    """v55: Likidasyon fiyatını belirler.

    ÖNCELİK 1 — Binance'in kendi `liquidationPrice` değeri (positionRisk
      yanıtından gelir). Kademeli maintenance-margin oranlarını, cross-margin
      paylaşımını ve gerçekleşmiş PnL'i doğru hesaba katan TEK kaynak budur.
    ÖNCELİK 2 — Borsa değeri yoksa (0/None) elle yaklaşım. Bu yaklaşım
      maintenance-margin kademelerini yok sayar; yalnızca fallback'tir.

    Bu fonksiyon eskiden üç ayrı dosyada (failsafe_liquidation, state_audit,
    risk_manager) birbirinden bağımsız kopyalanmıştı — sessizce birbirinden
    sapma riski taşıyordu. Tek kaynağa indirildi.
    """
    borsa = float(poz.get("likidasyon_fiyat", 0) or 0)
    if borsa > 0:
        return borsa

    giris    = float(poz.get("giris", 0) or 0)
    kaldirac = int(poz.get("kaldirac", 0) or 0)
    if giris <= 0 or kaldirac <= 0:
        return 0.0
    if str(poz.get("yon", "")).upper() == "LONG":
        return giris * (1 - 1/kaldirac + 0.004)
    return giris * (1 + 1/kaldirac - 0.004)

class FailsafeLiquidationGuard:
    def __init__(self):
        self._bus     = get_bus()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._kapatilan: dict = {}
        self._KAPATMA_COOLDOWN = 300
        self._istatistik = {"kontrol_sayisi":0,"uyari_sayisi":0,
                             "failsafe_kapatma":0,"acil_kapatma":0,
                             "son_kontrol_ts":0.0}

    def start(self):
        # v29: çift başlatma koruması
        if getattr(self, "_thread", None) and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="AstraFailsafeLiq")
        self._thread.start()
        log.info(f"[FAILSAFE] Başlatıldı — %{FAILSAFE_THRESHOLD_PCT} / %{EMERGENCY_THRESHOLD_PCT}")

    def stop(self):
        self._running = False

    def _loop(self):
        # v55 KRİTİK: Bu döngü ASLA ölmemeli. Eskiden yalnızca 4 istisna tipi
        # yakalanıyordu; bunların dışında bir hata (örn. kaldirac=0 →
        # ZeroDivisionError, ya da beklenmedik API yanıtı → KeyError) daemon
        # thread'ini sonlandırıyordu. Python daemon thread'i yeniden başlatmaz:
        # likidasyon koruması sessizce ve KALICI olarak ölüyor, bot ise
        # korunuyormuş gibi çalışmaya devam ediyordu.
        while self._running:
            try:
                self._kontrol()
                self._istatistik["son_kontrol_ts"] = time.time()
            except (FatalExchangeError, RetryableExchangeError) as e:
                log.error(f"[FAILSAFE] Exchange hatası: {e}")
            except NetworkError as e:
                log.warning(f"[FAILSAFE] Ağ hatası (sonraki döngüde tekrar): {e}")
            except threading.ThreadError as e:
                log.critical(f"[FAILSAFE] Thread hatası: {e}")
            except Exception as e:
                log.critical(f"[FAILSAFE] Beklenmedik hata (thread YAŞIYOR): "
                             f"{type(e).__name__}: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL)

    def saglikli_mi(self, max_sessizlik_s: float = None) -> bool:
        """v55: Dışarıdan liveness kontrolü. Döngü çalışıyor ve son kontrol
        makul süre önce yapıldıysa True. state_audit/watchdog bunu kullanabilir."""
        if max_sessizlik_s is None:
            max_sessizlik_s = CHECK_INTERVAL * 5
        t = self._thread if getattr(self, "_thread", None) else None
        if not (t and t.is_alive()):
            return False
        son = self._istatistik.get("son_kontrol_ts", 0)
        return son > 0 and (time.time() - son) <= max_sessizlik_s

    def _kontrol(self):
        from data.binance_futures_client import (
            acik_futures_pozisyonlar, futures_anlık_fiyat)

        pozlar = acik_futures_pozisyonlar()
        if not pozlar: return

        self._istatistik["kontrol_sayisi"] += 1

        for poz in pozlar:
            sembol   = poz.get("sembol")
            yon      = poz.get("yon")
            giris    = float(poz.get("giris", 0) or 0)

            if not sembol or giris <= 0: continue

            guncel = futures_anlık_fiyat(sembol)
            if not guncel or guncel <= 0: continue

            # v55: Borsanın kendi likidasyon fiyatı (varsa) kullanılır.
            likit = likidasyon_fiyati(poz)
            if likit <= 0:
                log.warning(f"[FAILSAFE] {sembol} likidasyon fiyatı belirlenemedi — atlandı")
                continue

            if yon == "LONG":
                uzaklik = (guncel - likit) / guncel * 100
            else:
                uzaklik = (likit - guncel) / guncel * 100

            if uzaklik <= EMERGENCY_THRESHOLD_PCT:
                log.critical(f"[FAILSAFE] 🚨 ACİL: {sembol} {yon} uzaklık %{uzaklik:.2f}")
                self._zorla_kapat(sembol, yon, guncel, likit, uzaklik, acil=True)
            elif uzaklik <= FAILSAFE_THRESHOLD_PCT:
                # v57: koşullu emirler Algo Service'e taşındı; klasik
                # openOrders listesinde GÖRÜNMÜYOR. koruma_emirleri()
                # iki kaynağı birleştirir. Eskisi kullanılsaydı SL hep
                # "yok" görünüp pozisyon gereksiz yere kapatılırdı.
                from data.binance_futures_client import koruma_emirleri
                try:
                    acik_emirler = koruma_emirleri(sembol, strict=True)
                    sl_side = "SELL" if yon=="LONG" else "BUY"
                    sl_var  = any(e.get("type") in ("STOP_MARKET","STOP",
                                                    "TRAILING_STOP_MARKET")
                                  and e.get("side")==sl_side
                                  for e in acik_emirler)
                except (FatalExchangeError, RetryableExchangeError, NetworkError):
                    sl_var = False   # Bilinemiyor — güvenli tarafı seç

                if not sl_var:
                    log.critical(f"[FAILSAFE] SL YOK + yakın: {sembol} %{uzaklik:.2f}")
                    self._zorla_kapat(sembol, yon, guncel, likit, uzaklik, acil=False)
                else:
                    log.warning(f"[FAILSAFE] ⚠️ {sembol} {yon} %{uzaklik:.2f} (SL mevcut)")
                    self._istatistik["uyari_sayisi"] += 1
                    self._bus.publish(Event.ALERT, {
                        "mesaj": f"⚠️ {sembol} {yon} likidasyon %{uzaklik:.2f} uzaklık"
                    }, "FailsafeLiq")

    def _zorla_kapat(self, sembol, yon, guncel, likit, uzaklik, acil):
        if time.time() - self._kapatilan.get(sembol, 0) < self._KAPATMA_COOLDOWN:
            return

        from data.binance_futures_client import futures_market_kapat

        self._bus.publish(Event.ALERT, {
            "mesaj": (f"{'🚨 ACİL' if acil else '🛡️ FAILSAFE'}: "
                      f"{sembol} {yon} uzaklık %{uzaklik:.2f}")
        }, "FailsafeLiq")

        try:
            order = futures_market_kapat(sembol, yon)
            if order and order.get("orderId"):
                log.info(f"[FAILSAFE] ✅ {sembol} {yon} kapatıldı")
                self._kapatilan[sembol] = time.time()
                self._istatistik["acil_kapatma" if acil else "failsafe_kapatma"] += 1
                self._bus.publish(Event.POSITION_CLOSED,
                                  {"sembol":sembol,"yon":yon,
                                   "sebep":"EMERGENCY_LIQ" if acil else "FAILSAFE_LIQ",
                                   "uzaklik":uzaklik}, "FailsafeLiq")
            else:
                log.critical(f"[FAILSAFE] ❌ {sembol} kapatma başarısız — MANUEL MÜDAHALE!")
                self._bus.publish(Event.ALERT,
                                  {"mesaj": f"🚨 {sembol} kapatılamadı — MANUEL!"}, "FailsafeLiq")

        except FatalExchangeError as e:
            log.critical(f"[FAILSAFE] {sembol} fatal API hatası: {e} — MANUEL MÜDAHALE!")
        except (RetryableExchangeError, NetworkError) as e:
            log.critical(f"[FAILSAFE] {sembol} geçici hata, retry yok (acil): {e}")

    @property
    def istatistik(self) -> dict:
        return dict(self._istatistik)

    def telegram_raporu(self) -> str:
        s = self._istatistik
        return (f"🛡️ <b>FAILSAFE GUARD</b>\n"
                f"Kontrol:{s['kontrol_sayisi']} Uyarı:{s['uyari_sayisi']}\n"
                f"Failsafe:{s['failsafe_kapatma']} Acil:{s['acil_kapatma']}")

_guard_instance: Optional[FailsafeLiquidationGuard] = None

def get_failsafe_guard(otomatik_baslat: bool = False) -> FailsafeLiquidationGuard:
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = FailsafeLiquidationGuard()
        if otomatik_baslat:
            _guard_instance.start()
    return _guard_instance
