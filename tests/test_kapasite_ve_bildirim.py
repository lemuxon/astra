# =========================================================
# ASTRA — KAPASİTE + BİLDİRİM MUHAFIZLARI (v58, K-39 · K-71..K-74)
# Çalıştırma: python tests/test_kapasite_ve_bildirim.py
#
# 2026-09-10'da bulunan hatalar:
#   K-39  Model sürüm arşivi sınırsız büyüyordu (26.3 GB)
#   K-71  Rejim TEK global alandaydı → 3446 sahte değişim + yarış
#   K-72  Telegram raporu GİRİŞ eşiğine bağlıydı → 2303 mesaj/gün
#   K-73  4h barda tur 60 sn → bar başına 240 gereksiz ağır analiz
#   K-74  Panel tek yavaş yanıtta "BAĞLANTI YOK" diyordu
#
# ⚠️ §4.1: her kapı testinin yanında KONTROL testi var; düzeltmeler
# tek tek geri alınarak (mutasyon) kırmızıya döndükleri doğrulandı.
# =========================================================
import sys, os, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()

os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")


# ═════════════════════════════════════════════════════════
# K-71 — REJİM SEMBOL BAŞINA
# ═════════════════════════════════════════════════════════
def test_farkli_semboller_birbirinin_rejimini_ezmez():
    """İki sembol farklı rejimdeyken biri diğerini EZMEMELİ.

    Kırıldığında: tek global alan her sembolde takla atar. ÖLÇÜM
    (2026-09-10): 3446 REGIME SHIFT, ardışık iki değişim arası medyan
    2 saniye, deseni kusursuz alternatif (VOLATILE→TREND_UP→VOLATILE).
    """
    from strategy.regime_adapter import RegimeAdapter
    ra = RegimeAdapter()
    ra.rejim_guncelle("TREND_UP", "AAAUSDT")
    ra.rejim_guncelle("VOLATILE", "BBBUSDT")
    assert ra.aktif_rejim("AAAUSDT") == "TREND_UP", (
        "B sembolü A'nın rejimini ezdi — global alan geri gelmiş (K-71)")
    assert ra.aktif_rejim("BBBUSDT") == "VOLATILE"


def test_ayni_sembol_gercek_degisimi_bildirir():
    """KONTROL: AYNI sembolün rejimi gerçekten değişirse True dönmeli.

    Bu olmadan "hep False döndür" regresyonu rejim adaptasyonunu
    tamamen sessizleştirir ama üstteki test yine geçer.
    """
    from strategy.regime_adapter import RegimeAdapter
    ra = RegimeAdapter()
    assert ra.rejim_guncelle("TREND_UP", "AAAUSDT") is True, \
        "İlk rejim ataması değişim saymadı"
    assert ra.rejim_guncelle("TREND_UP", "AAAUSDT") is False, \
        "Aynı rejim tekrar bildirildi — sahte alarm üretir"
    assert ra.rejim_guncelle("BEAR", "AAAUSDT") is True, \
        "Gerçek rejim değişimi bildirilmedi"


def test_rejim_degisimi_telegrama_gitmez():
    """Rejim değişimi Telegram'a GİTMEMELİ, ama log ve dönüş korunmalı.

    ── v58 (K-81) ───────────────────────────────────────────────
    K-71 rejimi sembol bazlı yaptı (doğru). Ama 50 coinde her sembolün
    İLK ataması da bir "değişim"dir → açılışta 50'ye kadar bildirim.
    ÖLÇÜM: yeniden başlatmadan 20 dk sonra 15 Telegram mesajının 13'ü
    rejim bildirimiydi. Kullanıcının isteği: yalnızca çok emin sinyaller.
    """
    from strategy.regime_adapter import RegimeAdapter
    ra = RegimeAdapter()
    yayinlar = []
    ra._bus = type("B", (), {"publish": lambda self, *a, **k: yayinlar.append(a)})()
    degisti = ra.rejim_guncelle("BEAR", "AAAUSDT")
    assert degisti is True, (
        "Rejim değişimi artık RAPORLANMIYOR — bildirim susturulurken "
        "adaptasyon da kapatılmış (K-81 aşırı düzeltmesi)")
    assert not yayinlar, (
        f"Rejim değişimi Telegram'a gönderildi ({len(yayinlar)} yayın) — "
        f"50 coinde açılışta onlarca mesaj demek (K-81)")


def test_kaldirac_sembolun_kendi_rejiminden():
    """Kaldıraç limiti O SEMBOLÜN rejiminden gelmeli.

    Paralel analizde A coini B coininin `kaldirac_max` değeriyle
    işlem açabiliyordu (yarış durumu).
    """
    from strategy.regime_adapter import RegimeAdapter, REJIM_KONFIG
    ra = RegimeAdapter()
    ra.rejim_guncelle("TREND_UP", "AAAUSDT")
    ra.rejim_guncelle("BEAR", "BBBUSDT")
    a = ra.efektif_kaldirac(20, "AAAUSDT")
    b = ra.efektif_kaldirac(20, "BBBUSDT")
    assert a == min(20, REJIM_KONFIG["TREND_UP"].kaldirac_max)
    assert b == min(20, REJIM_KONFIG["BEAR"].kaldirac_max)
    assert a != b, ("İki farklı rejim aynı kaldıracı verdi — sembol "
                    "ayrımı çalışmıyor olabilir (test varsayımı)")


# ═════════════════════════════════════════════════════════
# K-72 — TELEGRAM BİLDİRİM KAPISI
# ═════════════════════════════════════════════════════════
def _sonuc(ai=5, conf=100, close=100.0, karar="📈 BUY", sembol="AAAUSDT"):
    return {"sembol": sembol, "ai_score": ai, "confidence": conf,
            "son_close": close, "karar": karar}


def test_ayni_bar_ikinci_kez_bildirilmez():
    """Aynı (sembol, bar) için İKİNCİ bildirim gitmemeli.

    4h ufkunda analiz sonucu 4 saat sabit ama tur 60 sn. Tekilleştirme
    olmadan aynı sinyal bar başına ~48 kez gidiyordu (ölçüm: 2303
    mesaj/gün, 1137'si grafik).
    """
    import main
    main._tg_bildirilen.clear()
    assert main._tg_bildirilmeli(_sonuc()) is True, "İlk bildirim engellendi"
    assert main._tg_bildirilmeli(_sonuc()) is False, (
        "Aynı bar ikinci kez bildirildi — Telegram seli geri gelir (K-72)")


def test_karar_degisince_yeniden_bildirilir():
    """KONTROL: karar BUY→SELL olursa bu YENİ bilgidir, gitmeli.

    Bu olmadan "bir kez gönder, bir daha asla" regresyonu gerçek
    dönüşleri kaçırır ve üstteki test yine geçer.
    """
    import main
    main._tg_bildirilen.clear()
    assert main._tg_bildirilmeli(_sonuc(karar="📈 BUY")) is True
    assert main._tg_bildirilmeli(_sonuc(karar="📉 SELL")) is True, \
        "Karar değiştiği hâlde bildirilmedi — gerçek dönüş kaçar"


