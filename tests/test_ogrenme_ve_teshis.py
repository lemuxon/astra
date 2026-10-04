# =========================================================
# ASTRA — ÖĞRENME + TEŞHİS MUHAFIZLARI (v58, K-63..K-68 + K-70)
# Çalıştırma: python tests/test_ogrenme_ve_teshis.py
#
# 2026-09-06/09 denetiminde bulunan yedi sessiz hatayı kilitler:
#   K-63  Retry uykusundan sonra BAYAT timestamp → sahte "-1021"
#   K-64  Online öğrenme etiketi uydurma (aynı bar tekrar tekrar "0")
#   K-65  Online model durumu diske HİÇ yazılmıyordu
#   K-66  Veto sayacı yalnızca canlı yolda → /neden paper'da kör
#   K-67  Balina dedektörü ölüyken "aktif" görünüyordu
#   K-68  Balina proxy'si gerçek veriye bağlandı; global sabit skordan çıktı
#   K-70  Online model dizini izolasyona uymuyordu (test → üretim sızıntısı)
#
# ⚠️ §4.1: Yeşil test kanıt değildir. Her veto testinin yanında bir
# KONTROL testi var — kapı kaldırıldığında testin gerçekten kırmızıya
# döndüğü, düzeltmeler tek tek geri alınarak (mutasyon) doğrulandı.
# Ağa çıkılmaz; requests ve zaman mock'lanır.
# =========================================================
import sys, os, warnings, hmac, hashlib
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()

os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

from urllib.parse import urlencode

TEST_SECRET = "test_api_secret_abcdefghijklmnop"


# ═════════════════════════════════════════════════════════
# K-64 — ONLINE ÖĞRENME ETİKETİ
# ═════════════════════════════════════════════════════════
def test_ayni_bar_tekrar_ogretilmez():
    """Aynı kapanmış bar ikinci kez etiket ÜRETMEMELİ.

    Kırıldığında: 4h barda tur ~1 dk'da döndüğü için model, sabit
    `son_close` ile ~288 kez "yükselmedi (0)" öğrenir ve
    P(yükseliş)→0 verir; bu güvene %10-35 ağırlıkla karışır.
    """
    from engines.online_learner import etiket_uret
    assert etiket_uret("bar_1", "bar_1", 110.0, 100.0) is None, (
        "Aynı bar için etiket üretildi — uydurma '0' etiketleri geri geldi "
        "(K-64). Online model 'fiyat asla yükselmez'i öğrenir.")


def test_yeni_bar_gercek_etiket_uretir():
    """KONTROL: bar gerçekten değiştiyse etiket ÜRETİLMELİ.

    Bu test olmadan K-64 düzeltmesi "her zaman None döndür" diye
    bozulabilir ve öğrenme tamamen durur — üstteki test yine geçerdi.
    """
    from engines.online_learner import etiket_uret
    assert etiket_uret("bar_2", "bar_1", 110.0, 100.0) == 1, \
        "Yeni barda yükseliş etiketi üretilmedi — öğrenme tamamen durdu"
    assert etiket_uret("bar_2", "bar_1", 90.0, 100.0) == 0, \
        "Yeni barda düşüş etiketi üretilmedi"


def test_etiket_degerden_degil_bar_kimliginden_bakar():
    """İki farklı bar AYNI fiyattan kapanabilir; o meşru '0' kaybolmamalı."""
    from engines.online_learner import etiket_uret
    assert etiket_uret("bar_2", "bar_1", 100.0, 100.0) == 0, (
        "Aynı fiyatla kapanan yeni bar atlandı — etikete değere göre "
        "bakılıyor, bar kimliğine göre değil")


def test_ilk_turda_etiket_yok():
    """Referans yokken uydurma etiket üretilmemeli (fail-closed)."""
    from engines.online_learner import etiket_uret
    assert etiket_uret("bar_1", None, 110.0, 100.0) is None
    assert etiket_uret(None, "bar_1", 110.0, 100.0) is None
    assert etiket_uret("bar_2", "bar_1", 110.0, 0) is None, \
        "Referans fiyat 0 iken etiket üretildi"


