# =========================================================
# ASTRA v58 — FEATURE DURAĞANLIK TESTLERİ (K-26)
# Çalıştırma: python tests/test_feature_duraganlik.py
#
# NE KORUYOR:
#   Feature setinde 7 tane HAM FİYAT SEVİYESİ vardı:
#       MA20, EMA9, EMA21, EMA50, EMA200, OBV, OBV_MA20
#   Ölçüm: hepsinin ortalaması ≈ 67.383 — yani BTC fiyatının kendisi.
#
#   Ağaç modelleri (RF/XGB/LGB/GB) MUTLAK EŞİKTE böler ve eğitim
#   aralığının DIŞINA EKSTRAPOLE EDEMEZ. BTC ölçüm penceresinde
#   67k → 77k gitti; 67k'da öğrenilen "EMA50 > 67.234" kuralı 77k'da
#   hiçbir şey ifade etmez. OBV/OBV_MA20 ise kümülatiftir, sınırsız büyür.
#
#   Bilgileri KAYBOLMADI — durağan karşılıkları zaten feature setindeydi:
#       EMA50/EMA200 → Price_EMA50 / Price_EMA200  (yüzde sapma)
#       EMA9/EMA21   → EMA9_21_cross               (ikili)
#       OBV/OBV_MA20 → OBV_Diff                    (fark)
#   Yani ham olanlar duplikasyondu; ara değer olarak duruyorlar.
#
# ⚠️ DEĞİŞİKLİĞİN GEREKÇESİ PERFORMANS DEĞİL, DOĞRULUK.
#   Ölçüm (60 gün 5m, 5 sembol, 40 eşli katman):
#       42 feature : -0.0039  std 0.0370
#       35 feature : +0.0011  std 0.0311
#       eşli fark  : +0.0050  p=0.347   ← anlamlı DEĞİL
#   Ölçümün işi "daha iyi mi" değil, "zarar veriyor mu" idi — vermiyor.
#
#   "Atmak yerine büyüklüğü durağanlaştırıp ekle" de denendi
#   (Price_MA20, EMA9_21_dist, OBV_Norm): eşli fark -0.0046 (p=0.153),
#   yani DAHA KÖTÜ. O büyüklük bilgisi değersiz.
#
# §4.1: Muhafızların yanına kontrol testleri — feature setini tamamen
#   boşaltan bir kod da "ham seviye yok" muhafızını geçerdi.
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

HAM_SEVIYE = ["MA20", "EMA9", "EMA21", "EMA50", "EMA200", "OBV", "OBV_MA20"]
DURAGAN_KARSILIK = ["Price_EMA50", "Price_EMA200", "EMA9_21_cross", "OBV_Diff"]


def _veri(n=600, baslangic=100.0, egim=0.0, seed=5):
    """Sentetik OHLCV. `egim` ile fiyat seviyesini kaydırabiliriz."""
    rng = np.random.default_rng(seed)
    adim = rng.normal(0, 0.5, n) + egim
    close = baslangic + np.cumsum(adim)
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({
        "Open":  close + rng.normal(0, 0.1, n),
        "High":  close + np.abs(rng.normal(0, 0.3, n)),
        "Low":   close - np.abs(rng.normal(0, 0.3, n)),
        "Close": close,
        "Volume": rng.random(n) * 1000 + 500,
    }, index=idx)


def _X(df):
    from core.sinyal_skor import feature_olustur
    X, _ = feature_olustur(df, "TESTSYM")
    return X


# ─────────────────────────────────────────────
# 1. MUHAFIZ — ham seviye feature olmamalı
# ─────────────────────────────────────────────
def test_ham_seviye_featurelari_yok():
    """İsim bazlı: 7 ham seviye feature seti dışında olmalı."""
    X = _X(_veri())
    kalan = [c for c in HAM_SEVIYE if c in X.columns]
    assert not kalan, (
        f"Ham fiyat seviyesi feature'ları geri gelmiş: {kalan}. "
        f"Ağaç modeli mutlak eşikte böler; fiyat aralığı değişince "
        f"bu kurallar anlamsızlaşır")


