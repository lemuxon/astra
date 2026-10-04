# =========================================================
# ASTRA v58 — GİRİŞ FİYATI TESTLERİ (K-31)
# Çalıştırma: python tests/test_giris_fiyati.py
#
# NE KORUYOR — ÖLÇÜLEN PARA KAYBI:
#   K-16'da `son_close` KAPANMIŞ barın kapanışına çevrildi (göstergeler
#   için doğru). Ama GİRİŞ FİYATI da ondan okunuyordu ve güncellenmedi.
#   Öncesinde `son_close` zaten oluşan barın anlık fiyatıydı, bu yüzden
#   sorun görünmüyordu — 4h'e geçince giriş 4 SAATE KADAR bayatladı.
#
#   VAKA (paper #7, 2026-09-04 14:56 XRPUSDT LONG):
#       son kapanmış 4h bar kapanışı : 1.45070
#       bot giriş fiyatı             : 1.45114   ← bayat
#       o anki gerçek fiyat          : 1.39120   (%-4.13)
#       SL 1.40440 → pozisyon 59 MİLİSANİYEDE stop, -%3.33
#   Piyasada var olmayan bir fiyattan girilip anında stop olundu.
#
# ── PAPER ↔ CANLI EŞİTLİĞİ (§5.3) ────────────────────────────
#   Canlı yol (v28, main.py::_execution_isle) bunu ZATEN doğru yapıyordu:
#     1. `futures_anlık_fiyat()` ile CANLI fiyattan girer
#     2. Fiyat sinyalin ALEYHİNE çok kaçtıysa işlemi İPTAL eder
#        ("geç giriş — kovalama yapma", MAX_GIRIS_KAYMA_PCT)
#   Paper'da İKİSİ DE yoktu → paper, canlının REDDEDECEĞİ işlemleri
#   açıyordu ve ölçüm canlıyı temsil etmiyordu.
#
# §4.1: Muhafızların yanına kontrol testleri — "hiç işlem açma" da
#   iptal muhafızını geçerdi.
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


def _sonuc(sembol, karar, ai, conf, son_close, anlik=None, atr_pct=1.0):
    """`son_close` = kapanmış bar, `anlik_fiyat` = oluşan barın anlık fiyatı."""
    d = {"sembol": sembol, "karar": karar, "ai_score": ai, "confidence": conf,
         "son_close": son_close, "son_atr": son_close * atr_pct / 100,
         # v58 (K-97): veto zinciri paper yoluna da bağlandı (§6.0).
         # `edge_sonuc` ve `mtf_confluence` artık ZORUNLU: üretimde
         # `coin_analiz` ikisini de HER ZAMAN üretiyor (ölçüldü 50/50),
         # onlarsız bir `sonuc` üretimde İMKÂNSIZDIR. Fikstür üretim
         # kuralına uymalı (§0.1) — kapı zayıflatılmadı.
         "edge_sonuc": {"gecti": True, "edge_score": 70, "sebep": ""},
         "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3,
                            "ana_trend_yon": "LONG", "yon": "LONG"},
         "rejim": "TREND_UP", "sig_id": None}
    if anlik is not None:
        d["anlik_fiyat"] = anlik
    return d


def _temizle(sembol):
    import sqlite3
    from data.database import tablolari_olustur
    tablolari_olustur()
    c = sqlite3.connect(os.environ["DB_PATH"])
    c.execute("DELETE FROM trades WHERE sembol=?", (sembol,))
    c.commit(); c.close()


def _acik(sembol):
    from data.database import acik_tradeler
    return [t for t in acik_tradeler("PAPER") if t["sembol"] == sembol]


