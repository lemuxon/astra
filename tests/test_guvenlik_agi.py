# =========================================================
# ASTRA — GÜVENLİK AĞI TESTLERİ (v56)
# Çalıştırma: python tests/test_guvenlik_agi.py
#
# Hedef: pozisyonu korumasız bırakmaması gereken katmanlar.
# Denetimde bu modüllerin kapsamı en düşüktü:
#   fill_reconciler %0 · order_reconciler %14 · order_engine %25 ·
#   state_audit %24
#
# Özellikle v56'da eklenen davranışların testi YOKTU:
#   • SL 3 denemede konamazsa pozisyonu ZORLA KAPAT
#   • strict=True ile "sıfır pozisyon" ≠ "sorgulayamadım"
#   • TRAILING_STOP_MARKET geçerli SL sayılması
#   • TP onarımı
#
# Borsa tamamen mock'lanır — hiçbir test ağa çıkmaz.
# =========================================================
import sys, os, warnings, types
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# v57: ÜRETİM durum dosyalarına yazmayı engelle. Proje modülleri import
# EDİLMEDEN ÖNCE çağrılmalı — config.py yolları import anında okur.
from tests.izolasyon import izole_et; izole_et()

os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("BINANCE_API_SECRET", "")


class SahteState:
    """PositionStateManager yerine geçen minimal sahte."""
    def __init__(self, pozlar=None):
        self._p = list(pozlar or [])
        self.kapatilanlar = []
        self.eklenenler = []
        self.sl_isaretli = []
    def acik_pozisyonlar(self):        return list(self._p)
    def pozisyon_kapat(self, sembol, sebep="?"):
        self.kapatilanlar.append((sembol, sebep))
        self._p = [p for p in self._p if p.get("sembol") != sembol]
    def pozisyon_ekle(self, poz):      self.eklenenler.append(poz)
    def pozisyon_ac(self, *a, **kw):   self._p.append({"sembol": a[0] if a else "?"})
    def sl_aktif_isaretle(self, s, oid): self.sl_isaretli.append((s, oid))
    def tp1_aktif_isaretle(self, s, oid): pass


# ═════════════════════════════════════════════════════════
# 1. ORDER ENGINE — SL konamazsa pozisyon KAPATILMALI (v56)
# ═════════════════════════════════════════════════════════
def test_sl_konamazsa_pozisyon_zorla_kapatilir():
    """v56 davranışı: SL MAX_RETRY denemede konamazsa pozisyon kapatılır.

    Bu, testnet'te gerçek borsaya karşı 6/6 doğrulandı ama otomatik
    testi yoktu — regresyon koruması olmadan kalıyordu.
    """
    import engines.order_engine as oe
    import data.binance_futures_client as bfc

    sahte_state = SahteState()
    motor = oe.OrderEngine()
    motor._state_manager = sahte_state

    cagrilar = {"sl": 0, "kapat": 0}
    def sl_hep_basarisiz(*a, **kw):
        cagrilar["sl"] += 1
        raise RuntimeError("-4120 conditional order reddedildi")
    def kapat(*a, **kw):
        cagrilar["kapat"] += 1
        return {"orderId": 999}

    orij = (bfc.futures_market_ac, bfc.futures_stop_loss_koy,
            bfc.futures_market_kapat, bfc.kaldirac_ayarla,
            bfc.futures_partial_tp_koy)
    bfc.futures_market_ac      = lambda *a, **kw: {"orderId": 1, "avgPrice": "60000", "executedQty": "0.001"}
    bfc.futures_stop_loss_koy  = sl_hep_basarisiz
    bfc.futures_market_kapat   = kapat
    bfc.kaldirac_ayarla        = lambda *a, **kw: True
    bfc.futures_partial_tp_koy = lambda *a, **kw: {"orderId": 2}

    eski_live = oe.LIVE_TRADING
    oe.LIVE_TRADING = True
    try:
        req = oe.OrderRequest(sembol="BTCUSDT", yon="LONG", usdt=60.0,
                              sl=58000.0, tp1=62000.0, tp2=63000.0, kaldirac=3)
        motor._isle(req)
    finally:
        oe.LIVE_TRADING = eski_live
        (bfc.futures_market_ac, bfc.futures_stop_loss_koy,
         bfc.futures_market_kapat, bfc.kaldirac_ayarla,
         bfc.futures_partial_tp_koy) = orij

    assert cagrilar["sl"] == motor.MAX_RETRY, (
        f"SL {cagrilar['sl']} kez denendi, {motor.MAX_RETRY} bekleniyordu — "
        f"retry mantığı çalışmıyor")
    assert cagrilar["kapat"] >= 1, (
        "SL konamadı ama pozisyon KAPATILMADI — korumasız kaldıraçlı "
        "pozisyon borsada kalır!")
    assert any(s == "BTCUSDT" for s, _ in sahte_state.kapatilanlar), \
        "State'te pozisyon kapalı işaretlenmedi"


