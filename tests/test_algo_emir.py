# =========================================================
# ASTRA v57 — ALGO (KOŞULLU) EMİR TESTLERİ
# Çalıştırma: python tests/test_algo_emir.py
#
# NE KORUYOR:
#   Koşullu emirler (STOP_MARKET / TAKE_PROFIT_MARKET / TRAILING_STOP_MARKET)
#   `/fapi/v1/order`'dan **Algo Service**'e taşındı. Eski endpoint artık
#   `-4120 "Please use the Algo Order API endpoints instead."` döndürüyor.
#   Şema testnet'te deneyerek çıkarıldı → BINANCE_ALGO_EMIR_SEMASI.md
#
# ⚠️ EN TEHLİKELİ TARAF — sadece endpoint değiştirmek YETMEZ:
#   Algo emirleri klasik `GET /fapi/v1/openOrders` listesinde GÖRÜNMÜYOR.
#   "SL var mı?" kontrolü klasik listeye bakarsa SL'i göremez →
#     • order_reconciler her turda gereksiz acil SL koyar (emir birikir)
#     • failsafe pozisyonu korumasız sanıp KAPATIR
#     • orphan temizliği eski SL/TP'leri hiç silmez
#   Bu, §5.1 fail-open deseninin yeni yüzü.
#
# §4.1: Muhafız testlerinin yanına KONTROL testleri yazıldı — "hep SL var
#   der" gibi bozuk bir kod da muhafızları geçerdi.
# =========================================================
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# v57: ÜRETİM durum dosyalarına yazmayı engelle.
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "test")
os.environ.setdefault("BINANCE_API_SECRET", "test")


def _yakala(bfc):
    """_futures_istek'i sahteyle değiştirip çağrıları kaydet."""
    kayit = []

    def sahte(method, path, params=None):
        kayit.append({"method": method, "path": path, "params": dict(params or {})})
        if "openAlgoOrders" in path or "openOrders" in path:
            return []
        if "algoOrder" in path:
            return {"algoId": 12345, "orderType": (params or {}).get("type"),
                    "triggerPrice": (params or {}).get("triggerPrice")}
        return {"orderId": 999}

    orij = bfc._futures_istek
    bfc._futures_istek = sahte
    return kayit, orij


# ─────────────────────────────────────────────
# 1. MUHAFIZ — koşullu emirler ALGO endpoint'ine gitmeli
# ─────────────────────────────────────────────
def test_stop_loss_algo_endpointine_gider():
    """SL artık /fapi/v1/algoOrder'a gitmeli, /fapi/v1/order'a DEĞİL.

    Eski yol `-4120` ile reddediliyor; oraya giderse SL HİÇ konulamaz.
    """
    import data.binance_futures_client as bfc
    kayit, orij = _yakala(bfc)
    try:
        bfc.futures_stop_loss_koy("BTCUSDT", "LONG", 60000.0)
    finally:
        bfc._futures_istek = orij

    postlar = [k for k in kayit if k["method"] == "POST"]
    assert postlar, "Hiç POST yapılmadı"
    yol = postlar[-1]["path"]
    assert "algoOrder" in yol, (
        f"SL '{yol}' adresine gitti — algo endpoint'i değil. "
        f"Eski yol -4120 ile reddedilir, stop-loss KONULAMAZ.")


def test_stop_loss_dogru_parametreleri_gonderir():
    """algoType=CONDITIONAL ve triggerPrice ZORUNLU; stopPrice artık yok."""
    import data.binance_futures_client as bfc
    kayit, orij = _yakala(bfc)
    try:
        bfc.futures_stop_loss_koy("BTCUSDT", "LONG", 60000.0)
    finally:
        bfc._futures_istek = orij

    p = [k for k in kayit if k["method"] == "POST"][-1]["params"]
    assert p.get("algoType") == "CONDITIONAL", (
        f"algoType eksik/yanlış: {p.get('algoType')} — "
        f"Binance -1102 'algotype eksik' döndürür")
    assert "triggerPrice" in p, (
        "triggerPrice yok — algo endpoint'i stopPrice KABUL ETMEZ "
        "(-1102 'triggerprice was not sent')")
    assert "stopPrice" not in p, (
        "stopPrice hâlâ gönderiliyor — eski şema kalıntısı")
    assert p.get("type") == "STOP_MARKET", f"type yanlış: {p.get('type')}"


