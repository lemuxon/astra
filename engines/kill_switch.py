# =========================================================
# ASTRA v30.0 — HARD KILL SWITCH
# Production-grade trading halt sistemi
# =========================================================
import logging, time, threading
from datetime import date, datetime
from dataclasses import dataclass, field
from typing import Optional, Callable
import sys; sys.path.append("..")

log = logging.getLogger("ASTRA.KILLSWITCH")

@dataclass
class KillReason:
    kod:     str
    mesaj:   str
    ts:      float = field(default_factory=time.time)
    kritik:  bool  = False

class HardKillSwitch:
    """
    Çoklu tetikleyicili katı işlem durdurma sistemi.
    Bir kez tetiklenince manuel reset gerekir (güvenlik).
    """
    def __init__(self,
                 max_consecutive_loss: int   = 5,
                 max_drawdown_pct: float      = 15.0,
                 max_api_errors: int          = 10,
                 max_ws_disconnects: int      = 5,
                 max_slippage_pct: float       = 1.0,
                 telegram_fn: Optional[Callable] = None):

        self._aktif          = True   # True = işlem açık
        self._kill_sebepleri: list[KillReason] = []
        self._lock           = threading.Lock()
        self._telegram       = telegram_fn

        # Sayaçlar
        self._consecutive_loss  = 0
        self._api_hata_sayisi   = 0
        self._ws_disconnect     = 0
        self._son_slippage      = 0.0
        self._gunluk_islem      = 0
        self._son_gun           = date.today()

        # Limitler
        self.MAX_CONSECUTIVE_LOSS = max_consecutive_loss
        self.MAX_DRAWDOWN_PCT     = max_drawdown_pct
        self.MAX_API_ERRORS       = max_api_errors
        self.MAX_WS_DISCONNECTS   = max_ws_disconnects
        self.MAX_SLIPPAGE_PCT     = max_slippage_pct

        log.info(f"[KILLSWITCH] Başlatıldı — "
                 f"MaxLoss:{max_consecutive_loss} "
                 f"MaxDD:{max_drawdown_pct}% "
                 f"MaxAPIErr:{max_api_errors}")

    def _gun_sifirla(self):
        bugun = date.today()
        if bugun != self._son_gun:
            self._api_hata_sayisi = 0
            self._ws_disconnect   = 0
            self._gunluk_islem    = 0
            self._son_gun         = bugun

    def _durdur(self, sebep: KillReason):
        with self._lock:
            if not self._aktif:
                return
            self._aktif = False
            self._kill_sebepleri.append(sebep)

        log.critical(f"[KILLSWITCH] 🛑 TİCARET DURDURULDU: {sebep.mesaj}")
        if self._telegram:
            try:
                self._telegram(
                    f"🛑 <b>HARD KILL SWITCH</b>\n"
                    f"Kod: {sebep.kod}\n"
                    f"Sebep: {sebep.mesaj}\n"
                    f"Zaman: {datetime.now().strftime('%H:%M:%S')}\n"
                    f"Manuel reset gerekli: /killswitch_reset",
                    tip="killswitch", force=True
                )
            except Exception: pass

    @property
    def aktif(self) -> bool:
        """True = işlem açılabilir, False = durduruldu."""
        return self._aktif

    def kontrol(self) -> bool:
        """İşlem açılabilir mi? False ise açma."""
        with self._lock:
            return self._aktif

    def trade_sonucu_bildir(self, kazandi: bool, pnl_usdt: float):
        """Her kapanan işlemden sonra çağır.

        v54 YARIŞ DURUMU DÜZELTMESİ: Sayaç artışı lock ALTINDA yapılır.
        Eskiden `self._consecutive_loss += 1` lock'suzdu; pozisyonlar
        farklı thread'lerde kapandığı için iki eşzamanlı kayıp bildirimi
        sayacı bozabiliyordu (5 kayıp olmasına rağmen sayaç 4'te kalıp
        kill switch TETİKLENMEYEBİLİRDİ). Kill switch son savunma hattı
        olduğu için sayacın güvenilirliği kritiktir."""
        self._gun_sifirla()
        tetikle = None
        with self._lock:
            if kazandi:
                self._consecutive_loss = 0
            else:
                self._consecutive_loss += 1
                if self._consecutive_loss >= self.MAX_CONSECUTIVE_LOSS:
                    tetikle = KillReason(
                        "CONSECUTIVE_LOSS",
                        f"Ard arda {self._consecutive_loss} kayıp",
                        kritik=True
                    )
        # _durdur kendi lock'unu alır → deadlock olmaması için dışarıda çağrılır
        if tetikle:
            self._durdur(tetikle)

    def drawdown_bildir(self, dd_pct: float):
        """Risk manager'dan drawdown %'si al."""
        if dd_pct >= self.MAX_DRAWDOWN_PCT:
            self._durdur(KillReason(
                "MAX_DRAWDOWN",
                f"Drawdown %{dd_pct:.1f} >= limit %{self.MAX_DRAWDOWN_PCT}",
                kritik=True
            ))

    def api_hatasi_bildir(self):
        """Binance API hatası her gerçekleştiğinde çağır.
        v54: Sayaç lock altında (yarış durumu düzeltmesi)."""
        self._gun_sifirla()
        tetikle = None
        with self._lock:
            self._api_hata_sayisi += 1
            if self._api_hata_sayisi >= self.MAX_API_ERRORS:
                tetikle = KillReason(
                    "MAX_API_ERRORS",
                    f"API hata sayısı {self._api_hata_sayisi} >= {self.MAX_API_ERRORS}",
                    kritik=False
                )
        if tetikle:
            self._durdur(tetikle)

    def ws_disconnect_bildir(self):
        """WebSocket kopunca çağır.
        v54: Sayaç lock altında (yarış durumu düzeltmesi)."""
        self._gun_sifirla()
        tetikle = None
        with self._lock:
            self._ws_disconnect += 1
            _mevcut = self._ws_disconnect
            if self._ws_disconnect >= self.MAX_WS_DISCONNECTS:
                tetikle = KillReason(
                    "WS_DISCONNECTS",
                    f"WebSocket {self._ws_disconnect} kez koptu",
                    kritik=False
                )
        log.warning(f"[KILLSWITCH] WS disconnect #{_mevcut}/{self.MAX_WS_DISCONNECTS}")
        if tetikle:
            self._durdur(tetikle)

    def slippage_bildir(self, slippage_pct: float, sembol: str):
        """Gerçekleşen slippage yüksekse bildir."""
        self._son_slippage = slippage_pct
        if slippage_pct > self.MAX_SLIPPAGE_PCT:
            log.warning(f"[KILLSWITCH] Yüksek slippage {sembol}: %{slippage_pct:.3f}")
            # Slippage için sadece uyarı, tam durdurma yok

    def manuel_durdur(self, sebep: str = "Manuel"):
        """Telegram komutundan veya koddan manuel durdur."""
        self._durdur(KillReason("MANUEL", sebep, kritik=False))

    def reset(self, sebep: str = "Manuel"):
        """Manuel reset — tüm sayaçları sıfırlar."""
        with self._lock:
            self._aktif            = True
            self._consecutive_loss = 0
            self._api_hata_sayisi  = 0
            self._ws_disconnect    = 0
            self._son_slippage     = 0.0
            self._kill_sebepleri.clear()
        log.info("[KILLSWITCH] ✅ Reset edildi — işlem tekrar aktif")
        if self._telegram:
            try:
                self._telegram("✅ <b>KILL SWITCH RESET</b>\nİşlemler tekrar aktif.",
                               tip="killswitch", force=True)
            except Exception: pass

    @property
    def durum(self) -> dict:
        return {
            "aktif":             self._aktif,
            "consecutive_loss":  self._consecutive_loss,
            "api_hata":          self._api_hata_sayisi,
            "ws_disconnect":     self._ws_disconnect,
            "son_slippage_pct":  self._son_slippage,
            "kill_sebepleri":    [{"kod": k.kod, "mesaj": k.mesaj}
                                  for k in self._kill_sebepleri[-5:]],
        }

    def telegram_raporu(self) -> str:
        d = self.durum
        durum_str = "✅ AKTİF" if d["aktif"] else "🛑 DURDURULDU"
        return (
            f"🔒 <b>KILL SWITCH</b> {durum_str}\n"
            f"Ard arda kayıp: {d['consecutive_loss']}/{self.MAX_CONSECUTIVE_LOSS}\n"
            f"API hata: {d['api_hata']}/{self.MAX_API_ERRORS}\n"
            f"WS kopma: {d['ws_disconnect']}/{self.MAX_WS_DISCONNECTS}\n"
            f"Son slippage: %{d['son_slippage_pct']:.3f}"
        )


_instance: Optional[HardKillSwitch] = None
_instance_lock = threading.Lock()   # v55: singleton yarış koruması

def get_kill_switch(telegram_fn=None) -> HardKillSwitch:
    global _instance
    # v55: double-checked locking. Kill switch son savunma hattıdır; iki ayrı
    # örnek oluşması sayaçların BÖLÜNMESİ demektir (biri 3 kayıp, diğeri 2
    # kayıp sayar → hiçbiri limite ulaşmaz).
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                from config import (MAX_CONSECUTIVE_LOSS, MAX_DRAWDOWN_PCT_KILL,
                                    MAX_API_ERRORS_KILL, MAX_WS_DISCONNECTS,
                                    MAX_SLIPPAGE_PCT)
                _instance = HardKillSwitch(
                    max_consecutive_loss = MAX_CONSECUTIVE_LOSS,
                    max_drawdown_pct     = MAX_DRAWDOWN_PCT_KILL,
                    max_api_errors       = MAX_API_ERRORS_KILL,
                    max_ws_disconnects   = MAX_WS_DISCONNECTS,
                    max_slippage_pct     = MAX_SLIPPAGE_PCT,
                    telegram_fn          = telegram_fn,
                )
    return _instance
