# =========================================================
# ASTRA — VETO ZİNCİRİ TESTLERİ (v56)
# Çalıştırma: python tests/test_veto_zinciri.py
#
# Hedef: main.py::_execution_isle — GERÇEK EMİRLERİN tetiklendiği yer.
# 290 satır, 13 ayrı güvenlik kapısı, kapsam %17'ydi.
#
# Test edilen tek soru: HER KAPI GERÇEKTEN ENGELLİYOR MU?
#
# Bu, oturumda bulunan hataların türünü hedefler:
#   • C-4: çoklu borsa vetosu AttributeError ile atlanıyordu
#   • H-1: strateji doğrulayıcı NameError ile hiç çalışmıyordu
# İkisi de "kapı var sanılıyordu ama yoktu" vakasıydı.
#
# Emir gönderimi mock'lanır — hiçbir test borsaya çıkmaz.
# =========================================================
import sys, os, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# v57: ÜRETİM durum dosyalarına yazmayı engelle. Proje modülleri import
# EDİLMEDEN ÖNCE çağrılmalı — config.py yolları import anında okur.
from tests.izolasyon import izole_et; izole_et()

os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("BINANCE_API_SECRET", "")

import main


class Sahte:
    """Herhangi bir metoda sabit değer döndüren esnek sahte nesne."""
    def __init__(self, **kw): self.__dict__.update(kw)
    def __getattr__(self, ad): return lambda *a, **kw: None


class SahteMex:
    def __init__(self, guvenilir=True, sebep=""):
        self.guvenilir, self.sebep = guvenilir, sebep
        # Kod bu alanları da okuyor; eksikse AttributeError try/except'e
        # düşüp vetoyu ATLIYOR — testin sessizce yanlış çalışmasına yol açar.
        self.arbitraj_yon, self.arbitraj_gucu = None, 0.0


def _temel_sonuc(karar="📈 BUY", edge_gecti=True):
    """Tüm kapıları geçecek 'temiz' sinyal.

    NOT: edge kararı `edge_engine`'den DEĞİL, sinyal dict'indeki
    `edge_sonuc` alanından okunuyor (coin_analiz doldurur). Bunu mock'ta
    atlamak, edge testinin yanlış sebeple geçmesine yol açıyordu.
    """
    return {"sembol": "BTCUSDT", "karar": karar, "son_close": 60000.0,
            "son_atr": 600.0, "rejim": "TREND_UP", "ai_score": 7,
            "confidence": 80, "yukselis_guveni": 80,
            "sinyal_ts": time.time(),
            "edge_sonuc": {"gecti": edge_gecti, "edge_score": 90,
                           "sebep": "" if edge_gecti else "edge düşük"},
            "mtf_confluence": {"hizalama_skoru": 2, "cascade_blok": False}}