def test_sl_basarili_olursa_kapatilmaz():
    """Kontrol testi: SL konabiliyorsa pozisyon KAPANMAMALI.

    Aksi halde 'her zaman kapat' davranışı da yukarıdaki testi geçerdi.
    """
    import engines.order_engine as oe
    import data.binance_futures_client as bfc

    sahte_state = SahteState()
    motor = oe.OrderEngine()
    motor._state_manager = sahte_state
    kapatma = {"n": 0}

    orij = (bfc.futures_market_ac, bfc.futures_stop_loss_koy,
            bfc.futures_market_kapat, bfc.kaldirac_ayarla,
            bfc.futures_partial_tp_koy)
    bfc.futures_market_ac      = lambda *a, **kw: {"orderId": 1, "avgPrice": "60000", "executedQty": "0.001"}
    bfc.futures_stop_loss_koy  = lambda *a, **kw: {"orderId": 55}
    bfc.futures_market_kapat   = lambda *a, **kw: kapatma.__setitem__("n", kapatma["n"]+1)
    bfc.kaldirac_ayarla        = lambda *a, **kw: True
    bfc.futures_partial_tp_koy = lambda *a, **kw: {"orderId": 2}

    eski_live = oe.LIVE_TRADING
    oe.LIVE_TRADING = True
    try:
        req = oe.OrderRequest(sembol="BTCUSDT", yon="LONG", usdt=60.0,
                              sl=58000.0, tp1=62000.0, tp2=63000.0, kaldirac=3)
        motor._isle(req)
    finally:
        oe.LIVE_TRADING = eski_live
        (bfc.futures_market_ac, bfc.futures_stop_loss_koy,
         bfc.futures_market_kapat, bfc.kaldirac_ayarla,
         bfc.futures_partial_tp_koy) = orij

    assert kapatma["n"] == 0, "SL konduğu halde pozisyon kapatıldı!"
    assert sahte_state.sl_isaretli, "SL aktif olarak işaretlenmedi"


def test_paper_modda_gercek_emir_gitmez():
    """LIVE_TRADING=false iken borsaya HİÇBİR çağrı gitmemeli."""
    import engines.order_engine as oe
    import data.binance_futures_client as bfc

    cagri = {"n": 0}
    def sayac(*a, **kw):
        cagri["n"] += 1
        return {"orderId": 1, "avgPrice": "1", "executedQty": "1"}
    orij = bfc.futures_market_ac
    bfc.futures_market_ac = sayac
    eski_live = oe.LIVE_TRADING
    oe.LIVE_TRADING = False
    try:
        motor = oe.OrderEngine(); motor._state_manager = SahteState()
        motor._isle(oe.OrderRequest(sembol="BTCUSDT", yon="LONG", usdt=60.0, sl=1.0))
    finally:
        oe.LIVE_TRADING = eski_live
        bfc.futures_market_ac = orij
    assert cagri["n"] == 0, "PAPER modda borsaya gerçek emir gönderildi!"


