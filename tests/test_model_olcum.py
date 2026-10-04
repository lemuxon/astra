# =========================================================
# ASTRA v58 — MODEL ÖLÇÜMÜ TESTLERİ (K-17 / K-18 / K-19 / K-20 / K-21)
# Çalıştırma: python tests/test_model_olcum.py
#
# NE KORUYOR — projenin en pahalı yanılgısı:
#   Model "accuracy 0.99" raporluyordu; gerçek sinyal karşılığı yazı
#   turaydı. Sebep model ya da feature'lar DEĞİL, ÖLÇÜMÜN KENDİSİYDİ.
#
#   ZİNCİR:
#   1) `_self_train_tetikle(sembol, 0.0)` drift tespitinde çağrılıyordu
#      (ortada kapanmış işlem yokken). İçerideki
#      `gercek_sonuc = 1 if pnl_pct > 0 else 0` kuralı her çağrıda
#      UYDURMA bir `target=0` kaydı yazıyordu.
#      ÖLÇÜM: 954 feedback kaydının 917'si (%96) böyleydi;
#      feedback_BTCUSDT.jsonl → target {0: 221, 1: 1}.
#   2) `feedback_veri_yukle` bu kayıtları verinin SONUNA ekliyordu.
#   3) Her eğitici `train_test_split(..., shuffle=False)` ile SON %20'yi
#      test yapıyordu → TEST SETİ TAMAMEN FEEDBACK ve TEK SINIFLI.
#
#   ÖLÇÜLEN SONUÇ (BTCUSDT, 14g/1h):
#       feedback YOK  → test_acc 0.516  (test'te target=1 oranı 0.484)
#       feedback VAR  → test_acc 0.963  (test'te target=1 oranı 0.000)
#   Dürüst 0.516, çoğunluk sınıfı taban çizgisiyle (0.518) aynı.
#   Bağımsız sinyal analizi de aynı yere varmıştı: excess getiri
#   +%0.003, p=0.93 (ANALIZ_KAYIP_NEDENI.md §3).
#
#   AYRICA (K-19): `rf_optimize(X_tr,y_tr,X_te,y_te)` Optuna'ya TEST
#   setindeki f1'i maksimize ettiriyordu; LGB'de `eval_set=[(X_te,y_te)]`
#   ile early stopping aynısını yapıyordu. Ölçülen şişme: +2.6 puan.
#
# §4.1: Her muhafızın yanına KONTROL testi — "feedback'i tamamen sil"
#   diyen bir düzeltme de muhafızları geçerdi ama öğrenmeyi öldürürdü.
# =========================================================
import sys, os, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# v57: ÜRETİM durum dosyalarına yazmayı engelle. Proje modülleri import
# EDİLMEDEN ÖNCE çağrılmalı — config.py yolları import anında okur.
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("BINANCE_API_SECRET", "")

import numpy as np
import pandas as pd

SEM = "OLCUMTEST"


def _piyasa_verisi(n=300, seed=7):
    """Dengeli etiketli sentetik piyasa verisi (target ~%50)."""
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.normal(0, 1, (n, 6)),
                     columns=[f"f{i}" for i in range(6)])
    y = pd.Series(rng.integers(0, 2, n), name="Target")
    return X, y


def _feedback_yaz(sembol, adet, target=0):
    """Tek sınıflı feedback kayıtları üret (gerçek vakanın kopyası)."""
    from config import MODEL_DIR
    os.makedirs(MODEL_DIR, exist_ok=True)
    yol = os.path.join(MODEL_DIR, f"feedback_{sembol}.jsonl")
    with open(yol, "w") as f:
        for i in range(adet):
            ozellik = {f"f{j}": float(i % 7) + j for j in range(6)}
            f.write(json.dumps({"features": ozellik, "target": target,
                                "pnl_pct": -1.0, "ts": "2026-09-03T00:00:00"}) + "\n")
    # feedback cache'i temizle (mtime aynı kalırsa eski veri okunur)
    from engines import model_engine as me
    me._fb_cache.pop(sembol, None)
    return yol


def _embargo():
    """Aktif hedefte train kuyruğundan kaç satır atılıyor?

    Üçlü bariyer etiketleri örtüştüğü için `egitim_test_bol` train'in
    son HEDEF_MAX_BAR satırını atar (K-23). Beklenen boyutlar sabit
    sayı yazılamaz — yapılandırmadan türetilmeli, yoksa hedef
    değiştiğinde bu testler alakasız sebeple kırmızıya döner.
    """
    from config import HEDEF_TIPI, HEDEF_MAX_BAR
    return HEDEF_MAX_BAR if HEDEF_TIPI == "ucgen_bariyer" else 0


