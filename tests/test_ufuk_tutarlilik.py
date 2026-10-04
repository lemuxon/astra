# =========================================================
# ASTRA v58 — UFUK TUTARLILIK TESTLERİ (K-29)
# Çalıştırma: python tests/test_ufuk_tutarlilik.py
#
# NE KORUYOR:
#   Bot 5m'den 4h'e taşındı. Ufka bağımlı ayarlar TEK KAYNAKTAN
#   (`ANA_INTERVAL` / `ANA_PERIOD`) türemezse, bir kısmı 5m'de kalır ve
#   sistem yarı-taşınmış olur — hiçbir hata vermeden.
#
#   NEDEN 4h (ölçüm, 2026-09-04, 3 yıl 5 sembol):
#   `beceri farkı = başabaş P(TP) − ölçülen taban oran`
#       5m: +20.6 puan  ← yapısal olarak İMKÂNSIZ
#       1h: +2.9 puan
#       4h: +1.3 puan
#       1d: +0.2 puan
#   5m barda ATR medyanı %0.148; maliyet %0.11 → hedefin %37'si
#   maliyete gidiyordu. Beş hipotezin (R/R, üçlü bariyer, uzun pencere,
#   feature azaltma, piyasa yapısı) reddedilme sebebi buydu.
#
# ⚠️ BU TESTLER "4h DOĞRU UFUK" DEMİYOR. Ayarların birbiriyle TUTARLI
#   olduğunu doğruluyor. Ufuk değişirse hepsi birlikte değişmeli.
#
# §4.1: Muhafızların yanına kontrol testleri.
# =========================================================
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# v57: ÜRETİM durum dosyalarına yazmayı engelle. Proje modülleri import
# EDİLMEDEN ÖNCE çağrılmalı — config.py yolları import anında okur.
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("BINANCE_API_SECRET", "")


def _kod(dosya):
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       dosya)
    with open(yol, encoding="utf-8") as fh:
        return "\n".join(l for l in fh.read().splitlines()
                         if not l.strip().startswith("#"))


# ─────────────────────────────────────────────
# 1. MUHAFIZ — ana döngü sabit interval kullanmamalı
# ─────────────────────────────────────────────
def test_ana_dongu_sabit_interval_kullanmiyor():
    """`coin_analiz` çağrıları ANA_INTERVAL'den türemeli.

    Sabit `interval="5m"` kalsaydı bot 4h'e taşınmış SAYILIRDI ama
    sinyalleri hâlâ 5m'den üretirdi.
    """
    kod = _kod("main.py").replace(" ", "")
    assert 'interval="5m"' not in kod, (
        "main.py'da sabit `interval=\"5m\"` kalmış — ufuk taşıması yarım")
    assert "ANA_INTERVAL" in kod, \
        "main.py ANA_INTERVAL kullanmıyor"


def test_model_egitimi_ana_ufukla_ayni():
    """Eğitim ve servis AYNI zaman diliminde olmalı (K-22).

    Farklı olurlarsa model, eğitildiğinden bambaşka ölçekte feature
    görür (ATR, Momentum_5, Volatility_10 ölçekleri TF'ye bağlı).
    """
    from config import ANA_INTERVAL, MODEL_EGITIM_INTERVAL
    assert MODEL_EGITIM_INTERVAL == ANA_INTERVAL, (
        f"Eğitim {MODEL_EGITIM_INTERVAL}, servis {ANA_INTERVAL} — "
        f"feature ölçekleri uyuşmaz (K-22)")


def test_yeniden_giris_beklemesi_bar_goreli():
    """Bekleme süresi EN AZ bir bar olmalı.

    Sabit 300 sn, 5m barda "bir bar"dı; 4h barda aynı barın içinde
    48 kez yeniden girmeye izin verirdi — ufuk değişince sessizce
    anlamsızlaşan bir sabitti (K-29).
    """
    from config import YENIDEN_GIRIS_BEKLEME_SN, ANA_BAR_DK
    assert YENIDEN_GIRIS_BEKLEME_SN >= ANA_BAR_DK * 60, (
        f"Bekleme {YENIDEN_GIRIS_BEKLEME_SN} sn < bir bar "
        f"({ANA_BAR_DK*60} sn) — aynı bar içinde tekrar girilir")


