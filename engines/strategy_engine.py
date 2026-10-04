# =========================================================
# ASTRA v30.0 — STRATEJİ ENGİNE (Seviye 3)
# Trend Follow / Mean Reversion / Grid / DCA
# Rejime göre otomatik strateji seçimi
# MTF confluence filtresi
# =========================================================
import logging, time
from typing import Optional
import sys; sys.path.append("..")
from config import (STRATEGY_MODE, GRID_LEVELS, GRID_SPACING_PCT,
                    FUTURES_LEVERAGE, COINS)

log = logging.getLogger("ASTRA.STRATEGY")

# ── Aktif Grid Seviyeleri ─────────────────────────────────
_grid_pozisyonlar: dict = {}   # {sembol: {"levels":[], "base_price":float}}

# ── Mean reversion aşırı bölge eşikleri — TEK KAYNAK (v58 K-102) ──
# Hem `mean_reversion_filtre` (giriş koşulu) hem `strateji_sec`
# (uygunluk ön kontrolü) bunları kullanır. İki yere ayrı yazılsaydı
# biri güncellenip diğeri unutulurdu — bu kod tabanının en sık
# tekrar eden hatası (K-13, K-69, K-86, K-89, K-95, K-97, K-99).
MR_RSI_ALT = 30.0    # BUY için: aşırı satım
MR_RSI_UST = 70.0    # SELL için: aşırı alım

