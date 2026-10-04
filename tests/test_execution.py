# =========================================================
# ASTRA v50.0 — EMİR YÜRÜTME (EXECUTION) GÜVENLİK TESTLERİ
# Çalıştırma: python tests/test_execution.py
#
# Bu testler GERÇEK PARA yolundaki kodu korur. Denetimde
# execution_engine'in hiç test edilmediği tespit edilmişti —
# burası bir regresyonun doğrudan maddi zarara dönüştüğü yer.
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


# ─────────────────────────────────────────────
# 1. EN KRİTİK: Paper modda GERÇEK EMİR GİTMEMELİ
# ─────────────────────────────────────────────
def test_paper_modda_gercek_emir_gitmez():
    """KRİTİK GÜVENLİK: LIVE_TRADING=false iken borsaya emir GİTMEMELİ.

    Bu test bozulursa, test modunda sanılan bir bot gerçek para
    harcayabilir. Regresyon yakalamak için borsa fonksiyonlarını
    izleyip hiç çağrılmadığını doğruluyoruz."""
    from execution.execution_engine import ExecutionEngine
    import data.binance_futures_client as bfc

    cagrildi = {"market_ac": 0}
    orijinal = getattr(bfc, "futures_market_ac", None)

    def izleyici(*a, **kw):
        cagrildi["market_ac"] += 1
        raise AssertionError("PAPER MODDA GERÇEK EMİR GÖNDERİLDİ!")

    bfc.futures_market_ac = izleyici
    try:
        motor = ExecutionEngine()
        sonuc = motor.pozisyon_ac("BTCUSDT", "LONG", usdt=100,
                                   sl=49000, tp1=51000, tp2=52000)
        assert cagrildi["market_ac"] == 0, "Paper modda borsa çağrısı yapıldı!"
        assert sonuc.order_id == "PAPER", f"Paper işaretlemesi yok: {sonuc.order_id}"
        assert sonuc.basarili is True, "Paper işlem başarılı dönmeli"
    finally:
        if orijinal is not None:
            bfc.futures_market_ac = orijinal


def test_paper_sonuc_sifir_miktar():
    """Paper modda exec_miktar/exec_fiyat 0 olmalı (gerçek dolum yok)."""
    from execution.execution_engine import ExecutionEngine
    motor = ExecutionEngine()
    s = motor.pozisyon_ac("ETHUSDT", "SHORT", usdt=50, sl=3100, tp1=2900, tp2=2800)
    assert s.exec_miktar == 0, "Paper modda miktar 0 olmalı"
    assert s.exec_fiyat == 0, "Paper modda fiyat 0 olmalı"


# ─────────────────────────────────────────────
# 2. İSTATİSTİK VE RAPORLAMA
# ─────────────────────────────────────────────
def test_istatistik_sayaclari():
    """Açma girişimleri sayılmalı (teşhis için kritik)."""
    from execution.execution_engine import ExecutionEngine
    motor = ExecutionEngine()
    onceki = motor.istatistik.get("acma_girişim", 0)
    motor.pozisyon_ac("BTCUSDT", "LONG", 100, 49000, 51000, 52000)
    motor.pozisyon_ac("ETHUSDT", "LONG", 100, 2900, 3100, 3200)
    sonraki = motor.istatistik.get("acma_girişim", 0)
    assert sonraki == onceki + 2, f"Sayaç yanlış: {onceki} → {sonraki}"


def test_telegram_raporu_calisir():
    """telegram_raporu() çökmeden metin dönmeli."""
    from execution.execution_engine import ExecutionEngine
    motor = ExecutionEngine()
    r = motor.telegram_raporu()
    assert isinstance(r, str) and len(r) > 0, "Rapor boş"


# ─────────────────────────────────────────────
# 3. HATA DAYANIKLILIĞI: çökmek yerine güvenli başarısızlık
# ─────────────────────────────────────────────
def test_gecersiz_sembol_cokmez():
    """Geçersiz girdide motor ÇÖKMEMELİ, sonuç nesnesi dönmeli."""
    from execution.execution_engine import ExecutionEngine
    motor = ExecutionEngine()
    s = motor.pozisyon_ac("", "LONG", 100, 0, 0, 0)
    assert s is not None, "Sonuç None dönmemeli"
    assert hasattr(s, "basarili"), "ExecutionSonuc yapısı bozuk"


