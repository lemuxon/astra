# =========================================================
# ASTRA v30.0 — ÇOKLU BORSA FİYAT DOĞRULAMA + ARBİTRAJ
# Bybit ve OKX'in PUBLIC ticker API'lerinden fiyat çekip
# Binance fiyatıyla karşılaştırır. İki işlevi var:
#
#   1. FİYAT DOĞRULAMA (güvenlik):
#      Binance fiyatı diğer borsalardan çok saparsa → şüpheli.
#      Manipülasyon / hatalı veri / wick'e karşı işlem engellenir.
#
#   2. ARBİTRAJ SİNYALİ (fırsat):
#      Bir borsada fiyat diğerlerinden önce hareket ederse,
#      bu kısa vadeli yön sinyali olarak kullanılır (doğrudan
#      arbitraj DEĞİL — momentum öncülü).
#
# Harici kütüphane YOK — sadece requests. Anahtar gerektirmez
# (public endpoint'ler). Bir borsa erişilemezse sessizce atlanır.
# =========================================================
import logging, time, threading
from typing import Dict, Optional, List
from dataclasses import dataclass
import requests

log = logging.getLogger("ASTRA.MULTIEXCHANGE")

try:
    from config import (
        MULTIEX_ENABLED, MULTIEX_MAX_SAPMA_PCT,
        MULTIEX_ARBITRAJ_ESIK_PCT, MULTIEX_CACHE_TTL,
    )
except ImportError:
    MULTIEX_ENABLED          = True
    MULTIEX_MAX_SAPMA_PCT    = 1.0   # Binance bu %'den fazla saparsa → veto
    MULTIEX_ARBITRAJ_ESIK_PCT= 0.15  # Borsalar arası bu fark → arbitraj sinyali
    MULTIEX_CACHE_TTL        = 3.0   # Fiyat cache süresi (saniye)


# ── Sembol dönüşümü ──────────────────────────────────────
# Binance: BTCUSDT | Bybit: BTCUSDT | OKX: BTC-USDT-SWAP
def _bybit_sembol(s: str) -> str:
    return s.upper()

def _okx_sembol(s: str) -> str:
    s = s.upper()
    if s.endswith("USDT"):
        return f"{s[:-4]}-USDT-SWAP"
    return s


@dataclass
class FiyatKarsilastirma:
    sembol:          str
    binance:         float
    bybit:           Optional[float]
    okx:             Optional[float]
    ortalama:        float            # mevcut borsaların ortalaması
    medyan:          float
    binance_sapma:   float            # Binance'in medyandan % sapması
    max_fark_pct:    float            # en yüksek-en düşük arası %
    kaynak_sayisi:   int              # kaç borsadan veri alındı
    guvenilir:       bool             # fiyat doğrulamadan geçti mi
    arbitraj_yon:    Optional[str]    # LONG/SHORT/None (momentum öncülü)
    arbitraj_gucu:   float            # sinyal gücü 0-1
    sebep:           str = ""


