# =========================================================
# ASTRA v58 — YENİDEN GİRİŞ BEKLEME TESTLERİ (K-C)
# Çalıştırma: python tests/test_yeniden_giris.py
#
# NE KORUYOR:
#   Motor bir pozisyonu kapattığı ANDA aynı sembolde yenisini
#   açabiliyordu. Ölçüm (2026-09-02, 21 işlem):
#       #15 XRPUSDT LONG kapandı  04:07:50
#       #16 XRPUSDT SHORT açıldı  04:07:50   ← AYNI SANİYE
#       ikisinin toplamı: %-0.45 (saf gidiş-dönüş maliyeti)
#   Kapanış→açılış boşluğu medyan 92 sn, MİNİMUM 0 sn.
#   Stop yiyen işlemden 1 sn sonra yeni pozisyon açılıyordu
#   (#12→#13, #19→#20).
#
#   Bu bir paper hatası DEĞİLDİ — canlı yol da aynı şeyi yapıyordu
#   (main.py: kapat → time.sleep(0.5) → aç). Yani düzeltmenin İKİ
#   yolda birden olması gerekir, yoksa §5.3 eşitliği bozulur.
#
# §4.1: Her muhafızın yanına KONTROL testi — "hiç işlem açmayan" bir
#   kod da muhafızları geçerdi.
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


def _trader():
    from engines.paper_trading import PaperTrader
    from data.database import tablolari_olustur
    tablolari_olustur()
    return PaperTrader(10000.0)


def _sonuc(sembol, karar, ai, conf, fiyat=100.0):
    return {"sembol": sembol, "karar": karar, "ai_score": ai,
            "confidence": conf, "son_close": fiyat, "son_atr": fiyat * 0.005,
            # v58 (K-97): veto zinciri paper yoluna da bağlandı (§6.0).
            # `edge_sonuc` ve `mtf_confluence` artık ZORUNLU: üretimde
            # `coin_analiz` ikisini de HER ZAMAN üretiyor (ölçüldü 50/50),
            # onlarsız bir `sonuc` üretimde İMKÂNSIZDIR. Fikstür üretim
            # kuralına uymalı (§0.1) — kapı zayıflatılmadı.
            "edge_sonuc": {"gecti": True, "edge_score": 70, "sebep": ""},
            "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3,
                               "ana_trend_yon": "LONG", "yon": "LONG"},
            "rejim": "RANGE", "sig_id": None}


def _temizle(sembol):
    import sqlite3
    from data.database import tablolari_olustur
    tablolari_olustur()
    c = sqlite3.connect(os.environ["DB_PATH"])
    c.execute("DELETE FROM trades WHERE sembol=?", (sembol,))
    c.commit(); c.close()