# ═════════════════════════════════════════════════════════
# K-65 — ONLINE MODEL KALICILIĞI
# ═════════════════════════════════════════════════════════
def test_her_egitimde_diske_yazilir():
    """Gerçek bir eğitim adımı olduğunda durum KAYDEDİLMELİ.

    Kırıldığında: `saved_models/online/` boş kalır (2026-09-06'da
    öyleydi), her yeniden başlatmada sayaç 0'a döner ve blend ağırlığı
    `egitim < 50` dalında 0.1'e çakılı kalır — öğrenme birikmez.
    """
    from engines.online_learner import OnlineLearner, RIVER_AVAILABLE
    if not RIVER_AVAILABLE:
        return   # river yoksa test anlamsız
    ol = OnlineLearner("TESTUSDT")
    kayit = {"n": 0}
    ol._kaydet = lambda: kayit.__setitem__("n", kayit["n"] + 1)
    feats = {"a": 1.0, "b": 2.0}
    ol.guncelle_ve_tahmin(feats, None, 100.0)      # ilk tur: _son_x doluyor
    ol.guncelle_ve_tahmin(feats, 1, 101.0)         # gerçek eğitim adımı
    assert kayit["n"] >= 1, (
        "Eğitim adımı diske yazılmadı — bot yeniden başlayınca öğrenilen "
        "her şey kaybolur (K-65)")


def test_online_model_uretim_dizinine_yazmaz():
    """Testler ÜRETİM `saved_models/online/` dizinine YAZMAMALI (K-70).

    `_ONLINE_MODEL_DIR` sabit koduydu ve `tests/izolasyon.py`'nin
    MODEL_DIR yönlendirmesini görmüyordu. KANIT: test paketi her
    koşuşta `online_TESTLEARN.pkl` üretiyordu (dosya tarihi her koşuda
    yenileniyordu). K-1 ve K-21 ile aynı sınıf; K-65 (her eğitimde
    kaydet) sızıntıyı büyütmüştü.
    """
    import os
    from engines.online_learner import _online_dizin
    dizin = os.path.abspath(_online_dizin())
    model_dir = os.environ.get("MODEL_DIR")
    assert model_dir, "izole_et() MODEL_DIR ayarlamamış (test kurulumu hatalı)"
    assert dizin.startswith(os.path.abspath(model_dir)), (
        f"Online modeller {dizin} altına yazılıyor — MODEL_DIR "
        f"({model_dir}) yönlendirmesi ETKİSİZ, üretim kirleniyor (K-70)")


def test_etiketsiz_turda_egitim_sayaci_artmaz():
    """KONTROL: etiket None ise eğitim SAYILMAMALI.

    Bu olmadan "her turda eğit" regresyonu (K-64) fark edilmez.
    """
    from engines.online_learner import OnlineLearner, RIVER_AVAILABLE
    if not RIVER_AVAILABLE:
        return
    ol = OnlineLearner("TESTUSDT2")
    feats = {"a": 1.0, "b": 2.0}
    ol.guncelle_ve_tahmin(feats, None, 100.0)
    once = ol._egitim_sayisi
    for _ in range(5):
        ol.guncelle_ve_tahmin(feats, None, 100.0)
    assert ol._egitim_sayisi == once, (
        "Etiketsiz 5 turda eğitim sayacı arttı "
        f"({once} → {ol._egitim_sayisi}) — model uydurma etiketle eğitiliyor")