def test_negatif_usdt_cokmez():
    """Negatif tutar gibi anormal girdi motoru çökertmemeli."""
    from execution.execution_engine import ExecutionEngine
    motor = ExecutionEngine()
    s = motor.pozisyon_ac("BTCUSDT", "LONG", -100, 49000, 51000, 52000)
    assert s is not None and hasattr(s, "basarili")


# ─────────────────────────────────────────────
# 4. GLOBAL HTTP TIMEOUT (v44 — donma önleme)
# ─────────────────────────────────────────────
def test_global_timeout_uygulaniyor():
    """KRİTİK: Global timeout patch'i timeout'suz istekleri korumalı.

    Bu koruma olmadan bir ağ çağrısı sonsuza kadar bekleyip botu
    kilitleyebilir (v44 öncesi gerçek sorunuydu)."""
    import requests
    from core.http_guard import global_timeout_uygula

    yakalanan = {}
    orijinal = requests.Session.request

    def izleyici(self, method, url, **kwargs):
        yakalanan["timeout"] = kwargs.get("timeout")
        raise requests.exceptions.ConnectionError("test")

    requests.Session.request = izleyici
    try:
        global_timeout_uygula(connect=7, read=13)
        try:
            requests.get("http://astra-test.invalid")
        except Exception:
            pass
        assert yakalanan.get("timeout") is not None, (
            "Timeout'suz istek korumasız kaldı! Global timeout çalışmıyor.")
    finally:
        requests.Session.request = orijinal


def test_belirtilen_timeout_ezilmez():
    """Açıkça verilen timeout, global patch tarafından ezilmemeli."""
    import requests
    from core.http_guard import global_timeout_uygula
    global_timeout_uygula()

    yakalanan = {}
    orijinal = requests.Session.request

    def izleyici(self, method, url, **kwargs):
        yakalanan["timeout"] = kwargs.get("timeout")
        raise requests.exceptions.ConnectionError("test")

    requests.Session.request = izleyici
    try:
        try:
            requests.get("http://astra-test.invalid", timeout=42)
        except Exception:
            pass
        assert yakalanan.get("timeout") == 42, (
            f"Kullanıcı timeout'u ezildi: {yakalanan.get('timeout')}")
    finally:
        requests.Session.request = orijinal


# ─────────────────────────────────────────────
# 5. WATCHDOG (donma tespiti)
# ─────────────────────────────────────────────
def test_watchdog_heartbeat():
    """Watchdog heartbeat alınca sessiz süre sıfırlanmalı."""
    from engines.watchdog import Watchdog
    wd = Watchdog(max_silent=300)
    wd.heartbeat()
    d = wd.durum
    assert isinstance(d, dict), "Watchdog durum dict dönmeli"


def test_watchdog_thread_dump_cokmez():
    """v42 teşhis: thread dump çağrısı çökmemeli (alarm anında kullanılır)."""
    from engines.watchdog import Watchdog
    wd = Watchdog(max_silent=300)
    # Doğrudan çağır — exception fırlatmamalı
    wd._thread_dump_logla(123.0)


# ─────────────────────────────────────────────
# 6. VERİTABANI BAĞLANTI SIZINTISI (v49 düzeltmesi)
# ─────────────────────────────────────────────
def test_db_baglanti_sizmaz():
    """KRİTİK: DB işlemleri dosya tanıtıcısı sızdırmamalı.

    v49 öncesi conn.close() try/finally dışındaydı; hata durumunda
    bağlantı sızıyor, 7/24 çalışmada 'too many open files' oluyordu."""
    import tempfile
    os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
    from data.database import tablolari_olustur, sinyal_kaydet
    import gc

    tablolari_olustur()
    gc.collect()
    fd_dizin = f"/proc/{os.getpid()}/fd"
    if not os.path.exists(fd_dizin):
        return   # Linux dışı ortam — test atlanır
    onceki = len(os.listdir(fd_dizin))
    for _ in range(40):
        sinyal_kaydet("BTCUSDT", 50000.0, 5, "BUY")
    gc.collect()
    sonraki = len(os.listdir(fd_dizin))
    assert sonraki - onceki <= 2, (
        f"Bağlantı sızıntısı! 40 işlemde {sonraki - onceki} tanıtıcı arttı.")


