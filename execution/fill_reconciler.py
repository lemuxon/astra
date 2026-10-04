# =========================================================
# ASTRA EXECUTION LAYER — FILL RECONCILER
# =========================================================
# Binance'in gerçek durumu ile bizim iç state'imizin
# sürekli senkronize olmasını sağlar.
#
# Çözdüğü sorunlar:
#   - Bizim state'de AÇIK ama Binance'te yok (SL/TP kapattı)
#   - Bizim state'de YOK ama Binance'te var (orphan pozisyon)
#   - SL emri kaybolmuş (pozisyon korumasız)
#   - TP emri kaybolmuş (kar fırsatı kaçar)
#   - State'deki miktar Binance miktarıyla uyuşmuyor
#   - Kısmi fill sonrası miktar tutarsızlığı
# =========================================================

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import sys
sys.path.append("..")
from config import STATE_SYNC_INTERVAL, ORPHAN_CHECK_INTERVAL
from engines.event_bus import get_bus, Event

log = logging.getLogger("ASTRA.FILL_RECONCILER")


@dataclass
class ReconcileUyumsuzluk:
    tip:     str    # "ORPHAN_POZ", "KAYIP_POZ", "MIKTAR_UYUMSUZ", "KAYIP_SL", "KAYIP_TP"
    sembol:  str
    detay:   str
    kritik:  bool


