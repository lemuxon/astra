# =========================================================
# ASTRA v30.0 — BINANCE FUTURES CLIENT
# Tam exception taksonomisi — broad except yok
# =========================================================
import logging, time, hmac, hashlib, math, threading, uuid
from urllib.parse import urlencode
from typing import Optional, Tuple
import requests, pandas as pd
import sys; sys.path.append("..")
from config import (BINANCE_API_KEY, BINANCE_API_SECRET, IS_TESTNET,
                    FUTURES_BASE_URL, FUTURES_LEVERAGE, FUTURES_MARGIN_TYPE,
                    FILL_VERIFY_TIMEOUT, FILL_VERIFY_INTERVAL,
                    MAX_SLIPPAGE_PCT, SLIPPAGE_WARN_PCT)
from utils.exceptions import (
    FuturesAPIError, FatalExchangeError, RetryableExchangeError,
    InsufficientBalanceError, InvalidOrderError, OrderNotFoundError,
    RateLimitError, NetworkError, TimeoutError as AstraTimeoutError,
    ConnectionError as AstraConnectionError,
    exchange_hata_siniflandir, http_hata_siniflandir,
    SlippageExceededError, StopLossFailedError
)

# FuturesAPIError artık utils.exceptions'dan import ediliyor (FatalExchangeError alias)

log = logging.getLogger("ASTRA.FUTURES")
MAX_RETRIES = 3; RETRY_DELAY = 1.5; REQUEST_TIMEOUT = 12
_exchange_info_cache: dict = {}
_leverage_set_cache:  set  = set()
_son_emirler: dict = {}
DUPLICATE_WINDOW_SEC = 60

# v37: Binance sunucu saati ile yerel saat farkı (offset) — VDS saati
# kayarsa -1021 "Timestamp ahead" hatasını önler.
_zaman_offset_ms = 0
_zaman_offset_guncel = 0.0
_zaman_offset_lock = threading.Lock()

def _sunucu_zaman_senkronize():
    """Binance sunucu saati ile yerel saat farkını hesapla.
    5 dakikada bir veya offset hiç hesaplanmadıysa güncellenir."""
    global _zaman_offset_ms, _zaman_offset_guncel
    with _zaman_offset_lock:
        if time.time() - _zaman_offset_guncel < 300 and _zaman_offset_guncel > 0:
            return _zaman_offset_ms
    try:
        # v58 (K-63): YEREL SAAT, GİDİŞ-DÖNÜŞÜN ORTASINDAN OKUNUR.
        # Eskiden `yerel_ms` istek DÖNDÜKTEN SONRA okunuyordu; serverTime
        # ise isteği işlerken (≈ t0 + RTT/2) damgalanır. Fark:
        #     offset = (t0 + RTT/2) − (t0 + RTT) = −RTT/2
        # ÖLÇÜLDÜ (2026-09-06): RTT≈300ms, bot offset'i −125..−167ms
        # hesaplıyordu; bağımsız orta-nokta ölçümü ise +25ms verdi.
        # Yani sağlıklı bir saatte SİSTEMATİK ~150ms hata üretiliyordu.
        _t0 = time.time()
        r = requests.get(f"{FUTURES_BASE_URL}/fapi/v1/time", timeout=5)
        _t1 = time.time()
        r.raise_for_status()
        sunucu_ms = int(r.json()["serverTime"])
        yerel_ms  = int((_t0 + _t1) / 2 * 1000)
        with _zaman_offset_lock:
            _zaman_offset_ms = sunucu_ms - yerel_ms
            _zaman_offset_guncel = time.time()
        if abs(_zaman_offset_ms) > 500:
            log.warning(f"[FUTURES] Saat farkı düzeltildi: {_zaman_offset_ms}ms "
                        f"(VDS saati {'geri' if _zaman_offset_ms>0 else 'ileri'})")
        return _zaman_offset_ms
    except Exception as e:
        log.debug(f"[FUTURES] Zaman senkronizasyonu başarısız: {e}")
        return _zaman_offset_ms

