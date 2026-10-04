# =========================================================
# ASTRA v56 — SİNYAL SKORLAMA / FEATURE ÜRETİMİ
# =========================================================
# main.py modülerleştirmesinin 2. adımı.
#
# Bu fonksiyonlar main.py'dan AYNEN taşındı; davranış değişikliği YOKTUR.
# Seçilme sebebi: saf hesaplama — global duruma dokunmuyorlar
# (ai_score_hesapla ve karar_ver'in HİÇ dış bağımlılığı yok).
#
# ⚠️ BİLİNEN SORUN (taşımada KASITLI olarak düzeltilmedi):
#    risk_hesapla() yön parametresi almıyor; her zaman LONG mantığıyla
#    SL'i aşağı, TP'yi yukarı koyuyor. SELL sinyallerinde Telegram
#    raporunda ters görünür. Gerçek emir yolu sl_tp_hesapla() kullandığı
#    için EMİRLER etkilenmez — bu yalnızca raporlama hatasıdır.
#    Refactor ile düzeltmeyi aynı adımda yapmak, bir sorun çıkarsa
#    hangisinden kaynaklandığını belirsizleştirir. Ayrı ele alınmalı.
# =========================================================
import logging
import pandas as pd

import sys; sys.path.append("..")
from config import BALANCE, RISK_PERCENT
from data.binance_client import close_al
from core.indicators import (
    hesapla_rsi, hesapla_macd, hesapla_atr, hesapla_adx, hesapla_cci,
    hesapla_stoch_rsi, hesapla_williams_r, hesapla_obv, hesapla_supertrend,
    hesapla_bollinger_bandwidth, mumlar_hesapla,
    # CVD göstergeleri de indicators içinde (market_data'da değil)
    hesapla_cvd_delta, hesapla_cvd_momentum, hesapla_cvd_divergence,
    hesapla_taker_buy_ratio,
)

log = logging.getLogger("ASTRA")