def test_db_context_manager_hatada_kapatir():
    """Exception olsa bile bağlantı kapanmalı (context manager garantisi).

    sqlite Connection.close salt-okunur olduğu için, kapanmayı doğrudan
    izlemek yerine: blok sonrası bağlantının KULLANILAMAZ olduğunu
    doğruluyoruz (kapalı bağlantı ProgrammingError fırlatır)."""
    import tempfile, sqlite3
    os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
    from data.database import baglanti, tablolari_olustur
    tablolari_olustur()

    kacan_conn = None
    try:
        with baglanti() as conn:
            kacan_conn = conn
            raise ValueError("test hatası")
    except ValueError:
        pass

    assert kacan_conn is not None, "Bağlantı alınamadı"
    kapali = False
    try:
        kacan_conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        kapali = True
    assert kapali, "Exception sonrası bağlantı HÂLÂ AÇIK — sızıntı var!"


# ─────────────────────────────────────────────
# 7. v51 KRİTİK: SL koyulamazsa pozisyon KAPATILMALI
# ─────────────────────────────────────────────
def test_sl_koyulamazsa_pozisyon_kapatilir():
    """EN KRİTİK GÜVENLİK TESTİ: Stop-loss yerleştirilemezse pozisyon
    açık BIRAKILMAMALI.

    Korumasız kaldıraçlı pozisyon = likidasyon riski. Piyasa aleyhe
    dönerse zararı durduracak hiçbir mekanizma kalmaz. v51 öncesi kod
    SL hatasını sadece logluyor, pozisyonu açık bırakıyordu.

    Bu test mock borsa ile: market emri başarılı + SL başarısız
    senaryosunda futures_market_kapat çağrıldığını doğrular."""
    import data.binance_futures_client as bfc
    from execution.execution_engine import ExecutionEngine
    import config

    # Testi anlamlı kılmak için LIVE yolunu simüle et
    orijinal_live = getattr(__import__('execution.execution_engine',
                                        fromlist=['LIVE_TRADING']), 'LIVE_TRADING', False)
    import execution.execution_engine as ee

    cagrilar = {"kapat": 0, "sl": 0}
    yedek = {}
    for ad in ["futures_market_ac", "kaldirac_ayarla", "futures_stop_loss_koy",
               "futures_take_profit_koy", "futures_partial_tp_koy",
               "acik_futures_pozisyonlar", "futures_anlık_fiyat",
               "pozisyon_var_mi", "duplicate_kontrol", "futures_market_kapat"]:
        yedek[ad] = getattr(bfc, ad, None)

    def sahte_market_ac(*a, **kw):
        return {"orderId": 12345, "executedQty": "0.01", "avgPrice": "50000"}
    def sahte_sl_koy(*a, **kw):
        cagrilar["sl"] += 1
        raise RuntimeError("SL emri reddedildi (test)")
    def sahte_kapat(*a, **kw):
        cagrilar["kapat"] += 1
        return {"orderId": 999}

    bfc.futures_market_ac = sahte_market_ac
    bfc.kaldirac_ayarla = lambda *a, **kw: True
    bfc.futures_stop_loss_koy = sahte_sl_koy
    bfc.futures_take_profit_koy = lambda *a, **kw: {"orderId": 2}
    bfc.futures_partial_tp_koy = lambda *a, **kw: {"orderId": 3}
    bfc.acik_futures_pozisyonlar = lambda *a, **kw: []
    bfc.futures_anlık_fiyat = lambda *a, **kw: 50000.0
    bfc.pozisyon_var_mi = lambda *a, **kw: False
    bfc.duplicate_kontrol = lambda *a, **kw: True
    bfc.futures_market_kapat = sahte_kapat
    ee.LIVE_TRADING = True   # LIVE yolunu zorla

    try:
        motor = ExecutionEngine()
        sonuc = motor.pozisyon_ac("BTCUSDT", "LONG", usdt=100,
                                   sl=49000, tp1=51000, tp2=52000)
        assert cagrilar["sl"] >= 1, "SL koyma hiç denenmedi"
        assert cagrilar["kapat"] >= 1, (
            "SL koyulamadığı halde pozisyon KAPATILMADI! "
            "Korumasız pozisyon = likidasyon riski.")
        assert sonuc.basarili is False, "SL'siz işlem 'başarılı' sayılmamalı"
        assert sonuc.sl_aktif is False, "sl_aktif False olmalı"
    finally:
        ee.LIVE_TRADING = orijinal_live
        for ad, fn in yedek.items():
            if fn is not None:
                setattr(bfc, ad, fn)



