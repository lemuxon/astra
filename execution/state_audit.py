# =========================================================
# ASTRA EXECUTION LAYER — BINANCE STATE AUDIT
# =========================================================
# Binance hesabının tam durumunu periyodik olarak denetler.
# "Gerçek nedir?" sorusunun cevabı her zaman Binance'ten gelir.
#
# Denetlenen alanlar:
#   - Hesap marjin dengesi
#   - Açık pozisyonlar ve PnL
#   - Açık emirler (SL, TP, Trailing)
#   - Kaldıraç ayarları
#   - Likidasyon fiyatları
#   - Risk oranı (margin ratio)
# =========================================================

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional
import sys
sys.path.append("..")
from engines.event_bus import get_bus, Event
from config import LIQUIDATION_BUFFER_PCT

log = logging.getLogger("ASTRA.STATE_AUDIT")


class BinanceStateAudit:
    """
    Binance hesabının gerçek durumunu denetler.
    Tek kaynak: Binance API.
    """

    AUDIT_INTERVAL       = 120   # saniye — her 2 dakikada tam denetim
    QUICK_CHECK_INTERVAL = 30    # saniye — hızlı marjin/likidasyon kontrolü

    # Risk oranı eşikleri
    MARGIN_RATIO_WARN    = 0.50  # %50 kullanıldıysa uyar
    MARGIN_RATIO_CRITICAL= 0.75  # %75 kullanıldıysa kritik
    LIQUIDATION_WARN_PCT = 15.0  # Likit fiyatına %15'ten yakınsa uyar
    LIQUIDATION_CRIT_PCT = 8.0   # %8'den yakınsa kritik

    def __init__(self):
        self._bus       = get_bus()
        self._running   = False
        self._thread: Optional[threading.Thread] = None
        self._son_audit = 0
        self._son_quick = 0
        self._son_snapshot: dict = {}
        self._istatistik = {
            "audit_sayisi": 0,
            "uyari_sayisi": 0,
            "kritik_sayisi": 0,
        }

    def start(self):
        # v29: çift başlatma koruması
        if getattr(self, "_thread", None) and self._thread.is_alive():
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="AstraStateAudit"
        )
        self._thread.start()
        log.info("[AUDIT] Başlatıldı")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                now = time.time()
                if now - self._son_quick >= self.QUICK_CHECK_INTERVAL:
                    self._hizli_kontrol()
                    self._son_quick = now
                if now - self._son_audit >= self.AUDIT_INTERVAL:
                    self._tam_denetim()
                    self._son_audit = now
            except Exception as e:
                log.error(f"[AUDIT] Loop hatası: {type(e).__name__}: {e}")
            time.sleep(10)

    # ──────────────────────────────────────────────────────
    # HIZLI KONTROL (her 30s)
    # ──────────────────────────────────────────────────────

    def _hizli_kontrol(self):
        """Marjin oranı ve likidasyon yakınlığı — hızlı kontrol."""
        from data.binance_futures_client import (
            acik_futures_pozisyonlar, futures_bakiye, futures_anlık_fiyat
        )
        try:
            pozlar = acik_futures_pozisyonlar()
            if not pozlar:
                return

            for poz in pozlar:
                sembol   = poz.get("sembol")
                giris    = float(poz.get("giris", 0) or 0)
                yon      = poz.get("yon")
                miktar   = abs(float(poz.get("miktar", 0) or 0))

                if not sembol or giris <= 0 or miktar <= 0:
                    continue

                guncel = futures_anlık_fiyat(sembol)
                if not guncel or guncel <= 0:
                    continue

                # v55: Likidasyon fiyatı tek kaynaktan (borsanın kendi değeri
                # varsa o, yoksa yaklaşım). Eskiden burada, failsafe_liquidation'da
                # ve risk_manager'da üç ayrı kopya formül vardı.
                from execution.failsafe_liquidation import likidasyon_fiyati
                likit_fiyat = likidasyon_fiyati(poz)
                if likit_fiyat <= 0:
                    continue
                if yon == "LONG":
                    uzaklik_pct  = (guncel - likit_fiyat) / guncel * 100
                else:
                    uzaklik_pct  = (likit_fiyat - guncel) / guncel * 100

                if uzaklik_pct <= self.LIQUIDATION_CRIT_PCT:
                    log.critical(f"[AUDIT] 🚨 KRİTİK LİKİDASYON: {sembol} {yon} "
                                  f"uzaklık %{uzaklik_pct:.1f} @ {guncel}")
                    self._bus.publish(Event.RISK_LIQUIDATION, {
                        "sembol":         sembol,
                        "yon":            yon,
                        "uzaklik_pct":    round(uzaklik_pct, 2),
                        "likidasyon_fiyat": round(likit_fiyat, 4),
                        "guncel_fiyat":   guncel,
                        "kritik":         True,
                    }, "StateAudit")
                    self._istatistik["kritik_sayisi"] += 1

                elif uzaklik_pct <= self.LIQUIDATION_WARN_PCT:
                    log.warning(f"[AUDIT] ⚠️ Likidasyon yakın: {sembol} {yon} "
                                 f"uzaklık %{uzaklik_pct:.1f}")
                    self._bus.publish(Event.ALERT, {
                        "mesaj": f"⚠️ {sembol} {yon} likidasyon uzaklığı "
                                  f"%{uzaklik_pct:.1f} — DİKKAT"
                    }, "StateAudit")
                    self._istatistik["uyari_sayisi"] += 1

        except Exception as e:
            log.error(f"[AUDIT] Hızlı kontrol hatası: {e}")

    # ──────────────────────────────────────────────────────
    # TAM DENETİM (her 2 dakika)
    # ──────────────────────────────────────────────────────

    def _tam_denetim(self):
        """Hesabın tam durumunu denetler ve snapshot alır."""
        from data.binance_futures_client import (
            acik_futures_pozisyonlar, futures_bakiye,
            koruma_emirleri, futures_anlık_fiyat, _futures_istek
        )

        self._istatistik["audit_sayisi"] += 1
        ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        log.info(f"[AUDIT] Tam denetim başlıyor...")

        try:
            pozlar       = acik_futures_pozisyonlar()
            bakiye       = futures_bakiye()
            # v57: denetim koşullu emirleri de görmeli (algo listesi ayrı)
            acik_emirler = koruma_emirleri()
        except Exception as e:
            log.error(f"[AUDIT] Denetim verisi alınamadı: {e}")
            return

        # ── Snapshot ──────────────────────────────────────
        snapshot = {
            "ts":           ts,
            "bakiye":       bakiye,
            "poz_sayisi":   len(pozlar),
            "emir_sayisi":  len(acik_emirler),
            "pozisyonlar":  [],
            "toplam_pnl":   0,
            "toplam_marjin":0,
            "uyarilar":     [],
        }

        toplam_pnl    = 0
        toplam_marjin = 0

        for poz in pozlar:
            sembol   = poz["sembol"]
            giris    = poz["giris"]
            yon      = poz["yon"]
            miktar   = abs(poz["miktar"])
            pnl      = poz["pnl"]
            kaldirac = poz.get("kaldirac", 5)

            guncel = futures_anlık_fiyat(sembol) or giris
            pnl_pct = ((guncel - giris) / giris * 100) * (1 if yon == "LONG" else -1)
            marjin  = (miktar * giris) / kaldirac

            toplam_pnl    += pnl
            toplam_marjin += marjin

            # Pozisyon için açık emir kontrolü
            poz_emirleri = [e for e in acik_emirler if e.get("symbol") == sembol]
            sl_var = any(e.get("type") in ("STOP_MARKET","STOP") for e in poz_emirleri)
            tp_var = any(e.get("type") in ("TAKE_PROFIT_MARKET","TAKE_PROFIT",
                                            "TRAILING_STOP_MARKET") for e in poz_emirleri)

            poz_snapshot = {
                "sembol":      sembol,
                "yon":         yon,
                "giris":       giris,
                "guncel":      guncel,
                "miktar":      miktar,
                "pnl":         round(pnl, 4),
                "pnl_pct":     round(pnl_pct, 2),
                "kaldirac":    kaldirac,
                "marjin":      round(marjin, 2),
                "sl_aktif":    sl_var,
                "tp_aktif":    tp_var,
            }
            snapshot["pozisyonlar"].append(poz_snapshot)

            # ── Uyarı üret ────────────────────────────────
            if not sl_var:
                uyari = f"⚠️ {sembol} SL EMRİ YOK — Pozisyon korumasız!"
                snapshot["uyarilar"].append(uyari)
                log.warning(f"[AUDIT] {uyari}")
                self._bus.publish(Event.ALERT, {"mesaj": uyari}, "StateAudit")

            if pnl_pct < -15:
                uyari = f"⚠️ {sembol} YÜKSEK KAYIP: %{pnl_pct:.1f}"
                snapshot["uyarilar"].append(uyari)
                log.warning(f"[AUDIT] {uyari}")

        snapshot["toplam_pnl"]    = round(toplam_pnl, 4)
        snapshot["toplam_marjin"] = round(toplam_marjin, 2)

        # ── Marjin oranı ──────────────────────────────────
        if bakiye > 0:
            marjin_orani = toplam_marjin / bakiye
            if marjin_orani >= self.MARGIN_RATIO_CRITICAL:
                uyari = (f"🚨 Marjin oranı kritik: %{marjin_orani*100:.1f} "
                          f"(kullanılan:{toplam_marjin:.2f} bakiye:{bakiye:.2f})")
                snapshot["uyarilar"].append(uyari)
                log.critical(f"[AUDIT] {uyari}")
                self._bus.publish(Event.ALERT, {"mesaj": uyari}, "StateAudit")
                self._istatistik["kritik_sayisi"] += 1
            elif marjin_orani >= self.MARGIN_RATIO_WARN:
                uyari = f"⚠️ Marjin oranı yüksek: %{marjin_orani*100:.1f}"
                snapshot["uyarilar"].append(uyari)
                log.warning(f"[AUDIT] {uyari}")
                self._istatistik["uyari_sayisi"] += 1

        self._son_snapshot = snapshot
        log.info(f"[AUDIT] ✅ Denetim tamamlandı: {len(pozlar)} poz, "
                  f"PnL:{toplam_pnl:+.2f} USDT, Marjin:{toplam_marjin:.2f} USDT, "
                  f"Uyarı:{len(snapshot['uyarilar'])}")

    def son_snapshot(self) -> dict:
        return dict(self._son_snapshot)

    def telegram_raporu(self) -> str:
        s = self._son_snapshot
        if not s:
            return "📊 <b>STATE AUDIT</b>\nHenüz denetim yapılmadı"

        poz_satirlari = ""
        for p in s.get("pozisyonlar", []):
            sl_d = "✅" if p["sl_aktif"] else "❌"
            tp_d = "✅" if p["tp_aktif"] else "❌"
            emoji = "🟢" if p["yon"] == "LONG" else "🔴"
            poz_satirlari += (
                f"\n{emoji} {p['sembol']} {p['yon']} x{p['kaldirac']}\n"
                f"  @ {p['giris']:,.4f} | PnL:{p['pnl_pct']:+.2f}%\n"
                f"  SL:{sl_d} TP:{tp_d} | Marjin:{p['marjin']:.2f}USDT\n"
            )

        uyari_satirlari = ""
        for u in s.get("uyarilar", []):
            uyari_satirlari += f"\n{u}"

        return (
            f"📊 <b>STATE AUDIT — {s.get('ts','?')[:19]}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Bakiye   : {s.get('bakiye',0):.2f} USDT\n"
            f"📦 Pozisyon : {s.get('poz_sayisi',0)}\n"
            f"📋 Emir     : {s.get('emir_sayisi',0)}\n"
            f"💵 Toplam PnL: {s.get('toplam_pnl',0):+.4f} USDT\n"
            f"📊 Toplam Marjin: {s.get('toplam_marjin',0):.2f} USDT\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{poz_satirlari}"
            f"{'━━━━━━━━━━━━━━━━━━' if uyari_satirlari else ''}"
            f"{uyari_satirlari}"
        )

    @property
    def istatistik(self) -> dict:
        return dict(self._istatistik)


# Singleton
_audit_instance: Optional[BinanceStateAudit] = None

def get_audit(otomatik_baslat: bool = False) -> BinanceStateAudit:
    global _audit_instance
    if _audit_instance is None:
        _audit_instance = BinanceStateAudit()
        if otomatik_baslat:
            _audit_instance.start()
    return _audit_instance
