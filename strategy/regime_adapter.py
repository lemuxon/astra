# =========================================================
# ASTRA v30.0 — REGIME ADAPTER
# Piyasa rejimine göre strateji parametrelerini dinamik ayarlar.
# Regime shift algılandığında pozisyon boyutunu ve
# risk toleransını otomatik değiştirir.
# =========================================================
import logging
import threading
from dataclasses import dataclass
from typing import Optional
import sys; sys.path.append("..")
from config import (FUTURES_LEVERAGE, FUTURES_LEVERAGE_MIN, FUTURES_LEVERAGE_MAX,
                    RISK_PERCENT, DAILY_LOSS_LIMIT_PCT)

log = logging.getLogger("ASTRA.REGIME_ADAPTER")


@dataclass
class RegimeKonfig:
    """Rejime özgü trading parametreleri."""
    rejim:              str
    kaldirac_max:       int
    risk_carpani:       float   # RISK_PERCENT ile çarpılır
    gunluk_limit_pct:   float   # DAILY_LOSS_LIMIT_PCT override
    pozisyon_max:       int
    strateji:           str
    volatilite_sabri:   float   # ATR çarpanı (SL genişliği)
    aciklama:           str


REJIM_KONFIG: dict[str, RegimeKonfig] = {
    "TREND_UP": RegimeKonfig(
        rejim="TREND_UP",
        kaldirac_max=min(FUTURES_LEVERAGE_MAX, 8),
        risk_carpani=1.2,       # Normal'den %20 daha agresif
        gunluk_limit_pct=DAILY_LOSS_LIMIT_PCT,
        pozisyon_max=3,
        strateji="TREND_FOLLOW",
        volatilite_sabri=1.0,
        aciklama="Güçlü yukarı trend — trend follow, normal risk",
    ),
    "TREND_DOWN": RegimeKonfig(
        rejim="TREND_DOWN",
        kaldirac_max=min(FUTURES_LEVERAGE_MAX, 8),
        risk_carpani=1.1,
        gunluk_limit_pct=DAILY_LOSS_LIMIT_PCT,
        pozisyon_max=3,
        strateji="TREND_FOLLOW",
        volatilite_sabri=1.0,
        aciklama="Güçlü aşağı trend — short trend follow",
    ),
    "RANGE": RegimeKonfig(
        rejim="RANGE",
        kaldirac_max=min(FUTURES_LEVERAGE, 5),
        risk_carpani=0.8,       # Daha muhafazakar
        gunluk_limit_pct=DAILY_LOSS_LIMIT_PCT * 0.8,
        pozisyon_max=2,
        strateji="MEAN_REVERSION",
        volatilite_sabri=0.9,
        aciklama="Yatay piyasa — küçük pozisyon, mean reversion",
    ),
    "VOLATILE": RegimeKonfig(
        rejim="VOLATILE",
        kaldirac_max=FUTURES_LEVERAGE_MIN + 1,  # Max 3x
        risk_carpani=0.5,       # Yarı risk
        gunluk_limit_pct=DAILY_LOSS_LIMIT_PCT * 0.6,
        pozisyon_max=1,
        strateji="MEAN_REVERSION",
        volatilite_sabri=1.5,   # Geniş SL
        aciklama="⚠️ Yüksek volatilite — minimum risk, geniş SL",
    ),
    "BEAR": RegimeKonfig(
        rejim="BEAR",
        kaldirac_max=FUTURES_LEVERAGE_MIN + 1,
        risk_carpani=0.4,       # Çok muhafazakar
        gunluk_limit_pct=DAILY_LOSS_LIMIT_PCT * 0.5,
        pozisyon_max=1,
        strateji="TREND_FOLLOW",  # sadece short
        volatilite_sabri=1.3,
        aciklama="🐻 Bear market — sadece short, minimal risk",
    ),
}