def test_zayif_sinyal_bildirilmez():
    """Girişi geçen ama "çok emin" olmayan sinyal Telegram'a GİTMEMELİ.

    Kullanıcı isteği: yalnızca çok emin olunanlar, fotoğraflı.
    ÖLÇÜM: |AI|>=4 → 20 bildirim/gün, |AI|>=5 & güven>=70 → 2.
    """
    import main
    main._tg_bildirilen.clear()
    assert main._tg_bildirilmeli(_sonuc(ai=4, conf=100)) is False, \
        "|AI|=4 bildirildi — eşik giriş kapısına geri bağlanmış olabilir"
    main._tg_bildirilen.clear()
    assert main._tg_bildirilmeli(_sonuc(ai=5, conf=60)) is False, \
        "Düşük güvenli sinyal bildirildi"


def test_guclu_sinyal_bildirilir():
    """KONTROL: eşiği geçen sinyal GERÇEKTEN gitmeli.

    Bu olmadan "hep False döndür" regresyonu botu tamamen sessizleştirir.
    """
    import main
    main._tg_bildirilen.clear()
    assert main._tg_bildirilmeli(_sonuc(ai=5, conf=100)) is True, \
        "Çok emin sinyal bildirilmedi — bot tamamen sessizleşti"


# ═════════════════════════════════════════════════════════
# K-73 — BAR BAŞINA BİR AĞIR ANALİZ
# ═════════════════════════════════════════════════════════
def test_bar_indeksi_bar_suresince_sabit():
    """Bar indeksi bar boyunca DEĞİŞMEMELİ, bar sınırında değişmeli."""
    import main
    from config import ANA_BAR_DK
    bar_sn = ANA_BAR_DK * 60
    gercek = main.time.time
    try:
        main.time.time = lambda: 1_000_000 * bar_sn + 5
        a = main._bar_indeksi()
        main.time.time = lambda: 1_000_000 * bar_sn + bar_sn - 5
        b = main._bar_indeksi()
        main.time.time = lambda: 1_000_001 * bar_sn + 5
        c = main._bar_indeksi()
    finally:
        main.time.time = gercek
    assert a == b, "Bar indeksi bar İÇİNDE değişti — önbellek hiç tutmaz"
    assert c == a + 1, "Bar sınırında indeks ilerlemedi — önbellek bayatlar"


def test_ayni_barda_agir_analiz_tekrar_edilmez():
    """Aynı barda `coin_analiz` İKİNCİ kez çağrılmamalı.

    Kırıldığında: 4h barda 240 gereksiz tam analiz → 418 IP ban,
    3446 sahte rejim değişimi, 1.33 GB/gün model arşivi.
    """
    import main
    sayac = {"n": 0}

    def sahte(sembol, **kw):
        sayac["n"] += 1
        return {"sembol": sembol, "son_close": 100.0, "anlik_fiyat": 100.0,
                "ai_score": 1, "confidence": 60, "karar": "WAIT"}

    gercek_analiz, gercek_fiyat = main.coin_analiz, main.guncel_fiyat_al
    main.coin_analiz = sahte
    main.guncel_fiyat_al = lambda s: 101.0
    main._analiz_onbellek.clear()
    try:
        main._analiz_al("AAAUSDT")
        main._analiz_al("AAAUSDT")
        s3 = main._analiz_al("AAAUSDT")
    finally:
        main.coin_analiz, main.guncel_fiyat_al = gercek_analiz, gercek_fiyat
    assert sayac["n"] == 1, (
        f"Aynı barda {sayac['n']} kez ağır analiz yapıldı — önbellek "
        f"çalışmıyor (K-73)")
    assert s3["anlik_fiyat"] == 101.0, (
        "Önbellekten dönen sonuçta ANLIK FİYAT tazelenmemiş — SL/TP "
        "kontrolü bayat fiyatla çalışır, bu tehlikelidir")


def test_fiyat_alinamazsa_tam_analize_dusulur():
    """KONTROL: anlık fiyat alınamıyorsa bayat fiyat KULLANILMAMALI.

    §5.1 fail-closed: fiyatı doğrulayamıyorsak SL/TP kontrolünü bayat
    veriyle çalıştırmak yanlış tetikleme üretir.
    """
    import main
    sayac = {"n": 0}

    def sahte(sembol, **kw):
        sayac["n"] += 1
        return {"sembol": sembol, "son_close": 100.0, "anlik_fiyat": 100.0,
                "ai_score": 1, "confidence": 60, "karar": "WAIT"}

    gercek_analiz, gercek_fiyat = main.coin_analiz, main.guncel_fiyat_al
    main.coin_analiz = sahte
    main.guncel_fiyat_al = lambda s: 0.0        # fiyat alınamadı
    main._analiz_onbellek.clear()
    try:
        main._analiz_al("AAAUSDT")
        main._analiz_al("AAAUSDT")
    finally:
        main.coin_analiz, main.guncel_fiyat_al = gercek_analiz, gercek_fiyat
    assert sayac["n"] == 2, (
        "Fiyat alınamadığı hâlde önbellekteki BAYAT fiyat kullanıldı — "
        "tam analize düşülmeliydi")


# ═════════════════════════════════════════════════════════
# K-39 — MODEL SÜRÜM SAKLAMA POLİTİKASI
# ═════════════════════════════════════════════════════════
def test_eski_surumler_budanir_ama_aktif_korunur():
    """Eski .pkl'ler silinmeli; AKTİF olan ve son N KORUNMALI.

    Arşiv 26.3 GB'a ulaşmıştı ve hiçbir temizlik yoktu. Ama sürümler
    `rollback_yap()` tarafından kullanılıyor — körü körüne silinemez.
    """
    from engines.model_registry import ModelRegistry
    from config import MODEL_SAKLANAN_SURUM as N
    from engines.model_registry import VERSIONS_DIR as MODEL_VERSIONS_DIR
    os.makedirs(MODEL_VERSIONS_DIR, exist_ok=True)
    r = ModelRegistry()
    kaynak = os.path.join(MODEL_VERSIONS_DIR, "_kaynak.pkl")
    with open(kaynak, "wb") as f:
        f.write(b"x" * 64)

    for _ in range(N + 5):
        r.register("ZZZUSDT", "rf", kaynak, accuracy=0.5)

    conn = r._baglanti(); c = conn.cursor()
    c.execute("""SELECT versiyon, dosya_yolu, aktif FROM model_versions
                 WHERE sembol='ZZZUSDT' AND model_tipi='rf'
                 ORDER BY versiyon DESC""")
    satirlar = c.fetchall(); conn.close()

    var = [s for s in satirlar if s[1] and os.path.exists(s[1])]
    assert len(var) <= N + 1, (
        f"{len(var)} dosya duruyor (sınır {N}) — budama çalışmıyor (K-39)")
    aktif = [s for s in satirlar if s[2]]
    assert aktif and os.path.exists(aktif[0][1]), \
        "AKTİF sürümün dosyası silindi — rollback ve canlı model kırılır"


