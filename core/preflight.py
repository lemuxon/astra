# ===========================================================
# ASTRA v38.0 — BAŞLANGIÇ SAĞLIK KONTROLÜ (PREFLIGHT CHECK)
# Bot başlamadan önce config, bağlantı ve kritik ayarları doğrular.
# Profesyonel ürün standardı: sessiz hatalı çalışma yerine net uyarı.
# ===========================================================
import os
import time
import logging

log = logging.getLogger("ASTRA.PREFLIGHT")


class PreflightSonuc:
    """Tek bir kontrolün sonucu."""
    def __init__(self, ad: str, gecti: bool, mesaj: str, kritik: bool = False):
        self.ad = ad
        self.gecti = gecti
        self.mesaj = mesaj
        self.kritik = kritik   # True ise başarısızlık botu durdurur


def _kontrol_python_surum() -> PreflightSonuc:
    import sys
    v = sys.version_info
    if v.major == 3 and v.minor >= 9:
        return PreflightSonuc("Python sürümü", True, f"Python {v.major}.{v.minor}")
    return PreflightSonuc("Python sürümü", False,
                          f"Python {v.major}.{v.minor} — 3.9+ gerekli", kritik=True)


def _kontrol_paketler() -> PreflightSonuc:
    """Zorunlu paketler yüklü mü?"""
    zorunlu = ["pandas", "numpy", "sklearn", "requests", "dotenv"]
    eksik = []
    for p in zorunlu:
        try:
            __import__(p)
        except ImportError:
            eksik.append(p)
    if not eksik:
        return PreflightSonuc("Zorunlu paketler", True, "Tümü yüklü")
    return PreflightSonuc("Zorunlu paketler", False,
                          f"Eksik: {', '.join(eksik)} → pip install", kritik=True)


def _kontrol_opsiyonel_paketler() -> PreflightSonuc:
    """Opsiyonel paketler — yokluğu botu durdurmaz ama özellik kapanır."""
    opsiyonel = {
        "xgboost": "XGBoost modeli",
        "river": "Online learning",
        "stable_baselines3": "RL ajanı",
        "websocket": "Canlı fiyat akışı (WS)",
        "tensorflow": "TFT modeli",
    }
    kapali = []
    for paket, ozellik in opsiyonel.items():
        try:
            __import__(paket)
        except ImportError:
            kapali.append(ozellik)
    if not kapali:
        return PreflightSonuc("Opsiyonel paketler", True, "Tümü aktif")
    return PreflightSonuc("Opsiyonel paketler", True,
                          f"Kapalı (bot çalışır): {', '.join(kapali)}")


