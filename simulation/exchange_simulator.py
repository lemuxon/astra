# =========================================================
# ASTRA v30.0 — EXCHANGE SIMULATION LAYER
# Gerçekçi paper execution: latency, slippage, partial fill
# Senaryo testleri: NORMAL, STRESS, CRASH, LATENCY
# =========================================================
import logging, time, random
import numpy as np
import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, List
import sys; sys.path.append("..")
from config import (SIM_LATENCY_MEAN_MS, SIM_LATENCY_STD_MS,
                    SIM_LATENCY_SPIKE_P, SIM_SLIPPAGE_BASE_BP,
                    SIM_PARTIAL_FILL_P, SIM_DEFAULT_SCENARIO,
                    LIVE_TRADING)

log = logging.getLogger("ASTRA.SIM")


@dataclass
class SimSonuc:
    kabul_edildi:    bool
    sembol:          str
    yon:             str
    senaryo:         str
    beklenen_fiyat:  float
    sim_fiyat:       float       # Slippage sonrası gerçek fiyat
    slippage_bps:    float       # Basis points cinsinden slippage
    latency_ms:      float       # Simüle edilen gecikme
    fill_pct:        float       # %100 = tam dolu
    red_sebebi:      str = ""

    @property
    def slippage_pct(self) -> float:
        return self.slippage_bps / 10000 * 100

    @property
    def maliyet_pct(self) -> float:
        """Toplam maliyet: slippage + gecikme maliyeti."""
        return self.slippage_pct + (self.latency_ms / 1000 * 0.001)  # gecikme proxy

    def __str__(self):
        d = "✅" if self.kabul_edildi else "❌"
        return (f"{d} {self.sembol} {self.yon} [{self.senaryo}] "
                f"@ {self.sim_fiyat:.4f} (beklenen:{self.beklenen_fiyat:.4f}) "
                f"slip:{self.slippage_bps:.1f}bps lat:{self.latency_ms:.0f}ms "
                f"fill:%{self.fill_pct:.0f}")


class Senaryo:
    """Senaryo parametreleri."""

    PROFILLER = {
        "NORMAL": {
            "latency_mult":    1.0,
            "slippage_mult":   1.0,
            "partial_fill_p":  SIM_PARTIAL_FILL_P,
            "red_p":           0.01,   # %1 red
            "aciklama":        "Normal piyasa koşulları",
        },
        "STRESS": {
            "latency_mult":    3.5,
            "slippage_mult":   5.0,
            "partial_fill_p":  0.25,
            "red_p":           0.05,
            "aciklama":        "Yüksek volatilite — spread açık, emirler yavaş",
        },
        "CRASH": {
            "latency_mult":    8.0,
            "slippage_mult":   20.0,
            "partial_fill_p":  0.50,
            "red_p":           0.15,
            "aciklama":        "Flash crash / aşırı volatilite — borsa aşırı yüklü",
        },
        "LATENCY": {
            "latency_mult":    15.0,
            "slippage_mult":   2.0,
            "partial_fill_p":  0.10,
            "red_p":           0.03,
            "aciklama":        "Yüksek latency (VPS/ağ sorunu simülasyonu)",
        },
    }

    @classmethod
    def profil(cls, senaryo: str) -> dict:
        return cls.PROFILLER.get(senaryo.upper(), cls.PROFILLER["NORMAL"])