def _feedback_sil(sembol):
    from config import MODEL_DIR
    yol = os.path.join(MODEL_DIR, f"feedback_{sembol}.jsonl")
    if os.path.exists(yol):
        os.remove(yol)
    from engines import model_engine as me
    me._fb_cache.pop(sembol, None)


# ─────────────────────────────────────────────
# 1. MUHAFIZ (K-18) — feedback TEST setine girmemeli
# ─────────────────────────────────────────────
def test_feedback_test_setine_girmez():
    """Gerçek vakanın kopyası: 220 tek sınıflı feedback kaydı."""
    from engines.model_engine import egitim_test_bol
    X, y = _piyasa_verisi()
    _feedback_yaz(SEM, 220, target=0)
    try:
        X_tr, X_te, y_tr, y_te = egitim_test_bol(X, y, SEM, 0.2)
        assert len(X_te) == 60, (
            f"Test seti {len(X_te)} satır — piyasa verisinin %20'si (60) "
            f"olmalıydı; feedback test setine sızmış")
        oran = y_te.mean()
        assert 0.2 < oran < 0.8, (
            f"Test setinde target=1 oranı {oran:.3f} — tek sınıfa çökmüş. "
            f"Feedback sızıntısı accuracy'yi sahte şekilde şişirir")
    finally:
        _feedback_sil(SEM)


def test_test_seti_zaman_sirasinin_SONU():
    """Test seti piyasa verisinin son %20'si olmalı (zaman sıralı)."""
    from engines.model_engine import egitim_test_bol
    X, y = _piyasa_verisi()
    _feedback_sil(SEM)
    X_tr, X_te, y_tr, y_te = egitim_test_bol(X, y, SEM, 0.2)
    assert list(X_te.index) == list(X.index[-60:]), \
        "Test seti zaman sıralı son dilim değil — geleceğe bakma riski"


# ─────────────────────────────────────────────
# 2. KONTROL — feedback'i tamamen atmak da YANLIŞ
# ─────────────────────────────────────────────
def test_feedback_TRAIN_setine_EKLENIR():
    """Kontrol testi (§4.1). Feedback eğitimde kullanılmaya devam etmeli.

    Bu test olmadan, `feedback_veri_yukle`'yi tamamen silen bir
    'düzeltme' de yukarıdaki muhafızları geçerdi — ama işlem
    sonuçlarından öğrenme yeteneği sessizce ölürdü.
    """
    from engines.model_engine import egitim_test_bol
    X, y = _piyasa_verisi()
    _feedback_yaz(SEM, 50, target=0)
    try:
        X_tr, X_te, y_tr, y_te = egitim_test_bol(X, y, SEM, 0.2)
        beklenen = 240 - _embargo() + 50
        assert len(X_tr) == beklenen, (
            f"Train {len(X_tr)} satır — {240-_embargo()} piyasa (embargo "
            f"{_embargo()}) + 50 feedback = {beklenen} olmalıydı; "
            f"feedback eğitime EKLENMİYOR")
    finally:
        _feedback_sil(SEM)


def test_feedback_yokken_calisir():
    """Kontrol: feedback dosyası olmayan sembolde bölme bozulmamalı."""
    from engines.model_engine import egitim_test_bol
    X, y = _piyasa_verisi()
    _feedback_sil(SEM)
    X_tr, X_te, y_tr, y_te = egitim_test_bol(X, y, SEM, 0.2)
    assert len(X_tr) == 240 - _embargo() and len(X_te) == 60, (
        f"feedback yokken bölme bozuldu: {len(X_tr)}/{len(X_te)} "
        f"(beklenen {240 - _embargo()}/60, embargo {_embargo()})")


