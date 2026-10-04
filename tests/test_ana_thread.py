# =========================================================
# ASTRA v57 — ANA THREAD DAYANIKLILIĞI TESTLERİ
# Çalıştırma: python tests/test_ana_thread.py
#
# NE KORUYOR:
#   `bot` modu trading motorunu DAEMON thread'de çalıştırır ve Telegram'ı
#   ana thread'de. Ana thread biterse Python çıkar ve daemon motor thread'i
#   ÖLDÜRÜLÜR — motorun kendi koruyucu while döngüsü buna çare olmaz.
#
#   v56'da `telegram_bot_baslat()` DOĞRUDAN çağrılıyordu. O fonksiyon hatayı
#   kendi içinde yutup return eder → ana thread biter → motor ölür.
#   Gerçekleşen sonuç: oturum açılışında DNS hazır değilken Telegram
#   `getaddrinfo failed` aldı ve bot 2026-08-21..23 arasında 2+ gün hiç veri
#   toplamadı (8022 getaddrinfo failed, 325 NetworkError).
#
# §4.1: Muhafız testinin yanına KONTROL testi yazıldı — "asla dönmeyen"
#   bir fonksiyon muhafız testini de geçer, o yüzden Telegram'ın GERÇEKTEN
#   çağrıldığı ve yeniden denendiği ayrıca kanıtlanıyor.
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


class _Dur(Exception):
    """Sonsuz döngüyü testte sonlandırmak için sentinel."""


def _kur(main, *, telegram_var=True, token="123:ABC", cagri_kaydi=None,
         uyku_limiti=3):
    """telegram_denetimli_calistir'ı test edilebilir hale getir.

    time.sleep'i sayaçlı bir sahte ile değiştirir; `uyku_limiti` kadar
    uykudan sonra _Dur fırlatır. Böylece "sonsuza kadar döner" davranışı
    sonlu bir testte gözlemlenebilir.
    """
    orijinal = {
        "sleep": main.time.sleep,
        "baslat": main.telegram_bot_baslat,
        "avail": main.TELEGRAM_BOT_AVAILABLE,
        "token": main.BOT_TOKEN,
    }
    sayac = {"uyku": 0, "sure": []}

    def _sahte_sleep(s):
        sayac["uyku"] += 1
        sayac["sure"].append(s)
        if sayac["uyku"] >= uyku_limiti:
            raise _Dur()

    main.time.sleep = _sahte_sleep
    main.TELEGRAM_BOT_AVAILABLE = telegram_var
    main.BOT_TOKEN = token
    if cagri_kaydi is not None:
        def _sahte_baslat():
            cagri_kaydi.append(1)
            return          # v56 davranışı: hatayı yutup DÖN
        main.telegram_bot_baslat = _sahte_baslat
    return orijinal, sayac


def _geri_al(main, orijinal):
    main.time.sleep = orijinal["sleep"]
    main.telegram_bot_baslat = orijinal["baslat"]
    main.TELEGRAM_BOT_AVAILABLE = orijinal["avail"]
    main.BOT_TOKEN = orijinal["token"]


# ─────────────────────────────────────────────
# 1. MUHAFIZ — Telegram dönse bile ana thread bitmemeli
# ─────────────────────────────────────────────
def test_telegram_donerse_ana_thread_bitmez():
    """telegram_bot_baslat() return etse bile denetimli katman DÖNMEMELİ.

    Dönerse ana thread biter → daemon AstraEngine thread'i öldürülür →
    veri toplama sessizce durur. v56'daki tam senaryo buydu.
    """
    import main
    cagrilar = []
    orijinal, sayac = _kur(main, cagri_kaydi=cagrilar, uyku_limiti=3)
    try:
        dondu_mu = False
        try:
            main.telegram_denetimli_calistir()
            dondu_mu = True          # BURAYA GELİNMEMELİ
        except _Dur:
            pass                     # döngü devam ediyordu — doğru
        assert not dondu_mu, (
            "telegram_denetimli_calistir() DÖNDÜ — ana thread biter ve "
            "daemon trading motoru öldürülür (v56 hatası geri gelmiş)")
    finally:
        _geri_al(main, orijinal)


def test_telegram_kapaliyken_de_ana_thread_bitmez():
    """BOT_TOKEN yoksa da ana thread canlı kalmalı.

    Telegram kasıtlı kapalı olabilir; bu, trading motorunun ölmesi için
    sebep değildir.
    """
    import main
    orijinal, sayac = _kur(main, telegram_var=True, token="", uyku_limiti=2)
    try:
        dondu_mu = False
        try:
            main.telegram_denetimli_calistir()
            dondu_mu = True
        except _Dur:
            pass
        assert not dondu_mu, (
            "BOT_TOKEN boşken fonksiyon döndü — motor ölür")
    finally:
        _geri_al(main, orijinal)