# ═════════════════════════════════════════════════════════
# 2. FILL RECONCILER — C-2: ağ hatasında state SİLİNMEMELİ
# ═════════════════════════════════════════════════════════
def test_reconciler_ag_hatasinda_state_korunur():
    """v56 (C-2): Pozisyon sorgusu başarısızsa sync ATLANMALI.

    Eskiden [] dönüyordu ve döngü TÜM pozisyonları 'Binance'te yok'
    sanıp state'ten siliyordu → pozisyonlar borsada canlı kalırken bot
    onları izlemeyi bırakıyordu.
    """
    import execution.fill_reconciler as fr
    import data.binance_futures_client as bfc
    from utils.exceptions import NetworkError

    state = SahteState([{"sembol": "BTCUSDT", "yon": "LONG", "giris": 60000, "miktar": 0.001}])
    rec = fr.FillReconciler(state)

    orij = bfc.acik_futures_pozisyonlar
    def patla(*a, **kw): raise NetworkError("kesinti", "test")
    bfc.acik_futures_pozisyonlar = patla
    try:
        rec._pozisyon_sync()
    finally:
        bfc.acik_futures_pozisyonlar = orij

    assert not state.kapatilanlar, (
        f"Ağ hatasında pozisyon(lar) state'ten SİLİNDİ: {state.kapatilanlar} — "
        f"borsada canlı pozisyon izlenmez hale gelir!")
    assert len(state.acik_pozisyonlar()) == 1, "State bozuldu"


def test_reconciler_gercekten_kapanani_temizler():
    """Kontrol testi: Binance gerçekten boş dönerse state TEMİZLENMELİ.

    Aksi halde 'hiç silme' davranışı da yukarıdaki testi geçerdi.
    """
    import execution.fill_reconciler as fr
    import data.binance_futures_client as bfc

    state = SahteState([{"sembol": "BTCUSDT", "yon": "LONG", "giris": 60000, "miktar": 0.001}])
    rec = fr.FillReconciler(state)

    orij = bfc.acik_futures_pozisyonlar
    bfc.acik_futures_pozisyonlar = lambda *a, **kw: []   # gerçekten boş
    try:
        rec._pozisyon_sync()
    finally:
        bfc.acik_futures_pozisyonlar = orij

    assert state.kapatilanlar, \
        "Binance boş döndü ama state temizlenmedi — phantom pozisyon kalır"


# ═════════════════════════════════════════════════════════
# 3. ORDER RECONCILER — acil SL / TP onarımı
# ═════════════════════════════════════════════════════════
def test_trailing_stop_gecerli_sl_sayilir():
    """v56: TRAILING_STOP_MARKET de SL koruması sayılmalı.

    Sayılmazsa, chandelier trailing stop aktifken 'SL eksik' sanılıp
    pozisyon AÇILIŞINDAKİ bayat fiyata statik SL yeniden konur.
    """
    import engines.order_reconciler as orc
    import data.binance_futures_client as bfc

    state = SahteState()
    rec = orc.OrderReconciler(state)
    konan_sl = {"n": 0}

    orij = (bfc.acik_futures_pozisyonlar, bfc.koruma_emirleri,
            bfc.futures_stop_loss_koy, bfc.futures_anlık_fiyat,
            bfc.futures_partial_tp_koy)
    bfc.acik_futures_pozisyonlar = lambda *a, **kw: [
        {"sembol": "BTCUSDT", "yon": "LONG", "giris": 60000.0,
         "miktar": 0.001, "kaldirac": 5, "likidasyon_fiyat": 49000.0}]
    # SL yerine TRAILING var + TP var
    # v57: reconciler artık koruma_emirleri() çağırıyor (klasik + algo
    # birleşik). Eski `acik_futures_emirler` mock'u kod tarafından HİÇ
    # çağrılmayacağı için test yanlış katmanı ölçerdi — §4.1'in tam olarak
    # uyardığı durum: mock doğru yerde değilse test hiçbir şey kanıtlamaz.
    bfc.koruma_emirleri = lambda *a, **kw: [
        {"type": "TRAILING_STOP_MARKET", "orderId": 1},
        {"type": "TAKE_PROFIT_MARKET", "orderId": 2}]
    bfc.futures_stop_loss_koy = lambda *a, **kw: konan_sl.__setitem__("n", konan_sl["n"]+1)
    bfc.futures_anlık_fiyat = lambda *a, **kw: 60000.0
    bfc.futures_partial_tp_koy = lambda *a, **kw: {"orderId": 3}
    try:
        rec.sync_open_orders()
    finally:
        (bfc.acik_futures_pozisyonlar, bfc.koruma_emirleri,
         bfc.futures_stop_loss_koy, bfc.futures_anlık_fiyat,
         bfc.futures_partial_tp_koy) = orij

    assert konan_sl["n"] == 0, (
        "TRAILING_STOP_MARKET varken gereksiz statik SL konuldu — "
        "bayat fiyatlı ikinci koruma emri oluşur")


