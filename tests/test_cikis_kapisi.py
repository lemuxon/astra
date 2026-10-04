# =========================================================
# ASTRA v58 — ÇIKIŞ KAPISI TESTLERİ
# Çalıştırma: python tests/test_cikis_kapisi.py
#
# NE KORUYOR (DEVAM_NOTLARI §5.3 — paper ↔ canlı eşitliği):
#
#   PaperTrader.sinyal_isle() zıt sinyalde pozisyonu kapatırken HİÇBİR
#   eşik uygulamıyordu. Kapatma bloğu `_filtre_gec()` çağrısından ÖNCE
#   çalışıyor; `_filtre_gec` yalnızca AÇILIŞ yolunda devrede.
#
#   Sonuç — asimetrik kapı:
#       AÇILIŞ  : |ai| >= MIN_AI_SCORE_BUY/SELL  VE  conf >= MIN_CONFIDENCE
#       KAPANIŞ : karar metninde "BUY"/"SELL" geçmesi YETERLİ
#
#   Yani ai=3 / conf=55 gibi bir sinyal pozisyon AÇAMAZ ama AÇIK bir
#   pozisyonu KAPATABİLİR. Pozisyonlar, giriş kararını verdiren sinyalin
#   çok altındaki gürültüyle erkenden kesiliyor.
#
# ÖLÇÜLEN ETKİ (2026-09-02, 21 kapanmış paper işlemi):
#   11 işlem (%52) zıt sinyalle kapandı. 11'inin 11'i de AÇILIŞ eşiğinin
#   ALTINDAKİ bir sinyalle kapatılmıştı (ai=±3 veya ±4; üçünde
#   conf=55 < MIN_CONFIDENCE=62). Toplam katkı: %-1.62.
#   Gerçek 1m barlarla karşı-olgusal: aynı 11 işlem SL/TP'ye kadar
#   tutulsaydı %-0.83 olurdu → erken kesme %0.79 puan kaybettiriyor.
#
# CANLI YOL BÖYLE DEĞİL (eşitlik ihlali):
#   main.py::_execution_isle zıt pozisyonu ancak chop/MTF/EdgeEngine/
#   strateji/sinyal_gecerli_mi zincirinin TAMAMI geçildikten SONRA
#   kapatıyor (main.py:1441-1449). Paper ise ham coin_analiz çıktısıyla
#   veto zincirinin DIŞINDA çağrılıyor (main.py:1829).
#
# §4.1: Muhafız testlerinin yanına KONTROL testleri yazıldı — hiçbir
#   pozisyonu kapatmayan bir kod da muhafızları geçerdi.
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


def _trader():
    from engines.paper_trading import PaperTrader
    from data.database import tablolari_olustur
    tablolari_olustur()
    return PaperTrader(10000.0)


def _acik_trade(sembol, yon, giris, sl, tp, miktar=1.0):
    """DB'ye doğrudan açık bir paper trade yaz, id'sini döndür."""
    from data.database import tablolari_olustur, trade_ac, acik_tradeler
    tablolari_olustur()
    trade_ac(sembol=sembol, yon=yon, giris_fiyat=giris, miktar=miktar,
             stop_loss=sl, take_profit=tp, mod="PAPER")
    k = [t for t in acik_tradeler("PAPER") if t["sembol"] == sembol]
    assert k, f"{sembol} açık trade oluşturulamadı — test önkoşulu"
    return k[-1]["id"]


def _hala_acik(trade_id):
    """BU trade hâlâ açık mı?

    Sembole bakmak YETMEZ: sinyal_isle zıt pozisyonu kapattıktan sonra
    AYNI çağrıda aynı sembolde ters yönde yeni pozisyon açabiliyor
    (gerçek veride #15 LONG → #16 SHORT, aynı saniye). Sembol sorgusu
    bunu "kapanmadı" sanardı.
    """
    from data.database import acik_tradeler
    return any(t["id"] == trade_id for t in acik_tradeler("PAPER"))


def _sonuc(sembol, karar, ai, conf, fiyat):
    """coin_analiz çıktısının sinyal_isle'nin okuduğu asgari alanları."""
    return {"sembol": sembol, "karar": karar, "ai_score": ai,
            "confidence": conf, "son_close": fiyat, "son_atr": fiyat * 0.005,
            "rejim": "VOLATILE", "sig_id": None}