# ═════════════════════════════════════════════════════════
# K-66 — VETO SAYACI PAPER YOLUNDA
# ═════════════════════════════════════════════════════════
def test_paper_yolu_veto_sayaci_kullanir():
    """Paper reddi teşhis sayacına DÜŞMELİ.

    Kırıldığında: /neden ve panel paper modda kalıcı olarak
    "henüz işlem denemesi yok" der — oysa logda binlerce red vardır
    (ölçüm: 2026-09-04..06 arası 1347 red satırı).
    """
    import inspect
    from engines import paper_trading
    kaynak = inspect.getsource(paper_trading)
    assert "_veto_kaydet" in kaynak, \
        "paper_trading.py veto sayacını hiç çağırmıyor (K-66)"
    from core.teshis import veto_ozet
    once = veto_ozet()["toplam_red"]
    motor = paper_trading.PaperTrader.__new__(
        paper_trading.PaperTrader)
    sonuc = {"sembol": "TESTUSDT", "ai_score": 0, "confidence": 1}
    gecti = paper_trading.PaperTrader._sinyal_kalitesi_gecer(
        motor, sonuc, "LONG")
    sonra = veto_ozet()["toplam_red"]
    assert gecti is False, "Güven eşiği geçirilmemeliydi (test kurulumu hatalı)"
    assert sonra == once + 1, (
        f"Paper reddi sayaca yazılmadı ({once} → {sonra}) — /neden kör kalır")


def test_cikis_reddi_giris_sayacina_yazilmaz():
    """KONTROL: ÇIKIŞ yolunun reddi giriş sayacına DÜŞMEMELİ.

    `_sinyal_kalitesi_gecer` hem açılış (`_filtre_gec`) hem kapanış
    (`_cikis_gecerli`) yolundan çağrılıyor. Ayrım yapılmazsa
    "pozisyon kapatılmadı" redleri "pozisyon açılmadı" diye sayılır;
    /neden'in açılma oranı paydası şişer ve teşhis yanlış yeri
    gösterir — K-56 ile aynı sınıf hata.

    ⚠️ `_sinyal_kalitesi_gecer(..., sayacli=False)` çağırmak YETMEZ —
    o yalnızca mekanizmayı sınar. Asıl risk `_cikis_gecerli`'nin bu
    bayrağı geçirmeyi UNUTMASI (K-29 tuzağı), bu yüzden ÇIKIŞ YOLU
    doğrudan sürülüyor.
    """
    from engines import paper_trading
    from core.teshis import veto_ozet
    motor = paper_trading.PaperTrader.__new__(paper_trading.PaperTrader)
    sonuc = {"sembol": "TESTUSDT", "ai_score": 0, "confidence": 1}
    once = veto_ozet()["toplam_red"]
    gecti = paper_trading.PaperTrader._cikis_gecerli(motor, sonuc, "SHORT")
    sonra = veto_ozet()["toplam_red"]
    assert gecti is False, "Zayıf sinyal pozisyonu kapatabildi (kurulum hatalı)"
    assert sonra == once, (
        f"Çıkış reddi giriş sayacına yazıldı ({once} → {sonra}) — "
        "/neden 'neden açılmıyor' sorusuna kapanış verisiyle cevap verir")


def test_paper_gecerli_sinyal_veto_yazmaz():
    """KONTROL: geçen sinyal sayaca red YAZMAMALI.

    Bu olmadan "_veto_kaydet'i her çağrıya koy" regresyonu sayacı
    anlamsız kılar ama üstteki test yine geçer.
    """
    from engines import paper_trading
    from core.teshis import veto_ozet
    motor = paper_trading.PaperTrader.__new__(
        paper_trading.PaperTrader)
    sonuc = {"sembol": "TESTUSDT", "ai_score": 99, "confidence": 100}
    once = veto_ozet()["toplam_red"]
    gecti = paper_trading.PaperTrader._sinyal_kalitesi_gecer(
        motor, sonuc, "LONG")
    sonra = veto_ozet()["toplam_red"]
    assert gecti is True, "Temiz sinyal reddedildi (test kurulumu hatalı)"
    assert sonra == once, \
        f"Geçen sinyal için red sayıldı ({once} → {sonra}) — sayaç anlamsızlaşır"


# ═════════════════════════════════════════════════════════
# K-63 — RETRY UYKUSUNDAN SONRA TAZE TIMESTAMP
# ═════════════════════════════════════════════════════════
class _Yanit:
    def __init__(self, status=200, govde=None, headers=None, metin=""):
        self.status_code = status
        self._govde = govde if govde is not None else {}
        self.headers = headers or {}
        self.text = metin or ""

    def json(self):
        return self._govde