# ─────────────────────────────────────────────
# 1. MUHAFIZ — giriş ANLIK fiyattan olmalı
# ─────────────────────────────────────────────
def test_giris_anlik_fiyattan_yapilir():
    """Kapanmış barın kapanışı değil, o anki fiyat kullanılmalı."""
    from config import MIN_AI_SCORE_BUY, MIN_CONFIDENCE
    _temizle("TESTGIRA")
    try:
        # anlık fiyat LEHTE kaçmış (LONG için aşağı) → giriş orada olmalı
        _trader().sinyal_isle(_sonuc("TESTGIRA", "STRONG BUY",
                                     MIN_AI_SCORE_BUY + 3, MIN_CONFIDENCE + 13,
                                     son_close=100.0, anlik=99.5))
        a = _acik("TESTGIRA")
        assert a, "pozisyon açılmadı — test önkoşulu"
        giris = float(a[0]["giris_fiyat"])
        # slippage payıyla anlık fiyata yakın olmalı, 100'e DEĞİL
        assert abs(giris - 99.5) < 0.5, (
            f"Giriş {giris:.4f} — anlık fiyat 99.5 yerine kapanmış bar "
            f"kapanışı (100.0) kullanılmış olabilir")
    finally:
        _temizle("TESTGIRA")


def test_fiyat_aleyhe_kacmissa_islem_ACILMAZ():
    """#7 vakasının birebir kopyası: fiyat %4 aleyhe kaçmış.

    Canlı yol bunu iptal ediyor ("geç giriş — kovalama yapma");
    paper da etmeli, yoksa canlının reddedeceği işlemi açar.
    """
    from config import MIN_AI_SCORE_BUY, MIN_CONFIDENCE
    _temizle("TESTGIRB")
    try:
        # LONG sinyali ama fiyat %4 YUKARI kaçmış → kovalama
        _trader().sinyal_isle(_sonuc("TESTGIRB", "STRONG BUY",
                                     MIN_AI_SCORE_BUY + 3, MIN_CONFIDENCE + 13,
                                     son_close=100.0, anlik=104.0))
        assert not _acik("TESTGIRB"), (
            "Fiyat %4 aleyhe kaçmışken pozisyon açıldı — canlı yol bunu "
            "iptal ederdi (MAX_GIRIS_KAYMA_PCT)")
    finally:
        _temizle("TESTGIRB")


def test_short_tarafinda_da_iptal():
    """Aynı koruma SHORT için de geçerli (fiyat aşağı kaçmışsa)."""
    from config import MIN_AI_SCORE_SELL, MIN_CONFIDENCE
    _temizle("TESTGIRC")
    try:
        _trader().sinyal_isle(_sonuc("TESTGIRC", "STRONG SELL",
                                     MIN_AI_SCORE_SELL - 3, MIN_CONFIDENCE + 13,
                                     son_close=100.0, anlik=96.0))
        assert not _acik("TESTGIRC"), (
            "SHORT sinyalinde fiyat %4 aşağı kaçmışken pozisyon açıldı")
    finally:
        _temizle("TESTGIRC")


def test_anlik_fiyattan_acilan_pozisyon_ANINDA_stop_olmaz():
    """Uçtan uca: #7'nin tekrarı olmamalı.

    Giriş anlık fiyattan yapılırsa SL de ondan hesaplanır ve pozisyon
    açılır açılmaz stop olmaz.
    """
    from config import MIN_AI_SCORE_BUY, MIN_CONFIDENCE
    _temizle("TESTGIRD")
    try:
        t = _trader()
        s = _sonuc("TESTGIRD", "STRONG BUY", MIN_AI_SCORE_BUY + 3,
                   MIN_CONFIDENCE + 13, son_close=100.0, anlik=99.8)
        t.sinyal_isle(s)
        a = _acik("TESTGIRD")
        assert a, "pozisyon açılmadı — test önkoşulu"
        # ana döngüdeki sıra: sinyal_isle → stop_tp_kontrol(anlik)
        t.stop_tp_kontrol("TESTGIRD", s["anlik_fiyat"])
        assert _acik("TESTGIRD"), (
            "Pozisyon açıldığı anda stop oldu — giriş fiyatı ile SL/TP "
            "kontrolü farklı fiyat ölçeklerinden geliyor (#7 vakası)")
    finally:
        _temizle("TESTGIRD")


