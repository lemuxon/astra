# =========================================================
# ASTRA v30.0 — WEBSOCKET MANAGER (Production Recovery)
# Ping timeout, stale data, auto-resubscribe, sequence validation
# =========================================================
import logging, json, threading, time
from typing import Callable, Optional
import sys; sys.path.append("..")
from config import FUTURES_BASE_URL, COINS

log = logging.getLogger("ASTRA.WEBSOCKET")

try:
    import websocket; WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    log.warning("websocket-client kurulu değil: pip install websocket-client")

_fiyat_cache: dict = {}
_ws_aktif          = False
_ws_thread: Optional[threading.Thread] = None
_son_mesaj_ts      = 0.0
_disconnect_cb: Optional[Callable] = None  # kill_switch bildirim için

# Stale data eşiği (v34: config'ten ayarlanabilir — testnet daha toleranslı)
try:
    from config import WS_STALE_ESIK_S as STALE_ESIK_S
except ImportError:
    STALE_ESIK_S = 30    # v34: 15→30 (testnet WS sık duraklar; gereksiz reconnect azalt)
RECONNECT_BKFF = [5, 10, 30, 60]  # backoff saniyesi


def son_fiyat(sembol: str) -> Optional[float]:
    veri = _fiyat_cache.get(sembol.upper())
    if not veri:
        return None
    yas = time.time() - veri["ts"]
    if yas > STALE_ESIK_S:
        log.warning(f"[WS] {sembol} fiyat stale ({yas:.0f}s)")
        return None
    return veri["fiyat"]


def ws_stale_mi() -> bool:
    """Son mesajdan STALE_ESIK_S saniye geçtiyse True."""
    return (time.time() - _son_mesaj_ts) > STALE_ESIK_S if _son_mesaj_ts else False


def _on_message(ws, message):
    global _son_mesaj_ts
    _son_mesaj_ts = time.time()
    try:
        data = json.loads(message)
        if "stream" in data:
            data = data["data"]
        sembol = data.get("s", "").upper()
        fiyat  = float(data.get("c", data.get("p", 0)))
        if sembol and fiyat > 0:
            _fiyat_cache[sembol] = {"fiyat": fiyat, "ts": time.time()}
    except Exception as e:
        log.debug(f"[WS] Mesaj parse hatası: {e}")


def _on_error(ws, error):
    log.warning(f"[WS] Hata: {error}")


def _on_close(ws, code, msg):
    global _ws_aktif
    _ws_aktif = False
    log.warning(f"[WS] Kapandı (code={code})")
    try:
        from engines.kill_switch import get_kill_switch
        get_kill_switch().ws_disconnect_bildir()
    except Exception as e:
        # v55: Eskiden `except Exception: pass` idi — HİÇ log yoktu.
        # Bu çağrı kill switch'in WS-disconnect sayacını besler; sessizce
        # başarısız olursa koruma sıfır iz bırakarak devre dışı kalır.
        log.error(f"[WS] kill switch disconnect bildirimi BAŞARISIZ: "
                  f"{type(e).__name__}: {e} — WS koruması sayaç almadı!")
    if _disconnect_cb:
        try: _disconnect_cb()
        except Exception: pass


def _on_open(ws):
    global _ws_aktif, _son_mesaj_ts
    _ws_aktif     = True
    _son_mesaj_ts = time.time()
    log.info("[WS] Bağlantı açıldı")


