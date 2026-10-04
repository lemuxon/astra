# =========================================================
# ASTRA — SİNYAL VETO ZİNCİRİ PAPER ↔ CANLI ORTAK (v58, K-97)
# Çalıştırma: python tests/test_veto_zinciri_ortak.py
#
# MTF cascade + MTF hizalama + EdgeEngine `main.py::_execution_isle`
# içine gömülüydü; o fonksiyon `if not LIVE_TRADING: return` ile
# başladığı için bu üç kapı PAPER YOLUNDA HİÇ ÇALIŞMIYORDU.
#
# ÖLÇÜLDÜ (2026-09-14 07:15, saniyesi saniyesine):
#   07:15:13.392  [TRADE AÇILDI] #1 ASTERUSDT      ← paper AÇTI
#   07:15:14.640  [EXEC ISLE] ASTERUSDT MTF hizalama yok → atlandı
#   07:16:01.493  [TRADE AÇILDI] #2 AAVEUSDT       ← paper AÇTI
#   07:16:02.776  [EXEC ISLE] AAVEUSDT MTF hizalama yok → atlandı
# Aynı sembol, aynı saniye: paper açtı, canlı reddetti. Toplanan
# örneklem canlıyı TEMSİL ETMİYORDU (§5.3). §6.0'ın kapanışı.
#
# Ağ, veritabanı ve gerçek emir kullanılmaz.
# =========================================================
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

from engines.futures_trade_engine import sinyal_veto_zinciri

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sonuc(**ek):
    """Zincirin TÜM kapılarından geçebilecek GERÇEKÇİ bir sinyal.

    ⚠️ v58 (K-98): `ai_score`/`confidence`/`rejim`/`karar` EKLENDİ.
    Zincirin sonuna `sinyal_gecerli_mi` (rejim eşiği dahil) eklenince
    minimal fikstür 4 testi birden kırdı — kusur KODDA DEĞİL,
    FİKSTÜRDEYDİ. §0.1'in dersi (bu oturumda üçüncü kez): fikstür
    üretimdeki kurala uymalı; üretimde `coin_analiz` bu alanları HER
    ZAMAN üretiyor.
    """
    s = {"sembol": "TESTUSDT",
         "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3},
         "edge_sonuc": {"gecti": True, "sebep": ""},
         "ai_score": 9, "confidence": 95, "rejim": "RANGE",
         "karar": "🚀 STRONG BUY"}
    s.update(ek)
    return s


# ── ÜÇ KAPI DA ÇALIŞIYOR ────────────────────────────────────────────
def test_cascade_bloklu_ise_veto():
    g, sebep, _ = sinyal_veto_zinciri(
        _sonuc(mtf_confluence={"bloklu": True, "hizalama_skoru": 3}), "LONG")
    assert g is False and sebep == "mtf_cascade"


def test_hizalama_sifirsa_veto():
    g, sebep, _ = sinyal_veto_zinciri(
        _sonuc(mtf_confluence={"bloklu": False, "hizalama_skoru": 0}), "LONG")
    assert g is False and sebep == "mtf_hizalama_yok"


def test_edge_gecmezse_veto():
    g, sebep, _ = sinyal_veto_zinciri(
        _sonuc(edge_sonuc={"gecti": False, "sebep": "AI skor düşük"}), "LONG")
    assert g is False and sebep == "edge_engine"


def test_zayif_hizalamada_pozisyon_kuculur():
    """hizalama_skoru == 1 → veto DEĞİL, %60 pozisyon (canlıyla aynı)."""
    g, sebep, carpan = sinyal_veto_zinciri(
        _sonuc(mtf_confluence={"bloklu": False, "hizalama_skoru": 1}), "LONG")
    assert g is True and sebep == ""
    assert abs(carpan - 0.6) < 1e-9, f"çarpan {carpan}, beklenen 0.6"


# ── KONTROL TESTLERİ (§4.1) — "hep veto" da üsttekileri geçerdi ──────
def test_temiz_sinyal_GECER():
    """Kapılar açıkken işlem AÇILABİLMELİ — yoksa zincir her şeyi keser."""
    g, sebep, carpan = sinyal_veto_zinciri(_sonuc(), "LONG")
    assert g is True, f"temiz sinyal reddedildi: {sebep}"
    assert carpan == 1.0


def test_eksik_edge_FAIL_CLOSED():
    """§5.1: `edge_sonuc` yoksa 'sorun yok' SAYMA.

    Canlı yol `edge.get("gecti", False)` ile fail-closed davranıyordu;
    taşırken bu korunmalı.
    """
    s = _sonuc(); del s["edge_sonuc"]
    g, sebep, _ = sinyal_veto_zinciri(s, "LONG")
    assert g is False and sebep == "edge_engine"


