# =========================================================
# ASTRA v57 — WATCHDOG UYKU/DONMA AYRIMI TESTLERİ
# Çalıştırma: python tests/test_watchdog_uyku.py
#
# NE KORUYOR:
#   Watchdog duvar saati sessizliğini ölçüyor ve v56'ya kadar "thread dondu"
#   ile "makine uyudu"yu AYIRT EDEMİYORDU.
#
#   ÖLÇÜLEN VAKA (2026-08-24): Laptop 22 saat 24 dakika uyudu
#   (Power-Troubleshooter: 08-23T19:47:52Z → 08-24T18:11:39Z). Uyanınca
#   watchdog "80678s sessiz" diye CRITICAL alarm + Telegram bildirimi
#   üretti. Bot donmamıştı — 25 saniye sonra normale döndü.
#
#   İKİ AYRI ZARAR:
#     1. Her sabah sahte CRITICAL → kullanıcı watchdog alarmlarını ciddiye
#        almamayı öğrenir ve GERÇEK bir donma kaçar.
#     2. `_uyari_sayisi >= 3` olunca watchdog SIGTERM ile botu ÖLDÜRÜR.
#        Uyanış 3 dakikayı aşarsa bot kendini kapatır; Windows'ta systemd
#        olmadığı için geri gelmesi zamanlanmış göreve kalır (10 dk kayıp).
#
#   AYRIM: Gerçek donmada watchdog thread'i tıklamaya DEVAM eder
#   (tik ≈ check_interval) ama heartbeat eskir. Askıya almada time.sleep()
#   duvar saatinde saatlerce sürer → tik patlar.
#
# §4.1: Muhafızın yanında KONTROL testi var — "hiç alarm verme" davranışı
#   uyku testlerini geçer ama gerçek donmayı da sessizleştirir.
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
    """Sonsuz _loop'u sonlu testte durdurmak için sentinel."""


def _kosturr(w, tik_sureleri, wd_mod):
    """_loop'u sahte bir saatle çalıştır.

    tik_sureleri: her `time.sleep` çağrısının duvar saatinde kaç saniye
    sürdüğü. Askıya alma = devasa bir değer.

    Returns: (alarm_mesajlari, uyari_loglari)
    """
    saat = {"t": 1000.0}
    kalan = list(tik_sureleri)

    def _sahte_sleep(_s):
        if not kalan:
            raise _Dur()
        saat["t"] += kalan.pop(0)

    def _sahte_time():
        return saat["t"]

    gercek_sleep, gercek_time = wd_mod.time.sleep, wd_mod.time.time
    gercek_kill = wd_mod.os.kill
    # 3 alarm sonrası watchdog os.kill(getpid(), SIGTERM) çağırıyor —
    # yakalanmazsa TEST SÜRECİNİ öldürür (ilk denemede exit 15 alındı).
    oldurmeler = []
    wd_mod.os.kill = lambda pid, sig: oldurmeler.append((pid, sig))
    wd_mod.time.sleep = _sahte_sleep
    wd_mod.time.time  = _sahte_time
    w._son_heartbeat = saat["t"]      # sahte saate hizala
    w._running = True

    alarmlar, uyarilar = [], []
    import logging

    class _Yakala(logging.Handler):
        def emit(self, kayit):
            m = kayit.getMessage()
            if kayit.levelno >= logging.CRITICAL:
                alarmlar.append(m)
            elif kayit.levelno >= logging.WARNING:
                uyarilar.append(m)

    h = _Yakala()
    wd_mod.log.addHandler(h)
    try:
        w._loop()
    except _Dur:
        pass
    finally:
        wd_mod.log.removeHandler(h)
        wd_mod.time.sleep = gercek_sleep
        wd_mod.time.time  = gercek_time
        wd_mod.os.kill    = gercek_kill
    return alarmlar, uyarilar, oldurmeler


def _yeni_watchdog():
    import engines.watchdog as wd
    w = wd.Watchdog(max_silent=300, check_interval=60)
    w._thread_dump_logla = lambda *a, **k: None      # test gürültüsünü kes
    return w, wd


# ─────────────────────────────────────────────
# 1. MUHAFIZ — uyku alarm ÜRETMEMELİ
# ─────────────────────────────────────────────
def test_uyku_sonrasi_alarm_verilmez():
    """22 saatlik askıya alma sonrası CRITICAL alarm OLMAMALI.

    Gerçek vakanın birebir kopyası: tek bir tik 80678 saniye sürüyor.
    """
    w, wd = _yeni_watchdog()
    alarmlar, uyarilar, _ = _kosturr(w, [80678.0, 60.0], wd)

    assert not alarmlar, (
        f"Uyku sonrası CRITICAL alarm verildi: {alarmlar}. "
        f"Her sabah sahte alarm → gerçek donma görmezden gelinir.")
    assert any("askıya" in u.lower() for u in uyarilar), (
        f"Askıya alma tespit edilip loglanmadı. Uyarılar: {uyarilar}")


