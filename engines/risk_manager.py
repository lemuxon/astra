# =========================================================
# ASTRA v30.0 — RİSK YÖNETİCİSİ
# v18 YENİLİKLER:
#   • Dynamic Fractional Kelly — canlı win_rate + avg_rr
#   • Per-coin Kelly geçmişi (son 50 işlem rolling window)
#   • Drawdown bazlı Kelly dampening (kötü seride otomatik küçül)
#   • Execution kalitesi takibi (slippage per-trade)
#   • Sharpe / Sortino / Calmar / Omega canlı hesaplama
#   • Likidasyon guard geliştirildi (funding oranı dahil)
# =========================================================
import logging, time, threading
from datetime import datetime, date
from collections import deque
import numpy as np
import sys; sys.path.append("..")
from config import (
    BALANCE, RISK_PERCENT, DAILY_LOSS_LIMIT_PCT,
    MAX_OPEN_POSITIONS, MAX_MARGIN_PCT, MAX_SAME_DIRECTION,
    FUTURES_LEVERAGE, FUTURES_LEVERAGE_MIN, FUTURES_LEVERAGE_MAX,
    FUTURES_DYNAMIC_LEVERAGE, DRAWDOWN_REDUCE_THRESHOLD,
    LIQUIDATION_BUFFER_PCT, MIN_POZISYON_USDT,
)
from engines.event_bus import get_bus, Event

log = logging.getLogger("ASTRA.RISK")

# ── Sabitler ─────────────────────────────────────────────
KELLY_PENCERE      = 50    # Rolling window — son N işlem
KELLY_FRAKSIYONU   = 0.5   # Half-Kelly: tam Kelly çok agresif
KELLY_MAX_PCT      = 0.15  # En fazla bakiyenin %15'i
KELLY_MIN_ISLEM    = 10    # Bu kadar işlem yoksa Kelly'e güvenme
YILLIK_RF_RATE     = 0.05  # Risk-free rate (%5 yıllık)

# ── Execution Kalitesi Takibi ─────────────────────────────
class ExecutionKalitesi:
    """Per-trade slippage ve fill kalitesini izler."""
    def __init__(self, pencere: int = 100):
        self._slippage_gecmis: deque = deque(maxlen=pencere)
        self._fill_sure_gecmis: deque = deque(maxlen=pencere)

    def kaydet(self, hedef_fiyat: float, gercek_fiyat: float,
                fill_sure_ms: float = 0):
        if hedef_fiyat <= 0: return
        slippage_bps = abs(gercek_fiyat - hedef_fiyat) / hedef_fiyat * 10000
        self._slippage_gecmis.append(slippage_bps)
        if fill_sure_ms > 0:
            self._fill_sure_gecmis.append(fill_sure_ms)

    def ortalama_slippage_bps(self) -> float:
        if not self._slippage_gecmis: return 0.0
        return float(np.mean(self._slippage_gecmis))

    def p95_slippage_bps(self) -> float:
        if not self._slippage_gecmis: return 0.0
        return float(np.percentile(list(self._slippage_gecmis), 95))

    def ortalama_fill_ms(self) -> float:
        if not self._fill_sure_gecmis: return 0.0
        return float(np.mean(self._fill_sure_gecmis))

    def rapor(self) -> dict:
        return {
            "slippage_ort_bps": round(self.ortalama_slippage_bps(), 2),
            "slippage_p95_bps": round(self.p95_slippage_bps(), 2),
            "fill_sure_ms":     round(self.ortalama_fill_ms(), 1),
            "orneklem":         len(self._slippage_gecmis),
        }


