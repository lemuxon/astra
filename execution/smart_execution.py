# =========================================================
# ASTRA v30.0 — SMART EXECUTION (TWAP / VWAP / Iceberg)
# Büyük emirleri böler → market impact (fiyat etkisi) azaltır.
#
# Neden?
#   Tek seferde 100 USDT market emri → order book'u yer → kötü fiyat.
#   TWAP: Emri N zaman dilimine eşit böl → ortalama fiyat iyileşir.
#   VWAP: Hacme orantılı böl → likit anlarda daha çok al.
#   Iceberg: Büyük emri küçük görünür parçalara böl → gizle.
#
# Eşik: MIN_TWAP_USDT üstündeki emirler bölünür.
# Küçük emirler doğrudan market (gecikme yaratmamak için).
# =========================================================
import logging, time
from dataclasses import dataclass, field
from typing import List, Optional, Callable
import numpy as np

log = logging.getLogger("ASTRA.SMART_EXEC")

# ── Eşikler (config'den override edilebilir) ─────────────
try:
    from config import (MIN_TWAP_USDT, TWAP_DILIM_SAYISI,
                        TWAP_DILIM_ARALIK_SN, SMART_EXEC_ENABLED,
                        TWAP_MAX_SURE_SN)
except ImportError:
    MIN_TWAP_USDT       = 80.0    # Bu USDT üstü emirler bölünür
    TWAP_DILIM_SAYISI   = 4       # Kaç parçaya bölünecek
    TWAP_DILIM_ARALIK_SN= 1.5     # Dilimler arası saniye
    TWAP_MAX_SURE_SN    = 8.0     # Toplam execution süresi tavanı
    SMART_EXEC_ENABLED  = True


@dataclass
class ExecPlan:
    """Bir emrin bölünmüş execution planı."""
    sembol:        str
    yon:           str
    toplam_usdt:   float
    yontem:        str             # MARKET / TWAP / VWAP / ICEBERG
    dilimler:      List[float]     # Her dilimin USDT miktarı
    aralik_sn:     float           # Dilimler arası bekleme
    sebep:         str = ""

    def __str__(self):
        return (f"{self.yontem} {self.sembol} {self.yon} "
                f"{self.toplam_usdt:.1f}USDT → {len(self.dilimler)} dilim")


