# =========================================================
# ASTRA v58 — POZİSYON KAYNAĞI ve PnL TUTARLILIĞI (K-56/K-57)
# Çalıştırma: python tests/test_pozisyon_kaynagi.py
#
# NE KORUYOR — kullanıcı bildirimi (2026-09-06):
#   "/fpoz açık pozisyon yok diyor ama panelde 2 tane açık?"
#
#   K-56: `futures_pozisyon_raporu` pozisyonları KOŞULSUZ
#   `acik_futures_pozisyonlar()`'dan okuyordu. Paper modda bot
#   futures'ta hiç işlem yapmadığı için liste HEP BOŞ → rapor
#   "📭 AÇIK POZİSYON YOK" diyordu, panelde 2 pozisyon dururken.
#
#   ⚠️ K-33'ün YARIM KALMIŞ hâli: o düzeltme aynı raporun BAKİYESİNİ
#   paper'a çevirmişti ama VERİ KAYNAĞINI çevirmemişti. Sonuç, PAPER
#   bakiyesini FUTURES pozisyonlarıyla gösteren — ve tutarlı GÖRÜNEN —
#   bir rapordu. Tek raporda iki kaynak.
#
#   K-57: PnL yanlış gösteriliyordu. Rapor `guncel` fiyatı taze
#   çekiyor ama PnL'i BAŞKA kaynaktan (analiz cache'i) alıyordu:
#       "Giriş:765.0995  Güncel:758.2000  ✅ PnL:+0.0000USDT"
#   Pozisyon zararda, rapor kârda gösteriyor. Cache boşsa PnL sessizce
#   0 kalıyordu. Artık aynı satırdaki `guncel` ile hesaplanıyor.
#
# §4.1: Muhafızların yanına KONTROL testleri var.
# =========================================================
import sys, os, ast, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _borsayi_izole_et():
    """Testler GERÇEK borsayı sorgulamamalı — v58 (K-101).

    ── NEDEN GEREKLİ ────────────────────────────────────────────
    `main.acik_pozisyonlar_birlesik()` önce `acik_futures_pozisyonlar()`
    çağırıyor; o da CANLI borsaya gidiyor. Bu dosyadaki testlerde HİÇ
    taklit yoktu — yani sessizce "testnet hesabı BOŞ" varsayımına
    dayanıyorlardı.

    2026-09-15 00:17'de bot ilk canlı emri açtı; hesapta gerçek bir
    ETHUSDT pozisyonu belirdi ve 6 test birden kırmızıya döndü
    ("pozisyon yokken 1 döndü"). Testler kusurluydu, kod değil.

    Borsa hesabı da ÜRETİM durumudur (§4.6'nın kapsaması gereken şey):
    test sonucu dış dünyanın anlık hâline bağlı olmamalı. Hem
    tekrarlanabilirlik için, hem de testin canlı hesaba yazma
    ihtimalini kapatmak için.
    """
    import main
    asil = main.acik_futures_pozisyonlar
    main.acik_futures_pozisyonlar = lambda *a, **kw: []
    return lambda: setattr(main, "acik_futures_pozisyonlar", asil)


def _temiz():
    from config import DB_PATH
    from data.database import tablolari_olustur
    tablolari_olustur()
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM trades"); c.commit()
    return DB_PATH


def _poz_ac(sembol, giris, miktar, yon="LONG"):
    from config import DB_PATH
    with sqlite3.connect(DB_PATH) as c:
        c.execute("INSERT INTO trades (ts_ac,sembol,yon,giris_fiyat,miktar,"
                  "durum,mod) VALUES ('2026-09-06T00:00:00',?,?,?,?,'ACIK','PAPER')",
                  (sembol, yon, giris, miktar))
        c.commit()


# ─────────────────────────────────────────────
# 1. K-56 — KAYNAK MODA GÖRE SEÇİLİYOR
# ─────────────────────────────────────────────
def test_paper_modda_paper_pozisyonlari_donuyor():
    """DAVRANIŞSAL: paper pozisyon varsa liste BOŞ dönmemeli."""
    _temiz()
    _poz_ac("BTCUSDT", 100.0, 2.0)
    _poz_ac("ETHUSDT", 50.0, 1.0)
    import main
    _geri = _borsayi_izole_et()
    try:
        pozlar, kaynak = main.acik_pozisyonlar_birlesik()
    finally:
        _geri()
    assert kaynak == "PAPER", f"kaynak '{kaynak}' — paper modda PAPER olmalı"
    assert len(pozlar) == 2, (
        f"{len(pozlar)} pozisyon döndü, 2 bekleniyordu — /fpoz 'açık "
        f"pozisyon yok' derken panel 2 gösteriyordu (K-56)")
    semboller = {p["sembol"] for p in pozlar}
    assert semboller == {"BTCUSDT", "ETHUSDT"}


def test_esleme_futures_semasina_uyuyor():
    """Paper kaydı, raporun beklediği alanlara sahip olmalı."""
    _temiz(); _poz_ac("BTCUSDT", 100.0, 2.0)
    import main
    _geri = _borsayi_izole_et()
    try:
        pozlar, _ = main.acik_pozisyonlar_birlesik()
    finally:
        _geri()
    p = pozlar[0]
    for alan in ("sembol", "yon", "giris", "pnl", "miktar", "kaldirac"):
        assert alan in p, f"'{alan}' alanı yok — rapor KeyError atar"
    assert p["giris"] == 100.0 and p["miktar"] == 2.0