def _kontrol_config() -> list:
    """Kritik config ayarlarını doğrula."""
    sonuclar = []
    try:
        from config import (BOT_TOKEN, CHAT_ID, BINANCE_API_KEY,
                            BINANCE_API_SECRET, LIVE_TRADING, IS_TESTNET,
                            FUTURES_LEVERAGE, TRADE_USDT)
    except ImportError as e:
        sonuclar.append(PreflightSonuc("Config yükleme", False,
                                        f"config.py okunamadı: {e}", kritik=True))
        return sonuclar

    # Telegram
    if BOT_TOKEN and CHAT_ID:
        sonuclar.append(PreflightSonuc("Telegram ayarı", True, "Token + Chat ID mevcut"))
    elif BOT_TOKEN and not CHAT_ID:
        sonuclar.append(PreflightSonuc("Telegram ayarı", True,
                                        "Token var, CHAT_ID yok — bildirimler gitmeyebilir"))
    else:
        sonuclar.append(PreflightSonuc("Telegram ayarı", True,
                                        "Token yok — Telegram bot devre dışı (bot yine çalışır)"))

    # Binance API
    if BINANCE_API_KEY and BINANCE_API_SECRET:
        sonuclar.append(PreflightSonuc("Binance API", True, "Anahtarlar mevcut"))
    else:
        kritiklik = LIVE_TRADING  # canlı modda API zorunlu
        sonuclar.append(PreflightSonuc("Binance API", not kritiklik,
                                        "API anahtarı yok" +
                                        (" — CANLI MOD için ZORUNLU!" if kritiklik
                                         else " (paper mod için sorun değil)"),
                                        kritik=kritiklik))

    # LIVE_TRADING güvenlik uyarısı
    if LIVE_TRADING:
        if IS_TESTNET:
            sonuclar.append(PreflightSonuc("İşlem modu", True,
                                            "CANLI MOD + Testnet (test parası, güvenli)"))
        else:
            sonuclar.append(PreflightSonuc("İşlem modu", True,
                                            "⚠️ GERÇEK PARA MODU AKTİF — dikkatli ol!"))
    else:
        sonuclar.append(PreflightSonuc("İşlem modu", True,
                                        "Paper/test modu (LIVE_TRADING=false) — güvenli"))

    # Kaldıraç makul mu?
    # v55: Eskiden her iki dal da gecti=True idi — 125x bile yalnızca uyarı
    # basıp botu başlatıyordu. Canlı modda sert tavan artık başlatmayı engeller.
    if FUTURES_LEVERAGE > 50:
        sonuclar.append(PreflightSonuc(
            "Kaldıraç", not LIVE_TRADING,
            f"🚨 {FUTURES_LEVERAGE}x AŞIRI YÜKSEK — canlı modda reddedilir "
            f"(FUTURES_LEVERAGE değerini düşür)",
            kritik=LIVE_TRADING))
    elif FUTURES_LEVERAGE > 20:
        sonuclar.append(PreflightSonuc("Kaldıraç", False,
                                        f"⚠️ {FUTURES_LEVERAGE}x çok yüksek — likidasyon riski büyük"))
    else:
        sonuclar.append(PreflightSonuc("Kaldıraç", True, f"{FUTURES_LEVERAGE}x"))

    return sonuclar


def _kontrol_veritabani() -> PreflightSonuc:
    """v55: Veritabanı erişilebilir ve bütünlüğü sağlam mı?

    Eskiden preflight yalnızca MODEL_DIR'i kontrol ediyordu; DB_PATH,
    JOURNAL_DB_PATH ve data/ dizini hiç doğrulanmıyordu. Yanlış bir volume
    mount'ta bot preflight'ı geçip ilk trade kaydında patlıyordu.
    """
    import sqlite3
    try:
        from config import DB_PATH
    except ImportError:
        DB_PATH = "data/astra.db"
    try:
        dizin = os.path.dirname(DB_PATH) or "."
        os.makedirs(dizin, exist_ok=True)

        # Yazılabilirlik testi
        test_dosya = os.path.join(dizin, ".preflight_db_test")
        with open(test_dosya, "w") as f:
            f.write("ok")
        os.remove(test_dosya)

        # DB açılabiliyor + bütünlük
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            sonuc = conn.execute("PRAGMA integrity_check").fetchone()
            bozuk = sonuc and str(sonuc[0]).lower() != "ok"
        finally:
            conn.close()

        if bozuk:
            return PreflightSonuc("Veritabanı", False,
                                  f"{DB_PATH} BÜTÜNLÜK HATASI — yedekten dön veya sil",
                                  kritik=True)
        return PreflightSonuc("Veritabanı", True, f"{DB_PATH} erişilebilir, bütünlük OK")
    except Exception as e:
        return PreflightSonuc("Veritabanı", False,
                              f"{DB_PATH} kullanılamıyor: {type(e).__name__}: {e}",
                              kritik=True)


def _kontrol_dosya_sistemi() -> PreflightSonuc:
    """Model/veri klasörleri yazılabilir mi?"""
    try:
        from config import MODEL_DIR
    except ImportError:
        MODEL_DIR = "saved_models"
    try:
        os.makedirs(MODEL_DIR, exist_ok=True)
        test_dosya = os.path.join(MODEL_DIR, ".preflight_test")
        with open(test_dosya, "w") as f:
            f.write("ok")
        os.remove(test_dosya)
        return PreflightSonuc("Dosya sistemi", True, f"{MODEL_DIR} yazılabilir")
    except Exception as e:
        return PreflightSonuc("Dosya sistemi", False,
                              f"{MODEL_DIR} yazılamıyor: {e}", kritik=True)


