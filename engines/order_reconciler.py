# =========================================================
# ASTRA v30.0 — ORDER RECONCILIATION SİSTEMİ
# Binance ↔ Bot State ↔ DB 3-yönlü senkron
# Her 15s'de çalışır
# =========================================================
import logging, time, threading
from typing import Optional
import sys; sys.path.append("..")

log = logging.getLogger("ASTRA.RECONCILER")

class OrderReconciler:
    """
    3-yönlü reconciliation:
    1. Binance gerçek pozisyonlar
    2. Bot iç state (position_state.py)
    3. DB kayıtları
    
    Düzelttiği sorunlar:
    - Phantom trade (bot düşünür açık, Binance'te yok)
    - Duplicate trade (botun unuttuğu Binance pozisyonu)
    - SL kaybı (pozisyon var ama koruma emri yok)
    - TP kaybı
    """

    def __init__(self, state_manager=None, interval: int = 15):
        self._state    = state_manager
        self._interval = interval
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._istatistik = {
            "sync_sayisi":         0,
            "phantom_duzeltme":    0,
            "duplicate_duzeltme":  0,
            "sl_onarim":           0,
            "tp_onarim":           0,
            "balance_sync":        0,
            "son_sync_ts":         0,
            "son_uyumsuzluk":      [],
        }

    def start(self):
        # v29: çift başlatma koruması
        if getattr(self, "_thread", None) and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="AstraOrderReconciler"
        )
        self._thread.start()
        log.info(f"[RECONCILER v14] Başlatıldı — {self._interval}s interval")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            time.sleep(self._interval)
            try:
                self.sync_tum()
            except Exception as e:
                log.error(f"[RECONCILER] Loop hatası: {e}")

    def sync_tum(self):
        """3-yönlü tam sync."""
        try:
            from config import LIVE_TRADING
            if not LIVE_TRADING:
                self._sync_paper()
                return

            self.sync_open_positions()
            self.sync_open_orders()
            self.sync_balance()
            self._istatistik["sync_sayisi"] += 1
            self._istatistik["son_sync_ts"] = time.time()
        except Exception as e:
            log.error(f"[RECONCILER] sync_tum hatası: {e}")

    def sync_open_positions(self):
        """Binance pozisyonlarını bot state ile karşılaştır."""
        try:
            from data.binance_futures_client import acik_futures_pozisyonlar, FuturesAPIError
            # v55: strict=True — ağ hatasında [] dönerse aşağıdaki `phantom`
            # kümesi TÜM bot pozisyonlarını kapsar ve hepsi state'ten silinir.
            binance_pozlar = acik_futures_pozisyonlar(strict=True)
            binance_set    = {p["sembol"] for p in binance_pozlar}

            if self._state is None:
                return

            bot_pozlar = self._state.acik_pozisyonlar()
            bot_set    = {p.get("sembol") for p in bot_pozlar}

            # Phantom: bot'ta var, Binance'te yok → state'den sil
            phantom = bot_set - binance_set
            for sem in phantom:
                log.warning(f"[RECONCILER] Phantom pozisyon: {sem} → state'den siliniyor")
                self._state.pozisyon_kapat(sem, "PHANTOM_CLEANUP")
                self._istatistik["phantom_duzeltme"] += 1
                self._istatistik["son_uyumsuzluk"].append(f"PHANTOM:{sem}")

            # Duplicate: Binance'te var, bot'ta yok → state'e ekle
            for poz in binance_pozlar:
                sem = poz["sembol"]
                if sem not in bot_set:
                    log.warning(f"[RECONCILER] Orphan Binance pozisyonu: {sem} → state'e ekleniyor")
                    # ── v58 (K-99): `pozisyon_ekle` DİYE BİR METOT YOK ────
                    # K-8/v57 bu hatayı `execution_engine.py`'de bulup
                    # düzeltmişti ve doğru imzayı oraya yazmıştı — ama
                    # AYNI hatalı çağrının BURADAKİ kopyası atlandı.
                    # "Bir yerde düzeltilip diğerinde unutulan" desen
                    # (K-13, K-69, K-78, K-86, K-89, K-95, K-97...).
                    #
                    # Sonuç: orphan pozisyon bulunduğunda AttributeError
                    # fırlıyor, `except` yakalayıp "pozisyon tutarlılığı
                    # DOĞRULANAMADI" diye logluyor ve orphan state'e HİÇ
                    # eklenmiyor — yani reconciler'ın tek işi yapılmıyor.
                    # (v55 sayesinde en azından GÖRÜNÜR; sessiz değil.)
                    # Sahada yakalandı: 2026-09-15 00:17:17.
                    #
                    # Doğru API: pozisyon_ac(sembol, yon, giris, miktar,
                    #                        sl, tp1, kaldirac, order_id)
                    # — dict değil KONUMLU argümanlar.
                    #
                    # ⚠️ SL/TP 0.0 geçiliyor: borsadan gelen orphan'ın
                    # koruma emirleri BİLİNMİYOR. 0.0 "koruma yok" demek
                    # ve `sl_tp_dogrula()` bunu eksik görüp koruma koyar.
                    # Uydurma bir seviye yazmak, olmayan korumayı VAR
                    # göstermek olurdu (§5.1).
                    self._state.pozisyon_ac(
                        sem,
                        poz["yon"],
                        poz["giris"],
                        poz["miktar"],
                        0.0,                              # sl — bilinmiyor
                        0.0,                              # tp1 — bilinmiyor
                        poz.get("kaldirac", 1),
                        order_id="RECONCILER",
                    )
                    self._istatistik["duplicate_duzeltme"] += 1

        except Exception as e:
            # v55: Pozisyon senkronizasyonu kritik — sessiz kalmamalı.
            # Başarısız olursa phantom/orphan pozisyonlar düzeltilmez.
            log.error(f"[RECONCILER] sync_open_positions BAŞARISIZ: {e} "
                      f"— pozisyon tutarlılığı doğrulanamadı!")

    def sync_open_orders(self):
        """SL/TP emirlerini doğrula, kayıpsa yeniden koy."""
        try:
            from data.binance_futures_client import (
                acik_futures_pozisyonlar, koruma_emirleri,
                futures_stop_loss_koy, futures_anlık_fiyat, FuturesAPIError,
                futures_partial_tp_koy
            )
            from config import (FUTURES_SL_ATR_MULT, FUTURES_TP_ATR_MULT,
                                FUTURES_PARTIAL_TP_PCT)

            # v55: strict=True — [] dönerse hiç pozisyon yok sanılıp SL/TP
            # doğrulaması sessizce atlanırdı.
            pozlar = acik_futures_pozisyonlar(strict=True)
            for poz in pozlar:
                sem = poz["sembol"]
                yon = poz["yon"]
                # v57 KRİTİK: koşullu emirler Algo Service'e taşındı ve
                # klasik openOrders listesinde GÖRÜNMÜYOR. `acik_futures_emirler`
                # kullanılırsa SL hep "kayıp" görünür ve her turda gereksiz
                # acil SL koyulur (üst üste emir birikir).
                # strict=True: sorgu başarısızsa "SL yok" VARSAYMA.
                emirler = koruma_emirleri(sem, strict=True)
                tipler  = {e.get("type") for e in emirler}

                # SL yok mu?
                # v55: TRAILING_STOP_MARKET de geçerli SL koruması sayılır.
                sl_tipler = {"STOP_MARKET", "STOP", "TRAILING_STOP_MARKET"}
                if not tipler.intersection(sl_tipler):
                    fiyat = futures_anlık_fiyat(sem) or poz["giris"]
                    # ── v55: Acil SL artık KALDIRAÇA duyarlı ──
                    # Eski kod sabit %5 kullanıyordu: 10x kaldıraçta %5 fiyat
                    # hareketi = %50 SERMAYE kaybı, 20x'te likidasyona yakın.
                    # Yeni kural: likidasyona olan mesafenin en fazla YARISI
                    # kadar uzakta, üst sınır %5.
                    _kald = max(float(poz.get("kaldirac", 1) or 1), 1.0)
                    _mesafe_pct = min(0.05, (1.0 / _kald) * 0.5)
                    acil_sl = (poz["giris"] * (1 - _mesafe_pct) if yon == "LONG"
                               else poz["giris"] * (1 + _mesafe_pct))
                    try:
                        futures_stop_loss_koy(sem, yon, acil_sl)
                        log.warning(f"[RECONCILER] {sem} SL kayıp → acil SL koyuldu "
                                    f"@ {acil_sl:.4f} (%{_mesafe_pct*100:.1f} mesafe, "
                                    f"{_kald:.0f}x kaldıraç)")
                        self._istatistik["sl_onarim"] += 1
                    except Exception as sl_e:
                        log.error(f"[RECONCILER] ⚠️ {sem} ACİL SL KOYULAMADI: {sl_e} "
                                  f"— pozisyon KORUMASIZ, manuel kontrol edin!")

                # ── v55: TP onarımı EKLENDİ ──
                # Modülün docstring'i "TP kaybı"nı çözdüğünü söylüyor ve
                # _istatistik["tp_onarim"] sayacı tanımlıydı, ama TP hiç
                # kontrol edilmiyor ve sayaç hiç artırılmıyordu. TP emrini
                # kaybeden pozisyon sonsuza dek take-profit'siz kalıyor,
                # rapor ise "tp_onarim: 0" ile "sorun yok" izlenimi veriyordu.
                tp_tipler = {"TAKE_PROFIT_MARKET", "TAKE_PROFIT"}
                if not tipler.intersection(tp_tipler):
                    giris = float(poz.get("giris", 0) or 0)
                    if giris > 0:
                        _kald_tp = max(float(poz.get("kaldirac", 1) or 1), 1.0)
                        # SL ile simetrik mantık: kaldıraca duyarlı hedef mesafe
                        _tp_pct = min(0.05 * (FUTURES_TP_ATR_MULT / max(FUTURES_SL_ATR_MULT, 0.1)),
                                      (1.0 / _kald_tp) * 1.0)
                        acil_tp = (giris * (1 + _tp_pct) if yon == "LONG"
                                   else giris * (1 - _tp_pct))
                        try:
                            futures_partial_tp_koy(sem, yon, acil_tp,
                                                   FUTURES_PARTIAL_TP_PCT)
                            log.warning(f"[RECONCILER] {sem} TP kayıp → yeniden koyuldu "
                                        f"@ {acil_tp:.4f} (%{_tp_pct*100:.1f} mesafe)")
                            self._istatistik["tp_onarim"] += 1
                        except Exception as tp_e:
                            log.error(f"[RECONCILER] {sem} TP yeniden konamadı: {tp_e}")

        except Exception as e:
            # v55: Kritik senkronizasyon hatası DEBUG'da gizlenmemeli.
            # Bu fonksiyon SL güvenlik ağıdır; sessizce çökerse kullanıcı
            # korumasız olduğunu bilmez (yanlış güven = en tehlikeli durum).
            log.error(f"[RECONCILER] sync_open_orders BAŞARISIZ: {e} "
                      f"— SL doğrulaması yapılamadı!")

    def sync_balance(self):
        """Bakiye senkronu."""
        try:
            from data.binance_futures_client import futures_bakiye
            bakiye = futures_bakiye()
            if bakiye and bakiye > 0:
                self._istatistik["balance_sync"] += 1
                log.debug(f"[RECONCILER] Bakiye sync: {bakiye:.2f} USDT")
        except Exception as e:
            log.debug(f"[RECONCILER] sync_balance: {e}")

    def _sync_paper(self):
        """Paper modda DB tutarlılığını kontrol et."""
        try:
            from data.database import acik_tradeler
            aciklar = acik_tradeler("PAPER")
            self._istatistik["sync_sayisi"] += 1
            self._istatistik["son_sync_ts"] = time.time()
            log.debug(f"[RECONCILER] Paper sync: {len(aciklar)} açık pozisyon")
        except Exception as e:
            log.debug(f"[RECONCILER] paper sync: {e}")

    @property
    def istatistik(self) -> dict:
        d = dict(self._istatistik)
        d["son_uyumsuzluk"] = d["son_uyumsuzluk"][-10:]
        return d

    def anlık_rapor(self) -> str:
        i = self.istatistik
        son_sync = time.time() - i["son_sync_ts"] if i["son_sync_ts"] else -1
        return (
            f"🔄 <b>RECONCILER v14</b>\n"
            f"Sync: {i['sync_sayisi']} | Son: {son_sync:.0f}s önce\n"
            f"Phantom: {i['phantom_duzeltme']} | Orphan: {i['duplicate_duzeltme']}\n"
            f"SL onarım: {i['sl_onarim']} | TP onarım: {i['tp_onarim']}\n"
            f"Bakiye sync: {i['balance_sync']}"
        )


_instance = None
def get_order_reconciler(state_manager=None, interval=15) -> OrderReconciler:
    global _instance
    if _instance is None:
        _instance = OrderReconciler(state_manager, interval)
    return _instance
