# =========================================================
# ASTRA v57 — GRAFİK ÜRETİMİ THREAD GÜVENLİĞİ
# Çalıştırma: python tests/test_grafik_thread.py
#
# NE KORUYOR:
#   Telegram'a giden teknik analiz grafikleri bazen SİMSİYAH, bazen
#   BEMBEYAZ geliyordu (kullanıcı bildirimi, 2026-09-02).
#
#   KÖK NEDEN: `_grafik_olustur` pyplot'un GLOBAL durumunu kullanıyordu
#   (`plt.subplots` / `plt.savefig` / `plt.close`), ama coin analizi
#   5 sembol için EŞZAMANLI çalışıyor:
#       loop.run_in_executor(None, coin_analiz, ...)     # main.py:1777
#       asyncio.gather(*[_tek_coin_isle(s) for s in COINS])
#   Yani fonksiyon 5 GERÇEK THREAD'den çağrılıyor ve pyplot'un figür
#   kaydı thread-safe DEĞİL:
#       Thread A: plt.subplots()  → figür A "current"
#       Thread B: plt.subplots()  → figür B "current" oldu
#       Thread A: plt.savefig()   → B'yi / yarım tuvali kaydeder
#       Thread A: plt.close()     → B'yi KAPATIR
#       Thread B: plt.savefig()   → figür yok → BOŞ görüntü
#
#   ÖLÇÜM (5 eşzamanlı üretim):
#       eski kod → renk sayıları [1, 1, 1, 1, 670]  → 4/5 BOZUK
#       yeni kod → [1630 × 5]                       → 0/5 bozuk
#
#   ÇÖZÜM: `Figure` + `FigureCanvasAgg` — pyplot'a hiç dokunulmuyor,
#   global kayıt yok, thread'ler birbirini göremiyor.
#
# §4.1: Muhafızın yanına KONTROL testi var — "hiç grafik üretmeyen" bir
#   kod da bozulma testini geçerdi.
# =========================================================
import sys, os, threading, tempfile, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

import matplotlib
matplotlib.use("Agg")

MIN_RENK = 50    # sağlıklı grafik binlerce renk içerir; tek renkli = bozuk


def _veri(n=150):
    import numpy as np, pandas as pd
    rng = np.random.default_rng(42)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)))
    return {
        "close": close,
        "rsi":   pd.Series(rng.uniform(20, 80, n)),
        "macd":  pd.Series(rng.normal(0, 1, n)),
        "sig":   pd.Series(rng.normal(0, 1, n)),
        "upper": close + 2,
        "lower": close - 2,
        "ma":    close.rolling(5).mean().bfill(),
    }


def _renk_sayisi(yol):
    from PIL import Image
    with Image.open(yol) as im:
        return len(im.convert("RGB").getcolors(maxcolors=1000000) or [])