def test_paket_yoksa_da_ana_thread_bitmez():
    """python-telegram-bot yüklü değilse de ana thread canlı kalmalı."""
    import main
    orijinal, sayac = _kur(main, telegram_var=False, token="123:ABC",
                           uyku_limiti=2)
    try:
        dondu_mu = False
        try:
            main.telegram_denetimli_calistir()
            dondu_mu = True
        except _Dur:
            pass
        assert not dondu_mu, "Telegram paketi yokken fonksiyon döndü"
    finally:
        _geri_al(main, orijinal)


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
#    "Hiç çağırmayan / hep bloklayan" kod da muhafızı geçer.
# ─────────────────────────────────────────────
def test_kontrol_telegram_gercekten_yeniden_deneniyor():
    """Telegram başarısız olunca GERÇEKTEN yeniden çağrılmalı.

    Muhafız testi, fonksiyon hiç Telegram çağırmadan sonsuza kadar uyusa
    da geçerdi. Bu test çağrının tekrarlandığını kanıtlar.
    """
    import main
    cagrilar = []
    orijinal, sayac = _kur(main, cagri_kaydi=cagrilar, uyku_limiti=3)
    try:
        try:
            main.telegram_denetimli_calistir()
        except _Dur:
            pass
        assert len(cagrilar) >= 3, (
            f"telegram_bot_baslat yalnızca {len(cagrilar)} kez çağrıldı — "
            f"yeniden deneme çalışmıyor, Telegram kalıcı ölü kalır")
    finally:
        _geri_al(main, orijinal)


def test_kontrol_yeniden_deneme_backoff_uyguluyor():
    """Bekleme süresi artmalı ve üst sınırla kapanmalı.

    Sabit 0s bekleme CPU'yu yakar; sınırsız artış Telegram'ı kalıcı
    ölü bırakır. İkisi de istenmiyor.
    """
    import main
    cagrilar = []
    orijinal, sayac = _kur(main, cagri_kaydi=cagrilar, uyku_limiti=4)
    try:
        try:
            main.telegram_denetimli_calistir()
        except _Dur:
            pass
        sureler = sayac["sure"]
        assert sureler, "Hiç bekleme yapılmadı — sıkı döngü CPU'yu yakar"
        assert all(s > 0 for s in sureler), f"Sıfır bekleme var: {sureler}"
        assert sureler == sorted(sureler), (
            f"Bekleme süresi artmıyor (backoff yok): {sureler}")
        assert max(sureler) <= 900, (
            f"Bekleme üst sınırı aşıldı: {max(sureler)}s — Telegram çok "
            f"uzun süre ölü kalır")
    finally:
        _geri_al(main, orijinal)


def test_kontrol_telegram_kapaliyken_bosuna_denemiyor():
    """Kasıtlı kapalıysa telegram_bot_baslat HİÇ çağrılmamalı.

    Aksi halde her döngüde boşuna çağrı yapılır ve log dolar.
    """
    import main
    cagrilar = []
    orijinal, sayac = _kur(main, token="", cagri_kaydi=cagrilar,
                           uyku_limiti=2)
    try:
        try:
            main.telegram_denetimli_calistir()
        except _Dur:
            pass
        assert not cagrilar, (
            f"BOT_TOKEN boşken telegram_bot_baslat {len(cagrilar)} kez "
            f"çağrıldı — gereksiz")
    finally:
        _geri_al(main, orijinal)


# ─────────────────────────────────────────────
# 3. YAPISAL: giriş noktası doğru fonksiyonu çağırıyor mu
# ─────────────────────────────────────────────
def test_bot_modu_denetimli_katmani_cagiriyor():
    """`bot` modu DOĞRUDAN telegram_bot_baslat() çağırmamalı.

    Kaynak düzeyinde kontrol: düzeltme geri alınırsa (birisi tekrar
    doğrudan çağrı yazarsa) bu test yakalar.
    """
    yol = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py")
    with open(yol, encoding="utf-8") as fh:
        satirlar = fh.readlines()

    # `elif mod == "bot":` bloğunu bul
    bas = None
    for i, s in enumerate(satirlar):
        if s.strip().startswith('elif mod == "bot"'):
            bas = i
            break
    assert bas is not None, "main.py'de `elif mod == \"bot\":` bulunamadı"

    blok = []
    for s in satirlar[bas + 1:]:
        if s.strip().startswith("elif mod ==") or s.strip().startswith("else:"):
            break
        blok.append(s)
    metin = "".join(blok)

    assert "telegram_denetimli_calistir()" in metin, (
        "bot modu telegram_denetimli_calistir() çağırmıyor")
    # Yorum satırlarını çıkar, sonra doğrudan çağrıyı ara
    kod = "\n".join(l for l in metin.splitlines()
                    if not l.strip().startswith("#"))
    assert "telegram_bot_baslat()" not in kod, (
        "bot modu hâlâ DOĞRUDAN telegram_bot_baslat() çağırıyor — "
        "hata durumunda ana thread biter ve trading motoru ölür")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA ANA THREAD DAYANIKLILIĞI — {len(testler)} test")
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
