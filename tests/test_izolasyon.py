# =========================================================
# ASTRA v57 — TEST İZOLASYONU MUHAFIZI
# Çalıştırma: python tests/test_izolasyon.py
#
# NE KORUYOR:
#   v56'ya kadar test paketi ÜRETİM durum dosyalarına yazıyordu. Koşu başına
#   data/astra.db'ye 11 sahte kapanmış işlem, journal.db'ye 12 satır (biri
#   mod='LIVE'), model_registry.db'ye 2 versiyon ekleniyor, ab_test.json
#   eziliyordu.
#
#   Bu, projedeki en tehlikeli kirlilikti: canlıya geçiş kararı
#   (CANLI_GECIS_PROTOKOLU.md Aşama 1) "100 kapanmış paper işlem" sayacına
#   dayanır. 2026-08-20'de sayaç 33 gösteriyordu; GERÇEK sayı 0'dı.
#   Sayaç yalnızca test koşularıyla dolmuştu.
#
# §4.1 KURALI (DEVAM_NOTLARI.md): Her engelleme testinin yanına KONTROL
#   testi yazılır. "Üretim dosyasına yazılmadı" iddiası, yazma yolunun
#   tamamen bozuk olmasıyla da sağlanır — o yüzden aşağıda geçici dizine
#   GERÇEKTEN yazıldığını doğrulayan kontrol testleri var.
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

from tests.izolasyon import URETIM_YOLLARI, uretim_yollari_dokunulmamis_mi

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GECICI = os.environ["ASTRA_TEST_DIZINI"]


# ─────────────────────────────────────────────
# 1. YÖNLENDİRME KURULMUŞ MU
# ─────────────────────────────────────────────

class _dis_dunyayi_izole_et:
    """Paper açılışının DIŞ bağımlılıklarını taklit et — v58 (K-103).

    Veto zinciri ortak modüle taşınırken (K-97/K-98/K-103) paper'a iki
    dış bağımlılık girdi:
      • strateji motoru (`futures_trade_engine._strategy_engine`)
      • çoklu borsa doğrulama (`data.multi_exchange.get_multiexchange`)

    Bu dosyanın testleri İZOLASYONU ölçüyor, strateji kalitesini değil.
    Dış dünyaya bağlı kalırlarsa K-101'in tuzağına düşerler: gerçek
    borsanın anlık hâli testin sonucunu belirler.
    """
    def __enter__(self):
        import engines.futures_trade_engine as fte
        import data.multi_exchange as mx
        self._fte, self._mx = fte, mx
        self._eski_se = fte._strategy_engine
        self._eski_mx = mx.get_multiexchange

        class _İzinVer:
            def karar_ver(self, sonuc, bakiye):
                return {"islem_yap": True, "strateji": "TREND_FOLLOW", "usdt": 60}

        class _Guvenilir:
            guvenilir = True; sebep = ""; arbitraj_yon = None; arbitraj_gucu = 0.0

        class _Mex:
            def karsilastir(self, sembol, fiyat): return _Guvenilir()

        fte._strategy_engine = _İzinVer()
        mx.get_multiexchange = lambda: _Mex()
        return self

    def __exit__(self, *a):
        self._fte._strategy_engine = self._eski_se
        self._mx.get_multiexchange = self._eski_mx
        return False


def test_tum_yollar_gecici_dizine_yonlendirildi():
    """6 kalıcı durum yolunun tamamı geçici dizini göstermeli (log dahil).

    Biri bile atlanırsa o dosya sessizce üretime yazılır.
    """
    beklenen = ["DB_PATH", "JOURNAL_DB_PATH", "MODEL_REGISTRY_DB",
                "MODEL_VERSIONS_DIR", "AB_DATA_PATH", "ASTRA_LOG_DIR"]
    for anahtar in beklenen:
        deger = os.environ.get(anahtar)
        assert deger, f"{anahtar} ayarlanmamış — izolasyon eksik"
        assert os.path.abspath(deger).startswith(os.path.abspath(GECICI)), (
            f"{anahtar}={deger} geçici dizin ({GECICI}) DIŞINDA — "
            f"üretim verisine yazma riski")


