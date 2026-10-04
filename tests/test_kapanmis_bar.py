# =========================================================
# ASTRA v58 — KAPANMIŞ BAR TESTLERİ (K-16)
# Çalıştırma: python tests/test_kapanmis_bar.py
#
# NE KORUYOR:
#   Binance'in döndürdüğü SON mum, içinde bulunulan periyodun HENÜZ
#   KAPANMAMIŞ barıdır; "Close" alanı o andaki fiyattır ve her saniye
#   değişir. Tüm göstergeler (RSI, MACD, ATR, Bollinger) bu yarım barla
#   hesaplanıyordu — sinyal, bar ilerledikçe kendi altından değişen bir
#   zemine dayanıyordu.
#
#   ÖLÇÜLEN ZARAR (paper işlemi #21, 2026-09-02):
#     5m bar 17:10 → O=98.79  H=99.94  C=98.47
#     Bot 17:11'de oluşan barın anlık fiyatını (99.92) okudu ve oradan
#     SHORT açtı. TP 99.14 zaten piyasanın altındaydı → 2.9 dakikada
#     "TP" oldu, +%0.64 yazıldı. Bar KAPANDIĞINDA fiyat 98.47'ydi;
#     kapanmış bar kullanılsaydı o sinyal hiç doğmayacaktı.
#
# İKİ AYRI İHTİYAÇ (karıştırılmamalı):
#   • GÖSTERGELER → kapanmış bar (kararlı zemin)
#   • SL/TP KONTROLÜ → en taze fiyat. Canlıda SL borsada duran bir
#     STOP_MARKET'tir, her tick'te tetiklenir; bar kapanışını beklemez.
#     Oluşan bar `df.attrs["olusan_bar"]` ile taşınır.
#
# TESPİT close_time İLE: "son barı her zaman at" YANLIŞ olurdu —
#   geçmiş aralık istendiğinde (backtest, endTime) son bar kapanmıştır
#   ve atılırsa veri sessizce kaybolur.
#
# Testler AĞA ÇIKMAZ: requests.get yakalanır.
# §4.1: Muhafızların yanına KONTROL testleri.
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

DK = 60_000


class _SahteYanit:
    def __init__(self, veri): self._veri = veri
    def raise_for_status(self): pass
    def json(self): return self._veri


def _bar(open_ms, o, h, l, c, sure_ms=5 * DK):
    """Binance kline satırı (12 alan)."""
    return [open_ms, str(o), str(h), str(l), str(c), "10.0",
            open_ms + sure_ms - 1, "1000.0", 5, "5.0", "500.0", "0"]


def _seri(n, son_bar_olusuyor: bool):
    """n barlık seri. Son bar oluşuyorsa close_time GELECEKTE olur."""
    simdi = int(time.time() * 1000)
    # son barın açılışı: oluşuyorsa şu anki periyot, değilse tamamen geçmiş
    son_open = simdi - 2 * DK if son_bar_olusuyor else simdi - 10 * DK
    barlar = []
    for i in range(n - 1, 0, -1):
        ot = son_open - i * 5 * DK
        barlar.append(_bar(ot, 100, 101, 99, 100))
    # #21 vakasının kopyası: oluşan barın anlık "close"u sıçramış
    barlar.append(_bar(son_open, 98.79, 99.94, 98.40, 99.92))
    return barlar


def _cek(veri, limit=50):
    from data import binance_client as bc
    orij = bc.requests.get
    yakalanan = {}

    def sahte(url, **kw):
        yakalanan["params"] = kw.get("params")
        return _SahteYanit(veri)

    bc.requests.get = sahte
    try:
        df = bc.klines_indir("TESTUSDT", "5m", limit)
    finally:
        bc.requests.get = orij
    return df, yakalanan.get("params", {})


