# =========================================================
# ASTRA v57 — POZİSYON STATE KAYDI TESTLERİ
# Çalıştırma: python tests/test_state_kayit.py
#
# NE KORUYOR — sessiz izleme kaybı:
#   `execution_engine.pozisyon_ac()` içinde şu satır vardı:
#       self._state.pozisyon_ekle({...})
#   Ama `StateManager`'da **`pozisyon_ekle` diye bir metot YOK.**
#   Doğrusu:
#       pozisyon_ac(sembol, yon, giris, miktar, sl, tp1, kaldirac, order_id)
#   — isim de imza da farklı (dict değil, adlandırılmış argümanlar).
#
#   Her pozisyon açılışında AttributeError fırlıyor, alttaki
#   `except Exception` onu yutuyor ve bot AÇTIĞI POZİSYONU KENDİ STATE'İNE
#   HİÇ KAYDETMİYORDU. Hiçbir şey çökmediği için fark edilmemişti.
#
#   ETKİSİ:
#     • `position_state.sl_tp_dogrula()` boş state üzerinde döner →
#       gerçek pozisyonların SL/TP'si HİÇ doğrulanmaz
#     • `pozisyon_var_mi()` her zaman False → bu katmandaki duplicate
#       koruması çalışmaz
#     • `testnet_emir_dogrula.py` adım 6 "borsada AÇIK ama state'te YOK"
#
#   2026-08-26'da doğrulama betiğinin 6. adımıyla yakalandı.
#
# §4.1: Muhafızın yanına KONTROL testi yazıldı — "hiç pozisyon açmayan"
#   bir kod da muhafızı geçerdi.
# =========================================================
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "test")
os.environ.setdefault("BINANCE_API_SECRET", "test")


# ─────────────────────────────────────────────
# 1. MUHAFIZ — çağrılan metot GERÇEKTEN var mı
# ─────────────────────────────────────────────
def test_state_manager_pozisyon_ac_metoduna_sahip():
    """StateManager'da `pozisyon_ac` bulunmalı — execution engine onu çağırıyor."""
    from engines.position_state import get_state_manager
    sm = get_state_manager()
    assert hasattr(sm, "pozisyon_ac"), (
        "StateManager.pozisyon_ac YOK — execution engine pozisyonu "
        "kaydedemez, bot açtığı pozisyonu izlemez")
    assert callable(sm.pozisyon_ac)


def test_execution_engine_var_olan_metodu_cagiriyor():
    """Kaynak düzeyi: `pozisyon_ekle` çağrısı GERİ GELMEMELİ.

    O metot hiç var olmadı. Yeniden yazılırsa AttributeError sessizce
    yutulur ve izleme kaybı geri döner.
    """
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "execution", "execution_engine.py"),
              encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))
    assert "_state.pozisyon_ekle" not in kod, (
        "execution_engine hâlâ `pozisyon_ekle` çağırıyor — StateManager'da "
        "böyle bir metot YOK, her pozisyon açılışında AttributeError olur "
        "ve state kaydı sessizce atlanır")
    assert "_state.pozisyon_ac" in kod, (
        "execution_engine state'e pozisyon kaydetmiyor — bot açtığı "
        "pozisyonu izlemez")


def test_state_kaydi_basarisizsa_sessiz_kalmaz():
    """State kaydı patlarsa CRITICAL loglanmalı, sessizce yutulmamalı.

    Eskiden `log.error` ile geçiştiriliyordu ve kimse fark etmedi
    (DEVAM_NOTLARI §5.2 sessiz başarısızlık kuralı).
    """
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "execution", "execution_engine.py"),
              encoding="utf-8") as fh:
        icerik = fh.read()
    i = icerik.find("_state.pozisyon_ac")
    assert i > 0, "state kayıt bloğu bulunamadı"
    blok = icerik[i:i + 1400]
    assert "log.critical" in blok, (
        "state kayıt hatası CRITICAL seviyede loglanmıyor — sessiz kalırsa "
        "bot pozisyonu izlemediği hâlde çalışmaya devam eder")


# ─────────────────────────────────────────────
# 2. KONTROL — kayıt GERÇEKTEN çalışıyor mu
# ─────────────────────────────────────────────
def test_kontrol_pozisyon_state_e_gercekten_yaziliyor():
    """`pozisyon_ac` çağrısı state'i GERÇEKTEN doldurmalı.

    Yukarıdaki testler yalnızca "doğru metot çağrılıyor" diyor. Metot
    var ama bozuk olsaydı hepsi geçerdi — bu test sonucu ölçer.
    """
    from engines.position_state import get_state_manager
    sm = get_state_manager()
    sembol = "TESTSTATEUSDT"
    try:
        once = len([p for p in sm.acik_pozisyonlar() if p["sembol"] == sembol])
        sm.pozisyon_ac(sembol=sembol, yon="LONG", giris=100.0, miktar=1.0,
                       sl=95.0, tp1=110.0, kaldirac=3, order_id="test1")
        sonra = [p for p in sm.acik_pozisyonlar() if p["sembol"] == sembol]
        assert len(sonra) == once + 1, (
            f"pozisyon_ac çağrıldı ama state'e yazılmadı ({once} → {len(sonra)})")
        p = sonra[0]
        assert p["giris"] == 100.0, f"giriş fiyatı yanlış: {p['giris']}"
        assert p["sl"] == 95.0, f"SL yanlış: {p['sl']}"
        assert sm.pozisyon_var_mi(sembol), "pozisyon_var_mi False döndü"
    finally:
        sm.pozisyon_kapat(sembol, "test temizlik")


def test_kontrol_sl_aktif_isaretlenebiliyor():
    """SL konduğunda state'te işaretlenmeli — doğrulama buna bakıyor."""
    from engines.position_state import get_state_manager
    sm = get_state_manager()
    sembol = "TESTSLUSDT"
    try:
        sm.pozisyon_ac(sembol=sembol, yon="LONG", giris=100.0, miktar=1.0,
                       sl=95.0, tp1=110.0, kaldirac=3, order_id="t")
        sm.sl_aktif_isaretle(sembol)
        p = next(p for p in sm.acik_pozisyonlar() if p["sembol"] == sembol)
        assert p.get("sl_aktif") is True, (
            "sl_aktif işaretlenmedi — SL konmuş olsa bile state 'korumasız' "
            "gösterir")
    finally:
        sm.pozisyon_kapat(sembol, "test temizlik")


def test_kontrol_kapatinca_state_ten_siliniyor():
    """Pozisyon kapanınca state'ten çıkmalı — yoksa hayalet pozisyon kalır."""
    from engines.position_state import get_state_manager
    sm = get_state_manager()
    sembol = "TESTKAPUSDT"
    sm.pozisyon_ac(sembol=sembol, yon="LONG", giris=100.0, miktar=1.0,
                   sl=95.0, tp1=110.0, kaldirac=3, order_id="t")
    assert sm.pozisyon_var_mi(sembol), "test önkoşulu: pozisyon açılmadı"
    sm.pozisyon_kapat(sembol, "test")
    assert not sm.pozisyon_var_mi(sembol), (
        "pozisyon kapatıldı ama state'te duruyor — hayalet pozisyon")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA POZİSYON STATE KAYDI — {len(testler)} test")
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