class _Kayitci:
    def __init__(self, yanitlar):
        self.yanitlar, self.istekler = list(yanitlar), []

    def __call__(self, url, params=None, headers=None, timeout=None, **kw):
        self.istekler.append({"params": dict(params or {})})
        return self.yanitlar.pop(0) if self.yanitlar else _Yanit(200, {})


def _bfc_hazirla(yanitlar):
    """bfc'yi mock'la; uyku SANAL zamanı ilerletir (bayatlığı ölçmek için)."""
    import data.binance_futures_client as bfc
    bfc._eski = (bfc.requests.get, bfc.requests.post, bfc.BINANCE_API_SECRET,
                 bfc.BINANCE_API_KEY, bfc.time.sleep, bfc.time.time,
                 bfc._sunucu_zaman_senkronize)
    bfc.BINANCE_API_SECRET, bfc.BINANCE_API_KEY = TEST_SECRET, "test_key"
    kay = _Kayitci(yanitlar)
    bfc.requests.get = kay
    sanal = {"t": 1_700_000_000.0}
    bfc.time.sleep = lambda sn: sanal.__setitem__("t", sanal["t"] + sn)
    bfc.time.time = lambda: sanal["t"]
    bfc._sunucu_zaman_senkronize = lambda: 0
    return bfc, kay, sanal


def _bfc_geri(bfc):
    (bfc.requests.get, bfc.requests.post, bfc.BINANCE_API_SECRET,
     bfc.BINANCE_API_KEY, bfc.time.sleep, bfc.time.time,
     bfc._sunucu_zaman_senkronize) = bfc._eski


def test_429_uykusundan_sonra_timestamp_tazelenir():
    """Rate-limit uykusundan sonra timestamp YENİDEN damgalanmalı.

    ÖLÇÜLEN VAKA (2026-09-06 logs/astra.log):
        15:55:45  429 → 15 sn bekleniyor
        15:56:01  -1021 "outside of recvWindow"
    Timestamp imzalanıp 15 sn bekletilince recvWindow'u (10 sn) aşıyordu.
    Bot bunu SAAT KAYMASI sanıp offset yeniliyordu; oysa yerel saat
    Binance'ten yalnızca +25 ms sapıyor (bağımsız ölçüm).
    """
    bfc, kay, sanal = _bfc_hazirla([
        _Yanit(429, {}, headers={"Retry-After": "15"}, metin="rate limit"),
        _Yanit(200, {"orderId": 1}),
    ])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        assert len(kay.istekler) == 2, "429 sonrası tekrar denenmedi"
        t1 = int(kay.istekler[0]["params"]["timestamp"])
        t2 = int(kay.istekler[1]["params"]["timestamp"])
        assert t2 - t1 >= 15000, (
            f"Uykudan sonra AYNI timestamp gönderildi (fark {t2 - t1} ms). "
            "15 sn uyku + 10 sn recvWindow → Binance -1021 döndürür (K-63)")
    finally:
        _bfc_geri(bfc)


def test_tazelenen_istek_yeniden_imzalanir():
    """KONTROL: timestamp değişince imza da GEÇERLİ olmalı.

    Yalnızca timestamp'i güncelleyip imzayı bırakmak -1022
    (Signature not valid) üretir — hata sınıfı değişir, sorun sürer.
    """
    bfc, kay, sanal = _bfc_hazirla([
        _Yanit(429, {}, headers={"Retry-After": "15"}),
        _Yanit(200, {"orderId": 2}),
    ])
    try:
        bfc._futures_istek("GET", "/fapi/v3/balance", {})
        p = dict(kay.istekler[1]["params"])
        imza = p.pop("signature")
        beklenen = hmac.new(TEST_SECRET.encode(), urlencode(p).encode(),
                            hashlib.sha256).hexdigest()
        assert imza == beklenen, \
            "Taze timestamp yeniden imzalanmadı — Binance -1022 döndürür"
    finally:
        _bfc_geri(bfc)


