# =========================================================
# ASTRA v58 — TELEGRAM KOMUT SEMBOL NORMALİZASYONU (K-52)
# Çalıştırma: python tests/test_komut_sembol.py
#
# NE KORUYOR:
#   36 Telegram komutu tek tek ÇAĞRILARAK test edildi (2026-09-06).
#   Çıktıda şu görüldü:
#       🌐 MARKET — BTCUSDTUSDT
#       ⛓️ ON-CHAIN — BTCUSDTUSDT
#
#   Kök neden — 11 komutta AYNI desen:
#       sembol = f"{c.args[0].upper()}USDT" if c.args else "BTCUSDT"
#
#       /market BTC      → BTCUSDT      ✓
#       /market BTCUSDT  → BTCUSDTUSDT  ✗   ← EN OLASI KULLANIM
#
#   Bot her yerde sembolleri TAM hâliyle gösteriyor (BTCUSDT), yani
#   kullanıcının tam sembolü yazması beklenen davranış — ve tam o
#   girdide bozuluyordu.
#
#   ⚠️ SESSİZ BOZULMA: geçersiz sembol gerçek API çağrısına gidiyor ve
#   `market_veri_topla("BTCUSDTUSDT")` hata vermek yerine SIFIR DOLU
#   sözlük döndürüyor (funding %0.0000, OI 0.00, F&G 0). Kullanıcı
#   bunu gerçek piyasa verisi sanar. §5.1 fail-open deseni.
#
# §4.1: Muhafızın yanına KONTROL testleri var — "her girdiye USDT
#   ekleme" ya da "hiç ekleme" davranışları da testi geçerdi.
# =========================================================
import sys, os, ast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

from main import _sembol_normalize

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─────────────────────────────────────────────
# 1. MUHAFIZ
# ─────────────────────────────────────────────
def test_tam_sembol_ikinci_kez_eklenmez():
    """EN ÖNEMLİ VAKA: kullanıcı tam sembolü yazarsa bozulmamalı."""
    for giris in ("BTCUSDT", "btcusdt", "BtcUsdt", "ETHUSDT", "XRPUSDT"):
        sonuc = _sembol_normalize(giris)
        assert sonuc == giris.upper(), (
            f"'{giris}' → '{sonuc}' (beklenen '{giris.upper()}') — "
            f"ikinci kez USDT ekleniyor, geçersiz sembol API'ye gider")
        assert not sonuc.endswith("USDTUSDT"), f"çift ek: {sonuc}"


def test_kisa_sembol_tamamlanir():
    """`/market BTC` → BTCUSDT (eski davranış KORUNMALI)."""
    assert _sembol_normalize("BTC") == "BTCUSDT"
    assert _sembol_normalize("eth") == "ETHUSDT"
    assert _sembol_normalize("  sol  ") == "SOLUSDT"


def test_ayirici_temizlenir():
    """Kullanıcı BTC/USDT ya da BTC-USDT yazabilir."""
    assert _sembol_normalize("BTC/USDT") == "BTCUSDT"
    assert _sembol_normalize("BTC-USDT") == "BTCUSDT"


def test_diger_teminatlar_korunur():
    """USDC/BUSD gibi çiftlere de USDT eklenmemeli."""
    for g in ("ETHUSDC", "BTCBUSD", "SOLFDUSD", "XRPTUSD"):
        assert _sembol_normalize(g) == g, (
            f"'{g}' → '{_sembol_normalize(g)}' — teminat çifti bozuldu")


def test_bos_girdi_varsayilana_duser():
    assert _sembol_normalize(None) == "BTCUSDT"
    assert _sembol_normalize("") == "BTCUSDT"
    assert _sembol_normalize("   ") == "BTCUSDT"
    assert _sembol_normalize(None, "ETHUSDT") == "ETHUSDT"


def test_eski_desen_kaynakta_kalmadi():
    """Kaynak: `{c.args[0].upper()}USDT` deseni HİÇBİR yerde olmamalı.

    AST ile: f-string içinde `.upper()` çağrısının ardından "USDT"
    sabiti gelen JoinedStr var mı?
    """
    with open(os.path.join(KOK, "main.py"), encoding="utf-8") as fh:
        agac = ast.parse(fh.read())
    kotu = []
    for n in ast.walk(agac):
        if not isinstance(n, ast.JoinedStr):
            continue
        parcalar = n.values
        for i, p in enumerate(parcalar[:-1]):
            if not isinstance(p, ast.FormattedValue):
                continue
            cagri = p.value
            if not (isinstance(cagri, ast.Call)
                    and isinstance(cagri.func, ast.Attribute)
                    and cagri.func.attr == "upper"):
                continue
            sonraki = parcalar[i + 1]
            if (isinstance(sonraki, ast.Constant)
                    and str(sonraki.value).upper().startswith("USDT")):
                kotu.append(n.lineno)
    assert not kotu, (
        f"Eski `{{arg.upper()}}USDT` deseni hâlâ var (satır {kotu}) — "
        f"tam sembol girildiğinde BTCUSDTUSDT üretir")


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_hicbir_sey_eklememe_davranisi_DEGIL():
    """AŞIRI DÜZELTME KONTROLÜ: kısa sembol tamamlanmaya DEVAM etmeli.

    "Hiç USDT ekleme" çözümü çift-ek testini geçerdi ama `/market BTC`
    bozulurdu (BTC diye bir çift yok).
    """
    assert _sembol_normalize("BTC") != "BTC", (
        "Kısa sembol tamamlanmıyor — düzeltme aşırıya kaçmış")
    assert _sembol_normalize("BTC").endswith("USDT")


def test_kontrol_her_girdiye_eklemek_DEGIL():
    """AŞIRI DÜZELTME KONTROLÜ: koşulsuz ekleme olmamalı."""
    assert _sembol_normalize("BTCUSDT").count("USDT") == 1, (
        "Koşulsuz USDT ekleniyor")


def test_kontrol_komutlar_yardimciyi_KULLANIYOR():
    """AST: komutlarda `_sembol_normalize` çağrısı GERÇEKTEN var mı?

    Yardımcıyı doğru yazıp tüketiciye bağlamamak bu kod tabanında
    daha önce yaşandı (K-29, K-37).
    """
    with open(os.path.join(KOK, "main.py"), encoding="utf-8") as fh:
        agac = ast.parse(fh.read())
    kullanan = set()
    for d in ast.walk(agac):
        if not isinstance(d, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not d.name.startswith("cmd_"):
            continue
        for n in ast.walk(d):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_sembol_normalize"):
                kullanan.add(d.name)
    assert len(kullanan) >= 8, (
        f"Yalnızca {len(kullanan)} komut `_sembol_normalize` kullanıyor "
        f"({sorted(kullanan)}) — 11 komutta bu desen vardı, yardımcı "
        f"tüketiciye bağlanmamış olabilir")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA KOMUT SEMBOLÜ — {len(testler)} test")
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
