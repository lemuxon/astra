# =========================================================
# ASTRA v30.0 — Strateji Doğrulama Kapısı Birim Testleri
# Çalıştırma: python -m pytest tests/test_validator.py -v
#   veya bağımsız:  python tests/test_validator.py
# =========================================================
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# v57: ÜRETİM durum dosyalarına yazmayı engelle. Proje modülleri import
# EDİLMEDEN ÖNCE çağrılmalı — config.py yolları import anında okur.
from tests.izolasyon import izole_et; izole_et()


import numpy as np
from engines.strategy_validator import get_validator, StratejiValidator


def _validator():
    return StratejiValidator()


def test_iyi_strateji_onaylanir():
    """Pozitif beklenti + düşük vol + tutarlı WF → ONAY."""
    v = _validator()
    rng = np.random.default_rng(1)
    getiriler = rng.normal(0.4, 1.5, 120)
    karar = v.dogrula(getiriler,
                      wf_pencere_getirileri=[5, 4, 6, 3, 5, 4],
                      deneme_sayisi=4)
    assert karar.onay is True, f"İyi strateji reddedildi (skor={karar.skor})"
    assert karar.skor >= 60


def test_kotu_strateji_reddedilir():
    """Negatif beklenti + yüksek vol → RED."""
    v = _validator()
    rng = np.random.default_rng(2)
    getiriler = rng.normal(-0.3, 4.0, 120)
    karar = v.dogrula(getiriler,
                      wf_pencere_getirileri=[-5, 3, -8, 2, -6, 1],
                      deneme_sayisi=4)
    assert karar.onay is False, f"Kötü strateji onaylandı (skor={karar.skor})"


def test_yetersiz_veri_reddedilir():
    """min_islem altında → RED (test edilemez)."""
    v = _validator()
    karar = v.dogrula(np.array([1.0, 2.0, -1.0]), deneme_sayisi=1)
    assert karar.onay is False
    assert "Yetersiz" in karar.sebepler[0]


def test_yuksek_iflas_riski_veto():
    """Çok yüksek volatilite → iflas riski VETO'su devreye girmeli."""
    v = _validator()
    rng = np.random.default_rng(3)
    # Pozitif ortalama ama uçuk volatilite → bazı bootstrap yolları iflas eder
    getiriler = rng.normal(0.5, 15.0, 100)
    karar = v.dogrula(getiriler, deneme_sayisi=1)
    # Yüksek vol'da iflas riski yüksek olmalı → onay verilmemeli
    assert karar.onay is False


def test_deneme_sayisi_deflation():
    """Çok deneme → DSR düşmeli (aynı getiri, daha çok deneme = daha az güven)."""
    v = _validator()
    rng = np.random.default_rng(4)
    getiriler = rng.normal(0.3, 2.0, 150)
    dsr_az  = v.deflated_sharpe(getiriler, deneme_sayisi=1)
    dsr_cok = v.deflated_sharpe(getiriler, deneme_sayisi=100)
    assert dsr_cok <= dsr_az, "Deneme sayısı arttıkça DSR düşmeli (overfit deflation)"


def test_deploy_izni_tutarli():
    """dogrula sonrası deploy kararı StratejiKarari ile tutarlı olmalı."""
    v = _validator()
    rng = np.random.default_rng(5)
    iyi = rng.normal(0.4, 1.5, 120)
    karar = v.dogrula(iyi, wf_pencere_getirileri=[5, 4, 6, 5, 4], deneme_sayisi=2)
    assert isinstance(karar.onay, bool)
    assert 0 <= karar.skor <= 100


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    gecen = 0
    for t in testler:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            gecen += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:
            print(f"  ⚠️ {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{gecen}/{len(testler)} test geçti")
    sys.exit(0 if gecen == len(testler) else 1)