# ─────────────────────────────────────────────
# 8. v51 FAIL-SAFE: SL/TP yön doğrulaması
# ─────────────────────────────────────────────
def _mock_borsa_kur(sl_koy_basarili=True):
    """Test için sahte borsa fonksiyonları kurar, yedek döner."""
    import data.binance_futures_client as bfc
    import execution.execution_engine as ee
    yedek = {ad: getattr(bfc, ad, None) for ad in [
        "futures_market_ac", "kaldirac_ayarla", "futures_stop_loss_koy",
        "futures_take_profit_koy", "futures_partial_tp_koy",
        "acik_futures_pozisyonlar", "futures_anlık_fiyat",
        "pozisyon_var_mi", "duplicate_kontrol", "futures_market_kapat"]}
    yedek["_LIVE"] = ee.LIVE_TRADING
    sayac = {"market_ac": 0, "kapat": 0}
    def market_ac(*a, **kw):
        sayac["market_ac"] += 1
        return {"orderId": 1, "executedQty": "0.01", "avgPrice": "50000"}
    bfc.futures_market_ac = market_ac
    bfc.kaldirac_ayarla = lambda *a, **kw: True
    bfc.futures_stop_loss_koy = (lambda *a, **kw: {"orderId": 2}) if sl_koy_basarili \
        else (lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("SL red")))
    bfc.futures_take_profit_koy = lambda *a, **kw: {"orderId": 3}
    bfc.futures_partial_tp_koy = lambda *a, **kw: {"orderId": 4}
    bfc.acik_futures_pozisyonlar = lambda *a, **kw: []
    bfc.futures_anlık_fiyat = lambda *a, **kw: 50000.0
    bfc.pozisyon_var_mi = lambda *a, **kw: False
    bfc.duplicate_kontrol = lambda *a, **kw: True
    def kapat(*a, **kw):
        sayac["kapat"] += 1
        return {"orderId": 9}
    bfc.futures_market_kapat = kapat
    ee.LIVE_TRADING = True
    return yedek, sayac

def _mock_borsa_geri_al(yedek):
    import data.binance_futures_client as bfc
    import execution.execution_engine as ee
    ee.LIVE_TRADING = yedek.pop("_LIVE")
    for ad, fn in yedek.items():
        if fn is not None:
            setattr(bfc, ad, fn)


def test_long_ters_sl_reddedilir():
    """KRİTİK: LONG'da SL fiyatın ÜSTÜNDEyse işlem AÇILMAMALI.

    Böyle bir SL pozisyon açılır açılmaz tetiklenir → her işlemde
    otomatik zarar. Emir gönderilmeden yakalanmalı."""
    from execution.execution_engine import ExecutionEngine
    yedek, sayac = _mock_borsa_kur()
    try:
        motor = ExecutionEngine()
        # Fiyat 50000, LONG ama SL 51000 (ÜSTTE = ters)
        s = motor.pozisyon_ac("BTCUSDT", "LONG", 100, sl=51000, tp1=52000, tp2=53000)
        assert s.basarili is False, "Ters SL'li işlem reddedilmeliydi"
        assert sayac["market_ac"] == 0, "Ters SL'e rağmen BORSAYA EMİR GİTTİ!"
    finally:
        _mock_borsa_geri_al(yedek)


def test_short_ters_sl_reddedilir():
    """KRİTİK: SHORT'ta SL fiyatın ALTINDAysa işlem AÇILMAMALI."""
    from execution.execution_engine import ExecutionEngine
    yedek, sayac = _mock_borsa_kur()
    try:
        motor = ExecutionEngine()
        # Fiyat 50000, SHORT ama SL 49000 (ALTTA = ters)
        s = motor.pozisyon_ac("BTCUSDT", "SHORT", 100, sl=49000, tp1=48000, tp2=47000)
        assert s.basarili is False, "Ters SL'li SHORT reddedilmeliydi"
        assert sayac["market_ac"] == 0, "Ters SL'e rağmen BORSAYA EMİR GİTTİ!"
    finally:
        _mock_borsa_geri_al(yedek)


def test_sifir_sl_reddedilir():
    """SL=0 (korumasız) işlem açılmamalı."""
    from execution.execution_engine import ExecutionEngine
    yedek, sayac = _mock_borsa_kur()
    try:
        motor = ExecutionEngine()
        s = motor.pozisyon_ac("BTCUSDT", "LONG", 100, sl=0, tp1=52000, tp2=53000)
        assert s.basarili is False, "SL=0 işlem reddedilmeliydi"
        assert sayac["market_ac"] == 0, "SL=0'a rağmen emir gitti!"
    finally:
        _mock_borsa_geri_al(yedek)


