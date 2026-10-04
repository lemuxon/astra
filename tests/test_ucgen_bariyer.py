# =========================================================
# ASTRA v58 — ÜÇLÜ BARİYER HEDEFİ TESTLERİ (K-23)
# Çalıştırma: python tests/test_ucgen_bariyer.py
#
# NE KORUYOR:
#   Eski model hedefi `close.pct_change().shift(-1) > 0` idi —
#   "bir sonraki mum yeşil mi?". İki sorunu vardı:
#     1. İşlem mantığıyla uyuşmuyor: bot mumun rengine göre değil,
#        SL/TP seviyelerine göre kazanıyor/kaybediyor.
#     2. Tek barlık yön, sinyal/gürültü oranı en düşük hedeftir.
#   Ölçüldü: dürüst accuracy 0.516, taban çizgisi 0.518.
#
#   Üçlü bariyer (López de Prado) etiketi işlemin GERÇEK sonucuna
#   bağlar: aynı ATR çarpanları, aynı ufuk.
#
# ⚠️ ÖLÇÜM SONUCU: bu hedef beklentiyi KARŞILAMADI. Baş başa
#   karşılaştırmada (aynı ekonomik yargıç ile) eski hedeften hafif
#   KÖTÜ çıktı. Ayrıntı DEVAM_NOTLARI §0.3'te. Makine korunuyor çünkü
#   (a) `HEDEF_TIPI` ile denenebilir olması gerekiyor,
#   (b) short tarafında zayıf ama tutarlı bir iz var.
#
#   Bu dosyanın işi hedefin İYİ olduğunu değil, DOĞRU HESAPLANDIĞINI
#   kanıtlamaktır. Yanlış hesaplanan bir hedefle yapılan karşılaştırma
#   hiçbir şey söylemez.
#
# §4.1: Muhafızların yanına kontrol testleri.
# Testler AĞA ÇIKMAZ — sentetik fiyat yolları kullanılır.
# =========================================================
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# v57: ÜRETİM durum dosyalarına yazmayı engelle. Proje modülleri import
# EDİLMEDEN ÖNCE çağrılmalı — config.py yolları import anında okur.
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("BINANCE_API_SECRET", "")

import numpy as np
import pandas as pd


def _df(bars):
    """bars: [(open, high, low, close), ...] → OHLCV DataFrame."""
    idx = pd.date_range("2026-01-01", periods=len(bars), freq="5min", tz="UTC")
    return pd.DataFrame(
        {"Open":  [b[0] for b in bars],
         "High":  [b[1] for b in bars],
         "Low":   [b[2] for b in bars],
         "Close": [b[3] for b in bars],
         "Volume": [100.0] * len(bars)}, index=idx)


def _atr(df, deger):
    return pd.Series(deger, index=df.index, dtype=float)


def _etiket(bars, atr=1.0, sl=1.5, tp=2.0, max_bar=5):
    from core.sinyal_skor import ucgen_bariyer
    df = _df(bars)
    return ucgen_bariyer(df, df["Close"], _atr(df, atr), sl, tp, max_bar)


# ─────────────────────────────────────────────
# 1. MUHAFIZ — temel bariyer mantığı
# ─────────────────────────────────────────────
def test_tp_once_vurulursa_1():
    """Giriş 100, ATR 1 → TP=102, SL=98.5. Fiyat önce 102'ye çıkıyor."""
    # bar0 giriş(100) · bar1 102.5'e değiyor (TP) · sonrası ilgisiz
    e = _etiket([(100, 100, 100, 100), (101, 102.5, 100.5, 102),
                 (102, 103, 101, 102), (102, 103, 101, 102),
                 (102, 103, 101, 102), (102, 103, 101, 102),
                 (102, 103, 101, 102)])
    assert e.iloc[0] == 1, f"TP önce vuruldu ama etiket {e.iloc[0]}"


def test_sl_once_vurulursa_0():
    """Fiyat önce 98.5'in altına iniyor."""
    e = _etiket([(100, 100, 100, 100), (99, 99.5, 98.0, 98.2),
                 (98, 99, 97, 98), (98, 99, 97, 98), (98, 99, 97, 98),
                 (98, 99, 97, 98), (98, 99, 97, 98)])
    assert e.iloc[0] == 0, f"SL önce vuruldu ama etiket {e.iloc[0]}"


