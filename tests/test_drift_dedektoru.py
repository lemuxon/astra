# =========================================================
# ASTRA v58 — FEATURE DRIFT DEDEKTÖRÜ (K-43)
# Çalıştırma: python tests/test_drift_dedektoru.py
#
# NE KORUYOR:
#   Üretim logunda drift z-skorları 10^15 mertebesine çıkıyordu:
#       [DRIFT/ETHUSDT] Feature drift tespit edildi! z=717347997812664.62
#   Sağlıklı bir z-skoru tek hanelidir. Ölçüm (4h dönemi, 162 alarm):
#       z > 1000 olan: 53/162 (%33) · en yüksek 1.9e15
#   Bu alarmlar 165 GEREKSİZ retrain tetikledi (CPU israfı).
#
#   İKİ AYRI HATA:
#   1. `std = float(np.std(...)) or 1.0` — `or` yalnızca std TAM 0
#      olduğunda devreye girer. std=1e-15 geçip bölmeyi patlatıyordu.
#   2. KÖK NEDEN: 4h'de bar 6 saatte bir kapanıyor ama analiz ~60 sn'de
#      bir çalışıyor. AYNI kapanmış barın feature'ları geçmişe defalarca
#      ekleniyor → son 20 kayıt birbirinin aynısı → std ≈ 0.
#      5m'de bar 5 dk'da kapandığı için sorun GÖRÜNMÜYORDU.
#      ➜ K-29/K-30 ile aynı sınıf: ufka bağlı sessiz varsayım.
#
# §4.1: Muhafızların yanına KONTROL testleri var — "hiç drift bulma"
#   davranışı da patlama testlerini geçerdi.
# =========================================================
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

import main
from main import _feature_drift_kontrol, _drift_ayni_bar, _DRIFT_FEATURELARI


def _sifirla():
    """Dedektörün sembol geçmişini temizle (fonksiyon niteliği)."""
    if hasattr(_feature_drift_kontrol, "_history"):
        _feature_drift_kontrol._history = {}


def _f(rsi=50.0, macd=0.1, atr=1.0, vol=1.0, adx=25.0):
    return {"RSI": rsi, "MACD": macd, "ATR_pct": atr,
            "Volume_Ratio": vol, "ADX": adx}


# ─────────────────────────────────────────────
# 1. MUHAFIZ — z-skoru patlamamalı
# ─────────────────────────────────────────────
def test_ayni_bar_tekrar_edince_z_patlamaz():
    """AYNI feature satırı 30 kez gelir, sonra farklı bir bar gelir.

    Eski kodda: 20 özdeş kayıt → std≈0 → z = 10^15 → sahte drift.
    Yeni kodda: tekrarlar geçmişe eklenmez, sahte alarm yok.
    """
    _sifirla()
    sabit = _f()
    for _ in range(30):
        assert _feature_drift_kontrol("TESTX", dict(sabit)) is False, (
            "Aynı bar tekrar edince drift bildirildi — dedektör aynı "
            "kapanmış barı yeni bilgi sanıyor")
    # Şimdi gerçekten farklı bir bar
    sonuc = _feature_drift_kontrol("TESTX", _f(rsi=52.0, macd=0.12))
    assert sonuc is False, (
        "Küçük ve tek seferlik değişim 'drift' sayıldı — geçmişte yeterli "
        "varyans yokken drift kararı verilmemeli")


def test_sabit_feature_z_skoru_uretmez():
    """Sabit kalan bir feature drift skoruna KATKI VERMEMELİ.

    `or 1.0` ikamesi sabit bir feature'ı sahte drift kaynağına
    çeviriyordu: std=0 → 1.0 ile bölünüyor → (mevcut−ortalama) kadar
    z üretiyor. Doğrusu o feature'ı ATLAMAK.
    """
    _sifirla()
    # RSI hariç hepsi sabit; RSI'da gerçek varyans var
    import random
    random.seed(0)
    for i in range(25):
        _feature_drift_kontrol("TESTS", _f(rsi=50 + random.uniform(-1, 1),
                                           macd=0.1, atr=1.0, vol=1.0, adx=25.0))
    # Sabit feature'lardan biri BÜYÜK sıçrasa bile z patlamamalı
    _feature_drift_kontrol("TESTS", _f(rsi=50.5, macd=999.0))
    # Patlama olmadığını kanıtla: hiçbir uyarı z'si sonsuz/çok büyük değil
    # (fonksiyon bool döndürüyor; asıl kanıt aşağıdaki kontrol testinde)


def test_drift_ayni_bar_yardimcisi():
    """`_drift_ayni_bar` aynı/farklı satırı doğru ayırmalı."""
    a = _f()
    assert _drift_ayni_bar(a, dict(a)) is True
    assert _drift_ayni_bar(a, _f(rsi=50.0000001)) is False, (
        "Küçük ama gerçek fark 'aynı bar' sayıldı")
    assert _drift_ayni_bar(a, _f(adx=26.0)) is False


