# =========================================================
# ASTRA v30.0 — MARKET DATA HUB
# v18 YENİLİKLER:
#   • CVD (Cumulative Volume Delta) — alıcı/satıcı baskısı
#   • Likidasyon Isı Haritası — büyük SL/likidasyon kümelerini tespit
#   • OB Depth Profile — fiyat bantlarında hacim duvarları
#   • Gelişmiş sentiment skoru (CVD + OB depth dahil)
# =========================================================
import logging, requests, time
from typing import Optional
import pandas as pd
import numpy as np
import sys; sys.path.append("..")
from config import FUTURES_BASE_URL, BINANCE_BASE_URL, IS_TESTNET
from data.binance_futures_client import (
    futures_funding_rate, futures_open_interest,
    futures_oi_gecmis, futures_long_short_ratio
)

log = logging.getLogger("ASTRA.MARKET_DATA")

_fear_greed_cache = {"deger": 50, "ts": 0}
_FEAR_CACHE_TTL   = 3600  # 1 saat

# ── CVD Cache ────────────────────────────────────────────
_cvd_cache: dict = {}   # {sembol: {"cvd": float, "cvd_momentum": float, "ts": float}}
_CVD_CACHE_TTL   = 60   # 1 dakika

def fear_greed_index() -> dict:
    global _fear_greed_cache
    if time.time() - _fear_greed_cache["ts"] < _FEAR_CACHE_TTL:
        return _fear_greed_cache
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        r.raise_for_status()
        data = r.json()["data"][0]
        result = {"deger": int(data["value"]),
                  "siniflandirma": data["value_classification"],
                  "ts": time.time()}
        _fear_greed_cache = result
        return result
    except Exception as e:
        log.warning(f"Fear&Greed alınamadı: {e}")
        return {"deger": 50, "siniflandirma": "Neutral", "ts": time.time()}


def hesapla_cvd(sembol: str, interval: str = "5m", limit: int = 100) -> dict:
    """
    v18: Cumulative Volume Delta (CVD).
    CVD = Σ(taker_buy_vol - taker_sell_vol)
    Pozitif CVD momentum: net alıcı baskısı artıyor
    Negatif CVD momentum: net satıcı baskısı artıyor

    Fiyat yukarı + CVD aşağı = sahte breakout sinyali (Divergence!)
    Fiyat aşağı + CVD yukarı = güçlü dip satın alma sinyali
    """
    cached = _cvd_cache.get(sembol)
    if cached and time.time() - cached["ts"] < _CVD_CACHE_TTL:
        return cached

    try:
        url = f"{FUTURES_BASE_URL}/fapi/v1/klines"
        r = requests.get(url, params={
            "symbol": sembol.upper(), "interval": interval,
            "limit": limit
        }, timeout=8)
        r.raise_for_status()
        klines = r.json()

        taker_buy_vol  = np.array([float(k[9])  for k in klines])   # taker buy base asset vol
        total_vol      = np.array([float(k[5])   for k in klines])   # total volume
        taker_sell_vol = total_vol - taker_buy_vol
        close_prices   = np.array([float(k[4])   for k in klines])

        # Delta = alıcı - satıcı (her mum için)
        delta = taker_buy_vol - taker_sell_vol

        # CVD = kümülatif delta
        cvd = float(np.sum(delta))

        # CVD Momentum = son 5 mumun delta ortalaması vs önceki 5 mum
        if len(delta) >= 10:
            son5    = float(np.mean(delta[-5:]))
            onceki5 = float(np.mean(delta[-10:-5]))
            cvd_momentum = son5 - onceki5
        else:
            cvd_momentum = 0.0

        # CVD vs Fiyat uyumsuzluğu tespiti (Divergence)
        fiyat_yon  = 1 if close_prices[-1] > close_prices[-6] else -1
        cvd_son5   = float(np.sum(delta[-5:]))
        cvd_yon    = 1 if cvd_son5 > 0 else -1
        divergence = fiyat_yon != cvd_yon  # Uyumsuzluk var mı?

        # Normalleştirilmiş CVD skoru (−1 ile +1)
        max_vol = float(np.sum(total_vol))
        cvd_norm = cvd / max(max_vol, 1e-10)
        cvd_norm = float(np.clip(cvd_norm, -1, 1))

        result = {
            "cvd":          round(cvd, 2),
            "cvd_norm":     round(cvd_norm, 4),
            "cvd_momentum": round(cvd_momentum, 2),
            "divergence":   divergence,
            "fiyat_yon":    fiyat_yon,
            "cvd_yon":      cvd_yon,
            "ts":           time.time(),
        }
        _cvd_cache[sembol] = result
        log.debug(f"[CVD/{sembol}] norm={cvd_norm:.3f} mom={cvd_momentum:.1f} "
                  f"div={'⚠️' if divergence else '✅'}")
        return result

    except Exception as e:
        log.warning(f"[CVD] {sembol} hesaplanamadı: {e}")
        return {"cvd": 0.0, "cvd_norm": 0.0, "cvd_momentum": 0.0,
                "divergence": False, "fiyat_yon": 0, "cvd_yon": 0, "ts": time.time()}


