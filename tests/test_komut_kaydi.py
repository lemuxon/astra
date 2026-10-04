# =========================================================
# ASTRA v58 — TELEGRAM KOMUT KAYIT BÜTÜNLÜĞÜ (K-54)
# Çalıştırma: python tests/test_komut_kaydi.py
#
# NE KORUYOR:
#   Bir komutun ÇALIŞMASI için ÜÇ şeyin birden doğru olması gerekir:
#     1. `cmd_x` fonksiyonu TANIMLI olmalı
#     2. `komutlar` listesinde KAYITLI olmalı (CommandHandler'a bağlanır)
#     3. `/yardim` çıktısında İLAN edilmeli (kullanıcı bilsin)
#
#   Bu üçü AYRI yerlerde tutuluyor ve elle senkron tutuluyor. Ayrışma
#   SESSİZDİR:
#     • İlan edildi ama kayıtlı değil → kullanıcı yazar, HİÇBİR ŞEY olmaz
#     • Kayıtlı ama fonksiyon yok      → çalışma anında NameError
#     • Tanımlı ama kayıtlı değil      → ölü kod
#
#   2026-09-06 denetiminde üçü de temizdi (36 fonksiyon, 38 kayıt —
#   fark `/help` ve `/start` takma adları). Bu test o durumu KİLİTLER.
#
#   ⚠️ Fonksiyonu doğru yazıp KAYIT ETMEMEK bu kod tabanında tekrar eden
#   bir sınıf: K-29 (MTF hiyerarşisi tüketiciye bağlanmamıştı), K-37
#   (nötrleme main.py'a bağlanmamıştı). Aynı hata komut katmanında da
#   olabilir ve orada belirtisi "komut hiç cevap vermiyor" olur.
#
# §4.1: Muhafızın yanına KONTROL testi var.
# =========================================================
import sys, os, ast, re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAKMA_ADLAR = {"help", "start", "yardim"}      # /yardim'ın kendisi + eşanlamlıları
# Yardım metninde komut GİBİ görünen ama komut OLMAYAN parçalar.
# "gecikme/kayma raporu" ifadesindeki `/kayma` bir komut değil.
YOK_SAYILAN = {"kayma"}


def _analiz():
    with open(os.path.join(KOK, "main.py"), encoding="utf-8") as fh:
        kaynak = fh.read()
    agac = ast.parse(kaynak)

    kayitli = {}
    for n in ast.walk(agac):
        if not isinstance(n, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "komutlar" for t in n.targets):
            continue
        if not isinstance(n.value, ast.List):
            continue
        for el in n.value.elts:
            if isinstance(el, ast.Tuple) and len(el.elts) == 2:
                ad, fn = el.elts
                if isinstance(ad, ast.Constant) and isinstance(fn, ast.Name):
                    kayitli[ad.value] = fn.id

    tanimli = {d.name for d in ast.walk(agac)
               if isinstance(d, (ast.AsyncFunctionDef, ast.FunctionDef))
               and d.name.startswith("cmd_")}

    # ⚠️ İLAN listesi KAYNAK METNİNDEN değil, STRING DEĞERLERİNDEN
    # çıkarılır. İlk sürüm `ast.get_source_segment` üzerinde regex
    # yapıyordu ve satır başındaki komutları KAÇIRIYORDU: kaynakta
    # `/btc`'nin önünde tırnak (`f"/btc · ...`) var, satır başı değil.
    # Sonuç: 38 komuttan yalnızca 22'si "ilan edilmiş" sayılıyordu ve
    # `test_ilan_edilen_her_komut_kayitli` sessizce zayıftı — mutasyon
    # testi bunu yakaladı (/saglik kaydı silindiğinde tepki vermedi).
    # Kullanıcının GÖRDÜĞÜ metin string değerlerinin kendisidir.
    ilan = set()
    for d in ast.walk(agac):
        if not (isinstance(d, (ast.AsyncFunctionDef, ast.FunctionDef))
                and d.name == "cmd_yardim"):
            continue
        metinler = []
        for n in ast.walk(d):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                metinler.append(n.value)
            elif isinstance(n, ast.JoinedStr):
                for p_ in n.values:
                    if isinstance(p_, ast.Constant) and isinstance(p_.value, str):
                        metinler.append(p_.value)
        for m in metinler:
            ilan |= set(re.findall(r"/([a-z_]{2,})", m))
    return kayitli, tanimli, ilan