# ─────────────────────────────────────────────
# 3. UÇTAN UCA — sahte accuracy geri gelmemeli
# ─────────────────────────────────────────────
def test_tek_sinifli_feedback_accuracyi_sismiyor():
    """Ölçülen hatanın birebir regresyon testi.

    Eskiden bu senaryoda test_acc 0.96'ya çıkıyordu. Artık test seti
    piyasa verisi olduğu için ~0.5 civarında kalmalı.
    """
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import accuracy_score
    from engines.model_engine import egitim_test_bol
    X, y = _piyasa_verisi()
    _feedback_yaz(SEM, 220, target=0)
    try:
        X_tr, X_te, y_tr, y_te = egitim_test_bol(X, y, SEM, 0.2)
        m = GradientBoostingClassifier(n_estimators=50, max_depth=3,
                                       random_state=42)
        m.fit(X_tr, y_tr)
        acc = accuracy_score(y_te, m.predict(X_te))
        assert acc < 0.75, (
            f"Rastgele veride test_acc={acc:.3f} — tek sınıflı feedback "
            f"test setine sızmış olabilir (sahte accuracy geri geldi)")
    finally:
        _feedback_sil(SEM)


# ─────────────────────────────────────────────
# 4. YAPISAL (K-19) — parametre seçimi TEST'e bakmamalı
# ─────────────────────────────────────────────
def _kod(dosya):
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       dosya)
    with open(yol, encoding="utf-8") as fh:
        return "\n".join(l for l in fh.read().splitlines()
                         if not l.strip().startswith("#"))


def test_optuna_test_setini_gormez():
    """`rf_optimize` çağrısı X_te/y_te almamalı."""
    kod = _kod(os.path.join("engines", "model_engine.py"))
    assert "rf_optimize(X_tr,y_tr,X_te,y_te)" not in kod.replace(" ", ""), (
        "rf_optimize hâlâ TEST setiyle çağrılıyor — Optuna test skorunu "
        "maksimize edip aynı skoru 'dürüst' diye raporlar")


def test_lgb_early_stopping_test_setini_gormez():
    """LightGBM early stopping eval_set'i TEST olmamalı."""
    kod = _kod(os.path.join("engines", "model_engine.py")).replace(" ", "")
    assert "eval_set=[(X_te,y_te)]" not in kod, (
        "LGB early stopping TEST setine bakıyor — model test skorunu "
        "maksimize eden iterasyonda duruyor")


# ─────────────────────────────────────────────
# 5. YAPISAL (K-17) — drift retrain etiket uydurmamalı
# ─────────────────────────────────────────────
def test_drift_retrain_feedback_yazmaz():
    """`gercek_islem` bayrağı olmadan feedback yazılmamalı."""
    kod = _kod("main.py")
    assert "gercek_islem" in kod, (
        "_self_train_tetikle'da `gercek_islem` ayrımı yok — drift retrain "
        "yine uydurma target=0 kaydı yazar")
    i = kod.find("def _self_train_tetikle")
    assert i > 0, "fonksiyon bulunamadı — test hedefi kaymış"
    govde = kod[i:i + 3000]
    j = govde.find("feedback_ekle(")
    assert j > 0, "feedback_ekle çağrısı bulunamadı"
    assert "if not gercek_islem" in govde[:j], (
        "feedback_ekle çağrısı `gercek_islem` kontrolüne bağlı değil")


def test_gercek_kapanis_feedback_YAZAR():
    """Kontrol testi (§4.1): gerçek işlem kapanışı feedback yazmalı.

    Aksi halde "hiç feedback yazma" da muhafızı geçerdi.
    """
    kod = _kod("main.py").replace(" ", "")
    assert "gercek_islem=True" in kod, (
        "Hiçbir çağrı `gercek_islem=True` geçmiyor — self-training "
        "tamamen ölmüş olur")


# ─────────────────────────────────────────────
# 6. YAPISAL (K-20) — seçim walk-forward ile
# ─────────────────────────────────────────────
def test_model_secimi_walk_forward_kullanir():
    """Seçim tek hold-out `acc` yerine WF'ye dayanmalı."""
    kod = _kod(os.path.join("engines", "model_engine.py"))
    i = kod.find("en_iyi=max(adaylar")
    assert i > 0, "model seçim satırı bulunamadı — test hedefi kaymış"
    assert "_wf_ortalama" in kod[i:i + 200], (
        "Model seçimi hâlâ `max(adaylar, key=acc)` — tek hold-out "
        "bölünmesi, varyansı yüksek ve K-18 öncesinde sahteydi")


