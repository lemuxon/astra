# =========================================================
# ASTRA v57 — MİNİMUM RİSK/ÖDÜL KAPISI
# Çalıştırma: python tests/test_rr_kapisi.py
#
# NE KORUYOR:
#   `sl_tp_hesapla` risk/ödül oranını HESAPLAYIP DÖNDÜRÜYORDU ama
#   hiçbir yer KONTROL ETMİYORDU. Sistem "bu işlem 0.77 oranında" diye
#   hesaplayıp yine de açıyordu.
#
#   VOLATILE rejimde çarpanlar R/R'ı TERS ÇEVİRİYOR:
#       sl_mult  = 1.5 × 1.3  = 1.95×ATR   (stop GENİŞLER)
#       tp1_mult = 2.0 × 0.75 = 1.50×ATR   (hedef DARALIR)
#       → R/R 0.77 → başabaş için %57 isabet gerekir
#
#   ÖLÇÜM (2026-09-02, 21 işlem):
#     TP/STOP ile kapanan 10 işlem → isabet **%50** (yazı tura)
#     ama beklenti **−%0.197**
#   Yani kayıp SİNYAL KALİTESİNDEN DEĞİL, ARİTMETİKTEN geliyordu:
#   hedef stop'tan yakınken %50 isabet bile kaybettirir.
#
#   Piyasa o dönemde %92 VOLATILE'di; 21 işlemin 14'ü bu ters oranla açıldı.
#
# EŞİK: R/R > (1-p)/p olmalı. p=%50 → başabaş 1.0. MIN_RR=1.2 pay bırakır.
#   Veriye BAKARAK değil, matematikle seçildi.
#
# §5.3: Kapı PAPER ve CANLI yollarının İKİSİNDE de olmalı — yalnızca
#   birinde olursa paper canlıyı temsil etmez.
# =========================================================
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "test")
os.environ.setdefault("BINANCE_API_SECRET", "test")


# ─────────────────────────────────────────────
# 1. MUHAFIZ — kapı kötü oranı engelliyor mu
# ─────────────────────────────────────────────
def test_volatile_rejimi_engelleniyor():
    """VOLATILE'in 0.77 R/R'ı işlem açtırmamalı.

    Bu oranda başabaş %57 isabet ister; ölçülen %50. Yani her açılan
    işlem negatif beklentili.
    """
    from engines.futures_trade_engine import sl_tp_hesapla, rr_yeterli_mi
    r = sl_tp_hesapla(100.0, "LONG", 1.0, "VOLATILE")
    assert r["rr"] < 1.0, (
        f"VOLATILE R/R {r['rr']} — beklenen <1.0. Çarpanlar değişmiş "
        f"olabilir, testin varsayımı geçersiz.")
    assert not rr_yeterli_mi(r["rr"], "TEST", "VOLATILE"), (
        f"R/R {r['rr']} olmasına rağmen kapı GEÇİRDİ — sistem matematiksel "
        f"olarak kaybeden işlem açar")


def test_saglikli_oran_gecebiliyor():
    """RANGE/TREND'in 1.33 R/R'ı ENGELLENMEMELİ.

    Kapı fazla sıkı olursa sistem hiç işlem açmaz — o da çözüm değil.
    """
    from engines.futures_trade_engine import sl_tp_hesapla, rr_yeterli_mi
    for rejim in ("RANGE", "TREND_UP", "TREND_DOWN"):
        r = sl_tp_hesapla(100.0, "LONG", 1.0, rejim)
        assert rr_yeterli_mi(r["rr"], "TEST", rejim), (
            f"{rejim} R/R={r['rr']} engellendi — kapı fazla sıkı, "
            f"sistem hiç işlem açamaz")


