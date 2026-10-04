# =========================================================
# ASTRA — GÖRÜNTÜ KATMANI GERÇEK KALDIRACI GÖSTERMELİ (v58, K-89)
# Çalıştırma: python tests/test_kaldirac_gosterimi.py
#
# K-86 paper'ı gerçek kaldıraca bağladı ama `main.py` kaldıracı ÜÇ
# AYRI YERDE kendisi yazıyordu ve üçü de `"kaldirac": 1` sabitiydi
# (panelin iki kolu + `_paper_pozlari_esle` → Telegram /fpoz).
# Ölçüldü: DB kaldirac=3.0 iken panel 1x gösteriyordu.
#
# ⚠️ BU TESTLER DAVRANIŞSAL — kaynak metninde "kaldirac" ARAMAZLAR.
# §0.29'un dersi: `inspect.getsource` + `in` araması bir davranışı
# kilitlemez, yalnızca metnin varlığını kilitler.
# Ağ, veritabanı ve gerçek emir kullanılmaz.
# =========================================================
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

import main


# ── ÇEKİRDEK: kayıttaki değer neye çevriliyor ────────────────────────
def test_gercek_kaldirac_okunur_sabit_1_degil():
    """DB'de 3.0 varsa görüntüde 3 çıkmalı — K-89'un ta kendisi."""
    assert main._kaldirac_goster({"kaldirac": 3.0}) == 3
    assert main._kaldirac_goster({"kaldirac": 5}) == 5
    assert main._kaldirac_goster({"kaldirac": "2"}) == 2


def test_kesirli_kaldirac_korunur():
    assert main._kaldirac_goster({"kaldirac": 2.5}) == 2.5


# ── KONTROL TESTİ (§4.1): "hep None dön" de veto testini geçerdi ─────
def test_eksik_kaldirac_1e_dusurulmez():
    """§5.1 fail-open: 'bilmiyorum' ≠ 'kaldıraç yok'.

    K-86 ÖNCESİ kayıtlarda alan yok. Orada 1 yazmak "1x ile açıldı"
    İDDİASIDIR ve yanlıştır — doğru cevap 'bilinmiyor'.
    """
    for bos in ({}, {"kaldirac": None}, {"kaldirac": ""}, {"kaldirac": "abc"}):
        assert main._kaldirac_goster(bos) is None, bos


# ── ÜÇ GÖRÜNTÜ YOLUNUN HEPSİ ────────────────────────────────────────
def test_paper_pozlari_esle_gercek_kaldiraci_tasir():
    """`/fpoz` ve panelin ortak eşleyicisi — K-56'da tek kaynağa
    çıkarılmıştı ama K-86 uygulanırken atlanmıştı."""
    ham = [{"sembol": "XRPUSDT", "yon": "LONG", "giris_fiyat": 1.34,
            "miktar": 39.05, "kaldirac": 3.0, "pnl": 0.04}]
    out = main._paper_pozlari_esle(ham)
    assert len(out) == 1
    assert out[0]["kaldirac"] == 3, "eşleyici hâlâ sabit 1 yazıyor (K-89)"


def test_esleyici_eksik_kaldiraci_uydurmaz():
    """KONTROL: alan yoksa eşleyici de 1 UYDURMAMALI."""
    ham = [{"sembol": "OLDUSDT", "yon": "LONG", "giris_fiyat": 10.0,
            "miktar": 1.0, "pnl": 0.0}]
    assert main._paper_pozlari_esle(ham)[0]["kaldirac"] is None


def test_panel_kaydi_dbdeki_degeri_yansitir():
    """Panelin gördüğü kayıt, DB satırıyla ÇELİŞMEMELİ (K-32/K-33 dersi)."""
    for kaldirac, beklenen in ((2, 2), (3.0, 3), (10, 10)):
        ham = [{"sembol": "ETHUSDT", "yon": "SHORT", "giris_fiyat": 2500.0,
                "miktar": 0.02, "kaldirac": kaldirac, "pnl": 0.0}]
        alinan = main._paper_pozlari_esle(ham)[0]["kaldirac"]
        assert alinan == beklenen, f"{kaldirac!r} → {alinan!r} (beklenen {beklenen})"


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA KALDIRAÇ GÖSTERİMİ (K-89) — {len(testler)} test")
    print(f"{'=' * 58}")
    basari, hata = 0, 0
    for test in testler:
        try:
            test()
            print(f"  [GEÇTİ]  {test.__name__}")
            basari += 1
        except AssertionError as exc:
            print(f"  [HATA]   {test.__name__}\n           → {str(exc)[:120]}")
            hata += 1
        except Exception as exc:
            print(f"  [ÇÖKTÜ]  {test.__name__}: {type(exc).__name__}: {str(exc)[:100]}")
            hata += 1
    print(f"{'=' * 58}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'=' * 58}\n")
    sys.exit(0 if hata == 0 else 1)
