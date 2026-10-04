# =========================================================
# ASTRA — PANEL KORUMA SEVİYELERİNİ GÖSTERMELİ (v58, K-90)
# Çalıştırma: python tests/test_panel_koruma_alanlari.py
#
# SL/TP/tasfiye/marjin/zaman-stop alanlarının hepsi `trades` satırında
# ZATEN duruyordu; panel hiçbirini okumuyordu. Kaldıraçlı bir
# pozisyonda bakılacak asıl sayılar bunlar.
#
# ⚠️ DAVRANIŞSAL testler — kaynak metninde alan adı ARAMIYORLAR
# (§0.29 dersi). Ağ, veritabanı ve gerçek emir kullanılmaz.
# =========================================================
import os
import sys
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

import config
import main


def _kayit(**ek):
    t = {"sembol": "XRPUSDT", "yon": "LONG", "giris_fiyat": 1.34,
         "miktar": 39.05, "kaldirac": 3.0, "pnl": 0.0,
         "stop_loss": 1.307, "take_profit": 1.3894,
         "tasfiye_fiyat": 0.90023759, "marjin": 17.4733,
         "funding_maliyet": 0.011,
         "ts_ac": (datetime.utcnow() - timedelta(hours=5)).isoformat()}
    t.update(ek)
    return t


def test_koruma_seviyeleri_panele_tasiniyor():
    """K-90'ın ta kendisi: DB'de duran SL/TP/tasfiye/marjin panele geçmeli."""
    p = main._paper_pozlari_esle([_kayit()])[0]
    assert p["stop_loss"] == 1.307
    assert p["take_profit"] == 1.3894
    assert round(p["tasfiye"], 4) == 0.9002
    assert round(p["marjin"], 2) == 17.47


def test_zaman_stop_ilerlemesi_tasiniyor():
    """5 saattir açık bir pozisyon ~5 saat göstermeli, ufuk da gelmeli."""
    p = main._paper_pozlari_esle([_kayit()])[0]
    assert 4.8 < p["gecen_saat"] < 5.2, p["gecen_saat"]
    assert p["zaman_stop_saat"] and p["zaman_stop_saat"] > 0
    assert p["zaman_stop_doldu"] is False


def test_zaman_stop_ufku_motorla_ayni_kaynaktan():
    """§5.3 deseni: panel ufku 24 diye SABİT yazmamalı.

    ⚠️ BU TEST BİR KEZ ZAYIF YAZILDI. İlk hâli yalnızca
    `_zaman_stop_saat() == config.ZAMAN_STOP_SN/3600` diyordu — ama
    mevcut yapılandırmada o değer TAM 24 olduğu için, fonksiyonu
    `return 24` diye sabitleyen mutasyon testi GEÇTİ (24 == 24.0).

    Gerçek iddia "config'i İZLİYOR" olmalı: değeri DEĞİŞTİRİP peşinden
    gidiyor mu diye bak (K-82/K-83 sınıfı: bir yerde kalibre edilmiş
    sabit, başka yerde güncellenmemiş).
    """
    asil = getattr(config, "ZAMAN_STOP_SN", None)
    try:
        config.ZAMAN_STOP_SN = 12 * 3600
        assert main._zaman_stop_saat() == 12.0, "ufuk sabit yazılmış — config izlenmiyor"
        config.ZAMAN_STOP_SN = 36 * 3600
        assert main._zaman_stop_saat() == 36.0
    finally:
        if asil is not None:
            config.ZAMAN_STOP_SN = asil


def test_suresi_dolan_pozisyon_doldu_isaretlenir():
    eski = (datetime.utcnow() - timedelta(days=30)).isoformat()
    p = main._paper_pozlari_esle([_kayit(ts_ac=eski)])[0]
    assert p["zaman_stop_doldu"] is True


def test_ufuk_okunamazsa_ilerleme_uydurulmaz():
    """Motor çağrısı PATLARSA panel 'süre doldu' UYDURMAMALI.

    ⚠️ Bu testin ilk hâli bozuk bir `ts_ac` geçiriyordu — ama
    `zaman_stop_doldu_mu()` onu KENDİ İÇİNDE yakalayıp (False, 0.0)
    döndürüyor, yani main.py'daki `except` bloğu o girdide HİÇ
    çalışmıyordu. Test, kendi kodumu değil motorun davranışını ölçüyordu
    ve fallback'i "doldu=True" yapan mutasyonu KAÇIRDI.

    Doğrusu: çağrıyı gerçekten patlat, fallback'e bak.
    """
    import engines.futures_trade_engine as fte
    asil = fte.zaman_stop_doldu_mu

    def _patla(_):
        raise RuntimeError("ufuk okunamadı")

    try:
        fte.zaman_stop_doldu_mu = _patla
        p = main._paper_pozlari_esle([_kayit()])[0]
        assert p["zaman_stop_doldu"] is False, "hata hâlinde 'doldu' uyduruldu"
        assert p["gecen_saat"] is None, "hata hâlinde sahte ilerleme üretildi"
    finally:
        fte.zaman_stop_doldu_mu = asil


# ── KONTROL TESTLERİ (§4.1) — "hep None dön" de üsttekileri geçerdi ──
def test_eksik_seviyeler_sifira_dusurulmez():
    """§5.1: 'SL bilinmiyor' ile 'SL sıfırda' AYNI ŞEY DEĞİL.

    Canlı (futures) yolu bu alanları göndermiyor. 0 basmak panelde
    'stop sıfırda' diye okunur ve korumasız pozisyonda YANLIŞ güvence
    verir — fail-open deseninin ta kendisi.
    """
    ciplak = {"sembol": "ETHUSDT", "yon": "LONG", "giris_fiyat": 2500.0,
              "miktar": 0.02, "pnl": 0.0}
    p = main._paper_pozlari_esle([ciplak])[0]
    for alan in ("stop_loss", "take_profit", "tasfiye", "marjin"):
        assert p[alan] is None, f"{alan} uydurulmuş: {p[alan]!r}"


def test_bozuk_zaman_damgasi_uydurma_ilerleme_uretmez():
    """KONTROL: okunamayan ts_ac'de 'süre doldu' DEMEMELİ.

    (Bu yolu motor kendi içinde ele alıyor; fallback'in kendisi
    `test_ufuk_okunamazsa_ilerleme_uydurulmaz` ile ayrıca kilitli.)
    """
    p = main._paper_pozlari_esle([_kayit(ts_ac="tarih-degil")])[0]
    assert p["zaman_stop_doldu"] is False


def test_gecerli_degerler_none_olmuyor():
    """KONTROL: 'her şeye None dön' mutasyonu bu testi geçemez."""
    p = main._paper_pozlari_esle([_kayit()])[0]
    for alan in ("stop_loss", "take_profit", "tasfiye", "marjin", "gecen_saat"):
        assert p[alan] is not None, alan


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA PANEL KORUMA ALANLARI (K-90) — {len(testler)} test")
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
