# =========================================================
# ASTRA v30.0 — BİNANCE VERİ İSTEMCİSİ
# data/binance_client.py
#
# Yahoo Finance'ın tamamen yerini alır.
# Public endpoint'ler için API key GEREKMİYOR.
# API key sadece özel hesap işlemleri için kullanılır.
#
# Kullanılan endpoint'ler:
#   GET /api/v3/klines          → OHLCV mum verisi
#   GET /api/v3/ticker/24hr     → 24 saatlik hacim / fiyat özeti
#   GET /api/v3/depth           → Order book (gelecekte kullanılabilir)
#
# Döndürülen DataFrame formatı main.py/indicators.py ile
# tam uyumludur: Open, High, Low, Close, Volume sütunları,
# DatetimeIndex (UTC).
# =========================================================

import logging
import threading
import time
import hmac
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
import pandas as pd
import numpy as np

import sys
sys.path.append("..")
from config import (BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_BASE_URL,
                    BINANCE_DATA_URL)

log = logging.getLogger("ASTRA.BINANCE")

# ── Binance interval ↔ Astra interval eşlemesi ────────────
# Astra içinde "1m","5m","1h","4h" kullanılır;
# bunlar zaten Binance formatıyla aynı.
INTERVAL_MAP = {
    "1m":  "1m",
    "3m":  "3m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "2h":  "2h",
    "4h":  "4h",
    "6h":  "6h",
    "8h":  "8h",
    "12h": "12h",
    "1d":  "1d",
}

# "period" → kaç mum çekileceğine dönüştürme tablosu
# Binance klines endpoint'i limit (max 1000) alır, period almaz.
# Astra "7d" + "1h" istediğinde → 7*24 = 168 mum lazım.
PERIOD_TO_BARS = {
    ("1d",  "1m"):  1440,
    ("1d",  "5m"):  288,
    ("1d",  "15m"): 96,
    ("2d",  "5m"):  576,
    ("2d",  "1h"):  48,
    ("7d",  "1h"):  168,
    ("7d",  "4h"):  42,
    ("14d", "1h"):  336,
    ("30d", "1h"):  720,
    ("60d", "1h"):  1000,   # Binance max 1000
    ("60d", "4h"):  360,
}


# v58 (K-24): Binance tek istekte en fazla 1000 mum döner. Eskiden
# `_period_to_limit` bunu SESSİZCE kırpıyordu: "7d/5m" isteyen kod
# 2016 bar beklerken 1000 (≈3.5 gün) alıyordu ve hiçbir uyarı yoktu.
# Etkisi ölçüldü — model eğitim penceresi istenenin yarısıydı.
# Artık `klines_indir` gerekirse SAYFALAYARAK tamamını çekiyor;
# bu sabit yalnızca istek başına tavandır.
ISTEK_BASI_TAVAN = 1000


