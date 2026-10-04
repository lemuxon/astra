# =========================================================
# ASTRA v58 — MODEL BECERİSİ: SEÇİM ve NÖTRLEME (K-37)
# Çalıştırma: python tests/test_model_beceri.py
#
# NE KORUYOR — üç ayrı kusur:
#
# 1) SEÇİM HAM ACCURACY'YE BAKIYORDU.
#    `walk_forward_cv` ham accuracy döndürüyor, seçim `max(..., WF)` ile
#    onu karşılaştırıyordu. Ama sınıf dengesi katmandan katmana oynuyor
#    (ölçüm: 4h, 3 yıl, 5 sembol, 40 katman → taban ort 0.5151, aralık
#    0.5007–0.5351). Taban 0.5351 olan katmanda 0.54 accuracy hiçbir şey;
#    taban 0.5007 olan katmanda aynı sayı gerçek beceri. Ham accuracy ile
#    seçmek BECERİYİ değil SINIF DENGESİZLİĞİNİ ödüllendirir.
#
# 2) SABİT EŞİK YANLIŞ BÜYÜKLÜĞÜ ÖLÇÜYORDU.
#    `MIN_USEFUL_ACC = 0.52` sabit. Katmanların %25'inde taban çizgisi
#    zaten 0.52'nin ÜSTÜNDE — orada eşiği geçen model sabit tahminciden
#    KÖTÜ olduğu halde "faydalı" sayılıyordu.
#
# 3) BECERİ YOKKEN DE MODELE GÜVENİLİYORDU.  ← en önemlisi
#    WF beceri değerleri 0.00–0.05, std 0.04–0.08: çoğu model taban
#    çizgisinden ayırt edilemez. Sistem yine de birini seçip
#    predict_proba çıktısını `yukselis_guveni` yapıyordu; o da doğrudan
#    ai_score'a giriyor. Üretim logu: 4037 kez "acc<0.52 → yeniden eğit"
#    — yani gürültünün üst kuyruğu aranıyordu.
#
#    §5.1'deki fail-open deseninin aynası:
#      orada  "bilmiyorum"             → "sorun yok"
#      burada "ölçülebilir beceri yok"  → "işte güvenilir olasılık"
#
# §4.1: Muhafızların yanına KONTROL testleri var — "her zaman nötrle"
#   ya da "hiç model seçme" davranışları da muhafızları geçerdi.
# =========================================================
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from engines.backtest_engine import walk_forward_cv
from engines.model_engine import (_wf_beceri, _wf_beceri_std, _wf_ortalama,
                                  model_beceri_anlamli_mi, guven_notrle)


def _meta(beceri, std, ortalama=0.55):
    return {"wf": {"ortalama": ortalama, "std": 0.03,
                   "beceri_ort": beceri, "beceri_std": std}}


# ─────────────────────────────────────────────
# 1. WF BECERİ RAPORLAMASI
# ─────────────────────────────────────────────
def test_wf_beceri_alanlarini_dondurur():
    """walk_forward_cv beceri/taban alanlarını üretmeli."""
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(400, 4)))
    y = pd.Series(rng.integers(0, 2, 400))
    wf = walk_forward_cv(X, y, RandomForestClassifier,
                         {"n_estimators": 10, "random_state": 0}, n_splits=4)
    for k in ("beceri_ort", "beceri_std", "taban_ort"):
        assert k in wf, f"walk_forward_cv '{k}' döndürmüyor — seçim beceriye bakamaz"
    assert 0.45 <= wf["taban_ort"] <= 0.75, (
        f"taban_ort={wf['taban_ort']} — çoğunluk sınıfı oranı olmalı (>=0.5)")


def test_beceri_accuracy_eksi_taban_esittir():
    """beceri_ort, ortalama − taban_ort ile TUTARLI olmalı.

    İki değer bağımsız hesaplanıyor; tutarsızlık bir tanesinin yanlış
    katmanlardan toplandığını gösterir.
    """
    rng = np.random.default_rng(1)
    X = pd.DataFrame(rng.normal(size=(400, 4)))
    y = pd.Series(rng.integers(0, 2, 400))
    wf = walk_forward_cv(X, y, RandomForestClassifier,
                         {"n_estimators": 10, "random_state": 0}, n_splits=4)
    bek = wf["ortalama"] - wf["taban_ort"]
    assert abs(wf["beceri_ort"] - bek) < 0.005, (
        f"beceri_ort={wf['beceri_ort']} ama ortalama−taban={bek:.4f}")