class ExchangeSimulator:
    """
    Binance'i simüle eden paper execution motoru.
    LIVE_TRADING=false olduğunda gerçek emirler yerine bu kullanılır.

    Özellikler:
    - Log-normal latency dağılımı (gerçekçi ağ gecikmesi)
    - Hacim + volatilite bağımlı slippage modeli
    - Kısmi fill simülasyonu
    - Senaryo bazlı stres testi (NORMAL/STRESS/CRASH/LATENCY)
    - Tüm sim trades DB'ye kaydedilir
    """

    def __init__(self, senaryo: str = SIM_DEFAULT_SCENARIO):
        self.senaryo         = senaryo.upper()
        self._istatistik     = {
            "toplam": 0, "kabul": 0, "red": 0,
            "kısmi_fill": 0, "toplam_slippage_bps": 0,
            "toplam_latency_ms": 0,
        }
        self._gecmis: list = []   # son 100 işlem

    # ──────────────────────────────────────────────────────
    # Gecikme Simülasyonu
    # ──────────────────────────────────────────────────────

    def latency_sim(self, senaryo_profil: dict) -> float:
        """
        Log-normal latency dağılımı.
        Gerçek borsa API'lerinde gözlemlenen dağılıma yakın.
        %5 olasılıkla spike (bağlantı sorunu, overload).
        """
        mult = senaryo_profil["latency_mult"]
        mu   = SIM_LATENCY_MEAN_MS * mult
        std  = SIM_LATENCY_STD_MS  * mult

        # Log-normal parametreler
        sigma_ln = np.sqrt(np.log(1 + (std/mu)**2))
        mu_ln    = np.log(mu) - sigma_ln**2 / 2
        latency  = float(np.random.lognormal(mu_ln, sigma_ln))

        # Latency spike
        if random.random() < SIM_LATENCY_SPIKE_P * mult:
            spike   = float(np.random.uniform(200, 2000) * mult)
            latency = max(latency, spike)
            log.debug(f"[SIM] Latency spike: {latency:.0f}ms")

        return round(min(latency, 5000), 1)  # max 5s cap

    # ──────────────────────────────────────────────────────
    # Slippage Simülasyonu
    # ──────────────────────────────────────────────────────

    def slippage_sim(self, fiyat: float, miktar_usdt: float,
                      yon: str, senaryo_profil: dict,
                      volatilite_pct: float = 1.0) -> float:
        """
        Slippage modeli:
        - Temel slippage: SIM_SLIPPAGE_BASE_BP
        - Miktar etkisi: büyük emir daha fazla slippage
        - Volatilite etkisi: yüksek vol = geniş spread
        - Senaryo çarpanı

        Döner: slippage basis points (1 bps = 0.01%)
        """
        mult = senaryo_profil["slippage_mult"]

        # Temel slippage (log-normal — simetrik değil, sağa çarpık)
        baz_slip = float(np.random.lognormal(
            np.log(SIM_SLIPPAGE_BASE_BP), 0.5
        )) * mult

        # Miktar etkisi: her 1000$ için +0.5bps
        miktar_etkisi = (miktar_usdt / 1000) * 0.5 * mult

        # Volatilite etkisi
        vol_etkisi = volatilite_pct * 0.3 * mult

        toplam_bps = baz_slip + miktar_etkisi + vol_etkisi

        # Yön: LONG için fiyat yukarı, SHORT için aşağı kayar
        isaret = 1 if yon == "LONG" else -1
        return round(toplam_bps * isaret, 4)

    # ──────────────────────────────────────────────────────
    # Partial Fill Simülasyonu
    # ──────────────────────────────────────────────────────

    def fill_sim(self, senaryo_profil: dict) -> float:
        """
        Kısmi fill olasılığı ve miktarı.
        Normal: %92 tam fill. Crash: %50 tam fill.
        Döner: fill yüzdesi (0-100)
        """
        kısmi_p = senaryo_profil["partial_fill_p"]
        if random.random() < kısmi_p:
            # Kısmi fill: %60-95 arası uniform
            return float(np.random.uniform(60, 95))
        return 100.0

    # ──────────────────────────────────────────────────────
    # Ana Simülasyon
    # ──────────────────────────────────────────────────────

    def emir_sim(self, sembol: str, yon: str, miktar_usdt: float,
                  anlık_fiyat: float, volatilite_pct: float = 1.0,
                  senaryo_override: str = None) -> SimSonuc:
        """
        Gerçekçi emir simülasyonu.
        """
        senaryo  = (senaryo_override or self.senaryo).upper()
        profil   = Senaryo.profil(senaryo)
        self._istatistik["toplam"] += 1

        # ── Red kontrolü ──────────────────────────────────
        if random.random() < profil["red_p"]:
            self._istatistik["red"] += 1
            sonuc = SimSonuc(
                kabul_edildi=False, sembol=sembol, yon=yon,
                senaryo=senaryo, beklenen_fiyat=anlık_fiyat,
                sim_fiyat=0, slippage_bps=0,
                latency_ms=self.latency_sim(profil),
                fill_pct=0, red_sebebi="Senaryo red")
            self._kaydet(sonuc)
            log.warning(f"[SIM] {senaryo} red: {sembol} {yon}")
            return sonuc

        # ── Latency ───────────────────────────────────────
        latency = self.latency_sim(profil)
        time.sleep(min(latency / 1000, 0.5))  # gerçek bekleme (max 500ms)

        # ── Slippage ──────────────────────────────────────
        slip_bps   = self.slippage_sim(anlık_fiyat, miktar_usdt, yon, profil, volatilite_pct)
        sim_fiyat  = anlık_fiyat * (1 + slip_bps / 10000)
        sim_fiyat  = round(sim_fiyat, 4)

        # ── Fill ──────────────────────────────────────────
        fill_pct = self.fill_sim(profil)
        if fill_pct < 100:
            self._istatistik["kısmi_fill"] += 1

        self._istatistik["kabul"] += 1
        self._istatistik["toplam_slippage_bps"] += abs(slip_bps)
        self._istatistik["toplam_latency_ms"]   += latency

        sonuc = SimSonuc(
            kabul_edildi = fill_pct >= 80,
            sembol       = sembol,
            yon          = yon,
            senaryo      = senaryo,
            beklenen_fiyat = anlık_fiyat,
            sim_fiyat    = sim_fiyat,
            slippage_bps = abs(slip_bps),
            latency_ms   = latency,
            fill_pct     = fill_pct,
        )
        self._kaydet(sonuc)
        log.info(f"[SIM] {sonuc}")
        return sonuc

    def _kaydet(self, sonuc: SimSonuc):
        self._gecmis.append(sonuc)
        if len(self._gecmis) > 100:
            self._gecmis = self._gecmis[-100:]
        try:
            from data.db_manager import sim_trade_kaydet
            sim_trade_kaydet(
                sembol=sonuc.sembol, yon=sonuc.yon, senaryo=sonuc.senaryo,
                beklenen_fiyat=sonuc.beklenen_fiyat, sim_fiyat=sonuc.sim_fiyat,
                slippage_bps=sonuc.slippage_bps, latency_ms=sonuc.latency_ms,
                fill_pct=sonuc.fill_pct, kabul_edildi=sonuc.kabul_edildi
            )
        except Exception as e:
            log.debug(f"[SIM] DB kayıt hatası: {e}")

    # ──────────────────────────────────────────────────────
    # Senaryo Testi
    # ──────────────────────────────────────────────────────

    def senaryo_testi(self, sembol: str, yon: str,
                       miktar_usdt: float, anlık_fiyat: float,
                       n_per_senaryo: int = 100) -> dict:
        """
        Tüm senaryolarda stratejiyi test eder.
        Her senaryo için n_per_senaryo simülasyon çalıştırır.
        Gerçek bekleme olmadan (latency sleep atlanır).
        """
        log.info(f"[SIM TEST] {sembol} {yon} — {n_per_senaryo} sim/senaryo")
        sonuclar = {}

        for senaryo in Senaryo.PROFILLER.keys():
            profil   = Senaryo.profil(senaryo)
            kabul_l  = []; slip_l = []; lat_l = []; fill_l = []

            for _ in range(n_per_senaryo):
                slip_bps = self.slippage_sim(anlık_fiyat, miktar_usdt,
                                              yon, profil)
                latency  = self.latency_sim(profil)
                fill_pct = self.fill_sim(profil)
                red      = random.random() < profil["red_p"]
                kabul    = (not red) and (fill_pct >= 80)

                kabul_l.append(kabul); slip_l.append(abs(slip_bps))
                lat_l.append(latency); fill_l.append(fill_pct)

            sonuclar[senaryo] = {
                "kabul_pct":       round(np.mean(kabul_l)*100, 1),
                "ort_slippage_bps":round(np.mean(slip_l), 2),
                "p95_slippage_bps":round(np.percentile(slip_l, 95), 2),
                "ort_latency_ms":  round(np.mean(lat_l), 1),
                "p95_latency_ms":  round(np.percentile(lat_l, 95), 1),
                "ort_fill_pct":    round(np.mean(fill_l), 1),
                "aciklama":        profil["aciklama"],
            }

        log.info(f"[SIM TEST] Tamamlandı: "
                 + " | ".join(f"{s}:{sonuclar[s]['kabul_pct']}%"
                               for s in sonuclar))
        return sonuclar

    def slippage_replay(self, gecmis_fiyatlar: pd.Series,
                         yon: str, miktar_usdt: float) -> pd.Series:
        """
        Tarihsel fiyat serisi üzerinde slippage replay.
        Her mum için gerçekleşecek slippage'ı hesaplar.
        Walk-forward analiz için kullanılır.
        """
        profil = Senaryo.profil("NORMAL")
        sonuclar = []
        fiyatlar = gecmis_fiyatlar.values

        for i, fiyat in enumerate(fiyatlar):
            if fiyat <= 0: sonuclar.append(0.0); continue
            slip = self.slippage_sim(float(fiyat), miktar_usdt, yon, profil)
            sonuclar.append(round(slip, 4))

        return pd.Series(sonuclar, index=gecmis_fiyatlar.index,
                         name=f"slippage_bps_{yon}")

    @property
    def istatistik(self) -> dict:
        s = self._istatistik
        if s["toplam"] > 0:
            ort_slip = s["toplam_slippage_bps"] / max(s["kabul"], 1)
            ort_lat  = s["toplam_latency_ms"]   / max(s["kabul"], 1)
        else:
            ort_slip = ort_lat = 0
        return {
            **s,
            "kabul_pct":        round(s["kabul"]/max(s["toplam"],1)*100, 1),
            "ort_slippage_bps": round(ort_slip, 2),
            "ort_latency_ms":   round(ort_lat, 1),
            "senaryo":          self.senaryo,
        }

    def senaryo_degistir(self, yeni_senaryo: str):
        self.senaryo = yeni_senaryo.upper()
        log.info(f"[SIM] Senaryo değişti: {self.senaryo}")

    def telegram_raporu(self) -> str:
        s = self.istatistik
        return (
            f"🎭 <b>EXCHANGE SIMULATOR</b>\n"
            f"Senaryo: {s['senaryo']}\n"
            f"Toplam : {s['toplam']} | "
            f"✅{s['kabul']} (%{s['kabul_pct']}) ❌{s['red']}\n"
            f"Kısmi fill: {s['kısmi_fill']}\n"
            f"Ort slippage: {s['ort_slippage_bps']:.2f} bps\n"
            f"Ort latency : {s['ort_latency_ms']:.0f} ms"
        )


# Singleton
_sim_instance: Optional[ExchangeSimulator] = None

def get_simulator(senaryo: str = SIM_DEFAULT_SCENARIO) -> ExchangeSimulator:
    global _sim_instance
    if _sim_instance is None:
        _sim_instance = ExchangeSimulator(senaryo)
    return _sim_instance