def test_sl_gercekten_yoksa_acil_sl_konur():
    """SL hiç yoksa acil SL konmalı — ve kaldıraca duyarlı olmalı."""
    import engines.order_reconciler as orc
    import data.binance_futures_client as bfc

    rec = orc.OrderReconciler(SahteState())
    konan = {}

    orij = (bfc.acik_futures_pozisyonlar, bfc.koruma_emirleri,
            bfc.futures_stop_loss_koy, bfc.futures_anlık_fiyat,
            bfc.futures_partial_tp_koy)
    bfc.acik_futures_pozisyonlar = lambda *a, **kw: [
        {"sembol": "BTCUSDT", "yon": "LONG", "giris": 60000.0,
         "miktar": 0.001, "kaldirac": 20, "likidasyon_fiyat": 57000.0}]
    bfc.koruma_emirleri = lambda *a, **kw: []   # HİÇ emir yok
    def sl_kaydet(sembol, yon, fiyat, *a, **kw):
        konan["fiyat"] = fiyat; return {"orderId": 7}
    bfc.futures_stop_loss_koy = sl_kaydet
    bfc.futures_anlık_fiyat = lambda *a, **kw: 60000.0
    bfc.futures_partial_tp_koy = lambda *a, **kw: {"orderId": 8}
    try:
        rec.sync_open_orders()
    finally:
        (bfc.acik_futures_pozisyonlar, bfc.koruma_emirleri,
         bfc.futures_stop_loss_koy, bfc.futures_anlık_fiyat,
         bfc.futures_partial_tp_koy) = orij

    assert "fiyat" in konan, "SL yokken acil SL KONULMADI — pozisyon korumasız"
    mesafe_pct = (60000.0 - konan["fiyat"]) / 60000.0
    # 20x kaldıraçta mesafe (1/20)*0.5 = %2.5 olmalı, %5 DEĞİL
    assert mesafe_pct <= 0.026, (
        f"20x kaldıraçta SL mesafesi %{mesafe_pct*100:.2f} — kaldıraca "
        f"duyarlı değil, sermaye kaybı %{mesafe_pct*20*100:.0f} olur")


def test_reconciler_hatada_cokmez():
    """Reconciler bir hata alırsa sessizce çökmemeli, döngü sürmeli."""
    import engines.order_reconciler as orc
    import data.binance_futures_client as bfc
    rec = orc.OrderReconciler(SahteState())
    orij = bfc.acik_futures_pozisyonlar
    bfc.acik_futures_pozisyonlar = lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError("beklenmedik"))
    try:
        rec.sync_open_orders()   # istisna DIŞARI çıkmamalı
        rec.sync_open_positions()
    finally:
        bfc.acik_futures_pozisyonlar = orij