def _temizle(sembol):
    import sqlite3
    from data.database import tablolari_olustur
    tablolari_olustur()           # tablo yoksa DELETE çöker (test sırası bağımlılığı)
    c = sqlite3.connect(os.environ["DB_PATH"])
    c.execute("DELETE FROM trades WHERE sembol=?", (sembol,))
    c.commit(); c.close()


# ─────────────────────────────────────────────
# 1. MUHAFIZ — eşik altı sinyal pozisyonu KAPATMAMALI
# ─────────────────────────────────────────────
def test_esik_alti_zit_sinyal_short_pozisyonu_kapatmaz():
    """Gerçek vakanın kopyası: 2026-08-29 SOLUSDT #1.

    SHORT açıkken 'WEAK BUY' (ai=+3, conf=80) geldi ve pozisyon kapandı.
    Oysa ai=3 < MIN_AI_SCORE_BUY=4 → bu sinyal LONG AÇAMAZ.
    Açamayan bir sinyal kapatmamalı da.
    """
    from config import MIN_AI_SCORE_BUY
    _temizle("TESTGUARDA")
    tid = _acik_trade("TESTGUARDA", "SHORT", 100.0, 101.0, 99.0)
    zayif = MIN_AI_SCORE_BUY - 1          # açılış eşiğinin ALTINDA
    _trader().sinyal_isle(_sonuc("TESTGUARDA", "WEAK BUY", zayif, 80, 100.1))
    assert _hala_acik(tid), (
        f"ai={zayif} < MIN_AI_SCORE_BUY={MIN_AI_SCORE_BUY} olan bir sinyal "
        f"SHORT pozisyonu kapattı. Bu sinyal LONG açamaz — kapatma da "
        f"yapmamalı (asimetrik çıkış kapısı)")
    _temizle("TESTGUARDA")


def test_esik_alti_zit_sinyal_long_pozisyonu_kapatmaz():
    """Aynı hatanın LONG tarafı: 2026-08-29 SOLUSDT #2 (WEAK SELL ai=-3)."""
    from config import MIN_AI_SCORE_SELL
    _temizle("TESTGUARDB")
    tid = _acik_trade("TESTGUARDB", "LONG", 100.0, 99.0, 101.0)
    zayif = MIN_AI_SCORE_SELL + 1         # örn. -3, eşik -4
    _trader().sinyal_isle(_sonuc("TESTGUARDB", "WEAK SELL", zayif, 80, 99.9))
    assert _hala_acik(tid), (
        f"ai={zayif} > MIN_AI_SCORE_SELL={MIN_AI_SCORE_SELL} olan bir sinyal "
        f"LONG pozisyonu kapattı — bu sinyal SHORT açamaz")
    _temizle("TESTGUARDB")


def test_dusuk_guvenli_zit_sinyal_pozisyonu_kapatmaz():
    """Gerçek vaka: #5 XRPUSDT, ai=-4 ama conf=55 < MIN_CONFIDENCE=62.

    AI eşiğini geçse bile güven eşiğini geçemeyen sinyal açamaz.
    """
    from config import MIN_AI_SCORE_BUY, MIN_CONFIDENCE
    _temizle("TESTGUARDC")
    tid = _acik_trade("TESTGUARDC", "SHORT", 100.0, 101.0, 99.0)
    _trader().sinyal_isle(_sonuc("TESTGUARDC", "BUY",
                                 MIN_AI_SCORE_BUY, MIN_CONFIDENCE - 7, 100.1))
    assert _hala_acik(tid), (
        f"conf={MIN_CONFIDENCE-7} < MIN_CONFIDENCE={MIN_CONFIDENCE} olan "
        f"sinyal pozisyonu kapattı — güven eşiği çıkışta uygulanmıyor")
    _temizle("TESTGUARDC")


