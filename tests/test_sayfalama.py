# =========================================================
# ASTRA v58 — KLINE SAYFALAMA TESTLERİ (K-24)
# Çalıştırma: python tests/test_sayfalama.py
#
# NE KORUYOR:
#   Binance tek istekte en fazla 1000 mum döner. `_period_to_limit`
#   bunu SESSİZCE kırpıyordu:
#
#       istenen "7d/5m"  = 2016 bar  →  alınan 1000 bar (≈3.5 gün)
#       istenen "30d/5m" = 8640 bar  →  alınan 1000 bar (≈3.5 gün)
#
#   Hiçbir uyarı yoktu. "Eğitim penceresini uzat" diyen her değişiklik
#   sessizce etkisiz kalıyordu — K-22'de retrain'i 7d/5m'e çevirmek de
#   gerçekte 1000 bar getiriyordu.
#
#   Bu, §5.2'deki "istenen ≠ yapılan olduğu her yerde sesli ol"
#   kuralının ihlaliydi: kod isteneni sessizce küçültüyordu.
#
# §4.1: Muhafızların yanına kontrol testleri — "her zaman sayfala"
#   diyen bir kod da muhafızları geçerdi ama tek sayfalık istekler için
#   gereksiz ağ trafiği üretirdi.
#
# Testler AĞA ÇIKMAZ: requests.get yakalanır, sahte mum üretilir.
# =========================================================
import sys, os, time, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# v57: ÜRETİM durum dosyalarına yazmayı engelle. Proje modülleri import
# EDİLMEDEN ÖNCE çağrılmalı — config.py yolları import anında okur.
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("BINANCE_API_SECRET", "")

DK5 = 5 * 60_000


class _SahteYanit:
    def __init__(self, veri): self._veri = veri
    def raise_for_status(self): pass
    def json(self): return self._veri


def _bar(open_ms):
    return [open_ms, "100.0", "101.0", "99.0", "100.5", "10.0",
            open_ms + DK5 - 1, "1000.0", 5, "5.0", "500.0", "0"]


