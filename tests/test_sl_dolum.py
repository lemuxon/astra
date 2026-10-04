# =========================================================
# ASTRA v57 — SL/TP DOLUM MODELİ TESTLERİ
# Çalıştırma: python tests/test_sl_dolum.py
#
# NE KORUYOR (DEVAM_NOTLARI §5.3 — paper ↔ canlı eşitliği):
#   Canlıda SL, borsada DURAN bir STOP_MARKET emridir: fiyat seviyeye
#   değdiği anda tetiklenir ve stop seviyesine yakın dolar — bot kapalı
#   olsa bile. TP ise limit emri; TP seviyesinden dolar, daha iyisinden
#   değil.
#
#   v56'ya kadar paper ve backtest pozisyonu `guncel_fiyat`tan (bar
#   kapanışından) kapatıyordu. Bu, seviyeyi aşan hareketin TAMAMINI
#   zarar/kâr olarak yazıyordu — iki tarafı da abartan bir model.
#
#   ÖLÇÜLEN VAKA (2026-08-23): BNBUSDT SHORT giriş 678.4264, SL 685.2127.
#   Bot 2 gün 8 saat kapalı kaldı (v57 K-3), fiyat 700.06'ya çıktı ve
#   zarar %3.27 yazıldı — olması gereken ≈%1.09'un 3 KATI.
#   100 işlemlik veri seti bu şekilde sistematik kötümser oluyordu ve
#   canlıya geçiş kararı buna dayanıyor.
#
# §4.1: Muhafız testlerinin yanına KONTROL testleri yazıldı — "hiçbir
#   pozisyonu kapatmayan" bir kod da muhafızları geçerdi.
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


def _temiz_trade(sembol, yon, giris, sl, tp, miktar=1.0):
    """DB'ye doğrudan açık bir paper trade yaz ve dict'ini döndür."""
    from data.database import tablolari_olustur, trade_ac, acik_tradeler
    tablolari_olustur()
    trade_ac(sembol=sembol, yon=yon, giris_fiyat=giris, miktar=miktar,
             stop_loss=sl, take_profit=tp, mod="PAPER")
    kayit = [t for t in acik_tradeler("PAPER") if t["sembol"] == sembol]
    assert kayit, f"{sembol} açık trade oluşturulamadı — test önkoşulu"
    return kayit[-1]


def _kapali(sembol):
    """Sembolün en son KAPANMIŞ kaydını döndür."""
    import sqlite3
    c = sqlite3.connect(os.environ["DB_PATH"])
    c.row_factory = sqlite3.Row
    r = c.execute(
        "SELECT * FROM trades WHERE sembol=? AND durum!='ACIK' "
        "ORDER BY id DESC LIMIT 1", (sembol,)).fetchone()
    return dict(r) if r else None


def _slip_oran():
    from config import PAPER_SLIPPAGE_BPS
    return PAPER_SLIPPAGE_BPS / 10000.0


# ─────────────────────────────────────────────
# 1. MUHAFIZ — SL seviyeden dolmalı, uç fiyattan DEĞİL
# ─────────────────────────────────────────────
def test_short_sl_seviyeden_dolar_uc_fiyattan_degil():
    """Gerçek vakanın birebir kopyası: BNBUSDT SHORT, bot uzun süre kapalı.

    Giriş 678.4264, SL 685.2127, bot geri geldiğinde fiyat 700.06.
    Kapanış SL seviyesine yakın olmalı — 700'e değil.
    """
    from engines.paper_trading import PaperTrader
    giris, sl, uc = 678.4264, 685.2127, 700.0600
    _temiz_trade("BNBUSDT", "SHORT", giris, sl, 668.2470)

    PaperTrader().stop_tp_kontrol("BNBUSDT", uc)

    k = _kapali("BNBUSDT")
    assert k, "Pozisyon kapanmadı"
    beklenen = sl * (1 + _slip_oran())          # SHORT çıkışı aleyhte = yukarı
    assert abs(k["cikis_fiyat"] - beklenen) < 0.01, (
        f"Çıkış {k['cikis_fiyat']:.4f}, beklenen ≈{beklenen:.4f} (SL+slippage). "
        f"Uç fiyat {uc} kullanılmış olabilir — bot kesintisi zararı şişirir.")
    assert k["cikis_fiyat"] < uc, (
        f"Çıkış ({k['cikis_fiyat']:.4f}) uç fiyattan ({uc}) iyi değil — "
        f"eski model geri gelmiş")


def test_long_sl_seviyeden_dolar():
    """LONG tarafı da aynı: SL'in ALTINA sarkan fiyat zarar yazmamalı."""
    from engines.paper_trading import PaperTrader
    giris, sl, uc = 100.0, 98.0, 90.0
    _temiz_trade("TESTLONGUSDT", "LONG", giris, sl, 104.0)

    PaperTrader().stop_tp_kontrol("TESTLONGUSDT", uc)

    k = _kapali("TESTLONGUSDT")
    assert k, "Pozisyon kapanmadı"
    beklenen = sl * (1 - _slip_oran())          # LONG çıkışı aleyhte = aşağı
    assert abs(k["cikis_fiyat"] - beklenen) < 0.01, (
        f"Çıkış {k['cikis_fiyat']:.4f}, beklenen ≈{beklenen:.4f} (SL-slippage)")
    assert k["cikis_fiyat"] > uc, (
        f"Çıkış ({k['cikis_fiyat']:.4f}) uç fiyattan ({uc}) iyi değil")