def feature_olustur(df, sembol):
    close = close_al(df)
    if close.empty: return pd.DataFrame(), pd.Series(dtype=int)
    mum = mumlar_hesapla(df, sembol); macd, sig, hist = hesapla_macd(close)
    stoch = hesapla_stoch_rsi(close); wil = hesapla_williams_r(df, sembol)
    cci_s = hesapla_cci(df, sembol); atr = hesapla_atr(df, sembol)
    obv = hesapla_obv(df, sembol); bb_bw = hesapla_bollinger_bandwidth(close)
    taker_ratio = hesapla_taker_buy_ratio(df)
    adx_s, plus_di, minus_di = hesapla_adx(df, sembol)
    try: _, st_dir = hesapla_supertrend(df, sembol)
    except (AttributeError, ValueError, KeyError): st_dir = pd.Series(1, index=close.index)
    # ── v58 (K-26): HAM FİYAT SEVİYELERİ FEATURE DEĞİLDİR ─────
    # MA20 / EMA9 / EMA21 / EMA50 / EMA200 ham fiyat seviyeleridir
    # (ölçüm: hepsinin ortalaması ≈ 67.383, yani BTC fiyatının kendisi).
    # Ağaç modelleri MUTLAK EŞİKTE böler ve eğitim aralığının dışına
    # EKSTRAPOLE EDEMEZ. BTC bu 60 günlük pencerede 67k → 77k gitti;
    # 67k'da öğrenilen "EMA50 > 67.234" kuralı 77k'da anlamsızdır.
    # Aynı sorun OBV ve OBV_MA20'de de var (kümülatif, sınırsız büyür).
    #
    # Bilgileri KAYBOLMUYOR — durağan karşılıkları zaten aşağıda:
    #   EMA50/EMA200 → Price_EMA50, Price_EMA200
    #   EMA9/EMA21   → EMA9_21_cross
    # MA20'nin durağan karşılığı YOK ve eklenmesi ölçümde KÖTÜ
    # çıktı (aşağıdaki not) — bu yüzden tamamen kaldırıldı.
    #   OBV/OBV_MA20 → OBV_Diff
    # Bu yüzden ham olanlar yalnızca ARA DEĞER olarak tutuluyor,
    # feature setine girmiyor.
    #
    # ÖLÇÜM (60 gün 5m, 5 sembol, 40 eşli katman):
    #   42 feature (hepsi)  : -0.0039  std 0.0370
    #   35 feature (ham yok): +0.0011  std 0.0311
    #   eşli fark B-A: +0.0050  p=0.347
    # ⚠️ PERFORMANS FAYDASI KANITLANMADI (p=0.347). Değişikliğin
    # gerekçesi DOĞRULUK: durağan olmayan feature yapısal hatadır ve
    # ölçüm zarar vermediğini gösteriyor. Yan fayda: varyans %16 düşük,
    # eğitim %25 hızlı.
    #
    # Not: "atmak yerine büyüklüğü durağanlaştırıp eklemek" de denendi
    # (Price_MA20, EMA9_21_dist, OBV_Norm) — B'den KÖTÜ çıktı
    # (eşli fark -0.0046, p=0.153). Yani o büyüklük bilgisi değersiz.
    _ema9   = close.ewm(span=9).mean()
    _ema21  = close.ewm(span=21).mean()
    _ema50  = close.ewm(span=50).mean()
    _ema200 = close.ewm(span=200).mean()

    ft = pd.DataFrame(index=df.index)
    ft["Price_EMA50"]  = (close - _ema50)  / _ema50.replace(0, 1e-10)  * 100
    ft["Price_EMA200"] = (close - _ema200) / _ema200.replace(0, 1e-10) * 100
    ft["EMA9_21_cross"] = (_ema9 > _ema21).astype(int)
    ft["SuperTrend_Dir"] = st_dir.reindex(close.index).fillna(1)
    ft["RSI"]       = hesapla_rsi(close); ft["Stoch_RSI"] = stoch
    # v58 (K-26): MACD ve MACD_Hist FİYAT BİRİMİNDEDİR (EMA farkı).
    # 1000x fiyat testinde ölçekleri 1000x kaydı — ham EMA'larla aynı
    # kusur. Fiyata bölünüp yüzdeye çevrildi; şekil bilgisi korunuyor.
    ft["Williams_R"] = wil; ft["CCI"] = cci_s
    ft["MACD"]      = macd / close.replace(0, 1e-10) * 100
    ft["MACD_Hist"] = hist / close.replace(0, 1e-10) * 100
    ft["MACD_Cross"] = (macd > sig).astype(int)
    ft["Momentum_5"]  = close.pct_change(5)  * 100
    ft["Momentum_20"] = close.pct_change(20) * 100
    # v58 (K-26): Ham `ATR` ATILDI — `ATR_pct` zaten aynı bilginin
    # durağan hâli. İkisini birden tutmak, biri kullanılamaz olan bir
    # duplikasyondu.
    ft["ATR_pct"] = atr / close.replace(0, 1e-10) * 100
    ft["Volatility_10"] = close.pct_change().rolling(10).std() * 100; ft["BB_Width"] = bb_bw
    # v58 (K-26): ham OBV ve OBV_MA20 kümülatiftir (sınırsız büyür) →
    # feature setinden çıkarıldı. Durağan fark korunuyor.
    ft["OBV_Diff"] = obv - obv.rolling(20).mean()
    ft["Taker_Ratio"] = taker_ratio
    ft["Volume_Ratio"] = df["Volume"] / df["Volume"].rolling(20).mean().replace(0, 1e-10)
    ft["ADX"] = adx_s; ft["Plus_DI"] = plus_di; ft["Minus_DI"] = minus_di; ft["DI_Diff"] = plus_di - minus_di
    ft = ft.join(mum[["Candle_Strength", "Bullish_Engulfing", "Bearish_Engulfing",
                       "Doji", "Hammer", "Shooting_Star", "Morning_Star", "Three_White_Soldiers"]])
    # v58 (K-26): Candle_Strength da fiyat birimindeydi (mum gövdesi).
    ft["Candle_Strength"] = ft["Candle_Strength"] / close.replace(0, 1e-10) * 100
    # v18: CVD Delta — alıcı/satıcı baskısı (model accuracy +3-5 puan)
    try:
        ft["CVD_Norm"]       = hesapla_cvd_delta(df)
        ft["CVD_Momentum"]   = hesapla_cvd_momentum(df)
        ft["CVD_Divergence"] = hesapla_cvd_divergence(df)
    except Exception as _cvd_e:
        log.debug(f"[CVD feature] {sembol}: {_cvd_e}")
        ft["CVD_Norm"] = 0.0; ft["CVD_Momentum"] = 0.0; ft["CVD_Divergence"] = 0.0
    target = hedef_uret(df, close, atr, sembol)
    veri = ft.join(target.rename("Target")).dropna()
    return veri.drop(columns=["Target"]), veri["Target"].astype(int)


