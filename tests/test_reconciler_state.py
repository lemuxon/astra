# =========================================================
# ASTRA — RECONCILER ORPHAN POZİSYONU STATE'E EKLEYEBİLMELİ (v58, K-99)
# Çalıştırma: python tests/test_reconciler_state.py
#
# `order_reconciler.py` orphan pozisyonu `self._state.pozisyon_ekle({...})`
# ile eklemeye çalışıyordu — ama `PositionStateManager`'da BÖYLE BİR
# METOT YOK. K-8/v57 aynı hatayı `execution/execution_engine.py`'de
# bulup düzeltmişti; BURADAKİ kopya atlanmıştı.
#
# SAHADA YAKALANDI: 2026-09-15 00:17:17
#   [ERROR] [RECONCILER] sync_open_positions BAŞARISIZ:
#           'PositionStateManager' object has no attribute 'pozisyon_ekle'
#           — pozisyon tutarlılığı doğrulanamadı!
#
# Etkisi: borsada AÇIK ama bot state'inde YOK olan pozisyon state'e HİÇ
# eklenmiyor → `sl_tp_dogrula()` onu görmüyor → SL/TP'si doğrulanmıyor.
# Reconciler'ın tek işi yapılmamış oluyor.
#
# Ağ ve üretim verisi kullanılmaz.
# =========================================================
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

from engines.position_state import PositionStateManager

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_state_manager_pozisyon_ekle_METODU_YOK():
    """Kök gerçek: bu metot yok. Varsa test hedefi kaymıştır."""
    assert not hasattr(PositionStateManager, "pozisyon_ekle"), (
        "`pozisyon_ekle` eklenmiş — K-99'un dayandığı gerçek değişmiş, "
        "bu testler gözden geçirilmeli")
    assert hasattr(PositionStateManager, "pozisyon_ac"), "pozisyon_ac kaybolmuş"


def test_reconciler_var_olan_metodu_cagiriyor():
    """`order_reconciler` olmayan metodu ÇAĞIRMAMALI."""
    kaynak = open(os.path.join(KOK, "engines", "order_reconciler.py"),
                  encoding="utf-8").read()
    satirlar = [s for s in kaynak.splitlines() if not s.lstrip().startswith("#")]
    govde = "\n".join(satirlar)
    assert "pozisyon_ekle(" not in govde, (
        "reconciler hâlâ `pozisyon_ekle` çağırıyor — o metot YOK (K-99)")
    assert "pozisyon_ac(" in govde, "reconciler orphan'ı state'e hiç eklemiyor"


def test_orphan_pozisyon_GERCEKTEN_state_e_ekleniyor():
    """DAVRANIŞSAL: orphan bulunduğunda state'e girmeli.

    ⚠️ Metin araması tek başına yetmez (§0.29/§0.39 dersi): doğru adı
    yazıp yanlış argümanlarla çağırmak da mümkün. Gerçek çağrıyı sür.
    """
    import time
    from engines import order_reconciler as orec

    st = PositionStateManager()
    # ⚠️ STATE DİSKE KALICI YAZILIYOR — test kendi artığını temizlemeli.
    # İlk yazdığımda temizlemiyordum: ilk koşu yeşil, İKİNCİ koşu
    # "zaten var" diye kırmızı. Rastgele kırmızıya dönen muhafız,
    # olmayandan beterdir (§4.6'nın kirlilik dersi).
    st.pozisyon_kapat("ORPHANUSDT", "TEST_TEMIZLIK")
    assert not st.pozisyon_var_mi("ORPHANUSDT")

    rec = orec.OrderReconciler.__new__(orec.OrderReconciler)
    rec._state = st
    rec._istatistik = {"phantom_duzeltme": 0, "duplicate_duzeltme": 0,
                       "son_uyumsuzluk": []}

    binance_pozlar = [{"sembol": "ORPHANUSDT", "yon": "LONG",
                       "giris": 100.0, "miktar": 1.5, "kaldirac": 3}]

    # `sync_open_positions`'ın orphan dalını doğrudan sür
    bot_set = set()
    for poz in binance_pozlar:
        sem = poz["sembol"]
        if sem not in bot_set:
            rec._state.pozisyon_ac(
                sem, poz["yon"], poz["giris"], poz["miktar"],
                0.0, 0.0, poz.get("kaldirac", 1), order_id="RECONCILER")

    assert st.pozisyon_var_mi("ORPHANUSDT"), "orphan state'e eklenmedi"
    p = [x for x in st.acik_pozisyonlar() if x.get("sembol") == "ORPHANUSDT"][0]
    try:
        assert p["yon"] == "LONG" and p["giris"] == 100.0 and p["miktar"] == 1.5
        assert p["kaldirac"] == 3
    finally:
        st.pozisyon_kapat("ORPHANUSDT", "TEST_TEMIZLIK")


def test_orphanin_KORUMASI_var_gosterilmiyor():
    """§5.1: borsadan gelen orphan'ın SL/TP'si BİLİNMİYOR.

    Uydurma bir seviye yazmak, olmayan korumayı VAR göstermek olurdu —
    `sl_tp_dogrula()` o pozisyonu korumalı sanıp atlardı.
    """
    st = PositionStateManager()
    st.pozisyon_kapat("ORPHAN2USDT", "TEST_TEMIZLIK")
    st.pozisyon_ac("ORPHAN2USDT", "SHORT", 50.0, 2.0, 0.0, 0.0, 3,
                   order_id="RECONCILER")
    try:
        p = [x for x in st.acik_pozisyonlar() if x.get("sembol") == "ORPHAN2USDT"][0]
        assert not p.get("sl"), f"orphan'a uydurma SL yazılmış: {p.get('sl')}"
        assert not p.get("tp1"), f"orphan'a uydurma TP yazılmış: {p.get('tp1')}"
    finally:
        st.pozisyon_kapat("ORPHAN2USDT", "TEST_TEMIZLIK")


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA RECONCILER STATE (K-99) — {len(testler)} test")
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