def test_ayni_barda_ikisi_de_vurulursa_KOTUMSER():
    """Bar hem 102'ye hem 98'e değiyor — hangisinin önce olduğu bilinemez.

    Bar içi sıralama veride YOK. İyimser saymak (TP) backtest'i
    sistematik olarak şişirir; bu yüzden SL sayılır.
    """
    e = _etiket([(100, 100, 100, 100), (100, 103, 97, 100),
                 (100, 101, 99, 100), (100, 101, 99, 100),
                 (100, 101, 99, 100), (100, 101, 99, 100),
                 (100, 101, 99, 100)])
    assert e.iloc[0] == 0, (
        "Aynı barda hem TP hem SL vuruldu; kötümser kural gereği SL "
        "(0) sayılmalıydı — iyimser sayım backtest'i şişirir")


def test_dikey_bariyer_getiri_isareti():
    """Hiçbir bariyere değmeden ufuk dolarsa getiri işareti kullanılır."""
    yatay = [(100, 100.5, 99.5, 100)] * 3
    yukari = [(100, 100.5, 99.5, 100.4)] * 4
    e = _etiket([(100, 100, 100, 100)] + yatay + yukari, max_bar=4)
    assert e.iloc[0] == 1, (
        f"Bariyere değilmedi, ufukta fiyat yukarıdaydı → 1 beklenirdi, "
        f"{e.iloc[0]} geldi")

    asagi = [(100, 100.5, 99.5, 99.6)] * 4
    e2 = _etiket([(100, 100, 100, 100)] + yatay + asagi, max_bar=4)
    assert e2.iloc[0] == 0, "Ufukta fiyat aşağıdaydı → 0 beklenirdi"


def test_son_barlar_etiketlenmez():
    """Son max_bar barın geleceği yok → NaN olmalı (uydurma etiket yok)."""
    e = _etiket([(100, 101, 99, 100)] * 20, max_bar=5)
    assert e.iloc[-5:].isna().all(), (
        "Son max_bar bar etiketlenmiş — geleceği olmayan barlara uydurma "
        "etiket verilmiş olur")
    assert e.iloc[:-5].notna().any(), "Hiçbir bar etiketlenmemiş"


# ─────────────────────────────────────────────
# 2. KONTROL — sabit etiket üreten kod da geçerdi
# ─────────────────────────────────────────────
def test_etiket_HER_IKI_degeri_de_uretebilir():
    """Kontrol testi (§4.1): hep 0 (ya da hep 1) döndüren kod da
    yukarıdaki muhafızların bir kısmını geçerdi."""
    rng = np.random.default_rng(3)
    fiyat = 100 + np.cumsum(rng.normal(0, 0.5, 400))
    bars = [(p, p + 0.4, p - 0.4, p) for p in fiyat]
    e = _etiket(bars, atr=0.5, max_bar=10).dropna()
    assert set(e.unique()) == {0.0, 1.0}, (
        f"Etiket tek değere çökmüş: {sorted(e.unique())} — hedef "
        f"ayrım üretmiyor")
    oran = e.mean()
    assert 0.15 < oran < 0.85, f"Etiket aşırı dengesiz: target=1 oranı {oran:.3f}"


# ─────────────────────────────────────────────
# 3. YAPILANDIRMA — iki hedef de seçilebilmeli
# ─────────────────────────────────────────────
def test_hedef_tipi_sonraki_bar_eski_davranis():
    """`HEDEF_TIPI=sonraki_bar` eski hedefi birebir geri vermeli.

    Karşılaştırma yapabilmek için eski davranışın korunması ŞART.
    """
    import importlib, config
    import core.sinyal_skor as ss
    eski = os.environ.get("HEDEF_TIPI")
    os.environ["HEDEF_TIPI"] = "sonraki_bar"
    try:
        importlib.reload(config); importlib.reload(ss)
        df = _df([(100, 101, 99, 100 + i * 0.1) for i in range(60)])
        hedef = ss.hedef_uret(df, df["Close"], _atr(df, 1.0), "T")
        beklenen = (df["Close"].pct_change().shift(-1) > 0).astype(int)
        assert (hedef.dropna() == beklenen.loc[hedef.dropna().index]).all(), \
            "sonraki_bar hedefi eski davranışı vermiyor"
    finally:
        if eski is None: os.environ.pop("HEDEF_TIPI", None)
        else: os.environ["HEDEF_TIPI"] = eski
        importlib.reload(config); importlib.reload(ss)


