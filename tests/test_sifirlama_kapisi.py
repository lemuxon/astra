# =========================================================
# ASTRA — SIFIRLAMA, BOT ÇALIŞIRKEN REDDEDİLMELİ (v58, K-93)
# Çalıştırma: python tests/test_sifirlama_kapisi.py
#
# `sifirla_k37.py::bot_calisiyor_mu()` PowerShell çıktısını
# `(... ).Count` ile okuyordu. PS 5.1 TEK nesneli sonucu diziden
# çıkarır ve `.Count` BOŞ STRING döner:
#       (...).Count  -> ''        @(...).Count -> '1'
# Boş string "bot yok" sayılıyordu.
#
# ÖLÇÜLDÜ (2026-09-13): bot PID 13760 ile çalışırken fonksiyon
# **False** döndü — yani kapı, korumak istediği NORMAL durumda
# (tek bot çalışıyor) tamamen etkisizdi. Sıfırlama sessizce devam
# eder ve K-59'un bakiye yarışını yaratırdı.
#
# Ağ ve üretim verisi kullanılmaz — PowerShell çağrısı taklit edilir.
# =========================================================
import importlib.util
import os
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _modul():
    yol = os.path.join(KOK, "sifirla_k37.py")
    spec = importlib.util.spec_from_file_location("_sifirla_kapi_test", yol)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Yanit:
    def __init__(self, cikti):
        self.stdout = cikti
        self.stderr = ""
        self.returncode = 0


def _sahte_run(cikti):
    def _f(*a, **k):
        return _Yanit(cikti)
    return _f


def _ile_sahte_run(mod, cikti, cagir=True):
    asil = subprocess.run
    try:
        subprocess.run = _sahte_run(cikti)
        return mod.bot_calisiyor_mu() if cagir else None
    finally:
        subprocess.run = asil


def test_tek_bot_calisiyorken_yakalanir():
    """K-93'ün ta kendisi: @(...) ile tek bot '1' döner, True olmalı."""
    mod = _modul()
    assert _ile_sahte_run(mod, "1\n") is True


def test_bos_yanit_fail_closed():
    """§5.1: ölçemediysek 'bot yok' DEME — yıkıcı işlemi durdur.

    Eski kod boş stringi "0 bot" sayıyordu; hatanın tam kaynağı buydu.
    """
    mod = _modul()
    assert _ile_sahte_run(mod, "") is True, "boş yanıt fail-open kalmış"
    assert _ile_sahte_run(mod, "   \n") is True


def test_okunamayan_durum_SESSIZ_kalmaz():
    """§5.2: ölçemediğimizi kullanıcı GÖRMELİ.

    ⚠️ Bu test sonradan eklendi. Mutasyon testinde `if ham == "":`
    dalını kaldıran varyant testleri GEÇTİ — çünkü boş string zaten
    `ham != "0"` yolundan da True dönüyor, yani dönüş değeri AYNI.
    Mutasyon davranışsal olarak EŞDEĞERDİ, test haklıydı.

    Ama dalın asıl katkısı UYARIYI BASMAK: "bot durumu okunamadı"
    sessizce yutulursa, kullanıcı sıfırlamanın neden reddedildiğini
    bilemez. Dönüş değeri kilitliydi, teşhis kaydı değildi.
    """
    import io as _io
    from contextlib import redirect_stdout
    mod = _modul()
    tampon = _io.StringIO()
    with redirect_stdout(tampon):
        sonuc = _ile_sahte_run(mod, "")
    cikti = tampon.getvalue().lower()
    assert sonuc is True
    assert "okunamadı" in cikti or "okunamadi" in cikti, (
        f"boş yanıtta uyarı basılmıyor — sessiz reddetme: {cikti!r}")


def test_powershell_patlarsa_fail_closed():
    """KONTROL: istisna halinde de durmalı (eski kod False dönüyordu)."""
    mod = _modul()
    asil = subprocess.run
    try:
        def _patla(*a, **k):
            raise OSError("powershell yok")
        subprocess.run = _patla
        assert mod.bot_calisiyor_mu() is True, "istisnada fail-open kalmış"
    finally:
        subprocess.run = asil


# ── KONTROL TESTLERİ (§4.1): "hep True dön" de üsttekileri geçerdi ───
def test_bot_gercekten_yoksa_sifirlamaya_izin_verilir():
    """Kapı HER ZAMAN kapalı olsaydı sıfırlama hiç yapılamazdı.

    Bu test olmadan `return True` mutasyonu yukarıdaki üç testi de
    geçerdi — veto testinin yanına kontrol testi kuralı (§4.1).
    """
    mod = _modul()
    assert _ile_sahte_run(mod, "0\n") is False, "bot yokken de engelliyor"


def test_birden_fazla_bot_da_yakalanir():
    mod = _modul()
    assert _ile_sahte_run(mod, "2\n") is True


def test_powershell_ifadesi_dizi_sarmalayici_kullaniyor():
    """`@(...)` olmadan PS 5.1 tek nesnede boş döner — kök neden buydu."""
    kaynak = open(os.path.join(KOK, "sifirla_k37.py"), encoding="utf-8").read()
    i = kaynak.find("def bot_calisiyor_mu")
    govde = kaynak[i:i + 2500]
    assert "@(Get-CimInstance" in govde, "dizi sarmalayıcı @() kaldırılmış (K-93)"


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA SIFIRLAMA KAPISI (K-93) — {len(testler)} test")
    print(f"{'=' * 58}")
    basari, hata = 0, 0
    for test in testler:
        try:
            test()
            print(f"  [GEÇTİ]  {test.__name__}")
            basari += 1
        except AssertionError as exc:
            print(f"  [HATA]   {test.__name__}\n           → {str(exc)[:160]}")
            hata += 1
        except Exception as exc:
            print(f"  [ÇÖKTÜ]  {test.__name__}: {type(exc).__name__}: {str(exc)[:100]}")
            hata += 1
    print(f"{'=' * 58}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'=' * 58}\n")
    sys.exit(0 if hata == 0 else 1)
