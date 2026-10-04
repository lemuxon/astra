# =========================================================
# ASTRA v58 — PİYASA VERİSİ KAYNAĞI TESTLERİ (K-15)
# Çalıştırma: python tests/test_veri_kaynagi.py
#
# NE KORUYOR — ölçülen vaka (2026-09-02, paper işlemi #21):
#   Bot SOLUSDT'yi 99.89'dan SHORT açtı. O anki 5m barlar:
#       TESTNET  O=98.79  H=99.94  C=98.47
#       GERÇEK   O=98.55  H=98.63  C=98.47
#   Testnet'te gerçek piyasada OLMAYAN bir sıçrama vardı. Bot henüz
#   kapanmamış bara baktığı için o anki "close" 99.92 okundu. TP 99.14
#   zaten piyasanın altındaydı → 2.9 dakikada "TP" oldu, +%0.64 yazıldı.
#   21 işlemlik veri setindeki 5 kazançtan biri, gerçek piyasada hiç
#   var olmayan bir fiyattan geliyordu.
#
#   Fiyat BAYAT DEĞİLDİ — tazeydi ama testnet'e özgüydü. Testnet spot
#   likiditesi ince; tek bir test emri fiyatı %1.5 oynatabiliyor.
#   Ölçüm: sinyallerin %2.3'ü gerçek piyasadan >%0.5, %0.54'ü >%1 sapmış.
#
# KURAL: Halka açık piyasa verisi (klines, ticker) GERÇEK borsadan;
#   hesap/emir işlemleri BINANCE_BASE_URL'de kalır.
#   `exchangeInfo` BİLEREK dışarıda — o, emrin gideceği borsanın
#   kurallarıdır (min_notional, lot adımı).
#
# Testler AĞA ÇIKMAZ: requests.get yakalanıp çağrılan URL doğrulanır.
#
# §4.1: Muhafızların yanına KONTROL testleri — "her şeyi data URL'e
#   yönlendir" de muhafızları geçerdi ama exchangeInfo'yu bozardı.
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


class _SahteYanit:
    """requests.Response yerine geçer."""
    def __init__(self, veri):
        self._veri = veri
    def raise_for_status(self):
        pass
    def json(self):
        return self._veri


def _url_yakala(fn, yanit_verisi):
    """`fn`i çağır, requests.get'e giden URL'i döndür (ağa çıkmadan)."""
    from data import binance_client as bc
    yakalanan = {}
    orij = bc.requests.get

    def sahte(url, **kw):
        yakalanan["url"] = url
        yakalanan["params"] = kw.get("params")
        return _SahteYanit(yanit_verisi)

    bc.requests.get = sahte
    try:
        fn(bc)
    finally:
        bc.requests.get = orij
    return yakalanan.get("url", "")


# Binance klines yanıt formatı (12 alan)
_KLINE = [[1756800000000, "100.0", "101.0", "99.0", "100.5", "10.0",
           1756800299999, "1000.0", 5, "5.0", "500.0", "0"]]


# ─────────────────────────────────────────────
# 1. MUHAFIZ — piyasa verisi GERÇEK borsadan
# ─────────────────────────────────────────────
def test_klines_veri_urlini_kullanir():
    """Mum verisi işlem borsasından DEĞİL, veri borsasından gelmeli."""
    from config import BINANCE_DATA_URL
    url = _url_yakala(lambda bc: bc.klines_indir("SOLUSDT", "5m", 10), _KLINE)
    assert url.startswith(BINANCE_DATA_URL), (
        f"klines {url!r} adresine gitti; BINANCE_DATA_URL "
        f"({BINANCE_DATA_URL}) bekleniyordu — testnet artefaktı sızar")


def test_ticker_24h_veri_urlini_kullanir():
    from config import BINANCE_DATA_URL
    url = _url_yakala(lambda bc: bc.ticker_24h("SOLUSDT"), {"lastPrice": "100"})
    assert url.startswith(BINANCE_DATA_URL), \
        f"ticker_24h {url!r} adresine gitti"


def test_anlik_fiyat_veri_urlini_kullanir():
    from config import BINANCE_DATA_URL
    url = _url_yakala(lambda bc: bc.anlık_fiyat("SOLUSDT"), {"price": "100.0"})
    assert url.startswith(BINANCE_DATA_URL), \
        f"anlık_fiyat {url!r} adresine gitti"


def test_veri_urli_testnet_degil():
    """Varsayılan GERÇEK borsa olmalı — BASE_URL testnet olsa bile.

    `.env` içinde BINANCE_BASE_URL testnet'e ayarlı. Veri URL'i ondan
    türetilseydi düzeltme hiçbir şey değiştirmezdi.
    """
    from config import BINANCE_DATA_URL
    assert "testnet" not in BINANCE_DATA_URL.lower(), (
        f"BINANCE_DATA_URL testnet'e bakıyor ({BINANCE_DATA_URL}) — "
        f"ince likidite sıçramaları paper verisine sızmaya devam eder")


# ─────────────────────────────────────────────
# 2. KONTROL — her şeyi taşımak YANLIŞ olurdu
# ─────────────────────────────────────────────
def test_exchange_info_ISLEM_urlini_kullanir():
    """Kontrol testi (§4.1): sembol kuralları emrin gideceği borsadan.

    min_notional / lot adımı testnet'te farklı olabilir. Gerçek borsanın
    filtreleriyle testnet'e emir göndermek reddedilmeye yol açar.
    Bu test olmadan "hepsini DATA_URL yap" da muhafızları geçerdi.
    """
    from config import BINANCE_BASE_URL
    from data import binance_client as bc
    bc._exchange_info_cache.pop("TESTSYMUSDT", None)   # önbellek çağrıyı yutmasın
    yanit = {"symbols": [{"symbol": "TESTSYMUSDT", "filters": [],
                          "baseAsset": "TESTSYM", "quoteAsset": "USDT"}]}
    url = _url_yakala(lambda b: b.sembol_filtre_al("TESTSYMUSDT"), yanit)
    assert url.startswith(BINANCE_BASE_URL), (
        f"exchangeInfo {url!r} adresine gitti; işlem borsası "
        f"({BINANCE_BASE_URL}) bekleniyordu — sembol kuralları emrin "
        f"gideceği borsadan okunmalı")


def test_imzali_istek_ISLEM_urlini_kullanir():
    """Kontrol: hesap/emir yolu veri borsasına KAYMAMALI.

    Gerçek borsaya testnet anahtarıyla imzalı istek atmak kimlik
    hatası verir; daha kötüsü canlı anahtarla yanlış borsaya emir.
    """
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "binance_client.py")
    with open(yol, encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))
    i = kod.find("def _istek")
    if i < 0:
        i = kod.find('url     = f"{BINANCE')
    assert i >= 0, "imzalı istek fonksiyonu bulunamadı — test hedefi kaymış"
    blok = kod[i:i + 600]
    assert "BINANCE_DATA_URL" not in blok, (
        "İmzalı/hesap isteği BINANCE_DATA_URL kullanıyor — kimlik "
        "doğrulaması yanlış borsaya gider")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA PİYASA VERİSİ KAYNAĞI — {len(testler)} test")
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