def test_son_n_surum_silinmez():
    """KONTROL: son N sürüm KORUNMALI (hepsini silme regresyonu)."""
    from engines.model_registry import ModelRegistry
    from config import MODEL_SAKLANAN_SURUM as N
    from engines.model_registry import VERSIONS_DIR as MODEL_VERSIONS_DIR
    os.makedirs(MODEL_VERSIONS_DIR, exist_ok=True)
    r = ModelRegistry()
    kaynak = os.path.join(MODEL_VERSIONS_DIR, "_kaynak2.pkl")
    with open(kaynak, "wb") as f:
        f.write(b"y" * 64)
    for _ in range(N + 5):
        r.register("YYYUSDT", "gb", kaynak, accuracy=0.5)

    conn = r._baglanti(); c = conn.cursor()
    c.execute("""SELECT dosya_yolu FROM model_versions
                 WHERE sembol='YYYUSDT' AND model_tipi='gb'
                 ORDER BY versiyon DESC LIMIT ?""", (N,))
    son_n = [x[0] for x in c.fetchall()]; conn.close()
    eksik = [y for y in son_n if y and not os.path.exists(y)]
    assert not eksik, (
        f"Son {N} sürümden {len(eksik)} tanesi silinmiş — rollback yapacak "
        f"sürüm kalmaz")


# ═════════════════════════════════════════════════════════
# K-86/K-87 — KALDIRAÇ SADAKATİ
# ═════════════════════════════════════════════════════════
def test_paper_kaldiraci_sabit_kodlamaz():
    """Paper kaldıracı CANLI ile aynı kaynaktan almalı.

    ── v58 (K-86) ───────────────────────────────────────────────
    Paper `kaldirac=1` SABİT KODLUYDU (paper_trading.py:486); canlı yol
    ise `dinamik_kaldirac_hesapla()` + rejim tavanı ile gerçek kaldıracı
    hesaplayıp `kaldirac_ayarla()` ile borsaya kuruyordu.
    Sonuç: paper 1x spot gibi davranıyordu → §5.3 ihlali.
    """
    import inspect
    from engines import paper_trading
    kaynak = inspect.getsource(paper_trading.PaperTrader._pozisyon_ac)
    # Kelimeyi değil ATAMAYI ara: "islem_kaldiraci" import satırında da
    # geçiyor, yalnızca ona bakmak testi zayıflatır (mutasyonda
    # yakalanmadı — §4.1).
    assert "kaldirac = islem_kaldiraci(" in kaynak, (
        "Paper kaldıracı ortak kaynaktan ALMIYOR — sabit kodlu değere "
        "dönmüş olabilir (K-86). Canlı yol dinamik kaldıraç kuruyor; "
        "paper 1x kalırsa örneklem canlıyı temsil etmez (§5.3).")


def test_bakiyeden_marjin_dusulur_notional_degil():
    """Açılışta bakiyeden MARJİN düşülmeli (notional/kaldıraç).

    Notional'in tamamını düşmek SPOT davranışıdır. Gerçek futures'ta
    yalnızca marjin bağlanır; canlı yol bunu zaten böyle hesaplıyor
    (futures_trade_engine.py: "Gerekli marjin = notional/kaldıraç").
    """
    import inspect
    from engines import paper_trading
    kaynak = inspect.getsource(paper_trading.PaperTrader._pozisyon_ac)
    assert "marjin   = notional / max(1.0, float(kaldirac))" in kaynak, (
        "Marjin hesabı yok — notional'in tamamı bağlanıyor olabilir (K-86)")
    assert "self.bakiye -= marjin" in kaynak, (
        "Bakiyeden marjin değil başka bir tutar düşülüyor (K-86)")


def test_restart_bakiyesi_de_marjin_kullanir():
    """KONTROL: restart'ta DB'den türetilen bakiye de MARJİN düşmeli.

    Açılışta marjin, restart'ta notional düşülseydi yeniden başlatılan
    bakiye çalışan bakiyeden saparadı — K-59'un düzelttiği hatanın
    birebir tekrarı (sessiz para kaçağı).
    """
    import inspect
    from engines import paper_trading
    kaynak = inspect.getsource(paper_trading.PaperTrader._bakiye_hesapla)
    assert 'm = t.get("marjin")' in kaynak, (
        "Restart bakiyesi marjin alanını okumuyor — notional düşüyor "
        "olabilir, çalışan bakiyeyle ayrışır (K-86)")


def test_pnl_yuzde_notional_bazinda_kalir():
    """`pnl_yuzde` NOTIONAL üzerinden kalmalı — karar kuralı ona bakıyor.

    ⚠️ `karar_kurali.py` beklentiyi `pnl_yuzde`'den hesaplıyor ve
    MIN_BEKLENTI_PCT=0.10 eşiği KALDIRAÇSIZ getiriye göre yazıldı.
    Tabanı marjine çevirmek tüm değerleri kaldıraç katı büyütür ve
    eşiği sessizce o kadar kolaylaştırır → protokol geçersiz olur
    (§0: "eşikler veri görülmeden belirlendi, değiştirilemez").
    """
    import inspect
    from engines import paper_trading
    kaynak = inspect.getsource(paper_trading.PaperTrader._kapat_ve_bakiye_guncelle)
    assert "pnl_pct = (pnl / maliyet * 100)" in kaynak, (
        "pnl_yuzde tabanı değişmiş — karar kuralının eşiği sessizce "
        "kaldıraç katı kadar kolaylaşır (K-86)")
    assert "geri_gelen = marjin + pnl" in kaynak, (
        "Kapanışta marjin yerine başka tutar iade ediliyor (K-86)")


def test_fonlama_maliyeti_modelleniyor():
    """Fonlama (funding) PnL'den düşülmeli.

    ── v58 (K-87) ───────────────────────────────────────────────
    Perpetual futures 8 saatte bir fonlama öder/alır. Komisyon (K-42)
    modelleniyordu ama fonlama HİÇ modellenmiyordu. K-85 ile pozisyonlar
    24 saate kadar tutuluyor → 3 fonlama dönemi.
    Gerçek oranlar (2026-09-13): 8 saatte %0.0032-0.0100.
    """
    import inspect
    from engines import paper_trading
    kaynak = inspect.getsource(paper_trading.PaperTrader._kapat_ve_bakiye_guncelle)
    assert "funding_maliyet" in kaynak, "fonlama hiç hesaplanmıyor (K-87)"
    assert "pnl_brut - komisyon - funding_maliyet" in kaynak, (
        "Fonlama net PnL'e dahil edilmiyor — bakiye ile DB ayrışır")


