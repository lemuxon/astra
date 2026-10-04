# =========================================================
# ASTRA EXECUTION LAYER — ORDER ACK VERIFIER
# =========================================================
# ⚠️ v55 DURUM UYARISI — BU MODÜL CANLI YOLDA KULLANILMIYOR.
#
# Canlı emir doğrulaması `data/binance_futures_client.py` içindeki
# `fill_verify()` fonksiyonu tarafından yapılır. Bu modül (OrderAckVerifier)
# hiçbir yerden import EDİLMEZ — grep ile doğrulandı.
#
# Neden silinmedi: fill_verify()'dan daha zengin bir durum modeli sunuyor
# (AckDurum enum'u, SLIPPAGE_ASIM / kritik_hata ayrımı). İleride canlı yola
# bağlanması planlanıyorsa referans olarak duruyor.
#
# DİKKAT: İki ayrı "emir doldu mu" uygulaması olması bakım riskidir —
# birine yapılan düzeltme (örn. MIN_FILL_PCT değişikliği) diğerine YANSIMAZ.
# Karar verilmeli: ya bu modül canlı yola bağlanıp fill_verify() emekliye
# ayrılmalı, ya da bu dosya tamamen silinmeli.
# =========================================================
# Her gönderilen emrin Binance tarafından gerçekten
# alındığını, işlendiğini ve doğru miktarda dolduğunu
# doğrular.
#
# Sorunlar bu katmanın çözdüğü:
#   - Emir gönderildi ama Binance'e ulaşmadı
#   - Emir kısmen doldu (partial fill)
#   - avgPrice beklenen fiyattan çok uzak (slippage)
#   - Emir Binance'te REJECTED/EXPIRED durumunda
#   - Network timeout sonrası durum belirsiz
# =========================================================

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import sys
sys.path.append("..")
from config import FILL_VERIFY_TIMEOUT, FILL_VERIFY_INTERVAL, MAX_SLIPPAGE_PCT, SLIPPAGE_WARN_PCT

log = logging.getLogger("ASTRA.ORDER_ACK")


class AckDurum(Enum):
    FILLED          = "FILLED"           # Tam doldu
    PARTIAL_KABUL   = "PARTIAL_KABUL"    # Kısmen doldu, kabul edildi
    PARTIAL_RED     = "PARTIAL_RED"      # Kısmen doldu, çok az — reddedildi
    REJECTED        = "REJECTED"         # Binance reddetti
    SLIPPAGE_ASIM   = "SLIPPAGE_ASIM"   # Slippage kabul sınırı aştı
    TIMEOUT         = "TIMEOUT"          # Zaman aşımı
    BILINMIYOR      = "BILINMIYOR"       # Durum belirlenemedi


@dataclass
class AckSonuc:
    durum:          AckDurum
    order_id:       int
    sembol:         str
    yon:            str
    beklenen_miktar:float
    gercek_miktar:  float
    fill_pct:       float          # % kaçı doldu
    beklenen_fiyat: float
    gercek_fiyat:   float
    slippage_pct:   float
    sure_saniye:    float
    ham_emir:       dict = field(default_factory=dict)
    aciklama:       str  = ""

    @property
    def kabul_edildi(self) -> bool:
        return self.durum in (AckDurum.FILLED, AckDurum.PARTIAL_KABUL)

    @property
    def kritik_hata(self) -> bool:
        return self.durum in (AckDurum.SLIPPAGE_ASIM, AckDurum.REJECTED)


