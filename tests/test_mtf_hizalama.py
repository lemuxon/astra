# =========================================================
# ASTRA — MTF HİZALAMA SKORU (v58, K-96)
# Çalıştırma: python tests/test_mtf_hizalama.py
#
# Eskiden referans KOŞULSUZ `ana_trend_yon` idi. Ana trend TF'si (taban+1)
# NÖTR olduğunda `hizali_tf` KOŞULSUZ boş kalıyor, skor her zaman 0 çıkıyor
# ve main.py bunu "MTF hizalama yok" diye VETO ediyordu.
#
# ÖLÇÜLDÜ (§0.35 Bulgu 1, 50 coin):
#     hizalama_skoru == 0 : 17 coin
#     ana_trend_yon NÖTR  : 17 coin      ← BİREBİR AYNI KÜME
# Veto "hizalama yok" değil, "1d'nin yönü yok" demekti.
#
# ⚠️ DAVRANIŞSAL testler — gerçek `mtf_confluence_skoru` sahte veriyle
# sürülüyor, kaynak metni ARANMIYOR (§0.29/§0.36 dersleri).
# Ağ kullanılmaz: `veri_indir_fn` taklit edilir.
# =========================================================
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

import pandas as pd

import core.indicators as ind


# ⚠️ DOĞRU KATMANI TAKLİT ET (§4.1).
# İlk denemede sahte OHLCV üretip `_tf_analiz`'in ondan "NÖTR" çıkarmasını
# ummuştum — çıkarmadı: yatay+salınımlı serim RSI 100 ile LONG okundu ve
# üç test birden YANLIŞ sebeple kırmızıya döndü. Kusur koddaydı değil,
# FİKSTÜRDEYDİ (§0.1'in dersi: gerçekçi olmayan fikstür gerçek bir kapıyı
# test edilemez kılar).
#
# Test edilen şey `mtf_confluence_skoru`'nun HİZALAMA MANTIĞI; `_tf_analiz`
# onun ALTINDAKİ katman. Onu stub'lamak doğru sınır: değiştirdiğim mantık
# gerçek kodla sürülüyor, kontrol edemediğim gösterge davranışı dışarıda.
def _sahne(yon_haritasi: dict):
    """TF → yön haritasını `mtf_confluence_skoru`'ya dayatan sahne.

    Döner: (sahte_indirici, geri_al_fonksiyonu)
    """
    hiyerarsi = ind._tf_hiyerarsi()
    aralik_tf = {ayar["interval"]: tf for tf, ayar, _ in hiyerarsi}

    def _indir(sembol, period, interval):
        df = pd.DataFrame({
            "Open": [1.0] * 60, "High": [1.0] * 60, "Low": [1.0] * 60,
            "Close": [1.0] * 60, "Volume": [1.0] * 60,
        })
        df.attrs["_test_tf"] = aralik_tf.get(interval, "?")
        return df

    def _sahte_analiz(df):
        tf = (df.attrs or {}).get("_test_tf", "?")
        yon = yon_haritasi.get(tf, "NÖTR")
        guc = 0.0 if yon == "NÖTR" else 1.0
        return {"yon": yon, "guc": guc, "skor": 0 if yon == "NÖTR" else 5,
                "tam_hizalama": yon != "NÖTR", "rsi": 50.0,
                "macd_yukari": yon == "LONG", "fiyat_ema50": 0.0}

    ind._mtf_cache.clear()                  # önbellek testler arası sızmasın
    asil = ind._tf_analiz
    ind._tf_analiz = _sahte_analiz
    return _indir, (lambda: setattr(ind, "_tf_analiz", asil))


def _olc(yon_haritasi: dict) -> dict:
    """Sahneyi kur, gerçek `mtf_confluence_skoru`'yu çalıştır, geri al."""
    indir, geri_al = _sahne(yon_haritasi)
    try:
        return ind.mtf_confluence_skoru("TESTUSDT", indir)
    finally:
        geri_al()
        ind._mtf_cache.clear()


def _tfler():
    t = [tf for tf, _, _ in ind._tf_hiyerarsi()]
    return t[-1], t[-2], t[0]               # taban, ana_trend, en_üst


def test_ana_trend_notrken_hizalama_SAYILIR():
    """K-96'nın ta kendisi: 1d nötrken 1w+4h hemfikirse skor 0 OLMAMALI."""
    taban, ana, ust = _tfler()
    m = _olc({ust: "LONG", ana: "NÖTR", taban: "LONG"})
    assert m["ana_trend_yon"] == "NÖTR", f"sahne kurulmadı: {m['detay']}"
    assert m["hizalama_skoru"] >= 2, (
        f"ana trend nötrken hizalama sayılmıyor (K-96): "
        f"skor={m['hizalama_skoru']} detay={ {k: v['yon'] for k, v in m['detay'].items()} }")


def test_ana_trend_notr_ve_taban_yonlu_ise_skor_en_az_1():
    """Yalnızca işlem barının görüşü varsa: veto değil, zayıf sinyal."""
    taban, ana, ust = _tfler()
    m = _olc({ust: "NÖTR", ana: "NÖTR", taban: "SHORT"})
    assert m["hizalama_skoru"] >= 1, "taban yön bildirirken skor 0 kalmış"


# ── KONTROL TESTLERİ (§4.1) — "hep yüksek skor dön" de üsttekileri geçerdi ──
def test_TUM_TF_NOTRSE_skor_0_KALIR():
    """Gerçekten bilgi yoksa veto DEVAM etmeli — kapı açılmadı."""
    taban, ana, ust = _tfler()
    m = _olc({ust: "NÖTR", ana: "NÖTR", taban: "NÖTR"})
    assert m["hizalama_skoru"] == 0, (
        f"tüm TF nötrken skor üretiliyor: {m['hizalama_skoru']}")


def test_ana_trend_YONLU_ise_davranis_DEGISMEDI():
    """Değişiklik HEDEFLİ: ana trend yön bildiriyorsa eski davranış aynen.

    Referans o durumda hâlâ `ana_trend_yon`; hizalı TF'ler onunla ölçülür.
    """
    taban, ana, ust = _tfler()
    m = _olc({ust: "LONG", ana: "LONG", taban: "LONG"})
    assert m["ana_trend_yon"] == "LONG"
    assert m["hizalama_skoru"] == 3, f"tam hizalamada skor {m['hizalama_skoru']}"
    assert m["bloklu"] is False


def test_cascade_BLOGU_hala_calisiyor():
    """KONTROL: taban ana trende TERSSE hâlâ bloklanmalı.

    K-96 yalnızca SAYMAYI düzeltti; "üst TF'ye karşı işlem açma"
    çekirdeği dokunulmadan kaldı.
    """
    taban, ana, ust = _tfler()
    m = _olc({ust: "LONG", ana: "LONG", taban: "SHORT"})
    assert m["bloklu"] is True, "cascade bloğu kırılmış — K-29/K-96 regresyonu"


def test_ana_trend_notrken_BLOK_atmaz():
    """Üst TF'nin görüşü yoksa karşı çıkılacak şey de yoktur."""
    taban, ana, ust = _tfler()
    m = _olc({ust: "LONG", ana: "NÖTR", taban: "SHORT"})
    assert m["bloklu"] is False, "ana trend nötrken blok atıyor"


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA MTF HİZALAMA (K-96) — {len(testler)} test")
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
            print(f"  [ÇÖKTÜ]  {test.__name__}: {type(exc).__name__}: {str(exc)[:120]}")
            hata += 1
    print(f"{'=' * 58}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'=' * 58}\n")
    sys.exit(0 if hata == 0 else 1)
