# =========================================================
# ASTRA v57 — TEST İZOLASYONU (önyükleyici)
#
# NEDEN VAR:
#   v56'ya kadar test paketi ÜRETİM durum dosyalarına yazıyordu.
#   Ölçülen kirlilik (koşu başına):
#       data/astra.db::trades           +11
#       data/astra.db::performance       +2
#       data/journal.db::journal        +12   (biri mod='LIVE' etiketli!)
#       data/model_registry.db          +2
#       data/ab_test.json               üzerine yazılıyor
#
#   Bu, projedeki EN TEHLİKELİ kirlilik türüydü: canlıya geçiş kararı
#   (CANLI_GECIS_PROTOKOLU.md Aşama 1) "100 kapanmış paper işlem" sayacına
#   dayanıyor. Sayaç test artefaktıyla şişiyordu — 2026-08-20'de sayaç 33
#   gösteriyordu, GERÇEK paper işlem sayısı 0'dı. Ayrıca PaperTrader restart
#   bakiyesini DB'den türettiği için sahte PnL canlı bakiyeye de sızıyordu.
#
# KULLANIM — her test dosyasının EN BAŞINDA, proje modülleri import
# EDİLMEDEN önce:
#       import izolasyon_yukle   # noqa  (bkz. aşağıdaki not)
#   veya doğrudan:
#       sys.path.insert(0, <kök>)
#       from tests.izolasyon import izole_et; izole_et()
#
# KRİTİK SIRA: config.py yolları import ANINDA os.getenv ile okur
# (config.py:140 DB_PATH, :230 JOURNAL_DB_PATH). Bu yüzden izole_et()
# config'i import eden HERHANGİ bir şeyden önce çağrılmalıdır. Sonra
# çağrılırsa sessizce ETKİSİZ kalır — bu yüzden geç çağrıyı yakalayıp
# uyarı basıyoruz.
# =========================================================
import atexit
import os
import shutil
import sys
import tempfile

# ── K-107 (2026-10-06): TEST ÇIKTISININ KODLAMASI ────────────────────
# K-105 `testleri_calistir.py`'yi düzeltti ama TEST DOSYALARININ KENDİ
# raporlayıcıları aynı kusuru taşıyordu. Çıktı yönlendirildiğinde Python
# Windows'ta locale kodlamasını kullanır (Türkçe: cp1254) ve
# `[HATA] ... → mesaj` satırındaki "→" yazılamaz:
#
#     python tests/test_x.py > sonuc.log
#     UnicodeEncodeError: 'charmap' codec can't encode character '→'
#
# ⚠️ İRONİ: bu yalnızca bir test BAŞARISIZ olunca tetiklenir — yani
# tam olarak çıktıya ihtiyaç duyduğun anda rapor yerine traceback alırsın.
# Mutasyon testi sırasında bu şekilde yakalandı (K-106'nın guard'ı doğru
# çalıştı ama hata mesajı basılamadı).
#
# CONTRIBUTING.md testleri doğrudan çalıştırmayı söylüyor
# (`python tests/test_x.py`), bu yüzden çalıştırıcının UTF-8 zorlaması
# o yolda devreye girmiyor. Burada düzeltiliyor çünkü bu modülü her test
# dosyası (53/54) proje modülleri import edilmeden ÖNCE yüklüyor.
for _akis in (sys.stdout, sys.stderr):
    try:
        _akis.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass   # eski Python / değiştirilmiş stdout — en kötüsü eski davranış

# Üretim yolları — koruma altındaki dosyalar.
URETIM_YOLLARI = (
    "data/astra.db",
    "data/journal.db",
    "data/model_registry.db",
    "data/ab_test.json",
    "data/position_state.json",
    "logs/astra.log",              # v57: teşhis kaydı da korunur
    "logs/order_engine.jsonl",
)

_izole_dizin = None