# ── Canlı Performans Metrikleri ───────────────────────────
class PerformansMetrikleri:
    """
    Sharpe, Sortino, Calmar, Omega — canlı rolling hesaplama.
    Batch analytics'e gerek kalmadan her işlem sonrası güncellenir.
    """
    def __init__(self, pencere: int = 100):
        self._getiriler: deque = deque(maxlen=pencere)   # % getiriler
        self._zirve_bakiye  = 0.0
        self._max_drawdown  = 0.0
        self._toplam_getiri = 0.0

    def islem_ekle(self, pnl_pct: float, bakiye: float):
        self._getiriler.append(pnl_pct)
        self._toplam_getiri += pnl_pct
        if bakiye > self._zirve_bakiye:
            self._zirve_bakiye = bakiye
        if self._zirve_bakiye > 0:
            dd = (self._zirve_bakiye - bakiye) / self._zirve_bakiye * 100
            self._max_drawdown = max(self._max_drawdown, dd)

    def sharpe(self) -> float:
        if len(self._getiriler) < 5: return 0.0
        g = np.array(self._getiriler)
        ort = np.mean(g)
        std = np.std(g)
        if std < 1e-9: return 0.0
        # Günlük işlem varsayımı → yıllık ölçek (252 işlem günü)
        return float((ort - YILLIK_RF_RATE/252) / std * np.sqrt(252))

    def sortino(self) -> float:
        """Sadece negatif getiri standart sapmasını cezalandırır."""
        if len(self._getiriler) < 5: return 0.0
        g = np.array(self._getiriler)
        ort = np.mean(g)
        negatifler = g[g < 0]
        if len(negatifler) < 2: return float("inf") if ort > 0 else 0.0
        downside_std = np.std(negatifler)
        if downside_std < 1e-9: return 0.0
        return float((ort - YILLIK_RF_RATE/252) / downside_std * np.sqrt(252))

    def calmar(self) -> float:
        """Yıllık getiri / Max Drawdown."""
        if self._max_drawdown < 0.01: return 0.0
        yillik_getiri = self._toplam_getiri / max(len(self._getiriler), 1) * 252
        return float(yillik_getiri / self._max_drawdown)

    def omega(self, esik_pct: float = 0.0) -> float:
        """Getiri / Kayıp oranı (eşiğin üstü / altı)."""
        if len(self._getiriler) < 5: return 1.0
        g = np.array(self._getiriler)
        kazanc = np.sum(g[g > esik_pct] - esik_pct)
        kayip  = np.sum(esik_pct - g[g <= esik_pct])
        if kayip < 1e-9: return float("inf") if kazanc > 0 else 1.0
        return float(kazanc / kayip)

    def rapor(self) -> dict:
        return {
            "sharpe":   round(self.sharpe(), 3),
            "sortino":  round(self.sortino(), 3),
            "calmar":   round(self.calmar(), 3),
            "omega":    round(self.omega(), 3),
            "orneklem": len(self._getiriler),
            "max_drawdown_pct": round(self._max_drawdown, 2),
        }


# ── Dynamic Kelly Engine ──────────────────────────────────
class KellyEngine:
    """
    Per-coin Dynamic Fractional Kelly hesabı.
    Son KELLY_PENCERE işlemin canlı win_rate ve avg_rr değerlerini kullanır.
    Batch değil — her işlem kapanışında otomatik güncellenir.
    """
    def __init__(self):
        # {sembol: deque([(pnl_pct, rr_ratio), ...])}
        self._gecmis: dict = {}

    def islem_kaydet(self, sembol: str, pnl_pct: float, rr_ratio: float):
        if sembol not in self._gecmis:
            self._gecmis[sembol] = deque(maxlen=KELLY_PENCERE)
        self._gecmis[sembol].append((pnl_pct, max(rr_ratio, 0.1)))

    def kelly_fraksiyon(self, sembol: str) -> tuple:
        """
        Returns (kelly_f, win_rate, avg_rr, orneklem)
        kelly_f: bakiyenin kaç katı riske edilmeli (0.0–0.15)
        """
        gecmis = self._gecmis.get(sembol, deque())
        orneklem = len(gecmis)

        if orneklem < KELLY_MIN_ISLEM:
            # Yetersiz veri → sabit RISK_PERCENT kullan
            return RISK_PERCENT, 0.0, 0.0, orneklem

        gecmis_l = list(gecmis)
        win_rate = sum(1 for p, _ in gecmis_l if p > 0) / orneklem
        avg_rr   = float(np.mean([rr for _, rr in gecmis_l]))

        # Kelly formülü: f = W - (1-W)/R
        kelly_f = win_rate - (1 - win_rate) / max(avg_rr, 0.1)
        kelly_f = max(kelly_f, 0.0)           # negatif kelly = işlem yok
        kelly_f *= KELLY_FRAKSIYONU           # half-kelly
        kelly_f = min(kelly_f, KELLY_MAX_PCT) # üst sınır

        return kelly_f, round(win_rate, 4), round(avg_rr, 3), orneklem

    def durum_raporu(self, sembol: str) -> str:
        f, wr, rr, n = self.kelly_fraksiyon(sembol)
        if n < KELLY_MIN_ISLEM:
            return f"Kelly[{sembol}]: veri yetersiz ({n}/{KELLY_MIN_ISLEM})"
        return (f"Kelly[{sembol}]: f={f:.3f} WR={wr:.1%} "
                f"avgRR={rr:.2f} n={n}")


