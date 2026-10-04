# =========================================================
# ASTRA v30.0 — SIGNAL NODE
# Bağımsız çalışan sinyal üretim node'u.
# Execution node'dan ayrıdır — Redis queue üzerinden iletişim.
# python nodes/signal_node.py  → sadece analiz + sinyal üretir
# =========================================================
import sys, os, time, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime, timezone
from config import (COINS, SCAN_INTERVAL, BOT_TOKEN, CHAT_ID,
                    REDIS_ENABLED, REDIS_HOST, REDIS_PORT, REDIS_DB,
                    MODEL_RETRAIN_INTERVAL, LIVE_TRADING)
from engines.event_bus import get_bus, Event
from utils.exceptions import NetworkError, ModelError, InsufficientDataError

log = logging.getLogger("ASTRA.SIGNAL_NODE")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SIGNAL] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/signal_node.log", encoding="utf-8"),
    ]
)

# Redis veya memory queue
try:
    if REDIS_ENABLED:
        import redis
        _redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
                              decode_responses=True, socket_timeout=3)
        _redis.ping()
        QUEUE_BACKEND = "redis"
        log.info(f"[SIGNAL NODE] Redis queue: {REDIS_HOST}:{REDIS_PORT}")
    else:
        raise ImportError("Redis disabled")
except (ImportError, Exception):
    from queue import Queue
    _memory_queue: Queue = Queue(maxsize=500)
    QUEUE_BACKEND = "memory"
    log.info("[SIGNAL NODE] Memory queue kullanılıyor")