# ── v58 (K-23): ÜÇLÜ BARİYER HEDEFİ ───────────────────────────
def ucgen_bariyer(df, close, atr, sl_mult: float, tp_mult: float,
                   max_bar: int) -> pd.Series:
    """Her bar için: TP'ye mi SL'e mi ÖNCE değer?

    1 = önce TP (long kazanırdı) · 0 = önce SL · dikey bariyerde getiri
    işareti (pozisyon hâlâ açıkken mark-to-market çıkış).

    ── NEDEN (López de Prado, "Advances in Financial ML") ────────
    Eski hedef `close.pct_change().shift(-1) > 0` idi: "bir sonraki
    mum yeşil mi?". Bunun iki sorunu var:

    1. **İşlem mantığıyla uyuşmuyor.** Bot bir sonraki mumun rengine
       göre değil, SL/TP seviyelerine göre para kazanıp kaybediyor.
       Model, kazanmakla ilgisi olmayan bir soruyu tahmin ediyordu.
    2. **Neredeyse saf gürültü.** Tek barlık yön, sinyal/gürültü oranı
       en düşük tahmin hedefidir. Ölçüldü: dürüst accuracy 0.516,
       çoğunluk sınıfı taban çizgisi 0.518 (DEVAM_NOTLARI §0.2).

    Üçlü bariyer, etiketi işlemin GERÇEK sonucuna bağlar: aynı ATR
    çarpanları, aynı ufuk. Model artık "bu girişten long açsam TP'ye mi
    SL'e mi değerdim" sorusunu öğreniyor.

    ⚠️ ETİKETLER ÖRTÜŞÜR. Ardışık barların ileri pencereleri iç içedir;
    train/test sınırında bilgi sızar. Bu yüzden `egitim_test_bol()`
    train'in son `max_bar` satırını ATAR (purging) ve walk-forward
    aynı embargoyu uygular. Bu yapılmazsa üçlü bariyer, eski hedeften
    daha iyi görünür ama sebebi sızıntıdır.
    """
    yuksek = df["High"].values
    dusuk  = df["Low"].values
    kapanis = close.values
    a = atr.reindex(close.index).values
    n = len(kapanis)
    out = pd.Series(index=close.index, dtype="float64")

    for i in range(n):
        giris = kapanis[i]
        av = a[i]
        if not (giris > 0) or not (av > 0):
            continue
        ust = giris + av * tp_mult      # long TP
        alt = giris - av * sl_mult      # long SL
        son = min(i + max_bar, n - 1)
        if son <= i:
            continue
        etiket = None
        for j in range(i + 1, son + 1):
            # Aynı barda ikisi de vurulduysa KÖTÜ olanı say (kötümser).
            # Hangisinin önce geldiğini bar içi veriyle bilemeyiz;
            # iyimser saymak backtest'i sistematik şişirir.
            tp_vuruldu = yuksek[j] >= ust
            sl_vuruldu = dusuk[j]  <= alt
            if sl_vuruldu:
                etiket = 0; break
            if tp_vuruldu:
                etiket = 1; break
        if etiket is None:
            # Dikey bariyer: pozisyon açıkken ufuk doldu → getiri işareti
            etiket = 1 if kapanis[son] > giris else 0
        out.iloc[i] = etiket
    # Son max_bar barın geleceği yok — etiketlenemez
    if max_bar > 0:
        out.iloc[-max_bar:] = float("nan")
    return out


def hedef_uret(df, close, atr, sembol: str = "") -> pd.Series:
    """Yapılandırmaya göre model hedefini üretir.

    `HEDEF_TIPI=sonraki_bar` eski davranışı geri getirir — karşılaştırma
    yapabilmek için bilerek korundu.
    """
    try:
        from config import (HEDEF_TIPI, HEDEF_MAX_BAR,
                            FUTURES_SL_ATR_MULT, FUTURES_TP_ATR_MULT)
    except ImportError:
        return (close.pct_change().shift(-1) > 0).astype(int)

    if HEDEF_TIPI != "ucgen_bariyer":
        return (close.pct_change().shift(-1) > 0).astype(int)

    try:
        return ucgen_bariyer(df, close, atr,
                             FUTURES_SL_ATR_MULT, FUTURES_TP_ATR_MULT,
                             HEDEF_MAX_BAR)
    except Exception as e:
        # fail-loud (§5.2): sessizce eski hedefe düşmek, "üçgen bariyer
        # kullanıyoruz" sanılırken eski etiketle eğitmek demektir.
        log.error(f"[HEDEF] {sembol} üçgen bariyer hesaplanamadı: "
                  f"{type(e).__name__}: {e} → sonraki_bar hedefine düşüldü")
        return (close.pct_change().shift(-1) > 0).astype(int)