# ── Ana Risk Manager ──────────────────────────────────────
class RiskManager:
    def __init__(self, baslangic_bakiye: float = BALANCE):
        self.baslangic_bakiye   = baslangic_bakiye
        self.zirve_bakiye       = baslangic_bakiye
        self.gunluk_pnl         = 0.0
        self.toplam_pnl         = 0.0
        self.gunluk_islem_sayisi= 0
        self.son_gun            = date.today()
        self._bus               = get_bus()
        # v55: Sayaçlar birden fazla coin worker thread'inden güncelleniyor.
        # `self.gunluk_pnl += x` atomik DEĞİLDİR; eşzamanlı iki kapanışta bir
        # güncelleme kaybolabiliyor ve gunluk_limit_kontrol() olduğundan DÜŞÜK
        # zarar görüp günlük limit aşılmasına rağmen işleme izin verebiliyordu.
        # (kill_switch v54'te aynı gerekçeyle kilitlenmişti; burada atlanmıştı.)
        self._lock              = threading.RLock()

        # v18: Yeni sub-sistemler
        self.kelly_engine       = KellyEngine()
        self.performans         = PerformansMetrikleri()
        self.execution_kalitesi = ExecutionKalitesi()

        self._gun_kontrol()

    def _gun_kontrol(self):
        bugun = date.today()
        if bugun != self.son_gun:
            log.info(f"[RISK] Yeni gün ({bugun}) — günlük sayaçlar sıfırlandı.")
            self.gunluk_pnl          = 0.0
            self.gunluk_islem_sayisi = 0
            self.son_gun             = bugun

    # ── PnL Güncelleme ───────────────────────────────────
    def pnl_guncelle(self, pnl_usdt: float, pnl_pct: float = 0.0,
                      sembol: str = "", rr_ratio: float = 1.5):
        """
        v18: pnl_pct ve rr_ratio ile Kelly + Performans metrikleri güncellenir.
        """
        # v55: Tüm okuma-değiştirme-yazma dizisi tek kilit altında.
        with self._lock:
            self._gun_kontrol()
            self.gunluk_pnl  += pnl_usdt
            self.toplam_pnl  += pnl_usdt
            mevcut_bakiye     = self.baslangic_bakiye + self.toplam_pnl
            self.zirve_bakiye = max(self.zirve_bakiye, mevcut_bakiye)

            # v18: Kelly geçmişine ekle
            if sembol and pnl_pct != 0.0:
                self.kelly_engine.islem_kaydet(sembol, pnl_pct, rr_ratio)

            # v18: Performans metriklerini güncelle
            if pnl_pct != 0.0:
                self.performans.islem_ekle(pnl_pct, mevcut_bakiye)

            gunluk_snapshot = self.gunluk_pnl
            toplam_snapshot = self.toplam_pnl

        log.info(f"[RISK] PnL: günlük={gunluk_snapshot:+.2f} "
                 f"toplam={toplam_snapshot:+.2f} "
                 f"Sharpe={self.performans.sharpe():.2f}")

        # Drawdown event
        if self.zirve_bakiye > 0:
            dd_pct = (self.zirve_bakiye - mevcut_bakiye) / self.zirve_bakiye * 100
            if dd_pct >= DRAWDOWN_REDUCE_THRESHOLD:
                self._bus.publish(Event.RISK_DRAWDOWN,
                                  {"dd_pct": round(dd_pct, 2),
                                   "mevcut_bakiye": round(mevcut_bakiye, 2)}, "RiskManager")

    def execution_kaydet(self, hedef_fiyat: float, gercek_fiyat: float,
                          fill_sure_ms: float = 0):
        """v18: Her emir dolumundan sonra çağrılır."""
        self.execution_kalitesi.kaydet(hedef_fiyat, gercek_fiyat, fill_sure_ms)
        slippage = self.execution_kalitesi.ortalama_slippage_bps()
        if slippage > 10:
            log.warning(f"[EXEC KALİTE] Yüksek slippage: {slippage:.1f} bps ort.")

    def drawdown_pct(self) -> float:
        # v55: tutarlı anlık görüntü (toplam_pnl ve zirve_bakiye birlikte okunmalı)
        with self._lock:
            mevcut = self.baslangic_bakiye + self.toplam_pnl
            zirve  = self.zirve_bakiye
        if zirve <= 0: return 0.0
        return max(0, (zirve - mevcut) / zirve * 100)

    def gunluk_limit_kontrol(self, mevcut_bakiye: float) -> bool:
        # v55: Günlük zarar limiti — son savunma hatlarından biri.
        # Sayaç okuması kilitli olmalı, yoksa yarım güncellenmiş değer görülebilir.
        with self._lock:
            self._gun_kontrol()
            gunluk = self.gunluk_pnl
        limit_usdt = mevcut_bakiye * (DAILY_LOSS_LIMIT_PCT / 100)
        if gunluk <= -limit_usdt:
            log.warning(f"[RISK] Günlük limit aşıldı! {gunluk:.2f} / -{limit_usdt:.2f}")
            self._bus.publish(Event.RISK_LIMIT_HIT,
                              {"gunluk_pnl": gunluk, "limit": -limit_usdt}, "RiskManager")
            return True
        return False

    def acik_pozisyon_kontrol(self, acik_pozisyonlar: list) -> bool:
        if len(acik_pozisyonlar) >= MAX_OPEN_POSITIONS:
            log.warning(f"[RISK] Max pozisyon: {len(acik_pozisyonlar)}/{MAX_OPEN_POSITIONS}")
            return True
        return False

    def korrelasyon_kontrol(self, acik_pozisyonlar: list, yon: str) -> bool:
        ayni = sum(1 for p in acik_pozisyonlar if p.get("yon") == yon)
        if ayni >= MAX_SAME_DIRECTION:
            log.warning(f"[RISK] Korelasyon limiti: {yon} x{ayni}/{MAX_SAME_DIRECTION}")
            return True
        return False

    def marjin_kontrol(self, acik_pozisyonlar: list,
                        yeni_marjin: float, toplam_bakiye: float) -> bool:
        # v52 FAIL-SAFE DÜZELTMESİ: Eski kod bakiye <= 0 iken False
        # ("limit aşılmadı") dönerek işleme İZİN veriyordu. Bakiye
        # bilinmiyorsa/sıfırsa marjin oranı hesaplanamaz — bu durumda
        # izin vermek değil, ENGELLEMEK gerekir. Ağ hatasında bakiye 0
        # dönerse marjin koruması tamamen devre dışı kalıyordu.
        if toplam_bakiye <= 0:
            log.warning("[RISK] Bakiye bilinmiyor/sıfır — marjin hesaplanamıyor, "
                        "işlem güvenlik gereği ENGELLENDİ")
            return True
        kullanilan = sum(
            abs(p.get("miktar",0)) * p.get("giris",0) / max(p.get("kaldirac", FUTURES_LEVERAGE), 1)
            for p in acik_pozisyonlar
        )
        pct = (kullanilan + yeni_marjin) / toplam_bakiye * 100
        if pct > MAX_MARGIN_PCT:
            log.warning(f"[RISK] Marjin limiti: %{pct:.1f} > %{MAX_MARGIN_PCT}")
            return True
        return False

    def likidasyon_guard(self, pozisyonlar: list,
                          mevcut_fiyatlar: dict,
                          funding_rate: float = 0.0) -> list:
        """
        v18: Funding rate de likidasyon fiyatına dahil edildi.
        Uzun vadeli tutmada funding birikimi gerçek likidasyon riskini artırır.
        """
        tehlikeli = []
        for poz in pozisyonlar:
            sembol   = poz.get("sembol","")
            giris    = float(poz.get("giris", 0) or 0)
            yon      = poz.get("yon","LONG")
            kaldirac = int(poz.get("kaldirac", FUTURES_LEVERAGE) or FUTURES_LEVERAGE)
            guncel   = mevcut_fiyatlar.get(sembol, giris)
            if giris <= 0 or not guncel or guncel <= 0 or kaldirac <= 0: continue

            # v18: Funding birikimini likidasyon hesabına ekle
            # 8 saatlik funding periyodu varsayımı
            funding_cost = abs(funding_rate) * 3  # ~24 saatlik birikim
            maintenance  = 0.004 + funding_cost   # base margin + funding

            # v55: Borsanın kendi likidasyon fiyatı varsa ONU kullan — elle
            # hesaplanan yaklaşım kademeli maintenance-margin oranlarını yok
            # sayıyor. Funding etkisi borsa fiyatının üzerine tampon olarak eklenir.
            borsa_likit = float(poz.get("likidasyon_fiyat", 0) or 0)
            if borsa_likit > 0:
                if yon == "LONG":
                    likit_fiyat = borsa_likit * (1 + funding_cost)
                    uzaklik_pct = (guncel - likit_fiyat) / guncel * 100
                else:
                    likit_fiyat = borsa_likit * (1 - funding_cost)
                    uzaklik_pct = (likit_fiyat - guncel) / guncel * 100
            elif yon == "LONG":
                likit_fiyat = giris * (1 - 1/kaldirac + maintenance)
                uzaklik_pct = (guncel - likit_fiyat) / guncel * 100
            else:
                likit_fiyat = giris * (1 + 1/kaldirac - maintenance)
                uzaklik_pct = (likit_fiyat - guncel) / guncel * 100

            if uzaklik_pct < LIQUIDATION_BUFFER_PCT:
                tehlikeli.append({
                    "sembol":        sembol,
                    "yon":           yon,
                    "likit_fiyat":   round(likit_fiyat, 4),
                    "guncel":        guncel,
                    "uzaklik_pct":   round(uzaklik_pct, 2),
                    "funding_etkisi":round(funding_cost * 100, 4),
                    "KRITIK":        uzaklik_pct < LIQUIDATION_BUFFER_PCT / 2,
                })
                self._bus.publish(Event.RISK_LIQUIDATION, {
                    "sembol": sembol, "uzaklik_pct": round(uzaklik_pct, 2)
                }, "RiskManager")
        return tehlikeli

    def tum_kontroller(self, yon: str, acik_pozisyonlar: list,
                        bakiye: float, yeni_marjin: float) -> tuple:
        if self.gunluk_limit_kontrol(bakiye):
            return True, "Günlük kayıp limiti aşıldı"
        if self.acik_pozisyon_kontrol(acik_pozisyonlar):
            return True, f"Max {MAX_OPEN_POSITIONS} pozisyon"
        if self.korrelasyon_kontrol(acik_pozisyonlar, yon):
            return True, f"{yon} korelasyon limiti"
        if self.marjin_kontrol(acik_pozisyonlar, yeni_marjin, bakiye):
            return True, f"Marjin %{MAX_MARGIN_PCT} limiti"
        return False, "OK"

    def pozisyon_buyuklugu_hesapla(self, bakiye: float, fiyat: float,
                                    atr: float, win_rate: float = 0.55,
                                    sembol: str = "") -> float:
        """
        v18: Dynamic Fractional Kelly.
        - sembol verilirse per-coin canlı kelly kullanılır
        - Yetersiz veri varsa RISK_PERCENT'e düşer
        - Drawdown'da otomatik damp edilir
        """
        dd = self.drawdown_pct()

        if sembol:
            kelly_f, live_wr, avg_rr, n = self.kelly_engine.kelly_fraksiyon(sembol)
            if n >= KELLY_MIN_ISLEM:
                # v53: Negatif Kelly = bu coinde matematiksel kazanç
                # beklentisi YOK. Eski kod uyarı basıp yine de 5 USDT
                # pozisyon açıyordu — koruma etkisizdi. Doğrusu: işlem
                # AÇMA (0 dön). Çağıran taraf minimum kontrolüyle atlar.
                if kelly_f <= 0:
                    log.warning(f"[KELLY/{sembol}] Negatif Kelly! WR={live_wr:.1%} "
                                f"avgRR={avg_rr:.2f} → bu coinde İŞLEM AÇILMAYACAK")
                    return 0.0
                log.info(f"[KELLY/{sembol}] f={kelly_f:.3f} WR={live_wr:.1%} "
                         f"avgRR={avg_rr:.2f} n={n}")
                usdt = bakiye * kelly_f
            else:
                # Fallback: sabit risk_percent + basit Kelly
                r_ratio = 1.5
                kelly_static = max(win_rate - (1-win_rate)/r_ratio, 0)
                kelly_static = min(kelly_static * KELLY_FRAKSIYONU, KELLY_MAX_PCT)
                risk_usdt    = bakiye * RISK_PERCENT
                kelly_usdt   = bakiye * kelly_static
                usdt = min(risk_usdt, kelly_usdt)
        else:
            # Sembol yok → eski davranış
            r_ratio = 1.5
            kelly   = max(win_rate - (1-win_rate)/r_ratio, 0)
            kelly   = min(kelly * KELLY_FRAKSIYONU, KELLY_MAX_PCT)
            usdt    = min(bakiye * RISK_PERCENT, bakiye * kelly)

        # v18: Drawdown dampening — kötü seride agresif küçül
        if dd >= DRAWDOWN_REDUCE_THRESHOLD * 1.5:
            damp = 0.3   # %30'a düş (ciddi drawdown)
        elif dd >= DRAWDOWN_REDUCE_THRESHOLD:
            damp = 0.6   # %60'a düş
        elif dd >= DRAWDOWN_REDUCE_THRESHOLD * 0.5:
            damp = 0.8   # %80'e düş (erken uyarı)
        else:
            damp = 1.0

        # v18: Performans Sharpe kontrolü — negatif Sharpe'da extra damp
        sharpe = self.performans.sharpe()
        if sharpe < -0.5:
            damp *= 0.7
            log.warning(f"[KELLY] Sharpe={sharpe:.2f} → pozisyon %30 ek kısım")

        usdt = usdt * damp

        # v55: Eskiden `return max(round(usdt,2), 5.0)` idi — damping sonucu
        # 5 USDT'nin altına düşen boyut yeniden 5'e ÇEKİLİYORDU. Yani ciddi
        # drawdown + negatif Sharpe halinde (damp=0.21) pozisyon, risk modelinin
        # hesapladığından BÜYÜK olabiliyordu; tam da dampening'in korumak için
        # var olduğu koşullarda koruma etkisiz kalıyordu.
        # Doğrusu: borsa minimumunun altına düşüyorsa İŞLEM AÇMA (0 dön).
        # (Negatif Kelly için zaten aynı yaklaşım kullanılıyor — v53.)
        usdt = round(usdt, 2)
        if usdt < MIN_POZISYON_USDT:
            log.warning(f"[RISK] Hesaplanan boyut {usdt:.2f} USDT < minimum "
                        f"{MIN_POZISYON_USDT} → işlem AÇILMAYACAK "
                        f"(damp={damp:.2f}, dd=%{dd:.1f})")
            return 0.0
        return usdt

    def dinamik_kaldirac_hesapla(self, fiyat: float, atr: float) -> int:
        if not FUTURES_DYNAMIC_LEVERAGE:
            return FUTURES_LEVERAGE
        if fiyat <= 0: return FUTURES_LEVERAGE

        vol_pct  = (atr / fiyat) * 100
        dd       = self.drawdown_pct()
        dd_pen   = int(dd / DRAWDOWN_REDUCE_THRESHOLD) if dd >= DRAWDOWN_REDUCE_THRESHOLD else 0

        # v18: Sharpe'a göre ek kaldıraç kısımı
        sharpe   = self.performans.sharpe()
        sharpe_pen = 1 if sharpe < 0 else 0

        if vol_pct < 0.5:   kaldirac = FUTURES_LEVERAGE_MAX
        elif vol_pct < 1.0: kaldirac = min(FUTURES_LEVERAGE_MAX, 7)
        elif vol_pct < 2.0: kaldirac = FUTURES_LEVERAGE
        elif vol_pct < 3.5: kaldirac = max(FUTURES_LEVERAGE_MIN + 1, 3)
        else:               kaldirac = FUTURES_LEVERAGE_MIN

        kaldirac = max(FUTURES_LEVERAGE_MIN, kaldirac - dd_pen - sharpe_pen)
        log.info(f"[RISK] Kaldıraç: vol={vol_pct:.2f}% dd={dd:.1f}% "
                 f"sharpe={sharpe:.2f} → {kaldirac}x")
        return kaldirac

    def durum_raporu(self, bakiye: float) -> str:
        self._gun_kontrol()
        limit    = bakiye * (DAILY_LOSS_LIMIT_PCT / 100)
        kalan    = max(0, (limit + self.gunluk_pnl) / limit * 100) if limit else 100
        dd       = self.drawdown_pct()
        perf     = self.performans.rapor()
        exec_r   = self.execution_kalitesi.rapor()

        durum = "✅ Normal"
        if kalan <= 10 or dd >= DRAWDOWN_REDUCE_THRESHOLD * 1.5:
            durum = "🛑 Kritik"
        elif kalan <= 40 or dd >= DRAWDOWN_REDUCE_THRESHOLD * 0.5:
            durum = "⚠️ Dikkat"

        return (
            f"🛡️ <b>RİSK DURUMU v18</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📅 Günlük PnL  : {self.gunluk_pnl:+.2f} USDT\n"
            f"💰 Toplam PnL  : {self.toplam_pnl:+.2f} USDT\n"
            f"🚧 Limit Kalan : %{kalan:.0f} ({limit:.2f} USDT)\n"
            f"📉 Drawdown    : %{dd:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Performans Metrikleri</b>\n"
            f"  Sharpe : {perf['sharpe']:+.3f}\n"
            f"  Sortino: {perf['sortino']:+.3f}\n"
            f"  Calmar : {perf['calmar']:+.3f}\n"
            f"  Omega  : {perf['omega']:.3f}\n"
            f"  Max DD : %{perf['max_drawdown_pct']:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <b>Execution Kalitesi</b>\n"
            f"  Slippage Ort: {exec_r['slippage_ort_bps']:.1f} bps\n"
            f"  Slippage P95: {exec_r['slippage_p95_bps']:.1f} bps\n"
            f"  Fill Süre   : {exec_r['fill_sure_ms']:.0f} ms\n"
            f"  Örnek       : {exec_r['orneklem']} işlem\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{durum}"
        )