def test_tur_tavani_bar_goreli():
    """Coin turu tavanı, turun içindeki işe göre ölçeklenmeli.

    ── ÖLÇÜLEN ARIZA (2026-09-04, 4h'e geçişten 8.3 saat sonra) ──
        tamamlanan tur : 0
        zaman aşımı    : 96
        paper işlem    : 0
    150 sn, 5m barı için ayarlanmış bir sabitti. 4h'de `coin_analiz`
    çok ağırlaştı (1081 bar + 1w MTF + 1081 barlık model eğitimi) ve
    tur HER SEFERİNDE iptal edildi; `sinyal_isle` sonuçlara hiç
    ulaşmadı.

    DEVAM_NOTLARI'ndaki v47 hatasının birebir tekrarı ("150s tur
    iptali → 42 sinyal ama 0 paper işlem"). O sefer sebep grafikti,
    bu sefer model eğitimi; ortak kök TURUN İÇİNDEKİ İŞTEN BAĞIMSIZ
    SABİT TAVAN.
    """
    from config import COIN_TUR_TIMEOUT, ANA_BAR_DK
    assert COIN_TUR_TIMEOUT >= 150,         f"Tur tavanı {COIN_TUR_TIMEOUT} sn — 150'nin altına inmemeli"
    # Uzun ufukta tavan da uzamalı: en az barın 1/24'ü
    assert COIN_TUR_TIMEOUT >= ANA_BAR_DK * 60 // 24, (
        f"Tur tavanı {COIN_TUR_TIMEOUT} sn, bir barın 1/24'ü "
        f"({ANA_BAR_DK*60//24} sn) altında — ağır turlar iptal edilir "
        f"ve sinyal işlenmez")


def test_tur_tavani_bir_bardan_KISA():
    """Kontrol testi (§4.1). Tavan sınırsız da olmamalı.

    Tur bir bardan uzun sürerse bot bar atlar; "tavanı çok büyüt"
    diyen bir düzeltme yukarıdaki muhafızı geçerdi ama yeni bir
    sorun yaratırdı.
    """
    from config import COIN_TUR_TIMEOUT, ANA_BAR_DK
    assert COIN_TUR_TIMEOUT < ANA_BAR_DK * 60, (
        f"Tur tavanı {COIN_TUR_TIMEOUT} sn ≥ bir bar ({ANA_BAR_DK*60} sn) "
        f"— tur barı geçerse bot bar atlar")


def test_mtf_hiyerarsisi_ana_ufuktan_turuyor():
    """MTF merdiveninin TABANI ana ufuk olmalı.

    Eskiden 4h/1h/15m/5m sabitti. Ana ufuk 4h olunca "tetikleyici"
    5m kalırdı — işlem barından 48 kat küçük bir gürültü, veto
    gerekçesi olurdu.
    """
    from core.indicators import _tf_hiyerarsi
    from config import ANA_INTERVAL
    tfler = [tf for tf, _, _ in _tf_hiyerarsi()]      # üstten alta
    assert tfler, "MTF hiyerarşisi boş"
    assert tfler[-1] == ANA_INTERVAL, (
        f"MTF tabanı {tfler[-1]}, ana ufuk {ANA_INTERVAL} — uyuşmuyor")

    # ⚠️ Yardımcının doğru olması YETMEZ — TÜKETİCİ onu kullanmalı.
    # Bu satır olmadan, `mtf_confluence_skoru` içinde hiyerarşiyi
    # yeniden sabit kodlayan bir değişiklik testi GEÇERDİ.
    # (Mutasyon denemesinde tam olarak bu oldu; §4.1 "yanlış katman".)
    kod = _kod(os.path.join("core", "indicators.py"))
    i = kod.find("def mtf_confluence_skoru")
    assert i > 0, "mtf_confluence_skoru bulunamadı — test hedefi kaymış"
    govde = kod[i:i + 2000]
    assert "_tf_hiyerarsi()" in govde, (
        "mtf_confluence_skoru `_tf_hiyerarsi()` çağırmıyor — hiyerarşi "
        "içeride sabit kodlanmış olabilir")
    assert '"interval": "5m"' not in govde.replace(" ", "").replace('"interval":"5m"', '"interval": "5m"'), (
        "mtf_confluence_skoru içinde sabit TF tanımı kalmış")