def likidasyon_isi_haritasi(sembol: str, mevcut_fiyat: float,
                              aralik_pct: float = 5.0) -> dict:
    """
    v18: Likidasyon Isı Haritası.
    OI geçmişi + fiyat hareketinden büyük likidasyon bölgelerini tahmin eder.
    Binance likidasyon API'si (fapi/v1/allForceOrders) ile gerçek likidasyon verisi.

    Döner:
      - alt_bolgeler: [{"fiyat": x, "tahmini_hacim": y, "yon": "LONG/SHORT"}]
      - en_yakin_long_likit: float  (en yakın LONG likidasyon seviyesi)
      - en_yakin_short_likit: float
      - yogunluk_skoru: 0-10 (ne kadar yoğun likidasyon potansiyeli var)
    """
    try:
        # v35: Testnet allForceOrders'ı desteklemiyor (400 döner) → atla.
        # Boş ama geçerli bir sonuç dön; çağıran taraf zarif şekilde devam eder.
        if IS_TESTNET:   # v48: modül seviyesine taşındı
            return _bos_likidasyon_harita(mevcut_fiyat, aralik_pct)
        # 1. Gerçek likidasyon emirleri (son 1 saat)
        url = f"{FUTURES_BASE_URL}/fapi/v1/allForceOrders"
        r = requests.get(url, params={
            "symbol": sembol.upper(), "limit": 100
        }, timeout=8)
        r.raise_for_status()
        orders = r.json()

        if not orders:
            return _bos_likidasyon_harita(mevcut_fiyat, aralik_pct)

        df = pd.DataFrame(orders)
        df["price"]    = pd.to_numeric(df["price"], errors="coerce")
        df["qty"]      = pd.to_numeric(df["origQty"], errors="coerce")
        df["side"]     = df["side"]  # BUY=long likit, SELL=short likit

        # Fiyat bantlarına göre grupla (%1'lik bantlar)
        bant_sayisi = int(aralik_pct * 2)  # ±aralik_pct aralığında
        bant_genislik = mevcut_fiyat * 0.01
        alt_bolgeler = []

        long_likitler  = df[df["side"] == "BUY"]["price"]
        short_likitler = df[df["side"] == "SELL"]["price"]

        # Fiyata en yakın likidasyon seviyeleri
        en_yakin_long  = float(long_likitler[long_likitler < mevcut_fiyat].max()) \
                          if not long_likitler[long_likitler < mevcut_fiyat].empty else 0.0
        en_yakin_short = float(short_likitler[short_likitler > mevcut_fiyat].min()) \
                          if not short_likitler[short_likitler > mevcut_fiyat].empty else 0.0

        # Yoğunluk skoru: fiyata %2 mesafede kaç likidasyon var
        yakin_bolgede = df[
            (df["price"] >= mevcut_fiyat * 0.98) &
            (df["price"] <= mevcut_fiyat * 1.02)
        ]
        yogunluk_skoru = min(10, len(yakin_bolgede))

        # Bantlara göre hacim dağılımı (ısı haritası)
        for i in range(-bant_sayisi//2, bant_sayisi//2 + 1):
            bant_alt  = mevcut_fiyat + i * bant_genislik
            bant_ust  = bant_alt + bant_genislik
            bant_df   = df[(df["price"] >= bant_alt) & (df["price"] < bant_ust)]
            if bant_df.empty: continue
            hacim     = float(bant_df["qty"].sum())
            cog_side  = "LONG" if (bant_df["side"] == "BUY").sum() > (bant_df["side"] == "SELL").sum() else "SHORT"
            alt_bolgeler.append({
                "fiyat":            round((bant_alt + bant_ust) / 2, 2),
                "tahmini_hacim":    round(hacim, 4),
                "yon":              cog_side,
                "mesafe_pct":       round((bant_alt - mevcut_fiyat) / mevcut_fiyat * 100, 2),
            })

        # Önemli seviyeleri hacme göre sırala (en büyük hacimli bölge = magnet seviye)
        alt_bolgeler.sort(key=lambda x: x["tahmini_hacim"], reverse=True)
        magnet_seviye = alt_bolgeler[0]["fiyat"] if alt_bolgeler else mevcut_fiyat

        return {
            "alt_bolgeler":        alt_bolgeler[:10],
            "en_yakin_long_likit": round(en_yakin_long, 4),
            "en_yakin_short_likit":round(en_yakin_short, 4),
            "yogunluk_skoru":      yogunluk_skoru,
            "magnet_seviye":       round(magnet_seviye, 4),
            "toplam_likidasyon":   len(orders),
        }

    except Exception as e:
        log.warning(f"[LİKİDASYON ISI] {sembol} alınamadı: {e}")
        return _bos_likidasyon_harita(mevcut_fiyat, aralik_pct)


def _bos_likidasyon_harita(fiyat: float, aralik_pct: float) -> dict:
    return {
        "alt_bolgeler":        [],
        "en_yakin_long_likit": fiyat * (1 - aralik_pct/100),
        "en_yakin_short_likit":fiyat * (1 + aralik_pct/100),
        "yogunluk_skoru":      0,
        "magnet_seviye":       fiyat,
        "toplam_likidasyon":   0,
    }


def order_book_depth_profil(sembol: str, derinlik: int = 50,
                             bant_sayisi: int = 10) -> dict:
    """
    v18: Gelişmiş Order Book Depth Analizi.
    Her %0.5'lik bant için bid/ask hacmini hesaplar.
    "Büyük duvar" tespiti: belirli seviyelerde anormal hacim var mı?
    """
    try:
        url = f"{BINANCE_BASE_URL}/api/v3/depth"
        r = requests.get(url, params={
            "symbol": sembol.upper(), "limit": derinlik
        }, timeout=6)
        r.raise_for_status()
        data = r.json()

        bids = [(float(p), float(q)) for p, q in data.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in data.get("asks", [])]

        if not bids or not asks:
            return {"imbalance": 0.5, "bid_vol": 0, "ask_vol": 0,
                    "baskı": "NÖTR", "bid_duvari": None, "ask_duvari": None}

        mid_price  = (bids[0][0] + asks[0][0]) / 2
        bant_byt   = mid_price * 0.005  # %0.5 bant genişliği

        # Her bant için hacim topla
        bid_bantlar = {}
        ask_bantlar = {}
        for price, qty in bids:
            bant = int((mid_price - price) / bant_byt)
            bid_bantlar[bant] = bid_bantlar.get(bant, 0) + qty
        for price, qty in asks:
            bant = int((price - mid_price) / bant_byt)
            ask_bantlar[bant] = ask_bantlar.get(bant, 0) + qty

        # Duvar tespiti: ortalama hacmin 3x üstünde bir seviye var mı?
        total_bids = sum(q for _, q in bids)
        total_asks = sum(q for _, q in asks)
        ort_bid_bant = total_bids / max(len(bid_bantlar), 1)
        ort_ask_bant = total_asks / max(len(ask_bantlar), 1)

        bid_duvari = None
        for bant, hacim in sorted(bid_bantlar.items()):
            if hacim > ort_bid_bant * 3.0:
                duvar_fiyat = mid_price - (bant + 0.5) * bant_byt
                bid_duvari = {"fiyat": round(duvar_fiyat, 4),
                              "hacim": round(hacim, 4),
                              "mesafe_pct": round((mid_price - duvar_fiyat)/mid_price*100, 2)}
                break

        ask_duvari = None
        for bant, hacim in sorted(ask_bantlar.items()):
            if hacim > ort_ask_bant * 3.0:
                duvar_fiyat = mid_price + (bant + 0.5) * bant_byt
                ask_duvari = {"fiyat": round(duvar_fiyat, 4),
                              "hacim": round(hacim, 4),
                              "mesafe_pct": round((duvar_fiyat - mid_price)/mid_price*100, 2)}
                break

        toplam = total_bids + total_asks
        imbalance = total_bids / toplam if toplam > 0 else 0.5

        return {
            "imbalance":   round(imbalance, 4),
            "bid_vol":     round(total_bids, 2),
            "ask_vol":     round(total_asks, 2),
            "baskı":       "ALIŞ" if imbalance > 0.55 else ("SATIŞ" if imbalance < 0.45 else "NÖTR"),
            "bid_duvari":  bid_duvari,   # En güçlü destek seviyesi
            "ask_duvari":  ask_duvari,   # En güçlü direnç seviyesi
            "mid_price":   round(mid_price, 4),
        }

    except Exception as e:
        log.warning(f"Order book depth alınamadı ({sembol}): {e}")
        return {"imbalance": 0.5, "bid_vol": 0, "ask_vol": 0,
                "baskı": "NÖTR", "bid_duvari": None, "ask_duvari": None}


def market_veri_topla(sembol: str) -> dict:
    """
    v18: CVD + Likidasyon Isı Haritası + OB Depth Profile dahil.
    """
    funding = futures_funding_rate(sembol)
    oi      = futures_open_interest(sembol)
    ls_ratio= futures_long_short_ratio(sembol)
    fg      = fear_greed_index()
    ob      = order_book_depth_profil(sembol)   # v18: gelişmiş OB
    cvd     = hesapla_cvd(sembol)               # v18: CVD

    # OI değişim
    oi_hist = futures_oi_gecmis(sembol, period="5m", limit=6)
    oi_degisim = 0.0
    if not oi_hist.empty and "sumOpenInterest" in oi_hist.columns:
        oi_vals = oi_hist["sumOpenInterest"].dropna()
        if len(oi_vals) >= 2:
            oi_degisim = float((oi_vals.iloc[-1] - oi_vals.iloc[0]) / oi_vals.iloc[0] * 100)

    # ── Sentiment Skoru (v18: CVD dahil, −4 ile +4) ──────
    sentiment = 0.0
    if funding < -0.0001:   sentiment += 1.0
    elif funding > 0.0005:  sentiment -= 1.0
    if ls_ratio > 2.0:      sentiment -= 1.0
    elif ls_ratio < 0.7:    sentiment += 1.0
    if oi_degisim > 3:      sentiment += 0.5
    elif oi_degisim < -3:   sentiment -= 0.5
    fg_val = fg["deger"]
    if fg_val < 25:         sentiment += 1.0
    elif fg_val > 75:       sentiment -= 1.0
    if ob["imbalance"] > 0.6:  sentiment += 0.5
    elif ob["imbalance"] < 0.4: sentiment -= 0.5

    # v18: CVD katkısı
    cvd_norm = cvd["cvd_norm"]
    if cvd_norm > 0.3:      sentiment += 0.5    # Güçlü alıcı baskısı
    elif cvd_norm < -0.3:   sentiment -= 0.5    # Güçlü satıcı baskısı
    if cvd["divergence"]:                       # Fiyat-CVD uyumsuzluğu
        sentiment -= 0.5 * cvd["fiyat_yon"]

    # v22: On-chain sentiment katkısı
    onchain = {"onchain_skor": 0.0, "aktif": False}
    try:
        from data.onchain_data import onchain_sentiment
        onchain = onchain_sentiment(sembol)
        if onchain.get("aktif"):
            sentiment += onchain["onchain_skor"]   # -2..+2 katkı
    except Exception as _oc_e:
        log.debug(f"[ONCHAIN] {sembol}: {_oc_e}")

    return {
        "funding_rate":      round(funding, 6),
        "open_interest":     round(oi, 0),
        "oi_degisim_pct":    round(oi_degisim, 3),
        "ls_ratio":          round(ls_ratio, 3),
        "fear_greed":        fg_val,
        "fg_sinif":          fg.get("siniflandirma", "Neutral"),
        "order_book":        ob,
        "cvd":               cvd,                    # v18: CVD verisi
        "onchain":           onchain,                # v22: on-chain sentiment
        "market_sentiment":  round(max(-6, min(6, sentiment)), 2),
    }