# ─────────────────────────────────────────────
# 1. MUHAFIZ
# ─────────────────────────────────────────────
def test_kayitli_her_komutun_fonksiyonu_var():
    """Kayıtlı ama tanımsız → import/çalışma anında NameError."""
    kayitli, tanimli, _ = _analiz()
    eksik = sorted({a: f for a, f in kayitli.items() if f not in tanimli}.items())
    assert not eksik, (
        f"Kayıtlı ama FONKSİYONU OLMAYAN komut(lar): {eksik} — "
        f"bot başlarken NameError atar")


def test_tanimli_her_komut_kayitli():
    """Tanımlı ama kayıtsız → ölü kod; kullanıcı komutu kullanamaz."""
    kayitli, tanimli, _ = _analiz()
    kayitli_fn = set(kayitli.values())
    olu = sorted(tanimli - kayitli_fn)
    assert not olu, (
        f"Tanımlı ama HİÇ KAYITLI OLMAYAN komut(lar): {olu} — "
        f"kod var ama kullanıcı erişemiyor (K-29/K-37 sınıfı: "
        f"yardımcı yazılıp tüketiciye bağlanmamış)")


def test_ilan_edilen_her_komut_kayitli():
    """/yardim'da duyurulan komut ÇALIŞMALI.

    En kötü hata sınıfı bu: kullanıcı yardımda görür, yazar, HİÇBİR
    ŞEY olmaz ve neden olmadığını anlayamaz.
    """
    kayitli, _, ilan = _analiz()
    eksik = sorted(ilan - set(kayitli) - TAKMA_ADLAR - YOK_SAYILAN)
    assert not eksik, (
        f"/yardim'da İLAN EDİLEN ama KAYITLI OLMAYAN komut(lar): {eksik} — "
        f"kullanıcı yazar, hiçbir şey olmaz")


def test_kayitli_komutlar_es_zamanli_fonksiyon():
    """Handler'lar async olmalı — senkron fonksiyon PTB'de patlar."""
    import inspect, main
    kayitli, _, _ = _analiz()
    senkron = []
    for ad, fn_adi in kayitli.items():
        fn = getattr(main, fn_adi, None)
        if fn is not None and not inspect.iscoroutinefunction(fn):
            senkron.append(f"/{ad}→{fn_adi}")
    assert not senkron, (
        f"async OLMAYAN handler(lar): {senkron} — "
        f"python-telegram-bot coroutine bekler")


def test_kayitli_isimler_gecerli():
    """Telegram komut adları: küçük harf, rakam, alt çizgi; 1-32 karakter."""
    kayitli, _, _ = _analiz()
    kotu = [a for a in kayitli if not re.fullmatch(r"[a-z0-9_]{1,32}", a)]
    assert not kotu, (
        f"Telegram'ın kabul etmeyeceği komut adı: {kotu}")


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_analiz_gercekten_veri_buluyor():
    """AŞIRI DÜZELTME KONTROLÜ: ayrıştırıcı boş dönerse tüm testler
    anlamsız biçimde yeşil olur (boş küme farkı hep boştur)."""
    kayitli, tanimli, ilan = _analiz()
    assert len(kayitli) >= 30, f"Yalnızca {len(kayitli)} kayıtlı komut bulundu"
    assert len(tanimli) >= 30, f"Yalnızca {len(tanimli)} cmd_* fonksiyonu bulundu"
    assert len(ilan) >= 30, (
        f"/yardim'da yalnızca {len(ilan)} komut bulundu — ayrıştırıcı "
        f"eksik yakalıyor (ilk sürüm 38'de 22 buluyordu ve testi "
        f"sessizce zayıflatıyordu)")


def test_kontrol_bilinen_komutlar_kayitli():
    """Somut çapa: en çok kullanılan komutlar gerçekten kayıtlı olmalı."""
    kayitli, _, _ = _analiz()
    for ad in ("btc", "coin", "paper", "bakiye", "risk", "saglik", "yardim"):
        assert ad in kayitli, f"/{ad} kayıtlı değil"


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA KOMUT KAYIT BÜTÜNLÜĞÜ — {len(testler)} test")
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