def test_hedef_tipi_ucgen_bariyer_secilebilir():
    """`HEDEF_TIPI=ucgen_bariyer` gerçekten bariyer hedefini üretmeli."""
    import importlib, config
    import core.sinyal_skor as ss
    eski = os.environ.get("HEDEF_TIPI")
    os.environ["HEDEF_TIPI"] = "ucgen_bariyer"
    try:
        importlib.reload(config); importlib.reload(ss)
        rng = np.random.default_rng(11)
        fiyat = 100 + np.cumsum(rng.normal(0, 0.5, 300))
        df = _df([(p, p + 0.4, p - 0.4, p) for p in fiyat])
        h = ss.hedef_uret(df, df["Close"], _atr(df, 0.5), "T")
        b = ss.ucgen_bariyer(df, df["Close"], _atr(df, 0.5),
                             config.FUTURES_SL_ATR_MULT,
                             config.FUTURES_TP_ATR_MULT,
                             config.HEDEF_MAX_BAR)
        assert (h.dropna() == b.dropna()).all(), \
            "hedef_uret, ucgen_bariyer ile aynı sonucu vermiyor"
    finally:
        if eski is None: os.environ.pop("HEDEF_TIPI", None)
        else: os.environ["HEDEF_TIPI"] = eski
        importlib.reload(config); importlib.reload(ss)


# ─────────────────────────────────────────────
# 4. SIZINTI — örtüşen etiketler için embargo
# ─────────────────────────────────────────────
def test_embargo_walk_forward_train_kuyrugunu_atar():
    """`walk_forward_cv(embargo=N)` train'in son N satırını atmalı.

    Üçlü bariyer etiketi ileriye baktığı için train'in son satırlarının
    etiketi TEST dönemi fiyatlarından hesaplanmıştır. Atılmazsa model
    test dönemini dolaylı görür ve hedef sahte şekilde iyi görünür.
    """
    from engines.backtest_engine import walk_forward_cv

    gorulen = {}

    class _Sahte:
        def __init__(self, **kw): pass
        def fit(self, X, y):
            gorulen["son_index"] = int(X.index[-1]); return self
        def predict(self, X): return np.zeros(len(X), dtype=int)

    X = pd.DataFrame({"a": np.arange(400.0)}, index=range(400))
    y = pd.Series(np.zeros(400, dtype=int), index=range(400))

    walk_forward_cv(X, y, _Sahte, {}, n_splits=1, embargo=0)
    embargosuz = gorulen["son_index"]
    walk_forward_cv(X, y, _Sahte, {}, n_splits=1, embargo=30)
    embargolu = gorulen["son_index"]

    assert embargolu == embargosuz - 30, (
        f"Embargo uygulanmadı: train sonu {embargosuz} → {embargolu} "
        f"(30 satır atılmalıydı)")


def test_embargo_varsayilani_davranisi_degistirmez():
    """Kontrol: embargo=0 (varsayılan) eski davranışı korumalı."""
    from engines.backtest_engine import walk_forward_cv
    gorulen = {}

    class _Sahte:
        def __init__(self, **kw): pass
        def fit(self, X, y):
            gorulen.setdefault("n", []).append(len(X)); return self
        def predict(self, X): return np.zeros(len(X), dtype=int)

    X = pd.DataFrame({"a": np.arange(400.0)}, index=range(400))
    y = pd.Series(np.zeros(400, dtype=int), index=range(400))
    walk_forward_cv(X, y, _Sahte, {}, n_splits=3)
    assert gorulen["n"] == [100, 200, 300], (
        f"embargo'suz fold boyutları değişmiş: {gorulen['n']}")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA ÜÇLÜ BARİYER — {len(testler)} test")
    print(f"{'='*56}")
    basari, hata = 0, 0
    for t in testler:
        try:
            t()
            print(f"  [GEÇTİ]  {t.__name__}")
            basari += 1
        except AssertionError as e:
            print(f"  [HATA]   {t.__name__}")
            print(f"           → {str(e)[:95]}")
            hata += 1
        except Exception as e:
            print(f"  [ÇÖKTÜ]  {t.__name__}: {type(e).__name__}: {str(e)[:70]}")
            hata += 1
    print(f"{'='*56}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'='*56}\n")
    sys.exit(0 if hata == 0 else 1)