def _kapali_trade_yaz(sembol, yon="LONG", yas_sn=0):
    """Bu sembolde `yas_sn` saniye önce KAPANMIŞ bir işlem oluştur."""
    import sqlite3
    from datetime import datetime, timezone, timedelta
    from data.database import tablolari_olustur
    tablolari_olustur()
    # ts_kapat NAIVE UTC yazılır (data/database.py::trade_kapat)
    ts = (datetime.now(timezone.utc).replace(tzinfo=None)
          - timedelta(seconds=yas_sn)).isoformat()
    c = sqlite3.connect(os.environ["DB_PATH"])
    c.execute("INSERT INTO trades (ts_ac,ts_kapat,sembol,yon,giris_fiyat,"
              "cikis_fiyat,miktar,pnl,pnl_yuzde,durum,mod) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (ts, ts, sembol, yon, 100.0, 100.0, 1.0, 0.0, 0.0, "TP", "PAPER"))
    c.commit(); c.close()


def _acik_sayisi(sembol):
    from data.database import acik_tradeler
    return len([t for t in acik_tradeler("PAPER") if t["sembol"] == sembol])


# ─────────────────────────────────────────────
# 1. ZAMAN ÖLÇEĞİ — sessiz başarısızlığın kaynağı
# ─────────────────────────────────────────────
def test_kapanis_yasi_utc_olceginde_hesaplanir():
    """`ts_kapat` NAIVE UTC yazılıyor; yaş da UTC ile ölçülmeli.

    `datetime.now()` (yerel) kullanılsaydı bu makinede (UTC+3) yaş
    ~10800 sn şişerdi → bekleme kapısı HİÇ tetiklenmez, hiçbir test
    çökmez, hata sessizce yaşardı (§5.2). Bu test tam onu yakalar.
    """
    from data.database import son_kapanis_yasi_sn
    _temizle("TESTZAMAN")
    _kapali_trade_yaz("TESTZAMAN", yas_sn=0)
    yas = son_kapanis_yasi_sn("TESTZAMAN", "PAPER")
    assert yas is not None, "az önce kapanan işlem bulunamadı"
    assert abs(yas) < 120, (
        f"Yaş {yas:.0f} sn çıktı, ~0 olmalıydı. Saat dilimi ölçeği "
        f"uyuşmuyor (yerel vs UTC) — bekleme kapısı sessizce ölü kalır")
    _temizle("TESTZAMAN")


def test_hic_kapanmis_islem_yoksa_kisit_yok():
    """Kontrol: geçmişi olmayan sembolde bekleme uygulanmamalı."""
    from data.database import son_kapanis_yasi_sn
    _temizle("TESTBOS")
    assert son_kapanis_yasi_sn("TESTBOS", "PAPER") is None, (
        "hiç kapanmış işlemi olmayan sembol için None dönmeliydi")


# ─────────────────────────────────────────────
# 2. MUHAFIZ — bekleme içinde AÇMAMALI
# ─────────────────────────────────────────────
def test_bekleme_icinde_yeni_pozisyon_acilmaz():
    """Gerçek vaka: #19 XRPUSDT stop → #20 BTCUSDT 1 sn sonra açıldı."""
    import config
    from config import MIN_AI_SCORE_BUY, MIN_CONFIDENCE
    _temizle("TESTBEKA")
    _kapali_trade_yaz("TESTBEKA", yas_sn=5)      # 5 sn önce kapandı
    eski = config.YENIDEN_GIRIS_BEKLEME_SN
    config.YENIDEN_GIRIS_BEKLEME_SN = 300
    try:
        _trader().sinyal_isle(_sonuc("TESTBEKA", "STRONG BUY",
                                     MIN_AI_SCORE_BUY + 3, MIN_CONFIDENCE + 13))
        assert _acik_sayisi("TESTBEKA") == 0, (
            "Son kapanıştan 5 sn sonra yeni pozisyon açıldı — "
            "yeniden giriş beklemesi uygulanmıyor")
    finally:
        config.YENIDEN_GIRIS_BEKLEME_SN = eski
        _temizle("TESTBEKA")


def test_ayni_cagrida_ters_donus_yapilmaz():
    """#15 LONG kapanış → #16 SHORT açılış AYNI saniye (%-0.45 maliyet).

    Kapatma meşru (güçlü sinyal) ama hemen ardından ters pozisyon
    açılmamalı — kapanış beklemeyi başlatır.
    """
    import config
    from config import MIN_AI_SCORE_SELL, MIN_CONFIDENCE
    from data.database import trade_ac, acik_tradeler
    _temizle("TESTFLIP")
    trade_ac(sembol="TESTFLIP", yon="LONG", giris_fiyat=100.0, miktar=1.0,
             stop_loss=99.0, take_profit=101.0, mod="PAPER")
    eski = config.YENIDEN_GIRIS_BEKLEME_SN
    config.YENIDEN_GIRIS_BEKLEME_SN = 300
    try:
        # Güçlü SELL: LONG'u kapatmaya YETER, ama SHORT açmaya yetmemeli
        _trader().sinyal_isle(_sonuc("TESTFLIP", "STRONG SELL",
                                     MIN_AI_SCORE_SELL - 3, MIN_CONFIDENCE + 13))
        acik = [t for t in acik_tradeler("PAPER") if t["sembol"] == "TESTFLIP"]
        assert not acik, (
            f"LONG kapandıktan sonra AYNI çağrıda {[t['yon'] for t in acik]} "
            f"açıldı — ters dönüş engellenmiyor")
    finally:
        config.YENIDEN_GIRIS_BEKLEME_SN = eski
        _temizle("TESTFLIP")


# ─────────────────────────────────────────────
# 3. KONTROL — "hiç açma" da muhafızları geçerdi
# ─────────────────────────────────────────────
def test_bekleme_dolunca_pozisyon_ACILIR():
    """Kontrol testi (§4.1). Bekleme geçtiyse işlem açılabilmeli.

    Bu test olmadan, açılışı tamamen kapatan bir 'düzeltme' de yeşil
    olurdu.
    """
    import config
    from config import MIN_AI_SCORE_BUY, MIN_CONFIDENCE
    _temizle("TESTBEKB")
    _kapali_trade_yaz("TESTBEKB", yas_sn=1000)   # bekleme çoktan doldu
    eski = config.YENIDEN_GIRIS_BEKLEME_SN
    config.YENIDEN_GIRIS_BEKLEME_SN = 300
    try:
        _trader().sinyal_isle(_sonuc("TESTBEKB", "STRONG BUY",
                                     MIN_AI_SCORE_BUY + 3, MIN_CONFIDENCE + 13))
        assert _acik_sayisi("TESTBEKB") == 1, (
            "Bekleme dolduğu hâlde pozisyon açılmadı — kapı sürekli "
            "kapalı kalıyor olabilir")
    finally:
        config.YENIDEN_GIRIS_BEKLEME_SN = eski
        _temizle("TESTBEKB")


def test_bekleme_KAPANISI_engellemez():
    """Kontrol: bekleme yalnızca AÇILIŞI kısıtlar.

    Kapanışı da engelleseydi, bekleme penceresinde açılan bir pozisyon
    zıt sinyal geldiğinde kapatılamaz, korumasız kalırdı.
    """
    import config
    from config import MIN_AI_SCORE_SELL, MIN_CONFIDENCE
    from data.database import trade_ac, acik_tradeler
    _temizle("TESTBEKC")
    trade_ac(sembol="TESTBEKC", yon="LONG", giris_fiyat=100.0, miktar=1.0,
             stop_loss=99.0, take_profit=101.0, mod="PAPER")
    _kapali_trade_yaz("TESTBEKC", yon="SHORT", yas_sn=5)   # bekleme AKTİF
    eski = config.YENIDEN_GIRIS_BEKLEME_SN
    config.YENIDEN_GIRIS_BEKLEME_SN = 300
    try:
        _trader().sinyal_isle(_sonuc("TESTBEKC", "STRONG SELL",
                                     MIN_AI_SCORE_SELL - 3, MIN_CONFIDENCE + 13))
        # SADECE LONG'a bak: burada ölçülen şey "kapanış engellendi mi".
        # Tüm pozisyonlara bakılsaydı test ters dönüş hatasında da
        # kırmızıya döner ve mesajı yanıltıcı olurdu (o ayrı bir test).
        kalan_long = [t for t in acik_tradeler("PAPER")
                      if t["sembol"] == "TESTBEKC" and t.get("yon") == "LONG"]
        assert not kalan_long, (
            "Bekleme aktifken LONG kapatılamadı — bekleme kapanışı da "
            "engelliyor, pozisyon korumasız kalır")
    finally:
        config.YENIDEN_GIRIS_BEKLEME_SN = eski
        _temizle("TESTBEKC")


# ─────────────────────────────────────────────
# 4. YAPISAL — paper ↔ canlı eşitliği (§5.3)
# ─────────────────────────────────────────────
def test_canli_yolda_da_bekleme_kapisi_var():
    """Kapı yalnızca paper'da olsaydı paper canlıyı temsil etmezdi.

    Bu, projede tekrar eden hata sınıfı: v56'da paper risk limitlerini
    uygulamıyordu, v57'de rejim ayarını uygulamıyordu.
    """
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "main.py")
    with open(yol, encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))
    assert "YENIDEN_GIRIS_BEKLEME_SN" in kod, (
        "main.py (canlı yol) yeniden giriş beklemesini uygulamıyor — "
        "paper ↔ canlı eşitliği bozuk (§5.3)")
    assert "son_kapanis_yasi_sn" in kod, (
        "main.py bekleme süresini DB'den okumuyor")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA YENİDEN GİRİŞ BEKLEMESİ — {len(testler)} test")
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