class Ortam:
    """main.py global'lerini test için geçici olarak değiştirir.

    _execution_isle modül düzeyi global'lere bağlı olduğu için
    (bağımlılık enjeksiyonu yok) test böyle kurulmak zorunda.
    Bu, modülerleştirmenin neden zor olduğunun da kanıtı.
    """
    ALANLAR = ["LIVE_TRADING", "kill_switch", "circuit_breaker", "correlation_eng",
               "multiexchange", "edge_engine", "risk_manager", "exec_engine",
               "strateji_engine", "_strategy_engine", "_strateji_onay",
               "watchdog", "order_engine"]

    def __init__(self, **ayarlar):
        self.ayarlar = ayarlar
        self.eski = {}
        self.gonderilen = []

    def __enter__(self):
        import data.binance_futures_client as bfc
        import engines.futures_trade_engine as fte
        self._bfc, self._fte = bfc, fte
        for a in self.ALANLAR:
            if hasattr(main, a):
                self.eski[a] = getattr(main, a)

        # Varsayılan: TÜM kapılar AÇIK (izin veren) — test edilen kapı kapatılır
        main.LIVE_TRADING    = True
        main.kill_switch     = Sahte(kontrol=lambda *a, **kw: True)
        main.circuit_breaker = Sahte(kontrol=lambda *a, **kw: True)
        main.correlation_eng = Sahte(pozisyon_acilabilir_mi=lambda *a, **kw: (True, ""))
        main.multiexchange   = Sahte(karsilastir=lambda *a, **kw: SahteMex(True))
        # v58 (K-103): ÇOKLU BORSA KAPISI `futures_trade_engine`'E TAŞINDI
        # ve ortak fonksiyon `data.multi_exchange.get_multiexchange()`
        # çağırıyor. Yalnızca main'deki kopyayı taklit etmek YETMEZ —
        # gerçek borsa sorgusu devreye girer ve kontrol testi ("tüm
        # kapılar açıkken emir gitmeli") kırmızıya döner.
        # (Aynı taklit-noktası kayması K-98'de de yaşandı.)
        import data.multi_exchange as _mx
        self._mx = _mx
        self._eski_mx = _mx.get_multiexchange
        _mx.get_multiexchange = lambda: main.multiexchange
        main.edge_engine     = Sahte(degerlendir=lambda *a, **kw: {"gecti": True, "edge_score": 90})
        main._strateji_onay  = {}
        main.risk_manager    = Sahte(
            dinamik_kaldirac_hesapla=lambda *a, **kw: 3,
            pozisyon_buyuklugu_hesapla=lambda *a, **kw: 60.0,
            tum_kontroller=lambda *a, **kw: (False, ""))
        main.strateji_engine = Sahte(karar_ver=lambda *a, **kw: {"islem_yap": True, "usdt": 60, "strateji": "T"})
        main._strategy_engine = main.strateji_engine
        # v58 (K-98): STRATEJİ KAPISI `futures_trade_engine`'E TAŞINDI.
        # Zincir artık `fte._strategy_engine`'i okuyor; yalnızca main'deki
        # kopyayı taklit etmek YETMEZ — gerçek motor devreye girer ve
        # sentetik fikstürü reddeder. Kontrol testi ("tüm kapılar açıkken
        # emir gitmeli") bu yüzden kırmızıya döndü; taklit noktası kaydı.
        self._eski_fte_se = getattr(fte, "_strategy_engine", None)

        # Emir gönderimini yakala
        gonderilen = self.gonderilen
        main.exec_engine = Sahte(
            pozisyon_ac=lambda *a, **kw: gonderilen.append(("ac", a, kw)),
            pozisyon_kapat=lambda *a, **kw: None)
        self._eski_submit = getattr(main, "order_engine", None)
        main.order_engine = Sahte(submit=lambda req: gonderilen.append(("submit", req)))

        # Borsa çağrıları
        self._eski_bfc = (bfc.futures_anlık_fiyat, bfc.pozisyon_var_mi,
                          bfc.futures_bakiye)
        bfc.futures_anlık_fiyat = lambda *a, **kw: 60000.0
        bfc.pozisyon_var_mi     = lambda *a, **kw: False
        bfc.futures_bakiye      = lambda *a, **kw: 5000.0
        main.futures_anlık_fiyat = bfc.futures_anlık_fiyat
        main.pozisyon_var_mi     = bfc.pozisyon_var_mi
        main.futures_bakiye      = bfc.futures_bakiye
        self._eski_sgm = fte.sinyal_gecerli_mi
        fte.sinyal_gecerli_mi = lambda *a, **kw: True

        # Test edilen kapıyı kapat
        for k, v in self.ayarlar.items():
            setattr(main, k, v)
        # v58 (K-98): SENKRON kwargs'TAN SONRA. Testler stratejiyi
        # `Ortam(_strategy_engine=red)` ile eziyor; senkronu önce yapsaydık
        # varsayılan (izin veren) motor zincire kalır, "strateji reddetti"
        # testi YANLIŞ SEBEPLE geçerdi.
        fte._strategy_engine = getattr(main, "_strategy_engine", None)
        return self

    def __exit__(self, *a):
        # v58 (K-103): taşınan çoklu borsa kapısını da geri al
        try:
            self._mx.get_multiexchange = self._eski_mx
        except Exception:
            pass
        # v58 (K-98): taşınan strateji motorunu da geri al
        try:
            self._fte._strategy_engine = self._eski_fte_se
        except Exception:
            pass
        for k, v in self.eski.items():
            setattr(main, k, v)
        (self._bfc.futures_anlık_fiyat, self._bfc.pozisyon_var_mi,
         self._bfc.futures_bakiye) = self._eski_bfc
        self._fte.sinyal_gecerli_mi = self._eski_sgm
        return False

    @property
    def emir_gitti(self):
        return len(self.gonderilen) > 0