def test_dogru_sl_tp_gecer():
    """Doğru yönde SL/TP olan işlem NORMAL şekilde açılabilmeli.
    (Doğrulama fazla katı olmamalı — meşru işlemleri engellememeli.)"""
    from execution.execution_engine import ExecutionEngine
    yedek, sayac = _mock_borsa_kur(sl_koy_basarili=True)
    try:
        motor = ExecutionEngine()
        # Fiyat 50000, LONG, SL 49000 (altta ✓), TP 51000 (üstte ✓)
        s = motor.pozisyon_ac("BTCUSDT", "LONG", 100, sl=49000, tp1=51000, tp2=52000)
        assert sayac["market_ac"] >= 1, "Geçerli işlem engellendi (fazla katı doğrulama)"
        assert s.sl_aktif is True, "SL aktif olmalıydı"
    finally:
        _mock_borsa_geri_al(yedek)



# ─────────────────────────────────────────────
# 9. v52: Hayalet pozisyon + dolum kontrolleri
# ─────────────────────────────────────────────
def test_sifir_dolum_pozisyon_acmaz():
    """KRİTİK: Emir gönderilip HİÇ dolmadıysa (executedQty=0) işlem
    başarılı sayılmamalı ve SL koymaya çalışılmamalı.

    v52 öncesi kod sadece orderId'ye bakıyordu; dolmayan emirde
    var olmayan pozisyona SL koymaya çalışıyordu."""
    import data.binance_futures_client as bfc
    from execution.execution_engine import ExecutionEngine
    yedek, sayac = _mock_borsa_kur()
    sl_denendi = {"sayi": 0}
    def sl_izle(*a, **kw):
        sl_denendi["sayi"] += 1
        return {"orderId": 2}
    bfc.futures_stop_loss_koy = sl_izle
    # Emir gönderiliyor ama HİÇ dolmuyor
    bfc.futures_market_ac = lambda *a, **kw: {
        "orderId": 77, "executedQty": "0", "avgPrice": "0"}
    bfc.futures_emir_iptal = lambda *a, **kw: {"ok": True}
    try:
        motor = ExecutionEngine()
        s = motor.pozisyon_ac("BTCUSDT", "LONG", 100, sl=49000, tp1=51000, tp2=52000)
        assert s.basarili is False, "Dolmayan emir 'başarılı' sayıldı!"
        assert s.exec_miktar == 0, "Dolmayan emirde miktar 0 olmalı"
        assert sl_denendi["sayi"] == 0, (
            "Pozisyon yokken SL koymaya çalışıldı!")
    finally:
        _mock_borsa_geri_al(yedek)


def test_slippage_kapatilamazsa_uyarir():
    """KRİTİK: Slippage nedeniyle kapatma başarısız olursa, hata
    mesajı manuel müdahale gerektiğini BELİRTMELİ.

    v52 öncesi kapatma hatası sessizce yutuluyordu → hayalet pozisyon
    (sistem 'işlem yok' sanır, borsada korumasız pozisyon durur)."""
    import data.binance_futures_client as bfc
    from execution.execution_engine import ExecutionEngine
    import config
    yedek, sayac = _mock_borsa_kur()
    # Aşırı slippage üret: anlık fiyat 50000, dolum 60000 (%20 slippage)
    bfc.futures_market_ac = lambda *a, **kw: {
        "orderId": 88, "executedQty": "0.01", "avgPrice": "60000"}
    bfc.futures_anlık_fiyat = lambda *a, **kw: 50000.0
    # Kapatma HER ZAMAN başarısız
    def kapat_hata(*a, **kw):
        raise RuntimeError("borsa kapatma reddetti (test)")
    bfc.futures_market_kapat = kapat_hata
    try:
        motor = ExecutionEngine()
        motor._smart = None   # smart execution slippage kontrolünü atlar → market yolunu test et
        s = motor.pozisyon_ac("BTCUSDT", "LONG", 100, sl=49000, tp1=51000, tp2=52000)
        assert s.basarili is False, "Aşırı slippage'li işlem başarılı sayılmamalı"
        assert "MANUEL" in s.hata.upper(), (
            f"Kapatma başarısızken manuel müdahale uyarısı yok: {s.hata}")
    finally:
        _mock_borsa_geri_al(yedek)