def test_take_profit_algo_endpointine_gider():
    """TP de aynı yola gitmeli."""
    import data.binance_futures_client as bfc
    kayit, orij = _yakala(bfc)
    try:
        bfc.futures_take_profit_koy("BTCUSDT", "LONG", 70000.0)
    finally:
        bfc._futures_istek = orij

    p = [k for k in kayit if k["method"] == "POST"][-1]
    assert "algoOrder" in p["path"], f"TP '{p['path']}' adresine gitti"
    assert p["params"].get("algoType") == "CONDITIONAL"
    assert "triggerPrice" in p["params"]


def test_trailing_closeposition_KULLANMAZ():
    """TRAILING_STOP_MARKET + closePosition algo'da REDDEDİLİYOR.

    Testnet: -4136 "Target strategy invalid for orderType
    TRAILING_STOP_MARKET,closePosition true". Naif taşıma trailing stop'u
    sessizce ölü bırakırdı — her çağrı hata döner, üst katman None görür.
    """
    import data.binance_futures_client as bfc
    kayit, orij = _yakala(bfc)
    orij_poz = bfc.acik_futures_pozisyonlar
    bfc.acik_futures_pozisyonlar = lambda *a, **kw: [
        {"sembol": "BTCUSDT", "yon": "LONG", "miktar": 0.01}]
    try:
        bfc.futures_trailing_stop_koy("BTCUSDT", "LONG", 1.5)
    finally:
        bfc._futures_istek = orij
        bfc.acik_futures_pozisyonlar = orij_poz

    postlar = [k for k in kayit if k["method"] == "POST"]
    assert postlar, "Trailing stop hiç gönderilmedi"
    p = postlar[-1]["params"]
    assert "closePosition" not in p, (
        "trailing stop closePosition gönderiyor — Binance -4136 ile reddeder, "
        "trailing koruma HİÇ KURULMAZ")
    assert "quantity" in p, "closePosition yerine quantity verilmeli"


# ─────────────────────────────────────────────
# 2. MUHAFIZ — SL görünürlüğü (en kritik)
# ─────────────────────────────────────────────
def test_koruma_emirleri_algo_listesini_de_okur():
    """koruma_emirleri() İKİ kaynağı da sorgulamalı.

    Yalnızca klasik listeye bakarsa SL 'yok' görünür → reconciler her turda
    acil SL koyar, failsafe pozisyonu kapatır.
    """
    import data.binance_futures_client as bfc
    kayit, orij = _yakala(bfc)
    try:
        bfc.koruma_emirleri("BTCUSDT")
    finally:
        bfc._futures_istek = orij

    yollar = " ".join(k["path"] for k in kayit)
    assert "openOrders" in yollar, "klasik emir listesi sorgulanmadı"
    assert "openAlgoOrders" in yollar, (
        "ALGO emir listesi sorgulanmadı — SL görünmez, fail-open oluşur")


def test_koruma_emirleri_algo_kaydini_normalize_eder():
    """Algo kaydı klasik biçime çevrilmeli (type/orderId/_algo)."""
    import data.binance_futures_client as bfc

    def sahte(method, path, params=None):
        if "openAlgoOrders" in path:
            return [{"algoId": 777, "orderType": "STOP_MARKET", "side": "SELL"}]
        return []

    orij = bfc._futures_istek
    bfc._futures_istek = sahte
    try:
        k = bfc.koruma_emirleri("BTCUSDT")
    finally:
        bfc._futures_istek = orij

    assert len(k) == 1, f"beklenen 1 emir, gelen {len(k)}"
    e = k[0]
    assert e["type"] == "STOP_MARKET", (
        f"orderType→type normalize edilmemiş: {e.get('type')} — mevcut kod "
        f"e.get('type') kullanıyor, SL'i tanıyamaz")
    assert e["orderId"] == 777, "algoId→orderId normalize edilmemiş"
    assert e["_algo"] is True, "_algo işareti yok — iptal yolu seçilemez"