class SmartExecutor:
    """
    Akıllı emir yürütücü.
    Emir boyutuna ve piyasa koşullarına göre execution stratejisi seçer.
    """

    def __init__(self):
        self._istatistik = {
            "market":  0, "twap": 0, "vwap": 0, "iceberg": 0,
            "toplam_dilim": 0, "ort_slippage_iyilesme_bps": 0.0,
        }

    def plan_olustur(self, sembol: str, yon: str, usdt: float,
                      volatilite_pct: float = 1.0,
                      hacim_profili: Optional[List[float]] = None,
                      likidite_dusuk: bool = False) -> ExecPlan:
        """
        Emir için execution planı oluştur.

        volatilite_pct: ATR/fiyat % — yüksekse daha çok böl
        hacim_profili:  Son saatlerin hacim dağılımı (VWAP için)
        likidite_dusuk: Order book ince mi? → iceberg kullan
        """
        if not SMART_EXEC_ENABLED or usdt < MIN_TWAP_USDT:
            # Küçük emir → doğrudan market
            self._istatistik["market"] += 1
            return ExecPlan(
                sembol=sembol, yon=yon, toplam_usdt=usdt,
                yontem="MARKET", dilimler=[usdt],
                aralik_sn=0, sebep=f"Küçük emir (<{MIN_TWAP_USDT})"
            )

        # Dilim sayısını volatiliteye göre ayarla
        dilim_n = TWAP_DILIM_SAYISI
        if volatilite_pct > 3.0:
            dilim_n = min(TWAP_DILIM_SAYISI + 2, 8)   # Yüksek vol → daha çok böl
        elif volatilite_pct < 1.0:
            dilim_n = max(TWAP_DILIM_SAYISI - 1, 2)   # Düşük vol → az böl

        # ── Düşük likidite → ICEBERG ─────────────────────
        if likidite_dusuk:
            self._istatistik["iceberg"] += 1
            # Eşit ama daha çok küçük parça (gizleme)
            iceberg_n = min(dilim_n + 2, 10)
            dilim_usdt = usdt / iceberg_n
            return ExecPlan(
                sembol=sembol, yon=yon, toplam_usdt=usdt,
                yontem="ICEBERG", dilimler=[dilim_usdt] * iceberg_n,
                aralik_sn=TWAP_DILIM_ARALIK_SN * 1.5,
                sebep="Düşük likidite — gizli emir"
            )

        # ── Hacim profili varsa → VWAP ───────────────────
        if hacim_profili and len(hacim_profili) >= dilim_n:
            self._istatistik["vwap"] += 1
            # Hacme orantılı dağıt
            son_n   = hacim_profili[-dilim_n:]
            toplam_h= sum(son_n) or 1.0
            dilimler= [usdt * (h / toplam_h) for h in son_n]
            # Minimum dilim kontrolü
            dilimler= [max(d, MIN_TWAP_USDT * 0.2) for d in dilimler]
            # Yeniden normalize
            olcek   = usdt / sum(dilimler)
            dilimler= [d * olcek for d in dilimler]
            return ExecPlan(
                sembol=sembol, yon=yon, toplam_usdt=usdt,
                yontem="VWAP", dilimler=dilimler,
                aralik_sn=TWAP_DILIM_ARALIK_SN,
                sebep=f"Hacme orantılı ({dilim_n} dilim)"
            )

        # ── Varsayılan → TWAP (eşit zaman dilimleri) ─────
        self._istatistik["twap"] += 1
        dilim_usdt = usdt / dilim_n
        return ExecPlan(
            sembol=sembol, yon=yon, toplam_usdt=usdt,
            yontem="TWAP", dilimler=[dilim_usdt] * dilim_n,
            aralik_sn=TWAP_DILIM_ARALIK_SN,
            sebep=f"Zaman ağırlıklı ({dilim_n} dilim)"
        )

    def calistir(self, plan: ExecPlan,
                  market_ac_fn: Callable,
                  anlık_fiyat_fn: Callable) -> dict:
        """
        Execution planını uygula. Her dilimi sırayla market emri olarak gönderir.

        market_ac_fn(sembol, yon, usdt) → emir_detay dict
        anlık_fiyat_fn(sembol) → float

        Returns: {basarili, ort_fiyat, toplam_miktar, dilim_sonuclari, slippage_bps}
        """
        if plan.yontem == "MARKET":
            # Tek emir — doğrudan
            try:
                detay = market_ac_fn(plan.sembol, plan.yon, plan.toplam_usdt)
                if detay:
                    return {
                        "basarili": True,
                        "ort_fiyat": float(detay.get("avgPrice", 0)),
                        "toplam_miktar": float(detay.get("executedQty", 0)),
                        "dilim_sonuclari": [detay],
                        "yontem": "MARKET",
                    }
                return {"basarili": False, "hata": "Market emri başarısız"}
            except Exception as e:
                return {"basarili": False, "hata": str(e)}

        # ── Bölünmüş execution ───────────────────────────
        baslangic_fiyat = anlık_fiyat_fn(plan.sembol) or 0
        dilim_sonuclari = []
        toplam_miktar   = 0.0
        toplam_maliyet  = 0.0
        basarili_dilim  = 0

        log.info(f"[SMART EXEC] {plan} başlatılıyor")

        # v23: Toplam execution süresini TWAP_MAX_SURE_SN ile sınırla (SL gecikme koruması)
        _n_bekleme = max(len(plan.dilimler) - 1, 1)
        _efektif_aralik = min(plan.aralik_sn, TWAP_MAX_SURE_SN / _n_bekleme)

        for i, dilim_usdt in enumerate(plan.dilimler):
            try:
                # v23: İlk dilim normal (duplicate kontrolü geçerli),
                # sonraki dilimler _ic_slice=True (cooldown/pozisyon kontrolü atlanır)
                _slice_flag = (i > 0)
                try:
                    detay = market_ac_fn(plan.sembol, plan.yon, dilim_usdt,
                                         _ic_slice=_slice_flag)
                except TypeError:
                    # market_ac_fn _ic_slice parametresini desteklemiyorsa (test/mock)
                    detay = market_ac_fn(plan.sembol, plan.yon, dilim_usdt)
                if detay:
                    fiyat  = float(detay.get("avgPrice", 0))
                    miktar = float(detay.get("executedQty", 0))
                    if fiyat > 0 and miktar > 0:
                        toplam_miktar  += miktar
                        toplam_maliyet += fiyat * miktar
                        basarili_dilim += 1
                    dilim_sonuclari.append(detay)
                    log.info(f"[SMART EXEC] Dilim {i+1}/{len(plan.dilimler)} "
                             f"@ {fiyat:.4f} ({dilim_usdt:.1f}USDT)")

                # Son dilim değilse bekle
                if i < len(plan.dilimler) - 1:
                    time.sleep(_efektif_aralik)

            except Exception as e:
                log.error(f"[SMART EXEC] Dilim {i+1} hatası: {e}")
                dilim_sonuclari.append({"hata": str(e)})

        self._istatistik["toplam_dilim"] += len(plan.dilimler)

        ort_fiyat = toplam_maliyet / toplam_miktar if toplam_miktar > 0 else 0

        # Slippage iyileşmesi: bölünmüş ort fiyat vs başlangıç fiyat
        if baslangic_fiyat > 0 and ort_fiyat > 0:
            slippage_bps = abs(ort_fiyat - baslangic_fiyat) / baslangic_fiyat * 10000
        else:
            slippage_bps = 0

        return {
            "basarili": basarili_dilim > 0,
            "ort_fiyat": round(ort_fiyat, 4),
            "toplam_miktar": round(toplam_miktar, 6),
            "dilim_sonuclari": dilim_sonuclari,
            "basarili_dilim": basarili_dilim,
            "toplam_dilim": len(plan.dilimler),
            "slippage_bps": round(slippage_bps, 2),
            "yontem": plan.yontem,
        }

    def istatistik(self) -> dict:
        return dict(self._istatistik)

    def telegram_raporu(self) -> str:
        s = self._istatistik
        return (
            f"⚡ <b>SMART EXECUTION v22</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Market : {s['market']}\n"
            f"TWAP   : {s['twap']}\n"
            f"VWAP   : {s['vwap']}\n"
            f"Iceberg: {s['iceberg']}\n"
            f"Toplam dilim: {s['toplam_dilim']}"
        )


# ── Singleton ─────────────────────────────────────────────
_smart_executor: Optional[SmartExecutor] = None

def get_smart_executor() -> SmartExecutor:
    global _smart_executor
    if _smart_executor is None:
        _smart_executor = SmartExecutor()
    return _smart_executor
