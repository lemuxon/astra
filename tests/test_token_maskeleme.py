# =========================================================
# ASTRA — TELEGRAM TOKEN'I LOG'A DÜŞMEMELİ (v58, K-108)
# Çalıştırma: python tests/test_token_maskeleme.py
#
# ÖLÇÜLDÜ (2026-10-06 18:44, bot yeniden başlatılırken):
#   `requests` istisnasının metni URL'in TAMAMINI içerir ve Telegram
#   URL'inde token var. `log.error(f"... {e}")` bunu düz metin olarak
#   diske yazıyordu:
#
#     401 Client Error: Unauthorized for url:
#     https://api.telegram.org/bot<TOKEN GÖRÜNÜYORDU>/sendMessage
#
#   4 log dosyasında bulundu: astra.log, astra_onemli.log,
#   bot_autostart.log (×2).
#
# ⚠️ SECURITY.md bunu AÇIKÇA güvenlik kusuru sayıyor: "Anything that
#   could leak credentials ... into logs". Depo herkese açık; biri hata
#   ayıklamak için log parçası paylaşırsa token'ı da paylaşır.
#
# ⚠️ NEDEN İKİ KATMAN: yalnızca `.env` değerini değiştirmek
#   "bilmediğim token sızmaz" varsayımı olurdu (§5.1 fail-open). URL
#   deseni de yakalanıyor, böylece token .env'dekinden FARKLI gelse bile
#   (eski token, kopyala-yapıştır hatası, başka modülün değeri) sızmaz.
#
# ⚠️ NEDEN KONTROL TESTLERİ: "her şeyi <BOT_TOKEN> ile değiştir" diyen
#   bir kod da guard'ları geçer ama logu işe yaramaz hale getirir.
#   Kontroller teşhis bilgisinin KORUNDUĞUNU kilitliyor.
#
# Ağ, veritabanı ve gerçek emir kullanılmaz. Gerçek token OKUNMAZ —
# testler modülün BOT_TOKEN'ını geçici olarak sahte değerle değiştirir,
# böylece sonuç makineden bağımsızdır.
# =========================================================
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

import core.log_gizle as lg
import core.telegram_gonderim as tg

SAHTE = "1234567890:AAFakeTokenForTestingOnly_abcdefghij"
BASKA = "9876543210:BBDifferentTokenNotInEnv_klmnopqrst"


def _ile_token(deger, fn):
    """BOT_TOKEN'i gecici olarak degistirip calistirir.

    DIKKAT: maskeleme `core.log_gizle`'de yasiyor, `telegram_gonderim`
    yalnizca onu import ediyor. Yanlis modulu yamalamak testi SESSIZCE
    etkisiz birakir (gercek .env degeri okunur, sonuc makineye baglanir).
    Bu tam olarak bu projenin "yanlis sebeple gecen test" tuzagi.
    """
    asil = lg.BOT_TOKEN
    lg.BOT_TOKEN = deger
    try:
        return fn()
    finally:
        lg.BOT_TOKEN = asil


def test_maskeleme_TEK_KAYNAK():
    """telegram_gonderim._gizle, log_gizle.token_gizle ile AYNI olmali.

    Iki yerde iki desen listesi tutulursa biri gunceller biri kalir ve
    "bir yerde maskelendi, otekinde sizdi" olur. Bu test o ayrismayi
    yakalar.
    """
    assert tg._gizle is lg.token_gizle, (
        "telegram_gonderim yerel bir kopya kullaniyor — desenler ayrisabilir")


# ── GUARD: token hiçbir biçimde log'a geçmemeli ─────────────────────

def test_url_icindeki_token_maskelenir():
    """requests istisnasının tipik metni — token silinmeli."""
    mesaj = ("401 Client Error: Unauthorized for url: "
             "https://api.telegram.org/bot%s/sendMessage" % SAHTE)
    c = _ile_token(SAHTE, lambda: tg._gizle(mesaj))
    assert SAHTE not in c, "Token maskelenmedi! Log'a düz metin yazılır: %r" % c
    assert "<BOT_TOKEN>" in c, "Maskeleme işareti yok: %r" % c


def test_CIPLAK_token_da_maskelenir():
    """Token URL olmadan, tek başına geçse de silinmeli."""
    c = _ile_token(SAHTE, lambda: tg._gizle("beklenmeyen hata, token=%s" % SAHTE))
    assert SAHTE not in c, "URL dışında geçen token maskelenmedi: %r" % c


def test_ENV_DISI_token_da_maskelenir():
    """BOT_TOKEN'dan FARKLI bir token bile URL deseninden yakalanmalı.

    Bu, §5.1'in uygulaması: "bu değeri tanımıyorum" ≠ "sızmasında sorun yok".
    Tek katman (sadece BOT_TOKEN.replace) olsaydı bu test kırmızı olurdu.
    """
    mesaj = "hata: https://api.telegram.org/bot%s/sendPhoto" % BASKA
    c = _ile_token(SAHTE, lambda: tg._gizle(mesaj))   # .env'de SAHTE var, mesajda BASKA
    assert BASKA not in c, (
        "Tanınmayan token sızdı — URL deseni yakalamıyor: %r" % c)


def test_token_bos_olsa_bile_COKMEZ():
    """BOT_TOKEN boşken `.replace('')` her yere eklenmemeli, çökmemeli."""
    c = _ile_token("", lambda: tg._gizle("sıradan bir hata mesajı"))
    assert c == "sıradan bir hata mesajı", "Boş token metni bozdu: %r" % c