def test_strict_sorgu_hatasinda_istisna_yukseltir():
    """strict=True iken sorgu hatası SESSİZCE [] dönmemeli.

    'Sorgulayamadım' ile 'SL yok' aynı şey değildir (§5.1). Sessiz [] dönüşü
    pozisyonu korumasız sanıp kapatmaya yol açar.
    """
    import data.binance_futures_client as bfc
    from utils.exceptions import NetworkError

    def patla(method, path, params=None):
        raise NetworkError("ağ koptu", path)

    orij = bfc._futures_istek
    bfc._futures_istek = patla
    try:
        hata_geldi = False
        try:
            bfc.acik_algo_emirler("BTCUSDT", strict=True)
        except NetworkError:
            hata_geldi = True
        assert hata_geldi, (
            "strict=True iken ağ hatası yutuldu ve [] döndü — "
            "'SL yok' sanılır, fail-open")
    finally:
        bfc._futures_istek = orij


# ─────────────────────────────────────────────
# 3. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_strict_kapaliyken_bos_liste_doner():
    """strict=False iken hata yutulup [] dönmeli.

    Yukarıdaki test yalnızca "istisna atıyor" diyor; bu test, davranışın
    strict bayrağına GERÇEKTEN bağlı olduğunu kanıtlar. Aksi halde "her
    zaman patla" gibi bozuk bir kod da o testi geçerdi.
    """
    import data.binance_futures_client as bfc
    from utils.exceptions import NetworkError

    def patla(method, path, params=None):
        raise NetworkError("ağ koptu", path)

    orij = bfc._futures_istek
    bfc._futures_istek = patla
    try:
        sonuc = bfc.acik_algo_emirler("BTCUSDT", strict=False)
        assert sonuc == [], f"strict=False iken [] beklenirdi, gelen: {sonuc}"
    finally:
        bfc._futures_istek = orij


def test_kontrol_bos_algo_listesi_sl_yok_demek():
    """Gerçekten SL yoksa koruma_emirleri BOŞ dönmeli.

    "Her zaman SL var de" gibi bozuk bir kod yukarıdaki muhafızları geçerdi.
    """
    import data.binance_futures_client as bfc

    orij = bfc._futures_istek
    bfc._futures_istek = lambda *a, **kw: []
    try:
        k = bfc.koruma_emirleri("BTCUSDT")
        assert k == [], f"emir yokken boş liste beklenirdi: {k}"
    finally:
        bfc._futures_istek = orij


def test_kontrol_idempotency_algo_yolunda_da_var():
    """Algo POST'una clientAlgoId eklenmeli.

    `"/order" in "/fapi/v1/algoOrder"` FALSE döner — v53 idempotency
    koruması algo yolunda SESSİZCE devre dışı kalıyordu. Ağ timeout'u +
    retry İKİ stop-loss koyabilirdi.
    """
    import data.binance_futures_client as bfc
    kayit, orij = _yakala(bfc)
    try:
        bfc.futures_stop_loss_koy("BTCUSDT", "LONG", 60000.0)
    finally:
        bfc._futures_istek = orij
    # _yakala _futures_istek'i komple değiştirdiği için idempotency kodu
    # çalışmaz; bunun yerine KAYNAK düzeyinde doğrula.
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "data", "binance_futures_client.py"),
              encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))
    assert "clientAlgoId" in kod, "algo idempotency anahtarı hiç kullanılmıyor"
    assert "_algo_endpointi" in kod, (
        "algo endpoint'i idempotency kontrolünde ayrılmamış — "
        "çift stop-loss riski")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA ALGO EMİR TESTLERİ — {len(testler)} test")
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
