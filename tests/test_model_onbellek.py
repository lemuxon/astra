# =========================================================
# ASTRA v58 — MODEL ÖNBELLEĞİ / ZORLA YENİDEN EĞİTİM (K-55)
# Çalıştırma: python tests/test_model_onbellek.py
#
# NE KORUYOR:
#   `en_iyi_model_yukle_veya_egit` TAZE bir modeli bile
#   `acc < MIN_USEFUL_ACC` (0.52) ise atıp YENİDEN EĞİTİYORDU. Yeni
#   model de gürültü olduğu için genelde yine eşiği geçemiyor →
#   HER ÇAĞRIDA yeniden eğitim.
#
#   ÖLÇÜM (2026-09-06):
#     • Son 2 saatte **525** `[SKIP] … → yeniden eğit`
#     • `/btc` komutu **75.2 sn** (o sürede 11 SKIP, 11 model kaydı,
#       8 Optuna koşusu, 4 stacking, 1 TFT)
#     • `/scan` 180 sn'de bitmiyordu
#
#   NEDEN KALDIRMAK GÜVENLİ — davranış DEĞİŞMİYOR:
#     K-37 sonrası **634 model seçiminin 0'ında** beceri anlamlı çıktı
#     (1284 nötrleme). Model katkısı her durumda 50.0 (nötr) olduğundan
#     HANGİ modelin seçildiği sinyali ETKİLEMİYOR. Eşik koruma
#     sağlamıyordu, yalnızca maliyet üretiyordu.
#
#     Gerçek koruma K-37'de: beceri belirsizlikten büyük değilse güven
#     nötrleniyor. Seçim de WF BECERİSİYLE yapılıyor, ham accuracy ile
#     değil. `acc` hâlâ loglanıyor ama SEÇMİYOR ve ELEMİYOR.
#
#   DÜZELTMEDEN SONRA (ölçüldü):
#     /btc  75.2s → 13.1s   ·  /coin 66.8s → 6.8s  ·  /scan >180s → 79.2s
#
# §4.1: Muhafızın yanına KONTROL testi var — "hiç eğitme" davranışı da
#   yeniden-eğitim testini geçerdi.
# =========================================================
import sys, os, ast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fonksiyon(ad, dosya="engines/model_engine.py"):
    with open(os.path.join(KOK, dosya), encoding="utf-8") as fh:
        kaynak = fh.read()
    for d in ast.walk(ast.parse(kaynak)):
        if isinstance(d, (ast.FunctionDef, ast.AsyncFunctionDef)) and d.name == ad:
            return d, kaynak
    return None, kaynak


# ─────────────────────────────────────────────
# 1. MUHAFIZ
# ─────────────────────────────────────────────
def test_min_useful_acc_ADAYLIGI_ELEMIYOR():
    """AST: `acc >= MIN_USEFUL_ACC` bir `if` KOŞULU olarak KULLANILMAMALI.

    Karşılaştırma log satırında geçebilir (`acc < MIN_USEFUL_ACC` uyarısı),
    ama adaylığı ELEYEN bir dala bağlı olmamalı.
    """
    fn, _ = _fonksiyon("en_iyi_model_yukle_veya_egit")
    assert fn is not None, "en_iyi_model_yukle_veya_egit bulunamadı"
    eleyen = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.If):
            continue
        # Bu `if`in gövdesinde adaylar.append var mı?
        govde_ekliyor = any(
            isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
            and x.func.attr == "append"
            and isinstance(x.func.value, ast.Name) and x.func.value.id == "adaylar"
            for x in ast.walk(ast.Module(body=n.body, type_ignores=[])))
        if not govde_ekliyor:
            continue
        # Koşulda MIN_USEFUL_ACC geçiyor mu?
        kosul_isimler = {x.id for x in ast.walk(n.test) if isinstance(x, ast.Name)}
        if "MIN_USEFUL_ACC" in kosul_isimler:
            eleyen.append(n.lineno)
    assert not eleyen, (
        f"MIN_USEFUL_ACC hâlâ adaylığı ELİYOR (satır {eleyen}) — taze "
        f"model atılıp yeniden eğitilir, her çağrıda eğitim döngüsü "
        f"oluşur (ölçüm: 2 saatte 525 SKIP, /btc 75 sn)")