# ─────────────────────────────────────────────
# 2. KONTROL — "hiç açma" da muhafızı geçerdi
# ─────────────────────────────────────────────
def test_kayma_kucukse_islem_ACILIR():
    """Kontrol testi (§4.1). Küçük kayma işlemi engellememeli.

    Bu test olmadan, tüm girişleri reddeden bir 'düzeltme' de iptal
    muhafızlarını geçerdi ama bot hiç işlem yapmazdı.
    """
    from config import MIN_AI_SCORE_BUY, MIN_CONFIDENCE
    _temizle("TESTGIRE")
    try:
        _trader().sinyal_isle(_sonuc("TESTGIRE", "STRONG BUY",
                                     MIN_AI_SCORE_BUY + 3, MIN_CONFIDENCE + 13,
                                     son_close=100.0, anlik=100.05))
        assert _acik("TESTGIRE"), (
            "%0.05 kayma ile işlem açılmadı — eşik çok dar, bot hiç "
            "işlem yapamaz")
    finally:
        _temizle("TESTGIRE")


def test_anlik_fiyat_yoksa_son_closea_duser():
    """Kontrol: `anlik_fiyat` alanı yoksa sistem çökmemeli.

    Eski `sonuc` sözlükleri (ör. testler, tek_seferlik_analiz) bu alanı
    taşımayabilir; geriye dönük uyumluluk şart.
    """
    from config import MIN_AI_SCORE_BUY, MIN_CONFIDENCE
    _temizle("TESTGIRF")
    try:
        _trader().sinyal_isle(_sonuc("TESTGIRF", "STRONG BUY",
                                     MIN_AI_SCORE_BUY + 3, MIN_CONFIDENCE + 13,
                                     son_close=100.0, anlik=None))
        a = _acik("TESTGIRF")
        assert a, "anlik_fiyat yokken pozisyon açılmadı — uyumluluk bozuk"
        assert abs(float(a[0]["giris_fiyat"]) - 100.0) < 0.5, \
            "anlik_fiyat yokken son_close'a düşmedi"
    finally:
        _temizle("TESTGIRF")


# ─────────────────────────────────────────────
# 3. YAPISAL — paper ↔ canlı aynı korumaya sahip
# ─────────────────────────────────────────────
def test_paper_da_gec_giris_korumasi_var():
    """Kod düzeyinde: paper geç giriş eşiğini YAPILANDIRMADAN almalı.

    Davranış testi mock'lanan bir katmanı ölçebilir; bu test kodun
    kendisine bakar (§4.1).

    ⚠️ v58 (K-95): BU TEST BİR KEZ UYGULAMA DETAYINA BAĞLIYDI.
    Eskiden yalnızca `"MAX_GIRIS_KAYMA_PCT" in kod` diyordu. Eşik
    ortak `giris_kayma_esigi()` fonksiyonuna çıkarılınca — yani koruma
    ZAYIFLAMADI, GÜÇLENDİ (paper ve canlı tek kaynağa bağlandı) — test
    kırmızıya döndü. Sabit adı değil SÖZLEŞMEYİ aramalı: eşik ya ortak
    fonksiyondan ya config'ten gelmeli, ELDE SABİT YAZILMAMALI.
    """
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "engines", "paper_trading.py")
    with open(yol, encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))
    assert ("giris_kayma_esigi" in kod or "MAX_GIRIS_KAYMA_PCT" in kod), (
        "paper_trading geç giriş eşiğini ne ortak fonksiyondan ne config'ten "
        "alıyor — canlı yol geç girişi iptal ederken paper açar (§5.3 ihlali)")
    assert "anlik_fiyat" in kod, \
        "paper_trading anlık fiyatı hiç okumuyor"


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA GİRİŞ FİYATI — {len(testler)} test")
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