def _kontrol_binance_baglanti() -> PreflightSonuc:
    """Binance'e erişilebiliyor mu + saat senkronizasyonu."""
    try:
        from config import LIVE_TRADING
    except ImportError:
        LIVE_TRADING = False
    try:
        from config import FUTURES_BASE_URL
        import requests
        t0 = time.time()
        r = requests.get(f"{FUTURES_BASE_URL}/fapi/v1/time", timeout=5)
        gecikme = (time.time() - t0) * 1000
        if r.status_code == 200:
            sunucu_ms = int(r.json()["serverTime"])
            yerel_ms = int(time.time() * 1000)
            fark = abs(sunucu_ms - yerel_ms)
            if fark > 1000:
                return PreflightSonuc("Binance bağlantı", True,
                                      f"Erişim OK ({gecikme:.0f}ms) ama SAAT {fark}ms kaymış "
                                      f"— otomatik düzeltilecek (OS'ta NTP önerilir)")
            return PreflightSonuc("Binance bağlantı", True,
                                  f"Erişim OK ({gecikme:.0f}ms), saat senkron (±{fark}ms)")
        # v55: Bu iki dal eskiden de gecti=True dönüyordu — yani bu kontrol
        # HİÇBİR koşulda başarısız olamıyordu. Binance tamamen erişilemezken
        # bile "✅ Tüm kontroller geçti" yazıp bot canlı işleme başlıyordu.
        return PreflightSonuc("Binance bağlantı", False,
                              f"Yanıt {r.status_code} — bağlantı sorunlu",
                              kritik=LIVE_TRADING)
    except Exception as e:
        return PreflightSonuc("Binance bağlantı", False,
                              f"Erişilemedi: {type(e).__name__} — ağ/firewall kontrol et",
                              kritik=LIVE_TRADING)


def _kontrol_islem_boyutu() -> PreflightSonuc:
    """v56: TRADE_USDT, işlem yapılacak sembollerin min_notional'ını karşılıyor mu?

    Binance'in min_notional filtresi sembole göre değişir (BTCUSDT=50,
    ETHUSDT=20, SOL/XRP=5 USDT). TRADE_USDT bunun altındaysa o sembolde
    emir borsaya HİÇ gitmez — kod yalnızca bir log.warning basıp sessizce
    atlar. Kullanıcı haftalarca "neden bu coinde işlem açılmıyor" diye
    arar ve nedenini bulamaz.

    CANLI_GECIS_PROTOKOLU'nun Aşama 2 ayarı (TRADE_USDT=10) ile BTC ve ETH
    hiç işlem görmez — bu kontrol tam olarak onu yakalar.
    """
    try:
        from config import TRADE_USDT, COINS, LIVE_TRADING
    except ImportError:
        return PreflightSonuc("İşlem boyutu", True, "config okunamadı, atlandı")

    try:
        from data.binance_futures_client import (futures_sembol_filtre,
                                                  futures_anlık_fiyat)
    except Exception:
        return PreflightSonuc("İşlem boyutu", True, "borsa istemcisi yok, atlandı")

    engellenen, kontrol_edilen = [], 0
    for sembol in (COINS or [])[:8]:
        try:
            filtre = futures_sembol_filtre(sembol)
            mn = float(filtre.get("min_notional", 5.0))
            kontrol_edilen += 1
            if TRADE_USDT < mn:
                engellenen.append(f"{sembol}(≥{mn:.0f})")
        except Exception:
            continue

    if not kontrol_edilen:
        return PreflightSonuc("İşlem boyutu", True, "sembol filtresi alınamadı, atlandı")

    if engellenen:
        return PreflightSonuc(
            "İşlem boyutu", False,
            f"TRADE_USDT={TRADE_USDT:.0f} yetersiz → şu semboller HİÇ işlem "
            f"göremez: {', '.join(engellenen)}. TRADE_USDT'yi yükseltin veya "
            f"bu sembolleri COINS'ten çıkarın.",
            kritik=False)

    return PreflightSonuc("İşlem boyutu", True,
                          f"TRADE_USDT={TRADE_USDT:.0f} — {kontrol_edilen} sembolün "
                          f"tümü için yeterli")


