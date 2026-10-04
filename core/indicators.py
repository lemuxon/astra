# MTF confluence cache — her TF için 60s TTL
_mtf_cache: dict = {}  # {sembol_tf: (ts, value)}
_MTF_TTL = 60  # saniye

# =========================================================
# ASTRA v16.0 — TEKNİK İNDİKATÖRLER (Profesyonel Seviye)
# =========================================================
import numpy as np
import pandas as pd

def _col(df, name, sembol=None):
    if isinstance(df.columns, pd.MultiIndex): return df[name][sembol]
    return df[name]

def hesapla_rsi(close, period=14):
    delta = close.diff()
    k = delta.where(delta > 0, 0.0).rolling(period).mean()
    y = (-delta.where(delta < 0, 0.0)).rolling(period).mean().replace(0, 1e-10)
    return 100 - (100 / (1 + k / y))

def hesapla_stoch_rsi(close, period=14):
    rsi = hesapla_rsi(close, period)
    mn = rsi.rolling(period).min(); mx = rsi.rolling(period).max()
    return (rsi - mn) / (mx - mn).replace(0, 1e-10) * 100

def hesapla_williams_r(df, sembol=None, period=14):
    h = _col(df,"High",sembol); l = _col(df,"Low",sembol); c = _col(df,"Close",sembol)
    hh = h.rolling(period).max(); ll = l.rolling(period).min()
    return -100 * (hh - c) / (hh - ll).replace(0, 1e-10)

def hesapla_cci(df, sembol=None, period=20):
    h = _col(df,"High",sembol); l = _col(df,"Low",sembol); c = _col(df,"Close",sembol)
    tp = (h+l+c)/3; ma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x-x.mean()).mean())
    return (tp-ma) / (0.015*mad.replace(0,1e-10))

def hesapla_macd(close, fast=12, slow=26, signal=9):
    ef = close.ewm(span=fast).mean(); es = close.ewm(span=slow).mean()
    m = ef-es; s = m.ewm(span=signal).mean()
    return m, s, m-s

def hesapla_bollinger(close, period=20):
    ma = close.rolling(period).mean(); std = close.rolling(period).std()
    return ma, ma+std*2, ma-std*2

def hesapla_bollinger_bandwidth(close, period=20):
    ma = close.rolling(period).mean(); std = close.rolling(period).std()
    upper = ma+std*2; lower = ma-std*2
    return (upper-lower) / ma.replace(0,1e-10) * 100

def hesapla_vwap(df, sembol=None):
    h=_col(df,"High",sembol); l=_col(df,"Low",sembol)
    c=_col(df,"Close",sembol); v=_col(df,"Volume",sembol)
    tp=(h+l+c)/3
    return (tp*v).cumsum() / v.replace(0,1e-10).cumsum()

def hesapla_atr(df, sembol=None, period=14):
    h=_col(df,"High",sembol); l=_col(df,"Low",sembol); c=_col(df,"Close",sembol)
    p=c.shift(1)
    tr=pd.concat([h-l,(h-p).abs(),(l-p).abs()],axis=1).max(axis=1)
    return tr.rolling(period).mean()

def hesapla_atr_dizi(df, sembol=None, period=14):
    if sembol: return hesapla_atr(df, sembol, period)
    try: h=df["High"]; l=df["Low"]; c=df["Close"]
    except (AttributeError, ValueError): return pd.Series(dtype=float)
    p=c.shift(1)
    tr=pd.concat([h-l,(h-p).abs(),(l-p).abs()],axis=1).max(axis=1)
    return tr.rolling(period).mean()

def hesapla_adx(df, sembol=None, period=14):
    h=_col(df,"High",sembol); l=_col(df,"Low",sembol); c=_col(df,"Close",sembol)
    plus_dm=h.diff(); minus_dm=-l.diff()
    plus_dm=plus_dm.where((plus_dm>minus_dm)&(plus_dm>0),0.0)
    minus_dm=minus_dm.where((minus_dm>plus_dm)&(minus_dm>0),0.0)
    p=c.shift(1)
    tr=pd.concat([h-l,(h-p).abs(),(l-p).abs()],axis=1).max(axis=1)
    atr_s=tr.rolling(period).mean().replace(0,1e-10)
    plus_di=100*plus_dm.rolling(period).mean()/atr_s
    minus_di=100*minus_dm.rolling(period).mean()/atr_s
    dx=100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,1e-10)
    return dx.rolling(period).mean(), plus_di, minus_di

