# =========================================================
# ASTRA v30.0 — A/B TEST ÇERÇEVESİ
# İki strateji / model varyantını istatistiksel olarak karşılaştır.
#
# Kullanım:
#   - Strateji A: Mevcut (kontrol grubu)
#   - Strateji B: Yeni varyant (test grubu)
#   Her sinyal hangi gruba yönlendirileceğini hash ile belirler.
#   Yeterli veri birikince Mann-Whitney U testi → istatistiksel karar.
#
# Entegrasyon: paper_trading üzerine — canlı risk yok.
# Telegram: /abtest → anlık karşılaştırma raporu.
# =========================================================
import logging, json, os, hashlib, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import numpy as np

log = logging.getLogger("ASTRA.AB_TEST")

# v57: bkz. model_registry.py — testler URETIM ab_test.json'unu eziyordu.
AB_DATA_PATH = os.getenv("AB_DATA_PATH", "data/ab_test.json")

try:
    from scipy.stats import mannwhitneyu, ttest_ind
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class ABVaryant:
    """Tek bir A/B varyantının sonuç kaydı."""

    def __init__(self, isim: str, max_kayit: int = 500):
        self.isim         = isim
        self._pnl_list    = deque(maxlen=max_kayit)
        self._win_list    = deque(maxlen=max_kayit)
        self._toplam      = 0
        self._kazanan     = 0
        self._kaybeden    = 0

    def islem_ekle(self, pnl_pct: float):
        self._pnl_list.append(pnl_pct)
        self._win_list.append(1 if pnl_pct > 0 else 0)
        self._toplam += 1
        if pnl_pct > 0:  self._kazanan += 1
        else:             self._kaybeden += 1

    @property
    def n(self) -> int: return len(self._pnl_list)

    @property
    def win_rate(self) -> float:
        return self._kazanan / max(self._toplam, 1)

    @property
    def ort_pnl(self) -> float:
        return float(np.mean(self._pnl_list)) if self._pnl_list else 0.0

    @property
    def std_pnl(self) -> float:
        return float(np.std(self._pnl_list)) if len(self._pnl_list) > 1 else 0.0

    @property
    def sharpe(self) -> float:
        """İŞLEM BAŞINA Sharpe — yıllıklandırma YOK.

        v58 (K-47): Eskiden `* np.sqrt(252)` vardı. Bu, listedeki her
        kaydın GÜNLÜK getiri olduğunu varsayar; oysa kayıtlar İŞLEM
        BAŞINA PnL ve bot 4h ufkunda günde ~3 işlem yapıyor. Sonuç
        panelde `sharpe: -28.356` gibi anlamsız rakamlardı
        (−1.786 × √252 = −28.36).

        Yıllıklandırmak için işlem/yıl oranı gerekir ve o oran
        rejime göre değişiyor — sabit bir çarpan doğru olamaz.
        İşlem başına Sharpe hem doğru hem karşılaştırılabilir.

        n < 30: 0 döner. 5 işlemle Sharpe raporlamak gürültüyü
        ölçmektir; eski eşik (5) bunu yapıyordu.
        """
        if len(self._pnl_list) < 30 or self.std_pnl < 1e-9:
            return 0.0
        return float(np.mean(self._pnl_list) / self.std_pnl)

    @property
    def toplam_pnl(self) -> float:
        return float(sum(self._pnl_list))

    def pnl_array(self) -> np.ndarray:
        return np.array(list(self._pnl_list))

    def ozet(self) -> dict:
        return {
            "isim": self.isim, "n": self.n,
            "win_rate": round(self.win_rate, 4),
            "ort_pnl":  round(self.ort_pnl, 4),
            "std_pnl":  round(self.std_pnl, 4),
            "sharpe":   round(self.sharpe, 3),
            "toplam_pnl": round(self.toplam_pnl, 4),
        }