def test_retry_client_order_id_degismez():
    """KONTROL: tazeleme çift emir korumasını BOZMAMALI.

    newClientOrderId retry'lar arasında AYNI kalmazsa ağ timeout'unda
    iki pozisyon açılır (v53 koruması).
    """
    bfc, kay, sanal = _bfc_hazirla([])
    try:
        gonderilen = []

        def post(url, params=None, headers=None, timeout=None, **kw):
            gonderilen.append(dict(params or {}))
            return (_Yanit(429, {}, headers={"Retry-After": "12"})
                    if len(gonderilen) == 1 else _Yanit(200, {"orderId": 3}))

        bfc.requests.post = post
        bfc._futures_istek("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"})
        assert len(gonderilen) == 2, "POST yolunda tekrar denenmedi"
        assert (gonderilen[0]["newClientOrderId"] ==
                gonderilen[1]["newClientOrderId"]), \
            "Retry'da newClientOrderId DEĞİŞTİ — çift emir koruması kırıldı"
        assert (int(gonderilen[1]["timestamp"]) -
                int(gonderilen[0]["timestamp"])) >= 12000, \
            "POST yolunda timestamp tazelenmedi"
    finally:
        _bfc_geri(bfc)


def test_offset_gidis_donusun_ortasindan_olculur():
    """Saat offset'i RTT/2 kadar yanlı OLMAMALI.

    Eskiden yerel saat istek DÖNDÜKTEN sonra okunuyordu; serverTime ise
    isteğin ortasında damgalanır → offset sistematik olarak −RTT/2.
    ÖLÇÜLDÜ: bot −125..−167 ms diyordu, gerçek sapma +25 ms idi.
    """
    import data.binance_futures_client as bfc
    eski = (bfc.requests.get, bfc.time.time, bfc._zaman_offset_guncel)
    sanal = {"t": 1000.0}

    def get(url, timeout=None, **kw):
        sanal["t"] += 0.300                     # 300 ms gidiş-dönüş
        y = _Yanit(200, {"serverTime": int((1000.0 + 0.150) * 1000)})
        y.raise_for_status = lambda: None
        return y

    bfc.requests.get = get
    bfc.time.time = lambda: sanal["t"]
    bfc._zaman_offset_guncel = 0.0
    try:
        offset = bfc._sunucu_zaman_senkronize()
        assert abs(offset) <= 20, (
            f"Offset {offset} ms — sağlıklı saatte sıfıra yakın olmalıydı. "
            "Yerel saat gidiş-dönüşün ORTASINDAN okunmuyor (K-63)")
    finally:
        (bfc.requests.get, bfc.time.time, bfc._zaman_offset_guncel) = eski


# ═════════════════════════════════════════════════════════
# K-67 — BALİNA DEDEKTÖRÜ DÜRÜSTLÜĞÜ
# ═════════════════════════════════════════════════════════
def test_whale_olu_iken_whale_aktif_false():
    """Glassnode anahtarı yokken balina tespiti KAPALI raporlanmalı.

    Eskiden tek bir `aktif` bayrağı vardı ve netflow proxy'si çalıştığı
    için True dönüyordu — ölü balina dedektörü "aktif" görünüyordu.
    """
    import data.onchain_data as oc
    eski = (oc.exchange_netflow_proxy, oc.whale_hareket_tespit, dict(oc._cache))
    oc._cache.clear()
    oc.exchange_netflow_proxy = lambda s: {"netflow_skoru": -0.5,
                                           "yorum": "Para çıkışı",
                                           "kaynak": "coingecko_proxy"}
    oc.whale_hareket_tespit = lambda s: {"whale_skoru": 0.0,
                                         "buyuk_islem_orani": 0.0,
                                         "kaynak": "yok"}
    try:
        r = oc.onchain_sentiment("BTCUSDT")
        assert r.get("whale_aktif") is False, (
            "Balina dedektörü ölüyken whale_aktif True — /onchain raporu "
            "çalışmayan bir dedektörü çalışıyor gösterir (K-67)")
        assert r.get("coine_ozgu") is False, \
            "netflow proxy'si global; coine özgü DEĞİL olarak işaretlenmeli"
    finally:
        oc.exchange_netflow_proxy, oc.whale_hareket_tespit = eski[0], eski[1]
        oc._cache.clear()
        oc._cache.update(eski[2])


