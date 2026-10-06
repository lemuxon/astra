# =========================================================
# ASTRA — İŞLEM BORSASI VARSAYILANI GÜVENLİ TARAFA DÜŞMELİ (v58, K-106)
# Çalıştırma: python tests/test_guvenli_varsayilan_url.py
#
# `config.py` eskiden şöyleydi:
#     FUTURES_BASE_URL = os.getenv("FUTURES_BASE_URL", "https://fapi.binance.com")
#
# Yani BELİRTİLMEMİŞ bir değer ÜRETİME düşüyordu. Depo herkese açıldığında
# (2026-10-06) temiz kurulumda ÖLÇÜLDÜ (.env yok, ayrı dizin):
#
#     FUTURES_BASE_URL : https://fapi.binance.com   ← ÜRETİM
#     LIVE_TRADING     : False                      ← tek koruma buydu
#
# Tehlikeli senaryo: depoyu klonlayan biri kendi `.env`'ini yazar,
# anahtarlarını ve LIVE_TRADING=true koyar, URL satırını yazmayı atlar
# → GERÇEK PARA. `.env.example`'ı kopyalayan güvendeydi (orada testnet
# yazıyor), kendi dosyasını yazan değildi.
#
# §5.1 ihlali: "bilmiyorum" ≠ "sorun yok". Asimetri açık — yanlış yönde
# hata gerçek para kaybı, doğru yönde hata "testnet bakiyesi gördüm".
#
# ⚠️ NEDEN KONTROL TESTLERİ ŞART (CONTRIBUTING.md):
#   "varsayılan testnet" testini, üretim URL'ini TAMAMEN ENGELLEYEN bir
#   kod da geçer. O yüzden her guard'ın yanında "açıkça üretim isteyen
#   SAYGI GÖRÜR" kontrolü var. İkisi birlikte davranışı kilitler.
#
# ⚠️ NEDEN ALT SÜREÇ: `config.py` ortam değişkenlerini import anında okur
#   ve `load_dotenv()` çağırır. Testin gerçek `.env`'i okumaması gerekiyor,
#   yoksa test makineye göre farklı sonuç verir. Çözüm: alt süreçte dotenv
#   SAPLANIR (hiçbir dosya okunmaz) ve ortam kontrollü verilir.
#
# Ağ, veritabanı ve gerçek emir kullanılmaz.
# =========================================================
import json
import os
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
from tests.izolasyon import izole_et
izole_et()

URETIM = "https://fapi.binance.com"
TESTNET = "https://testnet.binancefuture.com"

# Alt süreçte çalışacak kod: dotenv'i sapla, config'i yükle, değerleri bas.
_ALT_KOD = (
    "import sys, types, json\n"
    "_m = types.ModuleType('dotenv')\n"
    "_m.load_dotenv = lambda *a, **k: None\n"
    "_m.find_dotenv = lambda *a, **k: ''\n"
    "sys.modules['dotenv'] = _m\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import config\n"
    "print(json.dumps({\n"
    "    'futures':    config.FUTURES_BASE_URL,\n"
    "    'veri':       config.BINANCE_DATA_URL,\n"
    "    'spot':       config.BINANCE_BASE_URL,\n"
    "    'backup':     config.BACKUP_FUTURES_URL,\n"
    "    'is_testnet': config.IS_TESTNET,\n"
    "    'live':       config.LIVE_TRADING,\n"
    "}))\n"
)


def _yukle(**cevre):
    """config.py'yi izole alt süreçte yükler. `.env` ASLA okunmaz."""
    # İlgili tüm değişkenleri ortamdan TEMİZLE; yalnızca testin verdiği kalsın.
    ortam = {k: v for k, v in os.environ.items()
             if not k.startswith(("FUTURES_", "BINANCE_", "LIVE_TRADING"))}
    ortam.update({k: str(v) for k, v in cevre.items()})
    sonuc = subprocess.run([sys.executable, "-c", _ALT_KOD, KOK],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=ortam)
    if sonuc.returncode != 0:
        raise RuntimeError("config yüklenemedi: " + (sonuc.stderr or "")[-400:])
    return json.loads(sonuc.stdout.strip().split("\n")[-1])


# ── GUARD: belirtilmemiş değer güvenli tarafa düşmeli ──────────────