class OrderAckVerifier:
    """
    Emir ACK doğrulayıcısı.

    Kullanım:
        verifier = OrderAckVerifier()
        sonuc = verifier.dogrula(sembol, order_id, beklenen_miktar, beklenen_fiyat, yon)
        if not sonuc.kabul_edildi:
            # Pozisyon açılmadı — SL/TP koymaya gerek yok
    """

    # Kısmi fill için minimum kabul eşiği
    MIN_FILL_PCT = 0.80   # %80'den az doluyorsa reddedilir

    def __init__(self,
                 timeout:   int   = FILL_VERIFY_TIMEOUT,
                 interval:  float = FILL_VERIFY_INTERVAL,
                 max_slip:  float = MAX_SLIPPAGE_PCT,
                 warn_slip: float = SLIPPAGE_WARN_PCT):
        self._timeout   = timeout
        self._interval  = interval
        self._max_slip  = max_slip
        self._warn_slip = warn_slip

    def dogrula(self,
                sembol:          str,
                order_id:        int,
                beklenen_miktar: float,
                beklenen_fiyat:  float,
                yon:             str) -> AckSonuc:
        """
        Emrin durumunu periyodik sorgulayarak doğrular.

        Akış:
        1. Her FILL_VERIFY_INTERVAL saniyede emir sorgula
        2. FILLED → slippage kontrol et
        3. PARTIALLY_FILLED → yeterince doldu mu kontrol et
        4. CANCELED/REJECTED → hemen geri dön
        5. Timeout → son durumu raporla
        """
        from data.binance_futures_client import emir_durum_sorgula, futures_emir_iptal

        baslangic = time.time()
        log.info(f"[ACK] {sembol} #{order_id} doğrulama başlıyor "
                 f"(timeout={self._timeout}s)")

        son_emir: dict = {}

        while time.time() - baslangic < self._timeout:
            sure = round(time.time() - baslangic, 1)

            # ── Binance'ten emir durumunu sorgula ─────────
            emir = emir_durum_sorgula(sembol, order_id)
            if emir is None:
                log.warning(f"[ACK] #{order_id} sorgu başarısız, {self._interval}s sonra tekrar")
                time.sleep(self._interval)
                continue

            son_emir = emir
            durum         = emir.get("status", "")
            dolan_miktar  = float(emir.get("executedQty", 0))
            avg_fiyat     = float(emir.get("avgPrice", 0)) or beklenen_fiyat
            fill_pct      = (dolan_miktar / beklenen_miktar * 100
                             if beklenen_miktar > 0 else 0)

            # ── FILLED ────────────────────────────────────
            if durum == "FILLED":
                slip_pct = self._slippage_hesapla(beklenen_fiyat, avg_fiyat, yon)
                sonuc    = AckSonuc(
                    durum           = AckDurum.FILLED,
                    order_id        = order_id,
                    sembol          = sembol,
                    yon             = yon,
                    beklenen_miktar = beklenen_miktar,
                    gercek_miktar   = dolan_miktar,
                    fill_pct        = 100.0,
                    beklenen_fiyat  = beklenen_fiyat,
                    gercek_fiyat    = avg_fiyat,
                    slippage_pct    = slip_pct,
                    sure_saniye     = sure,
                    ham_emir        = emir,
                )

                if slip_pct > self._max_slip:
                    log.error(f"[ACK] #{order_id} SLIPPAGE AŞIMI: "
                              f"%{slip_pct:.3f} > %{self._max_slip} limit")
                    sonuc.durum     = AckDurum.SLIPPAGE_ASIM
                    sonuc.aciklama  = f"Slippage %{slip_pct:.3f} limit %{self._max_slip}"
                elif slip_pct > self._warn_slip:
                    log.warning(f"[ACK] #{order_id} yüksek slippage: %{slip_pct:.3f}")

                if sonuc.durum == AckDurum.FILLED:
                    log.info(f"[ACK] ✅ #{order_id} DOLU: "
                             f"{dolan_miktar} @ {avg_fiyat:.4f} "
                             f"slip=%{slip_pct:.3f} ({sure}s)")
                return sonuc

            # ── PARTIALLY_FILLED ──────────────────────────
            elif durum == "PARTIALLY_FILLED":
                log.warning(f"[ACK] #{order_id} KISMİ: "
                             f"{dolan_miktar}/{beklenen_miktar} (%{fill_pct:.1f}) @ {sure}s")

                if fill_pct >= self.MIN_FILL_PCT * 100:
                    # Yeterince doldu — geri kalanı iptal et, devam et
                    log.info(f"[ACK] %{fill_pct:.1f} fill kabul edildi, kalan iptal")
                    try:
                        futures_emir_iptal(sembol, order_id)
                    except Exception as e:
                        log.warning(f"[ACK] Kısmi fill iptal hatası: {e}")

                    slip_pct = self._slippage_hesapla(beklenen_fiyat, avg_fiyat, yon)
                    return AckSonuc(
                        durum           = AckDurum.PARTIAL_KABUL,
                        order_id        = order_id,
                        sembol          = sembol,
                        yon             = yon,
                        beklenen_miktar = beklenen_miktar,
                        gercek_miktar   = dolan_miktar,
                        fill_pct        = fill_pct,
                        beklenen_fiyat  = beklenen_fiyat,
                        gercek_fiyat    = avg_fiyat,
                        slippage_pct    = slip_pct,
                        sure_saniye     = sure,
                        ham_emir        = emir,
                        aciklama        = f"Kısmi fill %{fill_pct:.1f} kabul edildi",
                    )

                # Yeterli fill yok — beklemeye devam
                time.sleep(self._interval)
                continue

            # ── CANCELED / REJECTED / EXPIRED ─────────────
            elif durum in ("CANCELED", "REJECTED", "EXPIRED"):
                log.error(f"[ACK] ❌ #{order_id} {durum} @ {sure}s")
                return AckSonuc(
                    durum           = AckDurum.REJECTED,
                    order_id        = order_id,
                    sembol          = sembol,
                    yon             = yon,
                    beklenen_miktar = beklenen_miktar,
                    gercek_miktar   = dolan_miktar,
                    fill_pct        = fill_pct,
                    beklenen_fiyat  = beklenen_fiyat,
                    gercek_fiyat    = avg_fiyat,
                    slippage_pct    = 0,
                    sure_saniye     = sure,
                    ham_emir        = emir,
                    aciklama        = f"Binance {durum}",
                )

            # ── NEW / PENDING — Beklemeye devam ──────────
            else:
                log.debug(f"[ACK] #{order_id} bekleniyor: {durum} @ {sure}s")
                time.sleep(self._interval)

        # ── TIMEOUT ───────────────────────────────────────
        sure = round(time.time() - baslangic, 1)
        dolan_miktar = float(son_emir.get("executedQty", 0)) if son_emir else 0
        fill_pct     = dolan_miktar / beklenen_miktar * 100 if beklenen_miktar > 0 else 0

        if fill_pct >= self.MIN_FILL_PCT * 100 and dolan_miktar > 0:
            # Timeout ama yeterince doldu — kabul et
            log.warning(f"[ACK] #{order_id} TIMEOUT ama %{fill_pct:.1f} fill — kabul")
            return AckSonuc(
                durum=AckDurum.PARTIAL_KABUL, order_id=order_id, sembol=sembol, yon=yon,
                beklenen_miktar=beklenen_miktar, gercek_miktar=dolan_miktar,
                fill_pct=fill_pct, beklenen_fiyat=beklenen_fiyat,
                gercek_fiyat=float(son_emir.get("avgPrice",0)) or beklenen_fiyat,
                slippage_pct=0, sure_saniye=sure, ham_emir=son_emir,
                aciklama=f"Timeout ama %{fill_pct:.1f} fill kabul edildi",
            )

        log.error(f"[ACK] ⏱️ #{order_id} TIMEOUT ({self._timeout}s) — fill:%{fill_pct:.1f}")
        return AckSonuc(
            durum=AckDurum.TIMEOUT, order_id=order_id, sembol=sembol, yon=yon,
            beklenen_miktar=beklenen_miktar, gercek_miktar=dolan_miktar,
            fill_pct=fill_pct, beklenen_fiyat=beklenen_fiyat,
            gercek_fiyat=float(son_emir.get("avgPrice",0)) or beklenen_fiyat,
            slippage_pct=0, sure_saniye=sure, ham_emir=son_emir,
            aciklama=f"Timeout {self._timeout}s",
        )

    def _slippage_hesapla(self, beklenen: float, gercek: float, yon: str) -> float:
        if beklenen <= 0 or gercek <= 0:
            return 0.0
        fark = gercek - beklenen
        # LONG için daha yüksek fiyat = olumsuz slippage
        # SHORT için daha düşük fiyat = olumsuz slippage
        if yon == "LONG":
            return round(fark / beklenen * 100, 4)
        else:
            return round(-fark / beklenen * 100, 4)