def test_eksik_hizalama_ESKI_VARSAYILANI_korur():
    """KONTROL: `hizalama_skoru` yoksa 2 sayılır (veto YOK).

    Canlı yol `mtf.get("hizalama_skoru", 2)` kullanıyordu. Taşırken
    varsayılanı 0'a çevirmek SESSİZ bir davranış değişikliği olurdu.
    """
    g, sebep, carpan = sinyal_veto_zinciri(
        _sonuc(mtf_confluence={"bloklu": False}), "LONG")
    assert g is True, f"eksik hizalama veto üretti: {sebep}"
    assert carpan == 1.0


def test_sira_cascade_once():
    """Cascade, hizalamadan ÖNCE değerlendirilmeli (canlıdaki sıra)."""
    g, sebep, _ = sinyal_veto_zinciri(
        _sonuc(mtf_confluence={"bloklu": True, "hizalama_skoru": 0}), "LONG")
    assert sebep == "mtf_cascade", f"sıra değişmiş: {sebep}"


# ── İKİ YOL DA AYNI FONKSİYONU ÇAĞIRIYOR ───────────────────────────
def test_paper_veto_zincirini_GERCEKTEN_uyguluyor():
    """DAVRANIŞSAL: paper, MTF vetosu olan sinyali AÇMAMALI.

    ⚠️ BU TESTİN İLK HÂLİ ZAYIFTI ve mutasyonda KAÇTI. Kaynakta
    `"sinyal_veto_zinciri" in kod` arıyordu — ama o ad İMPORT
    SATIRINDA da geçiyor, dolayısıyla çağrıyı sabit `True` ile
    değiştiren mutasyon testi GEÇTİ.

    §0.29'da K-86 için birebir aynısı yazılmıştı ("islem_kaldiraci
    kelimesini arıyordu, import satırında da geçiyordu"). Aynı tuzağa
    tekrar düşüldü ➜ tek güvenilir yol: gerçek `_filtre_gec`'i sür.
    """
    from engines.paper_trading import PaperTrader
    pt = PaperTrader.__new__(PaperTrader)      # __init__ yan etkisiz kalsın

    # `_sinyal_kalitesi_gecer`'i geçir; ölçmek istediğimiz SONRAKİ kapı.
    pt._sinyal_kalitesi_gecer = lambda *a, **k: True

    vetolu = _sonuc(mtf_confluence={"bloklu": True, "hizalama_skoru": 3})
    assert pt._filtre_gec(vetolu, "LONG") is False, (
        "paper MTF cascade vetosunu UYGULAMIYOR — canlı reddederken "
        "paper açıyor (§5.3 ihlali, K-97)")

    hizalamasiz = _sonuc(mtf_confluence={"bloklu": False, "hizalama_skoru": 0})
    assert pt._filtre_gec(hizalamasiz, "LONG") is False, (
        "paper MTF hizalama vetosunu uygulamıyor")


def test_canli_yol_ortak_zinciri_cagiriyor():
    """main.py tarafı: ADI değil, ATAMAYI ara (import satırı yanıltmasın)."""
    kod = open(os.path.join(KOK, "main.py"), encoding="utf-8").read()
    satirlar = [s for s in kod.splitlines() if not s.lstrip().startswith("#")]
    govde = "\n".join(satirlar)
    assert "= sinyal_veto_zinciri(" in govde, (
        "main.py ortak zinciri ÇAĞIRMIYOR (import yeterli değil)")


def test_paper_mtf_carpanini_pozisyona_uyguluyor():
    """Zayıf hizalamada boyut da eşitlenmeli, yoksa §5.3 yarım kapanır."""
    kod = open(os.path.join(KOK, "engines", "paper_trading.py"),
               encoding="utf-8").read()
    satirlar = [s for s in kod.splitlines() if not s.lstrip().startswith("#")]
    govde = "\n".join(satirlar)
    assert "_mtf_carpan" in govde, "paper çarpanı okumuyor"
    assert "usdt_boyut *= _carpan" in govde, "paper çarpanı boyuta UYGULAMIYOR"


# ═════════════════════════════════════════════════════════
# K-98 — STRATEJİ + SİNYAL FİLTRESİ + KILL SWITCH
# ═════════════════════════════════════════════════════════
class _SahteStrateji:
    def __init__(self, izin, sebep="Trend follow koşulu sağlanmadı"):
        self.izin, self.sebep, self.cagrildi = izin, sebep, 0

    def karar_ver(self, sonuc, bakiye):
        self.cagrildi += 1
        if not self.izin:
            return {"islem_yap": False, "sebep": self.sebep}
        return {"islem_yap": True, "strateji": "TREND_FOLLOW", "usdt": 42}