# ─────────────────────────────────────────────
# 2. KONTROL — "hiç kapatma" da muhafızları geçerdi
# ─────────────────────────────────────────────
def test_gecerli_zit_sinyal_pozisyonu_KAPATIR():
    """Kontrol testi (§4.1). Eşiği AŞAN zıt sinyal kapatmalı.

    Bu test olmadan, kapatmayı tamamen silen bir 'düzeltme' de yeşil olurdu.
    """
    from config import MIN_AI_SCORE_BUY, MIN_CONFIDENCE
    _temizle("TESTCTRLA")
    tid = _acik_trade("TESTCTRLA", "SHORT", 100.0, 101.0, 99.0)
    _trader().sinyal_isle(_sonuc("TESTCTRLA", "STRONG BUY",
                                 MIN_AI_SCORE_BUY + 3, MIN_CONFIDENCE + 13, 100.1))
    assert not _hala_acik(tid), (
        "Eşiği aşan GEÇERLİ zıt sinyal SHORT pozisyonu kapatmadı — "
        "çıkış mekanizması tamamen ölmüş olabilir")
    _temizle("TESTCTRLA")


def test_gecerli_zit_sinyal_long_pozisyonu_KAPATIR():
    """Kontrol testinin LONG tarafı."""
    from config import MIN_AI_SCORE_SELL, MIN_CONFIDENCE
    _temizle("TESTCTRLB")
    tid = _acik_trade("TESTCTRLB", "LONG", 100.0, 99.0, 101.0)
    _trader().sinyal_isle(_sonuc("TESTCTRLB", "STRONG SELL",
                                 MIN_AI_SCORE_SELL - 3, MIN_CONFIDENCE + 13, 99.9))
    assert not _hala_acik(tid), (
        "Eşiği aşan GEÇERLİ zıt sinyal LONG pozisyonu kapatmadı")
    _temizle("TESTCTRLB")


def test_esik_alti_sinyal_pozisyon_ACAMAZ_hala():
    """Kontrol: açılış kapısı bozulmamış olmalı (regresyon koruması)."""
    from config import MIN_AI_SCORE_BUY
    from data.database import acik_tradeler
    _temizle("TESTCTRLC")
    once = len([t for t in acik_tradeler("PAPER") if t["sembol"] == "TESTCTRLC"])
    _trader().sinyal_isle(_sonuc("TESTCTRLC", "WEAK BUY",
                                 MIN_AI_SCORE_BUY - 1, 80, 100.0))
    sonra = len([t for t in acik_tradeler("PAPER") if t["sembol"] == "TESTCTRLC"])
    assert sonra == once, (
        "Eşik altı sinyal pozisyon AÇTI — açılış kapısı da bozuk")
    _temizle("TESTCTRLC")


# ─────────────────────────────────────────────
# 3. YAPISAL — paper ↔ canlı çıkış kapısı eşitliği
# ─────────────────────────────────────────────
def test_paper_cikis_kapisi_kod_duzeyinde_esik_uyguluyor():
    """Kaynak düzeyinde: kapatma bloğu bir eşik kontrolüne bağlı olmalı.

    Davranış testleri mock'lanan bir katmanı ölçebilir; bu test kodun
    kendisine bakar (§4.1 — yanlış katmanı doğrulayan test tuzağı).
    """
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "engines", "paper_trading.py")
    with open(yol, encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))
    i_kapat = kod.find('_kapat_ve_bakiye_guncelle(trade, fiyat, "SELL_S')
    assert i_kapat > 0, "zıt-sinyal kapatma çağrısı bulunamadı — test hedefi kaymış"
    # SADECE çağrının ÖNCESİ. İleri pencere alınırsa AÇILIŞ yolundaki
    # `_filtre_gec` çağrısı görülür ve test yanlış sebeple geçer —
    # §4.1'deki "yanlış katmanı doğrulayan test" tuzağının aynısı.
    blok = kod[max(0, i_kapat - 700):i_kapat]
    assert ("_cikis_gecerli" in blok or "_filtre_gec" in blok
            or "MIN_AI_SCORE" in blok or "MIN_CONFIDENCE" in blok), (
        "Zıt sinyalde kapatma bloğu HİÇBİR eşiğe bakmıyor — herhangi bir "
        "BUY/SELL metni pozisyonu kapatabiliyor (açılış eşiğinden bağımsız)")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA ÇIKIŞ KAPISI — {len(testler)} test")
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