def _sentetik_boy(n=20, taban=100.0):
    """Gerçekçi varyanslı işlem-boyu geçmişi (std=0 ise z tanımsız olur)."""
    import random
    random.seed(7)
    return [taban + random.uniform(-8, 8) for _ in range(n)]


def test_whale_buyuk_islem_alis_pozitif():
    """Büyük işlemler + alış baskısı = BİRİKİM → pozitif skor.

    v58 (K-68): anahtar yokken sabit 0.0 dönüyordu; artık Binance'in
    ücretsiz kline alanlarından (quote_vol / num_trades, taker alış payı)
    coine özgü bir tahmin üretiliyor.
    """
    from data.onchain_data import whale_skor_hesapla
    r = whale_skor_hesapla(_sentetik_boy() + [400.0], [0.5] * 20 + [0.9])
    assert r["whale_skoru"] > 0.3, \
        f"Büyük alış işlemleri birikim olarak okunmadı ({r['whale_skoru']})"


def test_whale_buyuk_islem_satis_negatif():
    """KONTROL: aynı büyüklük SATIŞ yönündeyse DAĞITIM → negatif.

    Bu olmadan "her zaman pozitif döndür" regresyonu fark edilmez;
    balina skoru sürekli boğa yanlısı bir sabite dönerdi (K-67'nin
    düzeltmeye çalıştığı durumun aynısı).
    """
    from data.onchain_data import whale_skor_hesapla
    r = whale_skor_hesapla(_sentetik_boy() + [400.0], [0.5] * 20 + [0.1])
    assert r["whale_skoru"] < -0.3, \
        f"Büyük satış işlemleri dağıtım olarak okunmadı ({r['whale_skoru']})"


def test_whale_kucuk_islem_ters_balina_uydurmaz():
    """İşlemler KÜÇÜLDÜĞÜNDE negatif balina UYDURULMAMALI.

    Küçük ortalama işlem boyu "balina yok" demektir, "ters balina" değil.
    §5.1: bilgi yokluğu 0'dır, ters yönlü sinyal değil.
    """
    from data.onchain_data import whale_skor_hesapla
    r = whale_skor_hesapla(_sentetik_boy() + [60.0], [0.5] * 20 + [0.9])
    assert r["whale_skoru"] == 0.0, \
        f"Küçük işlemlerden sinyal uyduruldu ({r['whale_skoru']})"


def test_yetersiz_veride_skor_uretilmez():
    """Az bar varsa hesap YAPILMAMALI (fail-closed)."""
    from data.onchain_data import whale_skor_hesapla
    for boy, pay in (([100.0] * 5, [0.5] * 5), ([100.0] * 20, [0.5] * 20)):
        try:
            whale_skor_hesapla(boy, pay)
            raise AssertionError(
                "Yetersiz/varyanssız veriyle skor üretildi — 'bilmiyorum' "
                "durumu sinyale çevriliyor")
        except ValueError:
            pass