def _paralel_uret(fn, adet=5):
    """fn(sembol) -> yol  |  `adet` thread ile eşzamanlı çağır."""
    yollar, hatalar = [], []

    def isle(s):
        try:
            yollar.append(fn(s))
        except Exception as e:
            hatalar.append(f"{type(e).__name__}: {e}")

    ths = [threading.Thread(target=isle, args=(f"TESTC{i}",)) for i in range(adet)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(timeout=120)
    return yollar, hatalar


def _uret_gercek(sembol):
    """Üretimdeki gerçek fonksiyonu çağır."""
    import main
    d = _veri()
    return main._grafik_olustur(d["close"], d["rsi"], d["macd"], d["sig"],
                                d["upper"], d["lower"], d["ma"], sembol)


# ─────────────────────────────────────────────
# 1. MUHAFIZ
# ─────────────────────────────────────────────
def test_paralel_grafikler_bozulmuyor():
    """5 thread eşzamanlı grafik üretsin — hiçbiri tek renkli olmamalı.

    Eski kodda 5'in 4'ü tek renkli (simsiyah/bembeyaz) çıkıyordu.
    """
    yollar, hatalar = _paralel_uret(_uret_gercek, 5)
    assert not hatalar, f"Grafik üretiminde hata: {hatalar[:2]}"
    assert len(yollar) == 5, f"Beklenen 5 dosya, üretilen {len(yollar)}"

    renkler = [_renk_sayisi(y) for y in yollar]
    bozuk = [r for r in renkler if r < MIN_RENK]
    assert not bozuk, (
        f"{len(bozuk)}/5 grafik BOZUK (renk sayıları: {sorted(renkler)}). "
        f"Tek renkli görüntü = Telegram'a giden simsiyah/bembeyaz resim. "
        f"pyplot global durumu thread'ler arasında çakışıyor olabilir.")


def test_pyplot_global_durumu_kullanilmiyor():
    """Kaynak düzeyi: `_grafik_olustur` plt.savefig/plt.close ÇAĞIRMAMALI.

    Bir figürü global kayıttan kapatmak, BAŞKA bir thread'in figürünü
    kapatma riski taşır — hatanın kaynağıydı.
    """
    # AST ile ayrıştır: docstring ve yorumlar HARİÇ, yalnızca gerçek kod.
    # (İlk sürüm satır bazlı okuyordu ve DOCSTRING'deki `plt.savefig`
    #  açıklamasını gerçek çağrı sanıp yanlış alarm veriyordu.)
    import ast
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "main.py"), encoding="utf-8") as fh:
        agac = ast.parse(fh.read())

    fn = next((d for d in ast.walk(agac)
               if isinstance(d, ast.FunctionDef) and d.name == "_grafik_olustur"), None)
    assert fn is not None, "_grafik_olustur bulunamadı"

    govde = list(fn.body)
    if (govde and isinstance(govde[0], ast.Expr)
            and isinstance(govde[0].value, ast.Constant)
            and isinstance(govde[0].value.value, str)):
        govde = govde[1:]          # docstring'i at
    kod = "\n".join(ast.unparse(d) for d in govde)

    for yasak in ("plt.savefig", "plt.close", "plt.subplots", "plt.tight_layout"):
        assert yasak not in kod, (
            f"_grafik_olustur hâlâ `{yasak}` kullanıyor — pyplot global "
            f"durumu thread-safe değil, grafikler bozulur")
    assert "Figure(" in kod, "Figure nesnesi kullanılmıyor"


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_grafik_gercekten_uretiliyor():
    """Dosya GERÇEKTEN oluşmalı ve zengin içerikli olmalı.

    "Hiç grafik üretme" davranışı yukarıdaki bozulma testini de geçerdi
    (bozuk dosya yoksa liste boş kalır).
    """
    yol = _uret_gercek("TESTTEK")
    assert os.path.exists(yol), f"Grafik dosyası oluşmadı: {yol}"
    assert os.path.getsize(yol) > 5000, (
        f"Grafik dosyası çok küçük ({os.path.getsize(yol)} bayt) — "
        f"muhtemelen boş tuval")
    renk = _renk_sayisi(yol)
    assert renk > 500, (
        f"Tek grafikte yalnızca {renk} renk — içerik çizilmemiş olabilir")


def test_kontrol_bozulma_tespiti_calisiyor():
    """Bozulma ölçütü GERÇEKTEN bozuk dosyayı yakalıyor mu?

    Kasten tek renkli bir PNG üretip tespit edilmesini bekliyoruz.
    Bu olmadan muhafız testi, ölçüt bozuksa da yeşil kalırdı.
    """
    from PIL import Image
    d = tempfile.mkdtemp()
    yol = os.path.join(d, "duz.png")
    Image.new("RGB", (200, 200), (13, 17, 23)).save(yol)   # #0d1117 düz
    renk = _renk_sayisi(yol)
    assert renk < MIN_RENK, (
        f"Düz renkli görüntüde {renk} renk sayıldı — bozulma ölçütü "
        f"çalışmıyor, muhafız testi anlamsız")