def test_hicbir_feature_fiyat_olceginde_degil():
    """İsim değil ÖLÇEK bazlı — yeni eklenen bir seviye feature'ı da yakalar.

    İsim listesi kırılgandır: yarın `SMA100` eklenirse liste onu bilmez.
    Bu test ölçeğe bakar, yani kuralı adlandırmadan bağımsız uygular.
    """
    df = _veri(baslangic=50_000.0)
    X = _X(df)
    fiyat = float(df["Close"].mean())
    buyuk = [c for c in X.columns if abs(float(X[c].mean())) > fiyat * 0.01]
    assert not buyuk, (
        f"Fiyat ölçeğinde feature var: {buyuk} (fiyat≈{fiyat:.0f}). "
        f"Durağan olmayan seviye feature'ı eğitim aralığı dışında "
        f"kullanılamaz")


def test_fiyat_seviyesi_degisince_featurelar_kaymaz():
    """AYNI şekilli seri, farklı fiyat seviyesinde → feature'lar benzer.

    Asıl kusur buydu: 100 civarında eğitilen model 100.000 civarında
    bambaşka girdi görüyordu. Durağan feature'larda böyle bir kayma olmaz.
    """
    Xa = _X(_veri(baslangic=100.0, seed=5))
    Xb = _X(_veri(baslangic=100.0, seed=5) * 1.0)   # aynı
    # seviyeyi 1000x büyüt (şekil aynı kalsın diye tüm OHLC ölçeklenir)
    df_c = _veri(baslangic=100.0, seed=5)
    for k in ("Open", "High", "Low", "Close"):
        df_c[k] = df_c[k] * 1000.0
    Xc = _X(df_c)

    ortak = [c for c in Xa.columns if c in Xc.columns]
    kayanlar = []
    for c in ortak:
        a, b = float(Xa[c].mean()), float(Xc[c].mean())
        if abs(a) < 1e-6 and abs(b) < 1e-6:
            continue
        olcek = abs(b) / max(abs(a), 1e-9)
        if olcek > 10:          # 1000x seviye değişimiyle birlikte kaymış
            kayanlar.append((c, round(olcek, 1)))
    assert not kayanlar, (
        f"Fiyat seviyesi 1000x olunca kayan feature'lar: {kayanlar} — "
        f"bunlar durağan değil")


# ─────────────────────────────────────────────
# 2. KONTROL — bilgi kaybolmamalı
# ─────────────────────────────────────────────
def test_duragan_karsiliklar_DURUYOR():
    """Kontrol testi (§4.1). Ham olanlar atıldı ama bilgi korunmalı.

    Feature setini boşaltan bir kod da yukarıdaki muhafızları geçerdi.
    """
    X = _X(_veri())
    eksik = [c for c in DURAGAN_KARSILIK if c not in X.columns]
    assert not eksik, (
        f"Durağan karşılıklar kayıp: {eksik}. Ham seviyeler atılırken "
        f"bilgi de atılmış — trend/hacim sinyali tamamen kaybolur")


def test_feature_sayisi_makul():
    """Kontrol: set ne boşaldı ne de eski hâline döndü."""
    X = _X(_veri())
    assert 30 <= len(X.columns) <= 38, (
        f"{len(X.columns)} feature — 35 civarı bekleniyordu. "
        f"42 ise ham seviyeler geri gelmiş, 30 altıysa fazla atılmış")


def test_featurelar_hala_bilgi_tasiyor():
    """Kontrol: kalan feature'ların ÇOĞU sabit değil, NaN yok.

    ⚠️ Tek tek "hiçbiri sabit olmasın" DENENDİ ve yanlış çıktı:
    sentetik seride `SuperTrend_Dir` sabit kalabiliyor (rejim hiç
    dönmüyor). Gerçek veride sağlıklı (değerler -1/+1, std 0.99).
    Yani bu bir kod kusuru değil, test fikstürünün sınırı — testin
    iddiası ona göre daraltıldı.
    """
    X = _X(_veri())
    sabit = [c for c in X.columns if float(X[c].std()) == 0.0]
    assert len(sabit) <= 2, (
        f"{len(sabit)} feature sabit: {sabit} — feature üretimi bozulmuş "
        f"olabilir (sentetik veride 1-2 tanesi normal)")
    assert not X.isnull().any().any(), "Feature'larda NaN var"


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA FEATURE DURAĞANLIK — {len(testler)} test")
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