def test_SKIP_uyarisi_kalmadi():
    """`[SKIP]` log çağrısı ARTIK olmamalı — atma dalının imzasıydı.

    ⚠️ İlk sürüm `"yeniden eğit"` metnini arıyordu ve DOCSTRING'lerdeki
    açıklamalara takılıyordu (`ast.unparse` yorumları atar ama
    docstring'leri KORUR). Bugün üçüncü kez aynı tuzak — bu yüzden
    artık yapısal imzaya bakılıyor: `log.warning("[SKIP] …")` çağrısı.
    """
    fn, _ = _fonksiyon("en_iyi_model_yukle_veya_egit")
    skip_cagrilari = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        for arg in n.args:
            parcalar = []
            if isinstance(arg, ast.JoinedStr):
                parcalar = [v.value for v in arg.values
                            if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                parcalar = [arg.value]
            if any("[SKIP]" in p for p in parcalar):
                skip_cagrilari.append(n.lineno)
    assert not skip_cagrilari, (
        f"`[SKIP]` log çağrısı hâlâ var (satır {skip_cagrilari}) — taze "
        f"model eşiği geçemezse atılıp yeniden eğitiliyor demektir")


def test_secim_hala_WF_becerisiyle():
    """K-55, K-37'yi BOZMAMALI: seçim hâlâ beceriye bakmalı."""
    fn, _ = _fonksiyon("en_iyi_model_yukle_veya_egit")
    kaynak = ast.unparse(fn)
    assert "_wf_beceri" in kaynak, (
        "Seçim `_wf_beceri` kullanmıyor — K-37 geri alınmış olabilir, "
        "ham accuracy sınıf dengesizliğini ödüllendirir")


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_egitim_hala_yapiliyor():
    """AŞIRI DÜZELTME KONTROLÜ: "hiç eğitme" olmamalı.

    Model yoksa ya da bayatsa eğitim ÇAĞRILMALI; aksi halde sistem
    hiç model üretmez.
    """
    fn, _ = _fonksiyon("en_iyi_model_yukle_veya_egit")
    kaynak = ast.unparse(fn)
    assert "egitim_fn" in kaynak, (
        "Eğitim çağrısı kaldırılmış — model hiç üretilmez")
    assert "model_yasi" in kaynak, (
        "Model yaşı kontrolü kaldırılmış — bayat model hiç yenilenmez")


def test_kontrol_notrleme_hala_yerinde():
    """K-55'in güvenliği K-37'ye DAYANIYOR — o hâlâ bağlı olmalı.

    Eşiği kaldırmak, ancak beceri yoksa güvenin nötrlenmesi sayesinde
    güvenli. Nötrleme kalkarsa K-55 gerekçesiz kalır.
    """
    with open(os.path.join(KOK, "main.py"), encoding="utf-8") as fh:
        agac = ast.parse(fh.read())
    bulundu = False
    for d in ast.walk(agac):
        if (isinstance(d, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "yukselis_guveni"
                        for t in d.targets)
                and isinstance(d.value, ast.Call)
                and isinstance(d.value.func, ast.Name)
                and d.value.func.id == "guven_notrle"):
            bulundu = True
    assert bulundu, (
        "`yukselis_guveni = guven_notrle(...)` YOK — K-37 nötrlemesi "
        "kaldırılmış. K-55 (eşiksiz adaylık) yalnızca nötrleme varken "
        "güvenli; ikisi birlikte anlamlı.")


def test_kontrol_min_useful_acc_hala_tanimli():
    """Sabit tamamen silinmemeli — log/rapor için kullanılıyor."""
    from config import MIN_USEFUL_ACC
    assert 0.0 < MIN_USEFUL_ACC < 1.0


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA MODEL ÖNBELLEĞİ — {len(testler)} test")
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
