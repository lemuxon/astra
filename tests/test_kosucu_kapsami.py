"""Koşucu, tests/ altındaki HER test dosyasını çalıştırmalı (v58 K-91).

── NEDEN VAR ────────────────────────────────────────────────────
`testleri_calistir.py` test dosyalarını SABİT BİR LİSTEDEN okuyor.
Listeye eklenmeyen dosya sessizce atlanır — ne uyarı çıkar ne sayaç
değişir. 2026-09-13'te ölçüldü: K-89/K-90 için yazılan 14 muhafız
testi dosyaya kaydedilmişti, `pytest` onları topluyordu, ama projenin
KENDİ doğrulama komutu (`python testleri_calistir.py`, §1'in "her
değişiklikten sonra çalıştır" dediği komut) hiçbirini çalıştırmıyordu.
Toplam yine "476 test geçti" diyordu.

**Çalıştırılmayan muhafız, muhafız değildir** — üstelik olmayandan
beterdir, çünkü "yazdım, yeşil" sanılır.

§10'un tam olarak tarif ettiği sınıf: kör nokta kodun içinde değil,
kodun ÖLÇÜLDÜĞÜ yerde duruyor.
"""
import glob
import io
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _listedeki_dosyalar() -> set:
    kaynak = io.open(os.path.join(KOK, "testleri_calistir.py"),
                     encoding="utf-8").read()
    return set(re.findall(r'"(tests/test_[a-z0-9_]+\.py)"', kaynak))


def _diskteki_dosyalar() -> set:
    return {os.path.relpath(p, KOK).replace("\\", "/")
            for p in glob.glob(os.path.join(KOK, "tests", "test_*.py"))}


def test_her_test_dosyasi_kosucuya_kayitli():
    """Diskteki her dosya listede olmalı — yoksa sessizce atlanır."""
    eksik = sorted(_diskteki_dosyalar() - _listedeki_dosyalar())
    assert not eksik, (
        "Bu dosyalar `testleri_calistir.py` listesinde YOK, yani projenin "
        "kendi doğrulama komutu onları ÇALIŞTIRMIYOR:\n  " +
        "\n  ".join(eksik) +
        "\n\nListeye ekle — aksi hâlde muhafızların yeşil sanılır ama koşmaz."
    )


def test_listede_olmayan_dosyaya_atif_yok():
    """KONTROL: silinen/yeniden adlandırılan dosya listede kalmamalı.

    Koşucu var olmayan dosyayı "⚠ bulunamadı, atlanıyor" deyip GEÇİYOR —
    yani yanlış yazılmış bir yol da sessiz kapsama kaybıdır.
    """
    hayalet = sorted(_listedeki_dosyalar() - _diskteki_dosyalar())
    assert not hayalet, (
        "Listede olup diskte olmayan dosyalar (koşucu bunları sessizce "
        "atlıyor):\n  " + "\n  ".join(hayalet)
    )


def test_bu_muhafiz_kendisi_de_kayitli():
    """Bu dosya listede değilse hiç çalışmaz ve yukarıdakiler işe yaramaz."""
    assert "tests/test_kosucu_kapsami.py" in _listedeki_dosyalar()


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA KOŞUCU KAPSAMI (K-91) — {len(testler)} test")
    print(f"{'=' * 58}")
    basari, hata = 0, 0
    for test in testler:
        try:
            test()
            print(f"  [GEÇTİ]  {test.__name__}")
            basari += 1
        except AssertionError as exc:
            print(f"  [HATA]   {test.__name__}\n           → {str(exc)[:200]}")
            hata += 1
        except Exception as exc:
            print(f"  [ÇÖKTÜ]  {test.__name__}: {type(exc).__name__}: {str(exc)[:100]}")
            hata += 1
    print(f"{'=' * 58}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'=' * 58}\n")
    sys.exit(0 if hata == 0 else 1)