def test_fonlama_yonu_dogru():
    """LONG pozitif oranda ÖDER, SHORT ALIR.

    KONTROL: işaret ters olsaydı fonlama kâr gibi görünür ve paper
    sistematik olarak İYİMSER çıkardı — tam da K-42/v56'da düzeltilen
    "maliyet modellenmiyor" hatasının aynısı.
    """
    import inspect
    from engines import paper_trading
    kaynak = inspect.getsource(paper_trading.PaperTrader._kapat_ve_bakiye_guncelle)
    assert '_isaret = 1.0 if yon == "LONG" else -1.0' in kaynak, (
        "Fonlama işareti yanlış/eksik — LONG pozitif oranda ÖDEMELİ (K-87)")


def test_para_dokumu_ozdesligi_fonlamayi_icerir():
    """`brut = net + komisyon + fonlama` özdeşliği korunmalı.

    Bu özdeşlik raporun kendi iç tutarlılık kontrolü. Fonlama PnL'den
    düşülüp özdeşliğe eklenmezse rapor SAHTE kaçak gösterir.
    """
    import inspect
    from engines import paper_trading
    kaynak = inspect.getsource(paper_trading.PaperTrader.para_dokumu)
    assert "brut = net + kom + fon" in kaynak, (
        "Para dökümü özdeşliği fonlamayı içermiyor — sahte muhasebe "
        "kaçağı gösterir (K-87)")


# ═════════════════════════════════════════════════════════
# K-88 — TASFİYE (liquidation)
# ═════════════════════════════════════════════════════════
def test_tasfiye_fiyati_kaldiraca_gore():
    """Tasfiye mesafesi kaldıraçla ters orantılı olmalı.

    ── v58 (K-88) ───────────────────────────────────────────────
    3x → ~%32.9 · 10x → ~%9.6 aleyhte hareket.
    K-86 ile kaldıraç gerçek oldu; tasfiye de gerçek bir risk.
    """
    from engines.futures_trade_engine import tasfiye_fiyati
    u3  = (100.0 - tasfiye_fiyati(100.0, "LONG", 3)) / 100.0 * 100
    u10 = (100.0 - tasfiye_fiyati(100.0, "LONG", 10)) / 100.0 * 100
    assert 30 < u3 < 34, f"3x tasfiye mesafesi %{u3:.1f} — beklenen ~%32.9"
    assert 8 < u10 < 11, f"10x tasfiye mesafesi %{u10:.1f} — beklenen ~%9.6"
    assert u10 < u3, "yüksek kaldıraçta tasfiye DAHA YAKIN olmalı"
    kisa = tasfiye_fiyati(100.0, "SHORT", 3)
    assert kisa > 100.0, "SHORT tasfiyesi YUKARIDA olmalı"


def test_tasfiye_1x_te_yok():
    """KONTROL: 1x'te tasfiye YOKTUR (spot gibi).

    Bu olmadan "her zaman bir seviye döndür" regresyonu 1x pozisyonları
    sahte bir seviyeyle kapatır.
    """
    from engines.futures_trade_engine import tasfiye_fiyati
    assert tasfiye_fiyati(100.0, "LONG", 1) == 0.0,         "1x'te tasfiye seviyesi üretildi — spot pozisyon tasfiye olmaz"
    assert tasfiye_fiyati(0, "LONG", 3) == 0.0, "geçersiz girişte seviye üretildi"


def test_tasfiye_sl_tpden_sonra_kontrol_edilir():
    """SL/TP ÖNCE, tasfiye SON ÇARE olmalı.

    Tasfiye her zaman SL'den UZAKTADIR (3x → %32.9 vs SL %3-5). Normal
    işleyişte SL önce dolar. Tasfiye, SL'in dolmadığı durumun (fiyat
    boşluğu) karşılığıdır — sırası bozulursa zarar yanlış yazılır.
    """
    # DAVRANIŞSAL sınama — kaynak sırasına bakmak zayıf kalıyor (§4.1).
    # Fiyat tasfiyenin de ötesine düştüğünde SL zaten geçilmiştir;
    # kapanış sebebi STOP olmalı, TASFIYE değil.
    from engines import paper_trading
    from data.database import tablolari_olustur, trade_ac, acik_tradeler
    from engines.futures_trade_engine import tasfiye_fiyati
    tablolari_olustur()

    giris, kaldirac = 100.0, 3
    tf = tasfiye_fiyati(giris, "LONG", kaldirac)          # ~67.07
    trade_ac("TASTESTUSDT", "LONG", giris, 1.0,
             stop_loss=97.0, take_profit=104.0, mod="PAPER",
             kaldirac=kaldirac, marjin=giris / kaldirac, tasfiye_fiyat=tf)

    motor = paper_trading.PaperTrader.__new__(paper_trading.PaperTrader)
    motor.bakiye = 10000.0
    kapanislar = []
    motor._kapat_ve_bakiye_guncelle = (
        lambda t, f, sebep: kapanislar.append((sebep, f)))
    # Fiyat tasfiyenin ALTINA düştü — SL çoktan geçildi.
    paper_trading.PaperTrader.stop_tp_kontrol(motor, "TASTESTUSDT", tf - 5)

    assert kapanislar, "pozisyon hiç kapatılmadı"
    sebep, fiyat = kapanislar[0]
    assert sebep == "STOP", (
        f"kapanış sebebi '{sebep}' — tasfiye SL/TP'den ÖNCE kontrol "
        f"ediliyor. Tasfiye HER ZAMAN SL'den uzaktadır (3x: %32.9 vs "
        f"SL %3); SL önce dolmalı, yoksa zarar yanlış yazılır (K-88).")
    assert abs(fiyat - 97.0) < 1e-9, (
        f"dolum {fiyat} — STOP seviyesinden (97.0) dolmalıydı")


def test_tasfiyede_zarar_marjini_asmaz():
    """Tasfiyede zarar MARJİNLE sınırlı olmalı.

    İzole marjinde bakiye eksiye düşmez (borç oluşmaz); marjinin tamamı
    gider, o kadar. K-59'da "zarar pozisyon maliyetini aşarsa" diye
    bırakılan uyarının gerçek karşılığı budur.
    """
    import inspect
    from engines import paper_trading
    kaynak = inspect.getsource(paper_trading.PaperTrader._kapat_ve_bakiye_guncelle)
    assert 'sebep == "TASFIYE" and pnl < -marjin' in kaynak, (
        "Tasfiyede zarar marjine kırpılmıyor — bakiye eksiye düşebilir, "
        "izole marjinde bu OLMAZ (K-88)")
    assert "pnl = round(-marjin, 4)" in kaynak, (
        "Kırpma marjine değil başka bir değere yapılıyor")