class ABTestManager:
    """
    İki varyant arası istatistiksel karşılaştırma yöneticisi.

    Varyant atama: MD5(sembol + dongu_no) % 2 → deterministik, tekrarlanabilir.
    Her coin için aynı sinyal her zaman aynı gruba düşer.
    """

    MIN_ORNEKLEM     = 15    # v27: 30→15 (her grup). Daha erken anlamlı sonuç.
    ANLAMLILIK       = 0.05  # p < 0.05 → istatistiksel anlamlı fark

    def __init__(self, a_ismi: str = "Kontrol",
                 b_ismi: str = "Yeni_Varyant"):
        self.a = ABVaryant(a_ismi)
        self.b = ABVaryant(b_ismi)
        self._son_rapor_ts = 0.0
        self._karar: Optional[str] = None
        self._yukle()
        log.info(f"[A/B] Başlatıldı: '{a_ismi}' vs '{b_ismi}'")

    def _yukle(self):
        try:
            if os.path.exists(AB_DATA_PATH):
                with open(AB_DATA_PATH) as f:
                    data = json.load(f)
                for p in data.get("a_pnl", []):
                    self.a.islem_ekle(p)
                for p in data.get("b_pnl", []):
                    self.b.islem_ekle(p)
                log.info(f"[A/B] Yüklendi: A={self.a.n} B={self.b.n}")
        except Exception as e:
            log.debug(f"[A/B] Yükleme: {e}")

    def _kaydet(self):
        try:
            Path("data").mkdir(exist_ok=True)
            with open(AB_DATA_PATH, "w") as f:
                json.dump({
                    "a_pnl": list(self.a.pnl_array()),
                    "b_pnl": list(self.b.pnl_array()),
                    "ts":    datetime.now(timezone.utc).isoformat(),
                }, f)
        except Exception as e:
            log.debug(f"[A/B] Kayıt: {e}")

    def varyant_sec(self, sembol: str, dongu: int = 0) -> str:
        """
        Deterministik varyant ataması.
        Aynı sembol + döngü her zaman aynı varyanta düşer.
        """
        hash_val = int(hashlib.md5(f"{sembol}{dongu}".encode()).hexdigest(), 16)
        return "A" if hash_val % 2 == 0 else "B"

    def islem_kaydet(self, varyant: str, pnl_pct: float):
        """Kapanan işlem sonucunu kaydet."""
        if varyant == "A":
            self.a.islem_ekle(pnl_pct)
        else:
            self.b.islem_ekle(pnl_pct)

        if (self.a.n + self.b.n) % 10 == 0:
            self._kaydet()

    def istatistik_test(self) -> dict:
        """
        Mann-Whitney U testi (parametrik olmayan, küçük örneklem için uygun).
        p < 0.05 → A ve B arasında anlamlı fark var.
        """
        if not SCIPY_AVAILABLE:
            return {"test": "scipy_yok", "anlamli": False, "kazanan": "?"}

        if self.a.n < self.MIN_ORNEKLEM or self.b.n < self.MIN_ORNEKLEM:
            return {
                "test": "yetersiz_veri",
                "anlamli": False,
                "kazanan": "?",
                "mesaj": (f"Veri birikiyor — A:{self.a.n}/{self.MIN_ORNEKLEM} "
                          f"B:{self.b.n}/{self.MIN_ORNEKLEM} işlem "
                          f"(her grup en az {self.MIN_ORNEKLEM} olmalı)"),
            }

        a_arr = self.a.pnl_array()
        b_arr = self.b.pnl_array()

        try:
            stat, p_val = mannwhitneyu(a_arr, b_arr, alternative="two-sided")
            anlamli = p_val < self.ANLAMLILIK

            if anlamli:
                kazanan = self.a.isim if self.a.ort_pnl > self.b.ort_pnl else self.b.isim
                # Etki büyüklüğü: rank-biserial correlation
                n1, n2 = len(a_arr), len(b_arr)
                r_effect = 1 - (2 * stat) / (n1 * n2)
            else:
                kazanan = "Fark yok"
                r_effect = 0.0

            self._karar = kazanan if anlamli else None

            return {
                "test":       "Mann-Whitney U",
                "statistic":  round(float(stat), 2),
                "p_value":    round(float(p_val), 4),
                "anlamli":    anlamli,
                "kazanan":    kazanan,
                "etki":       round(float(r_effect), 3),
                "a_sharpe":   self.a.sharpe,
                "b_sharpe":   self.b.sharpe,
            }
        except Exception as e:
            return {"test": "hata", "hata": str(e), "anlamli": False, "kazanan": "?"}

    def telegram_raporu(self) -> str:
        test_sonuc = self.istatistik_test()
        a = self.a.ozet(); b = self.b.ozet()

        kazanan_emoji = kazanan_emoji_b = ""
        if test_sonuc.get("anlamli"):
            kazanan_emoji   = " 🏆" if test_sonuc["kazanan"] == a["isim"] else ""
            kazanan_emoji_b = " 🏆" if test_sonuc["kazanan"] == b["isim"] else ""

        bas = (
            f"🧪 <b>A/B TEST RAPORU v27</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"<b>[A] {a['isim']}{kazanan_emoji}</b> (n={a['n']})\n"
            f"  WR:%{a['win_rate']*100:.1f} | PnL:{a['ort_pnl']:+.3f}%\n"
            f"  Sharpe:{a['sharpe']:+.2f} | Toplam:{a['toplam_pnl']:+.2f}%\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"<b>[B] {b['isim']}{kazanan_emoji_b}</b> (n={b['n']})\n"
            f"  WR:%{b['win_rate']*100:.1f} | PnL:{b['ort_pnl']:+.3f}%\n"
            f"  Sharpe:{b['sharpe']:+.2f} | Toplam:{b['toplam_pnl']:+.2f}%\n"
            f"━━━━━━━━━━━━━━━━\n"
        )
        if test_sonuc.get("test") == "yetersiz_veri":
            return bas + f"⏳ {test_sonuc.get('mesaj','')}"
        if test_sonuc.get("test") == "scipy_yok":
            return bas + "⚠️ scipy yüklü değil — istatistik testi yapılamıyor"
        return bas + (
            f"📊 Mann-Whitney U  p={test_sonuc.get('p_value','?')}\n"
            f"  {'✅ Anlamlı fark' if test_sonuc['anlamli'] else '⏳ Henüz anlamlı fark yok'}\n"
            f"  Kazanan: <b>{test_sonuc['kazanan']}</b>"
            f" (etki={test_sonuc.get('etki','?')})"
        )


# ── Singleton ─────────────────────────────────────────────
_ab_manager: Optional[ABTestManager] = None

def get_ab_manager(a_ismi: str = "Mevcut_Strateji",
                    b_ismi: str = "TFT_Stratejisi") -> ABTestManager:
    global _ab_manager
    if _ab_manager is None:
        _ab_manager = ABTestManager(a_ismi, b_ismi)
    return _ab_manager