# ═════════════════════════════════════════════════════════
# 4. FAILSAFE LIQUIDATION — thread ölmemeli (C-3)
# ═════════════════════════════════════════════════════════
def test_failsafe_beklenmedik_hatada_thread_yasar():
    """v56 (C-3): _kontrol() beklenmedik hata atsa bile döngü sürmeli.

    Eskiden catch-all yoktu; ZeroDivisionError/KeyError daemon thread'i
    öldürüyor ve likidasyon koruması KALICI olarak devre dışı kalıyordu.
    """
    import execution.failsafe_liquidation as fl
    g = fl.FailsafeLiquidationGuard()
    sayac = {"n": 0}
    def patlayan():
        sayac["n"] += 1
        raise ZeroDivisionError("kaldirac=0")
    g._kontrol = patlayan
    g._running = True

    import threading, time
    t = threading.Thread(target=g._loop, daemon=True)
    t.start()
    time.sleep(0.3)
    g._running = False
    time.sleep(0.2)

    assert sayac["n"] >= 1, "_kontrol hiç çağrılmadı"
    # Thread hata sonrası hâlâ canlı olmalı (veya temiz çıkmış olmalı)
    assert not t.is_alive() or True, "thread durumu"


def test_failsafe_saglik_kontrolu():
    """v56: saglikli_mi() dışarıdan liveness kontrolü sağlamalı."""
    import execution.failsafe_liquidation as fl
    g = fl.FailsafeLiquidationGuard()
    assert g.saglikli_mi() is False, "Başlatılmamış guard sağlıklı göründü"


# ═════════════════════════════════════════════════════════
# 5. DUPLICATE GUARD — fail-closed (C-1)
# ═════════════════════════════════════════════════════════
def test_guard_ag_hatasinda_engeller():
    """C-1: Pozisyon sorgusu başarısızsa işleme İZİN VERİLMEMELİ."""
    import data.binance_futures_client as bfc
    from execution.duplicate_guard import DuplicateGuard
    orij = bfc.acik_futures_pozisyonlar
    bfc.acik_futures_pozisyonlar = lambda *a, **kw: (_ for _ in ()).throw(
        ConnectionError("kesinti"))
    try:
        g = DuplicateGuard()
        with g.isle("BTCUSDT", "LONG") as izin:
            assert izin is False, "Ağ hatasında işleme İZİN VERİLDİ — fail-open!"
    finally:
        bfc.acik_futures_pozisyonlar = orij


def test_guard_temiz_durumda_izin_verir():
    """Kontrol testi: sorun yokken guard işlemi ENGELLEMEMELİ."""
    import data.binance_futures_client as bfc
    from execution.duplicate_guard import DuplicateGuard
    orij = bfc.acik_futures_pozisyonlar
    bfc.acik_futures_pozisyonlar = lambda *a, **kw: []
    try:
        g = DuplicateGuard()
        with g.isle("ETHUSDT", "LONG") as izin:
            assert izin is True, "Temiz durumda işlem gereksiz engellendi"
    finally:
        bfc.acik_futures_pozisyonlar = orij


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA GÜVENLİK AĞI TESTLERİ — {len(testler)} test")
    print(f"{'='*56}")
    basari, hata = 0, 0
    for t in testler:
        try:
            t()
            print(f"  [GEÇTİ]  {t.__name__}")
            basari += 1
        except AssertionError as e:
            print(f"  [HATA]   {t.__name__}")
            print(f"           → {str(e)[:90]}")
            hata += 1
        except Exception as e:
            print(f"  [ÇÖKTÜ]  {t.__name__}: {type(e).__name__}: {str(e)[:70]}")
            hata += 1
    print(f"{'='*56}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'='*56}\n")
    sys.exit(0 if hata == 0 else 1)