def hesapla_obv(df, sembol=None):
    c=_col(df,"Close",sembol); v=_col(df,"Volume",sembol)
    delta=c.diff()
    direction=pd.Series(np.where(delta>0,1,np.where(delta<0,-1,0)),index=c.index)
    return (direction*v).cumsum()

def hesapla_taker_buy_ratio(df):
    if "taker_buy_base" in df.columns:
        tb=pd.to_numeric(df["taker_buy_base"],errors="coerce")
        tv=pd.to_numeric(df["Volume"],errors="coerce").replace(0,1e-10)
        return (tb/tv).clip(0.05,0.95)
    c=df["Close"]; o=df["Open"]
    ratio=(c-o)/(df["High"]-df["Low"]).replace(0,1e-10)*0.5+0.5
    return ratio.clip(0.1,0.9)

def hesapla_fibonacci(close):
    hi=float(close.max()); lo=float(close.min()); d=hi-lo
    return {"0.0":hi,"23.6":hi-d*.236,"38.2":hi-d*.382,
            "50.0":hi-d*.5,"61.8":hi-d*.618,"100.0":lo}

def hesapla_ichimoku(df, sembol=None):
    h=_col(df,"High",sembol); l=_col(df,"Low",sembol); c=_col(df,"Close",sembol)
    tenkan=(h.rolling(9).max()+l.rolling(9).min())/2
    kijun=(h.rolling(26).max()+l.rolling(26).min())/2
    senkou_a=((tenkan+kijun)/2).shift(26)
    senkou_b=((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
    return {"tenkan":tenkan,"kijun":kijun,
            "senkou_a":senkou_a,"senkou_b":senkou_b,"chikou":c.shift(-26)}

def hesapla_supertrend(df, sembol=None, period=10, multiplier=3.0):
    """SuperTrend — trend yönü + dinamik destek/direnç."""
    h=_col(df,"High",sembol); l=_col(df,"Low",sembol); c=_col(df,"Close",sembol)
    atr_s=hesapla_atr(df,sembol,period)
    upper_band = (h+l)/2 + multiplier*atr_s
    lower_band = (h+l)/2 - multiplier*atr_s
    supertrend = pd.Series(index=c.index, dtype=float)
    direction  = pd.Series(index=c.index, dtype=int)
    # v55: direction.iloc[0] hiç set edilmiyordu. Döngü i=1'den başladığı ve
    # else dalındaki `if i > 0` HER ZAMAN doğru olduğu için, ilk bar
    # "bantlar arası" durumdaysa tanımsız/0 bir yön ileriye yayılıyordu
    # (yön yalnızca +1/-1 olmalı). Açıkça başlatıldı.
    if len(c) > 0:
        direction.iloc[0] = 1
        supertrend.iloc[0] = lower_band.iloc[0]
    for i in range(1, len(c)):
        if c.iloc[i] > upper_band.iloc[i-1]:
            direction.iloc[i] = 1
        elif c.iloc[i] < lower_band.iloc[i-1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i-1]
        supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i]==1 else upper_band.iloc[i]
    return supertrend, direction

def hesapla_pivot_points(df, sembol=None):
    """Klasik pivot noktaları — destek/direnç seviyeleri."""
    h=_col(df,"High",sembol); l=_col(df,"Low",sembol); c=_col(df,"Close",sembol)
    pivot = (h+l+c)/3
    r1 = 2*pivot - l; s1 = 2*pivot - h
    r2 = pivot + (h-l); s2 = pivot - (h-l)
    return {"pivot":pivot,"r1":r1,"r2":r2,"s1":s1,"s2":s2}

def mumlar_hesapla(df, sembol=None):
    c=_col(df,"Close",sembol); o=_col(df,"Open",sembol)
    h=_col(df,"High",sembol); l=_col(df,"Low",sembol)
    f=pd.DataFrame(index=df.index)
    f["Candle_Strength"]=c-o; f["Body_Size"]=(c-o).abs()
    f["Candle_Range"]=h-l; f["Lower_Shadow"]=o-l; f["Upper_Shadow"]=h-c
    po,pc=o.shift(1),c.shift(1)
    f["Bullish_Engulfing"]=((pc<po)&(c>o)&(c>po)&(o<pc)).astype(int)
    f["Bearish_Engulfing"]=((pc>po)&(c<o)&(c<po)&(o>pc)).astype(int)
    # v55: Tamamen düz mum (O==H==L==C, ör. işlem görmemiş bar) için
    # Candle_Range=0 ve Body_Size=0 → `0 < 0` False, yani en uç Doji
    # vakası işaretlenmiyordu. Sıfır-aralık durumu ayrıca ele alındı.
    f["Doji"]=((f["Body_Size"]<f["Candle_Range"]*0.1) |
                ((f["Candle_Range"]==0) & (f["Body_Size"]==0))).astype(int)
    f["Hammer"]=(f["Lower_Shadow"]>f["Body_Size"]*2).astype(int)
    f["Shooting_Star"]=(f["Upper_Shadow"]>f["Body_Size"]*2).astype(int)
    f["Morning_Star"]=((pc>po)&(f["Body_Size"]<f["Candle_Range"]*0.2)&(c>o)).astype(int)
    f["Three_White_Soldiers"]=((c>o)&(c.shift(1)>o.shift(1))&(c.shift(2)>o.shift(2))&
                                (c>c.shift(1))&(c.shift(1)>c.shift(2))).astype(int)
    return f

def piyasa_rejimi_tespit(close, df, sembol=None, adx_period=14):
    adx_v,plus_di,minus_di=hesapla_adx(df,sembol,adx_period)
    bb_bw=hesapla_bollinger_bandwidth(close)
    ema50=close.ewm(span=50).mean(); ema200=close.ewm(span=200).mean()
    son_adx    =float(adx_v.iloc[-1])    if not adx_v.dropna().empty    else 20.0
    son_plus_di=float(plus_di.iloc[-1])  if not plus_di.dropna().empty  else 25.0
    son_min_di =float(minus_di.iloc[-1]) if not minus_di.dropna().empty else 25.0
    son_bw     =float(bb_bw.iloc[-1])    if not bb_bw.dropna().empty    else 5.0
    son_close  =float(close.iloc[-1])
    son_ema50  =float(ema50.iloc[-1])    if not ema50.dropna().empty     else son_close
    son_ema200 =float(ema200.iloc[-1])   if not ema200.dropna().empty    else son_close
    if son_bw > 15: return "VOLATILE"
    if son_close < son_ema200*0.97 and son_adx > 20: return "BEAR"
    if son_adx > 25:
        return "TREND_UP" if son_plus_di > son_min_di else "TREND_DOWN"
    return "RANGE"

def _tf_analiz(df) -> dict:
    """Tek bir TF için trend yönü ve gösterge değerlerini hesapla."""
    if df is None or len(df) < 30:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].iloc[:, 0]
    else:
        close = df["Close"]
    try:
        rsi_v          = hesapla_rsi(close)
        macd_v, sig, _ = hesapla_macd(close)
        ma20, _, _     = hesapla_bollinger(close)
        ema50          = close.ewm(span=50).mean()
        ema200         = close.ewm(span=200).mean() if len(close) >= 200 else ema50

        son_close = float(close.iloc[-1])
        son_rsi   = float(rsi_v.iloc[-1])
        son_macd  = float(macd_v.iloc[-1])
        son_sig   = float(sig.iloc[-1])
        son_ma20  = float(ma20.iloc[-1])
        son_ema50 = float(ema50.iloc[-1])
        son_ema200= float(ema200.iloc[-1])

        # Trend yönü: birden fazla gösterge hemfikir olmak zorunda
        long_sinyaller = [
            son_close > son_ma20,
            son_close > son_ema50,
            son_macd  > son_sig,
            son_rsi   > 50,
            son_close > son_ema200,
        ]
        short_sinyaller = [not s for s in long_sinyaller]
        long_puan  = sum(long_sinyaller)
        short_puan = sum(short_sinyaller)

        if long_puan >= 4:   yon = "LONG";  guc = long_puan / 5
        elif short_puan >= 4: yon = "SHORT"; guc = short_puan / 5
        else:                 yon = "NÖTR";  guc = 0.0

        # Trend momentumu: EMA20 > EMA50 > EMA200 (tam hizalama)
        tam_hizalama = (son_ma20 > son_ema50 > son_ema200) or \
                       (son_ma20 < son_ema50 < son_ema200)

        skor = (long_puan - short_puan)   # −5 ile +5 arası
        return {
            "yon": yon, "guc": round(guc, 2), "skor": skor,
            "tam_hizalama": tam_hizalama,
            "rsi": round(son_rsi, 1),
            "macd_yukari": son_macd > son_sig,
            "fiyat_ema50": round(son_close / son_ema50 - 1, 4),
        }
    except Exception:
        return None