def test_kaynak_secimi_kaynakta_bagli():
    """AST: rapor `acik_pozisyonlar_birlesik` KULLANMALI.

    Yardımcıyı yazıp tüketiciye bağlamamak bu kod tabanında tekrar eden
    hata (K-29, K-37, K-52).
    """
    with open(os.path.join(KOK, "main.py"), encoding="utf-8") as fh:
        agac = ast.parse(fh.read())
    fn = next((d for d in ast.walk(agac)
               if isinstance(d, ast.FunctionDef)
               and d.name == "futures_pozisyon_raporu"), None)
    assert fn is not None, "futures_pozisyon_raporu bulunamadı"
    cagrilar = {n.func.id for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "acik_pozisyonlar_birlesik" in cagrilar, (
        "Rapor `acik_pozisyonlar_birlesik` çağırmıyor — koşulsuz "
        "futures'tan okuyorsa paper modda hep 'pozisyon yok' der")
    assert "acik_futures_pozisyonlar" not in cagrilar, (
        "Rapor hâlâ DOĞRUDAN `acik_futures_pozisyonlar` çağırıyor")


# ─────────────────────────────────────────────
# 2. K-57 — PnL RAPORUN KENDİ FİYATINDAN
# ─────────────────────────────────────────────
def test_pnl_rapordaki_guncel_fiyattan_hesaplaniyor():
    """AST: PnL, `guncel_fiyat_al`'dan gelen değerle hesaplanmalı.

    Eskiden `p["pnl"]` kullanılıyordu ve o BAŞKA bir fiyat kaynağından
    (analiz cache'i) geliyordu. Cache boşsa PnL sessizce 0 kalıyor,
    zararda pozisyon "✅ +0.0000" görünüyordu.
    """
    with open(os.path.join(KOK, "main.py"), encoding="utf-8") as fh:
        kaynak = fh.read()
    agac = ast.parse(kaynak)
    fn = next((d for d in ast.walk(agac)
               if isinstance(d, ast.FunctionDef)
               and d.name == "futures_pozisyon_raporu"), None)
    govde = ast.unparse(fn)
    assert "guncel_fiyat_al" in govde, "rapor güncel fiyatı çekmiyor"
    # `guncel` değişkeni PnL hesabında KULLANILMALI
    assert "guncel - _gir" in govde or "_gir - guncel" in govde, (
        "PnL, raporun çektiği `guncel` fiyattan hesaplanmıyor — "
        "gösterilen fiyat ile gösterilen PnL farklı kaynaktan gelir "
        "(K-57: zararda pozisyon '+0.0000' görünüyordu)")


def test_pnl_isareti_zararda_negatif():
    """DAVRANIŞSAL: fiyat düşen LONG için PnL NEGATİF olmalı.

    Eşleme fonksiyonunu doğrudan sınıyoruz (rapor ağ çağrısı yapıyor).
    """
    import main
    ham = [{"sembol": "TESTX", "yon": "LONG", "giris_fiyat": 100.0,
            "miktar": 2.0}]
    main._son_analizler["TESTX"] = {"son_close": 90.0}
    try:
        p = main._paper_pozlari_esle(ham)[0]
        assert p["pnl"] < 0, (
            f"LONG 100→90 için PnL {p['pnl']} — negatif olmalı")
        assert abs(p["pnl"] - (-20.0)) < 1e-6, f"PnL {p['pnl']}, −20 bekleniyordu"
    finally:
        main._son_analizler.pop("TESTX", None)


def test_short_pnl_ters_yonde():
    """SHORT'ta fiyat düşerse PnL POZİTİF olmalı."""
    import main
    ham = [{"sembol": "TESTS", "yon": "SHORT", "giris_fiyat": 100.0,
            "miktar": 2.0}]
    main._son_analizler["TESTS"] = {"son_close": 90.0}
    try:
        p = main._paper_pozlari_esle(ham)[0]
        assert abs(p["pnl"] - 20.0) < 1e-6, (
            f"SHORT 100→90 için PnL {p['pnl']}, +20 bekleniyordu")
    finally:
        main._son_analizler.pop("TESTS", None)


# ─────────────────────────────────────────────
# 3. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_pozisyon_yokken_bos_donuyor():
    """AŞIRI DÜZELTME KONTROLÜ: uydurma pozisyon üretmemeli."""
    _temiz()
    import main
    _geri = _borsayi_izole_et()
    try:
        pozlar, _ = main.acik_pozisyonlar_birlesik()
    finally:
        _geri()
    assert pozlar == [], f"pozisyon yokken {len(pozlar)} döndü"


def test_kontrol_kapali_islem_acik_sayilmiyor():
    """Kapanmış işlem açık pozisyon listesine GİRMEMELİ."""
    from config import DB_PATH
    _temiz(); _poz_ac("BTCUSDT", 100.0, 1.0)
    with sqlite3.connect(DB_PATH) as c:
        c.execute("UPDATE trades SET durum='TP', ts_kapat='2026-09-06T01:00:00'")
        c.commit()
    import main
    _geri = _borsayi_izole_et()
    try:
        pozlar, _ = main.acik_pozisyonlar_birlesik()
    finally:
        _geri()
    assert pozlar == [], (
        f"Kapanmış işlem açık sayıldı ({len(pozlar)}) — bakiye ve "
        f"bağlı sermaye yanlış hesaplanır")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA POZİSYON KAYNAĞI — {len(testler)} test")
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