def test_global_piyasa_proxysi_skora_girmez():
    """Coine özgü OLMAYAN global proxy karara GİRMEMELİ.

    Eski hâli `skor = −netflow + whale` idi ve `netflow` aslında
    CoinGecko'nun TÜM PİYASA için verdiği 24s piyasa değeri değişimiydi
    — beş sembolde de aynı (+0.59 ölçüldü). Aynı sabiti hepsine eklemek
    hiçbir coini diğerinden ayırmaz (§0.8: ortak kayma ≠ edge) ve
    işareti de tersti (piyasa düşerken +boğa).
    """
    import data.onchain_data as oc
    eski = (oc.exchange_netflow_proxy, oc.whale_hareket_tespit, dict(oc._cache))
    oc._cache.clear()
    oc.exchange_netflow_proxy = lambda s: {"netflow_skoru": -1.0,
                                           "yorum": "Para çıkışı",
                                           "kaynak": "coingecko_proxy"}
    oc.whale_hareket_tespit = lambda s: {"whale_skoru": 0.0, "kaynak": "yok"}
    try:
        r = oc.onchain_sentiment("BTCUSDT")
        assert r["onchain_skor"] == 0.0, (
            f"Global piyasa proxy'si skora girdi ({r['onchain_skor']}) — "
            "beş coine de aynı sabit ekleniyor demektir")
        assert r["aktif"] is False, \
            "Coine özgü ölçüm yokken sentiment'e katkı açık bırakıldı"
        assert r["global_piyasa_24s"] == -1.0, \
            "Global değer raporlanmıyor — bağlam kayboldu (kaldırmak değil, ayırmak istendi)"
    finally:
        oc.exchange_netflow_proxy, oc.whale_hareket_tespit = eski[0], eski[1]
        oc._cache.clear()
        oc._cache.update(eski[2])


def test_whale_varsa_skor_whaleden_gelir():
    """KONTROL: coine özgü ölçüm VARSA skor onu YANSITMALI.

    Bu olmadan "skoru hep 0 döndür" regresyonu modülü sessizce
    tamamen devre dışı bırakır ve üstteki test yine geçer.
    """
    import data.onchain_data as oc
    eski = (oc.exchange_netflow_proxy, oc.whale_hareket_tespit, dict(oc._cache))
    oc._cache.clear()
    oc.exchange_netflow_proxy = lambda s: {"netflow_skoru": -1.0,
                                           "yorum": "Para çıkışı",
                                           "kaynak": "coingecko_proxy"}
    oc.whale_hareket_tespit = lambda s: {"whale_skoru": -0.42,
                                         "kaynak": "binance_hacim_proxy"}
    try:
        r = oc.onchain_sentiment("BTCUSDT")
        assert abs(r["onchain_skor"] - (-0.42)) < 1e-9, (
            f"Skor balina ölçümünü yansıtmıyor ({r['onchain_skor']}) — "
            "modül sessizce devre dışı kalmış olabilir")
        assert r["aktif"] is True
    finally:
        oc.exchange_netflow_proxy, oc.whale_hareket_tespit = eski[0], eski[1]
        oc._cache.clear()
        oc._cache.update(eski[2])


def test_whale_calisirken_aktif_true():
    """KONTROL: gerçek Glassnode verisi varsa whale_aktif True olmalı.

    Bu olmadan "whale_aktif = False döndür" regresyonu fark edilmez.
    """
    import data.onchain_data as oc
    eski = (oc.exchange_netflow_proxy, oc.whale_hareket_tespit, dict(oc._cache))
    oc._cache.clear()
    oc.exchange_netflow_proxy = lambda s: {"netflow_skoru": 0.0,
                                           "yorum": "Nötr", "kaynak": "yok"}
    oc.whale_hareket_tespit = lambda s: {"whale_skoru": 0.4,
                                         "buyuk_islem_orani": 1.2,
                                         "kaynak": "glassnode"}
    try:
        r = oc.onchain_sentiment("BTCUSDT")
        assert r.get("whale_aktif") is True, \
            "Gerçek balina verisi varken whale_aktif False"
        assert r.get("aktif") is True
    finally:
        oc.exchange_netflow_proxy, oc.whale_hareket_tespit = eski[0], eski[1]
        oc._cache.clear()
        oc._cache.update(eski[2])


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA ÖĞRENME + TEŞHİS MUHAFIZLARI — {len(testler)} test")
    print(f"{'=' * 58}")
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
    print(f"{'=' * 58}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'=' * 58}\n")
    sys.exit(0 if hata == 0 else 1)