def test_eksik_alan_cokme_yaratmaz():
    """None/eksik feature'lar istisna atmadan işlenmeli."""
    _sifirla()
    for _ in range(25):
        _feature_drift_kontrol("TESTN", {"RSI": 50.0})        # diğerleri yok
    assert _feature_drift_kontrol("TESTN", {"RSI": None}) in (True, False)
    assert _feature_drift_kontrol("TESTN", {}) in (True, False)


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_dedupe_OLMADAN_dedektor_KOR_kalir():
    """Dedupe'un KENDİNE ÖZGÜ işlevi: 4h tekrarlarına rağmen görebilmek.

    ⚠️ Bu test sonradan eklendi: mutasyon testi, dedupe'u kaldıran
    değişikliğin YAKALANMADIĞINI gösterdi — çünkü std eşiği patlamayı
    zaten önlüyordu. İki düzeltme birbirini örtüyordu.

    Dedupe'un asıl işlevi patlamayı önlemek DEĞİL: geçmişin GERÇEK
    barlardan oluşmasını sağlamak. Onsuz geçmiş aynı barın 20 kopyasıyla
    dolar, tüm feature'lar sabit görünür, hepsi std eşiğinde atlanır ve
    dedektör GERÇEK drift'i de göremez hale gelir.

    Üretim davranışını taklit ediyoruz: her bar ~240 kez tekrar ediyor
    (4h bar / 60 sn analiz). TEKRAR SAYISI PENCEREDEN (20) BÜYÜK OLMALI —
    aksi halde son-20 penceresi birden çok barı kapsar, std sıfıra
    inmez ve test dedupe'suz kodu da geçirir (ilk sürümde 12 kullanılmış
    ve mutasyonu yakalayamamıştı).
    """
    _sifirla()
    import random
    random.seed(7)
    # 25 FARKLI bar, her biri 25 kez tekrarlanarak besleniyor (>20 pencere)
    for _ in range(25):
        bar = _f(rsi=50 + random.uniform(-2, 2),
                 macd=0.1 + random.uniform(-0.02, 0.02),
                 atr=1.0 + random.uniform(-0.05, 0.05),
                 vol=1.0 + random.uniform(-0.1, 0.1),
                 adx=25 + random.uniform(-2, 2))
        for _ in range(25):
            _feature_drift_kontrol("TESTR", dict(bar))
    # Şimdi açıkça kaymış GERÇEK bir bar
    sonuc = _feature_drift_kontrol("TESTR", _f(
        rsi=95.0, macd=1.5, atr=5.0, vol=8.0, adx=70.0))
    assert sonuc is True, (
        "Tekrarlı barlardan sonra GERÇEK drift görülemedi — dedupe "
        "kaldırılmış olabilir. Geçmiş aynı barın kopyalarıyla dolunca "
        "tüm feature'lar sabit görünür ve std eşiğinde atlanır; dedektör "
        "kör kalır.")


def test_kontrol_GERCEK_drift_hala_yakalaniyor():
    """AŞIRI DÜZELTME KONTROLÜ: gerçek dağılım kayması BULUNMALI.

    "Hiç drift bulma" davranışı yukarıdaki tüm patlama testlerini
    geçerdi — ama dedektör işe yaramaz hale gelirdi.
    """
    _sifirla()
    import random
    random.seed(1)
    # 25 bar normal dağılım (RSI ~50±2)
    for _ in range(25):
        _feature_drift_kontrol("TESTD", _f(
            rsi=50 + random.uniform(-2, 2),
            macd=0.1 + random.uniform(-0.02, 0.02),
            atr=1.0 + random.uniform(-0.05, 0.05),
            vol=1.0 + random.uniform(-0.1, 0.1),
            adx=25 + random.uniform(-2, 2)))
    # Sonra AÇIKÇA kaymış bir bar (hepsi ~10+ sigma)
    sonuc = _feature_drift_kontrol("TESTD", _f(
        rsi=95.0, macd=1.5, atr=5.0, vol=8.0, adx=70.0))
    assert sonuc is True, (
        "Açık ve büyük dağılım kayması yakalanmadı — düzeltme aşırıya "
        "kaçmış, dedektör artık hiçbir şey bulmuyor")


def test_kontrol_normal_dalgalanma_drift_SAYILMAZ():
    """Normal gürültü drift olmamalı — aksi halde sürekli alarm.

    Üretimde tam bu oluyordu: 162 alarm, 165 gereksiz retrain.
    Sürekli alarm = alarm yok.
    """
    _sifirla()
    import random
    random.seed(2)
    for _ in range(25):
        _feature_drift_kontrol("TESTQ", _f(
            rsi=50 + random.uniform(-2, 2),
            macd=0.1 + random.uniform(-0.02, 0.02),
            atr=1.0 + random.uniform(-0.05, 0.05),
            vol=1.0 + random.uniform(-0.1, 0.1),
            adx=25 + random.uniform(-2, 2)))
    alarm = 0
    for _ in range(20):
        if _feature_drift_kontrol("TESTQ", _f(
                rsi=50 + random.uniform(-2, 2),
                macd=0.1 + random.uniform(-0.02, 0.02),
                atr=1.0 + random.uniform(-0.05, 0.05),
                vol=1.0 + random.uniform(-0.1, 0.1),
                adx=25 + random.uniform(-2, 2))):
            alarm += 1
    assert alarm <= 2, (
        f"20 normal barda {alarm} drift alarmı — eşik anlamsız, "
        f"dedektör gürültüye alarm veriyor")


def test_kontrol_std_esigi_kaynakta_var():
    """Kaynak düzeyi: `or 1.0` deseni GERİ GELMEMELİ."""
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "main.py"), encoding="utf-8") as fh:
        kaynak = fh.read()
    assert "np.std(gecmis_degerler)) or 1.0" not in kaynak, (
        "`or 1.0` ikamesi geri gelmiş — std=1e-15 bölmeyi patlatır")
    assert "olcek * 1e-6" in kaynak, (
        "Ölçek-göreli std eşiği yok — mutlak sıfır kontrolü yetmez")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA DRIFT DEDEKTÖRÜ — {len(testler)} test")
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