class RegimeAdapter:
    """
    Aktif rejimi takip eder ve parametre değişikliklerini yönetir.
    Regime shift algılandığında:
    - Risk parametrelerini günceller
    - Uyumsuz pozisyonları işaretler
    - Event bus'a bildirim yapar
    """

    # ── v58 (K-71): REJİM ARTIK SEMBOL BAŞINA ────────────────────
    # ESKİ HÂLİ: tek bir `_aktif_rejim` alanı vardı, ama
    # `rejim_guncelle()` HER SEMBOL için çağrılıyor (main.py:1003,
    # `coin_analiz` içinden) ve coinler PARALEL thread'lerde analiz
    # ediliyor (`[PARALEL] 5 coin ...`).
    #
    # İKİ SOMUT ZARAR:
    #
    # 1) SAHTE REJİM DEĞİŞİMİ SELİ. Beş coin farklı rejimdeyken tek
    #    alan her sembolde takla atıyordu. ÖLÇÜM (2026-09-10, tek gün):
    #        REGIME SHIFT satırı              : 3446
    #        ardışık iki değişim arası MEDYAN : 2 saniye
    #        60 sn'den kısa olanlar           : 3293
    #    Desen kusursuz alternatifti: VOLATILE → TREND_UP → VOLATILE…
    #    Piyasa 2 saniyede rejim değiştirmez; bu, sembollerin
    #    birbirinin üstüne yazmasıydı. Her değişim Telegram'a ALERT
    #    gönderiyordu → o gün 848 "rejim" mesajı (toplam 2303 mesajın
    #    en büyük kalemi).
    #
    # 2) YARIŞ DURUMU — YANLIŞ COİNİN RİSK AYARI. Çağıranlar
    #    `rejim_guncelle(x); aktif_konfig()` diye ard arda okuyor.
    #    Tek thread'de doğru, ama paralel analizde araya başka bir
    #    sembol girip alanı değiştirebiliyordu → A coini B coininin
    #    `kaldirac_max` değeriyle işlem açabilirdi.
    #
    # Sembol bazlı sözlük ikisini birden çözer. `sembol=None` eski
    # çağrı biçimini korur (tek genel kova).
    _GENEL = "_GENEL"

    def __init__(self):
        self._rejimler:  dict = {}
        self._oncekiler: dict = {}
        self._degisim_sayisi: int = 0
        self._lock = threading.Lock()
        from engines.event_bus import get_bus
        self._bus = get_bus()

    def rejim_guncelle(self, yeni_rejim: str, sembol=None) -> bool:
        """
        Bu SEMBOLÜN rejimini değerlendir. Değiştiyse adaptasyonu tetikle.
        Döner: True = bu sembolün rejimi değişti
        """
        anahtar = sembol or self._GENEL
        with self._lock:
            eski = self._rejimler.get(anahtar, "RANGE")
            if yeni_rejim == eski:
                return False
            self._oncekiler[anahtar] = eski
            self._rejimler[anahtar]  = yeni_rejim
            self._degisim_sayisi += 1
            sayi = self._degisim_sayisi

        etiket = f"{anahtar} " if sembol else ""
        log.info(f"[REGIME SHIFT] {etiket}{eski} → {yeni_rejim} (#{sayi})")

        # v58 (K-81): 50 coinde her sembolün ilk rejim ataması da bir
        # "değişim"dir; açılışta Telegram'ı dolduruyordu (20 dk'da 13
        # mesaj). Log yukarıda HER değişimi yazıyor — teşhis kaybolmuyor.
        try:
            from config import TG_REJIM_BILDIRIMI
        except ImportError:
            TG_REJIM_BILDIRIMI = False
        if not TG_REJIM_BILDIRIMI:
            return True

        from engines.event_bus import Event
        self._bus.publish(Event.ALERT, {
            "mesaj": (f"🔄 REJİM DEĞİŞİMİ {etiket}: {eski} → {yeni_rejim}\n"
                      f"{self.aktif_konfig(sembol).aciklama}")
        }, "RegimeAdapter")

        return True

    def aktif_konfig(self, sembol=None) -> RegimeKonfig:
        """O sembolün rejim konfigürasyonu (sembol yoksa genel kova)."""
        return REJIM_KONFIG.get(self.aktif_rejim(sembol), REJIM_KONFIG["RANGE"])

    def aktif_rejim(self, sembol=None) -> str:
        with self._lock:
            return self._rejimler.get(sembol or self._GENEL, "RANGE")

    def efektif_kaldirac(self, raw_kaldirac: int, sembol=None) -> int:
        """Rejime göre kaldıraç sınırla — O SEMBOLÜN rejimine göre."""
        konfig = self.aktif_konfig(sembol)
        return max(FUTURES_LEVERAGE_MIN,
                   min(raw_kaldirac, konfig.kaldirac_max))

    def efektif_risk(self, raw_risk_pct: float) -> float:
        """Rejime göre risk miktarını ölçekle."""
        return raw_risk_pct * self.aktif_konfig.risk_carpani

    def pozisyon_uygun_mu(self, yon: str) -> tuple:
        """
        Açılmak istenen pozisyon mevcut rejimle uyumlu mu?
        Döner: (uygun: bool, sebep: str)
        """
        konfig = self.aktif_konfig
        rejim  = self._aktif_rejim

        # Bear'da sadece short
        if rejim == "BEAR" and yon == "LONG":
            return False, "Bear rejimde LONG açılmaz"

        # Volatile'de hiç açma (opsiyonel — çok sıkı)
        # if rejim == "VOLATILE":
        #     return False, "Volatile rejimde pozisyon açılmaz"

        return True, "Uygun"

    def volatilite_sabri_ayarla(self, atr: float, base_sl_mult: float) -> float:
        """Rejime göre SL ATR çarpanını ayarla."""
        return base_sl_mult * self.aktif_konfig.volatilite_sabri

    def risk_adjusted_return_hesapla(self, beklenen_getiri: float,
                                      volatilite: float,
                                      max_kayip: float) -> float:
        """
        Sharpe-benzeri oran: beklenen_getiri / volatilite
        Rejim ayarlı: volatile dönemde daha yüksek eşik istenir.
        """
        if volatilite <= 0: return 0
        ham_rar  = beklenen_getiri / volatilite
        # Volatile/Bear'da daha yüksek R/R gereksinimi
        esik_map = {"TREND_UP":1.0,"TREND_DOWN":1.0,
                    "RANGE":1.2,"VOLATILE":1.8,"BEAR":1.5}
        esik = esik_map.get(self._aktif_rejim, 1.0)
        return ham_rar / esik

    def durum_raporu(self) -> str:
        k = self.aktif_konfig
        return (f"🔄 <b>REJİM ADAPTER</b>\n"
                f"Aktif rejim: <b>{self._aktif_rejim}</b>\n"
                f"Önceki: {self._onceki_rejim} | Değişim: {self._degisim_sayisi}x\n"
                f"Max kaldıraç: {k.kaldirac_max}x\n"
                f"Risk çarpanı: {k.risk_carpani}x\n"
                f"Max pozisyon: {k.pozisyon_max}\n"
                f"Strateji: {k.strateji}\n"
                f"📝 {k.aciklama}")


# Singleton
_adapter: Optional[RegimeAdapter] = None

def get_regime_adapter() -> RegimeAdapter:
    global _adapter
    if _adapter is None:
        _adapter = RegimeAdapter()
    return _adapter