def test_kapi_paper_yolunda_var():
    """Paper `_pozisyon_ac` kapıyı çağırmalı (kaynak düzeyi).

    §5.3: yalnızca canlıda olursa paper canlıyı temsil etmez ve
    toplanan 100 işlem geçersiz olur.
    """
    # ÇAĞRI aranıyor, sadece isim değil. İlk yazımda `"rr_yeterli_mi" in kod`
    # kontrolü vardı ve MUTASYONU KAÇIRDI: çağrı silinse bile `import`
    # satırında isim geçtiği için test yeşil kalıyordu.
    import ast
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "engines", "paper_trading.py"),
              encoding="utf-8") as fh:
        agac = ast.parse(fh.read())
    cagri = any(isinstance(n, ast.Call) and
                getattr(n.func, "id", "") == "rr_yeterli_mi"
                for n in ast.walk(agac))
    assert cagri, (
        "paper_trading R/R kapısını ÇAĞIRMIYOR — paper canlıdan ayrışır, "
        "negatif beklentili işlem açmaya devam eder")


def test_kapi_canli_yolunda_var():
    """Canlı `futures_trade_engine` kapıyı çağırmalı (kaynak düzeyi)."""
    import ast
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "engines", "futures_trade_engine.py"),
              encoding="utf-8") as fh:
        agac = ast.parse(fh.read())
    # rr_yeterli_mi TANIMI değil, ÇAĞRISI aranıyor
    cagri = any(isinstance(n, ast.Call) and
                getattr(n.func, "id", "") == "rr_yeterli_mi"
                for n in ast.walk(agac))
    assert cagri, (
        "canlı yol R/R kapısını çağırmıyor — gerçek parada matematiksel "
        "olarak kaybeden işlem açılır")


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_kapi_esige_gercekten_bakiyor():
    """Eşik değişince karar da değişmeli.

    "Her zaman False döndür" gibi bozuk bir kod, engelleme testini
    geçerdi. Bu test kapının MIN_RR'ı gerçekten okuduğunu kanıtlar.
    """
    import importlib
    import engines.futures_trade_engine as fte

    orij = os.environ.get("MIN_RR")
    try:
        # Eşiği 0.5'e indir → VOLATILE'in 0.77'si artık geçmeli
        os.environ["MIN_RR"] = "0.5"
        import config
        importlib.reload(config)
        r = fte.sl_tp_hesapla(100.0, "LONG", 1.0, "VOLATILE")
        assert fte.rr_yeterli_mi(r["rr"], "TEST", "VOLATILE"), (
            f"MIN_RR=0.5 iken R/R {r['rr']} hâlâ engellendi — kapı eşiği "
            f"okumuyor, sabit davranıyor")
    finally:
        if orij is None:
            os.environ.pop("MIN_RR", None)
        else:
            os.environ["MIN_RR"] = orij
        import config
        importlib.reload(config)


def test_kontrol_basabas_matematigi_dogru():
    """Kapının dayandığı matematik: R/R = (1-p)/p başabaş noktasıdır.

    Bu testin amacı eşiğin KEYFİ olmadığını sabitlemek. R/R 1.0 ise
    başabaş %50, R/R 0.77 ise %57 isabet gerekir.
    """
    for rr, beklenen_wr in ((1.00, 50.0), (0.77, 56.5), (1.33, 42.9),
                            (2.00, 33.3)):
        gereken = 100.0 / (1.0 + rr)
        assert abs(gereken - beklenen_wr) < 0.6, (
            f"R/R {rr} için başabaş %{gereken:.1f}, beklenen %{beklenen_wr} — "
            f"eşiğin dayandığı matematik yanlış")


def test_kontrol_volatile_carpanlari_beklendigi_gibi():
    """VOLATILE çarpanları değişirse bu testler anlamını yitirir.

    Biri çarpanları "düzeltirse" kapı gereksiz hale gelebilir; o zaman
    bu test kırmızıya dönüp durumu bildirir.
    """
    from config import FUTURES_SL_ATR_MULT as S, FUTURES_TP_ATR_MULT as T
    vol_sl = S * 1.3
    vol_tp = T * 0.75
    oran = vol_tp / vol_sl
    assert abs(oran - 0.77) < 0.02, (
        f"VOLATILE R/R {oran:.2f} — 0.77 bekleniyordu. Çarpanlar "
        f"değiştiyse (SL={S}, TP={T}) R/R kapısının eşiği yeniden "
        f"değerlendirilmeli.")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA MİNİMUM R/R KAPISI — {len(testler)} test")
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