# ─────────────────────────────────────────────
# 10. v53 KRİTİK: Çift emir önleme (idempotency)
# ─────────────────────────────────────────────
def test_retry_ayni_client_order_id_kullanir():
    """EN KRİTİK: POST emir retry'ında AYNI newClientOrderId kullanılmalı.

    SORUN: Emir gönderilir → Binance ALIR ve işler → yanıt dönerken
    timeout → kod tekrar gönderir → İKİ POZİSYON açılır. duplicate_kontrol
    emirden ÖNCE çalıştığı için bunu yakalayamaz.

    ÇÖZÜM: Aynı newClientOrderId ile ikinci istek borsa tarafından
    reddedilir → emir iki kez işlenmez."""
    import importlib, requests
    import data.binance_futures_client as bfc

    idler = []
    sayac = {"n": 0}
    orij_post, orij_get = bfc.requests.post, bfc.requests.get
    orij_key = bfc.BINANCE_API_KEY
    orij_secret = bfc.BINANCE_API_SECRET
    bfc.BINANCE_API_KEY = "test_key"
    bfc.BINANCE_API_SECRET = "test_secret"

    def sahte_post(url, params=None, headers=None, timeout=None, **kw):
        sayac["n"] += 1
        idler.append(params.get("newClientOrderId"))
        if sayac["n"] <= 2:
            raise requests.exceptions.Timeout("ağ koptu")
        class R:
            status_code = 200
            def json(self): return {"orderId": 1, "executedQty": "0.01"}
        return R()

    def sahte_get(*a, **kw):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"serverTime": int(__import__("time").time()*1000)}
        return R()

    bfc.requests.post = sahte_post
    bfc.requests.get = sahte_get
    try:
        bfc._futures_istek("POST", "/fapi/v1/order", {"symbol": "BTCUSDT", "side": "BUY"})
        assert len(idler) >= 2, "Retry gerçekleşmedi, test anlamsız"
        assert len(set(idler)) == 1, (
            f"ÇİFT EMİR RİSKİ! Retry'da {len(set(idler))} farklı ID kullanıldı — "
            f"her deneme yeni pozisyon açardı.")
    finally:
        bfc.requests.post, bfc.requests.get = orij_post, orij_get
        bfc.BINANCE_API_KEY, bfc.BINANCE_API_SECRET = orij_key, orij_secret


def test_get_istekleri_client_id_almaz():
    """GET (sorgu) isteklerine gereksiz newClientOrderId eklenmemeli."""
    import requests
    import data.binance_futures_client as bfc
    yakalanan = {}
    orij_get = bfc.requests.get
    orij_key, orij_secret = bfc.BINANCE_API_KEY, bfc.BINANCE_API_SECRET
    bfc.BINANCE_API_KEY = "test_key"; bfc.BINANCE_API_SECRET = "test_secret"

    def sahte_get(url, params=None, headers=None, timeout=None, **kw):
        if params and "serverTime" not in str(url):
            yakalanan.update(params)
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"serverTime": int(__import__("time").time()*1000)}
        return R()
    bfc.requests.get = sahte_get
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        assert "newClientOrderId" not in yakalanan, "GET isteğine emir ID'si eklendi"
    finally:
        bfc.requests.get = orij_get
        bfc.BINANCE_API_KEY, bfc.BINANCE_API_SECRET = orij_key, orij_secret



def test_kucuk_boyut_islem_acmaz():
    """v53: Minimum altı pozisyon boyutu tek noktadan engellenmeli.

    Yukarı katmanlar (negatif Kelly, düşük bakiye, damp çarpanları)
    0 veya çok küçük boyut üretebilir. main.py'de kontrol yoktu;
    0 USDT'lik emir borsaya gidip hata alırdı."""
    from execution.execution_engine import ExecutionEngine
    motor = ExecutionEngine()
    for tutar in (0, 0.5, 4.99):
        s = motor.pozisyon_ac("BTCUSDT", "LONG", tutar, 49000, 51000, 52000)
        assert s.basarili is False, f"{tutar}$ ile işlem açıldı (minimum 5$)"
        assert "küçük" in s.hata.lower(), f"Hata mesajı beklenmedik: {s.hata}"


def test_negatif_kelly_islem_acmaz():
    """v53: Negatif Kelly = matematiksel edge yok → 0 dönmeli.

    Eski kod uyarı basıp yine de 5$ pozisyon döndürüyordu."""
    from engines.risk_manager import RiskManager
    rm = RiskManager()
    # Kelly motorunu negatif dönecek şekilde taklit et
    orij = rm.kelly_engine.kelly_fraksiyon
    rm.kelly_engine.kelly_fraksiyon = lambda s: (-0.15, 0.35, 0.8, 50)
    try:
        usdt = rm.pozisyon_buyuklugu_hesapla(
            bakiye=1000, fiyat=50000, atr=500, win_rate=0.35, sembol="BTCUSDT")
        assert usdt == 0.0, (
            f"Negatif Kelly'de {usdt}$ pozisyon önerildi — işlem açılmamalıydı")
    finally:
        rm.kelly_engine.kelly_fraksiyon = orij