# v58 (K-29): MTF merdiveni — taban ANA_INTERVAL, üstü ondan türer.
# Her basamak bir öncekinin ~4 katı; ağırlık üstten alta azalır.
_TF_MERDIVEN = ["5m", "15m", "1h", "4h", "1d", "1w"]
# Period'lar eski davranışla BİREBİR aynı tutuldu (5m tabanlı yol
# değişmesin); yalnızca yeni basamaklar (1d, 1w) eklendi.
_TF_PERIOD = {"5m": "2d", "15m": "5d", "1h": "7d", "4h": "30d",
              "1d": "365d", "1w": "1000d"}


def _tf_hiyerarsi():
    """[(tf, {period, interval}, agirlik)] — üstten alta.

    Taban ANA_INTERVAL; üzerine merdivenden 3 basamak eklenir.
    Ağırlıklar eski davranışla aynı: bağlam 3.0, ana trend 2.0,
    zamanlama 1.5, tetikleyici 1.0.
    """
    try:
        from config import ANA_INTERVAL
    except ImportError:
        ANA_INTERVAL = "5m"
    if ANA_INTERVAL not in _TF_MERDIVEN:
        ANA_INTERVAL = "5m"
    i = _TF_MERDIVEN.index(ANA_INTERVAL)
    # taban + üstündeki 3 basamak (merdiven biterse mevcutlarla yetin)
    secili = _TF_MERDIVEN[i:i + 4]
    agirliklar = [1.0, 1.5, 2.0, 3.0][:len(secili)]
    # üstten alta sırala
    ciftler = list(zip(secili, agirliklar))[::-1]
    return [(tf, {"period": _TF_PERIOD.get(tf, "60d"), "interval": tf}, ag)
            for tf, ag in ciftler]