# ═════════════════════════════════════════════════════════
# K-85 — ZAMAN STOP
# ═════════════════════════════════════════════════════════
def test_zaman_stop_model_ufkundan_turetilir():
    """Zaman stop süresi, modelin ETİKET UFKUNA bağlı olmalı.

    ── v58 (K-85) ───────────────────────────────────────────────
    `HEDEF_MAX_BAR` üçlü bariyerin dikey ufku: model "önümüzdeki N bar
    içinde ne olacak" sorusuna göre eğitiliyor. O ufkun ötesinde
    pozisyon tutmak, modelin hakkında HİÇBİR İDDİASI OLMAYAN bir
    pozisyonu tutmaktır (K-22 ile aynı ilke: eğitim/servis ufku ayrışmaz).

    SORUN (§0.29 ölçümü): 10 açık pozisyon, 24-34 saattir açık,
    10/10'u SL/TP'ye değmemiş; kapanış hızı 0.70/gün → 144 gün.
    """
    from config import ZAMAN_STOP_BAR, HEDEF_MAX_BAR, ZAMAN_STOP_SN, ANA_BAR_DK
    assert ZAMAN_STOP_BAR == HEDEF_MAX_BAR, (
        f"zaman stop {ZAMAN_STOP_BAR} bar, model ufku {HEDEF_MAX_BAR} bar — "
        f"ayrışmış. Model, tutulan sürenin sonucu hakkında iddia üretmiyor.")
    assert ZAMAN_STOP_SN == ZAMAN_STOP_BAR * ANA_BAR_DK * 60


def test_zaman_stop_suresi_dolunca_tetiklenir():
    """Ufku aşan pozisyon kapatılmalı."""
    from engines.futures_trade_engine import zaman_stop_doldu_mu
    from config import ZAMAN_STOP_SN
    from datetime import datetime, timedelta
    eski = (datetime.utcnow() - timedelta(seconds=ZAMAN_STOP_SN + 3600)).isoformat()
    doldu, saat = zaman_stop_doldu_mu(eski)
    assert doldu is True, f"ufku aşan pozisyon kapatılmadı ({saat:.1f} sa)"


def test_zaman_stop_erken_tetiklenmez():
    """KONTROL: ufuk DOLMADAN kapatılmamalı.

    Bu olmadan "hep True döndür" regresyonu her pozisyonu anında
    kapatır — §0.14'te ölçülen "erken kesme" zararının en uç hâli.
    """
    from engines.futures_trade_engine import zaman_stop_doldu_mu
    from config import ZAMAN_STOP_SN
    from datetime import datetime, timedelta
    yeni = (datetime.utcnow() - timedelta(seconds=ZAMAN_STOP_SN * 0.5)).isoformat()
    doldu, _ = zaman_stop_doldu_mu(yeni)
    assert doldu is False, "ufkun yarısında kapatıldı — erken kesme"
    assert zaman_stop_doldu_mu(None)[0] is False, "zaman yokken kapatıldı"
    assert zaman_stop_doldu_mu("bozuk")[0] is False,         "okunamayan zaman damgasında kapatıldı — belirsizlikte işlem yapılmamalı"


def test_sl_tp_zaman_stoptan_once_gelir():
    """SL/TP kontrolü zaman stop'tan ÖNCE olmalı.

    Fiyat stop seviyesindeyse gerçekte stop dolmuştur. Zaman stop onu
    ezerse zarar YANLIŞ fiyattan yazılır (stop seviyesi yerine piyasa).
    """
    # DAVRANIŞSAL sınama — kaynak metni aramak zayıf kalıyor (§4.1):
    # "if not tetiklendi:" ifadesi tasfiye bloğunda da geçiyor, o yüzden
    # varlığına bakmak mutasyonu YAKALAMIYORDU.
    from engines import paper_trading
    from data.database import tablolari_olustur, trade_ac
    from datetime import datetime, timedelta, timezone
    from config import ZAMAN_STOP_SN
    tablolari_olustur()

    tid = trade_ac("ZSTESTUSDT", "LONG", 100.0, 1.0,
                   stop_loss=97.0, take_profit=104.0, mod="PAPER",
                   kaldirac=3, marjin=100.0 / 3)
    # Açılışı zaman stop ufkunun ÖTESİNE al — hem SL hem süre dolmuş olsun.
    from data.database import baglanti
    eski_ts = (datetime.now(timezone.utc).replace(tzinfo=None)
               - timedelta(seconds=ZAMAN_STOP_SN + 3600)).isoformat()
    with baglanti() as conn:
        conn.execute("UPDATE trades SET ts_ac=? WHERE id=?", (eski_ts, tid))
        conn.commit()

    motor = paper_trading.PaperTrader.__new__(paper_trading.PaperTrader)
    motor.bakiye = 10000.0
    kapanislar = []
    motor._kapat_ve_bakiye_guncelle = (
        lambda t, f, sebep: kapanislar.append((sebep, f)))
    # Fiyat STOP seviyesinin altında VE süre dolmuş → STOP kazanmalı.
    paper_trading.PaperTrader.stop_tp_kontrol(motor, "ZSTESTUSDT", 96.0)

    assert kapanislar, "pozisyon hiç kapatılmadı"
    sebep, fiyat = kapanislar[0]
    assert sebep == "STOP", (
        f"kapanış sebebi '{sebep}' — zaman stop SL/TP'yi EZİYOR. "
        f"Fiyat stop seviyesindeyse gerçekte stop dolmuştur; zaman stop "
        f"onu ezerse zarar piyasa fiyatından yazılır (K-85).")
    assert abs(fiyat - 97.0) < 1e-9, (
        f"dolum {fiyat} — STOP seviyesinden (97.0) dolmalıydı")


def test_zaman_stop_iki_yolda_da_ayni_kaynaktan():
    """Paper ve canlı AYNI fonksiyonu çağırmalı (§5.3).

    Ayrı ayrı yazılsaydı biri güncellenip diğeri unutulurdu — bu kod
    tabanında §5.3 tam olarak böyle kırılmıştı (K-13, K-69, K-78).
    """
    import inspect
    from engines import paper_trading, futures_trade_engine
    p_kaynak = inspect.getsource(paper_trading)
    f_kaynak = inspect.getsource(futures_trade_engine.futures_pozisyon_izle)
    assert "zaman_stop_doldu_mu" in p_kaynak,         "paper yolu ortak fonksiyonu çağırmıyor"
    assert "zaman_stop_doldu_mu" in f_kaynak,         "canlı yol ortak fonksiyonu çağırmıyor — §5.3 ayrışması"