def test_mtf_ana_trend_sabit_1h_degil():
    """`ana_trend_yon` hiyerarşiden türemeli, "1h"e sabit olmamalı.

    Sabit kalsaydı 4h tabanda hiyerarşide "1h" HİÇ bulunmaz,
    ana_trend_yon her zaman "NÖTR" olur ve MTF cascade vetosu
    SESSİZCE ÖLÜRDÜ (§5.2).
    """
    kod = _kod(os.path.join("core", "indicators.py")).replace(" ", "")
    assert 'analizler.get("1h",{})' not in kod, (
        "ana_trend_yon hâlâ \"1h\"e sabit — 4h tabanda MTF vetosu ölür")
    assert "_ana_trend_tf" in kod, \
        "ana_trend TF'si hiyerarşiden türetilmiyor"


# ─────────────────────────────────────────────
# 2. KONTROL — eski davranış hâlâ üretilebilmeli
# ─────────────────────────────────────────────
def test_5m_secilirse_ESKI_hiyerarsi_geri_gelir():
    """Kontrol testi (§4.1). ANA_INTERVAL=5m → eski 4h/1h/15m/5m.

    Bu test olmadan, hiyerarşiyi tek bir TF'ye indiren bir 'düzeltme'
    de muhafızları geçerdi. Ayrıca 5m'e geri dönüş yolunu açık tutar.
    """
    import importlib, config
    import core.indicators as ind
    eski = os.environ.get("ANA_INTERVAL")
    os.environ["ANA_INTERVAL"] = "5m"
    try:
        importlib.reload(config); importlib.reload(ind)
        tfler = [tf for tf, _, _ in ind._tf_hiyerarsi()]
        assert tfler == ["4h", "1h", "15m", "5m"], (
            f"5m tabanda eski hiyerarşi üretilmiyor: {tfler}")
    finally:
        if eski is None:
            os.environ.pop("ANA_INTERVAL", None)
        else:
            os.environ["ANA_INTERVAL"] = eski
        importlib.reload(config); importlib.reload(ind)


def test_hiyerarsi_agirliklari_ustten_alta_azalir():
    """Kontrol: üst TF'nin ağırlığı tabandan büyük olmalı."""
    from core.indicators import _tf_hiyerarsi
    h = _tf_hiyerarsi()
    agirliklar = [ag for _, _, ag in h]
    assert agirliklar == sorted(agirliklar, reverse=True), (
        f"Ağırlıklar üstten alta azalmıyor: {agirliklar}")
    assert agirliklar[-1] == 1.0, \
        f"Taban TF ağırlığı 1.0 olmalı, {agirliklar[-1]} bulundu"


def test_ana_ufuk_yeterli_bar_veriyor():
    """Kontrol: ANA_PERIOD, EMA200 için yeterli bar sağlamalı.

    Yetersizse `feature_olustur` dropna sonrası boş döner ve model
    hiç eğitilemez — sessiz bir ölüm.
    """
    from config import ANA_PERIOD, ANA_INTERVAL
    from data.binance_client import _period_to_limit
    bar = _period_to_limit(ANA_PERIOD, ANA_INTERVAL)
    assert bar >= 300, (
        f"{ANA_PERIOD}/{ANA_INTERVAL} yalnızca {bar} bar veriyor; "
        f"EMA200 + ısınma için en az 300 gerekir")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA UFUK TUTARLILIK — {len(testler)} test")
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