def mtf_confluence_skoru(sembol: str, veri_indir_fn) -> dict:
    """
    v19: TOP-DOWN MTF Cascade Hiyerarşisi.

    Hiyerarşi (üst TF yönüyle çelişen alt TF sinyali bloklanır):
      4h  → Genel bağlam (ağırlık 3x, blok yok ama ceza)
      1h  → Ana trend  (ağırlık 2x, ZORUNLU — ters yön = blok)
      15m → Giriş zamanlaması (ağırlık 1.5x, güçlü filtre)
      5m  → Hassas tetikleyici (ağırlık 1x)

    Döner:
      skor: ağırlıklı toplam
      yuzde: 0-100
      yon: LONG/SHORT/NÖTR
      ana_trend_yon: tabanın bir üstündeki TF yönü (blok referansı)
      bloklu: True = 1h ile 5m çelişiyor → işlem yasak
      hizalama_skoru: 0-4 (kaç TF hizalı)
      detay: her TF analizi
    """
    import time as _t
    cache_key = sembol
    if cache_key in _mtf_cache:
        ts, val = _mtf_cache[cache_key]
        if _t.time() - ts < _MTF_TTL:
            return val

    # ── v58 (K-29): HİYERARŞİ ANA UFUKTAN TÜRETİLİR ───────────
    # Eskiden 4h/1h/15m/5m sabitti ve taban 5m'di. Ana ufuk 4h'e
    # taşınınca bu hiyerarşi ANLAMSIZ hale gelirdi: "tetikleyici" 5m,
    # işlem barından 48 kat küçük olurdu ve MTF cascade, işlemle
    # ilgisiz bir gürültüyü veto gerekçesi yapardı.
    # Artık taban = ANA_INTERVAL, üstündekiler ondan yukarı.
    TF_HIYERARSI = _tf_hiyerarsi()

    analizler = {}
    for tf, ayar, _ in TF_HIYERARSI:
        try:
            df = veri_indir_fn(sembol, ayar["period"], ayar["interval"])
            sonuc = _tf_analiz(df)
            if sonuc:
                analizler[tf] = sonuc
        except Exception:
            continue

    if not analizler:
        bos = {"skor": 0, "yuzde": 50, "yon": "NÖTR", "bloklu": False,
               "ana_trend_yon": "NÖTR", "hizalama_skoru": 0, "detay": {}}
        _mtf_cache[sembol] = (_t.time(), bos)
        return bos

    # ── Ana trend: TABANIN BİR ÜSTÜNDEKİ TF ───────────────
    # v58 (K-29): Eskiden `analizler.get("1h")` SABİTTİ. Taban 5m iken
    # 1h, tabanın bir üstüydü — mantık buydu. Ana ufuk 4h'e taşınınca
    # hiyerarşide "1h" HİÇ BULUNMAZ; ana_trend_yon her zaman "NÖTR"
    # olur, `bloklu` asla True olmaz ve MTF cascade vetosu SESSİZCE
    # ÖLÜRDÜ. (§5.2 — "kapı var sanılıyor ama yok" deseni.)
    _tfler       = [tf for tf, _, _ in TF_HIYERARSI]      # üstten alta
    _taban_tf    = _tfler[-1]                              # işlem barı
    _ana_trend_tf= _tfler[-2] if len(_tfler) >= 2 else _taban_tf
    ana_trend_yon = analizler.get(_ana_trend_tf, {}).get("yon", "NÖTR")

    # ── Hizalama referansı ────────────────────────────────
    # v58 (K-96): ANA TREND NÖTR İSE HİYERARŞİDE AŞAĞI İN.
    #
    # Eskiden referans KOŞULSUZ `ana_trend_yon` idi ve döngü
    # `if ana_trend_yon != "NÖTR" ...` ile korunuyordu. Sonuç: ana trend
    # TF'si (taban+1, yani 1d) NÖTR olduğunda `hizali_tf` KOŞULSUZ boş
    # kalıyor, `hizalama_skoru` her zaman 0 çıkıyor ve main.py bunu
    # "MTF hizalama yok" diye VETO ediyordu.
    #
    # ÖLÇÜLDÜ (§0.35 Bulgu 1, 50 coin):
    #     hizalama_skoru == 0 : 17 coin
    #     ana_trend_yon NÖTR  : 17 coin     ← BİREBİR AYNI KÜME
    # Yani veto "hizalama yok" değil, "1d'nin yönü yok" demekti.
    # `1w=LONG · 4h=LONG · 1d=NÖTR` durumunda işlem reddediliyordu —
    # görüşü olan İKİ TF hemfikir olmasına rağmen. İsim ve davranış
    # ayrışmıştı (docstring: "kaç TF hizalı").
    #
    # ⚠️ ÇOĞUNLUK OYU KULLANILMADI: `1w=LONG · 4h=SHORT` gibi beraberlikte
    # `Counter.most_common` ekleme sırasına göre KEYFİ seçer — kararmış
    # gibi görünen bir rastgelelik olurdu. Onun yerine hiyerarşik iniş:
    # otorite sırası korunur, sonuç deterministiktir.
    #
    # ⚠️ `bloklu` DEĞİŞMEDİ — o hâlâ `ana_trend_yon`'a bağlı. Cascade'in
    # çekirdeği "üst TF'ye karşı işlem açma"dır; üst TF'nin görüşü yoksa
    # karşı çıkılacak bir şey de yoktur.
    hizalama_ref = ana_trend_yon
    if hizalama_ref == "NÖTR":
        # Ana trend susmuş → bir alttaki otorite: işlem barının kendisi.
        for _tf in _tfler[_tfler.index(_ana_trend_tf):]:
            _y = analizler.get(_tf, {}).get("yon", "NÖTR")
            if _y != "NÖTR":
                hizalama_ref = _y
                break

    # ── Hizalama kontrolü ─────────────────────────────────
    hizali_tf = []
    bloklu    = False
    for tf, _, _ in TF_HIYERARSI:
        a = analizler.get(tf)
        if not a:
            continue
        tf_yon = a["yon"]
        if hizalama_ref != "NÖTR" and tf_yon == hizalama_ref:
            hizali_tf.append(tf)
        # Blok YALNIZCA ana trend yön bildiriyorsa ve taban ona tersse.
        if (ana_trend_yon != "NÖTR" and tf_yon != "NÖTR"
                and tf == _taban_tf and tf_yon != ana_trend_yon):
            # Giriş TF'si ana trendle ters → blok
            # (v58 K-29: "5m" sabiti yerine taban TF)
            bloklu = True

    hizalama_skoru = len(hizali_tf)

    # ── Ağırlıklı skor ───────────────────────────────────
    agirlikli_toplam = 0.0
    agirlik_toplam   = 0.0
    for tf, _, agirlik in TF_HIYERARSI:
        a = analizler.get(tf)
        if not a:
            continue
        tf_skor = a["skor"]
        # Tam hizalama bonusu
        if a.get("tam_hizalama"):
            tf_skor *= 1.2
        # Üst TF ile ters gidiyorsa ceza
        if ana_trend_yon != "NÖTR" and a["yon"] not in ("NÖTR", ana_trend_yon):
            tf_skor *= -0.5   # Ters TF skoru negatife dön + küçült
        agirlikli_toplam += tf_skor * agirlik
        agirlik_toplam   += agirlik

    norm_skor = agirlikli_toplam / max(agirlik_toplam, 1)  # −5 ile +5 arası

    # 0-100 yüzde
    yuzde = int((norm_skor + 5) / 10 * 100)
    yuzde = max(0, min(100, yuzde))

    # Genel yön
    if norm_skor >= 1.5:   genel_yon = "LONG"
    elif norm_skor <= -1.5: genel_yon = "SHORT"
    else:                   genel_yon = "NÖTR"

    sonuc = {
        "skor":          round(norm_skor, 2),
        "yuzde":         yuzde,
        "yon":           genel_yon,
        "ana_trend_yon": ana_trend_yon,      # bir üst TF'nin kararı
        "bloklu":        bloklu,             # Alt TF üstle çelişiyor mu?
        "hizalama_skoru":hizalama_skoru,     # Kaç TF hizalı (0-4)
        "detay":         analizler,
        # v58 (K-94): TF ADLARI DA DÖNÜYOR — teşhis kaydı için.
        # main.py veto mesajı "5m yönü 1h ana trendi ile çelişiyor" diye
        # SABİT yazıyordu. K-29 hiyerarşiyi ANA_INTERVAL'den türetilir
        # yaptı (artık 1w/1d/4h) ama mesaj güncellenmedi; log YANLIŞ
        # zaman dilimi adı veriyordu. Veto zinciri incelenirken bu,
        # "bot 4h'de ama MTF 5m'e mi bakıyor?" diye yanlış iz sürdürdü.
        # Adları burada döndürerek mesajın bir daha ayrışmasını engelliyoruz.
        "taban_tf":      _taban_tf,          # işlem barı (= ANA_INTERVAL)
        "ana_trend_tf":  _ana_trend_tf,      # blok referansı (bir üstü)
    }
    _mtf_cache[sembol] = (_t.time(), sonuc)
    return sonuc

