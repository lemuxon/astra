# =========================================================
# ASTRA — İMZA + RETRY YOLU TESTLERİ (v56)
# Çalıştırma: python tests/test_imza_retry.py
#
# Hedef: data/binance_futures_client.py — GERÇEK EMİRLERİN imzalanıp
# gönderildiği son katman. Denetimde kapsamı %26 idi.
#
# En kritik özellik: RETRY ÇİFT EMİR AÇMAMALI.
# Senaryo: emir gider → Binance işler → yanıt dönerken timeout →
# kod tekrar gönderir → İKİ pozisyon açılır, sistem birini bilir.
# Koruma: newClientOrderId retry döngüsünden ÖNCE üretilir ve
# tüm denemelerde AYNI kalır → borsa ikinciyi "duplicate" ile reddeder.
#
# Ağa çıkılmaz: requests tamamen mock'lanır, sahte anahtar kullanılır.
# =========================================================
import sys, os, warnings, hmac, hashlib, re
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# v57: ÜRETİM durum dosyalarına yazmayı engelle. Proje modülleri import
# EDİLMEDEN ÖNCE çağrılmalı — config.py yolları import anında okur.
from tests.izolasyon import izole_et; izole_et()

os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

from urllib.parse import urlencode, parse_qs

TEST_KEY    = "test_api_key_1234567890"
TEST_SECRET = "test_api_secret_abcdefghijklmnop"


class SahteYanit:
    """requests.Response yerine geçen minimal sahte."""
    def __init__(self, status=200, govde=None, headers=None, metin=""):
        self.status_code = status
        self._govde = govde if govde is not None else {}
        self.headers = headers or {}
        self.text = metin or str(self._govde)
    def json(self):
        if isinstance(self._govde, Exception):
            raise self._govde
        return self._govde


class Kayitci:
    """Giden istekleri kaydeden sahte requests fonksiyonu."""
    def __init__(self, yanitlar):
        self.yanitlar = list(yanitlar)
        self.istekler = []
    def __call__(self, url, params=None, headers=None, timeout=None, **kw):
        self.istekler.append({"url": url, "params": dict(params or {}),
                              "headers": dict(headers or {})})
        return self.yanitlar.pop(0) if self.yanitlar else SahteYanit(200, {})


def _hazirla(yanitlar, uyku_yakala=True):
    """bfc modülünü test için mock'la. (modul, kayitci, uykular) döner."""
    import data.binance_futures_client as bfc
    bfc.BINANCE_API_KEY    = TEST_KEY
    bfc.BINANCE_API_SECRET = TEST_SECRET
    bfc._zaman_offset_guncel = 0.0
    kayitci = Kayitci(yanitlar)
    uykular = []

    bfc._orij = {
        "post": bfc.requests.post, "get": bfc.requests.get,
        "delete": bfc.requests.delete, "sleep": bfc.time.sleep,
        "senk": bfc._sunucu_zaman_senkronize,
    }
    bfc.requests.post = kayitci
    bfc.requests.get = kayitci
    bfc.requests.delete = kayitci
    bfc._sunucu_zaman_senkronize = lambda *a, **kw: 0
    if uyku_yakala:
        bfc.time.sleep = lambda s: uykular.append(s)
    return bfc, kayitci, uykular


def _geri_al(bfc):
    o = bfc._orij
    bfc.requests.post, bfc.requests.get = o["post"], o["get"]
    bfc.requests.delete, bfc.time.sleep = o["delete"], o["sleep"]
    bfc._sunucu_zaman_senkronize = o["senk"]


# ═════════════════════════════════════════════════════════
# 1. İMZA DOĞRULUĞU
# ═════════════════════════════════════════════════════════
def test_imza_hmac_sha256_dogru_hesaplaniyor():
    """İmza, signature HARİÇ tüm parametrelerin urlencode'unun HMAC'i olmalı."""
    bfc, kay, _ = _hazirla([SahteYanit(200, {"orderId": 1})])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {"asset": "USDT"})
        gonderilen = kay.istekler[0]["params"]
        imza = gonderilen.pop("signature", None)
        assert imza, "signature parametresi hiç gönderilmedi!"
        beklenen = hmac.new(TEST_SECRET.encode(),
                            urlencode(gonderilen).encode(),
                            hashlib.sha256).hexdigest()
        assert imza == beklenen, (
            "İmza yanlış hesaplanmış — Binance tüm imzalı istekleri reddeder")
    finally:
        _geri_al(bfc)