def _veto_sayaci_sifirla():
    try:
        from core.teshis import _veto_sayac
        _veto_sayac.clear()
    except Exception:
        pass


# ═════════════════════════════════════════════════════════
# KONTROL TESTİ — kapılar açıkken emir GİTMELİ
# ═════════════════════════════════════════════════════════
def test_tum_kapilar_acikken_emir_gonderilir():
    """Bu test geçmezse aşağıdaki veto testleri ANLAMSIZDIR.

    'Hiçbir zaman emir gönderme' davranışı da tüm veto testlerini
    geçerdi — bu kontrol onu dışlar.
    """
    _veto_sayaci_sifirla()
    with Ortam() as o:
        main._execution_isle(_temel_sonuc())
        assert o.emir_gitti, (
            "Tüm kapılar açıkken emir GÖNDERİLMEDİ — veto testleri anlamsız "
            "olur (her şeyi engelleyen kod da onları geçer)")


# ═════════════════════════════════════════════════════════
# HER KAPI AYRI AYRI — engelliyor mu?
# ═════════════════════════════════════════════════════════
def test_live_trading_kapaliyken_emir_yok():
    _veto_sayaci_sifirla()
    with Ortam(LIVE_TRADING=False) as o:
        main._execution_isle(_temel_sonuc())
        assert not o.emir_gitti, "LIVE_TRADING=False iken GERÇEK EMİR gönderildi!"


def test_sinyal_yoksa_emir_yok():
    _veto_sayaci_sifirla()
    with Ortam() as o:
        main._execution_isle(_temel_sonuc(karar="⏳ WAIT"))
        assert not o.emir_gitti, "WAIT kararında emir gönderildi"


def test_kill_switch_engeller():
    _veto_sayaci_sifirla()
    with Ortam(kill_switch=Sahte(kontrol=lambda *a, **kw: False)) as o:
        main._execution_isle(_temel_sonuc())
        assert not o.emir_gitti, (
            "KILL SWITCH aktifken emir gönderildi — son savunma hattı çalışmıyor!")


def test_circuit_breaker_engeller():
    _veto_sayaci_sifirla()
    with Ortam(circuit_breaker=Sahte(kontrol=lambda *a, **kw: False)) as o:
        main._execution_isle(_temel_sonuc())
        assert not o.emir_gitti, "Circuit breaker aktifken emir gönderildi"


def test_coklu_borsa_vetosu_engeller():
    """C-4 REGRESYONU: Bu veto AttributeError yüzünden hiç çalışmıyordu.

    Binance fiyatı diğer borsalardan saparsa (manipülasyon/bad tick)
    işlem AÇILMAMALI.
    """
    _veto_sayaci_sifirla()
    with Ortam(multiexchange=Sahte(
            karsilastir=lambda *a, **kw: SahteMex(False, "fiyat sapması %3"))) as o:
        main._execution_isle(_temel_sonuc())
        assert not o.emir_gitti, (
            "ÇOKLU BORSA VETOSU çalışmadı — manipüle/hatalı fiyattan işlem "
            "açılabilir (C-4 regresyonu)")


def test_korelasyon_limiti_engeller():
    _veto_sayaci_sifirla()
    with Ortam(correlation_eng=Sahte(
            pozisyon_acilabilir_mi=lambda *a, **kw: (False, "majors limiti"))) as o:
        main._execution_isle(_temel_sonuc())
        assert not o.emir_gitti, "Korelasyon limiti aşıldı ama emir gönderildi"


def test_edge_engine_engeller():
    """Edge filtresi geçmediyse işlem açılmamalı.

    Edge kararı sinyal dict'indeki `edge_sonuc` alanından okunuyor
    (edge_engine nesnesinden değil) — mock'u yanlış yere koymak testin
    yanlış sebeple geçmesine yol açıyordu.
    """
    _veto_sayaci_sifirla()
    with Ortam() as o:
        main._execution_isle(_temel_sonuc(edge_gecti=False))
        assert not o.emir_gitti, "Edge filtresi geçmedi ama emir gönderildi"


def test_strateji_reddi_engeller():
    _veto_sayaci_sifirla()
    red = Sahte(karar_ver=lambda *a, **kw: {"islem_yap": False, "sebep": "rejim uygun değil"})
    with Ortam(strateji_engine=red, _strategy_engine=red) as o:
        main._execution_isle(_temel_sonuc())
        assert not o.emir_gitti, "Strateji reddetti ama emir gönderildi"