def ai_score_hesapla(son_rsi, son_close, son_ma, macd_son, signal_son,
                      yukselis_guveni=50, stoch=50, wil=-50, cci=0,
                      adx=20, rejim="RANGE", market_data=None,
                      mtf_skor=0, supertrend_dir=1):
    """
    v16: Düzeltilmiş AI skor hesabı.
    Sorun: yukselis_guveni > 60 = +3 çok büyük, trend indikatörleri
    birbiriyle yüksek korelasyonlu — RANGE'de de STRONG BUY üretiyordu.
    Çözüm: Kademeli bonus, rejim penaltisi, eşik yükseltme.
    """
    s = 0

    # ── Momentum İndikatörleri (max ±4) ──────────────────
    # RSI: aşırı satım/alım
    if son_rsi < 25:    s += 2
    elif son_rsi < 35:  s += 1
    elif son_rsi > 75:  s -= 2
    elif son_rsi > 65:  s -= 1

    # Stochastic RSI
    if stoch < 15:   s += 1
    elif stoch > 85: s -= 1

    # Williams %R
    if wil < -85:   s += 1
    elif wil > -15: s -= 1

    # CCI
    if cci < -150:  s += 1
    elif cci > 150: s -= 1

    # ── Trend İndikatörleri (tek grup, max ±3) ─────────
    # MACD (en güçlü trend sinyali)
    if macd_son > signal_son: s += 2
    else:                     s -= 2

    # MA pozisyonu — sadece MACD ile aynı yöndeyse ekstra puan
    if son_close > son_ma and macd_son > signal_son: s += 1
    elif son_close < son_ma and macd_son < signal_son: s -= 1

    # SuperTrend — ADX güçlüyse daha değerli
    if adx > 30:
        if supertrend_dir == 1:   s += 1
        elif supertrend_dir == -1: s -= 1
    # ADX düşükse SuperTrend sinyali zayıf, yar puan
    elif adx > 20:
        if supertrend_dir == 1:   pass  # nötr
        elif supertrend_dir == -1: s -= 1

    # ── Model Güveni (kademeli, max ±2) ─────────────────
    # Önceden: > 60 = +3 (çok büyük, neredeyse her zaman tetikleniyordu)
    if yukselis_guveni >= 80:    s += 2
    elif yukselis_guveni >= 70:  s += 1
    elif yukselis_guveni >= 60:  pass   # nötr — eşiği geçmek yetmiyor
    elif yukselis_guveni < 40:   s -= 2
    elif yukselis_guveni < 50:   s -= 1

    # ── MTF Confluence (max ±2) ──────────────────────────
    if mtf_skor >= 4:    s += 2
    elif mtf_skor >= 2:  s += 1
    elif mtf_skor <= -4: s -= 2
    elif mtf_skor <= -2: s -= 1

    # ── Market Data (max ±2) ─────────────────────────────
    if market_data:
        ms = market_data.get("market_sentiment", 0)
        # Sentiment katkısı sınırlandırıldı
        if ms > 1.5:   s += 1
        elif ms < -1.5: s -= 1
        fr = market_data.get("funding_rate", 0)
        if fr > 0.002:    s -= 2   # Çok pahalı long, short squeeze riski
        elif fr > 0.001:  s -= 1
        elif fr < -0.001: s += 1

    # ── Rejim Penaltisi / Bonusu ─────────────────────────
    if rejim == "BEAR":       s -= 3   # Bear'da long zor
    elif rejim == "VOLATILE": s -= 2   # Volatil'de sinyal güvenilmez
    elif rejim == "RANGE":    s -= 1   # RANGE'de trend sinyalleri yanıltıcı
    elif rejim == "TREND_UP" and adx > 25:   s += 1  # Güçlü trend bonus
    elif rejim == "TREND_DOWN" and adx > 25: s -= 1

    return s

def karar_ver(ai_score):
    """
    v16: Yükseltilmiş eşikler.
    Düzeltilmiş ai_score_hesapla ile max ~10-11 puan mümkün.
    STRONG BUY için gerçekten güçlü sinyal gerekli.
    """
    if ai_score >= 9:    return "🚀 ULTRA STRONG BUY"
    elif ai_score >= 7:  return "✅ STRONG BUY"
    elif ai_score >= 5:  return "📈 BUY"
    elif ai_score >= 3:  return "📊 WEAK BUY"
    elif ai_score <= -9:  return "💀 ULTRA STRONG SELL"
    elif ai_score <= -7: return "🔴 STRONG SELL"
    elif ai_score <= -5: return "📉 SELL"
    elif ai_score <= -3: return "📊 WEAK SELL"
    return "⏳ WAIT"

def risk_hesapla(son_close, son_atr):
    stop = son_close - son_atr * 2; tp = son_close + son_atr * 3
    risk = son_close - stop; reward = tp - son_close
    return {"stop_loss": round(stop, 2), "take_profit": round(tp, 2),
            "rr_ratio": round(reward / risk, 2) if risk > 0 else 0,
            "pozisyon_size": round((BALANCE * RISK_PERCENT) / risk, 6) if risk > 0 else 0}