# ═════════════════════════════════════════════════════════
# K-84 — TEMPO KAPANIŞLARI SAYMALI
# ═════════════════════════════════════════════════════════
def test_tempo_kapanmis_islemi_sayar():
    """Sağlık betiği "100 işlem" tahminini KAPANIŞLARDAN türetmeli.

    ── v58 (K-84) ───────────────────────────────────────────────
    Eski satır `(kapali + acik)` yani AÇILAN işlemleri sayıyordu ama
    "100 işlem" hedefiyle kıyaslıyordu. `karar_kurali.py` MIN_ISLEM=100'ü
    KAPANMIŞ işlemler üzerinden uyguluyor — kapanmamış pozisyonun PnL'i
    yok, hükme giremez.

    ÖLÇÜLEN SAPMA (2026-09-13, 37.4 saat): 11 açılan / 1 kapanmış
        gösterilen : 7.1 işlem/gün →  13 gün
        GERÇEK     : 0.64 kapanış/gün → 156 gün   (12 KAT iyimser)
    Kullanıcı "10 pozisyon açık, ilerlemiyor" derken bunu fark etmişti.
    """
    import inspect, re
    kaynak = inspect.getsource(__import__("kontrol_4h"))
    m = re.search(r'100 KAPANMIŞ işlem.*?\{100/kapanma', kaynak, re.S)
    assert m, ("Süre tahmini kapanış hızından türetilmiyor — açılan "
               "işlemleri sayan eski formül geri gelmiş olabilir (K-84)")
    assert "kapanma = kapali * 24 / gecen" in kaynak, (
        "Kapanma hızı hesabı yok — tahmin yine açılışlardan yapılıyor")


def test_tempo_acilma_hizini_da_gosterir():
    """KONTROL: açılma hızı DA gösterilmeli.

    Yalnızca kapanışa bakmak da yanıltır: açılış hiç olmuyorsa (bir kapı
    tıkıyorsa) bunu görmek gerekir. İki sayı birlikte anlamlı.
    """
    import inspect
    kaynak = inspect.getsource(__import__("kontrol_4h"))
    # Kelimeyi değil, ETİKETLİ SATIRI ara: "Açılma" kelimesi aşağıdaki
    # uyarı metninde de geçiyor, yalnızca ona bakmak testi zayıflatır
    # (mutasyonda yakalanmadı — §4.1).
    assert 'f"  Açılma  : {acilma' in kaynak, (
        "Açılma hızı satırı kaldırılmış — bir kapı tıkadığında "
        "(hiç işlem açılmıyorsa) fark edilmez")
    assert 'f"  KAPANMA : {kapanma' in kaynak, (
        "Kapanma hızı satırı kaldırılmış — hüküm süresi görünmez")


# ═════════════════════════════════════════════════════════
# K-83 — WATCHDOG SAĞLIKLI BOTU ÖLDÜRMESİN
# ═════════════════════════════════════════════════════════
def test_watchdog_esigi_tur_suresinden_uzun():
    """Watchdog eşiği, MEŞRU en uzun turdan uzun OLMALI.

    ── v58 (K-83) ───────────────────────────────────────────────
    600 sn, 5 coinli dönemde kalibre edilmişti (tur 66 sn). 50 coinde
    bar sınırındaki tam analiz turu 948 sn sürüyor → watchdog her bar
    sınırında sağlıklı botu donmuş sanır.

    ÖLÇÜLEN VAKA (2026-09-11 00:02): "2424s donma" deyip process'i
    yeniden başlattı. Bot DONMAMIŞTI — o 40 dakikada dakikada 25-55
    satır log yazıyordu (model eğitimi). 10 saatte İKİ kez oldu.
    Zararı: ısınma çöpe gidiyor, yeniden ısınma da uzun sürdüğü için
    döngüye girme riski var.
    """
    from config import WATCHDOG_MAX_SILENT, COIN_TUR_TIMEOUT
    assert WATCHDOG_MAX_SILENT > COIN_TUR_TIMEOUT, (
        f"watchdog eşiği {WATCHDOG_MAX_SILENT}s <= tur tavanı "
        f"{COIN_TUR_TIMEOUT}s — tek bir meşru uzun tur sahte alarm "
        f"üretir ve bot öldürülür (K-83)")


def test_watchdog_hala_gercek_donmayi_yakalar():
    """KONTROL: eşik sonsuza çekilmemeli.

    Bu olmadan "çok büyüt" regresyonu donma tespitini tamamen işlevsiz
    kılar — bot asılı kalır ve kimse fark etmez (§5.2 sessiz başarısızlık).
    """
    from config import WATCHDOG_MAX_SILENT, ANA_BAR_DK
    assert WATCHDOG_MAX_SILENT <= ANA_BAR_DK * 60, (
        f"watchdog eşiği {WATCHDOG_MAX_SILENT}s bir bardan uzun — gerçek "
        f"donma bir barı kaçırdıktan sonra fark edilir")


# ═════════════════════════════════════════════════════════
# K-82 — TUR İPTALİ HEP AYNI COİNLERİ AÇ BIRAKMASIN
# ═════════════════════════════════════════════════════════
def test_tur_sirasi_her_turda_kayar():
    """Coin sırası her turda kaymalı — kuyruk açlığı yapısal olarak bitsin.

    ── v58 (K-82) ───────────────────────────────────────────────
    Tur tavanı aşılınca `asyncio.gather` iptal ediliyor ve iptal HEP
    listenin sonunda vuruyordu. ÖLÇÜM (2026-09-10 22:28-22:52):
    kapsama 39/50'de TAKILDI; eksik 11 coinin 10'u listenin SON 10
    coiniydi (COTI, HBAR, ATOM, ETC, BCH, HEMI, JUP, ICP, THE, ETHFI).
    O coinler hiç sinyal üretemiyordu — 50 coin koymanın amacı boşa
    çıkıyordu.
    """
    import main
    coinler = [f"C{i}USDT" for i in range(10)]
    ilkler = {main._tur_sirasi(coinler, d)[0] for d in range(len(coinler))}
    assert ilkler == set(coinler), (
        f"Kaydırma tüm coinleri başa getirmiyor ({len(ilkler)}/{len(coinler)}) — "
        f"iptal sürerse aynı kuyruk aç kalır (K-82)")


def test_tur_sirasi_hicbir_coini_dusurmez():
    """KONTROL: kaydırma coin KAYBETMEMELİ.

    Bu olmadan "listeyi kes" gibi bir regresyon coinleri sessizce
    evrenden çıkarır ve üstteki test yine geçebilir.
    """
    import main
    coinler = [f"C{i}USDT" for i in range(10)]
    for d in (0, 3, 7, 25):
        s = main._tur_sirasi(coinler, d)
        assert sorted(s) == sorted(coinler), (
            f"döngü {d}: kaydırma coin düşürdü/çoğalttı "
            f"({len(s)} vs {len(coinler)})")
    assert main._tur_sirasi([], 5) == [], "boş liste çökertmemeli"