# ─────────────────────────────────────────────
# 11. v54: Kill switch yarış durumu (thread güvenliği)
# ─────────────────────────────────────────────
def test_killswitch_esamanli_sayac_guvenli():
    """KRİTİK: Kill switch sayacı thread-güvenli olmalı.

    Pozisyonlar farklı thread'lerde kapanır. Sayaç lock'suz artarsa
    eşzamanlı bildirimler kaybolur → 5 kayıp olmasına rağmen sayaç
    4'te kalıp kill switch TETİKLENMEYEBİLİR. Kill switch son savunma
    hattı olduğu için sayacın güvenilirliği kritiktir."""
    import threading
    from engines.kill_switch import HardKillSwitch
    ks = HardKillSwitch(max_consecutive_loss=50)
    threadler = [threading.Thread(
        target=lambda: ks.trade_sonucu_bildir(kazandi=False, pnl_usdt=-10))
        for _ in range(50)]
    for t in threadler: t.start()
    for t in threadler: t.join(timeout=5)
    assert ks._consecutive_loss == 50, (
        f"Yarış durumu! 50 bildirimden {50 - ks._consecutive_loss} kayboldu "
        f"(sayaç={ks._consecutive_loss})")
    assert ks.kontrol() is False, "50 kayıptan sonra kill switch tetiklenmedi"


def test_killswitch_deadlock_yok():
    """Lock düzeni deadlock üretmemeli (_durdur kendi lock'unu alır)."""
    import time
    from engines.kill_switch import HardKillSwitch
    ks = HardKillSwitch(max_consecutive_loss=3, max_api_errors=3,
                        max_ws_disconnects=3)
    t0 = time.time()
    for _ in range(5):
        ks.trade_sonucu_bildir(kazandi=False, pnl_usdt=-10)
        ks.api_hatasi_bildir()
        ks.ws_disconnect_bildir()
    assert time.time() - t0 < 2.0, "Deadlock şüphesi: çağrılar askıda kaldı"