def _strateji_ile(motor):
    """Strateji motorunu geçici kaydet; geri alıcı döndür."""
    import engines.futures_trade_engine as fte
    asil = fte._strategy_engine
    fte._strategy_engine = motor
    return lambda: setattr(fte, "_strategy_engine", asil)


def test_strateji_reddi_zincirde_UYGULANIYOR():
    """K-98'in ta kendisi: canlı vetoların %12'siydi, paper'da YOKTU.

    K-97'den sonra açılan İLK paper işlemi (PAXGUSDT SHORT, 2026-09-14
    19:21) canlıda tam bu kapıya takılmıştı.
    """
    geri = _strateji_ile(_SahteStrateji(izin=False))
    try:
        g, sebep, _ = sinyal_veto_zinciri(_sonuc(), "LONG", bakiye_fn=lambda: 10000.0)
        assert g is False and sebep == "strateji_red", f"({g}, {sebep})"
    finally:
        geri()


def test_strateji_izin_verirse_alanlari_yaziyor():
    """KONTROL: strateji GEÇERSE zincir devam etmeli ve alanları yazmalı."""
    geri = _strateji_ile(_SahteStrateji(izin=True))
    try:
        s = _sonuc()
        g, sebep, _ = sinyal_veto_zinciri(s, "LONG", bakiye_fn=lambda: 10000.0)
        assert g is True, f"strateji izin verdi ama zincir reddetti: {sebep}"
        assert s.get("strateji") == "TREND_FOLLOW"
        assert s.get("trade_usdt") == 42
    finally:
        geri()


def test_bakiye_TEMBEL_cagriliyor():
    """MTF'de ölen sinyalde bakiye İSTENMEMELİ (gereksiz REST + 429).

    `bakiye_fn` erken çağrılsaydı, zaten vetolanacak her sinyal için
    ağ isteği yapılırdı — v55'te bilerek kaldırılan maliyet.
    """
    cagri = {"n": 0}

    def _bakiye():
        cagri["n"] += 1
        return 10000.0

    geri = _strateji_ile(_SahteStrateji(izin=True))
    try:
        sinyal_veto_zinciri(
            _sonuc(mtf_confluence={"bloklu": True, "hizalama_skoru": 3}),
            "LONG", bakiye_fn=_bakiye)
        assert cagri["n"] == 0, "cascade'de ölen sinyalde bakiye çekildi"
        sinyal_veto_zinciri(_sonuc(), "LONG", bakiye_fn=_bakiye)
        assert cagri["n"] == 1, "strateji kapısında bakiye çekilmedi"
    finally:
        geri()


def test_bakiye_alinamazsa_FAIL_CLOSED():
    """§5.1: bakiye okunamıyorsa strateji kapısı ATLANAMAZ."""
    def _patla():
        raise RuntimeError("ağ yok")

    geri = _strateji_ile(_SahteStrateji(izin=True))
    try:
        g, sebep, _ = sinyal_veto_zinciri(_sonuc(), "LONG", bakiye_fn=_patla)
        assert g is False, "bakiye hatasında zincir GEÇİRDİ (fail-open)"
        assert sebep == "strateji_bakiye_hata"
    finally:
        geri()


def test_sinyal_filtresi_zincirde_UYGULANIYOR():
    """Zayıf sinyal, son kapıda (rejim eşiği dahil) reddedilmeli.

    ⚠️ BU TEST SONRADAN EKLENDİ. Mutasyon koşusunda `sinyal_gecerli_mi`
    çağrısını öldüren varyant KAÇTI — çünkü tüm fikstürlerim ai=9/conf=95
    ile o kapıdan zaten GEÇİYORDU. Bir kapıyı test etmek için, o kapının
    TEK BAŞINA reddedeceği bir girdi gerekir; aksi halde kapı silinse de
    testler yeşil kalır.

    (Canlı sayacı 0 görünüyordu ama bu da maskelemeydi: zincirde
    `strateji_red`'den sonra geldiği için sinyaller ona ulaşmıyordu.)
    """
    geri = _strateji_ile(_SahteStrateji(izin=True))
    try:
        zayif = _sonuc(ai_score=1, confidence=30, karar="📊 WEAK BUY")
        g, sebep, _ = sinyal_veto_zinciri(zayif, "LONG", bakiye_fn=lambda: 10000.0)
        assert g is False, "zayıf sinyal son kapıdan GEÇTİ"
        assert sebep == "sinyal_filtresi", f"beklenen sinyal_filtresi, gelen {sebep}"
    finally:
        geri()


