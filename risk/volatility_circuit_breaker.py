# =========================================================
# ASTRA v30.0 — VOLATİLİTE CIRCUIT BREAKER
# =========================================================
import logging, time, threading
from dataclasses import dataclass, field
from typing import Optional, Callable
import sys; sys.path.append("..")

log = logging.getLogger("ASTRA.CIRCUIT_BREAKER")

class VolatilityCircuitBreaker:
    def __init__(self, max_atr_pct=4.0, max_funding_rate=0.003,
                 max_spread_pct=0.15, atr_spike_katsayi=2.5,
                 bekleme_suresi=300, telegram_fn=None):
        self._max_atr     = max_atr_pct
        self._max_funding = max_funding_rate
        self._max_spread  = max_spread_pct
        self._atr_spike   = atr_spike_katsayi
        self._bekleme     = bekleme_suresi
        self._telegram    = telegram_fn
        self._lock        = threading.Lock()
        # ── v58 (K-78): DURUM SEMBOL BAŞINA ──────────────────────
        # ESKİ HÂLİ tek `_aktif` / `_sebep` / `_bekleme_bitis` alanıydı,
        # ama TÜM tetikleyiciler sembol bazlı (`atr_guncelle(sembol,…)`,
        # `funding_guncelle(sembol,…)`). Yani BİR coinin yüksek ATR'si
        # BÜTÜN evreni 300 sn durduruyordu.
        #
        # ÖLÇÜLEN VAKA (2026-09-10 02:32, 50 coine geçişten 3 dk sonra):
        #     [CIRCUIT BREAKER] ATR çok yüksek PROMUSDT: %4.78 — 300s dur
        #     [PROMUSDT] Circuit Breaker aktif — analiz atlandı
        #     [SOLUSDT]  Circuit Breaker aktif — analiz atlandı   ← başka coin
        #     [XRPUSDT]  Circuit Breaker aktif — analiz atlandı   ← başka coin
        #     [BNBUSDT]  Circuit Breaker aktif — analiz atlandı   ← başka coin
        # 4 dakikada 17 tetiklenme. 5 coinde nadirdi; 50 coinde volatil
        # altcoin (PROM, NEAR, PUMP…) HER ZAMAN bulunur → bot sürekli donar.
        # K-71 (rejim) ile aynı sınıf: sembol bazlı olması gereken durumun
        # tek global alanda tutulması.
        self._durum: dict = {}          # sembol → {"aktif","sebep","bitis"}
        self._tetiklenme_sayisi = 0
        self._atr_gecmis: dict = {}
        log.info(f"[CIRCUIT BREAKER] MaxATR:{max_atr_pct}% MaxFunding:{max_funding_rate*100:.2f}%")

    _GENEL = "_GENEL"

    def kontrol(self, sembol=None) -> bool:
        """Bu SEMBOL işlem yapabilir mi? (sembol yoksa genel kova)"""
        anahtar = sembol or self._GENEL
        with self._lock:
            d = self._durum.get(anahtar)
            if d is None:
                return True
            if not d["aktif"] and time.time() >= d["bitis"]:
                d["aktif"] = True; d["sebep"] = ""
                log.info(f"[CIRCUIT BREAKER] ✅ {anahtar} yeniden aktif")
            if not d["aktif"]:
                log.debug(f"[CIRCUIT BREAKER] {anahtar} kapalı: {d['sebep']}")
            return d["aktif"]

    def atr_guncelle(self, sembol: str, atr: float, fiyat: float) -> bool:
        if fiyat <= 0: return True
        atr_pct = atr / fiyat * 100
        with self._lock:
            g = self._atr_gecmis.setdefault(sembol, [])
            g.append(atr_pct)
            if len(g) > 20: g.pop(0)
            if len(g) >= 10:
                s5  = sum(g[-5:]) / 5
                s20 = sum(g) / len(g)
                if s20 > 0 and s5 / s20 > self._atr_spike:
                    self._tetikle(f"ATR spike {sembol}: {s5:.2f}% ({self._atr_spike:.1f}x)", sembol)
                    return False
            if atr_pct > self._max_atr:
                self._tetikle(f"ATR çok yüksek {sembol}: %{atr_pct:.2f}", sembol)
                return False
        return True

    def funding_guncelle(self, sembol: str, funding_rate: float) -> bool:
        if abs(funding_rate) > self._max_funding:
            with self._lock:
                self._tetikle(f"Funding spike {sembol}: %{funding_rate*100:.4f}", sembol)
            return False
        return True

    def spread_kontrol(self, sembol: str, bid: float, ask: float) -> bool:
        if bid <= 0 or ask <= 0: return True
        mid = (bid + ask) / 2
        sp  = (ask - bid) / mid * 100
        if sp > self._max_spread:
            log.warning(f"[CIRCUIT BREAKER] Spread geniş {sembol}: %{sp:.4f}")
            return False
        return True

    def _tetikle(self, sebep: str, sembol=None):
        # lock içinden çağrılmalı
        anahtar = sembol or self._GENEL
        self._durum[anahtar] = {"aktif": False, "sebep": sebep,
                                "bitis": time.time() + self._bekleme}
        self._tetiklenme_sayisi += 1
        log.warning(f"[CIRCUIT BREAKER] ⚡ {sebep} — {anahtar} {self._bekleme}s dur")
        if self._telegram:
            try:
                # v58 (K-78): `force=True` KALDIRILDI. Throttle'ı atlıyordu;
                # 50 coinde 4 dakikada 17 mesaj gitti. Tek `tip` kullanılıyor
                # ki çok sayıda coin aynı anda tetiklense bile Telegram'a
                # throttle aralığında en fazla bir mesaj düşsün. Log ise
                # HER tetiklenmeyi yazmaya devam ediyor (teşhis kaybolmaz).
                self._telegram(f"⚡ <b>CIRCUIT BREAKER</b>\n{sebep}\n{self._bekleme}s duraklama",
                               tip="circuit_breaker")
            except Exception: pass

    @property
    def durum(self) -> dict:
        """Özet: kaç sembol duraklatılmış, hangileri (v58 K-78)."""
        simdi = time.time()
        with self._lock:
            duran = {k: v for k, v in self._durum.items()
                     if not v["aktif"] and simdi < v["bitis"]}
            kalan = round(max([v["bitis"] - simdi for v in duran.values()],
                              default=0))
            return {"aktif": not duran,
                    "duraklatilan": sorted(duran),
                    "duraklatilan_sayisi": len(duran),
                    "sebep": "; ".join(f"{k}: {v['sebep']}"
                                       for k, v in sorted(duran.items()))[:300],
                    "kalan_s": kalan,
                    "tetiklenme": self._tetiklenme_sayisi}

    def telegram_raporu(self) -> str:
        d = self.durum
        return (f"⚡ <b>CIRCUIT BREAKER</b>\n"
                f"Durum: {'✅ Tüm coinler açık' if d['aktif'] else '🛑 ' + str(d['duraklatilan_sayisi']) + ' coin duraklatıldı'}\n"
                f"Tetiklenme: {d['tetiklenme']}\n"
                f"{'Duraklatılan: ' + ', '.join(d['duraklatilan'][:8]) if d['duraklatilan'] else ''}\n"
                f"{'Kalan: ' + str(d['kalan_s']) + 's' if not d['aktif'] else ''}")


_instance = None
def get_circuit_breaker(telegram_fn=None) -> VolatilityCircuitBreaker:
    global _instance
    if _instance is None:
        try:
            from config import (MAX_ATR_PCT, MAX_FUNDING_RATE, MAX_SPREAD_PCT,
                                CIRCUIT_BREAKER_BEKLEME)
        except ImportError:
            MAX_ATR_PCT=4.0; MAX_FUNDING_RATE=0.003
            MAX_SPREAD_PCT=0.15; CIRCUIT_BREAKER_BEKLEME=300
        _instance = VolatilityCircuitBreaker(MAX_ATR_PCT, MAX_FUNDING_RATE,
                                              MAX_SPREAD_PCT, 2.5,
                                              CIRCUIT_BREAKER_BEKLEME, telegram_fn)
    return _instance