def test_tur_tavani_coin_sayisiyla_olceklenir():
    """Tur tavanı 50 coini analiz etmeye YETMELİ.

    600 sn 5 coin için kalibre edilmişti (tur 66 sn). 50 coinde tur
    sürekli aşıp iptal ediliyordu.
    """
    from config import COIN_TUR_TIMEOUT, COINS, ANALIZ_ESZAMANLI, ANA_BAR_DK
    gereken = len(COINS) / max(1, ANALIZ_ESZAMANLI) * 40    # ~40 sn/coin
    assert COIN_TUR_TIMEOUT >= gereken, (
        f"tavan {COIN_TUR_TIMEOUT}s < gereken ~{gereken:.0f}s "
        f"({len(COINS)} coin / {ANALIZ_ESZAMANLI} eşzamanlı) — tur iptal "
        f"edilir, kuyruk analiz edilmez (K-82)")
    assert COIN_TUR_TIMEOUT <= ANA_BAR_DK * 60 / 2, (
        f"tavan {COIN_TUR_TIMEOUT}s barın yarısını aşıyor — bir sonraki "
        f"bar gelmeden tur bitmeli")


# ═════════════════════════════════════════════════════════
# K-80 — SLOT TAVANI YAN LİMİTLE YUTULMASIN
# ═════════════════════════════════════════════════════════
def test_ayni_yon_tavani_slot_artisini_yutmamali():
    """`MAX_SAME_DIRECTION`, slot sayısını PRATİKTE kısıtlamamalı.

    ── v58 (K-80) ───────────────────────────────────────────────
    İşlem hızının darboğazı ölçüldü (§0.27): tutuş 13.6 saat × 3 slot
    = 5.3 işlem/gün → 100 işlem 19 gün. Slot 10'a çıkarıldı.
    AMA `MAX_SAME_DIRECTION=2` kalsaydı bot en fazla
    2 LONG + 2 SHORT = 4 pozisyon tutabilirdi — artış SESSİZCE
    yutulurdu. (5 coinli dönemde "Aynı yönde 2/2 → ATLANDI" günde
    130 kez tetiklenmiş, en baskın red sebebiydi.)

    Bu test SPESİFİK DEĞERLERİ değil İLİŞKİYİ kilitler: iki yönün
    toplam kapasitesi slot sayısını karşılamalı.
    """
    from config import MAX_OPEN_POSITIONS, MAX_SAME_DIRECTION
    kapasite = MAX_SAME_DIRECTION * 2          # LONG + SHORT
    assert kapasite >= MAX_OPEN_POSITIONS, (
        f"MAX_SAME_DIRECTION={MAX_SAME_DIRECTION} → pratik tavan "
        f"{kapasite} pozisyon, ama MAX_OPEN_POSITIONS={MAX_OPEN_POSITIONS}. "
        f"Slot artışı yan limitle yutuluyor (K-80).")


def test_yon_tavani_hala_koruma_sagliyor():
    """KONTROL: yön tavanı TAMAMEN kalkmamalı.

    Amacı korelasyon riski: kripto yüksek korelasyonlu, tüm slotları
    tek yöne doldurmak tek bir yönlü bahistir — piyasa dönerse hepsi
    birlikte stop olur. Bu olmadan "sonsuz yap" regresyonu korumayı
    sessizce kaldırır ve üstteki test yine geçer.
    """
    from config import MAX_OPEN_POSITIONS, MAX_SAME_DIRECTION
    assert MAX_SAME_DIRECTION < MAX_OPEN_POSITIONS, (
        f"MAX_SAME_DIRECTION={MAX_SAME_DIRECTION} >= "
        f"MAX_OPEN_POSITIONS={MAX_OPEN_POSITIONS} — tüm pozisyonlar tek "
        f"yönde açılabilir, korelasyon koruması yok")


def test_slot_sayisi_sermaye_limitini_asmamali():
    """Tüm slotlar dolduğunda marjin tavanı AŞILMAMALI.

    Aksi hâlde son slotlar hiç açılamaz — yine sessiz bir tavan olur.
    """
    from config import MAX_OPEN_POSITIONS, MAX_MARGIN_PCT, TRADE_USDT, BALANCE
    kullanim = MAX_OPEN_POSITIONS * TRADE_USDT / BALANCE * 100
    assert kullanim <= MAX_MARGIN_PCT, (
        f"{MAX_OPEN_POSITIONS} slot × {TRADE_USDT} USDT = %{kullanim:.1f} "
        f"marjin, tavan %{MAX_MARGIN_PCT} — son slotlar açılamaz")


# ═════════════════════════════════════════════════════════
# K-78 — CIRCUIT BREAKER SEMBOL BAŞINA
# ═════════════════════════════════════════════════════════
def test_bir_coinin_atrsi_digerlerini_durdurmaz():
    """Bir coinin yüksek ATR'si DİĞER coinleri durdurmamalı.

    ── v58 (K-78) ───────────────────────────────────────────────
    Durum tek global alandaydı (`_aktif`), ama tetikleyiciler sembol
    bazlı. ÖLÇÜLEN VAKA (2026-09-10 02:32, 50 coine geçişten 3 dk sonra):
        ATR çok yüksek PROMUSDT: %4.78 — 300s dur
        [SOLUSDT] Circuit Breaker aktif — analiz atlandı   ← başka coin
        [XRPUSDT] Circuit Breaker aktif — analiz atlandı   ← başka coin
    4 dakikada 17 tetiklenme. 50 coinde volatil altcoin her zaman
    bulunur → bot sürekli donar. K-71 ile aynı sınıf.
    """
    from risk.volatility_circuit_breaker import VolatilityCircuitBreaker
    cb = VolatilityCircuitBreaker(max_atr_pct=4.0)
    cb.atr_guncelle("PROMUSDT", 4.78, 100.0)      # %4.78 ATR → tetikler
    assert cb.kontrol("PROMUSDT") is False, \
        "Tetikleyen coin durdurulmadı (test kurulumu hatalı)"
    assert cb.kontrol("SOLUSDT") is True, (
        "Bir coinin ATR'si BAŞKA coini durdurdu — global alan geri "
        "gelmiş (K-78). 50 coinde bot sürekli donar.")


def test_tetikleyen_coin_gercekten_durur():
    """KONTROL: tetikleyen coin GERÇEKTEN durmalı.

    Bu olmadan "hep True döndür" regresyonu breaker'ı tamamen
    devre dışı bırakır ve üstteki test yine geçer.
    """
    from risk.volatility_circuit_breaker import VolatilityCircuitBreaker
    cb = VolatilityCircuitBreaker(max_atr_pct=4.0)
    assert cb.kontrol("XYZUSDT") is True, "Tetiklenmeden önce kapalıydı"
    cb.atr_guncelle("XYZUSDT", 9.0, 100.0)
    assert cb.kontrol("XYZUSDT") is False, \
        "ATR %9 olduğu hâlde coin durdurulmadı — koruma çalışmıyor"