def test_tp_seviyeden_dolar_daha_iyisinden_degil():
    """TP limit emridir: seviyeden dolar, seviyeyi aşan kâr YAZILMAZ.

    Eski model burada da abartıyordu — kârı şişirmek, zararı şişirmek
    kadar tehlikeli (canlıya geçince 'strateji bozuldu' yanılgısı).
    """
    from engines.paper_trading import PaperTrader
    giris, tp, uc = 100.0, 104.0, 112.0
    _temiz_trade("TESTTPUSDT", "LONG", giris, 98.0, tp)

    PaperTrader().stop_tp_kontrol("TESTTPUSDT", uc)

    k = _kapali("TESTTPUSDT")
    assert k, "Pozisyon kapanmadı"
    beklenen = tp * (1 - _slip_oran())
    assert abs(k["cikis_fiyat"] - beklenen) < 0.01, (
        f"Çıkış {k['cikis_fiyat']:.4f}, beklenen ≈{beklenen:.4f} (TP-slippage)")
    assert k["cikis_fiyat"] < uc, (
        f"TP çıkışı {k['cikis_fiyat']:.4f}, uç fiyat {uc}'e kadar kâr "
        f"yazılmış — kâr şişiyor")


def test_gercek_vakanin_zarari_makul_seviyeye_dondu():
    """BNBUSDT vakası: %3.27 zarar yerine ≈%1.1 olmalı.

    Sayısal bekçi — model tekrar bozulursa oran fırlar.
    """
    from engines.paper_trading import PaperTrader
    giris, sl, uc = 678.4264, 685.2127, 700.0600
    _temiz_trade("BNBZARARUSDT", "SHORT", giris, sl, 668.2470, miktar=0.033283)

    PaperTrader().stop_tp_kontrol("BNBZARARUSDT", uc)

    k = _kapali("BNBZARARUSDT")
    assert k, "Pozisyon kapanmadı"
    assert -2.0 < k["pnl_yuzde"] < 0, (
        f"Zarar %{k['pnl_yuzde']:.2f} — beklenen ≈%-1.1 aralığında değil. "
        f"Eski model %-3.27 yazıyordu (3 katı).")


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
#    "Hiç kapatmayan" kod da yukarıdaki muhafızları geçer.
# ─────────────────────────────────────────────
def test_kontrol_tetiklenmeyen_pozisyon_acik_kalir():
    """SL/TP'ye değmeyen fiyat pozisyonu KAPATMAMALI.

    Bu olmadan "her şeyi anında kapat" gibi bozuk bir kod da muhafızları
    geçebilirdi.
    """
    from engines.paper_trading import PaperTrader
    from data.database import acik_tradeler
    _temiz_trade("TESTACIKUSDT", "LONG", 100.0, 98.0, 104.0)

    PaperTrader().stop_tp_kontrol("TESTACIKUSDT", 101.0)   # SL/TP arasında

    acik = [t for t in acik_tradeler("PAPER") if t["sembol"] == "TESTACIKUSDT"]
    assert acik, ("SL/TP tetiklenmediği hâlde pozisyon kapatıldı — "
                  "erken kapanış tüm sonuçları bozar")


def test_kontrol_pozisyon_gercekten_kapaniyor():
    """Tetiklendiğinde pozisyon GERÇEKTEN kapanmalı.

    "Hiçbir zaman kapatma" davranışı yukarıdaki muhafızları geçemez ama
    bu testi de geçemediğini açıkça göstermek gerekiyor.
    """
    from engines.paper_trading import PaperTrader
    from data.database import acik_tradeler
    _temiz_trade("TESTKAPUSDT", "LONG", 100.0, 98.0, 104.0)

    PaperTrader().stop_tp_kontrol("TESTKAPUSDT", 97.0)     # SL altı

    acik = [t for t in acik_tradeler("PAPER") if t["sembol"] == "TESTKAPUSDT"]
    assert not acik, "SL tetiklendiği hâlde pozisyon açık kaldı"
    assert _kapali("TESTKAPUSDT"), "Kapanış kaydı DB'ye yazılmadı"


def test_kontrol_slippage_hala_aleyhte_uygulaniyor():
    """Dolum SL seviyesinin TAM ÜSTÜ değil, biraz ALEYHTE olmalı.

    Aksi halde maliyet modellemesi kaybolur ve paper iyimser olur —
    v56'da düzeltilen hatanın tersi.
    """
    from engines.paper_trading import PaperTrader
    giris, sl = 100.0, 98.0
    _temiz_trade("TESTSLIPUSDT", "LONG", giris, sl, 104.0)

    PaperTrader().stop_tp_kontrol("TESTSLIPUSDT", 95.0)

    k = _kapali("TESTSLIPUSDT")
    assert k, "Pozisyon kapanmadı"
    if _slip_oran() > 0:
        assert k["cikis_fiyat"] < sl, (
            f"LONG çıkışı {k['cikis_fiyat']:.4f}, SL {sl} — slippage "
            f"aleyhte uygulanmamış (maliyet modeli kayboldu)")


# ─────────────────────────────────────────────
# 3. BACKTEST aynı modeli kullanmalı (kaynak düzeyi)
# ─────────────────────────────────────────────
def test_backtest_seviyeden_dolduruyor():
    """backtest_engine bar kapanışından değil, tetik seviyesinden doldurmalı.

    Paper ile backtest ayrışırsa §5.3 eşitliği yine bozulur.
    """
    yol = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "engines", "backtest_engine.py")
    with open(yol, encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))

    assert "_slippage_uygula(tetik_fiyat" in kod, (
        "backtest_engine dolumu `tetik_fiyat` üzerinden yapmıyor — "
        "bar kapanışı kullanılıyor olabilir (eski model)")
    assert "_slippage_uygula(fiyat, -giris_yon)" not in kod, (
        "backtest_engine hâlâ bar kapanışından (`fiyat`) dolduruyor")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA SL/TP DOLUM MODELİ — {len(testler)} test")
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