# ── v18: CVD Delta Feature (DataFrame bazlı) ─────────────
def hesapla_cvd_delta(df) -> pd.Series:
    """
    Cumulative Volume Delta — klines DataFrame'inden hesapla.
    taker_buy_base sütunu varsa gerçek CVD, yoksa yaklaşık.
    Feature olarak kullanım için normalize edilmiş seri döner.
    """
    import pandas as pd, numpy as np
    try:
        if "taker_buy_base" in df.columns:
            tb = pd.to_numeric(df["taker_buy_base"], errors="coerce").fillna(0)
            tv = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
            ts = tv - tb  # taker sell
            delta = tb - ts
        else:
            # Yaklaşık: mum yönüne göre hacim atfet
            close = pd.to_numeric(df["Close"], errors="coerce")
            open_ = pd.to_numeric(df["Open"],  errors="coerce")
            vol   = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
            yon   = np.sign(close - open_)
            delta = vol * yon

        cvd = delta.cumsum()
        # Normalize: rolling max-min scale (−1, +1)
        roll_max = cvd.rolling(50, min_periods=5).max()
        roll_min = cvd.rolling(50, min_periods=5).min()
        denom    = (roll_max - roll_min).replace(0, 1e-10)
        cvd_norm = ((cvd - roll_min) / denom * 2 - 1).clip(-1, 1)
        return cvd_norm.rename("CVD_Norm")
    except Exception:
        return pd.Series(0.0, index=df.index, name="CVD_Norm")