class FillReconciler:
    """
    Pozisyon ve emir durumunu Binance ile karşılaştırır.
    Her STATE_SYNC_INTERVAL saniyede arka planda çalışır.
    Uyumsuzluk bulursa hem düzeltir hem bildirir.
    """

    def __init__(self, state_manager, order_engine=None):
        self._state    = state_manager
        self._engine   = order_engine
        self._bus      = get_bus()
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._son_sync = 0
        self._son_orphan_check = 0
        self._istatistik = {
            "sync_sayisi":       0,
            "uyumsuzluk_toplam": 0,
            "duzeltme_toplam":   0,
            "orphan_iptal":      0,
            "sl_yeniden":        0,
            "tp_yeniden":        0,
        }

    def start(self):
        # v29: çift başlatma koruması
        if getattr(self, "_thread", None) and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="AstraFillReconciler"
        )
        self._thread.start()
        log.info(f"[RECONCILER] Başlatıldı — sync:{STATE_SYNC_INTERVAL}s "
                 f"orphan:{ORPHAN_CHECK_INTERVAL}s")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                now = time.time()

                if now - self._son_sync >= STATE_SYNC_INTERVAL:
                    self._pozisyon_sync()
                    self._son_sync = now

                if now - self._son_orphan_check >= ORPHAN_CHECK_INTERVAL:
                    self._orphan_emir_temizle()
                    self._sl_tp_dogrula()
                    self._son_orphan_check = now

            except Exception as e:
                log.error(f"[RECONCILER] Loop hatası: {type(e).__name__}: {e}",
                          exc_info=True)
            time.sleep(10)

    # ──────────────────────────────────────────────────────
    # POZISYON SYNC
    # ──────────────────────────────────────────────────────

    def _pozisyon_sync(self):
        """
        State ↔ Binance karşılaştırması.
        Her pozisyon için:
          - Var mı?
          - Miktar doğru mu?
          - Yön doğru mu?
        """
        from data.binance_futures_client import acik_futures_pozisyonlar

        # v55 KRİTİK: strict=True olmadan bu çağrı ağ hatasında [] dönüyordu ve
        # aşağıdaki döngü TÜM açık pozisyonları "Binance'te yok" sanıp state'ten
        # siliyordu. Pozisyonlar borsada canlı kalırken bot onları izlemeyi
        # bırakıyor, SL doğrulaması da devre dışı kalıyordu.
        try:
            binance_pozlar = acik_futures_pozisyonlar(strict=True)
        except Exception as e:
            log.error(f"[RECONCILER] Binance pozisyon listesi alınamadı: {e} "
                      f"→ sync ATLANDI (state korundu)")
            return

        self._istatistik["sync_sayisi"] += 1
        binance_map = {p["sembol"]: p for p in binance_pozlar}
        state_pozlar = self._state.acik_pozisyonlar()
        uyumsuzluklar = []

        # ── State'de var, Binance'te yok ──────────────────
        for poz in state_pozlar:
            sembol = poz["sembol"]
            if sembol not in binance_map:
                log.info(f"[RECONCILER] {sembol} state'de var, Binance'te yok → "
                         f"SL/TP kapattı veya manuel kapatıldı")
                self._state.pozisyon_kapat(sembol, "RECONCILER_SYNC")
                self._bus.publish(Event.POSITION_CLOSED, {
                    "sembol":    sembol,
                    "sebep":     "RECONCILER_ALGILADI",
                    "yon":       poz.get("yon", "?"),
                    "giris":     poz.get("giris", 0),
                }, "FillReconciler")
                uyumsuzluklar.append(ReconcileUyumsuzluk(
                    tip    = "KAYIP_POZ",
                    sembol = sembol,
                    detay  = "Binance'te pozisyon yok — state temizlendi",
                    kritik = False,
                ))
                continue

            # ── Miktar uyumsuzluğu ─────────────────────────
            binance_miktar = abs(binance_map[sembol]["miktar"])
            state_miktar   = abs(poz.get("miktar", 0))
            if state_miktar > 0:
                fark_pct = abs(binance_miktar - state_miktar) / state_miktar * 100
                if fark_pct > 5:  # %5'ten fazla fark varsa uyar
                    log.warning(f"[RECONCILER] {sembol} miktar uyumsuz: "
                                f"state={state_miktar} binance={binance_miktar} "
                                f"(fark %{fark_pct:.1f})")
                    # State'i Binance gerçeğiyle güncelle
                    with self._state._lock:
                        if sembol in self._state._state:
                            self._state._state[sembol]["miktar"] = binance_miktar
                            self._state._kaydet()
                    uyumsuzluklar.append(ReconcileUyumsuzluk(
                        tip    = "MIKTAR_UYUMSUZ",
                        sembol = sembol,
                        detay  = f"state={state_miktar:.4f} binance={binance_miktar:.4f}",
                        kritik = False,
                    ))

        # ── Binance'te var, state'de yok (orphan) ─────────
        state_semboller = {p["sembol"] for p in state_pozlar}
        for sembol, b_poz in binance_map.items():
            if sembol not in state_semboller:
                log.warning(f"[RECONCILER] 🚨 ORPHAN POZİSYON: {sembol} {b_poz['yon']} "
                             f"{b_poz['miktar']} @ {b_poz['giris']} — state'e ekleniyor")
                self._state.pozisyon_ac(
                    sembol   = sembol,
                    yon      = b_poz["yon"],
                    giris    = b_poz["giris"],
                    miktar   = abs(b_poz["miktar"]),
                    sl       = 0,   # bilinmiyor
                    tp1      = 0,
                    kaldirac = b_poz.get("kaldirac", 5),
                    order_id = "ORPHAN_KURTARILDI",
                )
                self._bus.publish(Event.ALERT, {
                    "mesaj": f"🚨 ORPHAN POZİSYON ALGILANDI: {sembol} {b_poz['yon']} "
                             f"@ {b_poz['giris']} — SL/TP manuel kontrol edin!"
                }, "FillReconciler")
                uyumsuzluklar.append(ReconcileUyumsuzluk(
                    tip    = "ORPHAN_POZ",
                    sembol = sembol,
                    detay  = f"Binance'te var, state'de yoktu — kurtarıldı",
                    kritik = True,
                ))

        if uyumsuzluklar:
            self._istatistik["uyumsuzluk_toplam"] += len(uyumsuzluklar)
            self._istatistik["duzeltme_toplam"]   += len(uyumsuzluklar)
            log.warning(f"[RECONCILER] {len(uyumsuzluklar)} uyumsuzluk düzeltildi")
        else:
            log.debug(f"[RECONCILER] Sync OK — {len(state_pozlar)} pozisyon uyumlu")

    # ──────────────────────────────────────────────────────
    # ORPHAN EMİR TEMİZLEME
    # ──────────────────────────────────────────────────────

    def _orphan_emir_temizle(self):
        """
        Pozisyonu kapanmış ama SL/TP emri hâlâ açık olan emirleri iptal eder.
        Bu, pozisyon SL/TP ile kapandıktan sonra kalan "ters" emirlerdir.
        """
        # v57: koşullu emirler Algo Service'te; klasik listede görünmez.
        from data.binance_futures_client import (
            koruma_emirleri, futures_emir_iptal, algo_emir_iptal,
            acik_futures_pozisyonlar
        )

        try:
            acik_emirler    = koruma_emirleri(strict=True)
            acik_poz_sembol = {p["sembol"] for p in acik_futures_pozisyonlar()}
        except Exception as e:
            log.error(f"[RECONCILER] Orphan check veri alınamadı: {e}")
            return

        KORUNAN_TIPLER = {
            "STOP_MARKET", "TAKE_PROFIT_MARKET",
            "STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET"
        }
        iptal_sayisi = 0

        for emir in acik_emirler:
            sembol    = emir.get("symbol", "")
            emir_tipi = emir.get("type", "")
            order_id  = emir.get("orderId")

            if emir_tipi in KORUNAN_TIPLER and sembol not in acik_poz_sembol:
                _algo = emir.get("_algo", False)
                log.warning(f"[RECONCILER] Orphan emir iptal: "
                             f"{sembol} #{order_id} {emir_tipi} "
                             f"({'algo' if _algo else 'klasik'})")
                try:
                    # v57: algo emirleri DELETE /fapi/v1/algoOrder ile iptal
                    # edilir. Klasik yol onları bulamaz → orphan SL/TP borsada
                    # birikir ve sonraki pozisyonu yanlış seviyeden kapatabilir.
                    if _algo:
                        algo_emir_iptal(sembol, order_id)
                    else:
                        futures_emir_iptal(sembol, order_id)
                    iptal_sayisi += 1
                    self._istatistik["orphan_iptal"] += 1
                except Exception as e:
                    log.error(f"[RECONCILER] #{order_id} iptal hatası: {e}")

        if iptal_sayisi:
            log.info(f"[RECONCILER] {iptal_sayisi} orphan emir iptal edildi")

    # ──────────────────────────────────────────────────────
    # SL / TP DOĞRULAMA VE YENİDEN KOYMA
    # ──────────────────────────────────────────────────────

    def _sl_tp_dogrula(self):
        """
        State'deki her açık pozisyon için:
        - SL emri Binance'te aktif mi?
        - TP emri Binance'te aktif mi?
        Değilse yeniden koyar.
        """
        from data.binance_futures_client import (
            koruma_emirleri, futures_stop_loss_koy,
            futures_partial_tp_koy, futures_anlık_fiyat, FuturesAPIError
        )
        from config import FUTURES_PARTIAL_TP_PCT, FUTURES_TRAILING_STOP

        state_pozlar = self._state.acik_pozisyonlar()
        if not state_pozlar:
            return

        log.debug(f"[RECONCILER] SL/TP doğrulama: {len(state_pozlar)} pozisyon")

        for poz in state_pozlar:
            sembol = poz["sembol"]
            yon    = poz["yon"]
            sl     = poz.get("sl", 0)
            tp1    = poz.get("tp1", 0)

            try:
                # strict=True: sorgulayamadıysak "SL yok" VARSAYMA.
                acik_emirler = koruma_emirleri(sembol, strict=True)
                sl_side      = "SELL" if yon == "LONG" else "BUY"
                tp_side      = sl_side

                sl_emirleri  = [e for e in acik_emirler
                                if e.get("type") in ("STOP_MARKET", "STOP",
                                                      "TRAILING_STOP_MARKET")
                                and e.get("side") == sl_side]
                tp_emirleri  = [e for e in acik_emirler
                                if e.get("type") in ("TAKE_PROFIT_MARKET",
                                                      "TAKE_PROFIT",
                                                      "TRAILING_STOP_MARKET")
                                and e.get("side") == tp_side]

                # ── SL eksik ──────────────────────────────
                if not sl_emirleri:
                    if sl > 0:
                        log.warning(f"[RECONCILER] ⚠️ {sembol} SL EKSİK @ {sl} — yeniden koyuluyor")
                        try:
                            futures_stop_loss_koy(sembol, yon, sl)
                            self._istatistik["sl_yeniden"] += 1
                            self._bus.publish(Event.ALERT, {
                                "mesaj": f"{sembol} SL eksikti, yeniden koyuldu @ {sl}"
                            }, "FillReconciler")
                        except FuturesAPIError as e:
                            log.critical(f"[RECONCILER] {sembol} SL YENİDEN KOYULAMADI: {e}")
                            self._bus.publish(Event.ALERT, {
                                "mesaj": f"🚨 {sembol} SL konamıyor! Manuel kontrol edin!"
                            }, "FillReconciler")
                    else:
                        # SL fiyatı bilinmiyor (orphan kurtarıldı) — ATR'den hesapla
                        log.warning(f"[RECONCILER] {sembol} SL fiyatı bilinmiyor — "
                                     f"acil koruma gerekiyor")
                        guncel = futures_anlık_fiyat(sembol)
                        if guncel:
                            # Acil SL: mevcut fiyattan %3 uzağa koy
                            acil_sl = (guncel * 0.97 if yon == "LONG"
                                       else guncel * 1.03)
                            try:
                                futures_stop_loss_koy(sembol, yon, acil_sl)
                                log.info(f"[RECONCILER] {sembol} acil SL koyuldu @ {acil_sl}")
                                self._istatistik["sl_yeniden"] += 1
                            except FuturesAPIError as e:
                                log.critical(f"[RECONCILER] {sembol} ACİL SL KOYULAMADI: {e}")

                # ── TP eksik ──────────────────────────────
                if not tp_emirleri and tp1 > 0 and not FUTURES_TRAILING_STOP:
                    log.warning(f"[RECONCILER] {sembol} TP EKSİK @ {tp1} — yeniden koyuluyor")
                    try:
                        futures_partial_tp_koy(sembol, yon, tp1, FUTURES_PARTIAL_TP_PCT)
                        self._istatistik["tp_yeniden"] += 1
                    except FuturesAPIError as e:
                        log.warning(f"[RECONCILER] {sembol} TP yeniden koyulamadı: {e}")

            except Exception as e:
                log.error(f"[RECONCILER] {sembol} SL/TP doğrulama hatası: "
                           f"{type(e).__name__}: {e}")

    @property
    def istatistik(self) -> dict:
        return dict(self._istatistik)

    def anlık_rapor(self) -> str:
        s = self._istatistik
        return (
            f"🔄 <b>FILL RECONCILER</b>\n"
            f"Sync sayısı    : {s['sync_sayisi']}\n"
            f"Uyumsuzluk     : {s['uyumsuzluk_toplam']}\n"
            f"Düzeltme       : {s['duzeltme_toplam']}\n"
            f"Orphan iptal   : {s['orphan_iptal']}\n"
            f"SL yeniden     : {s['sl_yeniden']}\n"
            f"TP yeniden     : {s['tp_yeniden']}"
        )