# ── KONTROL: teşhis bilgisi KORUNMALI (yoksa log işe yaramaz) ───────

def test_teshis_bilgisi_KORUNUR():
    """Maskeleme HTTP kodunu ve hata nedenini silmemeli.

    Bu kontrol olmadan guard'ları, her şeyi maskeleyen bir kod da geçer
    ve logdan "neden gönderilemedi" sorusu cevaplanamaz hale gelir.
    """
    mesaj = ("401 Client Error: Unauthorized for url: "
             "https://api.telegram.org/bot%s/sendMessage" % SAHTE)
    c = _ile_token(SAHTE, lambda: tg._gizle(mesaj))
    assert "401" in c, "HTTP kodu kayboldu: %r" % c
    assert "Unauthorized" in c, "Hata nedeni kayboldu: %r" % c
    assert "api.telegram.org" in c, "Hangi servis olduğu kayboldu: %r" % c


def test_token_SUZ_mesaj_AYNEN_gecer():
    """İçinde token olmayan mesaj hiç değişmemeli."""
    mesaj = "ConnectionError: Max retries exceeded (timeout=10)"
    c = _ile_token(SAHTE, lambda: tg._gizle(mesaj))
    assert c == mesaj, "Token içermeyen mesaj değiştirildi: %r" % c


def test_chat_id_gibi_kisa_sayilar_bozulmaz():
    """Desen fazla agresif olmamalı — sıradan sayılar maskelenmemeli."""
    mesaj = "chat_id=123456789 gönderildi, 2 parça, 4096 sınırı"
    c = _ile_token(SAHTE, lambda: tg._gizle(mesaj))
    assert c == mesaj, "Sıradan sayılar maskelendi: %r" % c


# ── İstisna nesnesi de kabul edilmeli (log'da {e} geçiyor) ──────────

def test_istisna_nesnesi_kabul_edilir():
    """_gizle() str değil Exception alabilir — çağrı yeri `{_gizle(e)}`."""
    hata = RuntimeError("url: https://api.telegram.org/bot%s/sendMessage" % SAHTE)
    c = _ile_token(SAHTE, lambda: tg._gizle(hata))
    assert SAHTE not in c, "Exception nesnesinden token sızdı: %r" % c


def test_CIPLAK_InvalidToken_bicimi_maskelenir():
    """python-telegram-bot'un mesaji token'i URL OLMADAN tasiyor.

    OLCULDU (2026-10-06 18:45 ve 18:47, main.py:3456):
      "InvalidToken: The token `<TOKEN>` was rejected by the server"
    Bu IKINCI sizma yoluydu; yalnizca URL desenine bakan eski surum
    bunu KACIRIYORDU.
    """
    mesaj = "InvalidToken: The token `%s` was rejected by the server" % SAHTE
    c = _ile_token("", lambda: lg.token_gizle(mesaj))   # .env bos: yalniz desen calissin
    assert SAHTE not in c, "Ciplak token sizdi: %r" % c
    assert "InvalidToken" in c and "rejected" in c, "Teshis bilgisi kayboldu: %r" % c


def test_formatter_TRACEBACK_icindeki_tokeni_maskeler():
    """exc_info=True ile yazilan TRACEBACK'te de token kalmamali.

    NEDEN FORMATTER, FILTER DEGIL: `record.exc_text` filtre calistigi anda
    henuz None'dir; traceback metni formatlama sirasinda uretilir. Filtre
    kullansaydik traceback icindeki token KACARDI. Bu test o secimi kilitler.
    """
    import logging, tempfile, io as _io, os as _os
    yol = _os.path.join(tempfile.mkdtemp(), "t.log")
    h = logging.FileHandler(yol, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    kok = logging.getLogger("TEST_K108")
    kok.handlers = [h]
    kok.propagate = False
    kok.setLevel(logging.DEBUG)
    try:
        assert lg.kur(kok) == 1, "handler sarilmadi"
        try:
            raise RuntimeError("The token `%s` was rejected" % SAHTE)
        except RuntimeError:
            kok.critical("baslatma hatasi", exc_info=True)
        h.flush()
        icerik = _io.open(yol, encoding="utf-8").read()
    finally:
        h.close()
        kok.handlers = []
    assert "Traceback" in icerik, "exc_info yazilmamis, test anlamsiz: %r" % icerik[:200]
    assert SAHTE not in icerik, "TRACEBACK'ten token sizdi!"
    assert "RuntimeError" in icerik, "Istisna tipi kayboldu"


def test_kur_IKI_KEZ_sarmaz():
    """kur() tekrar cagrilirsa ayni handler'i ikinci kez sarmamali."""
    import logging
    h = logging.NullHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    kok = logging.getLogger("TEST_K108_2")
    kok.handlers = [h]
    try:
        assert lg.kur(kok) == 1, "ilk cagri sarmali"
        assert lg.kur(kok) == 0, "ikinci cagri sarmamali (cift sarma)"
    finally:
        kok.handlers = []


def test_kur_handler_YOKSA_sifir_dondurur():
    """Handler yoksa 0 donmeli — main.py bunu CRITICAL uyarisi icin kullaniyor."""
    import logging
    kok = logging.getLogger("TEST_K108_3")
    kok.handlers = []
    assert lg.kur(kok) == 0, "handler yokken 0 donmeli"


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA TOKEN MASKELEME (K-108) — {len(testler)} test")
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
