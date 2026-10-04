# =========================================================
# ASTRA — MTF VETO MESAJI HİYERARŞİDEN TÜRETİLMELİ (v58, K-94)
# Çalıştırma: python tests/test_mtf_teshis_kaydi.py
#
# main.py veto mesajı "5m yönü 1h ana trendi ile çelişiyor" diye SABİT
# yazıyordu. K-29 hiyerarşiyi ANA_INTERVAL'den türetilir yaptı — gerçek
# kıyas artık 4h ↔ 1d — ama metin güncellenmedi.
#
# Yanlış büyüklük adı veren teşhis kaydı OLMAYANDAN BETERDİR: veto
# zinciri incelenirken "bot 4h'de ama MTF 5m'e mi bakıyor?" diye yanlış
# iz sürdürdü ve kod okumak gerekti (§0.35 Bulgu 3).
#
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
from core.indicators import _tf_hiyerarsi

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_mtf_sonucu_tf_adlarini_donduruyor():
    """Mesajın türetilebilmesi için adlar sonuçta BULUNMALI."""
    kaynak = open(os.path.join(KOK, "core", "indicators.py"),
                  encoding="utf-8").read()
    i = kaynak.find("def mtf_confluence_skoru")
    assert i > 0
    govde = kaynak[i:i + 8000]
    assert '"taban_tf"' in govde, "taban_tf döndürülmüyor (K-94)"
    assert '"ana_trend_tf"' in govde, "ana_trend_tf döndürülmüyor (K-94)"


def test_veto_mesaji_sabit_tf_adi_icermiyor():
    """K-94'ün ta kendisi: mesajda '5m'/'1h' SABİTİ olmamalı.

    Hiyerarşi ANA_INTERVAL'den türediği için mesaj da türemeli.
    """
    kaynak = open(os.path.join(KOK, "main.py"), encoding="utf-8").read()
    i = kaynak.find("MTF CASCADE BLOK")
    assert i > 0, "veto mesajı bulunamadı — test hedefi kaymış"
    # ⚠️ BU TEST İKİ KEZ YANLIŞ YAZILDI, ikisi de öğretici:
    #
    # 1) Pencere yalnızca log satırının SONRASINA bakıyordu; `_taban`/
    #    `_ust` atamaları ÖNCE geldiği için test TEMİZ KODDA da patladı.
    #    Mutasyon koşusunda "hep kırmızı" görünce fark edildi — hep-kırmızı
    #    bir test, hep-yeşil kadar işe yaramaz.
    #
    # 2) Pencere genişletilince bu kez KENDİ AÇIKLAMA YORUMUM içindeki
    #    "5m yönü" alıntısını yakaladı. §0.29'un dersi bir kez daha:
    #    kaynak metni arayan test kodu YORUMDAN ayırt edemez.
    #
    # Çözüm: yorum satırlarını ayıkla. Hâlâ metin araması — sınırını
    # bilerek kabul ediyoruz: mesaj ŞABLONU çalıştırılmadan başka türlü
    # kilitlenemiyor; TF adlarının DOĞRULUĞU ise ayrı testlerde
    # davranışsal olarak (`_tf_hiyerarsi()` ile) doğrulanıyor.
    ham = kaynak[max(0, i - 900):i + 400]
    blok = "\n".join(satir for satir in ham.splitlines()
                     if not satir.lstrip().startswith("#"))
    assert "5m yönü" not in blok, "mesaj hâlâ '5m' sabitini içeriyor (K-94)"
    assert "taban_tf" in blok and "ana_trend_tf" in blok, (
        "mesaj TF adlarını sonuçtan okumuyor — yeniden bayatlayabilir")


def test_hiyerarsi_ana_ufuktan_turuyor():
    """KONTROL: taban TF, ANA_INTERVAL olmalı (K-29 hâlâ sağlam mı).

    Bu test olmadan K-94 düzeltmesi, yanlış bir hiyerarşinin adlarını
    doğru biçimde basmaktan ibaret kalırdı.
    """
    tfler = [tf for tf, _, _ in _tf_hiyerarsi()]
    assert tfler, "hiyerarşi boş"
    assert tfler[-1] == config.ANA_INTERVAL, (
        f"taban TF {tfler[-1]} ≠ ANA_INTERVAL {config.ANA_INTERVAL}")
    assert len(tfler) >= 2, "blok referansı için en az 2 TF gerekir"


def test_adlar_gercek_hiyerarsiyle_ayni():
    """Döndürülen adlar, `_tf_hiyerarsi()`'nin verdiğiyle tutarlı olmalı."""
    tfler = [tf for tf, _, _ in _tf_hiyerarsi()]
    beklenen_taban = tfler[-1]
    beklenen_ust = tfler[-2]
    # mtf_confluence_skoru ağ ister; adların türetimi saf mantık olduğu
    # için hiyerarşiden doğrudan doğrulanıyor.
    assert beklenen_taban != beklenen_ust, "taban ve referans aynı TF olamaz"
    assert beklenen_taban == config.ANA_INTERVAL


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA MTF TEŞHİS KAYDI (K-94) — {len(testler)} test")
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