def test_imza_kendi_kendini_imzalamiyor():
    """signature, imzalanan payload'ın İÇİNDE olmamalı (klasik hata)."""
    bfc, kay, _ = _hazirla([SahteYanit(200, {})])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        p = kay.istekler[0]["params"]
        imza = p["signature"]
        # signature dahil edilerek hesaplanan imza FARKLI olmalı
        yanlis = hmac.new(TEST_SECRET.encode(),
                          urlencode(p).encode(), hashlib.sha256).hexdigest()
        assert imza != yanlis, "signature kendi payload'ına dahil edilmiş"
    finally:
        _geri_al(bfc)


def test_timestamp_ve_recvwindow_imzaya_dahil():
    """timestamp/recvWindow imzadan ÖNCE eklenmeli, yoksa -1022 alınır."""
    bfc, kay, _ = _hazirla([SahteYanit(200, {})])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        p = kay.istekler[0]["params"]
        assert "timestamp" in p and "recvWindow" in p
        assert int(p["recvWindow"]) >= 5000, "recvWindow çok dar — saat kaymasında red"
    finally:
        _geri_al(bfc)


def test_api_key_header_gonderiliyor():
    bfc, kay, _ = _hazirla([SahteYanit(200, {})])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        assert kay.istekler[0]["headers"].get("X-MBX-APIKEY") == TEST_KEY
    finally:
        _geri_al(bfc)


def test_secret_asla_gonderilmiyor():
    """GÜVENLİK: secret hiçbir zaman istek gövdesinde/başlığında olmamalı."""
    bfc, kay, _ = _hazirla([SahteYanit(200, {})])
    try:
        bfc._futures_istek("POST", "/fapi/v1/order",
                           {"symbol": "BTCUSDT", "side": "BUY"})
        istek = kay.istekler[0]
        hepsi = str(istek["params"]) + str(istek["headers"]) + istek["url"]
        assert TEST_SECRET not in hepsi, "API SECRET isteğe sızdı!"
    finally:
        _geri_al(bfc)


def test_anahtar_yoksa_fatal_hata():
    """Anahtar yoksa retry yapılmamalı, hemen fatal dönmeli."""
    import data.binance_futures_client as bfc
    from utils.exceptions import FatalExchangeError
    eski_k, eski_s = bfc.BINANCE_API_KEY, bfc.BINANCE_API_SECRET
    bfc.BINANCE_API_KEY = ""
    try:
        try:
            bfc._futures_istek("GET", "/fapi/v3/balance", {})
            raise AssertionError("Anahtarsız istek fatal hata vermedi")
        except FatalExchangeError:
            pass
    finally:
        bfc.BINANCE_API_KEY, bfc.BINANCE_API_SECRET = eski_k, eski_s