def izole_et() -> str:
    """Tüm kalıcı durum yollarını geçici bir dizine yönlendir.

    Idempotent: birden çok kez çağrılabilir, ilk çağrı geçerlidir.
    Süreç sonunda geçici dizin silinir.

    Returns:
        Kullanılan geçici dizin yolu.
    """
    global _izole_dizin
    if _izole_dizin is not None:
        return _izole_dizin

    # Çalıştırıcı (testleri_calistir.py) zaten bir dizin verdiyse onu kullan.
    onceden = os.environ.get("ASTRA_TEST_DIZINI")
    if onceden:
        _izole_dizin = onceden
        os.makedirs(_izole_dizin, exist_ok=True)
    else:
        _izole_dizin = tempfile.mkdtemp(prefix="astra_test_")
        atexit.register(shutil.rmtree, _izole_dizin, ignore_errors=True)

    d = _izole_dizin
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    os.makedirs(os.path.join(d, "saved_models", "versions"), exist_ok=True)
    os.makedirs(os.path.join(d, "logs"), exist_ok=True)

    # config.py bunları import anında okur.
    os.environ["DB_PATH"]             = os.path.join(d, "data", "astra.db")
    os.environ["JOURNAL_DB_PATH"]     = os.path.join(d, "data", "journal.db")
    # v57'de env'e açıldı (öncesinde sabit koduydu).
    os.environ["MODEL_REGISTRY_DB"]   = os.path.join(d, "data", "model_registry.db")
    os.environ["MODEL_VERSIONS_DIR"]  = os.path.join(d, "saved_models", "versions")
    # v58 (K-21): model + feedback dosyaları da izole. Öncesinde MODEL_DIR
    # sabit koduydu; testler üretim `saved_models/` dizinine .pkl ve
    # feedback_*.jsonl yazıyordu. Feedback dosyaları modelin eğitim
    # verisidir — kirlenmeleri doğrudan sinyali etkiler.
    os.environ["MODEL_DIR"]           = os.path.join(d, "saved_models") + os.sep
    os.environ["AB_DATA_PATH"]        = os.path.join(d, "data", "ab_test.json")
    # ── v58 (K-100): STATE_FILE YÖNLENDİRİLMİYORDU ──────────────
    # `data/position_state.json` URETIM_YOLLARI listesinde VARDI (yani
    # kirlilik denetimi onu sayıyordu) ama burada env'i KURULMUYORDU.
    # `config.STATE_FILE` zaten `os.getenv("STATE_FILE", ...)` — yani
    # yönlendirilebilirdi, sadece yönlendirilmemişti. §4.6'nın yarım
    # uygulanmış hâli: "listeye ekle VE izole_et() içine ekle".
    #
    # SONUÇ (2026-09-15'te yakalandı): testler ÜRETİM state'ini okuyup
    # YAZIYORDU. Bot canlı bir pozisyon tutarken `test_pozisyon_kaynagi`
    # onu görüp "pozisyon yokken 1 döndü" diye kırmızıya döndü — test
    # kusurlu değildi, izolasyon eksikti. Ters yönü daha kötü: testler
    # çalışan botun pozisyon state'ine YAZABİLİYORDU.
    os.environ["STATE_FILE"]          = os.path.join(d, "data", "position_state.json")
    # v57: Log da yönlendirilir. Aksi halde testler ÜRETİM `logs/astra.log`
    # dosyasına sentetik fikstür satırları (BTCUSDT @ 63018.9 gibi) yazıyor;
    # veri bozulmuyor ama teşhis kaydı güvenilmez oluyor — logu inceleyen
    # biri bu satırları gerçek işlem sanabilir.
    os.environ["ASTRA_LOG_DIR"]       = os.path.join(d, "logs")
    os.environ["ASTRA_TEST_DIZINI"]   = d

    # Geç çağrı tespiti: config zaten yüklendiyse yönlendirme ETKİSİZDİR.
    # Sessiz geçmek, kirliliğin geri gelip fark edilmemesi demektir
    # (DEVAM_NOTLARI.md §5.2 "sessiz başarısızlık" kuralı).
    if "config" in sys.modules:
        print(
            "  ⚠️  UYARI: izole_et() config.py yüklendikten SONRA çağrıldı — "
            "yol yönlendirmesi ETKİSİZ. Testler üretim verisine yazabilir.",
            file=sys.stderr,
        )

    return d


def uretim_yollari_dokunulmamis_mi(kok: str) -> list:
    """Üretim durum dosyalarının şu anki parmak izlerini döndür.

    Muhafız testi (`test_izolasyon.py`) bunu önce/sonra karşılaştırır.
    """
    import hashlib

    izler = []
    for rel in URETIM_YOLLARI:
        tam = os.path.join(kok, rel)
        if not os.path.exists(tam):
            izler.append((rel, None))
            continue
        with open(tam, "rb") as fh:
            izler.append((rel, hashlib.sha256(fh.read()).hexdigest()))
    return izler