def _sahte_borsa(toplam_bar, simdi_ms=None):
    """`toplam_bar` kadar geçmişi olan bir borsayı taklit eder.

    endTime'a saygı duyar; her istekte en fazla `limit` bar döner.
    Böylece sayfalama mantığı gerçekten sınanır.
    """
    simdi_ms = simdi_ms or int(time.time() * 1000)
    # en yeni barın açılışı: şu anki 5m periyodunun başı
    son_open = (simdi_ms // DK5) * DK5
    ilk_open = son_open - (toplam_bar - 1) * DK5
    cagrilar = []

    def sahte(url, **kw):
        p = kw.get("params", {})
        limit = int(p.get("limit", 500))
        end = int(p.get("endTime", son_open + DK5))
        cagrilar.append({"limit": limit, "endTime": p.get("endTime")})
        # end'den geriye doğru limit kadar bar
        son = min(son_open, ((end - 1) // DK5) * DK5)
        bas = max(ilk_open, son - (limit - 1) * DK5)
        if son < ilk_open:
            return _SahteYanit([])
        return _SahteYanit([_bar(t) for t in range(bas, son + DK5, DK5)])

    return sahte, cagrilar


def _cek(limit, toplam_bar):
    from data import binance_client as bc
    sahte, cagrilar = _sahte_borsa(toplam_bar)
    orij = bc.requests.get
    bc.requests.get = sahte
    try:
        df = bc.klines_indir("TESTUSDT", "5m", limit)
    finally:
        bc.requests.get = orij
    return df, cagrilar


# ─────────────────────────────────────────────
# 1. MUHAFIZ — kırpma olmamalı
# ─────────────────────────────────────────────
def test_period_to_limit_kirpmiyor():
    """İstenen bar sayısı 1000'e kırpılmamalı."""
    from data.binance_client import _period_to_limit
    assert _period_to_limit("7d", "5m") > 1000, (
        f"7d/5m için {_period_to_limit('7d','5m')} bar isteniyor — "
        f"2016 olmalıydı; sessiz kırpma geri gelmiş")
    assert _period_to_limit("30d", "5m") > 8000, \
        "30d/5m isteği kırpılıyor"


def test_bin_ustu_istek_sayfalanir():
    """2500 bar istenince birden fazla istek yapılmalı ve hepsi gelmeli."""
    df, cagrilar = _cek(2500, toplam_bar=5000)
    assert df is not None, "sayfalı çekim None döndü"
    assert len(df) >= 2400, (
        f"{len(df)} bar geldi — ~2500 beklenirdi; sayfalama eksik "
        f"({len(cagrilar)} istek yapıldı)")
    assert len(cagrilar) >= 3, (
        f"Yalnızca {len(cagrilar)} istek yapıldı — 2500 bar için en az "
        f"3 sayfa gerekir")


def test_sayfali_sonuc_kronolojik_ve_tekil():
    """Sayfalar birleştirilirken sıra bozulmamalı, tekrar olmamalı."""
    df, _ = _cek(2500, toplam_bar=5000)
    assert df.index.is_monotonic_increasing, (
        "Sayfalar birleştirildikten sonra index artan değil — geriye "
        "doğru çekilen parçalar ters sırada eklenmiş")
    assert not df.index.duplicated().any(), \
        "Sayfa sınırlarında tekrar eden bar var"


def test_sayfali_yolda_da_olusan_bar_atilir():
    """K-16 kuralı sayfalı yolda da geçerli olmalı.

    İki ayrı DataFrame kurma yolu olsaydı, biri düzeltilip diğeri
    unutulurdu — bu test ortak yardımcıyı zorunlu kılar.
    """
    df, _ = _cek(2500, toplam_bar=5000)
    ob = df.attrs.get("olusan_bar")
    assert ob is not None, (
        "Sayfalı yolda oluşmakta olan bar `attrs` ile taşınmıyor — "
        "SL/TP kontrolü taze fiyatı kaybeder")
    # oluşan bar df'in İÇİNDE olmamalı
    assert ob["open_time"] not in df.index, \
        "Oluşan bar hem atılmamış hem attrs'a yazılmış"


# ─────────────────────────────────────────────
# 2. KONTROL — küçük istekler sayfalanmamalı
# ─────────────────────────────────────────────
def test_kucuk_istek_tek_cagri():
    """Kontrol testi (§4.1). 576 bar için tek istek yeterli.

    "Her zaman sayfala" diyen bir kod yukarıdaki muhafızları geçerdi
    ama her döngüde gereksiz ağ trafiği üretirdi (5 coin × 4 timeframe).
    """
    df, cagrilar = _cek(576, toplam_bar=5000)
    assert len(cagrilar) == 1, (
        f"576 bar için {len(cagrilar)} istek yapıldı — 1 olmalıydı")
    assert df is not None and len(df) >= 500, \
        f"tek sayfalı çekim bozuldu: {0 if df is None else len(df)} bar"


def test_borsada_az_veri_varsa_cokmez():
    """Sınır durumu: 5000 bar isteniyor ama borsada 1200 var."""
    df, cagrilar = _cek(5000, toplam_bar=1200)
    assert df is not None, "veri az olunca None döndü — çağıranlar çöker"
    assert 1000 <= len(df) <= 1200, (
        f"{len(df)} bar geldi — borsadaki 1200'e yakın olmalıydı "
        f"(sonsuz döngü ya da erken kesme olabilir)")
    assert len(cagrilar) <= 8, \
        f"{len(cagrilar)} istek — veri tükendiğinde döngü durmalıydı"


# ─────────────────────────────────────────────
# 3. YAPISAL (K-25) — eğitim penceresi tek kaynak
# ─────────────────────────────────────────────
def test_egitim_penceresi_tek_kaynak():
    """Drift retrain, ana döngüyle AYNI pencere ayarını kullanmalı.

    Eskiden ana döngü 2d/5m, drift retrain 14d/1h kullanıyordu ve İKİSİ
    DE aynı model dosyasına yazıyordu — modelin neyle eğitildiği hangi
    yolun son çalıştığına bağlıydı (K-22/K-25).
    """
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "main.py")
    with open(yol, encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))
    i = kod.find("def _self_train_tetikle")
    assert i > 0, "_self_train_tetikle bulunamadı — test hedefi kaymış"
    govde = kod[i:i + 2500]
    assert "MODEL_EGITIM_PERIOD" in govde, (
        "Drift retrain sabit pencere kullanıyor — ana döngüyle ayrışır")
    assert 'interval="1h"' not in govde, (
        "Drift retrain hâlâ 1h ile eğitiyor; servis 5m — feature "
        "ölçekleri uyuşmaz (K-22)")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA KLINE SAYFALAMA — {len(testler)} test")
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