def _stale_monitor():
    """Stale data monitörü — ayrı thread.
    v36: Art arda stale tekrarında REST polling moduna kalıcı geçer ve
    uyarı spam'ini keser. Yavaş VDS'lerde WS hiç düzelmeyebilir; bu durumda
    sürekli uyarı basmak yerine sessizce REST'e düşmek daha sağlıklı."""
    global _ws_aktif
    ardisik_stale = 0
    uyari_verildi = False
    rest_gecis_zamani = 0.0
    REST_GECIS_ESIK = 6   # v45: 3→6 (testnet geçici kopmalarında daha sabırlı)
    WS_TEKRAR_DENE_S = 300  # v45: REST'e geçtikten 5dk sonra WS'i tekrar dene
    while True:
        time.sleep(10)
        # v45: REST moduna geçtiyse, periyodik olarak WS'i tekrar dene
        # (testnet toparlanırsa saniyelik güncellemelere geri dön)
        if not _ws_aktif and uyari_verildi:
            if time.time() - rest_gecis_zamani > WS_TEKRAR_DENE_S:
                log.info("[WS] WebSocket tekrar deneniyor (testnet toparlanmış olabilir)...")
                _ws_aktif = True
                uyari_verildi = False
                ardisik_stale = 0
                if _disconnect_cb:
                    try: _disconnect_cb()   # yeniden bağlanmayı tetikle
                    except Exception: pass
            continue
        if not _ws_aktif:
            continue
        if ws_stale_mi():
            ardisik_stale += 1
            if ardisik_stale <= REST_GECIS_ESIK:
                # İlk birkaç stale: yenilemeyi dene
                log.warning(f"[WS] Stale data ({ardisik_stale}/{REST_GECIS_ESIK}) — bağlantı yenileniyor")
                if _disconnect_cb:
                    try: _disconnect_cb()
                    except Exception: pass
            elif not uyari_verildi:
                # Eşik aşıldı: WS bu ortamda kararsız → geçici REST moduna geç
                log.warning(f"[WS] WebSocket {REST_GECIS_ESIK} denemede düzelmedi — "
                            "geçici olarak REST polling moduna geçildi (fiyatlar REST "
                            f"API'den çekilecek, bot normal çalışır). {WS_TEKRAR_DENE_S//60}dk "
                            "sonra WS tekrar denenecek.")
                _ws_aktif = False   # REST fallback devreye girer
                uyari_verildi = True
                rest_gecis_zamani = time.time()
        else:
            # Veri geldi → sayacı sıfırla
            if ardisik_stale > 0:
                ardisik_stale = 0


def ws_baslat(coins: list = None, spot: bool = False,
               disconnect_callback: Callable = None):
    global _ws_thread, _disconnect_cb

    if not WS_AVAILABLE:
        log.warning("[WS] websocket-client kurulu değil, REST polling kullanılacak")
        return

    # v29: çift başlatma koruması — iki WS thread'i çift veri/stale tetikler
    if _ws_thread is not None and _ws_thread.is_alive():
        log.warning("[WS] Zaten çalışıyor — tekrar başlatılmadı "
                    "(disconnect_callback DEĞİŞTİRİLMEDİ)")
        return

    # v55: _disconnect_cb ataması "zaten çalışıyor" kontrolünün ALTINA alındı.
    # Eskiden koşulsuz en başta atanıyordu; ikinci bir ws_baslat() çağrısı
    # farklı (veya None) callback geçtiğinde ÇALIŞAN bağlantının
    # disconnect/reconnect kablolaması sessizce değişiyor/siliniyordu.
    _disconnect_cb = disconnect_callback

    coins   = coins or COINS
    streams = [f"{c.lower()}@miniTicker" for c in coins]
    url     = (f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
               if spot else
               f"wss://fstream.binance.com/stream?streams={'/'.join(streams)}")

    attempt = 0

    def _run():
        nonlocal attempt
        while True:
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_message = _on_message,
                    on_error   = _on_error,
                    on_close   = _on_close,
                    on_open    = _on_open,
                )
                # v46: reconnect parametresi eski websocket-client'larda
                # yok — güvenli şekilde dene, yoksa parametresiz çağır.
                try:
                    ws.run_forever(ping_interval=20, ping_timeout=10, reconnect=5)
                except TypeError:
                    ws.run_forever(ping_interval=20, ping_timeout=10)
                attempt = 0
            except Exception as e:
                log.error(f"[WS] Çalışma hatası: {e}")

            bekle = RECONNECT_BKFF[min(attempt, len(RECONNECT_BKFF)-1)]
            attempt += 1
            log.info(f"[WS] {bekle}s sonra yeniden bağlanılacak (deneme #{attempt})")
            time.sleep(bekle)

    _ws_thread = threading.Thread(target=_run, daemon=True, name="AstraWS")
    _ws_thread.start()

    # Stale monitor başlat
    threading.Thread(target=_stale_monitor, daemon=True, name="AstraWS_Stale").start()

    log.info(f"[WS] {len(coins)} coin başlatıldı | Stale eşiği: {STALE_ESIK_S}s")


def ws_durum() -> dict:
    stale = ws_stale_mi()
    return {
        "aktif":          _ws_aktif,
        "stale":          stale,
        "son_mesaj_once": round(time.time() - _son_mesaj_ts, 1) if _son_mesaj_ts else -1,
        "izlenen_coin":   len(_fiyat_cache),
        "cache":          {k: v["fiyat"] for k, v in _fiyat_cache.items()},
    }