def test_paper_kill_switch_KONTROL_ediyor():
    """DAVRANIŞSAL: paper switch'i besliyordu ama okumuyordu (K-98).

    Besleyip okumamak, sayaç tutup bakmamaktır: switch tetiklenince
    canlı durur, paper işlem açmaya devam ederdi.
    """
    from engines.paper_trading import PaperTrader
    import engines.kill_switch as ks

    pt = PaperTrader.__new__(PaperTrader)
    pt._sinyal_kalitesi_gecer = lambda *a, **k: True
    pt.bakiye = 10000.0

    class _Kapali:
        def kontrol(self): return False

    asil = ks.get_kill_switch
    try:
        ks.get_kill_switch = lambda: _Kapali()
        assert pt._filtre_gec(_sonuc(), "LONG") is False, (
            "kill switch KAPALI iken paper işlem açıyor (K-98)")
    finally:
        ks.get_kill_switch = asil


# ═════════════════════════════════════════════════════════
# K-103 — ÇOKLU BORSA KAPISI PAPER'DA DA VAR
# ═════════════════════════════════════════════════════════
def test_coklu_borsa_sapmada_VETO():
    """Binance medyandan çok saparsa işlem AÇILMAMALI.

    Amaç "başka borsada işlem yap" değil — kimsenin görmediği bir
    Binance fiyatına güvenmemek (K-15: testnet'te gerçek piyasada
    olmayan sıçrama sahte "TP" üretmişti).
    """
    from engines.futures_trade_engine import coklu_borsa_gecerli_mi
    import data.multi_exchange as mx

    class _Sonuc:
        guvenilir = False
        sebep = "Binance medyandan %5.00 sapıyor"
        arbitraj_yon = None
        arbitraj_gucu = 0.0

    class _Mex:
        def karsilastir(self, sembol, fiyat): return _Sonuc()

    asil = mx.get_multiexchange
    try:
        mx.get_multiexchange = lambda: _Mex()
        ok, sebep = coklu_borsa_gecerli_mi("TESTUSDT", 100.0, "LONG", {})
        assert ok is False and "sapıyor" in sebep
    finally:
        mx.get_multiexchange = asil


def test_coklu_borsa_HATADA_fail_open():
    """KONTROL: OKX'in API'si bozuk diye TÜM işlemler durmamalı.

    Erişilemeyen borsa durumu `karsilastir` içinde ele alınıyor
    (kaynak==1 → güven ver); buradaki istisna gerçek arızadır ve
    canlının davranışı da fail-open. §5.3 gereği birebir korundu.
    """
    from engines.futures_trade_engine import coklu_borsa_gecerli_mi
    import data.multi_exchange as mx

    asil = mx.get_multiexchange
    try:
        def _patla(): raise RuntimeError("borsa erişilemedi")
        mx.get_multiexchange = _patla
        ok, _ = coklu_borsa_gecerli_mi("TESTUSDT", 100.0, "LONG", {})
        assert ok is True, "hata hâlinde işlem engellendi (fail-closed) — canlıdan ayrışır"
    finally:
        mx.get_multiexchange = asil


def test_paper_coklu_borsa_kapisini_UYGULUYOR():
    """DAVRANIŞSAL: paper da bu kapıdan geçmeli (K-103).

    K-98'de "0 ateşleme" diye bırakılmıştı; sonra 347 kez ateşledi ve
    paper canlıdan %4 gevşek kaldı. "Şu an ateşlemiyor" kalıcı bir
    gerekçe değil.
    """
    from engines.paper_trading import PaperTrader
    import data.multi_exchange as mx

    class _Sonuc:
        guvenilir = False
        sebep = "şüpheli fiyat"
        arbitraj_yon = None
        arbitraj_gucu = 0.0

    class _Mex:
        def karsilastir(self, sembol, fiyat): return _Sonuc()

    pt = PaperTrader.__new__(PaperTrader)
    pt._sinyal_kalitesi_gecer = lambda *a, **k: True
    pt.bakiye = 10000.0

    asil = mx.get_multiexchange
    try:
        mx.get_multiexchange = lambda: _Mex()
        s = _sonuc(); s["son_close"] = 100.0
        assert pt._filtre_gec(s, "LONG") is False, (
            "paper çoklu borsa vetosunu UYGULAMIYOR (K-103)")
    finally:
        mx.get_multiexchange = asil


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA VETO ZİNCİRİ ORTAK (K-97) — {len(testler)} test")
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