def _kontrol_kosullu_emir() -> PreflightSonuc:
    """Koşullu emir (Algo Service) yolu erişilebilir mi?

    v57 — SORUN ÇÖZÜLDÜ, KONTROL DEĞİŞTİ:
      Koşullu emirler `/fapi/v1/order`'dan **Algo Service**'e taşındı.
      Eski endpoint artık şunu döndürüyor:
        -4120 "Order type not supported for this endpoint.
               Please use the Algo Order API endpoints instead."
      Şema testnet'te doğrulandı → BINANCE_ALGO_EMIR_SEMASI.md

    ⚠️ `exchangeInfo` GÜVENİLMEZ: STOP_MARKET'i hâlâ "destekleniyor" diye
      beyan ediyor. v56'daki kontrol buna bakıyordu ve bu yüzden yanıltıcıydı
      — "destekliyor" diyordu ama emir gönderilince reddediliyordu.

    Artık ALGO endpoint'inin gerçekten erişilebilir olduğu kontrol edilir.
    Emir GÖNDERİLMEZ (gerçek para riski olmasın diye); yalnızca açık algo
    emirleri sorgulanır — 200 dönerse yol açık demektir.
    """
    try:
        from data.binance_futures_client import _futures_istek
        sonuc = _futures_istek("GET", "/fapi/v1/openAlgoOrders", {})
        if isinstance(sonuc, list):
            return PreflightSonuc(
                "Koşullu emir", True,
                f"Algo Service erişilebilir ({len(sonuc)} açık koşullu emir)")
        return PreflightSonuc(
            "Koşullu emir", False,
            "Algo Service beklenmeyen yanıt döndü — stop-loss konulamayabilir",
            kritik=False)
    except Exception as e:
        # Erişilemiyorsa bu KRİTİK değil ama görünür olmalı: SL konulamazsa
        # bot pozisyonu hemen kapatır (zarar riski yok, işlem açılamaz).
        return PreflightSonuc(
            "Koşullu emir", False,
            f"Algo Service erişilemedi ({type(e).__name__}) — stop-loss "
            f"konulamayabilir, bot işlem açamaz",
            kritik=False)


def preflight_calistir(sessiz: bool = False) -> bool:
    """
    Tüm başlangıç kontrollerini çalıştırır.
    Döner: True = başlatılabilir, False = kritik hata var.
    """
    sonuclar = []
    sonuclar.append(_kontrol_python_surum())
    sonuclar.append(_kontrol_paketler())
    sonuclar.append(_kontrol_opsiyonel_paketler())
    sonuclar.extend(_kontrol_config())
    sonuclar.append(_kontrol_dosya_sistemi())
    sonuclar.append(_kontrol_veritabani())      # v55
    sonuclar.append(_kontrol_binance_baglanti())
    sonuclar.append(_kontrol_islem_boyutu())    # v56
    sonuclar.append(_kontrol_kosullu_emir())    # v56

    if not sessiz:
        print("\n" + "=" * 56)
        print("  ASTRA BAŞLANGIÇ SAĞLIK KONTROLÜ (PREFLIGHT)")
        print("=" * 56)
        for s in sonuclar:
            if s.gecti:
                ikon = "✅"
            elif s.kritik:
                ikon = "❌"
            else:
                ikon = "⚠️"
            print(f"  {ikon} {s.ad:<22} {s.mesaj}")
        print("=" * 56)

    kritik_hatalar = [s for s in sonuclar if not s.gecti and s.kritik]
    if kritik_hatalar:
        if not sessiz:
            print(f"\n  🛑 {len(kritik_hatalar)} KRİTİK HATA — bot başlatılamıyor:")
            for s in kritik_hatalar:
                print(f"     • {s.ad}: {s.mesaj}")
            print()
        log.critical(f"Preflight {len(kritik_hatalar)} kritik hata ile başarısız")
        return False

    uyarilar = [s for s in sonuclar if not s.gecti and not s.kritik]
    if not sessiz:
        if uyarilar:
            print(f"\n  ⚠️ {len(uyarilar)} uyarı var ama bot çalışabilir.\n")
        else:
            print("\n  ✅ Tüm kontroller geçti — bot sağlıklı.\n")
    return True