def test_dengesiz_sinifta_yuksek_accuracy_BECERI_DEGILDIR():
    """%80 tek sınıflı seride 0.80 accuracy → beceri ≈ 0.

    Bu, düzeltmenin ta kendisi: ham accuracy 0.80 görünür ve eski seçim
    onu 'çok iyi' sayardı; beceri ise sıfır civarındadır.
    """
    rng = np.random.default_rng(2)
    X = pd.DataFrame(rng.normal(size=(500, 4)))
    y = pd.Series((rng.random(500) < 0.8).astype(int))   # %80 sınıf 1
    wf = walk_forward_cv(X, y, RandomForestClassifier,
                         {"n_estimators": 20, "random_state": 0}, n_splits=4)
    assert wf["ortalama"] > 0.6, (
        f"kurulum hatalı: dengesiz seride ham accuracy düşük çıktı "
        f"({wf['ortalama']})")
    assert wf["beceri_ort"] < 0.10, (
        f"Rastgele feature'larla beceri {wf['beceri_ort']:+.3f} çıktı — "
        f"beceri hesabı sınıf dengesizliğini temizlemiyor")


# ─────────────────────────────────────────────
# 2. NÖTRLEME KARARI
# ─────────────────────────────────────────────
def test_beceri_belirsizlikten_kucukse_anlamli_degil():
    """beceri <= std → anlamlı DEĞİL (üretimdeki tipik durum)."""
    assert not model_beceri_anlamli_mi(_meta(0.02, 0.06))
    assert not model_beceri_anlamli_mi(_meta(0.05, 0.05))


def test_negatif_beceri_asla_anlamli_degil():
    """Taban çizgisinin ALTINDAKİ model anlamlı sayılmamalı.

    std çok küçükse `beceri > std` koşulu negatif beceriyi de geçirebilirdi
    (−0.02 > −0.03 değil ama std hep pozitif; yine de açıkça kilitliyoruz).
    """
    assert not model_beceri_anlamli_mi(_meta(-0.05, 0.01))
    assert not model_beceri_anlamli_mi(_meta(-0.001, 0.0))


def test_eski_format_wf_anlamli_sayilmaz():
    """beceri alanı OLMAYAN eski WF dosyası → beceri yok kabul edilir.

    Sessizce ham accuracy'ye düşmek düzeltmeyi etkisiz kılardı: eski
    dosyalar aylarca diskte kalabilir.
    """
    eski = {"wf": {"ortalama": 0.58, "std": 0.03}}     # beceri alanı YOK
    assert _wf_beceri(eski) == 0.0
    assert not model_beceri_anlamli_mi(eski)


def test_bozuk_meta_cokmez_ve_anlamli_degil():
    """None/bozuk meta → fail-closed (anlamlı değil), istisna atmadan."""
    for bozuk in (None, {}, {"wf": None}, {"wf": "abc"}, {"wf": {"beceri_ort": "x"}}):
        assert not model_beceri_anlamli_mi(bozuk), f"bozuk meta geçti: {bozuk}"


# ─────────────────────────────────────────────
# 3. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_gercek_beceri_ANLAMLI_sayilir():
    """AŞIRI DÜZELTME KONTROLÜ: 'her zaman nötrle' olmamalı.

    Beceri belirsizliğinden açıkça büyükse model KULLANILMALI — aksi
    halde ileride gerçek bir edge bulunsa da sistem onu görmezden gelir.
    """
    assert model_beceri_anlamli_mi(_meta(0.08, 0.02)), (
        "beceri 0.08 ± 0.02 anlamlı sayılmadı — düzeltme aşırıya kaçmış, "
        "gerçek bir edge bulunsa da kullanılmaz")
    assert model_beceri_anlamli_mi(_meta(0.15, 0.05))


def test_kontrol_wf_ham_ortalama_hala_raporlaniyor():
    """Ham accuracy KAYBOLMAMALI — registry ve loglar onu kullanıyor."""
    m = _meta(0.03, 0.05, ortalama=0.561)
    assert _wf_ortalama(m) == 0.561, (
        "_wf_ortalama ham accuracy'yi döndürmüyor — raporlama bozulur")


def test_kontrol_beceri_std_okunuyor():
    """Belirsizlik gerçekten meta'dan okunmalı (sabitlenmemeli)."""
    assert _wf_beceri_std(_meta(0.03, 0.077)) == 0.077
    assert _wf_beceri_std(_meta(0.03, 0.0)) == 0.0


