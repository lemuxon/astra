# =========================================================
# ASTRA — STRATEJİ SEÇİMİ GİRİŞ KOŞULUNA BAKMALI (v58, K-102)
# Çalıştırma: python tests/test_strateji_secimi.py
#
# `strateji_sec` VOLATILE'de KOŞULSUZ `MEAN_REVERSION` seçiyordu. Ama
# MR'ın giriş koşulu "BUY ise RSI<30, SELL ise RSI>70" — ve AI bir
# MOMENTUM modeli: güç görünce BUY, zayıflık görünce SELL diyor.
# İkisi TABAN TABANA ZIT.
#
# ÖLÇÜLDÜ (§0.42, 1824 gerçek red):
#     RSI max 51.1 · medyan 36.9
#     RSI > 70 (SELL şartı):    0 / 1824   %0.0   ← HİÇ OLMADI
#     RSI < 30 (BUY şartı) :  478 / 1824   %26.2
#     AI BUY derken RSI ort. 53.9 (eşik <30) · SELL 40.8 (eşik >70)
#     Kesişen coin: 0/50
# Piyasa %96 VOLATILE olduğu için neredeyse HER sinyal, giriş koşulu
# sağlanamayan bir stratejiye yönlendiriliyordu.
#
# İLKE: giriş koşulunun sağlanamayacağı BİLİNEN strateji seçilmez.
# MR'ın mantığına DOKUNULMADI — o mean reversion için doğru; yanlış
# olan momentum setup'ına onu DAYATMAKTI.
#
# Ağ, veritabanı ve gerçek emir kullanılmaz.
# =========================================================
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

from engines.strategy_engine import StratejiEngine, MR_RSI_ALT, MR_RSI_UST


def _motor():
    e = StratejiEngine()
    e.mod = "AUTO"          # seçici yalnızca AUTO modda çalışır
    return e


def _s(karar, rsi):
    return {"karar": karar, "son_rsi": rsi, "sembol": "TESTUSDT"}


# ── K-102'NİN TA KENDİSİ ────────────────────────────────────────────
def test_momentum_setupta_MR_SECILMEZ():
    """AI zayıflıkta SELL diyor (RSI 41) — MR ise aşırı alım istiyor."""
    e = _motor()
    assert e.strateji_sec("VOLATILE", 3, 0.0, _s("SELL", 41.0)) == "TREND_FOLLOW"
    assert e.strateji_sec("VOLATILE", 3, 0.0, _s("BUY", 54.0)) == "TREND_FOLLOW"


def test_RANGE_de_ayni_kontrol_var():
    """Aynı hata RANGE dalında da vardı — orada bırakmak K-97→K-98
    tekrarını doğururdu."""
    e = _motor()
    # mtf_skor > 2 olmalı ki GRID'e düşmesin
    assert e.strateji_sec("RANGE", 3, 0.0, _s("SELL", 41.0)) == "TREND_FOLLOW"


# ── KONTROL TESTLERİ (§4.1) — "hep TREND_FOLLOW dön" de üsttekileri geçerdi ──
def test_GERCEK_MR_setupta_MR_SECILIR():
    """MR KALDIRILMADI: koşulu sağlanıyorsa hâlâ seçilmeli.

    Bu test olmadan "her zaman TREND_FOLLOW" mutasyonu da yukarıdaki
    testleri geçerdi — ve mean reversion sessizce ölürdü.
    """
    e = _motor()
    assert e.strateji_sec("VOLATILE", 3, 0.0, _s("BUY", 25.0)) == "MEAN_REVERSION"
    assert e.strateji_sec("VOLATILE", 3, 0.0, _s("SELL", 75.0)) == "MEAN_REVERSION"
    assert e.strateji_sec("RANGE", 3, 0.0, _s("BUY", 25.0)) == "MEAN_REVERSION"


def test_diger_rejimler_DEGISMEDI():
    """KONTROL: değişiklik HEDEFLİ — TREND/BEAR/GRID dokunulmadı."""
    e = _motor()
    assert e.strateji_sec("TREND_UP", 5, 0.0, _s("BUY", 50.0)) == "TREND_FOLLOW"
    assert e.strateji_sec("BEAR", 3, 0.0, _s("SELL", 50.0)) == "TREND_FOLLOW"
    assert e.strateji_sec("BEAR", 3, -0.001, _s("SELL", 50.0)) == "DCA"
    # RANGE + çok zayıf sinyal → hâlâ GRID
    assert e.strateji_sec("RANGE", 1, 0.0, _s("BUY", 25.0)) == "GRID"


def test_sonuc_verilmezse_ESKI_davranis():
    """Geriye dönük uyum: `sonuc` yoksa eski seçim korunur."""
    e = _motor()
    assert e.strateji_sec("VOLATILE", 3, 0.0) == "MEAN_REVERSION"


# ── MR FİLTRESİNİN KENDİSİ DEĞİŞMEDİ ───────────────────────────────
def test_MR_filtresinin_mantigi_AYNI():
    """Filtrenin içine dokunulmadı — yalnızca SEÇİM düzeltildi."""
    e = _motor()
    assert e.mean_reversion_filtre(_s("BUY", 25.0)) is True
    assert e.mean_reversion_filtre(_s("BUY", 54.0)) is False
    assert e.mean_reversion_filtre(_s("SELL", 75.0)) is True
    assert e.mean_reversion_filtre(_s("SELL", 41.0)) is False


def test_esikler_TEK_KAYNAK():
    """Seçici ve filtre AYNI eşiği kullanmalı — ayrışırlarsa seçici
    'uygun' der, filtre reddeder ve sinyal yine ölür.

    ⚠️ Eşik DEĞİŞTİRİLEREK doğrulanıyor: mevcut değerle tesadüfen
    eşleşen bir iddia ikisini ayırt edemezdi (§0.36'nın dersi).
    """
    import engines.strategy_engine as se
    e = _motor()
    asil_alt, asil_ust = se.MR_RSI_ALT, se.MR_RSI_UST
    try:
        se.MR_RSI_ALT, se.MR_RSI_UST = 45.0, 55.0
        # Yeni eşiğe göre RSI 40 artık "aşırı satım" sayılmalı
        assert e.mean_reversion_uygun_mu(_s("BUY", 40.0)) is True
        assert e.mean_reversion_filtre(_s("BUY", 40.0)) is True
        assert e.strateji_sec("VOLATILE", 3, 0.0, _s("BUY", 40.0)) == "MEAN_REVERSION"
    finally:
        se.MR_RSI_ALT, se.MR_RSI_UST = asil_alt, asil_ust


def test_yonsuz_sinyalde_MR_uygun_degil():
    """WAIT sinyalinde MR 'uygun' sayılmamalı (zaten işlem açılmaz)."""
    e = _motor()
    assert e.mean_reversion_uygun_mu({"karar": "⏳ WAIT", "son_rsi": 25.0}) is False


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA STRATEJİ SEÇİMİ (K-102) — {len(testler)} test")
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
