# =========================================================
# ASTRA v30.0 — EDGE ANALYTİCS
# Expectancy, Profit Factor Decay, Regime WinRate, Sharpe by Vol
# =========================================================
import logging, math
from collections import defaultdict
from typing import Optional
import sys; sys.path.append("..")

log = logging.getLogger("ASTRA.EDGE_ANALYTICS")


class EdgeAnalytics:
    """
    Trade verisinden gerçek edge metrikleri:
    - Expectancy (beklenti değeri)
    - Profit Factor (ve zamansal bozunma)
    - Rejim bazlı WinRate
    - Volatilite rejimine göre Sharpe
    - Execution latency impact
    """

    def __init__(self):
        self._islemler: list = []   # Her kapanan işlem

    def islem_ekle(self, pnl_usdt: float, pnl_pct: float,
                    rejim: str, volatility_pct: float,
                    latency_ms: float, strateji: str, yon: str,
                    sembol: str, ts: float):
        self._islemler.append({
            "pnl_usdt":      pnl_usdt,
            "pnl_pct":       pnl_pct,
            "rejim":         rejim,
            "vol_pct":       volatility_pct,
            "latency_ms":    latency_ms,
            "strateji":      strateji,
            "yon":           yon,
            "sembol":        sembol,
            "ts":            ts,
            "kazandi":       pnl_usdt > 0,
        })
        if len(self._islemler) > 2000:
            self._islemler = self._islemler[-2000:]

    def expectancy(self, son_n: int = 100) -> dict:
        """
        Expectancy = WinRate × AvgWin - LossRate × AvgLoss
        Pozitif = beklenen kar, Negatif = beklenen zarar per işlem
        """
        islemler = self._islemler[-son_n:] if len(self._islemler) > son_n else self._islemler
        if not islemler:
            return {"expectancy_usdt": 0, "expectancy_pct": 0, "r_multiple": 0}

        kazananlar = [t["pnl_usdt"] for t in islemler if t["pnl_usdt"] > 0]
        kaybedenler= [t["pnl_usdt"] for t in islemler if t["pnl_usdt"] <= 0]
        n = len(islemler)

        wr         = len(kazananlar) / n
        avg_win    = sum(kazananlar) / len(kazananlar) if kazananlar else 0
        avg_loss   = sum(kaybedenler) / len(kaybedenler) if kaybedenler else 0
        expectancy = wr * avg_win + (1-wr) * avg_loss
        r_multiple = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        return {
            "expectancy_usdt": round(expectancy, 4),
            "win_rate_pct":    round(wr * 100, 1),
            "avg_win":         round(avg_win, 4),
            "avg_loss":        round(avg_loss, 4),
            "r_multiple":      round(r_multiple, 2),
            "n":               n,
        }

    def profit_factor_decay(self, pencere: int = 20) -> dict:
        """
        Profit Factor zamansal bozunması:
        Son N işlemde PF vs tüm işlemler PF.
        Düşüşü varsa model bozunuyor.
        """
        if len(self._islemler) < pencere * 2:
            return {"pf_tumü": 0, "pf_son": 0, "decay": 0, "alarm": False}

        def _pf(lst):
            kazanc = sum(t["pnl_usdt"] for t in lst if t["pnl_usdt"] > 0)
            kayip  = abs(sum(t["pnl_usdt"] for t in lst if t["pnl_usdt"] < 0))
            return round(kazanc / kayip, 3) if kayip > 0 else 999.0

        pf_tum = _pf(self._islemler)
        pf_son = _pf(self._islemler[-pencere:])
        decay  = round((pf_son - pf_tum) / max(pf_tum, 0.01), 3)

        return {
            "pf_tumu": pf_tum,
            "pf_son":  pf_son,
            "decay":   decay,
            "alarm":   decay < -0.3,   # PF %30 düşüşü alarm
        }

    def regime_winrate(self) -> dict:
        """Her rejim için ayrı WinRate."""
        rejim_data = defaultdict(list)
        for t in self._islemler:
            rejim_data[t["rejim"]].append(t["kazandi"])
        return {
            r: {
                "win_rate": round(sum(v)/len(v)*100, 1),
                "n":        len(v),
                "tavsiye":  "✅ İyi" if sum(v)/len(v) > 0.55 else
                            ("⚠️ Zayıf" if sum(v)/len(v) > 0.40 else "❌ Dur"),
            }
            for r, v in rejim_data.items() if len(v) >= 3
        }

    def sharpe_by_volatility(self) -> dict:
        """Düşük/orta/yüksek volatilite bantlarında Sharpe."""
        bantlar = {"dusuk": [], "orta": [], "yuksek": []}
        for t in self._islemler:
            v = t.get("vol_pct", 0)
            if v < 1.0:   bantlar["dusuk"].append(t["pnl_pct"])
            elif v < 2.5: bantlar["orta"].append(t["pnl_pct"])
            else:         bantlar["yuksek"].append(t["pnl_pct"])

        def _sharpe(lst):
            if len(lst) < 3: return None
            import statistics
            ort = statistics.mean(lst)
            std = statistics.stdev(lst)
            return round(ort / std * math.sqrt(252), 3) if std > 0 else 0

        return {b: {"sharpe": _sharpe(v), "n": len(v)} for b, v in bantlar.items()}

    def latency_impact(self) -> dict:
        """Yüksek latency'nin PnL'e etkisi."""
        if not self._islemler:
            return {}
        hizli  = [t["pnl_pct"] for t in self._islemler if t.get("latency_ms", 0) < 100]
        yavas  = [t["pnl_pct"] for t in self._islemler if t.get("latency_ms", 0) >= 100]
        ort_h  = round(sum(hizli)/len(hizli), 3)  if hizli else 0
        ort_y  = round(sum(yavas)/len(yavas), 3)  if yavas else 0
        return {"hizli_ort_pnl": ort_h, "yavas_ort_pnl": ort_y,
                "fark": round(ort_h - ort_y, 3), "hizli_n": len(hizli), "yavas_n": len(yavas)}

    def tam_rapor(self) -> dict:
        return {
            "expectancy":         self.expectancy(),
            "profit_factor_decay":self.profit_factor_decay(),
            "regime_winrate":     self.regime_winrate(),
            "sharpe_by_vol":      self.sharpe_by_volatility(),
            "latency_impact":     self.latency_impact(),
        }

    def telegram_raporu(self) -> str:
        exp = self.expectancy()
        pfd = self.profit_factor_decay()
        rwr = self.regime_winrate()
        if exp["n"] == 0:
            return "📐 <b>EDGE ANALYTICS</b>\nYetersiz veri."
        rejim_str = "\n".join(
            f"  {r}: %{d['win_rate']} {d['tavsiye']} ({d['n']} işlem)"
            for r, d in rwr.items()
        )
        decay_uyari = "⚠️ MODEL BOZUNUYOR!" if pfd.get("alarm") else "✅ Stabil"
        return (
            f"📐 <b>EDGE ANALYTICS v16</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Expectancy: {exp['expectancy_usdt']:+.4f}$/işlem\n"
            f"📊 WinRate: %{exp['win_rate_pct']} | R-Multiple: {exp['r_multiple']:.2f}\n"
            f"📉 PF Tümü: {pfd['pf_tumu']:.2f} | Son: {pfd['pf_son']:.2f} {decay_uyari}\n"
            f"🏛️ Rejim WinRate:\n{rejim_str}"
        )


_instance = None
def get_edge_analytics() -> EdgeAnalytics:
    global _instance
    if _instance is None:
        _instance = EdgeAnalytics()
    return _instance