def test_notrleme_beceri_yokken_50_dondurur():
    """DAVRANIŞSAL: beceri anlamlı değilse güven 50.0 olmalı."""
    assert guven_notrle(85.0, _meta(0.02, 0.06)) == 50.0
    assert guven_notrle(12.0, _meta(0.02, 0.06)) == 50.0
    assert guven_notrle(85.0, None) == 50.0


class _PatlayanMeta(dict):
    """Erişildiğinde istisna atan meta — fail-closed yolunu tetikler.

    ⚠️ BOŞ OLMAMALI. İlk sürüm boş bir dict alt sınıfıydı; kod
    `(meta or {}).get(...)` yazdığı için boş sözlük FALSY olup düz `{}`
    ile değişiyordu ve `get` hiç çağrılmıyordu. Test istisna yolunu
    tetiklediğini SANIYORDU — mutasyon (fail-open) yakalanmadı.
    Bu yüzden içi dolu: nesne truthy olmalı ki kod ona dokunsun.
    """
    def __init__(self):
        super().__init__({"wf": {}})     # truthy olsun

    def get(self, *a, **k):
        raise RuntimeError("meta okunamadi (simulasyon)")


def test_notrleme_ISTISNA_halinde_de_notr():
    """FAIL-CLOSED: beceri kontrolü ÇÖKERSE de güven nötrlenmeli.

    ⚠️ Bu test sonradan eklendi: mutasyon testi, `except` dalını
    fail-open'a çeviren değişikliğin YAKALANMADIĞINI gösterdi — çünkü
    mevcut testlerin hiçbiri istisna yolunu tetiklemiyordu (None bile
    normal daldan geçiyor). §5.1: hata hâlinde modele güvenmek, tam da
    düzeltmenin engellemek istediği şey.
    """
    assert guven_notrle(85.0, _PatlayanMeta()) == 50.0, (
        "Beceri kontrolü çöktüğünde güven nötrlenmedi — fail-open. "
        "Model bozukken bile ai_score'u etkilemeye devam eder.")


def test_notrleme_gercek_beceriyi_BOZMAZ():
    """AŞIRI DÜZELTME KONTROLÜ: beceri anlamlıysa güven DEĞİŞMEMELİ."""
    assert guven_notrle(85.0, _meta(0.08, 0.02)) == 85.0
    assert guven_notrle(31.5, _meta(0.12, 0.03)) == 31.5


def test_kontrol_notrleme_main_de_BAGLI():
    """AST: main.py `yukselis_guveni`'yi GERÇEKTEN guven_notrle'den alıyor mu?

    ⚠️ Bu testin ÖNCEKİ hâli kaynakta string arıyordu ve nötrlemeyi
    kaldıran mutasyonu YAKALAYAMADI (testler 12/12 yeşil kaldı). Bu,
    K-29'daki "yardımcıyı doğrulayıp tüketiciyi doğrulamayan test"
    tuzağının birebir tekrarıydı — bu yüzden AST'ye çevrildi:
    `yukselis_guveni = guven_notrle(...)` ATAMASINI arıyoruz.
    """
    import ast
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "main.py"), encoding="utf-8") as fh:
        agac = ast.parse(fh.read())

    bulundu = False
    for d in ast.walk(agac):
        if not isinstance(d, ast.Assign):
            continue
        hedefler = [t.id for t in d.targets if isinstance(t, ast.Name)]
        if "yukselis_guveni" not in hedefler:
            continue
        if (isinstance(d.value, ast.Call)
                and isinstance(d.value.func, ast.Name)
                and d.value.func.id == "guven_notrle"):
            bulundu = True
            break
    assert bulundu, (
        "main.py'da `yukselis_guveni = guven_notrle(...)` ataması YOK — "
        "nötrleme fonksiyonu yazıldı ama TÜKETİCİYE bağlanmadı. Model "
        "becerisi olmasa da güveni ai_score'a girmeye devam eder.")


def test_kontrol_secim_beceriye_bagli():
    """Kaynak düzeyi: nihai seçim `_wf_beceri` kullanmalı."""
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "engines", "model_engine.py"),
              encoding="utf-8") as fh:
        kaynak = fh.read()
    assert "max(adaylar,key=lambda x:_wf_beceri(x[2]))" in kaynak, (
        "Nihai seçim `_wf_beceri` ile yapılmıyor — ham accuracy'ye "
        "bakmak sınıf dengesizliğini ödüllendirir")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA MODEL BECERİSİ — {len(testler)} test")
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