def _klines_df(veri, sembol: str, interval: str, sessiz: bool = False):
    """Ham klines listesini DataFrame'e çevirir (tek yol — iki çağıran).

    v58 (K-24): Sayfalı ve tek-istekli yolun AYNI mantığı kullanması
    şart. İki kopya olsaydı biri düzeltilip diğeri unutulurdu — oluşan
    bar atma (K-16) gibi bir kural yalnızca bir yolda çalışırdı.
    """
    if not veri or not isinstance(veri, list):
        log.error(f"Binance ({sembol}): boş ya da hatalı yanıt")
        return None
    # Binance klines yanıt sırası:
    # [0:open_time, 1:open, 2:high, 3:low, 4:close, 5:volume,
    #  6:close_time, 7:quote_asset_volume, ...]
    df = pd.DataFrame(veri, columns=[
        "open_time", "Open", "High", "Low", "Close", "Volume",
        "close_time", "quote_vol", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ])

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.set_index("open_time", inplace=True)
    df.index.name = None

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── v58 (K-16): OLUŞMAKTA OLAN BARI AT ────────────────────
    # Binance'in döndürdüğü SON mum, içinde bulunulan periyodun HENÜZ
    # KAPANMAMIŞ barıdır; "Close" alanı o andaki fiyattır ve her saniye
    # değişir. Bütün göstergeler (RSI, MACD, ATR, Bollinger…) bu yarım
    # barla hesaplanıyordu — yani sinyal, bar ilerledikçe kendi altından
    # değişen bir zemine dayanıyordu.
    #
    # ÖLÇÜLEN ZARAR (paper işlemi #21, 2026-09-02): oluşan barın anlık
    # "close"u geçici bir sıçramayı gösterdi (99.92; bar 98.47'de kapandı)
    # ve oradan SHORT açıldı. TP zaten piyasanın altındaydı → 2.9 dakikada
    # "TP" oldu. Kapanmış bar kullanılsaydı o sinyal hiç doğmayacaktı.
    #
    # TESPİT close_time İLE: "son barı her zaman at" demek YANLIŞ olurdu —
    # geçmiş bir aralık istendiğinde (endTime ile backtest) son bar
    # kapanmıştır ve atılırsa veri sessizce kaybolur. Yalnızca close_time
    # GELECEKTEyse bar hâlâ oluşuyordur.
    df["close_time"] = pd.to_numeric(df["close_time"], errors="coerce")
    simdi_ms = int(time.time() * 1000)
    olusan_bar = None
    if len(df) and df["close_time"].iloc[-1] > simdi_ms:
        _s = df.iloc[-1]
        olusan_bar = {
            "open_time": df.index[-1],
            "Open":  float(_s["Open"]),  "High":   float(_s["High"]),
            "Low":   float(_s["Low"]),   "Close":  float(_s["Close"]),
            "Volume": float(_s["Volume"]),
        }
        df = df.iloc[:-1]

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    # SL/TP kontrolü canlıdaki gibi EN TAZE fiyatı ister (borsada duran
    # emir her tick'te tetiklenir). Göstergeler kapanmış bara bakar, fiyat
    # kontrolü buna. `.attrs` son df'e yazılır — pandas ara işlemlerde
    # attrs'ı korumayı garanti etmiyor.
    df.attrs["olusan_bar"] = olusan_bar

    log.info(f"Binance klines: {sembol} {interval} → {len(df)} kapanmış bar"
             f"{'' if olusan_bar else ' (oluşan bar yok)'}")
    if not sessiz:
        log.info(f"Binance klines: {sembol} {interval} → {len(df)} kapanmış bar"
                 f"{'' if olusan_bar else ' (oluşan bar yok)'}")
    return df


def _klines_sayfali(sembol: str, binance_interval: str, istenen: int,
                    url: str):
    """1000'den fazla mum için geriye doğru sayfalayarak çeker.

    v58 (K-24): Tek istek tavanı 1000. Eskiden fazlası sessizce
    kırpılıyordu. Burada en yeniden başlayıp `endTime` ile geriye
    gidiyoruz, sonra kronolojik sıraya çeviriyoruz.
    """
    parcalar = []
    end_time = None
    kalan = istenen
    while kalan > 0:
        p = {"symbol": sembol.upper(), "interval": binance_interval,
             "limit": min(kalan, ISTEK_BASI_TAVAN)}
        if end_time is not None:
            p["endTime"] = end_time
        try:
            r = requests.get(url, params=p, timeout=10)
            r.raise_for_status()
            d = r.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            log.warning(f"[KLINES SAYFA] {sembol} {binance_interval}: {e}")
            break
        if not d or not isinstance(d, list):
            break
        parcalar.append(d)
        kalan -= len(d)
        if len(d) < min(kalan + len(d), ISTEK_BASI_TAVAN):
            break                      # borsada daha eski veri yok
        end_time = d[0][0] - 1         # en eski barın hemen öncesi
    if not parcalar:
        log.error(f"[KLINES SAYFA] {sembol}: hiç veri alınamadı")
        return None
    ham = [satir for parca in reversed(parcalar) for satir in parca]
    # Sayfa sınırlarında tekrar olabilir — open_time'a göre tekille
    gorulen = set(); temiz = []
    for satir in ham:
        if satir[0] in gorulen: continue
        gorulen.add(satir[0]); temiz.append(satir)
    temiz.sort(key=lambda x: x[0])
    log.info(f"Binance klines: {sembol} {binance_interval} → "
             f"{len(temiz)} bar ({len(parcalar)} sayfa)")
    return _klines_df(temiz, sembol, binance_interval, sessiz=True)