def test_normal_altcoin_volatilitesi_engellenmez():
    """Sürekli yüksek ama NORMAL volatilite coini devre dışı BIRAKMAMALI.

    ── v58 (K-79) ───────────────────────────────────────────────
    `MAX_ATR_PCT=4.0` beş büyük coin için kalibre edilmişti. 50 coinlik
    evrende ATR aralığı ÖLÇÜLDÜ: BTC %1.05 … HEMI %9.04 (30 kat).
    Sonuç: 19 coin HER TURDA atlandı, panelde 50 yerine 31 coin göründü,
    19 saatte 894 tetiklenme oldu. Bunlar acil durum değil, o coinlerin
    NORMAL hâliydi — her biri hep AYNI değerle tetikleniyordu
    (medyan = maksimum).

    Kullanıcının 50 coin koyma amacı işlem hızıydı; breaker coinlerin
    %38'ini sessizce devre dışı bırakıp tam tersini yapıyordu.
    """
    from risk.volatility_circuit_breaker import VolatilityCircuitBreaker
    from config import MAX_ATR_PCT
    cb = VolatilityCircuitBreaker(max_atr_pct=MAX_ATR_PCT)
    # %5 ATR: NEAR/PUMP/PROM seviyesi — SL ≈ %7.5, işlenebilir.
    for _ in range(5):
        cb.atr_guncelle("NORMALUSDT", 5.0, 100.0)
    assert cb.kontrol("NORMALUSDT") is True, (
        f"ATR %5 (normal altcoin) coini durdurdu — MAX_ATR_PCT="
        f"{MAX_ATR_PCT} evrene göre çok düşük (K-79)")


def test_asiri_volatilite_hala_engellenir():
    """KONTROL: GERÇEKTEN aşırı volatilite hâlâ durdurulmalı.

    Bu olmadan "eşiği sonsuza çek" regresyonu korumayı tamamen
    kaldırır ve üstteki test yine geçer. %15 ATR → SL ≈ %22.
    """
    from risk.volatility_circuit_breaker import VolatilityCircuitBreaker
    from config import MAX_ATR_PCT
    cb = VolatilityCircuitBreaker(max_atr_pct=MAX_ATR_PCT)
    cb.atr_guncelle("CILGINUSDT", 15.0, 100.0)
    assert cb.kontrol("CILGINUSDT") is False, (
        f"ATR %15 olduğu hâlde coin durdurulmadı — MAX_ATR_PCT="
        f"{MAX_ATR_PCT} tavan olmaktan çıkmış, koruma yok")


def test_breaker_telegram_throttleini_atlamaz():
    """Breaker bildirimi rate-limit'i BYPASS ETMEMELİ.

    `force=True` throttle'ı atlıyordu; 50 coinde 4 dakikada 17 mesaj
    gitti. Log her tetiklenmeyi yazmaya devam eder (teşhis kaybolmaz),
    Telegram ise throttle'a tabidir.
    """
    from risk.volatility_circuit_breaker import VolatilityCircuitBreaker
    cagrilar = []

    def sahte_tg(mesaj, **kw):
        cagrilar.append(kw)

    cb = VolatilityCircuitBreaker(max_atr_pct=4.0, telegram_fn=sahte_tg)
    cb.atr_guncelle("ZZZUSDT", 9.0, 100.0)
    assert cagrilar, "Breaker tetiklendi ama Telegram'a hiç haber verilmedi"
    assert cagrilar[0].get("force") is not True, (
        "Breaker bildirimi force=True ile gönderiliyor — Telegram "
        "throttle'ı atlanıyor (K-78). 50 coinde 4 dakikada 17 mesaj gitti.")


# ═════════════════════════════════════════════════════════
# K-76 — REJİM EŞİĞİ ÇİFT CEZA / ULAŞILABİLİRLİK
# ═════════════════════════════════════════════════════════
def test_rejim_esigi_skor_cezasini_asmamali():
    """Eşik, o rejimin SKOR CEZASI hesaba katılınca ulaşılabilir kalmalı.

    ── v58 (K-76): ÇİFT CEZA ────────────────────────────────────
    `core/sinyal_skor.py` skoru rejime göre zaten düşürüyor:
        BEAR −3 · VOLATILE −2 · RANGE −1
    Eşik haritası AYNI rejimler için bir kez daha yükseltiliyordu
    (BEAR 7, VOLATILE 6). Sonuç ÖLÇÜLDÜ (2026-09-10, 4321 gözlem):
        VOLATILE  1031 gözlem → eşiği geçen: 0
        RANGE     1137 gözlem → eşiği geçen: 0
    Yani iki rejim tamamen ölüydü ve bu sessizdi.

    Bu test SPESİFİK DEĞERLERİ değil, İLİŞKİYİ kilitler: bir rejimin
    eşiği, o rejimde cezasız TREND eşiğine ceza eklenmiş hâlini
    aşarsa kapı yapısal olarak ulaşılamaz hâle gelir.
    """
    from engines.futures_trade_engine import rejim_ai_esigi
    CEZA = {"BEAR": 3, "VOLATILE": 2, "RANGE": 1, "TREND_UP": 0, "TREND_DOWN": 0}
    trend = rejim_ai_esigi("TREND_UP")
    for rejim, ceza in CEZA.items():
        esik = rejim_ai_esigi(rejim)
        ham_gerekli = esik + ceza          # LONG için gereken HAM skor
        assert ham_gerekli <= trend + 5, (
            f"{rejim}: eşik {esik} + skor cezası {ceza} = ham {ham_gerekli} "
            f"gerekiyor (TREND {trend}). Kapı ulaşılamaz hâle geldi — "
            f"bot bu rejimde hiç işlem açamaz (K-76)")


def test_hicbir_rejim_esigi_gozlenen_tavani_asmamali():
    """KONTROL: eşik, ölçülen skor tavanının üstüne çıkmamalı.

    2026-09-10 ölçümü: 4321 gözlemde |AI| tavanı 5, `|AI|>=6` HİÇ
    görülmedi. 6 ve 7 eşikleri bu yüzden ölüydü. Bu testin amacı
    "eşik 5 olsun" demek DEĞİL — eşiğin ölçülen aralığın dışına
    kaçmasını yakalamak.
    """
    from engines.futures_trade_engine import rejim_ai_esigi
    GOZLENEN_TAVAN = 5
    for rejim in ("TREND_UP", "TREND_DOWN", "RANGE", "BEAR", "VOLATILE"):
        esik = rejim_ai_esigi(rejim)
        assert esik <= GOZLENEN_TAVAN, (
            f"{rejim} eşiği {esik} > ölçülen tavan {GOZLENEN_TAVAN} — "
            f"kapı hiç açılmaz. Tavan değiştiyse ölçümü yenile, eşiği "
            f"körlemesine yükseltme.")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA KAPASİTE + BİLDİRİM MUHAFIZLARI — {len(testler)} test")
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