def hesapla_cvd_momentum(df, pencere: int = 5) -> pd.Series:
    """
    CVD Momentum: son N mumda CVD'nin hız değişimi.
    Pozitif: alıcı baskısı artıyor.
    Negatif: satıcı baskısı artıyor.
    """
    import pandas as pd, numpy as np
    try:
        if "taker_buy_base" in df.columns:
            tb    = pd.to_numeric(df["taker_buy_base"], errors="coerce").fillna(0)
            tv    = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
            delta = tb - (tv - tb)
        else:
            close = pd.to_numeric(df["Close"], errors="coerce")
            open_ = pd.to_numeric(df["Open"],  errors="coerce")
            vol   = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
            delta = vol * np.sign(close - open_)

        cvd_mom = delta.rolling(pencere).mean().diff()
        # Normalize
        std = cvd_mom.rolling(20, min_periods=5).std().replace(0, 1e-10)
        return (cvd_mom / std).clip(-3, 3).rename("CVD_Momentum")
    except Exception:
        return pd.Series(0.0, index=df.index, name="CVD_Momentum")


def hesapla_cvd_divergence(df, fiyat_pencere: int = 5) -> pd.Series:
    """
    CVD-Fiyat Divergence sinyali.
    +1 = Bullish divergence (fiyat düşüyor, CVD yükseliyor → dip fırsat)
    -1 = Bearish divergence (fiyat yükseliyor, CVD düşüyor → sahte kırılım)
     0 = Divergence yok
    """
    import pandas as pd, numpy as np
    try:
        cvd_norm = hesapla_cvd_delta(df)
        close    = pd.to_numeric(df["Close"], errors="coerce")
        fiyat_yon = close.diff(fiyat_pencere).apply(np.sign)
        cvd_yon   = cvd_norm.diff(fiyat_pencere).apply(np.sign)
        divergence = pd.Series(0, index=df.index, name="CVD_Divergence", dtype=float)
        # Bullish: fiyat aşağı ama CVD yukarı
        divergence[(fiyat_yon < 0) & (cvd_yon > 0)] = 1.0
        # Bearish: fiyat yukarı ama CVD aşağı
        divergence[(fiyat_yon > 0) & (cvd_yon < 0)] = -1.0
        return divergence
    except Exception:
        return pd.Series(0.0, index=df.index, name="CVD_Divergence")