def _period_to_limit(period: str, interval: str) -> int:
    """period + interval → kaç bar İSTENDİĞİNİ hesaplar (kırpma YOK).

    v58 (K-24): Dönen değer artık 1000'e kırpılmıyor. Kırpma isteğin
    kendisini sessizce küçültüyordu; sayfalama `klines_indir` içinde.
    """
    key = (period, interval)
    if key in PERIOD_TO_BARS:
        return PERIOD_TO_BARS[key]

    # Genel hesaplama: period'ı dakikaya çevir
    birim = period[-1]
    sayi  = int(period[:-1])
    dakika_cevrim = {"m": 1, "h": 60, "d": 1440, "w": 10080}
    period_dk = sayi * dakika_cevrim.get(birim, 1440)

    interval_dk_map = {
        "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "2h": 120, "4h": 240, "6h": 360,
        "8h": 480, "12h": 720, "1d": 1440,
    }
    interval_dk = interval_dk_map.get(interval, 60)
    return period_dk // interval_dk + 1


def _imzali_istek(method: str, path: str, params: dict = None) -> dict | None:
    """
    Binance imzalı (Private) API isteği.
    API key + secret gerektirir.
    """
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        log.warning("Binance API key/secret eksik — imzalı istek yapılamaz.")
        return None

    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    query   = urlencode(params)
    imza    = hmac.new(
        BINANCE_API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    params["signature"] = imza

    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    url     = f"{BINANCE_BASE_URL}{path}"

    try:
        if method.upper() == "GET":
            r = requests.get(url, params=params, headers=headers, timeout=10)
        elif method.upper() == "DELETE":
            r = requests.delete(url, params=params, headers=headers, timeout=10)
        else:
            r = requests.post(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"İmzalı istek hatası ({path}): {e}")
        return None


# =========================================================
# PUBLIC: OHLCV MUM VERİSİ (API key gerekmez)
# =========================================================

def klines_indir(sembol: str, interval: str = "1h",
                 limit: int = 200) -> pd.DataFrame | None:
    """
    Binance /api/v3/klines endpoint'inden ham mum verisi çeker.
    Döner: Open, High, Low, Close, Volume sütunlu DataFrame.
    Index: UTC DatetimeIndex.
    """
    binance_interval = INTERVAL_MAP.get(interval, interval)
    # v58 (K-15): piyasa verisi GERÇEK borsadan — testnet'in ince
    # likiditesi gerçekte olmayan sıçramalar üretiyor (bkz. config.py).
    url    = f"{BINANCE_DATA_URL}/api/v3/klines"
    # v58 (K-16): +1 bar iste — sondaki OLUŞMAKTA OLAN bar atılacak,
    # çağıran taraf yine istediği kadar KAPANMIŞ bar almalı.
    istenen = limit + 1
    params = {
        "symbol":   sembol.upper(),
        "interval": binance_interval,
        "limit":    min(istenen, ISTEK_BASI_TAVAN),
    }
    # v58 (K-24): 1000'den fazla bar isteniyorsa GERİYE DOĞRU sayfala.
    # `endTime` ile daha eski dilimleri çekip birleştiriyoruz; eskiden
    # istek sessizce 1000'e kırpılıyordu (bkz. _period_to_limit).
    if istenen > ISTEK_BASI_TAVAN:
        return _klines_sayfali(sembol, binance_interval, istenen, url)

    # v34: Toplam bloke süresi sınırlı. ESKİ: 10s timeout × 3 + (1+2+4)s sleep
    # = ~37s tek çağrıda. Bu, ana döngüyü dakikalarca takıp watchdog alarmına
    # yol açıyordu. YENİ: 6s timeout × 3 + (0.5+1)s = ~19.5s tavan.
    _baslangic = time.time()
    veri = None
    for deneme in range(3):
        try:
            r = requests.get(url, params=params, timeout=6)
            r.raise_for_status()
            veri = r.json()
            break
        except requests.exceptions.RequestException as e:
            log.warning(f"Binance klines ({sembol}) deneme {deneme+1}/3: {e}")
            if deneme < 2:
                time.sleep(0.5 * (deneme + 1))   # 0.5s, 1s (üstel değil, lineer kısa)
            else:
                _gecen = time.time() - _baslangic
                log.error(f"Binance klines ({sembol}) başarısız ({_gecen:.1f}s): {e}")
                return None

    if not veri or not isinstance(veri, list):
        log.error(f"Binance ({sembol}): boş ya da hatalı yanıt")
        return None

    return _klines_df(veri, sembol, interval)


def veri_indir(sembol: str, period: str = "7d",
               interval: str = "1h") -> pd.DataFrame | None:
    """
    main.py içindeki veri_indir() işlevinin Binance karşılığı.

    v48: 20s TTL önbellek eklendi. Aynı döngüde (analiz + MTF + HMM +
    market_data) aynı veri 2-4 kez indiriliyordu — yavaş ağda turların
    150s tavanını aşmasının önemli sebeplerinden biri. Önbellek, döngü
    içi tekrarları yok eder; 20s TTL döngüler arası (60s) tazeliği korur.

    Eski Yahoo Finance çağrısı:
        yf.download(sembol, period=period, interval=interval)

    Yeni Binance çağrısı (bu fonksiyon):
        binance_client.veri_indir(sembol, period, interval)

    Dönen DataFrame formatı indicators.py ile uyumludur:
      - Tek seviyeli sütunlar: Open, High, Low, Close, Volume
      - DatetimeIndex (UTC)
    """
    limit = _period_to_limit(period, interval)
    # v48: 20s TTL önbellek — döngü içi tekrar indirmeleri önler
    anahtar = f"{sembol}:{interval}:{limit}"
    simdi = time.time()
    with _veri_cache_lock:
        kayit = _veri_cache.get(anahtar)
        if kayit and simdi - kayit[0] < 20:
            return kayit[1]
    df = klines_indir(sembol, interval, limit)
    if df is not None and not df.empty:
        with _veri_cache_lock:
            _veri_cache[anahtar] = (simdi, df)
            # Önbellek şişmesin: 50 anahtardan fazlaysa en eskiyi at
            if len(_veri_cache) > 50:
                en_eski = min(_veri_cache, key=lambda k: _veri_cache[k][0])
                _veri_cache.pop(en_eski, None)
    return df


_veri_cache: dict = {}
_veri_cache_lock = threading.Lock()


def close_al(df: pd.DataFrame, sembol: str = None) -> pd.Series:
    """
    main.py içindeki close_al() işlevinin Binance karşılığı.

    Yahoo Finance'ta MultiIndex sütun olabilirdi; Binance'ta tek seviyeli.
    sembol parametresi artık kullanılmaz ama geriye dönük uyumluluk için
    imzada bırakılmıştır.
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return df["Close"].dropna()


# =========================================================
# PUBLIC: 24 SAATLİK TICKER (hacim, değişim, vb.)
# =========================================================

def ticker_24h(sembol: str) -> dict | None:
    """
    24 saatlik özet: priceChangePercent, volume, quoteVolume, vb.
    """
    url = f"{BINANCE_DATA_URL}/api/v3/ticker/24hr"   # v58 (K-15)
    try:
        r = requests.get(url, params={"symbol": sembol.upper()}, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"ticker_24h ({sembol}): {e}")
        return None


def anlık_fiyat(sembol: str) -> float | None:
    """En güncel fiyatı döner (milisaniye gecikmeli)."""
    url = f"{BINANCE_DATA_URL}/api/v3/ticker/price"  # v58 (K-15)
    try:
        r = requests.get(url, params={"symbol": sembol.upper()}, timeout=5)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as e:
        log.error(f"anlık_fiyat ({sembol}): {e}")
        return None


# =========================================================
# YARDIMCI: Sembol dönüşüm (eski Yahoo → Binance)
# =========================================================

def yahoo_to_binance(sembol: str) -> str:
    """
    Eski Yahoo formatını Binance formatına çevirir.
    Örnekler: "BTC-USD" → "BTCUSDT"
              "ETH-USD" → "ETHUSDT"
              "BTCUSDT" → "BTCUSDT" (zaten doğru)
    """
    if "-" in sembol:
        base = sembol.split("-")[0].upper()
        return f"{base}USDT"
    return sembol.upper()


# =========================================================
# PRIVATE: HESAP BİLGİSİ
# =========================================================

def hesap_bilgisi() -> dict | None:
    """
    Hesap bakiyesi ve varlıkları döner.
    GET /api/v3/account
    """
    return _imzali_istek("GET", "/api/v3/account")


def bakiye_al(varlik: str = "USDT") -> float:
    """
    Belirtilen varlığın serbest (free) bakiyesini döner.
    Örnek: bakiye_al("USDT") → 150.0
    """
    hesap = hesap_bilgisi()
    if not hesap:
        log.error("Hesap bilgisi alınamadı.")
        return 0.0
    for b in hesap.get("balances", []):
        if b["asset"] == varlik.upper():
            return float(b["free"])
    return 0.0


def acik_pozisyonlar() -> list:
    """
    Sıfırdan büyük bakiyesi olan varlıkları listeler.
    """
    hesap = hesap_bilgisi()
    if not hesap:
        return []
    return [
        b for b in hesap.get("balances", [])
        if float(b["free"]) > 0 or float(b["locked"]) > 0
    ]


# =========================================================
# PRIVATE: SEMBOL FİLTRE BİLGİSİ (lot size, min notional)
# =========================================================

_exchange_info_cache: dict = {}

def sembol_filtre_al(sembol: str) -> dict:
    """
    Bir sembol için LOT_SIZE ve MIN_NOTIONAL filtrelerini döner.
    Örnek dönüş: {"step_size": 0.00001, "min_qty": 0.00001,
                   "min_notional": 5.0, "tick_size": 0.01}
    """
    global _exchange_info_cache
    if sembol in _exchange_info_cache:
        return _exchange_info_cache[sembol]

    url = f"{BINANCE_BASE_URL}/api/v3/exchangeInfo"
    try:
        r = requests.get(url, params={"symbol": sembol.upper()}, timeout=10)
        r.raise_for_status()
        bilgi = r.json()
    except Exception as e:
        log.error(f"exchangeInfo hatası ({sembol}): {e}")
        return {}

    filtreler = {}
    for s in bilgi.get("symbols", []):
        if s["symbol"] == sembol.upper():
            for f in s.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    filtreler["step_size"] = float(f["stepSize"])
                    filtreler["min_qty"]   = float(f["minQty"])
                    filtreler["max_qty"]   = float(f["maxQty"])
                elif f["filterType"] == "NOTIONAL":
                    filtreler["min_notional"] = float(f.get("minNotional", 5.0))
                elif f["filterType"] == "MIN_NOTIONAL":
                    filtreler["min_notional"] = float(f.get("minNotional", 5.0))
                elif f["filterType"] == "PRICE_FILTER":
                    filtreler["tick_size"] = float(f["tickSize"])
            break

    _exchange_info_cache[sembol] = filtreler
    return filtreler


def miktar_duzelt(sembol: str, miktar: float) -> float:
    """
    Miktarı Binance LOT_SIZE step_size kuralına göre yuvarlar.
    """
    import math
    filtre = sembol_filtre_al(sembol)
    step   = filtre.get("step_size", 0.0)
    if step <= 0:
        return round(miktar, 6)
    hassasiyet = max(0, round(-math.log10(step)))
    duzeltilmis = math.floor(miktar / step) * step
    return round(duzeltilmis, hassasiyet)


# =========================================================
# PRIVATE: GERÇEK ORDER GÖNDERME
# =========================================================

def market_al(sembol: str, usdt_miktar: float) -> dict | None:
    """
    Gerçek MARKET BUY emri gönderir.
    usdt_miktar: harcamak istediğin USDT miktarı (örn. 50.0)

    Binance Spot API'de quoteOrderQty kullanarak tam USDT miktarıyla
    alım yapılır — önce bakiye kontrolü yapılır.
    """
    sembol = sembol.upper()

    # Bakiye kontrolü
    mevcut_usdt = bakiye_al("USDT")
    if mevcut_usdt < usdt_miktar:
        log.warning(f"[MARKET AL] Yetersiz bakiye: {mevcut_usdt:.2f} USDT < {usdt_miktar:.2f} USDT")
        return None

    # Minimum notional kontrolü
    filtre = sembol_filtre_al(sembol)
    min_notional = filtre.get("min_notional", 5.0)
    if usdt_miktar < min_notional:
        log.warning(f"[MARKET AL] Miktar min_notional altında: {usdt_miktar} < {min_notional}")
        return None

    params = {
        "symbol":        sembol,
        "side":          "BUY",
        "type":          "MARKET",
        "quoteOrderQty": round(usdt_miktar, 2),   # USDT miktarıyla al
    }

    log.info(f"[GERÇEK ORDER] MARKET BUY {sembol} — {usdt_miktar:.2f} USDT")
    sonuc = _imzali_istek("POST", "/api/v3/order", params)
    if sonuc:
        log.info(f"[ORDER OK] {sembol} BUY → orderId={sonuc.get('orderId')} "
                 f"status={sonuc.get('status')} "
                 f"executedQty={sonuc.get('executedQty')}")
    else:
        log.error(f"[ORDER HATA] {sembol} BUY başarısız")
    return sonuc


def market_sat(sembol: str, yuzde: float = 100.0) -> dict | None:
    """
    Gerçek MARKET SELL emri gönderir.
    yuzde: eldeki coin'in kaç %'ini satacağın (varsayılan: %100)

    Önce hesaptan ilgili coin'in bakiyesi okunur,
    LOT_SIZE'a göre yuvarlanır ve satılır.
    """
    sembol = sembol.upper()
    base   = sembol.replace("USDT", "").replace("BTC", "").replace("ETH", "")

    # Sembolden base asset'i çıkar (ör. BTCUSDT → BTC)
    hesap = hesap_bilgisi()
    if not hesap:
        log.error("[MARKET SAT] Hesap bilgisi alınamadı.")
        return None

    base_asset = None
    for b in hesap.get("balances", []):
        if sembol.startswith(b["asset"]) and float(b["free"]) > 0:
            base_asset = b["asset"]
            break

    if not base_asset:
        # Alternatif yöntem: sembol bilgisi için API
        url = f"{BINANCE_BASE_URL}/api/v3/exchangeInfo"
        try:
            r = requests.get(url, params={"symbol": sembol}, timeout=10)
            bilgi = r.json()
            for s in bilgi.get("symbols", []):
                if s["symbol"] == sembol:
                    base_asset = s["baseAsset"]
                    break
        except (AttributeError, ValueError, KeyError):
            pass

    if not base_asset:
        log.error(f"[MARKET SAT] {sembol} için base asset bulunamadı.")
        return None

    # Bakiye oku
    coin_bakiye = bakiye_al(base_asset)
    if coin_bakiye <= 0:
        log.warning(f"[MARKET SAT] {base_asset} bakiyesi sıfır veya negatif: {coin_bakiye}")
        return None

    satilacak = coin_bakiye * (yuzde / 100.0)
    satilacak = miktar_duzelt(sembol, satilacak)

    filtre    = sembol_filtre_al(sembol)
    min_qty   = filtre.get("min_qty", 0.0)
    if satilacak < min_qty:
        log.warning(f"[MARKET SAT] Miktar min_qty altında: {satilacak} < {min_qty}")
        return None

    params = {
        "symbol":   sembol,
        "side":     "SELL",
        "type":     "MARKET",
        "quantity": satilacak,
    }

    log.info(f"[GERÇEK ORDER] MARKET SELL {sembol} — {satilacak} {base_asset} (%{yuzde})")
    sonuc = _imzali_istek("POST", "/api/v3/order", params)
    if sonuc:
        log.info(f"[ORDER OK] {sembol} SELL → orderId={sonuc.get('orderId')} "
                 f"status={sonuc.get('status')} "
                 f"executedQty={sonuc.get('executedQty')}")
    else:
        log.error(f"[ORDER HATA] {sembol} SELL başarısız")
    return sonuc


def acik_emirler(sembol: str = None) -> list:
    """
    Açık (bekleyen) emirleri listeler.
    sembol=None ise tüm sembollerin emirleri döner.
    """
    params = {}
    if sembol:
        params["symbol"] = sembol.upper()
    sonuc = _imzali_istek("GET", "/api/v3/openOrders", params)
    return sonuc if isinstance(sonuc, list) else []


def emir_iptal(sembol: str, order_id: int) -> dict | None:
    """Açık bir emri iptal eder."""
    params = {"symbol": sembol.upper(), "orderId": order_id}
    return _imzali_istek("DELETE", "/api/v3/order", params)


def islem_gecmisi(sembol: str, limit: int = 10) -> list:
    """
    Son işlem geçmişi (filled orders).
    GET /api/v3/myTrades
    """
    params = {"symbol": sembol.upper(), "limit": min(limit, 500)}
    sonuc  = _imzali_istek("GET", "/api/v3/myTrades", params)
    return sonuc if isinstance(sonuc, list) else []
