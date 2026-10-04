# =========================================================
# ASTRA — GEÇ GİRİŞ EŞİĞİ ATR İLE ÖLÇEKLENİR (v58, K-95)
# Çalıştırma: python tests/test_giris_kayma_esigi.py
#
# Eski tavan `MAX_GIRIS_KAYMA_PCT * 2` = %0.70 MUTLAK sabitti ve ATR
# uyarlamasını SÖNDÜRÜYORDU (§0.35 Bulgu 2):
#     tavanın bağladığı nokta : ATR% > 2.33
#     medyan 4h ATR%          : 2.43   ← medyan coin ZATEN tavanda
#     tavana dayanan          : 27/50 (%54)
#
# ⚠️ DAVRANIŞSAL testler — kaynak metni ARAMIYORLAR. Bu oturumda
# metin araması üç kez zayıf çıktı (§0.29, §0.36); hesap tam da bu
# yüzden `futures_trade_engine`'e ayrı fonksiyon olarak çıkarıldı.
# Ağ ve üretim verisi kullanılmaz.
# =========================================================
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

import config
from engines.futures_trade_engine import giris_kayma_esigi

TABAN = config.MAX_GIRIS_KAYMA_PCT
ESKI_TAVAN = TABAN * 2          # %0.70 — kaldırılan mutlak sabit


def test_yuksek_atrde_eski_tavan_asilir():
    """K-95'in ta kendisi: oynak coin artık %0.70'e kırpılmamalı."""
    # ETHFIUSDT vakası: ATR %6.81 → amaçlanan eşik %1.37 idi
    esik = giris_kayma_esigi(6.81)
    assert esik > ESKI_TAVAN, f"hâlâ kırpılıyor: {esik:.3f} <= {ESKI_TAVAN}"
    assert abs(esik - (TABAN + 6.81 * 0.15)) < 0.01, (
        f"uyarlama terimi bağlayıcı değil: {esik:.3f}")


def test_medyan_atrde_de_kirpilmiyor():
    """Medyan 4h ATR %2.43 tam eski tavanın bağladığı noktaydı."""
    assert giris_kayma_esigi(2.43) > ESKI_TAVAN


# ── KONTROL TESTLERİ (§4.1) — "tavanı tamamen kaldır" da geçerdi ────
def test_dusuk_atrde_esik_DEGISMEDI():
    """Sakin coinlerde davranış AYNI kalmalı — değişiklik hedefli.

    BTCUSDT ATR %0.86 · TRXUSDT %0.54 · PAXGUSDT %0.41: bunlarda
    eski formül zaten tavana dayanmıyordu, dokunulmamalı.
    """
    for atr in (0.41, 0.54, 0.86):
        assert abs(giris_kayma_esigi(atr) - (TABAN + atr * 0.15)) < 1e-9


def test_esik_hala_SINIRLI():
    """Tavan kaldırılmadı, ÖLÇEKLENDİ — absürt ATR sınırsız tolerans vermez."""
    esik = giris_kayma_esigi(500.0)
    tavan = 500.0 * config.FUTURES_SL_ATR_MULT * config.MAX_GIRIS_KAYMA_STOP_PAYI
    assert esik <= tavan + 1e-9, "tavan devre dışı kalmış"
    assert esik < 500.0, "eşik ATR'nin kendisi kadar büyümemeli"


def test_buyuk_kayma_hala_reddedilir():
    """KONTROL: ölçülen en büyük kaymalar YİNE geçmemeli.

    FORMUSDT %2.07 kaymıştı, ATR'si %3.68. Bu düzeltme "her şeyi
    kabul et" demek DEĞİL — kovalama yasağı sürüyor.
    """
    assert 2.07 > giris_kayma_esigi(3.68), "büyük kayma artık geçiyor — fazla gevşek"


def test_taban_altina_dusmez():
    """ATR sıfır/bilinmiyorken bile taban korunur."""
    for bozuk in (0.0, -1.0, None, "abc"):
        assert giris_kayma_esigi(bozuk) >= TABAN - 1e-9, bozuk


def test_tavan_SL_carpanindan_turuyor():
    """§5.3 deseni: tavan sabit yazılmamalı, SL politikasını izlemeli.

    ⚠️ §0.36'nın dersi: mevcut değerle tesadüfen eşleşen bir iddia,
    "türüyor" ile "sabit yazılmış"ı ayırt edemez. Bu yüzden SL çarpanı
    DEĞİŞTİRİLİP peşinden gidip gitmediğine bakılıyor.

    ⚠️ İKİNCİ TUZAK (bu testte yaşandı): ATR=500 seçmiştim, ama orada
    tavan HİÇBİR çarpanda bağlamıyor — uyarlama terimi (75.35) ikisinden
    de küçük. Test "izlemiyor" diye kırmızı verdi, oysa kod doğruydu;
    kusur TESTİN ÖNCÜLÜNDEYDİ. Tavanın FİİLEN bağladığı bir ATR gerekir.
    Ölçüldü: ATR=10'da SL=0.5 tavanı (1.67) uyarlamayı (1.85) kırpıyor.
    """
    asil = config.FUTURES_SL_ATR_MULT
    ATR = 10.0                                   # tavanın bağladığı bölge
    try:
        config.FUTURES_SL_ATR_MULT = 0.5        # stop çok yakın → dar tavan
        dar = giris_kayma_esigi(ATR)
        config.FUTURES_SL_ATR_MULT = 3.0        # stop uzak → tavan bağlamaz
        genis = giris_kayma_esigi(ATR)
        assert genis > dar, (
            f"tavan SL çarpanını izlemiyor (sabit yazılmış): {genis} vs {dar}")
    finally:
        config.FUTURES_SL_ATR_MULT = asil


def test_paper_ve_canli_AYNI_kaynagi_kullaniyor():
    """§5.3: iki yol da `giris_kayma_esigi()` çağırmalı.

    Paper'da formülün İKİNCİ BİR KOPYASI vardı (`min(taban+ATR*0.15,
    taban*2)`) ve docstring'i "canlıyla aynı formül" diye söz veriyordu.
    Canlı ATR-ölçekli tavana geçerken burası güncellenmeseydi iki yol
    ayrışır, söz sessizce yalan olurdu — K-13/K-69/K-78/K-85/K-86 deseni.

    ⚠️ Metin araması değil DAVRANIŞ: aynı ATR ikisinde de aynı eşiği
    vermeli. Paper'ın kendi kopyası kalsaydı yüksek ATR'de ayrışırdı.
    """
    import inspect
    import engines.paper_trading as pt
    kaynak = inspect.getsource(pt._giris_fiyati) if hasattr(pt, "_giris_fiyati") \
        else inspect.getsource(pt.PaperTrader._giris_fiyati)
    # Kopyanın imzası: tavanın `_taban * 2` diye ELDE hesaplanması
    satirlar = [s for s in kaynak.splitlines()
                if not s.lstrip().startswith("#")]
    govde = "\n".join(satirlar)
    assert "giris_kayma_esigi" in govde, "paper ortak fonksiyonu çağırmıyor"
    assert "_taban * 2" not in govde, "paper'da ikinci kopya hâlâ duruyor"


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA GEÇ GİRİŞ EŞİĞİ (K-95) — {len(testler)} test")
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
