# =========================================================
# ASTRA v30.0 — SHADOW MODEL & VALIDATION GATING
# Canlı model güvenli retrain: test → shadow → approve → deploy
# =========================================================
import logging, os, pickle, time, json, threading
from pathlib import Path
from typing import Optional
import sys; sys.path.append("..")

log = logging.getLogger("ASTRA.SHADOW_MODEL")

SHADOW_DIR   = "saved_models/shadow"
APPROVED_DIR = "saved_models"
Path(SHADOW_DIR).mkdir(parents=True, exist_ok=True)

# Minimum shadow başarımı: canlı modelden bu kadar daha iyi olmak zorunda
MIN_IMPROVEMENT_PCT = 0.5   # %0.5 accuracy artışı


class ShadowModelManager:
    """
    Güvenli model yönetimi:
    1. Yeni model shadow'a eğitilir
    2. Shadow vs canlı karşılaştırılır
    3. Shadow daha iyiyse onay kuyruğuna girer
    4. Auto-approve (MIN_IMPROVEMENT) veya manuel onay
    5. Onaylı model canlıya alınır
    """

    def __init__(self, auto_approve: bool = True,
                 min_improvement_pct: float = MIN_IMPROVEMENT_PCT):
        self._auto_approve   = auto_approve
        self._min_improve    = min_improvement_pct
        self._lock           = threading.Lock()
        self._bekleyen: dict = {}   # {sembol: {"shadow_acc", "canli_acc", "ts"}}
        self._log: list      = []
        log.info(f"[SHADOW] Başlatıldı — auto_approve:{auto_approve} "
                 f"min_improve:{min_improvement_pct}%")

    def shadow_egit_ve_degerlendir(self, sembol: str, model, acc: float,
                                    canli_acc: float) -> bool:
        """
        Yeni model shadow'a kaydedilir ve karşılaştırılır.
        Returns: True = onaylandı ve canlıya alındı
        """
        with self._lock:
            shadow_yol  = os.path.join(SHADOW_DIR, f"shadow_{sembol}.pkl")
            shadow_meta = os.path.join(SHADOW_DIR, f"shadow_{sembol}_meta.json")

            # Shadow'a kaydet
            try:
                with open(shadow_yol, "wb") as f:
                    pickle.dump(model, f)
                with open(shadow_meta, "w") as f:
                    json.dump({"acc": acc, "canli_acc": canli_acc,
                               "ts": time.time(), "sembol": sembol}, f)
            except Exception as e:
                log.error(f"[SHADOW] {sembol} kayıt hatası: {e}")
                return False

            # Karşılaştır
            iyilesme = acc - canli_acc
            self._bekleyen[sembol] = {
                "shadow_acc": acc,
                "canli_acc":  canli_acc,
                "iyilesme":   round(iyilesme, 4),
                "ts":         time.time(),
            }

            log.info(f"[SHADOW] {sembol} shadow: {acc:.3f} vs canlı: {canli_acc:.3f} "
                     f"iyileşme: {iyilesme:+.4f}")

            # Auto-approve koşulu
            if self._auto_approve and iyilesme >= self._min_improve / 100:
                return self._onayla(sembol, model)
            elif iyilesme < 0:
                log.warning(f"[SHADOW] {sembol} shadow daha kötü ({iyilesme:+.4f}), reddedildi")
                self._log.append({"sembol": sembol, "karar": "RED",
                                   "iyilesme": iyilesme, "ts": time.time()})
                return False
            else:
                log.info(f"[SHADOW] {sembol} onay bekliyor (min_improve %{self._min_improve})")
                return False

    def _onayla(self, sembol: str, model) -> bool:
        """Shadow modeli canlıya al."""
        try:
            canli_yol = os.path.join(APPROVED_DIR, f"rf_{sembol}.pkl")  # veya en iyi model
            # Mevcut canlıyı yedekle
            if os.path.exists(canli_yol):
                yedek = canli_yol.replace(".pkl", "_yedek.pkl")
                os.replace(canli_yol, yedek)
            # Shadow → canlı
            shadow_yol = os.path.join(SHADOW_DIR, f"shadow_{sembol}.pkl")
            if os.path.exists(shadow_yol):
                with open(shadow_yol, "rb") as f:
                    onay_model = pickle.load(f)
                with open(canli_yol, "wb") as f:
                    pickle.dump(onay_model, f)
            meta = self._bekleyen.get(sembol, {})
            self._log.append({"sembol": sembol, "karar": "ONAYLANDI",
                               "iyilesme": meta.get("iyilesme", 0), "ts": time.time()})
            log.info(f"[SHADOW] ✅ {sembol} shadow onaylandı, canlıya alındı")
            return True
        except Exception as e:
            log.error(f"[SHADOW] {sembol} onay hatası: {e}")
            return False

    def manuel_onayla(self, sembol: str) -> bool:
        """Telegram /shadow_approve BTCUSDT komutuyla manuel onay."""
        with self._lock:
            shadow_yol = os.path.join(SHADOW_DIR, f"shadow_{sembol}.pkl")
            if not os.path.exists(shadow_yol):
                log.warning(f"[SHADOW] {sembol} shadow model yok")
                return False
            try:
                with open(shadow_yol, "rb") as f:
                    m = pickle.load(f)
                return self._onayla(sembol, m)
            except Exception as e:
                log.error(f"[SHADOW] Manuel onay hatası: {e}")
                return False

    def bekleyen_listesi(self) -> list:
        with self._lock:
            return [{"sembol": k, **v} for k, v in self._bekleyen.items()]

    def telegram_raporu(self) -> str:
        bekleyen = self.bekleyen_listesi()
        if not bekleyen:
            return "🤖 <b>SHADOW MODEL</b>\nOnay bekleyen model yok."
        satirlar = "\n".join(
            f"  • {b['sembol']}: shadow={b['shadow_acc']:.3f} "
            f"canlı={b['canli_acc']:.3f} ({b['iyilesme']:+.4f})"
            for b in bekleyen
        )
        return (f"🤖 <b>SHADOW MODEL</b>\n"
                f"Bekleyen: {len(bekleyen)}\n{satirlar}\n"
                f"/shadow_approve <SEMBOL> ile onaylar")


_instance = None
def get_shadow_manager(auto_approve=True) -> ShadowModelManager:
    global _instance
    if _instance is None:
        _instance = ShadowModelManager(auto_approve=auto_approve)
    return _instance
