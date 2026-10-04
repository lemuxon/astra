# =========================================================
# ASTRA — PAPER / CANLI REJİM EŞİĞİ EŞİTLİĞİ (v58, K-69)
# Çalıştırma: python tests/test_rejim_esigi_essitligi.py
#
# Paper yolunun sabit ±4, canlı yolun ise rejime göre 3/5/6/7 AI
# eşiği uygulaması, paper örneklemini canlı için geçersiz kılıyordu.
# Bu test, tüm rejim-yön-sınır birleşimlerinde iki yolun AYNI hükmü
# verdiğini doğrular. Ağ, veritabanı ve gerçek emir kullanılmaz.
# =========================================================
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("BINANCE_API_SECRET", "")


def _sonuc(rejim: str, ai: int, conf: int = 100) -> dict:
    return {
        "sembol": "TESTUSDT",
        "rejim": rejim,
        "ai_score": ai,
        "confidence": conf,
    }


def _paper_karari(sonuc: dict, yon: str) -> bool:
    """DB oluşturmadan paper giriş kapısını doğrudan çağır."""
    from engines.paper_trading import PaperTrader
    trader = PaperTrader.__new__(PaperTrader)
    return trader._sinyal_kalitesi_gecer(sonuc, yon, sayacli=False)


def test_tum_rejimlerde_paper_ve_canli_ayni_sinirda_esit():
    """Her rejimde uzun/kısa tam eşikte de eşik altında da aynı hüküm."""
    from engines.futures_trade_engine import rejim_ai_esigi, sinyal_gecerli_mi

    for rejim in ("TREND_UP", "TREND_DOWN", "RANGE", "BEAR", "VOLATILE"):
        esik = rejim_ai_esigi(rejim)
        vakalar = (
            ("LONG", esik, True),
            ("LONG", esik - 1, False),
            ("SHORT", -esik, True),
            ("SHORT", -esik + 1, False),
        )
        for yon, ai, beklenen in vakalar:
            sonuc = _sonuc(rejim, ai)
            canli = sinyal_gecerli_mi(sonuc, yon)
            paper = _paper_karari(sonuc, yon)
            assert canli == paper == beklenen, (
                f"{rejim}/{yon}/ai={ai}: canlı={canli}, paper={paper}, "
                f"beklenen={beklenen}. Rejim eşiği ayrıştı (K-69).")


def test_guven_esigi_de_iki_yolda_esit():
    """KONTROL: eşitlik, AI kapısını kaldırarak sağlanmış olmamalı."""
    from config import MIN_CONFIDENCE
    from engines.futures_trade_engine import rejim_ai_esigi, sinyal_gecerli_mi

    sonuc = _sonuc("VOLATILE", rejim_ai_esigi("VOLATILE"), MIN_CONFIDENCE - 1)
    assert not sinyal_gecerli_mi(sonuc, "LONG")
    assert not _paper_karari(sonuc, "LONG"), (
        "Düşük güven paper yolundan geçti — eşitlik AI kapısını atlayarak "
        "sağlanmış olabilir.")


def test_bilinmeyen_rejim_eski_fallbackini_korur():
    """KONTROL: beklenmedik rejim canlı ve paper'da aynı fallback'i kullanır."""
    from engines.futures_trade_engine import rejim_ai_esigi, sinyal_gecerli_mi

    assert rejim_ai_esigi("BILINMEYEN") == 4
    for ai, beklenen in ((4, True), (3, False)):
        sonuc = _sonuc("BILINMEYEN", ai)
        assert sinyal_gecerli_mi(sonuc, "LONG") == beklenen
        assert _paper_karari(sonuc, "LONG") == beklenen


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA REJİM EŞİĞİ EŞİTLİĞİ — {len(testler)} test")
    print(f"{'=' * 58}")
    basari, hata = 0, 0
    for test in testler:
        try:
            test()
            print(f"  [GEÇTİ]  {test.__name__}")
            basari += 1
        except AssertionError as exc:
            print(f"  [HATA]   {test.__name__}\n           → {str(exc)[:120]}")
            hata += 1
        except Exception as exc:
            print(f"  [ÇÖKTÜ]  {test.__name__}: {type(exc).__name__}: {str(exc)[:100]}")
            hata += 1
    print(f"{'=' * 58}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'=' * 58}\n")
    sys.exit(0 if hata == 0 else 1)