# ─────────────────────────────────────────────
# 1. MUHAFIZ — oluşan bar göstergelere girmemeli
# ─────────────────────────────────────────────
def test_olusan_bar_dataframeden_atilir():
    """#21 vakasının kopyası: sıçrayan yarım bar veriye girmemeli."""
    df, _ = _cek(_seri(10, son_bar_olusuyor=True))
    assert df is not None and len(df) == 9, \
        f"9 kapanmış bar bekleniyordu, {0 if df is None else len(df)} geldi"
    assert float(df["Close"].iloc[-1]) == 100.0, (
        f"Son kapanış {df['Close'].iloc[-1]} — oluşmakta olan barın anlık "
        f"fiyatı (99.92) göstergelere sızdı")


def test_olusan_bar_attrs_ile_tasinir():
    """SL/TP kontrolü için anlık fiyat kaybolmamalı."""
    df, _ = _cek(_seri(10, son_bar_olusuyor=True))
    ob = df.attrs.get("olusan_bar")
    assert ob is not None, "oluşan bar atıldı ama `attrs` ile taşınmadı"
    assert ob["Close"] == 99.92, f"anlık fiyat yanlış taşındı: {ob}"
    assert ob["High"] == 99.94, "oluşan barın High'ı taşınmadı"


def test_ek_bar_istenir_boylece_bar_sayisi_dusmez():
    """limit+1 istenmeli — yoksa her gösterge bir bar eksikle çalışır."""
    _, params = _cek(_seri(10, son_bar_olusuyor=True), limit=200)
    assert params.get("limit") == 201, (
        f"limit={params.get('limit')} istendi; 201 olmalıydı "
        f"(atılan bar telafi edilmiyor)")


# ─────────────────────────────────────────────
# 2. KONTROL — "hep son barı at" YANLIŞ olurdu
# ─────────────────────────────────────────────
def test_kapanmis_son_bar_ATILMAZ():
    """Kontrol testi (§4.1). Geçmiş aralıkta son bar KAPANMIŞTIR.

    Backtest `endTime` ile geçmiş veri çeker; orada son bar atılırsa
    veri sessizce kaybolur. "Her zaman sonuncuyu at" diyen bir kod
    yukarıdaki muhafızları geçerdi ama bunu bozardı.
    """
    df, _ = _cek(_seri(10, son_bar_olusuyor=False))
    assert df is not None and len(df) == 10, (
        f"Kapanmış son bar atıldı ({len(df) if df is not None else 0}/10) — "
        f"geçmiş veride bar kaybı olur")
    assert df.attrs.get("olusan_bar") is None, \
        "oluşan bar yokken attrs doldurulmuş"


def test_tek_barlik_seri_cokmez():
    """Sınır durumu: tek bar ve o da oluşuyorsa boş df dönmeli, çökmemeli."""
    simdi = int(time.time() * 1000)
    df, _ = _cek([_bar(simdi - 2 * DK, 100, 101, 99, 100.5)])
    assert df is not None, "tek oluşan barda None döndü — çağıranlar çöker"
    assert len(df) == 0, f"oluşan tek bar atılmalıydı, {len(df)} kaldı"


# ─────────────────────────────────────────────
# 3. YAPISAL — SL/TP taze fiyatı kullanmalı
# ─────────────────────────────────────────────
def test_sl_tp_kontrolu_taze_fiyat_kullanir():
    """Göstergeler kapanmış bara, SL/TP anlık fiyata bakmalı.

    Canlıda SL borsada duran bir STOP_MARKET'tir; bar kapanışını
    beklemez. `son_close` kullanılsaydı paper, canlının çoktan
    tetiklediği stop'u 5 dakikaya kadar geç görürdü (§5.3).
    """
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "main.py")
    with open(yol, encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))
    assert "stop_tp_kontrol" in kod, "stop_tp_kontrol çağrısı bulunamadı"
    for parca in kod.split("stop_tp_kontrol(")[1:]:
        arg = parca.split(")")[0]
        assert "anlik_fiyat" in arg, (
            f"stop_tp_kontrol({arg}) taze fiyatı kullanmıyor — kapanmış bar "
            f"kapanışıyla SL/TP kontrolü canlıdan sapar")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA KAPANMIŞ BAR — {len(testler)} test")
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
