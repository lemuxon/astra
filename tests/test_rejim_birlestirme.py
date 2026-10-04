# =========================================================
# ASTRA v58 — HMM/KURAL REJİM BİRLEŞTİRME (K-36)
# Çalıştırma: python tests/test_rejim_birlestirme.py
#
# NE KORUYOR:
#   `piyasa_rejimi_birlestir` şunu yapıyordu:
#
#       if hmm_rejim == "TRENDING" and kural_rejim == "RANGE":
#           return "TREND_UP"
#
#   HMM durumları volatilite/hacim üzerinden etiketlenir
#   (_DURUM_ETIKETLERI = {0:CALM, 1:TRENDING, 2:STRESSED}). "TRENDING"
#   bir trend OLDUĞUNU söyler, YÖNÜNÜ söylemez — düşen bir trend de
#   aynı durumu üretir. Kod yönü yukarı UYDURUYORDU.
#
#   ETKİSİ (ölçüm: 3 yıl, 4h, 5 sembol, 1500 örnek):
#     HMM etiketleri  CALM %78.1 · STRESSED %21.8 · TRENDING %0.1
#   Yani dal bugün pratikte ÖLÜ. Ama HMM yeniden eğitilince canlanır ve
#   her RANGE barı sessizce TREND_UP olur:
#     • ai_score_hesapla: RANGE cezası (−1) kalkar        → ALIŞ yönünde
#     • sl_tp_hesapla:    RANGE yerine TREND çarpanları   → ALIŞ yönünde
#
#   ⚠️ GEREKÇE PERFORMANS DEĞİL DOĞRULUK (K-26 ile aynı): kazanç iddiası
#   YOK. Yönsüz sinyalden yön üretmek yapısal hatadır.
#
# §4.1: Muhafızın yanına KONTROL testleri var — "birleştirmeyi tamamen
#   kapat" da yön-uydurma testini geçerdi, ama STRESSED→VOLATILE
#   korumasını da öldürürdü.
# =========================================================
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

from core.market_regime import HMMRegimDetector, _DURUM_ETIKETLERI


def _det():
    """Eğitim gerekmez — birleştirme saf fonksiyon, HMM sonucu dışarıdan."""
    return HMMRegimDetector()


def _hmm(rejim, olasilik=0.9, aktif=True):
    return {"rejim": rejim, "olasilik": olasilik, "hmm_aktif": aktif}


# ─────────────────────────────────────────────
# 1. MUHAFIZ — yön uydurulmamalı
# ─────────────────────────────────────────────
def test_trending_range_i_trend_up_a_cevirmez():
    """TRENDING yönsüzdür — RANGE, TREND_UP'a DÖNÜŞMEMELİ."""
    d = _det()
    sonuc = d.piyasa_rejimi_birlestir("RANGE", _hmm("TRENDING"))
    assert sonuc == "RANGE", (
        f"RANGE + HMM(TRENDING) → '{sonuc}'. HMM'in TRENDING durumu YÖN "
        f"taşımaz; TREND_UP dönmek yön uydurmaktır ve ai_score'u ALIŞ "
        f"yönünde kaydırır (RANGE cezası −1 kalkar)")


def test_trending_hicbir_kural_rejimini_yon_degistirmez():
    """TRENDING hiçbir girdide yön DEĞİŞTİRMEMELİ (sadece RANGE değil).

    İlk düzeltme yalnızca RANGE dalını kapatsaydı, birisi yarın
    "TREND_DOWN + TRENDING → TREND_UP" ekleyebilirdi. Kural genel:
    yönsüz etiket yön üretmez.
    """
    d = _det()
    for kural in ("RANGE", "TREND_UP", "TREND_DOWN", "BEAR", "VOLATILE"):
        sonuc = d.piyasa_rejimi_birlestir(kural, _hmm("TRENDING"))
        assert sonuc == kural, (
            f"{kural} + HMM(TRENDING) → '{sonuc}' (beklenen '{kural}'). "
            f"Yönsüz HMM etiketi kural rejimini değiştirmemeli")


def test_hmm_etiketleri_yon_tasimiyor():
    """Kaynak düzeyi: HMM etiket kümesinde YÖNLÜ bir etiket olmamalı.

    Bu test, gelecekte biri `_DURUM_ETIKETLERI`'ne "TRENDING_UP" gibi
    yönlü bir etiket eklerse uyarır — o zaman birleştirmenin yön
    kullanması MEŞRU olur ve bu testler yeniden düşünülmeli.
    """
    yonlu = [e for e in _DURUM_ETIKETLERI.values()
             if "UP" in e.upper() or "DOWN" in e.upper()
             or "BULL" in e.upper() or "BEAR" in e.upper()]
    assert not yonlu, (
        f"HMM etiketlerinde yönlü olan(lar) var: {yonlu}. Etiketler "
        f"volatilite/hacimden türüyor; yön iddiası taşıyorlarsa "
        f"_feature_cikar gözden geçirilmeli")


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_stressed_hala_volatile_yapiyor():
    """AŞIRI DÜZELTME KONTROLÜ: STRESSED → VOLATILE korunmalı.

    "Birleştirmeyi tamamen kapat, hep kural rejimini dön" de yukarıdaki
    üç testi geçerdi — ama ölçümde asıl İŞ YAPAN dal bu:
    3 yıl / 1500 örnekte 277 kez (%18.5) rejimi VOLATILE'e çeviriyor,
    ve VOLATILE R/R kapısı (K-11) buna bakıyor.
    """
    d = _det()
    for kural in ("RANGE", "TREND_UP", "TREND_DOWN", "BEAR"):
        sonuc = d.piyasa_rejimi_birlestir(kural, _hmm("STRESSED", 0.9))
        assert sonuc == "VOLATILE", (
            f"{kural} + HMM(STRESSED, p=0.9) → '{sonuc}'. Stres override'ı "
            f"kayboldu — R/R kapısı VOLATILE'i göremez")


def test_kontrol_zayif_stressed_override_etmiyor():
    """Olasılık eşiği (>0.7) hâlâ uygulanmalı — her STRESSED override etmez."""
    d = _det()
    sonuc = d.piyasa_rejimi_birlestir("TREND_UP", _hmm("STRESSED", 0.5))
    assert sonuc == "TREND_UP", (
        f"p=0.5 STRESSED override etti ('{sonuc}') — olasılık eşiği "
        f"devre dışı kalmış")


def test_kontrol_hmm_kapaliyken_kural_rejimi_doner():
    """HMM aktif değilse kural rejimi aynen dönmeli (fail-safe yol)."""
    d = _det()
    for kural in ("RANGE", "TREND_UP", "BEAR"):
        sonuc = d.piyasa_rejimi_birlestir(kural, _hmm("TRENDING", aktif=False))
        assert sonuc == kural, (
            f"HMM kapalıyken {kural} → '{sonuc}' (kural rejimi dönmeliydi)")


def test_kontrol_calm_kural_rejimini_koruyor():
    """CALM + kural TREND → kural korunur (mevcut davranış bozulmasın)."""
    d = _det()
    for kural in ("RANGE", "TREND_UP", "TREND_DOWN"):
        sonuc = d.piyasa_rejimi_birlestir(kural, _hmm("CALM"))
        assert sonuc == kural, f"CALM + {kural} → '{sonuc}'"


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA REJİM BİRLEŞTİRME — {len(testler)} test")
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