# ═════════════════════════════════════════════════════════
# 2. IDEMPOTENCY — çift emir önleme (v53), EN KRİTİK
# ═════════════════════════════════════════════════════════
def test_retry_ayni_client_order_id_kullanir():
    """RETRY'LARDA newClientOrderId DEĞİŞMEMELİ.

    Değişirse borsa ikinci isteği yeni emir sanar → ÇİFT POZİSYON.
    """
    from utils.exceptions import RetryableExchangeError
    # 2 kez geçici hata, 3.'de başarı
    bfc, kay, _ = _hazirla([
        SahteYanit(500, {"code": -1001, "msg": "internal"}),
        SahteYanit(500, {"code": -1001, "msg": "internal"}),
        SahteYanit(200, {"orderId": 42}),
    ])
    try:
        bfc._futures_istek("POST", "/fapi/v1/order",
                           {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET"})
        assert len(kay.istekler) == 3, f"{len(kay.istekler)} deneme yapıldı"
        idler = {i["params"].get("newClientOrderId") for i in kay.istekler}
        assert len(idler) == 1, (
            f"Retry'larda FARKLI newClientOrderId kullanıldı: {idler} — "
            f"borsa bunları AYRI emir sayar, ÇİFT POZİSYON açılır!")
        assert list(idler)[0], "newClientOrderId hiç üretilmedi"
    finally:
        _geri_al(bfc)


def test_client_order_id_binance_formatina_uygun():
    """Binance kuralı: ^[\\.A-Z\\:/a-z0-9_-]{1,36}$"""
    bfc, kay, _ = _hazirla([SahteYanit(200, {"orderId": 1})])
    try:
        bfc._futures_istek("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"})
        cid = kay.istekler[0]["params"]["newClientOrderId"]
        assert re.fullmatch(r"[\.A-Z\:/a-z0-9_-]{1,36}", cid), \
            f"Geçersiz newClientOrderId: {cid!r} — borsa reddeder"
    finally:
        _geri_al(bfc)


def test_emir_disi_endpointe_client_id_eklenmez():
    """Sadece POST /order idempotency ID almalı; GET'ler almamalı."""
    bfc, kay, _ = _hazirla([SahteYanit(200, {}), SahteYanit(200, {})])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        bfc._futures_istek("GET", "/fapi/v3/positionRisk", {})
        for i in kay.istekler:
            assert "newClientOrderId" not in i["params"], \
                "GET isteğine gereksiz newClientOrderId eklendi"
    finally:
        _geri_al(bfc)


def test_disaridan_verilen_client_id_korunur():
    """Çağıran kendi ID'sini verdiyse üzerine yazılmamalı."""
    bfc, kay, _ = _hazirla([SahteYanit(200, {"orderId": 1})])
    try:
        bfc._futures_istek("POST", "/fapi/v1/order",
                           {"symbol": "BTCUSDT", "newClientOrderId": "benim_id_123"})
        assert kay.istekler[0]["params"]["newClientOrderId"] == "benim_id_123"
    finally:
        _geri_al(bfc)


def test_duplicate_hatasinda_tekrar_gonderilmez():
    """v53: Borsa 'duplicate' derse emir TEKRAR GÖNDERİLMEMELİ.

    'duplicate' = ilk emir borsaya ULAŞMIŞ demektir. Tekrar göndermek
    yerine emrin gerçek durumu sorgulanmalı.
    """
    bfc, kay, _ = _hazirla([
        SahteYanit(400, {"code": -4015, "msg": "Duplicate client order id"}),
        SahteYanit(200, {"orderId": 77, "status": "FILLED",
                         "executedQty": "0.001", "avgPrice": "60000"}),
    ])
    try:
        sonuc = bfc._futures_istek("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"})
        # 1. istek emir, 2. istek DURUM SORGUSU olmalı (yeni emir değil)
        assert len(kay.istekler) == 2, f"{len(kay.istekler)} istek yapıldı"
        ikinci = kay.istekler[1]
        assert "origClientOrderId" in ikinci["params"], (
            "Duplicate sonrası YENİ EMİR gönderilmiş olabilir — "
            "durum sorgusu (origClientOrderId) bekleniyordu")
        assert sonuc and sonuc.get("orderId") == 77, \
            "İlk emrin gerçek durumu döndürülmedi"
    finally:
        _geri_al(bfc)


# ═════════════════════════════════════════════════════════
# 3. RETRY POLİTİKASI
# ═════════════════════════════════════════════════════════
def test_fatal_hatada_retry_yapilmaz():
    """Yetersiz bakiye gibi fatal hatada tekrar denemek anlamsız + riskli."""
    from utils.exceptions import FatalExchangeError
    bfc, kay, _ = _hazirla([SahteYanit(400, {"code": -2010, "msg": "insufficient balance"})])
    try:
        try:
            bfc._futures_istek("GET", "/fapi/v3/balance", {})
            raise AssertionError("Fatal hatada istisna fırlatılmadı")
        except FatalExchangeError:
            pass
        assert len(kay.istekler) == 1, \
            f"Fatal hatada {len(kay.istekler)} kez denendi — retry yapılmamalı"
    finally:
        _geri_al(bfc)


def test_gecici_hatada_max_retries_kadar_denenir():
    bfc, kay, _ = _hazirla([SahteYanit(500, {"code": -1001, "msg": "x"})
                            for _ in range(10)])
    try:
        try:
            bfc._futures_istek("GET", "/fapi/v3/balance", {})
        except Exception:
            pass
        assert len(kay.istekler) == bfc.MAX_RETRIES, (
            f"{len(kay.istekler)} deneme yapıldı, {bfc.MAX_RETRIES} bekleniyordu")
    finally:
        _geri_al(bfc)


def test_ustel_geri_cekilme():
    """Denemeler arası bekleme ARTMALI (sabit değil) — borsayı dövmemek için."""
    bfc, kay, uykular = _hazirla([SahteYanit(500, {"code": -1001, "msg": "x"})
                                  for _ in range(10)])
    try:
        try:
            bfc._futures_istek("GET", "/fapi/v3/balance", {})
        except Exception:
            pass
        gercek = [u for u in uykular if u > 0]
        assert len(gercek) >= 2, "Denemeler arası hiç bekleme yok"
        assert gercek[1] > gercek[0], \
            f"Bekleme artmıyor ({gercek}) — üstel geri çekilme yok"
    finally:
        _geri_al(bfc)