def test_uyku_sonrasi_uyari_sayaci_sifirlanir():
    """Askıya alma sonrası `_uyari_sayisi` 0 olmalı.

    Sıfırlanmazsa birikip SIGTERM eşiğine (3) ulaşır ve watchdog botu
    ÖLDÜRÜR — veri toplama durur.
    """
    w, wd = _yeni_watchdog()
    w._uyari_sayisi = 2                     # SIGTERM'e bir kala
    _kosturr(w, [80678.0, 60.0], wd)

    assert w._uyari_sayisi == 0, (
        f"Uyarı sayacı {w._uyari_sayisi} — sıfırlanmamış. Bir alarm daha "
        f"gelirse watchdog botu SIGTERM ile öldürür.")


def test_uyku_heartbeat_taban_cizgisini_gunceller():
    """Uyandıktan sonra heartbeat referansı ŞU ANA çekilmeli.

    Aksi halde bir sonraki tikte yine 22 saatlik sessizlik görünür ve
    alarm zinciri devam eder.
    """
    w, wd = _yeni_watchdog()
    alarmlar, _, _ = _kosturr(w, [80678.0, 60.0, 60.0, 60.0], wd)
    assert not alarmlar, (
        f"Uyanıştan sonraki tiklerde alarm devam etti: {alarmlar} — "
        f"heartbeat taban çizgisi güncellenmemiş")


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
#    "Hiç alarm verme" davranışı yukarıdakileri de geçer.
# ─────────────────────────────────────────────
def test_kontrol_gercek_donma_hala_alarm_veriyor():
    """Watchdog tıklamaya devam ederken heartbeat eskirse ALARM ŞART.

    Bu, düzeltmenin gerçek donma tespitini bozmadığının kanıtı.
    Senaryo: tikler normal (60s) ama heartbeat hiç yenilenmiyor →
    max_silent (300s) aşılır.
    """
    w, wd = _yeni_watchdog()
    alarmlar, _, oldurmeler = _kosturr(w, [60.0] * 8, wd)

    assert alarmlar, (
        "Gerçek donmada alarm VERİLMEDİ — watchdog artık işe yaramıyor. "
        "Uyku düzeltmesi donma tespitini de sessizleştirmiş.")
    assert any("sessiz" in a.lower() for a in alarmlar), (
        f"Alarm mesajı beklenen formatta değil: {alarmlar}")
    # 3 alarmdan sonra SIGTERM yolu da çalışmalı — gerçek donmada
    # sürecin yeniden başlatılması KASITLI davranıştır.
    assert oldurmeler, (
        "3 alarma rağmen SIGTERM gönderilmedi — donmuş süreç yeniden "
        "başlatılmaz, veri toplama kalıcı durur")


def test_kontrol_normal_calismada_alarm_yok():
    """Heartbeat düzenli gelirken alarm OLMAMALI (yanlış pozitif kontrolü)."""
    w, wd = _yeni_watchdog()

    # Her tikte heartbeat gelmiş gibi davran: _son_heartbeat'i ilerlet.
    import engines.watchdog as _wd
    saat_ilerlet = []

    w2, wd2 = w, wd
    # Basit yol: tikleri max_silent altında tut ve her tikte heartbeat çağır.
    saat = {"t": 1000.0}
    kalan = [60.0] * 6

    def _sahte_sleep(_s):
        if not kalan:
            raise _Dur()
        saat["t"] += kalan.pop(0)
        w2._son_heartbeat = saat["t"]        # düzenli heartbeat

    def _sahte_time():
        return saat["t"]

    import logging
    alarmlar = []

    class _Yakala(logging.Handler):
        def emit(self, kayit):
            if kayit.levelno >= logging.CRITICAL:
                alarmlar.append(kayit.getMessage())

    h = _Yakala()
    gs, gt = wd2.time.sleep, wd2.time.time
    wd2.time.sleep, wd2.time.time = _sahte_sleep, _sahte_time
    wd2.log.addHandler(h)
    w2._son_heartbeat = saat["t"]
    w2._running = True
    try:
        w2._loop()
    except _Dur:
        pass
    finally:
        wd2.log.removeHandler(h)
        wd2.time.sleep, wd2.time.time = gs, gt

    assert not alarmlar, f"Normal çalışmada alarm verildi: {alarmlar}"


def test_kontrol_kisa_gecikme_uyku_sayilmaz():
    """Küçük jitter (2x check_interval) askıya alma SAYILMAMALI.

    Eşik çok gevşek olursa gerçek donmalar 'uyku' diye yutulur.
    """
    w, wd = _yeni_watchdog()
    # 120s tik = 2x check_interval → eşiğin (3x=180s) ALTINDA
    alarmlar, uyarilar, _ = _kosturr(w, [120.0] * 5, wd)

    assert not any("askıya" in u.lower() for u in uyarilar), (
        f"2x gecikme yanlışlıkla 'askıya alma' sayıldı — eşik çok gevşek, "
        f"gerçek donmalar yutulur. Uyarılar: {uyarilar}")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA WATCHDOG UYKU/DONMA AYRIMI — {len(testler)} test")
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