def test_futures_url_varsayilani_TESTNET():
    """Hiçbir ortam değişkeni yokken işlem borsası TESTNET olmalı."""
    c = _yukle()
    assert c["futures"] == TESTNET, (
        "FUTURES_BASE_URL varsayılanı %r — ÜRETİM varsayılanı §5.1 ihlali. "
        "Belirtilmemiş değer güvenli tarafa düşmeli." % c["futures"])


def test_varsayilanda_IS_TESTNET_dogru():
    """Türetilmiş bayrak de varsayılanla tutarlı olmalı."""
    c = _yukle()
    assert c["is_testnet"] is True, (
        "IS_TESTNET=%r ama varsayılan URL testnet — türetim bozuk." % c["is_testnet"])


def test_LIVE_TRADING_varsayilani_KAPALI():
    """İkinci koruma katmanı: emir açma varsayılan olarak kapalı."""
    c = _yukle()
    assert c["live"] is False, "LIVE_TRADING varsayılanı açık olmamalı!"


# ── KONTROL: açıkça istenen SAYGI GÖRMELİ (yoksa guard anlamsız) ───

def test_ACIK_uretim_urlsi_SAYGI_GORUR():
    """Üretim bilinçli yazıldığında ÇALIŞMALI.

    Bu kontrol olmadan guard'ı, üretimi tamamen engelleyen bir kod da
    geçer. Amaç varsayılanı güvenli yapmak, üretimi yasaklamak değil.
    """
    c = _yukle(FUTURES_BASE_URL=URETIM)
    assert c["futures"] == URETIM, (
        "Açıkça yazılan üretim URL'i yoksayıldı (%r) — varsayılan "
        "sabitlenmiş olabilir." % c["futures"])
    assert c["is_testnet"] is False, (
        "Üretim URL'inde IS_TESTNET True kaldı — bot kendini testnette "
        "sanıp gerçek parayla işlem yapar. Bu K-106'dan DAHA tehlikeli.")


def test_ACIK_testnet_urlsi_SAYGI_GORUR():
    """Testnet açıkça yazıldığında da aynı sonuç (idempotent)."""
    c = _yukle(FUTURES_BASE_URL=TESTNET)
    assert c["futures"] == TESTNET
    assert c["is_testnet"] is True


def test_ACIK_LIVE_TRADING_SAYGI_GORUR():
    """LIVE_TRADING=true yazan biri gerçekten canlı moda geçebilmeli."""
    c = _yukle(LIVE_TRADING="true")
    assert c["live"] is True, "LIVE_TRADING=true yoksayıldı — kapı kilitlenmiş."


# ── K-15 DEĞİŞMEZİ: piyasa verisi her zaman gerçek borsadan ────────

def test_piyasa_verisi_URETIMDE_kalir():
    """İşlem borsası testnet olsa da klines/ticker GERÇEK borsadan gelir.

    K-15: testnet spot likiditesi ince, gerçek piyasada olmayan sıçramalar
    üretiyor (ölçülen vaka: SOLUSDT 99.94). Varsayılanı testnete çekmek
    bu değişmezi BOZMAMALI.
    """
    c = _yukle()
    assert "testnet" not in c["veri"].lower(), (
        "BINANCE_DATA_URL testnete kaymış (%r) — K-15 bozuldu, sahte "
        "fiyatlar örnekleme sızar." % c["veri"])


def test_backup_url_varsayilanda_futuresi_izler():
    """BACKUP_FUTURES_URL belirtilmezse işlem borsasıyla aynı olmalı.

    Aksi halde ana URL testnet, yedek üretim olur ve failover sessizce
    GERÇEK borsaya düşer.
    """
    c = _yukle()
    assert c["backup"] == c["futures"], (
        "Yedek URL (%r) ana URL'den (%r) farklı — failover gerçek borsaya "
        "düşebilir." % (c["backup"], c["futures"]))


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA GÜVENLİ VARSAYILAN URL (K-106) — {len(testler)} test")
    print(f"{'=' * 58}")
    basari, hata = 0, 0
    for test in testler:
        try:
            test()
            print(f"  [GEÇTİ]  {test.__name__}")
            basari += 1
        except AssertionError as exc:
            print(f"  [HATA]   {test.__name__}\n           → {str(exc)[:180]}")
            hata += 1
        except Exception as exc:
            print(f"  [ÇÖKTÜ]  {test.__name__}: {type(exc).__name__}: {str(exc)[:120]}")
            hata += 1
    print(f"{'=' * 58}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'=' * 58}\n")
    sys.exit(0 if hata == 0 else 1)