# ═════════════════════════════════════════════════════════
# 4. RATE LIMIT (v56 eklendi — hiç test edilmemişti)
# ═════════════════════════════════════════════════════════
def test_429_retry_after_saygi_gosterir():
    """v56: HTTP 429'da Retry-After başlığına UYULMALI."""
    bfc, kay, uykular = _hazirla([
        SahteYanit(429, {}, headers={"Retry-After": "7"}, metin="rate limit"),
        SahteYanit(200, {"orderId": 1}),
    ])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        assert any(abs(u - 7.0) < 0.01 for u in uykular), (
            f"Retry-After=7 yok sayıldı, beklemeler: {uykular} — "
            f"IP ban süresi uzayabilir")
    finally:
        _geri_al(bfc)


def test_418_ip_ban_uzun_bekler():
    """418 = IP ban. Retry-After yoksa kısa beklememeli."""
    bfc, kay, uykular = _hazirla([
        SahteYanit(418, {}, metin="banned"),
        SahteYanit(200, {}),
    ])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        assert any(u >= 30 for u in uykular), (
            f"418 IP ban'da kısa beklendi ({uykular}) — ban uzayabilir")
    finally:
        _geri_al(bfc)


def test_rate_limit_ust_sinirli():
    """Retry-After absürt gelirse (örn. 99999) beklemede tavan olmalı."""
    bfc, kay, uykular = _hazirla([
        SahteYanit(429, {}, headers={"Retry-After": "99999"}),
        SahteYanit(200, {}),
    ])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        assert all(u <= 300 for u in uykular), (
            f"Bekleme tavanı yok ({uykular}) — bot saatlerce donabilir")
    finally:
        _geri_al(bfc)


def test_binance_1003_rate_limit_olarak_siniflanir():
    """v56: Binance -1003 kodu RateLimitError olmalı."""
    from utils.exceptions import RateLimitError, exchange_hata_siniflandir
    e = exchange_hata_siniflandir(-1003, "TOO_MANY_REQUESTS", "/x")
    assert isinstance(e, RateLimitError), \
        f"-1003 {type(e).__name__} olarak sınıflandı — bekleme süresi yok sayılır"
    assert e.bekleme_suresi > 0


# ═════════════════════════════════════════════════════════
# 5. SAAT KAYMASI (-1021)
# ═════════════════════════════════════════════════════════
def test_1021_offset_yenilenip_tekrar_denenir():
    """-1021 (timestamp) hatasında offset YENİDEN SORULUP kullanılmalı.

    NOT: Offset'i sabit tutup 'timestamp değişti mi' diye bakmak yanıltıcıdır —
    iki istek aynı milisaniyede olursa timestamp doğal olarak aynı çıkar.
    Bu yüzden senkronizasyon fonksiyonu ikinci çağrıda FARKLI offset döndürür;
    böylece yeni offset'in gerçekten KULLANILDIĞI gözlemlenebilir.
    """
    bfc, kay, _ = _hazirla([
        SahteYanit(400, {"code": -1021, "msg": "Timestamp for this request..."}),
        SahteYanit(200, {"orderId": 5}),
    ])
    cagri = {"n": 0}
    def degisen_offset(*a, **kw):
        cagri["n"] += 1
        return 0 if cagri["n"] == 1 else 123456   # 2. çağrıda farklı
    bfc._sunucu_zaman_senkronize = degisen_offset
    try:
        sonuc = bfc._futures_istek("GET", "/fapi/v3/balance", {})
        assert len(kay.istekler) == 2, "Saat hatasında tekrar denenmedi"
        assert sonuc and sonuc.get("orderId") == 5
        assert cagri["n"] >= 2, "Offset yeniden senkronize edilmedi"

        t1 = int(kay.istekler[0]["params"]["timestamp"])
        t2 = int(kay.istekler[1]["params"]["timestamp"])
        assert t2 - t1 >= 123000, (
            f"Yeni offset kullanılmamış (fark {t2-t1}ms) — saat düzeltmesi "
            f"uygulanmadan tekrar deneniyor, -1021 sonsuza kadar sürer")

        # Yeni timestamp ile YENİDEN imzalanmış olmalı
        p2 = dict(kay.istekler[1]["params"])
        imza2 = p2.pop("signature")
        beklenen = hmac.new(TEST_SECRET.encode(), urlencode(p2).encode(),
                            hashlib.sha256).hexdigest()
        assert imza2 == beklenen, \
            "Timestamp güncellendi ama imza yenilenmemiş — istek reddedilir"
    finally:
        _geri_al(bfc)


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA İMZA + RETRY TESTLERİ — {len(testler)} test")
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