def _futures_istek_sorgu(orijinal_path: str, sembol: str, client_order_id: str,
                          algo: bool = False):
    """v53: Çift emir koruması tetiklendiğinde, ilk emrin gerçek durumunu
    borsadan sorgular. Böylece 'emir gitti mi?' belirsizliği ortadan kalkar.

    v57: `algo=True` ise koşullu emir (Algo Service) sorgulanır —
    farklı endpoint ve farklı parametre adı kullanır:
        klasik : GET /fapi/v1/order      origClientOrderId=...
        algo   : GET /fapi/v1/algoOrder  clientAlgoId=...
    Bu ayrım yapılmazsa algo emri "bulunamadı" görünür ve çift emir
    koruması sessizce işlevsiz kalır.

    ÖNEMLİ: Bu fonksiyon retry döngüsüne girmez (sonsuz döngü olmasın diye),
    tek seferlik doğrudan sorgu yapar."""
    if not sembol or not client_order_id:
        return None
    try:
        p = {
            "symbol": sembol,
            "timestamp": int(time.time() * 1000) + _sunucu_zaman_senkronize(),
            "recvWindow": 10000,
        }
        if algo:
            p["clientAlgoId"] = client_order_id
            yol = "/fapi/v1/algoOrder"
        else:
            p["origClientOrderId"] = client_order_id
            yol = "/fapi/v1/order"
        q = urlencode(p)
        p["signature"] = hmac.new(BINANCE_API_SECRET.encode(), q.encode(),
                                   hashlib.sha256).hexdigest()
        r = requests.get(f"{FUTURES_BASE_URL}{yol}",
                         params=p, headers={"X-MBX-APIKEY": BINANCE_API_KEY},
                         timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            sonuc = r.json()
            if algo:
                log.info(f"[FUTURES] Algo emir durumu doğrulandı: {sembol} "
                         f"algoId={sonuc.get('algoId')} "
                         f"status={sonuc.get('algoStatus')}")
            else:
                log.info(f"[FUTURES] Emir durumu doğrulandı: {sembol} "
                         f"orderId={sonuc.get('orderId')} status={sonuc.get('status')} "
                         f"dolan={sonuc.get('executedQty')}")
            return sonuc
    except Exception as e:
        log.error(f"[FUTURES] Emir durum sorgusu hatası: {e}")
    return None


def _futures_istek(method: str, path: str, params: dict = None) -> Optional[dict]:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise FatalExchangeError(-1, "API key/secret eksik", path)

    params = params or {}

    # ── v53 KRİTİK: ÇİFT EMİR ÖNLEME (idempotency) ──
    # SORUN: Retry döngüsü POST isteklerinde de çalışıyordu. Senaryo:
    #   1) POST emir gönderilir → Binance emri ALIR ve işler
    #   2) Yanıt dönerken timeout olur (ağ koptu)
    #   3) Kod timeout yakalar → emri TEKRAR gönderir
    #   4) İKİ pozisyon açılır; sistem sadece birini bilir (hayalet pozisyon)
    # duplicate_kontrol() emir gönderilmeden ÖNCE çalıştığı için bu
    # senaryoyu yakalayamıyordu.
    #
    # ÇÖZÜM: Binance'in newClientOrderId parametresi. Aynı ID ile ikinci
    # istek gelirse borsa "duplicate" hatası döner → emir İKİ KEZ İŞLENMEZ.
    # ID retry döngüsünden ÖNCE üretilir, tüm denemelerde AYNI kalır.
    # v57: ALGO endpoint'i AYRI ele alınmalı.
    #   Koşullu emirler (STOP_MARKET/TAKE_PROFIT_MARKET/TRAILING_STOP_MARKET)
    #   /fapi/v1/algoOrder'a taşındı (bkz. BINANCE_ALGO_EMIR_SEMASI.md).
    #   `"/order" in "/fapi/v1/algoOrder"` FALSE döner (alt dize yok), yani
    #   yukarıdaki v53 idempotency koruması algo emirlerinde SESSİZCE
    #   DEVRE DIŞI kalıyordu → ağ timeout'u + retry İKİ stop-loss koyabilirdi.
    #   Algo API'sinin karşılığı `clientAlgoId`; testnet'te doğrulandı:
    #   aynı id ile ikinci istek -4116 "ClientOrderId is duplicated" döner.
    _algo_endpointi = (method.upper() == "POST" and "/algoOrder" in path)
    _emir_endpointi = (method.upper() == "POST" and "/order" in path)
    if _algo_endpointi and "clientAlgoId" not in params:
        params["clientAlgoId"] = f"astra{uuid.uuid4().hex[:24]}"
    elif _emir_endpointi and "newClientOrderId" not in params:
        # Binance kuralı: ^[\.A-Z\:/a-z0-9_-]{1,36}$
        params["newClientOrderId"] = f"astra{uuid.uuid4().hex[:24]}"

    # v37: Sunucu saatine göre düzeltilmiş timestamp + geniş recvWindow.
    def _zamanla_ve_imzala():
        """timestamp + recvWindow + signature'ı TAZE üret.

        ── v58 (K-63): BAYAT TIMESTAMP → SAHTE "-1021 SAAT HATASI" ──
        Eskiden imza döngüden ÖNCE bir kez üretiliyordu. Ama denemeler
        ARASINDA uyunuyor: 429/418'de 10-300 sn, geçici hatada üstel
        geri çekilme. Uykudan sonra AYNI timestamp gönderiliyordu;
        Binance `serverTime - timestamp >= recvWindow` (10 sn) görüp
        -1021 döndürüyordu.

        ÖLÇÜLEN ZİNCİR (2026-09-06 15:55, logs/astra.log):
            15:55:45  429 rate limit → 15 sn bekleniyor
            15:56:01  -1021 "outside of recvWindow"   ← 15 sn sonra
        Bugün 87 rate-limit, 25 -1021; -1021'lerin 25/25'i dakikanın
        :00/:01 saniyesinde — yani 429 uykusunun bittiği an.

        ➜ Saat kayması DEĞİLDİ: bağımsız ölçümde yerel saat Binance'ten
        yalnızca +25 ms sapıyor. `w32tm /resync` bu hatayı çözmezdi.
        Not: newClientOrderId/clientAlgoId DEĞİŞMEZ (çift emir koruması
        ona dayanır) — yalnızca zaman ve imza tazelenir.
        """
        params.pop("signature", None)
        _offset = _sunucu_zaman_senkronize()
        params["timestamp"]  = int(time.time() * 1000) + _offset
        params["recvWindow"] = 10000
        params["signature"] = hmac.new(
            BINANCE_API_SECRET.encode(),
            urlencode(params).encode(), hashlib.sha256).hexdigest()

    _zamanla_ve_imzala()
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    url     = f"{FUTURES_BASE_URL}{path}"

    son_hata: Optional[Exception] = None

    for deneme in range(MAX_RETRIES):
        # İlk deneme yukarıda imzalandı; sonrakiler uykudan sonra gelir.
        if deneme:
            _zamanla_ve_imzala()
        try:
            if method.upper() == "GET":
                r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            elif method.upper() == "DELETE":
                r = requests.delete(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            else:
                r = requests.post(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)

            if r.status_code != 200:
                try:
                    hata = r.json()
                except ValueError:
                    hata = {}

                kod = hata.get("code", r.status_code)
                msg = hata.get("msg", r.text[:300])

                # ── v55: RATE LIMIT / IP BAN — Retry-After'a SAYGI GÖSTER ──
                # Eskiden 429/418 ve Binance'in -1003 kodu hiç özel işlenmiyordu;
                # exchange_hata_siniflandir() bunları sıradan RetryableExchangeError
                # yapıyor, aşağıdaki RateLimitError dalı ise ULAŞILAMAZ kalıyordu.
                # Sonuç: IP ban süresine uyulmadan tekrar denenip ban UZATILABİLİYORDU.
                if r.status_code in (429, 418) or kod == -1003:
                    try:
                        bekle = float(r.headers.get("Retry-After", 0) or 0)
                    except (TypeError, ValueError):
                        bekle = 0.0
                    if bekle <= 0:
                        # 418 = IP ban (uzun), 429 = rate limit (kısa)
                        bekle = 60.0 if r.status_code == 418 else 10.0
                    bekle = min(bekle, 300.0)   # üst sınır: tek beklemede 5 dk
                    log.warning(f"[FUTURES] 🚦 Rate limit/IP ban "
                                f"(HTTP {r.status_code}, kod={kod}) → {bekle:.0f}s bekleniyor")
                    son_hata = RateLimitError(f"Rate limit: {path}", int(bekle))
                    if deneme < MAX_RETRIES - 1:
                        time.sleep(bekle)
                        continue
                    raise son_hata

                # ── v53: Idempotency koruması devrede ──
                # -4015 / "duplicate" = aynı newClientOrderId ile ikinci istek.
                # Bu bir HATA DEĞİL, korumanın çalıştığının kanıtıdır: ilk emir
                # borsaya ULAŞMIŞ demektir. Retry'ı durdur ve emrin gerçek
                # durumunu borsadan sorgula — böylece çift pozisyon açılmaz.
                # v57: -4116 = algo endpoint'inin duplicate kodu.
                if (_emir_endpointi or _algo_endpointi) and (
                        "duplicate" in str(msg).lower()
                        or kod in (-4015, -2010, -4116)):
                    log.warning(f"[FUTURES] ✅ Çift emir koruması devrede "
                                f"(kod={kod}): ilk emir borsaya ulaşmış. "
                                f"Tekrar gönderilmiyor, durum sorgulanıyor.")
                    _cid = (params.get("clientAlgoId") if _algo_endpointi
                            else params.get("newClientOrderId"))
                    if _cid:
                        try:
                            _mevcut = _futures_istek_sorgu(
                                path, params.get("symbol"), _cid,
                                algo=_algo_endpointi)
                            if _mevcut:
                                return _mevcut
                        except Exception as _se:
                            log.error(f"[FUTURES] Emir durumu sorgulanamadı: {_se}")
                    raise FatalExchangeError(
                        kod, "Emir zaten gönderilmiş (çift emir engellendi)", path)

                # v37: -1021 (timestamp) hatası → offset'i ZORLA yenile + timestamp düzelt + tekrar dene
                if kod == -1021 and deneme < MAX_RETRIES - 1:
                    global _zaman_offset_guncel
                    with _zaman_offset_lock:
                        _zaman_offset_guncel = 0.0   # cache'i geçersiz kıl
                    time.sleep(0.3)
                    # v58 (K-63): İmzalama döngünün BAŞINDA yapılıyor —
                    # burada tekrarlanmaz. Cache geçersiz kılındığı için
                    # bir sonraki tur offset'i sunucudan yeniden sorar.
                    log.warning(f"[FUTURES] -1021 → offset cache'i geçersiz "
                                f"kılındı, taze timestamp ile tekrar deneniyor")
                    continue

                exc = exchange_hata_siniflandir(kod, msg, path)
                if not exc.retryable:
                    log.error(f"[FUTURES] Fatal hata {kod} ({path}): {msg}")
                    raise exc

                if isinstance(exc, RateLimitError):
                    log.warning(f"[FUTURES] Rate limit — {exc.bekleme_suresi}s bekleniyor")
                    time.sleep(exc.bekleme_suresi)
                    continue

                log.warning(f"[FUTURES] Geçici hata {kod} ({path}): {msg} "
                             f"(deneme {deneme+1}/{MAX_RETRIES})")
                son_hata = exc
                time.sleep(RETRY_DELAY * (2 ** deneme))
                continue

            return r.json()

        except requests.exceptions.Timeout as e:
            son_hata = AstraTimeoutError(f"Timeout: {path}", "BinanceHTTP")
            log.warning(f"[FUTURES] {son_hata} (deneme {deneme+1}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY * (2 ** deneme))

        except requests.exceptions.ConnectionError as e:
            son_hata = AstraConnectionError(f"Bağlantı hatası: {path} — {e}", "BinanceHTTP")
            log.error(f"[FUTURES] {son_hata}")
            time.sleep(RETRY_DELAY * (2 ** deneme))

        except (FatalExchangeError, RetryableExchangeError):
            raise   # Zaten sınıflandırıldı

        except requests.exceptions.RequestException as e:
            son_hata = NetworkError(f"İstek hatası: {e}", "BinanceHTTP")
            log.error(f"[FUTURES] {son_hata}")
            time.sleep(RETRY_DELAY * (2 ** deneme))

    log.error(f"[FUTURES] {path} — {MAX_RETRIES} denemede başarısız. Son hata: {son_hata}")
    if son_hata:
        raise son_hata
    raise NetworkError(f"{path} erişilemiyor", "BinanceHTTP")


def futures_sembol_filtre(sembol: str) -> dict:
    if sembol in _exchange_info_cache:
        return _exchange_info_cache[sembol]
    try:
        r = requests.get(f"{FUTURES_BASE_URL}/fapi/v1/exchangeInfo", timeout=10)
        r.raise_for_status()
        bilgi = r.json()
    except requests.exceptions.RequestException as e:
        log.error(f"[FUTURES] exchangeInfo alınamadı: {e}")
        return {}

    for s in bilgi.get("symbols", []):
        if s["symbol"] == sembol.upper():
            f = {}
            for fil in s.get("filters", []):
                if fil["filterType"] == "LOT_SIZE":
                    f["step_size"] = float(fil["stepSize"])
                    f["min_qty"]   = float(fil["minQty"])
                    f["qty_prec"]  = s.get("quantityPrecision", 3)
                elif fil["filterType"] == "PRICE_FILTER":
                    f["tick_size"] = float(fil["tickSize"])
                    f["prc_prec"]  = s.get("pricePrecision", 2)
                elif fil["filterType"] == "MIN_NOTIONAL":
                    f["min_notional"] = float(fil.get("notional", 5.0))
            _exchange_info_cache[sembol] = f
            return f
    return {}


def miktar_duzelt_futures(sembol: str, miktar: float) -> float:
    f = futures_sembol_filtre(sembol)
    step = f.get("step_size", 0.001); prec = f.get("qty_prec", 3)
    if step <= 0: return round(miktar, prec)
    return round(math.floor(miktar / step) * step, prec)


def fiyat_duzelt_futures(sembol: str, fiyat: float) -> float:
    f = futures_sembol_filtre(sembol)
    tick = f.get("tick_size", 0.01); prec = f.get("prc_prec", 2)
    if tick <= 0: return round(fiyat, prec)
    return round(round(fiyat / tick) * tick, prec)


def kaldirac_ayarla(sembol: str, kaldirac: int = None) -> bool:
    cache_key = f"{sembol}_{kaldirac}"
    if cache_key in _leverage_set_cache:
        return True
    kaldirac = kaldirac or FUTURES_LEVERAGE
    try:
        _futures_istek("POST", "/fapi/v1/marginType",
                       {"symbol": sembol.upper(), "marginType": FUTURES_MARGIN_TYPE.upper()})
    except FatalExchangeError as e:
        if e.kod != -4046:
            log.warning(f"[FUTURES] marginType hatası {sembol}: {e}")
    except (NetworkError, RetryableExchangeError) as e:
        log.warning(f"[FUTURES] marginType geçici hata {sembol}: {e}")

    try:
        sonuc = _futures_istek("POST", "/fapi/v1/leverage",
                               {"symbol": sembol.upper(), "leverage": kaldirac})
        if sonuc and "leverage" in sonuc:
            log.info(f"[FUTURES] {sembol} kaldıraç: {sonuc['leverage']}x")
            _leverage_set_cache.add(cache_key)
            return True
        return False
    except FatalExchangeError as e:
        log.error(f"[FUTURES] Kaldıraç fatal hata {sembol}: {e}")
        return False
    except (NetworkError, RetryableExchangeError) as e:
        log.warning(f"[FUTURES] Kaldıraç geçici hata {sembol}: {e}")
        return False


_son_bilinen_bakiye = [None]   # v39: ağ hatasında 0.0 yerine son bilineni kullan

def futures_bakiye(strict: bool = False) -> float:
    """Futures USDT bakiyesini döner.

    v56 GÜVENLİK NOTU — `strict` parametresi (bkz. acik_futures_pozisyonlar):
      strict=False (varsayılan): hata durumunda son bilinen bakiye, o da
        yoksa 0.0 döner. Raporlama/gösterim için uygundur.
      strict=True: hata durumunda istisnayı YÜKSELTİR.

    "Bakiye 0" ile "bakiyeyi sorgulayamadım" AYNI ŞEY DEĞİLDİR. Bu ayrım
    olmadan bir kimlik doğrulama hatası (-2015) veya ağ kesintisi, çağırana
    "hesabında para yok" gibi görünür — teşhisi tamamen yanlış yöne saptırır.
    Kurulum doğrulaması ve teşhis akışları strict=True kullanmalıdır.
    """
    try:
        sonuc = _futures_istek("GET", "/fapi/v3/balance")
        if isinstance(sonuc, list):
            for v in sonuc:
                if v.get("asset") == "USDT":
                    bakiye = float(v.get("availableBalance", 0))
                    _son_bilinen_bakiye[0] = bakiye   # başarılı → cache güncelle
                    return bakiye
        # USDT kaydı yoksa: gerçekten 0 bakiye demektir
        if strict:
            return 0.0
        return _son_bilinen_bakiye[0] if _son_bilinen_bakiye[0] is not None else 0.0
    except FatalExchangeError as e:
        log.error(f"[FUTURES] Bakiye fatal hata: {e}")
        if strict:
            raise
        # v39: Fatal hatada bile son bilinen bakiyeyi dön (0 dönmek risk hesabını bozar)
        if _son_bilinen_bakiye[0] is not None:
            log.warning(f"[FUTURES] Son bilinen bakiye kullanılıyor: {_son_bilinen_bakiye[0]:.2f}")
            return _son_bilinen_bakiye[0]
        return 0.0
    except (NetworkError, RetryableExchangeError) as e:
        log.warning(f"[FUTURES] Bakiye geçici hata: {e}")
        if strict:
            raise
        # v39: Geçici hatada son bilinen bakiyeyi dön — bot "bakiyem 0" sanmasın
        if _son_bilinen_bakiye[0] is not None:
            return _son_bilinen_bakiye[0]
        return 0.0


def acik_futures_pozisyonlar(strict: bool = False) -> list:
    """Açık futures pozisyonlarını döner.

    v55 GÜVENLİK NOTU — `strict` parametresi:
      strict=False (varsayılan): hata durumunda [] döner. Yalnızca RAPORLAMA /
        gösterim amaçlı çağrılar için uygundur.
      strict=True: hata durumunda [] DÖNMEZ, istisnayı YÜKSELTİR.

    "Sıfır pozisyon var" ile "sorgulayamadım" aynı şey DEĞİLDİR. Bu ayrımı
    yapmayan çağrılar sessizce fail-open olur:
      - duplicate_guard  → çift pozisyon açılmasına izin verir
      - fill_reconciler / position_state → ağ kesintisinde TÜM açık
        pozisyonları "kapandı" sanıp izlemeyi bırakır (pozisyonlar borsada
        canlı ve korumasız kalır)
    Güvenlik-kritik her çağrı strict=True kullanmalıdır.
    """
    try:
        sonuc = _futures_istek("GET", "/fapi/v3/positionRisk")
        if not isinstance(sonuc, list):
            log.warning("[FUTURES] positionRisk beklenmedik yanıt")
            if strict:
                raise RetryableExchangeError(
                    0, "positionRisk beklenmedik yanıt tipi", "/fapi/v3/positionRisk")
            return []
        return [
            {"sembol":   p["symbol"],
             "miktar":   float(p["positionAmt"]),
             "giris":    float(p["entryPrice"]),
             "pnl":      float(p["unRealizedProfit"]),
             "yon":      "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
             "kaldirac": int(p.get("leverage", FUTURES_LEVERAGE) or FUTURES_LEVERAGE),
             # v55: Borsanın KENDİ likidasyon fiyatı. Elle hesaplanan
             # giris*(1-1/kaldirac) yaklaşımı kademeli maintenance-margin
             # oranlarını yok sayıyor; mümkün olan her yerde bu kullanılmalı.
             "likidasyon_fiyat": float(p.get("liquidationPrice", 0) or 0)}
            for p in sonuc if float(p["positionAmt"]) != 0
        ]
    except (FatalExchangeError, RetryableExchangeError, NetworkError) as e:
        log.error(f"[FUTURES] Pozisyon listesi hatası: {e}")
        if strict:
            raise
        return []


def pozisyon_var_mi(sembol: str, yon: str = None) -> bool:
    for p in acik_futures_pozisyonlar():
        if p["sembol"] == sembol.upper():
            if yon is None or yon == p["yon"]:
                return True
    return False


def acik_futures_emirler(sembol: str = None) -> list:
    params = {}
    if sembol: params["symbol"] = sembol.upper()
    try:
        sonuc = _futures_istek("GET", "/fapi/v1/openOrders", params)
        return sonuc if isinstance(sonuc, list) else []
    except (FatalExchangeError, RetryableExchangeError, NetworkError) as e:
        log.error(f"[FUTURES] Açık emirler hatası: {e}")
        return []


def futures_emir_iptal(sembol: str, order_id: int) -> Optional[dict]:
    try:
        return _futures_istek("DELETE", "/fapi/v1/order",
                              {"symbol": sembol.upper(), "orderId": order_id})
    except (FatalExchangeError, RetryableExchangeError, NetworkError) as e:
        log.error(f"[FUTURES] Emir iptal hatası #{order_id}: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════
# v57: ALGO (KOŞULLU) EMİRLER
#
# Koşullu emirler /fapi/v1/order'dan Algo Service'e taşındı. Eski endpoint
# `-4120: "Please use the Algo Order API endpoints instead."` döndürüyor.
# Şema testnet'te deneyerek çıkarıldı → BINANCE_ALGO_EMIR_SEMASI.md
#
# ⚠️ EN KRİTİK: Algo emirleri klasik `GET /fapi/v1/openOrders` listesinde
# GÖRÜNMEZ. SL/TP varlığı kontrol edilen HER yerde bu fonksiyon da
# sorgulanmalı; yalnızca klasik listeye bakmak "SL yok" sonucunu
# SESSİZCE üretir.
# ═════════════════════════════════════════════════════════════════════

def acik_algo_emirler(sembol: str = None, strict: bool = False) -> list:
    """Açık koşullu (algo) emirleri döndür.

    Args:
        strict: True ise sorgu başarısız olduğunda İSTİSNA yükseltir.

    `strict` NEDEN VAR (DEVAM_NOTLARI §5.1 fail-open deseni):
        Hata durumunda `[]` dönmek "koşullu emir yok" anlamına gelir.
        Güvenlik-kritik çağrılar için bu YIKICI: geçici bir ağ hatası
        `order_reconciler`'a "bu pozisyonun SL'i yok" dedirtir ve pozisyon
        gereksiz yere kapatılır — ya da tersi, eski SL iptal edilemediği
        için üst üste SL birikir.

        "Sorgulayamadım" ile "emir yok" AYRI şeylerdir.
        SL doğrulaması yapan her çağrı strict=True kullanmalıdır.
    """
    params = {}
    if sembol:
        params["symbol"] = sembol.upper()
    try:
        sonuc = _futures_istek("GET", "/fapi/v1/openAlgoOrders", params)
        return sonuc if isinstance(sonuc, list) else []
    except (FatalExchangeError, RetryableExchangeError, NetworkError) as e:
        log.error(f"[FUTURES] Açık algo emirleri alınamadı: {e}")
        if strict:
            raise
        return []


def algo_emir_iptal(sembol: str, algo_id) -> Optional[dict]:
    """Tek bir koşullu emri iptal et (algoId ile — orderId DEĞİL)."""
    try:
        return _futures_istek("DELETE", "/fapi/v1/algoOrder",
                              {"symbol": sembol.upper(), "algoId": algo_id})
    except (FatalExchangeError, RetryableExchangeError, NetworkError) as e:
        log.error(f"[FUTURES] Algo emir iptal hatası #{algo_id}: {e}")
        return None


def koruma_emirleri(sembol: str = None, strict: bool = False) -> list:
    """Pozisyonu koruyan TÜM açık emirleri döndür — klasik + algo BİRLİKTE.

    NEDEN VAR: v57'de koşullu emirler Algo Service'e taşındı ve klasik
    `GET /fapi/v1/openOrders` listesinde ARTIK GÖRÜNMÜYORLAR. "SL var mı?"
    kontrolü yapan kod yalnızca klasik listeye bakarsa SL'i göremez ve
    "koruma yok" sonucuna varır — her turda gereksiz acil SL koyar, ya da
    pozisyonu korumasız sanıp kapatır.

    Bu fonksiyon iki kaynağı birleştirir ve algo kayıtlarını klasik biçime
    NORMALİZE eder; böylece mevcut `e.get("type")` kullanan kod çalışmaya
    devam eder:
        algo `orderType` → `type`
        algo `algoId`    → `orderId` (ayrıca `_algo=True` işareti konur)

    İptal ederken `_algo` bayrağına bakın: True ise `algo_emir_iptal()`,
    False ise `futures_emir_iptal()` kullanılmalıdır.

    Args:
        strict: True ise HERHANGİ bir sorgu başarısız olursa istisna yükselir.
                SL doğrulaması yapan çağrılar bunu kullanmalıdır —
                "sorgulayamadım" ile "emir yok" karıştırılmamalıdır.
    """
    birlesik = []

    # 1) Klasik emirler (LIMIT/MARKET tabanlı koruma, eski kalıntılar)
    try:
        for e in _futures_istek("GET", "/fapi/v1/openOrders",
                                {"symbol": sembol.upper()} if sembol else {}) or []:
            e = dict(e)
            e["_algo"] = False
            birlesik.append(e)
    except (FatalExchangeError, RetryableExchangeError, NetworkError) as e:
        log.error(f"[FUTURES] Klasik açık emirler alınamadı: {e}")
        if strict:
            raise

    # 2) Algo (koşullu) emirler — SL/TP buradadır
    for a in acik_algo_emirler(sembol, strict=strict):
        a = dict(a)
        a["type"]    = a.get("orderType")
        a["orderId"] = a.get("algoId")
        a["_algo"]   = True
        birlesik.append(a)

    return birlesik


def _algo_eskiyi_iptal(sembol: str, tipler: tuple, side: str) -> None:
    """Aynı yön+tipteki eski koşullu emirleri iptal et.

    Yeni SL/TP koymadan ÖNCE çağrılır. Eskiden bu iş `acik_futures_emirler()`
    ile yapılıyordu ama algo emirleri o listede görünmediği için eski emir
    HİÇ İPTAL EDİLMİYORDU → aynı pozisyona birden fazla SL birikirdi.

    strict=True: listeyi alamıyorsak "eski emir yok" VARSAYAMAYIZ.
    """
    for e in acik_algo_emirler(sembol, strict=True):
        if e.get("orderType") in tipler and e.get("side") == side:
            aid = e.get("algoId")
            log.info(f"[ALGO] {sembol} eski {e.get('orderType')} iptal ediliyor "
                     f"(algoId={aid})")
            algo_emir_iptal(sembol, aid)


def sembol_tum_emirleri_iptal(sembol: str) -> Optional[dict]:
    try:
        return _futures_istek("DELETE", "/fapi/v1/allOpenOrders",
                              {"symbol": sembol.upper()})
    except (FatalExchangeError, RetryableExchangeError, NetworkError) as e:
        log.error(f"[FUTURES] Toplu iptal hatası {sembol}: {e}")
        return None


def duplicate_kontrol(sembol: str, yon: str) -> bool:
    if pozisyon_var_mi(sembol, yon):
        log.warning(f"[DUPLICATE] {sembol} {yon} açık pozisyon var")
        return True
    son = _son_emirler.get(sembol)
    if son and son["yon"] == yon:
        if time.time() - son["zaman"] < DUPLICATE_WINDOW_SEC:
            log.warning(f"[DUPLICATE] {sembol} {yon} cooldown aktif")
            return True
    return False


def _emir_kaydet(sembol: str, yon: str):
    _son_emirler[sembol] = {"yon": yon, "zaman": time.time()}


def emir_durum_sorgula(sembol: str, order_id: int) -> Optional[dict]:
    try:
        return _futures_istek("GET", "/fapi/v1/order",
                              {"symbol": sembol.upper(), "orderId": order_id})
    except (FatalExchangeError, RetryableExchangeError, NetworkError) as e:
        log.error(f"[FILL VERIFY] Emir sorgu hatası #{order_id}: {e}")
        return None


def fill_verify(sembol: str, order_id: int,
                beklenen_miktar: float) -> Tuple[bool, dict]:
    from utils.exceptions import FillTimeoutError
    bitis = time.time() + FILL_VERIFY_TIMEOUT
    while time.time() < bitis:
        emir = emir_durum_sorgula(sembol, order_id)
        if emir is None:
            time.sleep(FILL_VERIFY_INTERVAL); continue

        durum        = emir.get("status", "")
        dolan_miktar = float(emir.get("executedQty", 0))
        avg_fiyat    = float(emir.get("avgPrice", 0))

        if durum == "FILLED":
            return True, emir
        elif durum == "PARTIALLY_FILLED":
            dolan_pct = dolan_miktar / beklenen_miktar * 100 if beklenen_miktar > 0 else 0
            if dolan_pct >= 80:
                try: futures_emir_iptal(sembol, order_id)
                except (FatalExchangeError, NetworkError): pass
                return True, emir
            time.sleep(FILL_VERIFY_INTERVAL)
        elif durum in ("CANCELED", "REJECTED", "EXPIRED"):
            log.error(f"[FILL VERIFY] #{order_id} {durum}")
            return False, emir
        else:
            time.sleep(FILL_VERIFY_INTERVAL)

    log.error(f"[FILL VERIFY] #{order_id} timeout ({FILL_VERIFY_TIMEOUT}s)")
    return False, {}


def slippage_kontrol(beklenen: float, gercek: float, sembol: str, yon: str) -> bool:
    if beklenen <= 0 or gercek <= 0: return True
    fark_pct = abs(gercek - beklenen) / beklenen * 100
    if yon == "LONG" and gercek > beklenen * (1 + MAX_SLIPPAGE_PCT/100):
        raise SlippageExceededError(sembol, beklenen, gercek, fark_pct)
    if yon == "SHORT" and gercek < beklenen * (1 - MAX_SLIPPAGE_PCT/100):
        raise SlippageExceededError(sembol, beklenen, gercek, fark_pct)
    if fark_pct > SLIPPAGE_WARN_PCT:
        log.warning(f"[SLIPPAGE] {sembol} yüksek: %{fark_pct:.3f}")
    return True


def futures_market_ac(sembol: str, yon: str, usdt_miktar: float,
                       _ic_slice: bool = False) -> Optional[dict]:
    """
    _ic_slice=True: Smart execution (TWAP/VWAP) dilimi.
    Duplicate kontrolü + cooldown atlanır (üst katman zaten kontrol etti).
    Açık pozisyon olsa bile dilim eklenir (aynı yönde biriktirme).
    """
    sembol = sembol.upper(); yon = yon.upper()
    if not _ic_slice and duplicate_kontrol(sembol, yon):
        return None

    fiyat = futures_anlık_fiyat(sembol)
    if not fiyat or fiyat <= 0:
        raise NetworkError(f"{sembol} anlık fiyat alınamadı")

    miktar = miktar_duzelt_futures(sembol, usdt_miktar / fiyat)
    filtre = futures_sembol_filtre(sembol)
    if miktar * fiyat < filtre.get("min_notional", 5.0):
        # v23: Dilim min_notional altındaysa sessizce atla (uyarı sadece tam emirde)
        if not _ic_slice:
            log.warning(f"[FUTURES] {sembol} notional küçük")
        else:
            log.debug(f"[FUTURES] {sembol} dilim notional küçük — atlandı")
        return None

    bakiye = futures_bakiye()
    if bakiye < (miktar * fiyat) / max(FUTURES_LEVERAGE, 1):
        raise InsufficientBalanceError(-2010, f"{sembol} yetersiz bakiye", "/fapi/v1/order")

    side   = "BUY" if yon == "LONG" else "SELL"
    params = {"symbol": sembol, "side": side, "type": "MARKET",
              "quantity": miktar, "positionSide": "BOTH"}
    sonuc  = _futures_istek("POST", "/fapi/v1/order", params)

    if not sonuc or not sonuc.get("orderId"):
        raise RetryableExchangeError(0, f"{sembol} geçersiz emir yanıtı", "/fapi/v1/order")

    order_id = sonuc["orderId"]
    # v23: Dilim emirlerinde cooldown kaydı yapma (sonraki dilimi bloklamasın)
    if not _ic_slice:
        _emir_kaydet(sembol, yon)

    basarili, emir_detay = fill_verify(sembol, order_id, miktar)
    if not basarili:
        from utils.exceptions import FillTimeoutError
        raise FillTimeoutError(order_id, sembol, FILL_VERIFY_TIMEOUT)

    gercek_fiyat = float(emir_detay.get("avgPrice", 0))
    if gercek_fiyat > 0:
        slippage_kontrol(fiyat, gercek_fiyat, sembol, yon)

    log.info(f"[FUTURES] ✅ {sembol} {yon} @ {gercek_fiyat:.4f}"
             f"{' (dilim)' if _ic_slice else ''}")
    return emir_detay


def futures_market_kapat(sembol: str, yon: str) -> Optional[dict]:
    sembol = sembol.upper(); yon = yon.upper()
    pozlar = acik_futures_pozisyonlar()
    hedef  = next((p for p in pozlar if p["sembol"]==sembol and p["yon"]==yon), None)
    if not hedef:
        log.warning(f"[FUTURES] {sembol} {yon} kapatılacak pozisyon yok")
        return None

    miktar = miktar_duzelt_futures(sembol, abs(hedef["miktar"]))
    sembol_tum_emirleri_iptal(sembol)
    side   = "SELL" if yon=="LONG" else "BUY"
    params = {"symbol":sembol,"side":side,"type":"MARKET",
              "quantity":miktar,"positionSide":"BOTH","reduceOnly":"true"}
    sonuc  = _futures_istek("POST", "/fapi/v1/order", params)
    if sonuc and sonuc.get("orderId"):
        log.info(f"[FUTURES] ✅ {sembol} {yon} kapatıldı")
    return sonuc


def futures_stop_loss_koy(sembol: str, yon: str, stop_fiyat: float) -> Optional[dict]:
    """Stop-loss koy — v57: Algo Service üzerinden.

    Eski `/fapi/v1/order` yolu `-4120` ile reddediliyor (koşullu emirler
    Algo Service'e taşındı). Şema: BINANCE_ALGO_EMIR_SEMASI.md
      • `algoType=CONDITIONAL` eklendi   • `stopPrice` → `triggerPrice`
      • yanıtta `orderId` → `algoId`
    """
    sembol = sembol.upper(); yon = yon.upper()
    stop_fiyat = fiyat_duzelt_futures(sembol, stop_fiyat)
    side = "SELL" if yon=="LONG" else "BUY"
    _algo_eskiyi_iptal(sembol, ("STOP_MARKET","STOP"), side)
    params = {"symbol":sembol,"side":side,
              "algoType":"CONDITIONAL","type":"STOP_MARKET",
              "triggerPrice":stop_fiyat,"positionSide":"BOTH",
              "closePosition":"true","workingType":"MARK_PRICE","priceProtect":"true"}
    sonuc = _futures_istek("POST", "/fapi/v1/algoOrder", params)
    if not sonuc or not sonuc.get("algoId"):
        raise StopLossFailedError(sembol, stop_fiyat)
    log.info(f"[SL] ✅ {sembol} {yon} @ {stop_fiyat} (algoId={sonuc['algoId']})")
    return sonuc


def futures_partial_tp_koy(sembol: str, yon: str, tp_fiyat: float,
                             pct: float=50) -> Optional[dict]:
    sembol=sembol.upper(); yon=yon.upper()
    tp_fiyat=fiyat_duzelt_futures(sembol,tp_fiyat)
    pozlar=acik_futures_pozisyonlar()
    poz=next((p for p in pozlar if p["sembol"]==sembol and p["yon"]==yon),None)
    if not poz: return None
    toplam=abs(poz["miktar"])
    kapatilacak=miktar_duzelt_futures(sembol,toplam*pct/100)
    filtre=futures_sembol_filtre(sembol)
    if kapatilacak < filtre.get("min_qty",0.001):
        kapatilacak=miktar_duzelt_futures(sembol,toplam)
    side="SELL" if yon=="LONG" else "BUY"
    # v57: Algo Service (bkz. futures_stop_loss_koy açıklaması)
    _algo_eskiyi_iptal(sembol, ("TAKE_PROFIT_MARKET","TAKE_PROFIT"), side)
    params={"symbol":sembol,"side":side,
            "algoType":"CONDITIONAL","type":"TAKE_PROFIT_MARKET",
            "triggerPrice":tp_fiyat,"quantity":kapatilacak,"positionSide":"BOTH",
            "reduceOnly":"true","workingType":"MARK_PRICE","priceProtect":"true"}
    sonuc=_futures_istek("POST","/fapi/v1/algoOrder",params)
    if sonuc and sonuc.get("algoId"):
        log.info(f"[TP] ✅ {sembol} {yon} partial @ {tp_fiyat} (algoId={sonuc['algoId']})")
    return sonuc


def futures_take_profit_koy(sembol: str, yon: str, tp_fiyat: float) -> Optional[dict]:
    sembol=sembol.upper(); yon=yon.upper()
    tp_fiyat=fiyat_duzelt_futures(sembol,tp_fiyat)
    side="SELL" if yon=="LONG" else "BUY"
    # v57: Algo Service (bkz. futures_stop_loss_koy açıklaması)
    _algo_eskiyi_iptal(sembol, ("TAKE_PROFIT_MARKET","TAKE_PROFIT"), side)
    params={"symbol":sembol,"side":side,
            "algoType":"CONDITIONAL","type":"TAKE_PROFIT_MARKET",
            "triggerPrice":tp_fiyat,"positionSide":"BOTH",
            "closePosition":"true","workingType":"MARK_PRICE","priceProtect":"true"}
    sonuc=_futures_istek("POST","/fapi/v1/algoOrder",params)
    if sonuc and sonuc.get("algoId"):
        log.info(f"[TP] ✅ {sembol} {yon} @ {tp_fiyat} (algoId={sonuc['algoId']})")
    return sonuc


def futures_trailing_stop_koy(sembol: str, yon: str, callback_oran: float=1.5) -> Optional[dict]:
    sembol=sembol.upper()
    side="SELL" if yon=="LONG" else "BUY"
    # v57: Algo Service. İKİ fark var, ikisi de testnet'te doğrulandı:
    #   1) TRAILING_STOP_MARKET'te triggerPrice YOK — callbackRate kullanılır
    #      (yanıtta triggerPrice=0.00 döner).
    #   2) `closePosition=true` REDDEDİLİYOR:
    #        -4136 "Target strategy invalid for orderType
    #               TRAILING_STOP_MARKET,closePosition true"
    #      Bunun yerine açık pozisyonun miktarı `quantity` olarak verilmeli.
    #      Klasik endpoint closePosition'ı kabul ediyordu; naif taşıma
    #      trailing stop'u SESSİZCE ÖLDÜRÜRDÜ (her çağrı hata döner,
    #      üst katman `None` görüp devam eder → koruma yok sanılmaz,
    #      HİÇ KOYULMAZ).
    _algo_eskiyi_iptal(sembol, ("TRAILING_STOP_MARKET",), side)

    poz = next((p for p in acik_futures_pozisyonlar()
                if p["sembol"] == sembol and p["yon"] == yon), None)
    if not poz:
        log.warning(f"[TRAILING] {sembol} {yon}: açık pozisyon yok — "
                    f"trailing stop koyulmadı")
        return None
    miktar = miktar_duzelt_futures(sembol, abs(poz["miktar"]))
    if miktar <= 0:
        log.warning(f"[TRAILING] {sembol} miktar 0'a yuvarlandı — atlandı")
        return None

    params={"symbol":sembol,"side":side,
            "algoType":"CONDITIONAL","type":"TRAILING_STOP_MARKET",
            "callbackRate":round(callback_oran,1),"positionSide":"BOTH",
            "quantity":miktar,"reduceOnly":"true","workingType":"MARK_PRICE"}
    sonuc=_futures_istek("POST","/fapi/v1/algoOrder",params)
    if sonuc and sonuc.get("algoId"):
        log.info(f"[TRAILING] ✅ {sembol} {yon} %{callback_oran} "
                 f"miktar={miktar} (algoId={sonuc['algoId']})")
    return sonuc


def futures_veri_indir(sembol: str, interval: str="1h", limit: int=500) -> Optional[pd.DataFrame]:
    url=f"{FUTURES_BASE_URL}/fapi/v1/klines"
    params={"symbol":sembol.upper(),"interval":interval,"limit":min(limit,1500)}
    for deneme in range(MAX_RETRIES):
        try:
            r=requests.get(url,params=params,timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            veri=r.json()
            if not veri: return None
            df=pd.DataFrame(veri,columns=["open_time","Open","High","Low","Close","Volume",
                                           "close_time","quote_vol","num_trades",
                                           "taker_buy_base","taker_buy_quote","ignore"])
            df["open_time"]=pd.to_datetime(df["open_time"],unit="ms",utc=True)
            df.set_index("open_time",inplace=True); df.index.name=None
            for col in ["Open","High","Low","Close","Volume","taker_buy_base"]:
                df[col]=pd.to_numeric(df[col],errors="coerce")
            return df[["Open","High","Low","Close","Volume","taker_buy_base"]].dropna(
                subset=["Open","High","Low","Close","Volume"])
        except requests.exceptions.Timeout:
            log.warning(f"[FUTURES] Klines timeout {sembol} deneme {deneme+1}")
            time.sleep(RETRY_DELAY)
        except requests.exceptions.ConnectionError as e:
            log.error(f"[FUTURES] Klines bağlantı hatası {sembol}: {e}")
            time.sleep(RETRY_DELAY)
        except requests.exceptions.RequestException as e:
            log.error(f"[FUTURES] Klines istek hatası {sembol}: {e}")
            time.sleep(RETRY_DELAY)
    return None


def futures_funding_rate(sembol: str) -> float:
    try:
        r=requests.get(f"{FUTURES_BASE_URL}/fapi/v1/premiumIndex",
                       params={"symbol":sembol.upper()},timeout=5)
        r.raise_for_status()
        return float(r.json().get("lastFundingRate",0))
    except requests.exceptions.RequestException as e:
        log.warning(f"[FUTURES] Funding rate hatası {sembol}: {e}")
        return 0.0


def futures_open_interest(sembol: str) -> float:
    try:
        r=requests.get(f"{FUTURES_BASE_URL}/fapi/v1/openInterest",
                       params={"symbol":sembol.upper()},timeout=5)
        r.raise_for_status()
        return float(r.json().get("openInterest",0))
    except requests.exceptions.RequestException as e:
        log.warning(f"[FUTURES] OI hatası {sembol}: {e}")
        return 0.0


def futures_oi_gecmis(sembol: str, period: str="5m", limit: int=50) -> pd.DataFrame:
    # v43: Testnet openInterestHist'i desteklemiyor (boş yanıt → JSON hatası).
    # Testnet'te boş DataFrame dön, gereksiz hata logu + ağ yükünü önle.
    if IS_TESTNET:   # v48: modül seviyesine taşındı
        return pd.DataFrame()
    try:
        r=requests.get(f"{FUTURES_BASE_URL}/futures/data/openInterestHist",
                       params={"symbol":sembol.upper(),"period":period,"limit":limit},timeout=8)
        r.raise_for_status()
        data=r.json()
        if not data: return pd.DataFrame()
        df=pd.DataFrame(data)
        df["timestamp"]=pd.to_datetime(df["timestamp"],unit="ms",utc=True)
        df["sumOpenInterest"]=pd.to_numeric(df["sumOpenInterest"])
        df["sumOpenInterestValue"]=pd.to_numeric(df["sumOpenInterestValue"])
        return df.set_index("timestamp")
    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        # v43: ValueError = JSON parse hatası (boş yanıt) da yakalanır
        log.debug(f"[FUTURES] OI geçmiş alınamadı {sembol}: {e}")
        return pd.DataFrame()


def futures_long_short_ratio(sembol: str, period: str="5m", limit: int=20) -> float:
    # v35: Testnet bu endpoint'i desteklemiyor (boş yanıt → JSON hatası).
    # Testnet'te nötr 1.0 dön, gereksiz hata logunu önle.
    if IS_TESTNET:   # v48: modül seviyesine taşındı
        return 1.0
    try:
        r=requests.get(f"{FUTURES_BASE_URL}/futures/data/topLongShortPositionRatio",
                       params={"symbol":sembol.upper(),"period":period,"limit":limit},timeout=8)
        r.raise_for_status()
        data=r.json()
        if data: return float(data[-1].get("longShortRatio",1.0))
    except (requests.exceptions.RequestException, ValueError, KeyError, IndexError) as e:
        # v35: ValueError = JSON parse hatası (boş yanıt) da yakalanır
        log.debug(f"[FUTURES] L/S ratio alınamadı {sembol}: {e}")
    return 1.0


def futures_anlık_fiyat(sembol: str) -> Optional[float]:
    try:
        r=requests.get(f"{FUTURES_BASE_URL}/fapi/v1/ticker/price",
                       params={"symbol":sembol.upper()},timeout=5)
        r.raise_for_status()
        return float(r.json()["price"])
    except requests.exceptions.RequestException as e:
        log.warning(f"[FUTURES] Anlık fiyat hatası {sembol}: {e}")
        return None