# ─────────────────────────────────────────────
# 6.1 K-27 — WF önbellekten yüklenen modelde de olmalı
# ─────────────────────────────────────────────
def test_wf_modelle_birlikte_saklanir():
    """Yüklenen modelin WF'si kayıp olmamalı.

    K-20 seçimi WF'ye bağladı ama WF yalnızca EĞİTİM anında
    hesaplanıyordu; önbellekten yüklenen modelin meta'sı boş gelince
    WF=0 oluyor ve seçim sessizce `test_acc`e düşüyordu. Modeller 1
    saat taze kaldığı için bu çağrıların ÇOĞUNLUĞUYDU — üretim
    logunda 229 kez "hiçbir adayda WF yok" uyarısı görüldü.
    """
    from engines.model_engine import wf_kaydet, wf_yukle
    wf = {"splits": 8, "ortalama": 0.5432, "std": 0.04,
          "min": 0.5, "max": 0.6, "auc_ort": 0, "detay": []}
    wf_kaydet("BIRIM_TEST", wf)
    geri = wf_yukle("BIRIM_TEST")
    assert abs(geri.get("ortalama", 0) - 0.5432) < 1e-9, (
        f"WF kaydedilip okunamadı: {geri}")


def test_wf_yoksa_bos_doner_cokmez():
    """Kontrol: hiç WF kaydı olmayan model çökmemeli."""
    from engines.model_engine import wf_yukle
    bos = wf_yukle("HIC_OLMAYAN_MODEL_XYZ")
    assert bos.get("ortalama", None) == 0.0,         f"WF yokken 0 dönmeliydi: {bos}"


def test_yuklenen_model_yolunda_wf_okunuyor():
    """Önbellekten yüklenen model WF'siyle birlikte aday olmalı (K-27).

    ⚠️ ÇAPA DEĞİŞTİ (v58 K-55): bu test eskiden
    `kod.find("if acc >= MIN_USEFUL_ACC:")` ile METİN arıyordu. K-55 o
    satırı kaldırınca test "hedef kaymış" diye KIRILDI — oysa korumak
    istediği davranış (önbellek yolunun WF taşıması) hiç bozulmamıştı.

    Metin çapası, ilgisiz bir düzeltmede kopar ve yanlış alarm verir.
    Artık AST: `adaylar.append(...)` çağrılarından en az birinin meta
    sözlüğü `wf_yukle(...)` İÇERMELİ.
    """
    import ast
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "engines", "model_engine.py")
    with open(yol, encoding="utf-8") as fh:
        agac = ast.parse(fh.read())

    fn = next((d for d in ast.walk(agac)
               if isinstance(d, ast.FunctionDef)
               and d.name == "en_iyi_model_yukle_veya_egit"), None)
    assert fn is not None, "en_iyi_model_yukle_veya_egit bulunamadı"

    toplam = wf_li = 0
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "append"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "adaylar"):
            continue
        toplam += 1
        adlar = {x.func.id for x in ast.walk(n)
                 if isinstance(x, ast.Call) and isinstance(x.func, ast.Name)}
        if "wf_yukle" in adlar:
            wf_li += 1

    assert toplam > 0, "adaylar.append hiç bulunamadı — test hedefi kaymış"
    assert wf_li > 0, (
        f"{toplam} `adaylar.append` var ama HİÇBİRİ `wf_yukle` çağırmıyor "
        f"— önbellekten yüklenen model WF'siz ekleniyor, seçim sessizce "
        f"test_acc'ye düşer (K-27)")


# ─────────────────────────────────────────────
# 7. YAPISAL (K-21) — model dizini izole edilebilir
# ─────────────────────────────────────────────
def test_model_dizini_izole():
    """MODEL_DIR testlerde geçici dizine yönlenmeli.

    Sabit koduyken test paketi ÜRETİM saved_models/ dizinine .pkl ve
    feedback_*.jsonl yazıyordu. Feedback dosyaları modelin EĞİTİM
    VERİSİDİR — kirlenmeleri doğrudan sinyali etkiler (§4.6).
    """
    from config import MODEL_DIR
    gecici = os.environ.get("ASTRA_TEST_DIZINI", "")
    assert gecici, "izolasyon dizini kurulmamış"
    assert os.path.abspath(MODEL_DIR).startswith(os.path.abspath(gecici)), (
        f"MODEL_DIR={MODEL_DIR} geçici dizinin dışında — testler üretim "
        f"model ve feedback dosyalarına yazıyor")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA MODEL ÖLÇÜMÜ — {len(testler)} test")
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