def test_config_gecici_yollari_okudu():
    """config.py import anında okur; izole_et() ondan ÖNCE çalışmalıydı."""
    from config import DB_PATH, JOURNAL_DB_PATH
    for isim, yol in (("DB_PATH", DB_PATH), ("JOURNAL_DB_PATH", JOURNAL_DB_PATH)):
        assert os.path.abspath(yol).startswith(os.path.abspath(GECICI)), (
            f"config.{isim}={yol} hâlâ üretim yolunu gösteriyor — "
            f"izole_et() config import edildikten SONRA çağrılmış olabilir")


# ─────────────────────────────────────────────
# 2. MUHAFIZ: paper işlem üretimi ÜRETİME dokunmamalı
# ─────────────────────────────────────────────
def test_paper_islemi_uretim_dosyalarina_dokunmaz():
    """10 paper işlemi aç/kapat — yazılan HER yol geçici dizinde olmalı.

    NEDEN PARMAK İZİ KARŞILAŞTIRMASI DEĞİL (v57 revizyonu):
      İlk sürüm üretim dosyalarının sha256'sını önce/sonra karşılaştırıyordu.
      Bot artık 7/24 çalışıyor ve `data/astra.db` ile `logs/astra.log`'a
      MEŞRU şekilde yazıyor — parmak izi bot yüzünden de değişir. O tasarım
      testi, botun yazımlarını "test kirliliği" sanıp rastgele kırmızıya
      döndürürdü. Rastgele kırmızıya dönen bir muhafıza kimse güvenmez;
      görmezden gelinir ve gerçek regresyon da kaçar.

      Bunun yerine DETERMİNİSTİK olan şey doğrulanıyor: kodun FİİLEN
      kullandığı yollar. `baglanti_al()` modül global'i `DB_PATH`'i çağrı
      anında okur, journal singleton `_db`'yi tutar, logging handler
      `baseFilename`'i tutar. Üçü de geçici dizinde ise üretime yazmak
      MÜMKÜN DEĞİLDİR — bot çalışsa da çalışmasa da.

    Bu testin tek başına geçmesi yine yeterli değil; aşağıdaki kontrol
    testleri yazma yolunun gerçekten çalıştığını ayrıca kanıtlar.
    """
    import logging
    from engines.paper_trading import PaperTrader
    from engines.kill_switch import get_kill_switch
    from engines.trade_journal import get_journal
    from data.database import tablolari_olustur, acik_tradeler
    import data.database as _db_mod

    tablolari_olustur()
    pt = PaperTrader()
    ks = get_kill_switch()
    al = {"sembol": "BTCUSDT", "karar": "🚀 STRONG BUY", "son_close": 63000.0,
          "ai_score": 8, "confidence": 88, "atr": 600.0, "son_atr": 600.0,
          "edge_sonuc": {"gecti": True, "edge_score": 70, "sebep": ""}, "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3, "ana_trend_yon": "LONG", "yon": "LONG"}, "rejim": "TREND_UP", "yukselis_guveni": 88}
    for i in range(10):
        ks.reset()
        with _dis_dunyayi_izole_et():
            pt.sinyal_isle(al)
        if acik_tradeler("PAPER"):
            # v58: ai_score de TERS. Üretimde `karar` ai_score'dan
            # türer (karar_ver); "SELL + ai=+8" imkânsızdır ve çıkış
            # kapısı (K-A) bunu haklı olarak reddeder.
            pt.sinyal_isle(dict(al, karar="📉 SELL", ai_score=-8,
                                son_close=63000.0 * (1.004 if i % 2 == 0 else 0.997)))

    # v58: Kapanışın ardından meşru bir ters pozisyon açılıyor (çıkış
    # kapısı artık tutarlı ai_score istiyor, K-A). Açık bırakılırsa
    # MAX_OPEN_POSITIONS=1 sonraki testleri sessizce engeller.
    for _t in list(acik_tradeler("PAPER")):
        pt._kapat_ve_bakiye_guncelle(_t, float(_t["giris_fiyat"]), "TEST_DUZLESTIR")

    gecici = os.path.abspath(GECICI)
    kullanilan = [("data.database.DB_PATH", _db_mod.DB_PATH),
                  ("journal._db",           get_journal()._db)]
    # Dosya log handler'ı yalnızca main.py import edilirse kurulur; bu test
    # main'i import etmiyor. Varsa doğrula, yoksa sessizce atlama —
    # log yönlendirmesi ayrı bir testle (kaynak düzeyinde) kanıtlanıyor.
    for h in logging.getLogger().handlers:
        if hasattr(h, "baseFilename"):
            kullanilan.append(("logging.baseFilename", h.baseFilename))

    disarida = [(isim, yol) for isim, yol in kullanilan
                if not os.path.abspath(yol).startswith(gecici)]
    assert not disarida, (
        f"Test, geçici dizin DIŞINDAKİ yollara yazıyor: {disarida}. "
        f"Canlıya geçiş sayacı (100 paper işlem) kirlenir.")
    assert len(kullanilan) >= 2, (
        f"Yalnızca {len(kullanilan)} yol doğrulandı — muhafız eksik "
        f"kontrol yapıyor")


# ─────────────────────────────────────────────
# 3. KONTROL TESTLERİ — yazma yolu GERÇEKTEN çalışıyor mu?
#    (§4.1: "hiç yazmama" da muhafız testini geçer)
# ─────────────────────────────────────────────
def test_kontrol_paper_islem_gecici_dbye_yaziliyor():
    """Paper işlemleri geçici astra.db'ye GERÇEKTEN düşmeli.

    Bu olmadan yukarıdaki muhafız testi, yazma yolu tamamen bozuk olsa da
    geçerdi — ve izolasyonun çalıştığı sanılırdı.
    """
    import sqlite3
    from engines.paper_trading import PaperTrader
    from engines.kill_switch import get_kill_switch
    from data.database import tablolari_olustur, acik_tradeler

    tablolari_olustur()
    gecici_db = os.environ["DB_PATH"]
    once = sqlite3.connect(gecici_db).execute(
        "SELECT COUNT(*) FROM trades").fetchone()[0]

    pt = PaperTrader()
    get_kill_switch().reset()
    al = {"sembol": "ETHUSDT", "karar": "🚀 STRONG BUY", "son_close": 2000.0,
          "ai_score": 8, "confidence": 88, "atr": 20.0, "son_atr": 20.0,
          "edge_sonuc": {"gecti": True, "edge_score": 70, "sebep": ""}, "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3, "ana_trend_yon": "LONG", "yon": "LONG"}, "rejim": "TREND_UP", "yukselis_guveni": 88}
    with _dis_dunyayi_izole_et():
        pt.sinyal_isle(al)
    assert [t for t in acik_tradeler("PAPER") if t["sembol"] == "ETHUSDT"], \
        "Paper pozisyon açılmadı — yazma yolu bozuk, muhafız testi anlamsız"
    pt.sinyal_isle(dict(al, karar="📉 SELL", ai_score=-8, son_close=2000.0))

    # v58: Kapanışın ardından meşru bir ters pozisyon açılıyor (çıkış
    # kapısı artık tutarlı ai_score istiyor, K-A). Açık bırakılırsa
    # MAX_OPEN_POSITIONS=1 sonraki testleri sessizce engeller.
    for _t in list(acik_tradeler("PAPER")):
        pt._kapat_ve_bakiye_guncelle(_t, float(_t["giris_fiyat"]), "TEST_DUZLESTIR")

    sonra = sqlite3.connect(gecici_db).execute(
        "SELECT COUNT(*) FROM trades").fetchone()[0]
    assert sonra > once, (
        f"Geçici DB'ye hiç işlem yazılmadı ({once} -> {sonra}). "
        f"İzolasyon 'çalışıyor' değil, yazma yolu ÖLÜ.")


def test_kontrol_journal_gecici_dosyaya_yaziliyor():
    """Journal kayıtları da geçici dosyaya düşmeli (üretime değil).

    KENDİ KENDİNE YETERLİ: testler alfabetik sırayla koştuğu için başka bir
    testin işlem üretmiş olmasına GÜVENİLMEZ — kendi işlemini açar.
    (İlk yazımda bu bağımlılık vardı ve test yanlış sebeple kırmızıydı.)
    """
    import sqlite3
    from engines.trade_journal import get_journal
    from engines.paper_trading import PaperTrader
    from engines.kill_switch import get_kill_switch
    from data.database import tablolari_olustur, acik_tradeler

    tablolari_olustur()
    j = get_journal()
    assert os.path.abspath(j._db).startswith(os.path.abspath(GECICI)), (
        f"Journal üretim yolunu kullanıyor: {j._db}")

    once = sqlite3.connect(j._db).execute(
        "SELECT COUNT(*) FROM journal").fetchone()[0]

    pt = PaperTrader()
    get_kill_switch().reset()
    al = {"sembol": "XRPUSDT", "karar": "🚀 STRONG BUY", "son_close": 0.50,
          "ai_score": 8, "confidence": 88, "atr": 0.005, "son_atr": 0.005,
          "edge_sonuc": {"gecti": True, "edge_score": 70, "sebep": ""}, "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3, "ana_trend_yon": "LONG", "yon": "LONG"}, "rejim": "TREND_UP", "yukselis_guveni": 88}
    with _dis_dunyayi_izole_et():
        pt.sinyal_isle(al)
    assert [t for t in acik_tradeler("PAPER") if t["sembol"] == "XRPUSDT"], \
        "Paper pozisyon açılmadı — test önkoşulu sağlanamadı"
    pt.sinyal_isle(dict(al, karar="📉 SELL", ai_score=-8, son_close=0.50))

    # v58: Kapanışın ardından meşru bir ters pozisyon açılıyor (çıkış
    # kapısı artık tutarlı ai_score istiyor, K-A). Açık bırakılırsa
    # MAX_OPEN_POSITIONS=1 sonraki testleri sessizce engeller.
    for _t in list(acik_tradeler("PAPER")):
        pt._kapat_ve_bakiye_guncelle(_t, float(_t["giris_fiyat"]), "TEST_DUZLESTIR")

    sonra = sqlite3.connect(j._db).execute(
        "SELECT COUNT(*) FROM journal").fetchone()[0]
    assert sonra > once, (
        f"Geçici journal'a hiç kayıt düşmedi ({once} -> {sonra}) — "
        f"journal yazma yolu ÖLÜ, muhafız testi yanlış sebeple geçiyor.")


# ─────────────────────────────────────────────
# 4. ÜRETİM HATASI REGRESYONU: journal yolu config'ten gelmeli
# ─────────────────────────────────────────────
def test_get_journal_varsayilani_configten_gelir():
    """get_journal() argümansız çağrıldığında JOURNAL_DB_PATH'i kullanmalı.

    v56'da varsayılan "data/journal.db" SABİT KODLUYDU. 6 çağrı yerinin
    5'i argümansız çağırıyor (bootstrap/app_init.py, paper_trading x2,
    execution_engine x2); yalnızca main.py yolu geçiyordu. Singleton ilk
    çağrıya göre sabitlendiği için, .env'de JOURNAL_DB_PATH değiştirilse
    bile journal SESSİZCE eski dosyaya yazabiliyordu (Docker volume
    senaryosu — bkz. core/preflight.py:134).
    """
    import engines.trade_journal as tj
    from config import JOURNAL_DB_PATH

    onceki = tj._instance
    try:
        tj._instance = None
        j = tj.get_journal()
        assert os.path.abspath(j._db) == os.path.abspath(JOURNAL_DB_PATH), (
            f"get_journal() varsayılanı config'i yok sayıyor: "
            f"{j._db} != {JOURNAL_DB_PATH}")
    finally:
        tj._instance = onceki


def test_journal_yol_catismasi_sessiz_kalmaz():
    """Singleton farklı yolla tekrar istenirse UYARI basılmalı.

    DEVAM_NOTLARI.md §5.2: sessiz başarısızlık kabul edilemez. Eskiden
    ikinci çağrı sessizce ilk instance'ı döndürüyordu.
    """
    import logging
    import engines.trade_journal as tj

    kayitlar = []

    class _Yakala(logging.Handler):
        def emit(self, kayit):
            kayitlar.append(kayit.getMessage())

    h = _Yakala()
    tj.log.addHandler(h)
    onceki = tj._instance
    try:
        tj.get_journal()                      # instance'ı garantile
        tj.get_journal(os.path.join(GECICI, "data", "BASKA_journal.db"))
        assert any("atism" in m.lower() for m in kayitlar), (
            f"Yol çatışması sessiz kaldı — journal iki dosyaya bölünebilir. "
            f"Yakalanan loglar: {kayitlar}")
    finally:
        tj.log.removeHandler(h)
        tj._instance = onceki


# ─────────────────────────────────────────────
# 5. ÖNYÜKLEYİCİ DAVRANIŞI
# ─────────────────────────────────────────────
def test_izole_et_idempotent():
    """Tekrar çağrılırsa aynı dizini döndürmeli, yeni dizin açmamalı."""
    from tests.izolasyon import izole_et as _iz
    assert _iz() == GECICI, "izole_et() ikinci çağrıda farklı dizin döndürdü"


def test_log_yolu_env_ile_yonlendirilebilir():
    """main.py ve order_engine.py log yolunu ASTRA_LOG_DIR'den almalı.

    Sabit kodlu kaldığı sürece testler ÜRETİM `logs/astra.log` dosyasına
    sentetik fikstür satırları (BTCUSDT @ 63018.9 gibi) yazıyordu. Veriyi
    bozmuyordu ama teşhis kaydını güvenilmez yapıyordu: logu inceleyen biri
    bu satırları gerçek işlem sanabilir (bu oturumda neredeyse oldu).

    Kaynak düzeyinde kontrol — handler yalnızca main import edilince kurulur,
    o da bu pakette 17sn sürer.
    """
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, beklenen in (("main.py", 'os.getenv("ASTRA_LOG_DIR"'),
                          (os.path.join("engines", "order_engine.py"),
                           'os.getenv("ASTRA_LOG_DIR"')):
        with open(os.path.join(kok, rel), encoding="utf-8") as fh:
            kod = "\n".join(l for l in fh.read().splitlines()
                            if not l.strip().startswith("#"))
        assert beklenen in kod, (
            f"{rel} log yolunu ASTRA_LOG_DIR'den almıyor — sabit kodlu "
            f"kalmış olabilir")
        assert '_RFH("logs/astra.log"' not in kod, (
            f"{rel} hâlâ sabit kodlu 'logs/astra.log' kullanıyor")


def test_uretim_yol_listesi_eksiksiz():
    """Korunan yol listesi, izole edilen env değişkenleriyle örtüşmeli.

    Yeni bir kalıcı dosya eklenip listeye yazılmazsa sessizce korumasız kalır.
    """
    for rel in ("data/astra.db", "data/journal.db", "data/model_registry.db",
                "data/ab_test.json", "logs/astra.log"):
        assert rel in URETIM_YOLLARI, f"{rel} koruma listesinde yok"


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA TEST İZOLASYONU MUHAFIZI — {len(testler)} test")
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