# ─────────────────────────────────────────────
# 3. İZOLASYON (v58 K-34)
# ─────────────────────────────────────────────
# Grafik yolu SABİT KODLUYDU: f"logs/astra_{sembol}.png".
# Logging kurulumu `_LOG_DIR` (ASTRA_LOG_DIR) kullanırken grafik yazımı
# bu yönlendirmenin DIŞINDA kalıyordu → test koşusu üretim `logs/`
# dizinine PNG bırakıyordu (kanıt: astra_TESTC0..4.png, 2026-09-05).
#
# Bugünkü zarar kozmetikti (sentetik semboller), ama delik şuydu:
# gerçek bir sembolle çağrılan bir test, botun Telegram'a gönderdiği
# grafiği SESSİZCE ezerdi — kullanıcıya fikstür verisi gerçek piyasa
# diye giderdi. DEVAM_NOTLARI.md §4.6.

def _uretim_logs_dizini():
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(kok, "logs")


def test_grafik_izole_dizine_yaziliyor():
    """Grafik ASTRA_LOG_DIR'e yazılmalı, üretim `logs/`'una DEĞİL.

    izole_et() ASTRA_LOG_DIR'i geçici dizine kurar; grafik oradan
    çıkmalı ve üretim dizinine hiç dokunmamalı.
    """
    import main
    sembol = "TESTIZOLE"
    uretim = os.path.join(_uretim_logs_dizini(), f"astra_{sembol}.png")
    if os.path.exists(uretim):
        os.remove(uretim)          # önceki koşudan kalmış olabilir

    yol = _uret_gercek(sembol)

    assert os.path.exists(yol), f"Grafik oluşmadı: {yol}"
    assert os.path.abspath(yol).startswith(os.path.abspath(main._LOG_DIR)), (
        f"Grafik _LOG_DIR ({main._LOG_DIR}) DIŞINA yazıldı: {yol}")
    assert not os.path.exists(uretim), (
        f"Test ÜRETİM logs/ dizinine yazdı: {uretim} — izolasyon deliği. "
        f"Gerçek bir sembolle çağrılsaydı botun Telegram'a gönderdiği "
        f"grafiği ezerdi (§4.6)")


def test_grafik_yolu_sabit_kodlu_degil():
    """Kaynak düzeyi: `_grafik_olustur` "logs/" literalini İÇERMEMELİ.

    Davranış testi tek başına yetmez: birisi yolu yeniden sabit koderse
    ve o sırada ASTRA_LOG_DIR tesadüfen "logs" ise test yeşil kalırdı.
    """
    import ast
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "main.py"), encoding="utf-8") as fh:
        agac = ast.parse(fh.read())

    fn = next((d for d in ast.walk(agac)
               if isinstance(d, ast.FunctionDef) and d.name == "_grafik_olustur"), None)
    assert fn is not None, "_grafik_olustur bulunamadı"

    govde = list(fn.body)
    if (govde and isinstance(govde[0], ast.Expr)
            and isinstance(govde[0].value, ast.Constant)
            and isinstance(govde[0].value.value, str)):
        govde = govde[1:]
    kod = "\n".join(ast.unparse(d) for d in govde)

    assert "logs/" not in kod and "logs\\" not in kod, (
        "_grafik_olustur içinde sabit kodlu `logs/` yolu var — "
        "ASTRA_LOG_DIR yönlendirmesini atlar")
    assert "_LOG_DIR" in kod, (
        "_grafik_olustur `_LOG_DIR` kullanmıyor — yol yönlendirilemez")


def test_kontrol_uretimde_varsayilan_logs_kalmali():
    """AŞIRI DÜZELTME KONTROLÜ: ASTRA_LOG_DIR yoksa varsayılan `logs`.

    "Grafiği hep geçici dizine yaz" da yukarıdaki iki testi geçerdi —
    ama o zaman üretimde Telegram'a giden grafik hiç kalıcı olmazdı.
    """
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "main.py"), encoding="utf-8") as fh:
        kaynak = fh.read()
    assert 'os.getenv("ASTRA_LOG_DIR", "logs")' in kaynak, (
        "_LOG_DIR varsayılanı `logs` değil — üretimde grafik/log "
        "beklenmedik yere gider")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA GRAFİK THREAD GÜVENLİĞİ — {len(testler)} test")
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
