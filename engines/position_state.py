# =========================================================
# ASTRA v30.0 — PERSISTENT POSITION STATE
# Pozisyon durumu JSON'a yazılır.
# Reconnect/restart sonrası Binance'le sync edilir.
# Orphan SL/TP emirleri temizlenir.
# =========================================================
import json, logging, time, threading, os
from datetime import datetime, timezone
from typing import Optional
import sys; sys.path.append("..")
from config import STATE_FILE, STATE_SYNC_INTERVAL, ORPHAN_CHECK_INTERVAL
from engines.event_bus import get_bus, Event

log = logging.getLogger("ASTRA.POSITION_STATE")

class PositionStateManager:
    """
    Kalıcı pozisyon durumu yöneticisi.
    - JSON dosyasına yazar (Redis opsiyonel)
    - Restart sonrası Binance'le karşılaştırır
    - Orphan emirleri temizler
    - State drift tespiti
    """

    def __init__(self):
        self._state: dict = {}       # {sembol: {"yon","giris","miktar","sl","tp1","ts"}}
        self._lock  = threading.Lock()
        self._bus   = get_bus()
        self._son_sync = 0
        self._dosya = STATE_FILE
        os.makedirs(os.path.dirname(self._dosya) if os.path.dirname(self._dosya) else ".", exist_ok=True)
        self._yukle()

    def _yukle(self):
        """Disk'ten önceki durumu yükle."""
        if not os.path.exists(self._dosya):
            log.info("[STATE] Durum dosyası yok, temiz başlangıç")
            return
        try:
            with open(self._dosya, "r", encoding="utf-8") as f:
                self._state = json.load(f)
            log.info(f"[STATE] {len(self._state)} pozisyon yüklendi: {list(self._state.keys())}")
        except json.JSONDecodeError as e:
            log.error(f"[STATE] Bozuk durum dosyası: {e} — sıfırlanıyor")
            self._state = {}
        except OSError as e:
            log.error(f"[STATE] Dosya okuma hatası: {e}")
            self._state = {}

    def _kaydet(self):
        """Mevcut durumu diske yaz (atomik)."""
        tmp = self._dosya + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, self._dosya)  # atomik rename
        except OSError as e:
            log.error(f"[STATE] Dosya yazma hatası: {e}")

    def pozisyon_ac(self, sembol: str, yon: str, giris: float,
                     miktar: float, sl: float, tp1: float,
                     kaldirac: int = 5, order_id: str = ""):
        """Yeni pozisyonu kaydet."""
        with self._lock:
            self._state[sembol] = {
                "sembol":   sembol,
                "yon":      yon,
                "giris":    giris,
                "miktar":   miktar,
                "sl":       sl,
                "tp1":      tp1,
                "kaldirac": kaldirac,
                "order_id": order_id,
                "acilis_ts":datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "sl_aktif": False,
                "tp1_aktif":False,
            }
            self._kaydet()
            log.info(f"[STATE] Pozisyon eklendi: {sembol} {yon} @ {giris}")

    def pozisyon_kapat(self, sembol: str, sebep: str = ""):
        """Pozisyonu state'den sil."""
        with self._lock:
            if sembol in self._state:
                log.info(f"[STATE] Pozisyon kaldırıldı: {sembol} ({sebep})")
                del self._state[sembol]
                self._kaydet()

    def sl_aktif_isaretle(self, sembol: str, sl_order_id: str = ""):
        with self._lock:
            if sembol in self._state:
                self._state[sembol]["sl_aktif"]    = True
                self._state[sembol]["sl_order_id"] = sl_order_id
                self._kaydet()

    def tp1_aktif_isaretle(self, sembol: str, tp1_order_id: str = ""):
        with self._lock:
            if sembol in self._state:
                self._state[sembol]["tp1_aktif"]    = True
                self._state[sembol]["tp1_order_id"] = tp1_order_id
                self._kaydet()

    def acik_pozisyonlar(self) -> list:
        with self._lock:
            return list(self._state.values())

    def pozisyon_var_mi(self, sembol: str) -> bool:
        with self._lock:
            return sembol in self._state

    def binance_ile_sync(self):
        """
        Binance'teki gerçek pozisyonlarla state'i karşılaştır.
        State'de var ama Binance'te yok → state'den sil (SL/TP kapattı)
        Binance'te var ama state'de yok → state'e ekle (orphan kurtarma)
        """
        from data.binance_futures_client import acik_futures_pozisyonlar
        log.info("[STATE] Binance ile sync başlıyor...")

        # v55 KRİTİK: strict=True olmadan ağ hatasında [] dönüyordu ve aşağıdaki
        # `kapatilanlar` listesi TÜM pozisyonları kapsıyordu → state komple
        # siliniyor, pozisyonlar borsada korumasız kalıyordu.
        try:
            binance_pozlar = acik_futures_pozisyonlar(strict=True)
        except Exception as e:
            log.error(f"[STATE] Binance sync için pozisyon alınamadı: {e} "
                      f"→ sync ATLANDI (state korundu)")
            return

        binance_semboller = {p["sembol"] for p in binance_pozlar}

        with self._lock:
            # State'de var, Binance'te yok → kapatıldı (SL veya TP)
            kapatilanlar = [s for s in list(self._state.keys())
                            if s not in binance_semboller]
            for sembol in kapatilanlar:
                log.info(f"[STATE SYNC] {sembol} Binance'te yok → state'den silindi (SL/TP kapattı?)")
                self._bus.publish(Event.POSITION_CLOSED,
                                  {"sembol": sembol, "sebep": "SYNC_ALGILADI"}, "StateSync")
                del self._state[sembol]

            # Binance'te var, state'de yok → orphan pozisyon kurtarma
            for poz in binance_pozlar:
                sembol = poz["sembol"]
                if sembol not in self._state:
                    log.warning(f"[STATE SYNC] ORPHAN POZISYON ALGILANDI: {sembol} {poz['yon']} — state'e ekleniyor")
                    self._state[sembol] = {
                        "sembol":    sembol,
                        "yon":       poz["yon"],
                        "giris":     poz["giris"],
                        "miktar":    abs(poz["miktar"]),
                        "sl":        0,
                        "tp1":       0,
                        "kaldirac":  poz.get("kaldirac", 5),
                        "order_id":  "ORPHAN",
                        "acilis_ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                        "sl_aktif":  False,
                        "tp1_aktif": False,
                    }
                    self._bus.publish(Event.ALERT,
                                      {"mesaj": f"ORPHAN POZISYON: {sembol} {poz['yon']}"}, "StateSync")

            self._kaydet()
        log.info(f"[STATE SYNC] Tamamlandı: {len(self._state)} aktif pozisyon")

    def orphan_sl_tp_temizle(self):
        """
        Pozisyonu olmayan SL/TP emirlerini (orphan) Binance'ten iptal eder.
        Bu emirler pozisyon kapandıktan sonra çalışmayan açık emirler olabilir.
        """
        # v57: koşullu emirler Algo Service'te; klasik openOrders listesinde
        # görünmüyor. Eskisi kullanılsaydı orphan SL/TP'ler HİÇ TEMİZLENMEZ,
        # borsada birikirdi.
        from data.binance_futures_client import (koruma_emirleri,
                                                  futures_emir_iptal,
                                                  algo_emir_iptal,
                                                  acik_futures_pozisyonlar)
        log.info("[ORPHAN CHECK] Orphan SL/TP kontrolü başlıyor...")

        try:
            acik_emirler  = koruma_emirleri(strict=True)
            acik_pozisyon_semboller = {p["sembol"] for p in acik_futures_pozisyonlar()}
        except Exception as e:
            log.error(f"[ORPHAN CHECK] Veri alınamadı: {e}")
            return

        orphan_tipler = {"STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT",
                         "TRAILING_STOP_MARKET"}
        iptal_sayisi  = 0

        for emir in acik_emirler:
            sembol     = emir.get("symbol","")
            emir_tipi  = emir.get("type","")
            order_id   = emir.get("orderId")

            if emir_tipi in orphan_tipler and sembol not in acik_pozisyon_semboller:
                _algo = emir.get("_algo", False)
                log.warning(f"[ORPHAN] {sembol} #{order_id} {emir_tipi} "
                            f"({'algo' if _algo else 'klasik'}) — pozisyon yok, "
                            f"iptal ediliyor")
                try:
                    # v57: algo emirleri DELETE /fapi/v1/algoOrder ile iptal
                    # edilir; klasik iptal yolu onları bulamaz.
                    if _algo:
                        algo_emir_iptal(sembol, order_id)
                    else:
                        futures_emir_iptal(sembol, order_id)
                    iptal_sayisi += 1
                except Exception as e:
                    log.error(f"[ORPHAN] #{order_id} iptal hatası: {e}")

        log.info(f"[ORPHAN CHECK] Tamamlandı: {iptal_sayisi} orphan emir iptal edildi")

    def sl_tp_dogrula(self):
        """
        State'deki her pozisyon için SL ve TP emirlerinin Binance'te aktif
        olup olmadığını doğrular. Kayıpsa yeniden koyar.
        """
        # v57: bkz. yukarıdaki not — koşullu emirler algo listesinde.
        from data.binance_futures_client import (koruma_emirleri,
                                                  futures_stop_loss_koy,
                                                  futures_partial_tp_koy,
                                                  futures_anlık_fiyat)
        log.info("[SL/TP VERIFY] Kontrol başlıyor...")

        with self._lock:
            pozisyon_listesi = list(self._state.values())

        for poz in pozisyon_listesi:
            sembol = poz["sembol"]
            yon    = poz["yon"]
            sl     = poz.get("sl", 0)
            tp1    = poz.get("tp1", 0)

            try:
                # strict=True: sorgulayamadıysak "SL yok" VARSAYMA.
                acik_emirler = koruma_emirleri(sembol, strict=True)
                # v55: TRAILING_STOP_MARKET de geçerli bir SL korumasıdır.
                # Chandelier mantığı tetiklendiğinde SL emri iptal edilip
                # TRAILING_STOP_MARKET konuyor; eski liste bunu tanımadığı için
                # "SL eksik" sanılıp pozisyon AÇILIŞINDAKİ bayat sl fiyatına
                # statik SL yeniden konuyordu (aktif trailing'den daha kötü
                # bir seviyede olabiliyor + yanlış "SL kayıptı" alarmı).
                sl_emirleri  = [e for e in acik_emirler
                                if e.get("type") in ("STOP_MARKET", "STOP",
                                                      "TRAILING_STOP_MARKET")]
                tp_emirleri  = [e for e in acik_emirler
                                if e.get("type") in ("TAKE_PROFIT_MARKET","TAKE_PROFIT")]

                # SL eksik mi?
                if not sl_emirleri and sl > 0:
                    log.warning(f"[SL/TP VERIFY] {sembol} SL eksik — yeniden koyuluyor @ {sl}")
                    futures_stop_loss_koy(sembol, yon, sl)
                    self._bus.publish(Event.ALERT,
                                      {"mesaj": f"{sembol} SL yeniden koyuldu @ {sl}"}, "SLTPVerify")

                # TP eksik mi?
                if not tp_emirleri and tp1 > 0:
                    log.warning(f"[SL/TP VERIFY] {sembol} TP eksik — yeniden koyuluyor @ {tp1}")
                    futures_partial_tp_koy(sembol, yon, tp1, 50)
                    self._bus.publish(Event.ALERT,
                                      {"mesaj": f"{sembol} TP yeniden koyuldu @ {tp1}"}, "SLTPVerify")

            except Exception as e:
                log.error(f"[SL/TP VERIFY] {sembol} kontrol hatası: {e}")

    def periyodik_sync_baslat(self):
        """Arka planda periyodik sync ve orphan check."""
        # v55: ORPHAN_CHECK_INTERVAL < STATE_SYNC_INTERVAL yanlış yapılandırmasında
        # time.sleep() negatif değerle ValueError fırlatıyor, dış except onu
        # yakalıyor ve döngü GECİKMESİZ yeniden deniyordu → Binance API'yi döven
        # sıkı döngü. max(1, ...) ile tabanlandı.
        _orphan_bekleme = max(1, ORPHAN_CHECK_INTERVAL - STATE_SYNC_INTERVAL)

        def _loop():
            while True:
                try:
                    time.sleep(STATE_SYNC_INTERVAL)
                    self.binance_ile_sync()
                    time.sleep(_orphan_bekleme)
                    self.orphan_sl_tp_temizle()
                    self.sl_tp_dogrula()
                except Exception as e:
                    log.error(f"[STATE] Periyodik sync hatası: {e}")
                    time.sleep(5)   # v55: hata döngüsünde nefes payı
        t = threading.Thread(target=_loop, daemon=True, name="AstraStateSync")
        t.start()
        log.info(f"[STATE] Periyodik sync başlatıldı (her {STATE_SYNC_INTERVAL}s)")

# Singleton
_state_manager: Optional[PositionStateManager] = None
_state_manager_lock = threading.Lock()   # v55: singleton yarış koruması

def get_state_manager(auto_sync: bool = False) -> PositionStateManager:
    """
    auto_sync=True sadece futures_dashboard() içinden çağrılır.
    Import sırasında ağ isteği yapılmaz.
    """
    global _state_manager
    # v55: double-checked locking — kilitsizken iki thread ayrı state manager
    # kurabiliyor, kaybeden örnek kendi periyodik sync thread'iyle öksüz
    # kalıyordu (aynı DB/dosyaya iki senkronizasyon döngüsü).
    if _state_manager is None:
        with _state_manager_lock:
            if _state_manager is None:
                _yeni = PositionStateManager()
                if auto_sync:
                    _yeni.binance_ile_sync()
                    _yeni.orphan_sl_tp_temizle()
                _yeni.periyodik_sync_baslat()
                _state_manager = _yeni
    return _state_manager