class StratejiEngine:

    def __init__(self):
        self.mod = STRATEGY_MODE

    # ── Strateji Seçici ───────────────────────────────────
    @staticmethod
    def mean_reversion_uygun_mu(sonuc: dict) -> bool:
        """MR'ın KENDİ giriş koşulu sağlanabilir durumda mı? (v58 K-102)

        ── NEDEN VAR ────────────────────────────────────────────
        `strateji_sec` VOLATILE'de KOŞULSUZ `MEAN_REVERSION` seçiyordu.
        Ama MR'ın giriş koşulu "BUY ise RSI<30, SELL ise RSI>70" —
        ve AI bir MOMENTUM modeli: güç görünce BUY, zayıflık görünce
        SELL diyor. İkisi taban tabana ZIT.

        ÖLÇÜLDÜ (1824 gerçek red, §0.42):
            RSI max 51.1 · medyan 36.9
            RSI > 70 (SELL şartı):    0 / 1824   %0.0  ← HİÇ OLMADI
            RSI < 30 (BUY şartı) :  478 / 1824   %26.2
        Anlık kesit: AI BUY derken RSI ort. 53.9 (eşik <30),
                     AI SELL derken RSI ort. 40.8 (eşik >70).
        Kesişen coin: 0/50.

        Piyasa %96 VOLATILE olduğu için neredeyse HER sinyal, giriş
        koşulu sağlanamayan bir stratejiye yönlendiriliyordu.

        ── İLKE ─────────────────────────────────────────────────
        **Giriş koşulunun sağlanamayacağı BİLİNEN bir strateji
        seçilmez.** MR'ın mantığı yanlış değil — mean reversion için
        doğru. Yanlış olan, momentum setup'ına MR'ı DAYATMAKTI.
        Bu yüzden filtrenin içine dokunulmadı; yalnızca SEÇİM düzeltildi.
        """
        rsi = sonuc.get("son_rsi", 50) if sonuc else 50
        karar = ((sonuc or {}).get("karar") or "").upper()
        if "BUY" in karar:
            return rsi < MR_RSI_ALT
        if "SELL" in karar:
            return rsi > MR_RSI_UST
        return False      # yönsüz sinyalde zaten işlem açılmaz

    def strateji_sec(self, rejim: str, mtf_skor: int,
                     funding_rate: float, sonuc: dict = None) -> str:
        """
        Rejim + MTF confluence + funding rate'e göre
        en uygun strateji seçer.

        v58 (K-102): `sonuc` opsiyonel — MEAN_REVERSION seçilmeden önce
        onun giriş koşulunun sağlanabilir olup olmadığı kontrol edilir.
        Verilmezse eski davranış (geriye dönük uyumluluk).
        """
        if self.mod != "AUTO":
            return self.mod

        # Güçlü trend: trend takibi
        if rejim in ("TREND_UP","TREND_DOWN") and abs(mtf_skor) >= 4:
            return "TREND_FOLLOW"

        # Yatay piyasa: mean reversion veya grid
        if rejim == "RANGE":
            if abs(mtf_skor) <= 2:
                return "GRID"        # çok düşük sinyal = grid
            # v58 (K-102): RANGE'de de aynı kontrol. VOLATILE'de bulunan
            # hatayı yalnızca orada düzeltmek, aynı hatayı burada
            # bırakmak olurdu — bu oturumda K-97'yi K-98 izlemek zorunda
            # kalmıştı tam bu yüzden.
            if sonuc is not None and not self.mean_reversion_uygun_mu(sonuc):
                return "TREND_FOLLOW"
            return "MEAN_REVERSION"

        # Bear piyasası: DCA veya short trend
        if rejim == "BEAR":
            if funding_rate < -0.0003:  # funding negatif = short pahalı = bekle
                return "DCA"
            return "TREND_FOLLOW"   # bear'da short trend follow

        # Volatile: MR ancak KENDİ giriş koşulu sağlanabiliyorsa
        # (v58 K-102 — ölçüm §0.42; eskiden KOŞULSUZ MEAN_REVERSION idi
        #  ve piyasa %96 VOLATILE olduğu için neredeyse her sinyal
        #  giriş koşulu sağlanamayan bir stratejiye gidiyordu).
        if rejim == "VOLATILE":
            if sonuc is not None and not self.mean_reversion_uygun_mu(sonuc):
                return "TREND_FOLLOW"
            return "MEAN_REVERSION"

        return "TREND_FOLLOW"  # default

    # ── Trend Follow Filtresi ─────────────────────────────
    def trend_follow_filtre(self, sonuc: dict) -> bool:
        """
        Trend follow stratejisi için ek koşullar.
        MTF confluence + ADX + hacim onayı gerekir.
        """
        ai_score  = sonuc.get("ai_score", 0)
        rejim     = sonuc.get("rejim", "RANGE")
        mtf       = sonuc.get("mtf_confluence", {})
        mtf_skor  = mtf.get("skor", 0)
        son_adx   = sonuc.get("son_adx", 15)
        volume_r  = sonuc.get("volume_ratio", 1.0)

        # MTF confluence şart
        if abs(mtf_skor) < 2:
            log.info(f"[TREND] MTF confluence zayıf ({mtf_skor}) → geç"); return False
        # ADX trend gücü
        if son_adx < 20:
            log.info(f"[TREND] ADX düşük ({son_adx:.1f}) → trend yok"); return False
        # Hacim onayı
        if volume_r < 1.1:
            log.info(f"[TREND] Hacim onayı yok ({volume_r:.2f})"); return False
        return True

    # ── Mean Reversion Filtresi ───────────────────────────
    def mean_reversion_filtre(self, sonuc: dict) -> bool:
        """
        Mean reversion: RSI aşırı bölge + Bollinger dışına çıkış.
        """
        rsi       = sonuc.get("son_rsi", 50)
        son_close = sonuc.get("son_close", 0)
        karar     = sonuc.get("karar", "")

        # v58 (K-102): eşikler modül sabitinden — `strateji_sec`'in
        # uygunluk kontrolü ile AYNI kaynak, ayrışamazlar.
        if "BUY" in karar and rsi < MR_RSI_ALT:   return True   # aşırı satım
        if "SELL" in karar and rsi > MR_RSI_UST:  return True   # aşırı alım
        log.info(f"[MR] RSI={rsi:.1f} mean reversion koşulu sağlanmadı")
        return False

    # ── Grid Trading ─────────────────────────────────────
    def grid_baslat(self, sembol: str, mevcut_fiyat: float,
                    bakiye_usdt: float) -> list:
        """
        Range piyasada grid seviyeleri oluşturur.
        Her seviyede küçük long/short pozisyon açılır.
        """
        if sembol in _grid_pozisyonlar:
            return []   # zaten aktif

        spacing = GRID_SPACING_PCT / 100
        seviyeler = []
        for i in range(-GRID_LEVELS//2, GRID_LEVELS//2 + 1):
            fiyat_seviyesi = mevcut_fiyat * (1 + i * spacing)
            yon = "LONG" if i < 0 else "SHORT"
            usdt_per_level = bakiye_usdt * 0.1 / GRID_LEVELS  # bakiyenin %10'unu grid'e
            seviyeler.append({
                "fiyat": round(fiyat_seviyesi, 2),
                "yon":   yon,
                "usdt":  round(usdt_per_level, 2),
                "dolu":  False
            })

        _grid_pozisyonlar[sembol] = {
            "levels": seviyeler,
            "base_price": mevcut_fiyat,
            "ts": time.time()
        }
        log.info(f"[GRID/{sembol}] {len(seviyeler)} seviye oluşturuldu @ {mevcut_fiyat}")
        return seviyeler

    def grid_kontrol(self, sembol: str, mevcut_fiyat: float) -> Optional[dict]:
        """
        Mevcut fiyat grid seviyesine yaklaştı mı kontrol eder.
        Yaklaştıysa o seviyeyi döner (emir verilecek).
        """
        if sembol not in _grid_pozisyonlar:
            return None
        grid = _grid_pozisyonlar[sembol]
        for level in grid["levels"]:
            if level["dolu"]: continue
            fark_pct = abs(mevcut_fiyat - level["fiyat"]) / level["fiyat"] * 100
            if fark_pct < 0.1:   # %0.1 yakınlıkta tetikle
                level["dolu"] = True
                log.info(f"[GRID/{sembol}] Tetiklendi: {level['yon']} @ {level['fiyat']}")
                return level
        return None

    def grid_sifirla(self, sembol: str):
        if sembol in _grid_pozisyonlar:
            del _grid_pozisyonlar[sembol]
            log.info(f"[GRID/{sembol}] Sıfırlandı")

    # ── DCA (Dollar Cost Averaging) ───────────────────────
    def dca_kontrol(self, sembol: str, mevcut_fiyat: float,
                    ortalama_maliyet: float, dca_sayisi: int,
                    max_dca: int = 3) -> bool:
        """
        DCA: fiyat düşerken ek alım yapar.
        Koşullar: max_dca sınırı aşılmamış + fiyat %3 düşmüş
        """
        if dca_sayisi >= max_dca:
            log.info(f"[DCA/{sembol}] Max DCA ({max_dca}) sayısına ulaşıldı"); return False
        if ortalama_maliyet <= 0: return False
        dusus_pct = (ortalama_maliyet - mevcut_fiyat) / ortalama_maliyet * 100
        if dusus_pct >= 3.0:
            log.info(f"[DCA/{sembol}] %{dusus_pct:.1f} düşüş → DCA tetiklendi"); return True
        return False

    # ── Ana Karar Fonksiyonu ──────────────────────────────
    def karar_ver(self, sonuc: dict, bakiye: float) -> dict:
        """
        Rejim + strateji + sinyali birleştirerek nihai karar üretir.
        Döner: {"islem_yap":bool, "yon":str, "strateji":str,
                "sebep":str, "usdt":float}
        """
        rejim    = sonuc.get("rejim", "RANGE")
        karar    = sonuc.get("karar", "WAIT")
        mtf      = sonuc.get("mtf_confluence", {})
        funding  = sonuc.get("market_data", {}).get("funding_rate", 0)
        mtf_skor = mtf.get("skor", 0)

        strateji = self.strateji_sec(rejim, mtf_skor, funding, sonuc)
        sonuc["strateji"] = strateji

        is_buy  = "BUY" in karar
        is_sell = "SELL" in karar

        if not is_buy and not is_sell:
            return {"islem_yap": False, "strateji": strateji, "sebep": "WAIT sinyali"}

        yon = "LONG" if is_buy else "SHORT"

        # Strateji bazlı filtre
        if strateji == "TREND_FOLLOW":
            if not self.trend_follow_filtre(sonuc):
                return {"islem_yap": False, "strateji": strateji,
                        "sebep": "Trend follow koşulu sağlanmadı"}

        elif strateji == "MEAN_REVERSION":
            if not self.mean_reversion_filtre(sonuc):
                return {"islem_yap": False, "strateji": strateji,
                        "sebep": "Mean reversion koşulu sağlanmadı"}

        elif strateji == "GRID":
            return {"islem_yap": False, "strateji": strateji,
                    "sebep": "Grid modu: seviye bekleniyor"}

        elif strateji == "DCA":
            return {"islem_yap": False, "strateji": strateji,
                    "sebep": "DCA modu: düşüş bekleniyor"}

        return {"islem_yap": True, "yon": yon, "strateji": strateji,
                "sebep": f"{strateji} sinyali onaylandı",
                "usdt": bakiye * 0.15}  # bakiyenin %15'i