def test_dayaniklilik_kapisi_engeller():
    """H-1 REGRESYONU: Bu kapı NameError yüzünden v24'ten beri hiç çalışmamıştı.

    İstatistiksel olarak geçersizlenmiş coinde yeni pozisyon AÇILMAMALI.
    """
    # NOT: _strateji_onay {sembol: bool} tutar (main.py:174, 514).
    # Kapı `is False` ile karşılaştırdığı için değer TAM OLARAK False olmalı;
    # dict/0/None geçmek kapıyı sessizce atlatır.
    _veto_sayaci_sifirla()
    with Ortam(_strateji_onay={"BTCUSDT": False}) as o:
        main._execution_isle(_temel_sonuc())
        assert not o.emir_gitti, (
            "DAYANIKLILIK KAPISI çalışmadı — istatistiksel olarak geçersiz "
            "coinde işlem açılıyor (H-1 regresyonu)")


def test_dayaniklilik_onayliysa_engellemez():
    """Kontrol: onaylı coin gereksiz engellenmemeli."""
    _veto_sayaci_sifirla()
    with Ortam(_strateji_onay={"BTCUSDT": True}) as o:
        main._execution_isle(_temel_sonuc())
        assert o.emir_gitti, "Onaylı coinde işlem gereksiz engellendi"


def test_sinyal_filtresi_engeller():
    _veto_sayaci_sifirla()
    import engines.futures_trade_engine as fte
    with Ortam() as o:
        eski = fte.sinyal_gecerli_mi
        fte.sinyal_gecerli_mi = lambda *a, **kw: False
        try:
            main._execution_isle(_temel_sonuc())
        finally:
            fte.sinyal_gecerli_mi = eski
        assert not o.emir_gitti, "Sinyal filtresi reddetti ama emir gönderildi"


def test_gec_giris_slippage_engeller():
    """Sinyal sonrası fiyat aleyhe çok kaçtıysa kovalama YAPILMAMALI."""
    _veto_sayaci_sifirla()
    import data.binance_futures_client as bfc
    with Ortam() as o:
        eski = bfc.futures_anlık_fiyat
        # BUY sinyali ama fiyat %2 yukarı kaçmış (aleyhte, eşik ~%0.35)
        bfc.futures_anlık_fiyat = lambda *a, **kw: 61200.0
        main.futures_anlık_fiyat = bfc.futures_anlık_fiyat
        try:
            main._execution_isle(_temel_sonuc())
        finally:
            bfc.futures_anlık_fiyat = eski
            main.futures_anlık_fiyat = eski
        assert not o.emir_gitti, (
            "Fiyat %2 aleyhe kaçmışken emir gönderildi — geç giriş koruması yok")


def test_mevcut_pozisyon_varsa_tekrar_acilmaz():
    """Aynı yönde pozisyon zaten varsa ikinci kez açılmamalı."""
    _veto_sayaci_sifirla()
    import data.binance_futures_client as bfc
    with Ortam() as o:
        eski = bfc.pozisyon_var_mi
        bfc.pozisyon_var_mi = lambda sembol, yon=None, *a, **kw: (yon == "LONG")
        main.pozisyon_var_mi = bfc.pozisyon_var_mi
        try:
            main._execution_isle(_temel_sonuc())
        finally:
            bfc.pozisyon_var_mi = eski
            main.pozisyon_var_mi = eski
        assert not o.emir_gitti, "Aynı yönde pozisyon varken ikinci emir gönderildi"


def test_veto_sebepleri_kaydediliyor():
    """Her veto teşhis sayacına yazılmalı — /neden komutu buna dayanıyor."""
    from core.teshis import _veto_sayac
    _veto_sayaci_sifirla()
    with Ortam(kill_switch=Sahte(kontrol=lambda *a, **kw: False)):
        main._execution_isle(_temel_sonuc())
    assert _veto_sayac, "Veto kaydedilmedi — /neden raporu boş kalır"
    assert any("kill" in k.lower() for k in _veto_sayac), \
        f"kill_switch vetosu kaydedilmemiş: {dict(_veto_sayac)}"


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA VETO ZİNCİRİ TESTLERİ — {len(testler)} test")
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
