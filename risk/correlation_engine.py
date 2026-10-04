# =========================================================
# ASTRA v30.0 — EXPOSURE CORRELATION ENGINE
# BTC+ETH+SOL aynı yönde = tek trade gibi davranır
# =========================================================
import logging, threading
from typing import Optional
import sys; sys.path.append("..")

log = logging.getLogger("ASTRA.CORRELATION")

# Bilinen yüksek korelasyonlu coin grupları
KORELASYON_GRUPLARI = {
    "MAJORS":     {"BTCUSDT", "ETHUSDT"},           # ~0.85+
    "ALTCOINS":   {"SOLUSDT", "BNBUSDT", "XRPUSDT"}, # ~0.75+
    "ALL_CRYPTO": {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"},
}
# Aynı yönde max pozisyon limiti per grup
MAX_AYNI_YON_MAJORS   = 1   # BTC ve ETH aynı yönde en fazla 1
MAX_AYNI_YON_ALTCOINS = 2
MAX_TOPLAM_EXPOSURE   = 3   # Tüm coinlerde aynı yönde max 3


class CorrelationEngine:
    def __init__(self, max_majors=1, max_altcoins=2, max_toplam=3):
        self._max_majors   = max_majors
        self._max_altcoins = max_altcoins
        self._max_toplam   = max_toplam
        self._lock         = threading.Lock()
        log.info(f"[CORRELATION] Majors:{max_majors} Alts:{max_altcoins} Toplam:{max_toplam}")

    def pozisyon_acilabilir_mi(self, yeni_sembol: str, yeni_yon: str,
                                acik_pozisyonlar: list) -> tuple[bool, str]:
        """
        Yeni pozisyon korelasyon limitine takılıyor mu?
        Returns: (True/False, sebep)
        """
        with self._lock:
            # Mevcut aynı yöndeki pozisyonlar
            ayni_yon = [p for p in acik_pozisyonlar
                        if p.get("yon","").upper() == yeni_yon.upper()]
            ayni_set = {p.get("sembol","") for p in ayni_yon}
            ayni_set.add(yeni_sembol)

            # Toplam limit
            if len(ayni_yon) + 1 > self._max_toplam:
                return False, (f"Toplam {yeni_yon} limiti: {len(ayni_yon)+1} > {self._max_toplam}")

            # MAJORS kontrolü
            majors_acik = ayni_set & KORELASYON_GRUPLARI["MAJORS"]
            if len(majors_acik) > self._max_majors:
                return False, (f"MAJORS korelasyon: {majors_acik} > {self._max_majors} {yeni_yon}")

            # ALTCOINS kontrolü
            alts_acik = ayni_set & KORELASYON_GRUPLARI["ALTCOINS"]
            if len(alts_acik) > self._max_altcoins:
                return False, (f"ALTCOIN korelasyon: {alts_acik} > {self._max_altcoins} {yeni_yon}")

            return True, "OK"

    def portfoy_korelasyon_skoru(self, acik_pozisyonlar: list) -> float:
        """
        Portföy korelasyon skoru 0-1 arası.
        1 = tamamen korelasyonlu (tek trade gibi).
        """
        if len(acik_pozisyonlar) < 2:
            return 0.0
        long_set  = {p["sembol"] for p in acik_pozisyonlar if p.get("yon") == "LONG"}
        short_set = {p["sembol"] for p in acik_pozisyonlar if p.get("yon") == "SHORT"}
        all_set   = long_set | short_set
        # Ne kadarı aynı büyük gruptan?
        maks_grup = 0
        for grup in KORELASYON_GRUPLARI.values():
            overlap = len(all_set & grup)
            maks_grup = max(maks_grup, overlap)
        return round(maks_grup / max(len(all_set), 1), 2)

    def telegram_raporu(self, acik_pozisyonlar: list) -> str:
        skor = self.portfoy_korelasyon_skoru(acik_pozisyonlar)
        uyari = "⚠️ YÜKSEK" if skor > 0.7 else ("🟡 ORTA" if skor > 0.4 else "✅ DÜŞÜK")
        return (f"🔗 <b>KORELASYON</b> {uyari}\n"
                f"Portföy skoru: {skor:.2f}\n"
                f"Açık: {len(acik_pozisyonlar)} pozisyon")


_instance = None
def get_correlation_engine() -> CorrelationEngine:
    global _instance
    if _instance is None:
        try:
            from config import MAX_MAJORS_SAME_DIR, MAX_ALTS_SAME_DIR, MAX_TOPLAM_SAME_DIR
        except ImportError:
            MAX_MAJORS_SAME_DIR=2; MAX_ALTS_SAME_DIR=2; MAX_TOPLAM_SAME_DIR=3
        _instance = CorrelationEngine(MAX_MAJORS_SAME_DIR, MAX_ALTS_SAME_DIR, MAX_TOPLAM_SAME_DIR)
    return _instance