class MultiExchangePriceEngine:
    """
    Bybit + OKX public ticker'larını çeker, Binance ile karşılaştırır.
    Thread-safe cache ile çoklu coin paralel analizinde verimli çalışır.
    """

    def __init__(self):
        self._cache: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._istatistik = {
            "veto": 0, "arbitraj_long": 0, "arbitraj_short": 0,
            "bybit_basari": 0, "bybit_hata": 0,
            "okx_basari": 0, "okx_hata": 0,
        }

    # ── Borsa fiyat çekiciler ────────────────────────────
    def _bybit_fiyat(self, sembol: str) -> Optional[float]:
        try:
            r = requests.get(
                "https://api.bybit.com/v5/market/tickers",
                params={"category": "linear", "symbol": _bybit_sembol(sembol)},
                timeout=4
            )
            r.raise_for_status()
            data = r.json()
            lst = data.get("result", {}).get("list", [])
            if lst:
                fiyat = float(lst[0].get("lastPrice", 0))
                if fiyat > 0:
                    self._istatistik["bybit_basari"] += 1
                    return fiyat
        except Exception as e:
            log.debug(f"[BYBIT] {sembol} hata: {e}")
        self._istatistik["bybit_hata"] += 1
        return None

    def _okx_fiyat(self, sembol: str) -> Optional[float]:
        try:
            r = requests.get(
                "https://www.okx.com/api/v5/market/ticker",
                params={"instId": _okx_sembol(sembol)},
                timeout=4
            )
            r.raise_for_status()
            data = r.json()
            lst = data.get("data", [])
            if lst:
                fiyat = float(lst[0].get("last", 0))
                if fiyat > 0:
                    self._istatistik["okx_basari"] += 1
                    return fiyat
        except Exception as e:
            log.debug(f"[OKX] {sembol} hata: {e}")
        self._istatistik["okx_hata"] += 1
        return None

    # ── Ana karşılaştırma ────────────────────────────────
    def karsilastir(self, sembol: str, binance_fiyat: float) -> FiyatKarsilastirma:
        """
        Binance fiyatını Bybit + OKX ile karşılaştır.
        Fiyat doğrulama + arbitraj yön sinyali döner.
        """
        if not MULTIEX_ENABLED or binance_fiyat <= 0:
            return self._gecerli_varsayilan(sembol, binance_fiyat)

        # Cache kontrolü
        with self._lock:
            c = self._cache.get(sembol)
            if c and time.time() - c["ts"] < MULTIEX_CACHE_TTL:
                cached = c["sonuc"]
                # Binance fiyatını güncelle (cache'teki diğer borsalar geçerli)
                # v55: eskiden `cached.get(...)` çağrılıyordu — `cached` bir
                # FiyatKarsilastirma dataclass'ı olduğu için .get() yok →
                # her cache isabetinde AttributeError → main.py'da log.debug ile
                # yutuluyor ve fiyat sapma VETOSU hiç çalışmıyordu.
                # Ham önceki fiyatlar cache DICT'inde (c) tutuluyor.
                return self._yeniden_hesapla(sembol, binance_fiyat,
                                             cached.bybit, cached.okx,
                                             c.get("bybit_ham"),
                                             c.get("okx_ham"))

        bybit = self._bybit_fiyat(sembol)
        okx   = self._okx_fiyat(sembol)

        # Önceki değerleri al (arbitraj momentum için)
        with self._lock:
            onceki = self._cache.get(sembol, {})
            bybit_onceki = onceki.get("bybit_ham")
            okx_onceki   = onceki.get("okx_ham")

        sonuc = self._yeniden_hesapla(sembol, binance_fiyat, bybit, okx,
                                      bybit_onceki, okx_onceki)

        with self._lock:
            self._cache[sembol] = {
                "ts": time.time(), "sonuc": sonuc,
                "bybit_ham": bybit, "okx_ham": okx,
            }
        return sonuc

    def _yeniden_hesapla(self, sembol, binance, bybit, okx,
                          bybit_onceki=None, okx_onceki=None) -> FiyatKarsilastirma:
        fiyatlar = [binance]
        if bybit: fiyatlar.append(bybit)
        if okx:   fiyatlar.append(okx)
        kaynak = len(fiyatlar)

        ortalama = sum(fiyatlar) / kaynak
        sirali   = sorted(fiyatlar)
        medyan   = sirali[len(sirali)//2] if kaynak % 2 == 1 else \
                   (sirali[kaynak//2-1] + sirali[kaynak//2]) / 2

        binance_sapma = abs(binance - medyan) / medyan * 100 if medyan > 0 else 0
        max_fark = (max(fiyatlar) - min(fiyatlar)) / min(fiyatlar) * 100 if min(fiyatlar) > 0 else 0

        # ── FİYAT DOĞRULAMA ──────────────────────────────
        # Tek kaynak varsa (diğer borsalar erişilemedi) → doğrulama yapma, güven ver
        if kaynak == 1:
            guvenilir = True
            sebep = "tek kaynak (diğer borsalar erişilemedi) — doğrulama atlandı"
        elif binance_sapma > MULTIEX_MAX_SAPMA_PCT:
            guvenilir = False
            sebep = (f"Binance medyandan %{binance_sapma:.2f} sapıyor "
                     f"(eşik %{MULTIEX_MAX_SAPMA_PCT}) — şüpheli fiyat, işlem veto")
            self._istatistik["veto"] += 1
        else:
            guvenilir = True
            sebep = f"fiyat doğrulandı ({kaynak} borsa, sapma %{binance_sapma:.2f})"

        # ── ARBİTRAJ YÖN SİNYALİ ─────────────────────────
        # Diğer borsalar Binance'ten yüksekse → yukarı baskı (LONG öncülü)
        # Mantık: bir borsada fiyat önce hareket eder, diğerleri takip eder
        arbitraj_yon = None
        arbitraj_gucu = 0.0
        if kaynak >= 2 and guvenilir:
            digerleri = [f for f in [bybit, okx] if f]
            if digerleri:
                diger_ort = sum(digerleri) / len(digerleri)
                fark_pct = (diger_ort - binance) / binance * 100
                if abs(fark_pct) >= MULTIEX_ARBITRAJ_ESIK_PCT:
                    if fark_pct > 0:
                        arbitraj_yon = "LONG"   # diğerleri yüksek → Binance yükselebilir
                        self._istatistik["arbitraj_long"] += 1
                    else:
                        arbitraj_yon = "SHORT"
                        self._istatistik["arbitraj_short"] += 1
                    # Güç: farkın eşiğe oranı (0-1 arası clamp)
                    arbitraj_gucu = min(abs(fark_pct) / (MULTIEX_ARBITRAJ_ESIK_PCT * 4), 1.0)

        return FiyatKarsilastirma(
            sembol=sembol, binance=binance, bybit=bybit, okx=okx,
            ortalama=round(ortalama, 6), medyan=round(medyan, 6),
            binance_sapma=round(binance_sapma, 3),
            max_fark_pct=round(max_fark, 3), kaynak_sayisi=kaynak,
            guvenilir=guvenilir, arbitraj_yon=arbitraj_yon,
            arbitraj_gucu=round(arbitraj_gucu, 3), sebep=sebep,
        )

    def _gecerli_varsayilan(self, sembol, fiyat) -> FiyatKarsilastirma:
        return FiyatKarsilastirma(
            sembol=sembol, binance=fiyat, bybit=None, okx=None,
            ortalama=fiyat, medyan=fiyat, binance_sapma=0,
            max_fark_pct=0, kaynak_sayisi=1, guvenilir=True,
            arbitraj_yon=None, arbitraj_gucu=0, sebep="çoklu borsa devre dışı",
        )

    def istatistik(self) -> dict:
        return dict(self._istatistik)

    def telegram_raporu(self) -> str:
        s = self._istatistik
        by_top = s["bybit_basari"] + s["bybit_hata"]
        ok_top = s["okx_basari"] + s["okx_hata"]
        by_oran = (s["bybit_basari"]/by_top*100) if by_top else 0
        ok_oran = (s["okx_basari"]/ok_top*100) if ok_top else 0
        return (
            f"🌐 <b>ÇOKLU BORSA v26</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🛡️ Fiyat veto       : {s['veto']}\n"
            f"📈 Arbitraj LONG    : {s['arbitraj_long']}\n"
            f"📉 Arbitraj SHORT   : {s['arbitraj_short']}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Bybit erişim : %{by_oran:.0f} ({s['bybit_basari']}/{by_top})\n"
            f"OKX erişim   : %{ok_oran:.0f} ({s['okx_basari']}/{ok_top})"
        )


# ── Singleton ─────────────────────────────────────────────
_engine: Optional[MultiExchangePriceEngine] = None

def get_multiexchange() -> MultiExchangePriceEngine:
    global _engine
    if _engine is None:
        _engine = MultiExchangePriceEngine()
    return _engine