def sinyal_yayinla(sinyal: dict):
    """Sinyal üretildi → execution node'a gönder."""
    import json
    sinyal["ts"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    sinyal["kaynak"] = "signal_node"

    if QUEUE_BACKEND == "redis":
        try:
            _redis.lpush("astra:signals", json.dumps(sinyal, default=str))
            _redis.expire("astra:signals", 300)  # 5dk TTL
            log.debug(f"[QUEUE→Redis] {sinyal['sembol']} {sinyal.get('karar','?')}")
        except Exception as e:
            log.error(f"[QUEUE] Redis yayın hatası: {e} — memory'e fallback")
            _memory_queue.put(sinyal, block=False)
    else:
        try:
            _memory_queue.put_nowait(sinyal)
        except (AttributeError, KeyError, TypeError):
            log.warning("[QUEUE] Memory queue dolu, sinyal atlandı")

    get_bus().publish(Event.SIGNAL_GENERATED, sinyal, "SignalNode")


def coin_sinyal_uret(sembol: str) -> dict:
    """
    Tek coin için tam analiz — sadece sinyal üretir, emir vermez.
    """
    from data.binance_client import veri_indir, close_al
    from data.market_data import market_veri_topla
    from core.indicators import (
        hesapla_rsi, hesapla_macd, hesapla_bollinger, hesapla_atr,
        hesapla_adx, hesapla_supertrend, piyasa_rejimi_tespit,
        mtf_confluence_skoru,
    )
    from engines.model_engine import (
        en_iyi_model_yukle_veya_egit, feedback_veri_yukle)
    from strategy.edge_engine import EdgeEngine
    from sklearn.model_selection import train_test_split

    df = veri_indir(sembol, period="2d", interval="5m")
    if df is None:
        raise NetworkError(f"{sembol} veri alınamadı", "SignalNode")

    close = close_al(df)
    if close.empty or len(close) < 40:
        raise InsufficientDataError(f"{sembol} yetersiz veri ({len(close)} bar)")

    rsi         = hesapla_rsi(close)
    macd,sig,_  = hesapla_macd(close)
    ma,_,_      = hesapla_bollinger(close)
    atr         = hesapla_atr(df, sembol)
    adx,_,_     = hesapla_adx(df, sembol)

    try: _,st_dir = hesapla_supertrend(df, sembol)
    except (AttributeError, ValueError): st_dir = pd.Series(1, index=close.index)

    rejim      = piyasa_rejimi_tespit(close, df, sembol)
    mtf        = mtf_confluence_skoru(sembol, veri_indir)

    try: mkt_data = market_veri_topla(sembol)
    except NetworkError: mkt_data = {}

    # Model tahmin
    from main import feature_olustur, ai_score_hesapla, karar_ver
    X, y = feature_olustur(df, sembol)
    X, y = feedback_veri_yukle(sembol, X, y)
    yukselis = 50.0
    if not X.empty:
        model, acc, _, _ = en_iyi_model_yukle_veya_egit(X, y, sembol)
        if model is not None:
            _, X_te, _, _ = train_test_split(X, y, test_size=0.2, shuffle=False)
            try: yukselis = float(model.predict_proba(X_te)[-1][1] * 100)
            except (ValueError, AttributeError): pass

    ai_score = ai_score_hesapla(
        float(rsi.iloc[-1]) if not rsi.dropna().empty else 50,
        float(close.iloc[-1]),
        float(ma.iloc[-1]) if not ma.dropna().empty else float(close.iloc[-1]),
        float(macd.iloc[-1]) if not macd.dropna().empty else 0,
        float(sig.iloc[-1]) if not sig.dropna().empty else 0,
        yukselis,
        adx=float(adx.iloc[-1]) if not adx.dropna().empty else 20,
        rejim=rejim,
        market_data=mkt_data,
        mtf_skor=mtf.get("skor", 0),
        supertrend_dir=int(st_dir.iloc[-1]) if not st_dir.dropna().empty else 1,
    )

    # Edge Engine filtresi
    edge = EdgeEngine()
    edge_sonuc = edge.filtrele(
        ai_score=ai_score,
        rejim=rejim,
        mtf_skor=mtf.get("skor", 0),
        market_data=mkt_data,
        yukselis_guveni=yukselis,
        son_atr=float(atr.iloc[-1]) if not atr.dropna().empty else float(close.iloc[-1])*0.01,
        son_close=float(close.iloc[-1]),
    )

    return {
        "sembol":     sembol,
        "son_close":  float(close.iloc[-1]),
        "son_rsi":    float(rsi.iloc[-1]) if not rsi.dropna().empty else 50,
        "son_atr":    float(atr.iloc[-1]) if not atr.dropna().empty else float(close.iloc[-1])*0.01,
        "ai_score":   ai_score,
        "karar":      karar_ver(ai_score),
        "confidence": edge_sonuc["confidence"],
        "rejim":      rejim,
        "strateji":   edge_sonuc.get("strateji","TREND_FOLLOW"),
        "edge_score": edge_sonuc.get("edge_score", 0),
        "yukselis_guveni": yukselis,
        "mtf_confluence": mtf,
        "market_data": mkt_data,
        "edge_aktif":  edge_sonuc["gecti"],
        "edge_sebep":  edge_sonuc.get("sebep",""),
    }


def sinyal_node_calistir():
    """Signal node ana döngüsü."""
    os.makedirs("logs", exist_ok=True)
    from data.db_manager import tablolari_olustur
    tablolari_olustur()

    log.info(f"🟢 SIGNAL NODE başlatıldı — {len(COINS)} coin, {SCAN_INTERVAL}s")
    dongu = 0; son_egitim: dict = {}

    while True:
        dongu_baslangic = time.time()
        log.info(f"[DÖNGÜ] #{dongu} — {datetime.now().strftime('%H:%M:%S')}")

        for sembol in COINS:
            try:
                sinyal = coin_sinyal_uret(sembol)
                if sinyal.get("edge_aktif"):
                    sinyal_yayinla(sinyal)
                    log.info(f"[SİNYAL] {sembol} AI:{sinyal['ai_score']} "
                              f"Edge:{sinyal['edge_score']:.2f} {sinyal['karar']}")
                else:
                    log.debug(f"[FILTRE] {sembol}: {sinyal.get('edge_sebep','?')}")

            except NetworkError as e:
                log.warning(f"[DÖNGÜ] {sembol} ağ hatası: {e}")
            except InsufficientDataError as e:
                log.warning(f"[DÖNGÜ] {sembol} veri eksik: {e}")
            except ModelError as e:
                log.error(f"[DÖNGÜ] {sembol} model hatası: {e}")
            except (ImportError, AttributeError) as e:
                log.error(f"[DÖNGÜ] {sembol} import/attribute hatası: {e}")

        # Model yeniden eğitimi
        if dongu % 6 == 0:
            for sembol in COINS:
                if time.time() - son_egitim.get(sembol, 0) > MODEL_RETRAIN_INTERVAL:
                    try:
                        from data.binance_client import veri_indir, close_al
                        from engines.model_engine import en_iyi_model_yukle_veya_egit
                        from main import feature_olustur
                        df_r = veri_indir(sembol, period="14d", interval="1h")
                        if df_r is not None:
                            X_r, y_r = feature_olustur(df_r, sembol)
                            if not X_r.empty:
                                en_iyi_model_yukle_veya_egit(X_r, y_r, sembol,
                                                               yeniden_egit_suresi=0)
                                son_egitim[sembol] = time.time()
                    except (NetworkError, InsufficientDataError) as e:
                        log.warning(f"[RETRAIN] {sembol}: {e}")
                    except ModelError as e:
                        log.error(f"[RETRAIN] {sembol} model hatası: {e}")

        gecen = time.time() - dongu_baslangic
        bekleme = max(0, SCAN_INTERVAL - gecen)
        dongu += 1
        time.sleep(bekleme)


if __name__ == "__main__":
    sinyal_node_calistir()