# ─────────────────────────────────────────────
# 12. v55: DuplicateGuard eşzamanlılık
# ─────────────────────────────────────────────
def test_guard_lock_agda_bloklamaz():
    """KRİTİK EŞZAMANLILIK: Binance sorgusu LOCK DIŞINDA olmalı.

    Eskiden ağ çağrısı lock içindeydi → yavaş ağda (15s timeout) tüm
    thread'ler bloklanıyordu → ana döngü tıkanması → watchdog alarmı.
    Farklı semboller birbirini BEKLEMEMELİ."""
    import time, threading
    from execution.duplicate_guard import DuplicateGuard
    g = DuplicateGuard()
    g._binance_pozisyon_var = lambda s, y: (time.sleep(1.0), False)[1]

    def isci(sembol):
        with g.isle(sembol, "LONG"):
            pass

    t0 = time.time()
    tl = [threading.Thread(target=isci, args=(s,))
          for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")]
    for t in tl: t.start()
    for t in tl: t.join(timeout=10)
    sure = time.time() - t0
    assert sure < 2.0, (
        f"3 farklı sembol {sure:.1f}s sürdü — lock ağ çağrısında tutuluyor "
        f"(paralel olsaydı ~1s)")


def test_guard_ayni_sembol_duplicate_engeller():
    """Eşzamanlılık düzeltmesi duplicate korumasını BOZMAMALI."""
    import time, threading
    from execution.duplicate_guard import DuplicateGuard
    g = DuplicateGuard()
    g._binance_pozisyon_var = lambda s, y: False
    izinler = []
    def isci():
        with g.isle("BTCUSDT", "LONG") as izin:
            izinler.append(izin)
            time.sleep(0.2)
    tl = [threading.Thread(target=isci) for _ in range(5)]
    for t in tl: t.start()
    for t in tl: t.join(timeout=10)
    assert sum(1 for i in izinler if i) == 1, (
        f"5 eşzamanlı istekten {sum(1 for i in izinler if i)} tanesi geçti — "
        f"duplicate koruması bozuk!")


def test_guard_sorgu_hatasinda_engeller():
    """FAIL-SAFE: Pozisyon sorgusu başarısızsa işleme İZİN VERİLMEMELİ.

    v55 TEST DÜZELTMESİ — ÖNEMLİ:
    Bu test eskiden `g._binance_pozisyon_var`'ı DOĞRUDAN mock'layıp hata
    fırlatıyordu. Ancak GERÇEK hata tam da o metodun İÇİNDEYDİ:
    kendi `except Exception: return False` bloğuyla hatayı yutup
    "pozisyon yok" diyor, yani işleme İZİN VERİYORDU.
    Testi bu şekilde yazmak hatalı katmanı tamamen ATLIYOR → test geçiyor,
    bug yaşamaya devam ediyor (sahte güven).

    Artık gerçek zincir test ediliyor: en alttaki ağ fonksiyonu
    (acik_futures_pozisyonlar) hata fırlatıyor ve fail-safe davranışın
    guard'a kadar DOĞRU şekilde yayıldığı doğrulanıyor.
    """
    import data.binance_futures_client as bfc
    from execution.duplicate_guard import DuplicateGuard

    orijinal = bfc.acik_futures_pozisyonlar
    def patlayan(*a, **kw):
        raise ConnectionError("ağ kesintisi simülasyonu")
    bfc.acik_futures_pozisyonlar = patlayan
    try:
        g = DuplicateGuard()
        with g.isle("BTCUSDT", "LONG") as izin:
            assert izin is False, (
                "Ağ hatasında işleme İZİN VERİLDİ — fail-safe ihlali! "
                "(_binance_pozisyon_var hatayı yutuyor olabilir)")
    finally:
        bfc.acik_futures_pozisyonlar = orijinal


def test_guard_strict_parametresi_kullaniliyor():
    """Guard, pozisyon sorgusunu strict=True ile yapmalı.

    strict=False olursa ağ hatasında [] döner ve guard bunu
    'hiç pozisyon yok' sanıp fail-OPEN olur.
    """
    import data.binance_futures_client as bfc
    from execution.duplicate_guard import DuplicateGuard

    cagri_kayit = {}
    orijinal = bfc.acik_futures_pozisyonlar
    def izleyici(*a, **kw):
        cagri_kayit["strict"] = kw.get("strict", (a[0] if a else False))
        return []
    bfc.acik_futures_pozisyonlar = izleyici
    try:
        g = DuplicateGuard()
        with g.isle("BTCUSDT", "LONG"):
            pass
        assert cagri_kayit.get("strict") is True, (
            f"Guard strict=True kullanmıyor (strict={cagri_kayit.get('strict')}) "
            f"— ağ hatasında fail-open olur!")
    finally:
        bfc.acik_futures_pozisyonlar = orijinal


def test_pozisyon_sorgusu_strict_hatayi_yukseltir():
    """acik_futures_pozisyonlar(strict=True) hata durumunda [] DÖNMEMELİ.

    'Sıfır pozisyon var' ile 'sorgulayamadım' aynı şey değildir. Bu ayrım
    olmadan reconciler/state_sync ağ kesintisinde TÜM pozisyonları
    'kapandı' sanıp izlemeyi bırakır.
    """
    import data.binance_futures_client as bfc
    from utils.exceptions import NetworkError

    orijinal = bfc._futures_istek
    def patlayan(*a, **kw):
        raise NetworkError("ağ kesintisi", "test")
    bfc._futures_istek = patlayan
    try:
        # strict=False (varsayılan): geriye dönük uyumluluk — [] döner
        assert bfc.acik_futures_pozisyonlar() == [], \
            "strict=False geriye dönük uyumluluğu bozulmuş"
        # strict=True: istisna YÜKSELMELİ
        try:
            bfc.acik_futures_pozisyonlar(strict=True)
            raise AssertionError(
                "strict=True hata durumunda istisna YÜKSELTMEDİ — "
                "fail-open riski devam ediyor!")
        except NetworkError:
            pass   # beklenen
    finally:
        bfc._futures_istek = orijinal


# ─────────────────────────────────────────────
# Bağımsız çalıştırma
# ─────────────────────────────────────────────
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA EXECUTION & GÜVENLİK TESTLERİ — {len(testler)} test")
    print(f"{'='*56}")
    basari, hata = 0, 0
    for t in testler:
        try:
            t()
            print(f"  [GEÇTİ]  {t.__name__}")
            basari += 1
        except AssertionError as e:
            print(f"  [HATA]   {t.__name__}")
            print(f"           → {str(e)[:70]}")
            hata += 1
        except Exception as e:
            print(f"  [ÇÖKTÜ]  {t.__name__}: {type(e).__name__}: {str(e)[:50]}")
            hata += 1
    print(f"{'='*56}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'='*56}\n")
    sys.exit(0 if hata == 0 else 1)
