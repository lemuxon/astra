# =========================================================
# ASTRA AI TRADER v30.0 — PRODUCTION ANA GİRİŞ
# Kendi kendini eğiten, Binance Futures üzerinde aktif işlem yapan bot
# v17 düzeltmeleri & yenilikler:
#   • BUG FIX: yon değişkeni UnboundLocalError (correlation_eng bloğu)
#   • BUG FIX: _self_train_tetikle — feedback_ekle eksikti, model öğrenemiyordu
#   • BUG FIX: feedback_veri_yukle çift çağrısı (2x veri katlanması önlendi)
#   • BUG FIX: rl_reward_kaydet ceza çarpanı + ai_score tutarlılık bonusu
#   • YENİ: Adaptif öğrenme hızı — son N işlemin win_rate'ine göre retrain sıklığı
#   • YENİ: Feature drift dedektörü — dağılım kayması uyarısı ve otomatik yeniden eğitim
#   • YENİ: Ensemble model confidence kalibrasyon skoru
#   • YENİ: Per-coin öğrenme metrikleri Telegram raporu (/selflearn komutu güncellendi)
# =========================================================
import sys, os, time, logging, threading, asyncio
from datetime import datetime, timezone
from collections import deque   # v28: gecikme ölçümü
import pandas as pd, numpy as np
import requests
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split

from config import (MIN_AI_SCORE_BUY, MIN_AI_SCORE_SELL,
                    BOT_TOKEN, CHAT_ID, COINS, SCAN_INTERVAL, TIMEFRAMES,
                    BALANCE, RISK_PERCENT, MODEL_RETRAIN_INTERVAL, LIVE_TRADING,
                    ANA_PERIOD, ANA_INTERVAL,   # v58 K-29: ana işlem ufku
                    FUTURES_LEVERAGE, TRADE_USDT, WS_ENABLED, DASHBOARD_ENABLED, DASHBOARD_PORT,
                    PROMETHEUS_ENABLED, MC_SIMULATIONS, ASTRA_VERSION, ASTRA_SURUM_ETIKET,
                    # v55: Bu ikisi modül düzeyinde import EDİLMİYORDU.
                    # JOURNAL_DB_PATH yalnızca futures_dashboard() içinde yerel
                    # olarak import ediliyordu → _strateji_dayaniklilik_dogrula()
                    # her çağrıda NameError alıp log.debug'a düşüyor, strateji
                    # doğrulama kapısı hiç çalışmıyordu.
                    # LOOKBACK eksikliği de TFT tahminini tamamen devre dışı
                    # bırakıyordu (aynı şekilde sessizce).
                    JOURNAL_DB_PATH, LOOKBACK)
from data.database import tablolari_olustur as tablolari_olustur
from data.db_manager import (sinyal_kaydet, backtest_kaydet,
                             toplam_pnl, win_rate_hesapla, db_durum,
                             portfolio_state_kaydet)
from data.binance_client import (veri_indir, close_al, anlık_fiyat, bakiye_al)
from data.market_data import (market_veri_topla, hesapla_cvd,
                               likidasyon_isi_haritasi, order_book_depth_profil)
from core.indicators import (
    hesapla_cvd_delta, hesapla_cvd_momentum, hesapla_cvd_divergence,
    hesapla_rsi, hesapla_stoch_rsi, hesapla_williams_r, hesapla_cci,
    hesapla_macd, hesapla_bollinger, hesapla_bollinger_bandwidth,
    hesapla_vwap, hesapla_atr, hesapla_fibonacci, hesapla_ichimoku,
    hesapla_adx, hesapla_obv, hesapla_taker_buy_ratio,
    hesapla_supertrend, hesapla_pivot_points,
    mumlar_hesapla, piyasa_rejimi_tespit, mtf_confluence_skoru,
)
from engines.model_engine import (en_iyi_model_yukle_veya_egit, lstm_tahmin_yap,
                                   feedback_veri_yukle, rl_reward_kaydet, rl_ortalama_reward,
                                   feedback_ekle)
from engines.backtest_engine import backtest_calistir
from engines.paper_trading import PaperTrader
from engines.performance_tracker import PerformanceTracker
from engines.risk_manager import RiskManager
from engines.strategy_engine import StratejiEngine
from engines.futures_trade_engine import (
    futures_otomatik_isle, futures_pozisyon_izle, futures_pozisyon_kapat,
    risk_manager_set, strategy_engine_set, sl_tp_hesapla,
    sinyal_veto_zinciri,          # v58 K-97: paper ↔ canlı ortak veto zinciri
    coklu_borsa_gecerli_mi,       # v58 K-103: çoklu borsa kapısı da ortak
    _state_temizleyici_kaydol,
)
from engines.event_bus import get_bus, Event
from engines.order_engine import get_order_engine, OrderRequest
from engines.exchange_failover import get_failover
from engines.monte_carlo import get_mc
from engines.position_state import get_state_manager
from engines.watchdog import get_watchdog
from engines.walk_forward_advanced import purged_kfold_cv, expanding_window_cv
from monitoring.prometheus_metrics import get_metrics
from data.binance_futures_client import (acik_futures_pozisyonlar, futures_bakiye,
                                          futures_anlık_fiyat, pozisyon_var_mi,
                                          duplicate_kontrol, FuturesAPIError)

# ── v12: Advanced Analytics & Simulation ──────────────────
from analytics.risk_analytics import get_analytics, AdvancedRiskAnalytics
from analytics.portfolio_optimizer import get_portfolio_optimizer   # v20
from engines.ab_test             import get_ab_manager             # v21
from simulation.rl_environment   import rl_tahmin, rl_arka_plan_egitim  # v21
from engines.model_engine        import (tft_tahmin_yap, tft_egit_ve_kaydet)  # v21
from engines.model_registry      import get_model_registry            # v22
from engines.strategy_validator   import get_validator, StratejiKarari  # v24
from execution.smart_execution   import get_smart_executor            # v22
from data.onchain_data           import onchain_sentiment, durum_raporu as onchain_durum  # v22
from data.multi_exchange         import get_multiexchange                                 # v26
from simulation.exchange_simulator import get_simulator

# ── v12: EdgeEngine + RegimeAdapter ───────────────────────
from strategy.edge_engine import EdgeEngine
from strategy.regime_adapter import RegimeAdapter

# ── Execution Layer ────────────────────────────────────────
from execution.execution_engine import get_execution_engine
# ── v14: Yeni modüller ────────────────────────────────────
from engines.kill_switch     import get_kill_switch
from engines.online_learner  import (get_online_learner, online_durum_raporu,
                                     etiket_uret)  # v20, v58 K-64
# ── v16: Yeni modüller ────────────────────────────────────
from risk.volatility_circuit_breaker import get_circuit_breaker
from risk.correlation_engine  import get_correlation_engine
from engines.shadow_model     import get_shadow_manager
from engines.edge_analytics   import get_edge_analytics
from engines.trade_journal   import get_journal, TradeKayit
from engines.adaptive_sizing import get_adaptive_sizing
from engines.order_reconciler import get_order_reconciler
from core.market_regime      import get_regime_detector, get_hmm_detector
# FillReconciler → OrderReconciler ile birleştirildi (v15)
from execution.state_audit import get_audit
from execution.failsafe_liquidation import get_failsafe_guard

# ── Logging ───────────────────────────────────────────────
# v57: Log dizini env ile yonlendirilebilir. Sabit kodlu oldugu surece TEST
# kosulari da URETIM logina yaziyordu: logs/astra.log icinde sentetik fikstur
# fiyatlariyla (BTCUSDT @ 63018.9 gibi) sahte islem satirlari birikiyor,
# logu denetleyen biri bunlari gercek islem saniyordu. Veriyi bozmuyordu ama
# teshis kaydini guvenilmez yapiyordu (DEVAM_NOTLARI §4.6).
_LOG_DIR = os.getenv("ASTRA_LOG_DIR", "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
from logging.handlers import RotatingFileHandler as _RFH
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        _RFH(os.path.join(_LOG_DIR, "astra.log"), maxBytes=10*1024*1024,  # 10 MB
             backupCount=5, encoding="utf-8"),
    ],
)

# v57: KALICI TEŞHİS KAYDI — astra.log 4 SAATTE bir dönüyor.
#   Ölçüm (2026-08-25): analiz döngüsü ~10 MB/4 saat üretiyor (Optuna,
#   feedback, paralel tarama satırları). 5 yedekle toplam ~20 SAATLİK geçmiş
#   kalıyor. Oysa paper veri toplama ~7 HAFTA sürecek (ölçülen tempo:
#   12 saatte 1 pozisyon) ve bu oturumdaki teşhislerin TAMAMI log geçmişinden
#   yapıldı: 22 saatlik uyku, 2 günlük ölüm, SL dolum sapması, test kirliliği.
#   O kayıt kaybolursa "garip bir şey görürsen ciddiye al" (§10) uygulanamaz.
#
#   Çözüm: WARNING ve üstünü AYRI dosyada, yüksek saklama ile tut. Bu dosya
#   çok daha yavaş büyür (ölçüm: satırların ~%13'ü) → 20 MB × 10 yedek ile
#   haftalarca geçmiş saklar. İşlem açılış/kapanışları INFO seviyesinde
#   olduğu için ayrıca `data/astra.db` ve `journal.db` kalıcı kayıt tutar.
_onemli = _RFH(os.path.join(_LOG_DIR, "astra_onemli.log"),
               maxBytes=20*1024*1024, backupCount=10, encoding="utf-8")
_onemli.setLevel(logging.WARNING)
_onemli.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(_onemli)

# ── K-108: TOKEN LOG'A DÜŞMESİN ───────────────────────────────────────
# ÖLÇÜLDÜ (2026-10-06): Telegram token'ı 4 log dosyasına düz metin yazılmış
# bulundu, İKİ ayrı yoldan (telegram_gonderim.py'deki requests istisnası ve
# main.py:3456'daki InvalidToken + exc_info traceback'i).
# Tek tek yama yerine ÇIKTI ANINDA maskeleniyor: üçüncü bir sızma yolu
# olmadığını kanıtlayamam (§5.1). Ayrıntı: core/log_gizle.py
from core.log_gizle import kur as _gizlemeyi_kur
_gizlenen = _gizlemeyi_kur()
if not _gizlenen:
    logging.getLogger("ASTRA").critical(
        "[GUVENLIK] Log maskeleme KURULAMADI — token log'a sizabilir!")

log = logging.getLogger("ASTRA")

# ── v58 (K-40): TELEGRAM RAPOR/GRAFİK EŞİĞİ ────────────────────────
# Eskiden sabit 7 idi (grafik üretimi sabit 5). Sorun: skorun ulaşabildiği
# aralık ufka ve model katkısına bağlı, sabit sayı değil.
#   5m döneminde  |AI| >= 7 → sinyallerin %6.10'u  (çalışıyordu)
#   4h döneminde  |AI| >= 7 → %2.64                (seyrekleşti)
#   K-37 sonrası  gözlenen EN YÜKSEK |AI| = 4      (ASLA tetiklenmez)
# K-37 model güvenini nötrlediği için ai_score'un ±2'lik bileşeni gitti;
# eşik sessizce ULAŞILAMAZ hale geldi ve grafikler kesildi. Kullanıcı
# "bayadır resim atmıyor" diye bildirdi — log hiçbir şey söylemiyordu.
#
# Artık GİRİŞ eşiğiyle aynı kaynaktan: bot işlem açacak kadar güçlü
# bulduysa raporlar. Böylece ufuk/model değişse de eşik kendini korur.
# (K-29/K-30 dersi: zaman dilimine veya skor ölçeğine bağlı HER sabit,
#  ufuk değişince sessizce yanlış olur.)
_RAPOR_ESIGI = max(abs(MIN_AI_SCORE_BUY), abs(MIN_AI_SCORE_SELL))

# ── v58 (K-72): TELEGRAM BİLDİRİM KAPISI ────────────────────────
# `_RAPOR_ESIGI` GİRİŞ eşiğidir; rapor için kullanılması seli
# üretiyordu (bkz. config.py K-72 notu). Bildirim kendi eşiğine ve
# bar başına tekilleştirmeye tabi.
try:
    from config import (TG_MIN_AI_SINYAL, TG_MIN_CONF_SINYAL,
                        TG_BAR_BASINA_TEK)
except ImportError:
    TG_MIN_AI_SINYAL, TG_MIN_CONF_SINYAL, TG_BAR_BASINA_TEK = 5, 70, True

# ── v58 (K-73): BAR BAŞINA BİR AĞIR ANALİZ ──────────────────────
# `coin_analiz` pahalıdır: kline indirme + feature + model + market
# data + on-chain. 4h barda sonucu bar boyunca DEĞİŞMEZ (K-16), ama
# döngü 60 sn'de bir dönüyordu → bar başına 240 gereksiz analiz.
# Ayrıntı ve ölçümler config.py K-73 notunda.
try:
    from config import BAR_ONBELLEK, ANA_BAR_DK as _ANA_BAR_DK
except ImportError:
    BAR_ONBELLEK, _ANA_BAR_DK = True, 240

_analiz_onbellek: dict = {}        # sembol → (bar_indeksi, sonuc)
_analiz_onbellek_lock = threading.Lock()


def _tur_sirasi(coinler, dongu: int):
    """Coin sırasını her turda kaydır (v58 K-82).

    Tur tavanı aşılıp iptal edildiğinde listenin SONU hiç sıra
    alamıyordu — 50 coinde 11 coin kalıcı olarak analiz dışı kaldı.
    Kaydırma bunu yapısal olarak imkânsız kılar: iptal devam etse
    bile her coin birkaç tur içinde başa gelir.
    """
    if not coinler:
        return []
    k = dongu % len(coinler)
    return list(coinler[k:]) + list(coinler[:k])


def _bar_indeksi() -> int:
    """İçinde bulunulan bar penceresinin numarası (saatten türetilir).

    Kline indirmeye GEREK YOK: 4h barlar sabit UTC sınırlarında kapanır,
    bu yüzden bar kimliği saatten hesaplanabilir. Bar değişince indeks
    değişir ve önbellek kendiliğinden geçersizleşir.
    """
    return int(time.time() // max(60, _ANA_BAR_DK * 60))


def _analiz_al(sembol: str, **kw):
    """Ağır analizi bar başına BİR kez yap; ara turlarda fiyatı tazele.

    ⚠️ Tazelenen alan SADECE `anlik_fiyat`. SL/TP kontrolü
    (`stop_tp_kontrol`) ve geç-giriş iptali bu alandan besleniyor;
    onlar bar içinde de çalışmak ZORUNDA. Gösterge/karar alanları
    kapanmış bara ait olduğu için bilerek DONDURULUYOR — zaten
    değişmemeleri gerekiyordu (K-16).
    """
    if not BAR_ONBELLEK:
        return coin_analiz(sembol, **kw)

    simdiki = _bar_indeksi()
    with _analiz_onbellek_lock:
        kayit = _analiz_onbellek.get(sembol)
    if kayit and kayit[0] == simdiki and kayit[1]:
        sonuc = kayit[1]
        f = None
        try:
            f = guncel_fiyat_al(sembol)
        except Exception as e:
            log.debug(f"[BAR ÖNBELLEK] {sembol} fiyat tazelenemedi: {e}")
        if f and f > 0:
            sonuc["anlik_fiyat"] = f
        else:
            # §5.1: fiyatı doğrulayamıyorsak bayat fiyatla SL/TP
            # kontrolü yapmak yanlış tetikleme üretir — tam analize düş.
            log.warning(f"[BAR ÖNBELLEK] {sembol} anlık fiyat alınamadı "
                        f"→ tam analize düşülüyor")
            sonuc = coin_analiz(sembol, **kw)
            if sonuc:
                with _analiz_onbellek_lock:
                    _analiz_onbellek[sembol] = (simdiki, sonuc)
        return sonuc

    sonuc = coin_analiz(sembol, **kw)
    if sonuc:
        with _analiz_onbellek_lock:
            _analiz_onbellek[sembol] = (simdiki, sonuc)
    return sonuc


_tg_bildirilen: dict = {}          # sembol → (bar_ts, karar)
_tg_bildirilen_lock = threading.Lock()


def _tg_bildirilmeli(sonuc: dict) -> bool:
    """Bu sinyal Telegram'a GİTMELİ mi? (grafik dahil)

    Üç koşul:
      1. |AI| >= TG_MIN_AI_SINYAL     — "çok emin"
      2. güven >= TG_MIN_CONF_SINYAL
      3. bu (sembol, kapanmış bar) için daha önce gönderilmemiş
         VEYA kararı değişmiş (BUY→SELL gerçekten yeni bilgidir)

    4h ufkunda 3. koşul belirleyicidir: analiz sonucu bar boyunca
    sabit olduğu için tekilleştirme olmadan aynı sinyal ~48 kez gider.
    """
    ai   = abs(sonuc.get("ai_score", 0) or 0)
    conf = sonuc.get("confidence", 0) or 0
    if ai < TG_MIN_AI_SINYAL or conf < TG_MIN_CONF_SINYAL:
        return False
    if not TG_BAR_BASINA_TEK:
        return True

    sembol = sonuc.get("sembol", "?")
    # Bar kimliği: kapanmış barın kapanış fiyatı bar içinde SABİTTİR
    # (K-16). `sinyal_ts` kullanılamaz — her turda değişir.
    bar_kimlik = sonuc.get("son_close")
    karar      = sonuc.get("karar", "")
    with _tg_bildirilen_lock:
        onceki = _tg_bildirilen.get(sembol)
        if onceki == (bar_kimlik, karar):
            return False
        _tg_bildirilen[sembol] = (bar_kimlik, karar)
        if len(_tg_bildirilen) > 500:      # bellek koruması (50+ coin)
            for k in list(_tg_bildirilen)[:100]:
                _tg_bildirilen.pop(k, None)
    return True


def _sembol_normalize(ham: str, varsayilan: str = "BTCUSDT") -> str:
    """Telegram komut argümanını geçerli bir sembole çevirir.

    v58 (K-52): 11 komutta şu desen vardı:
        sembol = _sembol_normalize(c.args[0] if c.args else None)   # v58 K-52

    `/market BTC`     → BTCUSDT      ✓
    `/market BTCUSDT` → BTCUSDTUSDT  ✗   ← EN OLASI KULLANIM

    Bot her yerde sembolleri tam hâliyle gösteriyor (BTCUSDT), yani
    kullanıcının tam sembolü yazması BEKLENEN davranış — ve tam da o
    girdide bozuluyordu.

    Daha kötüsü SESSİZ: `market_veri_topla("BTCUSDTUSDT")` hata
    vermek yerine sıfır dolu bir sözlük döndürüyor (funding %0.0000,
    OI 0.00). Kullanıcı bunu gerçek veri sanar. §5.1 fail-open.
    """
    if not ham:
        return varsayilan
    t = str(ham).strip().upper().replace("/", "").replace("-", "")
    if not t:
        return varsayilan
    # Zaten bir teminat çiftiyle bitiyorsa dokunma
    for son in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD"):
        if t.endswith(son) and len(t) > len(son):
            return t
    return t + "USDT"

# v38 GÜVENLİK: httpx/telegram kütüphaneleri istek URL'lerini INFO seviyede
# logluyor — bu URL'lerde BOT_TOKEN açıkça görünüyor. Satılan üründe her
# müşterinin token'ı log dosyasına yazılırdı. WARNING'e çekerek token sızıntısını önle.
for _gurultu in ["httpx", "telegram", "telegram.ext", "telegram.bot", "urllib3"]:
    logging.getLogger(_gurultu).setLevel(logging.WARNING)

# v44 KÖK ÇÖZÜM: Global HTTP timeout. Hiçbir ağ çağrısı sonsuza kadar
# bekleyemez — takılan çağrı hangisi olursa olsun kesilir. Bu, "bot
# uzun süre çalışınca takılıyor/watchdog alarmı" sorununu kökten çözer.
try:
    from core.http_guard import global_timeout_uygula
    global_timeout_uygula(connect=8, read=15)
except Exception as _e:
    log.warning(f"[HTTP] Global timeout uygulanamadı: {_e}")

# v56: TELEGRAM_URL/TELEGRAM_PHOTO core/telegram_gonderim.py içinde

# ── Global Nesneler ───────────────────────────────────────
paper_trader    = PaperTrader(BALANCE)
risk_manager    = RiskManager(BALANCE)
strateji_engine = StratejiEngine()
edge_engine     = EdgeEngine()
regime_adapter  = RegimeAdapter()
bus             = get_bus()
order_engine    = get_order_engine()
failover        = get_failover()
mc_risk         = get_mc()
metrics         = get_metrics()
state_manager   = get_state_manager(auto_sync=False)  # v15: import güvenli

risk_manager_set(risk_manager)
strategy_engine_set(strateji_engine)
# v55: Chandelier/TP1 state'i POSITION_CLOSED event'inde temizlensin — pozisyon
# borsa tarafında (SL/TP/trailing dolumu) kapandığında da çalışması için şart.
_state_temizleyici_kaydol()
_strategy_engine = strateji_engine

# ── v12 nesneleri ─────────────────────────────────────────
analytics_engine   = get_analytics()
simulator          = get_simulator()
exec_engine        = get_execution_engine(risk_manager, state_manager)
portfolio_optimizer= get_portfolio_optimizer()   # v20: MVO
ab_manager         = get_ab_manager("Mevcut", "TFT+RL")  # v21: A/B test
model_registry     = get_model_registry()        # v22: model versiyonlama
smart_executor     = get_smart_executor()        # v22: TWAP/VWAP
multiexchange      = get_multiexchange()          # v26: çoklu borsa doğrulama
strateji_validator = get_validator()              # v24: dayanıklılık doğrulama
# v24: Per-coin strateji onay durumu. None=henüz test edilmedi, True=onaylı, False=red.
# Reddedilen coin'lerde yeni pozisyon AÇILMAZ (mevcutlar yönetilmeye devam eder).
_strateji_onay: dict = {}        # {sembol: bool}
_strateji_karar_cache: dict = {} # {sembol: StratejiKarari}
# reconciler (FillReconciler) kaldırıldı → order_reconciler kullanılıyor
reconciler_legacy = None  # geriye dönük uyumluluk için
state_audit      = get_audit()
failsafe_guard   = get_failsafe_guard()
# reconciler.start() → futures_dashboard() içinde başlatılıyor

watchdog = None
# v14 global nesneler (futures_dashboard'da init edilecek)
kill_switch      = None
circuit_breaker  = None
correlation_eng  = None
shadow_manager   = None
edge_analytics   = None
trade_journal    = None
adaptive_sizing  = None
order_reconciler = None
_heartbeat_basladi = False   # v55: heartbeat thread çift-başlatma koruması
regime_detector  = get_regime_detector()
hmm_detector     = get_hmm_detector()   # v19: HMM rejim

# ── Son analizlerden feature cache (self-training için) ───
_son_features_cache: dict = {}  # {sembol: {feature_dict}}

# ── v17: Adaptif Öğrenme Metrikleri ─────────────────────
_ogrenme_metrikleri: dict = {}  # {sembol: {"win":int,"loss":int,"son_retrain":float,"drift_uyari":bool}}
_portfolio_getiri_serileri: dict = {}  # v20: {sembol: pd.Series} MVO için getiri cache
_portfolio_son_fiyat: dict = {}        # v23: {sembol: float} son fiyat (getiri hesabı için)
_global_dongu_sayaci: int = 0          # v23: A/B varyant rotasyonu için global döngü sayacıloat,"drift_uyari":bool}}

def _ogrenme_metrik_guncelle(sembol: str, kazandi: bool):
    """Her kapanan işlem sonrası öğrenme metriklerini güncelle."""
    if sembol not in _ogrenme_metrikleri:
        _ogrenme_metrikleri[sembol] = {"win": 0, "loss": 0, "son_retrain": 0.0,
                                        "drift_uyari": False, "son_25": []}
    m = _ogrenme_metrikleri[sembol]
    m["win" if kazandi else "loss"] += 1
    m["son_25"].append(1 if kazandi else 0)
    if len(m["son_25"]) > 25:
        m["son_25"] = m["son_25"][-25:]

def _adaptif_retrain_gerekli_mi(sembol: str) -> tuple:
    """
    v17: Adaptif öğrenme hızı.
    Son 25 işlemin win rate'ine göre retrain eşiğini dinamik belirler.
    Düşük win rate → daha sık retrain.
    Returns: (gerekli_mi: bool, sebep: str)
    """
    m = _ogrenme_metrikleri.get(sembol)
    if not m or len(m["son_25"]) < 5:
        return False, "yetersiz veri"
    son25_wr = sum(m["son_25"]) / len(m["son_25"])
    simdi = time.time()
    gecen = simdi - m.get("son_retrain", 0)

    # Win rate bazlı dinamik retrain aralığı
    if son25_wr < 0.40:   # %40 altı win rate = çok kötü, 15dk'da bir retrain
        esik = 900
        sebep = f"kritik win rate {son25_wr:.0%} → acil retrain"
    elif son25_wr < 0.50:  # %50 altı = 30dk
        esik = 1800
        sebep = f"düşük win rate {son25_wr:.0%} → hızlı retrain"
    else:                  # Normal = 60dk (standart)
        esik = 3600
        sebep = f"normal win rate {son25_wr:.0%}"

    if gecen >= esik:
        m["son_retrain"] = simdi
        return True, sebep
    return False, f"son retrain {int(gecen/60)}dk önce"

_DRIFT_FEATURELARI = ("RSI", "MACD", "ATR_pct", "Volume_Ratio", "ADX")


def _drift_ayni_bar(onceki: dict, yeni: dict) -> bool:
    """v58 (K-43): İki feature satırı AYNI bardan mı geliyor?

    Ayrı fonksiyon: satır içinde olsaydı davranışsal olarak test
    edilemezdi (K-37'de tam bu tuzağa düşüldü).
    """
    for f in _DRIFT_FEATURELARI:
        a, b = onceki.get(f), yeni.get(f)
        if a is None or b is None:
            continue
        try:
            if abs(float(a) - float(b)) > max(abs(float(a)), 1e-12) * 1e-9:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _feature_drift_kontrol(sembol: str, yeni_features: dict) -> bool:
    """
    v17: Feature drift dedektörü.
    Son N cache'lenen feature'lar ile mevcut dağılımı karşılaştırır.
    Büyük sapma varsa True döner (retrain gerekli sinyali).
    """
    try:
        _drift_history = getattr(_feature_drift_kontrol, "_history", {})
        if sembol not in _drift_history:
            _drift_history[sembol] = []
        history = _drift_history[sembol]
        # ── v58 (K-43): AYNI BARI TEKRAR EKLEME ────────────────────
        # 4h'de bar 6 saatte bir kapanıyor ama analiz ~60 sn'de bir
        # çalışıyor. Aynı kapanmış barın feature'ları geçmişe defalarca
        # ekleniyordu → son 20 kayıt BİRBİRİNİN AYNISI → std ≈ 0 →
        # yeni bar geldiğinde z = değişim / 1e-15 = 10^15.
        # Ölçüm: 162 drift alarmının 53'ü (%33) z > 1000, en yüksek
        # 1.9e15. Bu alarmlar 165 gereksiz retrain tetikledi.
        # 5m'de bar 5 dakikada bir kapandığı için sorun görünmüyordu —
        # K-29/K-30 ile aynı sınıf: ufka bağlı sessiz varsayım.
        if history and _drift_ayni_bar(history[-1], yeni_features):
            return False          # yeni bilgi yok, drift kararı verilemez
        if len(history) < 20:
            history.append(yeni_features)
            _feature_drift_kontrol._history = _drift_history
            return False
        # RSI ve MACD gibi temel feature'lar için ortalama sapma kontrolü
        drift_skoru = 0.0
        kontrol_edilenler = list(_DRIFT_FEATURELARI)   # v58 K-43: tek kaynak
        karsilastirilan = 0
        for feat in kontrol_edilenler:
            gecmis_degerler = [h.get(feat) for h in history[-20:] if h.get(feat) is not None]
            mevcut = yeni_features.get(feat)
            if not gecmis_degerler or mevcut is None:
                continue
            ortalama = float(np.mean(gecmis_degerler))
            std = float(np.std(gecmis_degerler))
            # v58 (K-43): `or 1.0` YETMİYORDU — yalnızca std TAM 0 iken
            # devreye giriyordu. std=1e-15 gibi bir değer geçip bölmeyi
            # patlatıyordu. Ölçek-göreli eşik kullanıyoruz: feature
            # pratikte sabitse drift hakkında BİLGİ TAŞIMIYOR, o yüzden
            # 1.0 ile ikame etmek yerine ATLIYORUZ (ikame, sabit bir
            # feature'ı sahte drift kaynağına çevirirdi).
            olcek = max(abs(ortalama), 1e-9)
            if std < olcek * 1e-6:
                continue
            z_skor = abs((mevcut - ortalama) / std)
            drift_skoru += z_skor
            karsilastirilan += 1
        history.append(yeni_features)
        history[:] = history[-50:]  # Son 50'yi tut
        _feature_drift_kontrol._history = _drift_history
        if karsilastirilan == 0:
            return False
        ort_drift = drift_skoru / karsilastirilan
        if ort_drift > 2.5:  # 2.5 sigma sapma = drift uyarısı
            log.warning(f"[DRIFT/{sembol}] Feature drift tespit edildi! z={ort_drift:.2f}")
            if sembol in _ogrenme_metrikleri:
                _ogrenme_metrikleri[sembol]["drift_uyari"] = True
            return True
        return False
    except Exception as _e:
        log.debug(f"[DRIFT] {sembol} kontrol hatası: {_e}")
        return False


# ── Dashboard ─────────────────────────────────────────────
if DASHBOARD_ENABLED:
    try:
        from api.dashboard import dashboard_baslat, state_guncelle, pozisyon_kapandi_bildir
        dashboard_baslat()
    except Exception as e:
        log.warning(f"Dashboard başlatılamadı: {e}")
        def state_guncelle(**kwargs): pass
        def pozisyon_kapandi_bildir(*a,**kw): pass
else:
    def state_guncelle(**kwargs): pass
    def pozisyon_kapandi_bildir(*a,**kw): pass

# ── WebSocket ─────────────────────────────────────────────
_ws_fiyat_fn = None
if WS_ENABLED:
    try:
        from engines.websocket_manager import ws_baslat, son_fiyat
        ws_baslat(COINS, spot=False)
        _ws_fiyat_fn = son_fiyat
        metrics.ws_aktif.set(1)
    except Exception as e:
        log.warning(f"WebSocket başlatılamadı: {e}")

def guncel_fiyat_al(sembol: str) -> float:
    if _ws_fiyat_fn:
        f = _ws_fiyat_fn(sembol)
        if f: return f
    f = futures_anlık_fiyat(sembol)
    if f: return f
    return anlık_fiyat(sembol) or 0.0

# v56 MODÜLERLEŞTİRME: feature_olustur / ai_score_hesapla / karar_ver /
# risk_hesapla core/sinyal_skor.py'ye taşındı, buradan yeniden dışa verilir.
from core.sinyal_skor import (
    feature_olustur, ai_score_hesapla, karar_ver, risk_hesapla,
)

# ── Telegram ──────────────────────────────────────────────
# v56 MODÜLERLEŞTİRME: Gönderim katmanı core/telegram_gonderim.py'ye
# taşındı. Buradan yeniden dışa verilir — mevcut çağrı noktalarının
# hiçbiri değişmedi (main.telegram_gonder hâlâ çalışır).
from core.telegram_gonderim import (
    TELEGRAM_URL, TELEGRAM_PHOTO,
    TG_MAX_UZUNLUK, _TG_GUVENLI_UZUNLUK, _TG_MIN_ARALIK,
    _tg_lock, _tg_son_mesaj, _tg_son_zaman,
    _tg_parcala, _yanitla,
    telegram_gonder, telegram_grafik_gonder,
)

# ── Event Handlers ────────────────────────────────────────
def _on_order_filled(msg):
    d = msg.data
    log.info(f"[EVENT] ORDER FILLED: {d.get('sembol')} {d.get('yon')}")

def _on_risk_limit(msg):
    d = msg.data
    telegram_gonder(f"🛑 <b>RİSK LİMİTİ</b>\nGünlük PnL:{d.get('gunluk_pnl',0):+.2f}\nİşlemler durduruldu.")

def _on_risk_drawdown(msg):
    d = msg.data
    telegram_gonder(f"⚠️ <b>DRAWDOWN</b>\n%{d.get('dd_pct',0):.1f} | {d.get('mevcut_bakiye',0):.2f}USDT")

def _on_risk_liquidation(msg):
    d = msg.data
    telegram_gonder(f"🚨 <b>LİKİDASYON RİSKİ</b>\n{d.get('sembol')} uzaklık:%{d.get('uzaklik_pct',0):.1f}")

def _on_exchange_failover(msg):
    d = msg.data
    telegram_gonder(f"⚠️ <b>EXCHANGE FAILOVER</b>\n{d.get('from')} → {d.get('to')}")

def _on_alert(msg):
    d = msg.data
    mesaj = d.get("mesaj", "")
    if mesaj:
        # Rejim değişimleri için tip belirleme (spam önleme)
        tip = "rejim" if "REJİM" in mesaj else "alert"
        telegram_gonder(f"⚠️ <b>UYARI</b>\n{mesaj}", tip=tip)
        log.warning(f"[ALERT] {mesaj}")

def _on_position_closed(msg):
    d = msg.data
    sembol  = d.get("sembol", ""); sebep = d.get("sebep", "")
    pnl_pct = d.get("pnl_pct", 0)
    pnl_usdt= d.get("pnl_usdt", 0)
    log.info(f"[EVENT] POZİSYON KAPANDI: {sembol} {sebep} PnL:{pnl_pct:+.2f}%")

    # v23: Event payload'ı minimal — eksik alanları son analiz cache'inden tamamla
    # (publisher'lar ab_varyant/model_adi/risk_usdt/giris göndermeyebiliyor)
    try:
        with _son_analizler_lock:
            _cached = dict(_son_analizler.get(sembol, {}))
        for _k in ("ab_varyant", "model_adi", "risk_usdt", "giris",
                   "fill_fiyat", "son_atr", "rr_planlanan"):
            if _k not in d and _k in _cached:
                d[_k] = _cached[_k]
    except Exception as _enr_e:
        log.debug(f"[ENRICH] {_enr_e}")
    # Dashboard'a kapanışı bildir
    try:
        pozisyon_kapandi_bildir(
            sembol = sembol,
            yon    = d.get("yon", "LONG"),
            giris  = d.get("giris", 0),
            cikis  = d.get("cikis", 0),
            pnl_usdt = float(pnl_usdt),
            pnl_pct  = float(pnl_pct),
            sebep    = sebep,
        )
    except Exception as _ex:
        log.debug(f"[SUPPRESS] {_ex}")
    # v31: Bu işlemin giriş gecikmesine PnL'i eşle (gecikme analizi için)
    try:
        gecikme_pnl_esle(sembol, float(pnl_pct))
    except Exception as _ge:
        log.debug(f"[GECIKME ESLE] {_ge}")
    # Self-training tetikle
    _self_train_tetikle(sembol, pnl_pct, gercek_islem=True)   # v58 K-17: gerçek kapanış
    # v17: Öğrenme metriklerini güncelle
    try:
        _ogrenme_metrik_guncelle(sembol, pnl_pct > 0)
    except Exception: pass
    # v18: Kelly Engine güncelle (per-coin canlı win_rate için)
    try:
        # v23: Gerçek R:R — risk_usdt cache'ten gelir, yoksa planlanan R:R
        _risk_usdt = abs(d.get("risk_usdt", 0))
        if _risk_usdt > 0.01:
            rr_ratio = abs(d.get("pnl_usdt", 0)) / _risk_usdt
        else:
            rr_ratio = d.get("rr_planlanan", 1.5)   # planlanan R:R fallback
        risk_manager.pnl_guncelle(
            float(d.get("pnl_usdt", 0)),
            pnl_pct=pnl_pct,
            sembol=sembol,
            rr_ratio=max(rr_ratio, 0.1),
        )
    except Exception as _ke: log.debug(f"[KELLY UPDATE] {_ke}")
    # v18: Execution kalitesini kaydet
    try:
        hedef_f  = float(d.get("giris", 0))
        gercek_f = float(d.get("fill_fiyat", hedef_f))
        risk_manager.execution_kaydet(hedef_f, gercek_f)
    except Exception: pass
    # v21: A/B test sonucunu kaydet
    try:
        ab_varyant = d.get("ab_varyant", "A")
        ab_manager.islem_kaydet(ab_varyant, pnl_pct)
        log.debug(f"[A/B] {sembol} varyant={ab_varyant} pnl={pnl_pct:+.2f}%")
    except Exception as _ab_e: log.debug(f"[A/B] {_ab_e}")
    # v22: Model registry canlı performans güncelle + rollback kontrolü
    try:
        model_adi = d.get("model_adi", "")
        if "rf" in model_adi.lower():
            model_registry.canli_sonuc_guncelle(sembol, "rf", pnl_pct)
            # Rollback gerekli mi?
            rb = model_registry.rollback_gerekli_mi(sembol, "rf")
            if rb:
                from config import MODEL_DIR as _MDR
                if model_registry.rollback_yap(sembol, "rf", rb, _MDR):
                    telegram_gonder(
                        f"🔄 <b>MODEL ROLLBACK</b>\n{sembol} RF modeli "
                        f"v{rb['versiyon']}'e geri alındı (performans düşüşü)",
                        tip="rollback"
                    )
    except Exception as _mr_e: log.debug(f"[REGISTRY] {_mr_e}")
    # v16: Edge analytics'e kaydet
    try:
        if edge_analytics:
            import time as _t
            edge_analytics.islem_ekle(
                pnl_usdt   = float(pnl_usdt),
                pnl_pct    = float(pnl_pct),
                rejim      = d.get("rejim", "?"),
                volatility_pct = 0,
                latency_ms = 0,
                strateji   = sebep,
                yon        = d.get("yon","?"),
                sembol     = sembol,
                ts         = _t.time(),
            )
    except Exception: pass


def _kaldirac_goster(t: dict):
    """Paper işlem kaydındaki GERÇEK kaldıraç — görüntü katmanı için.

    ── NEDEN VAR (v58 K-89) ─────────────────────────────────────
    K-86 paper'ı 1x spot muhasebesinden çıkarıp canlıyla aynı
    kaldıraca bağladı (`islem_kaldiraci`), ama GÖRÜNTÜ katmanı
    güncellenmedi: `main.py` üç ayrı yerde `"kaldirac": 1` SABİT
    yazıyordu (panel'in iki kolu + `_paper_pozlari_esle`, yani
    Telegram `/fpoz`). Ölçüldü: DB `kaldirac=3.0` derken panel
    `1x` gösteriyordu.

    K-32/K-33'ün dersi birebir tekrar etmişti: iki kaynak aynı
    büyüklüğü farklı gösteriyorsa biri yalan söylüyordur.

    ⚠️ EKSİK DEĞER 1'E DÜŞÜRÜLMEZ (§5.1 fail-open). K-86 öncesi
    kayıtlarda `kaldirac` yok; orada `1` yazmak "kaldıraç yoktu"
    demek olurdu — oysa doğru cevap "bilinmiyor". None dönüyoruz,
    UI "?" gösteriyor.
    """
    ham = t.get("kaldirac")
    if ham in (None, ""):
        return None
    try:
        k = float(ham)
    except (TypeError, ValueError):
        return None
    return int(k) if k == int(k) else round(k, 2)


def _zaman_stop_saat():
    """Zaman stop ufku, SAAT cinsinden — motorla AYNI kaynaktan (v58 K-90).

    `config.ZAMAN_STOP_SN` `zaman_stop_doldu_mu()`'nun kullandığı değerin
    ta kendisi. Paneli "24" diye sabit yazmak, ufuk değişince sessizce
    yalan söyleyen bir gösterge bırakırdı — bu kod tabanının K-83/K-82'de
    tekrar eden hatası (bir yerde kalibre edilmiş sabit, başka yerde
    güncellenmemiş).
    """
    try:
        from config import ZAMAN_STOP_SN
        return round(ZAMAN_STOP_SN / 3600.0, 2) if ZAMAN_STOP_SN > 0 else None
    except ImportError:
        return None


def _strateji_dayaniklilik_dogrula(sembol: str = None) -> dict:
    """
    v24: Bir coin'in (veya tümünün) işlem geçmişini dayanıklılık testinden geçirir.
    Reddedilen coin'lerde yeni pozisyon açılmaz (_strateji_onay[sembol]=False).

    Yeterli işlem yoksa karar VERİLMEZ — coin onaylı kabul edilir (varsayılan izin),
    çünkü test edecek veri yok. Bu, yeni başlayan botu engellemez.
    """
    semboller = [sembol] if sembol else list(COINS)
    sonuclar = {}
    try:
        journal = get_journal(JOURNAL_DB_PATH)
    except Exception as e:
        log.debug(f"[VALIDATOR] Journal erişilemedi: {e}")
        return sonuclar

    for s in semboller:
        try:
            getiriler = journal.getiri_serisi(s, limit=200)
            if len(getiriler) < 30:
                # Yetersiz veri → varsayılan izin (test edilemiyor)
                _strateji_onay[s] = True
                continue

            import numpy as _np_v
            arr = _np_v.array(getiriler)

            # Walk-forward pencereleri: 30'arlık bloklara böl
            pencere_getirileri = []
            blok = 30
            for i in range(0, len(arr) - blok + 1, blok):
                pencere_getirileri.append(float(_np_v.sum(arr[i:i+blok])))

            karar = strateji_validator.dogrula(
                getiriler=arr,
                wf_pencere_getirileri=pencere_getirileri,
                deneme_sayisi=4,   # bot 4 strateji tipi deniyor (overfit deflation)
                bakiye=futures_bakiye() or BALANCE,
                min_islem=30,
            )
            _strateji_onay[s] = karar.onay
            _strateji_karar_cache[s] = karar
            sonuclar[s] = karar

            if not karar.onay:
                log.warning(f"[VALIDATOR] ⛔ {s} dayanıklılık REDDİ "
                            f"(skor={karar.skor}/100) — yeni pozisyon durduruldu")
                # v24: RED alan coin'in modelini son iyi versiyona geri al.
                # Dayanıklılık düşüşü genelde model bozulmasından gelir.
                try:
                    from config import MODEL_DIR as _MDIR
                    _rb = model_registry.rollback_gerekli_mi(s, "rf",
                                                             min_islem=10,
                                                             max_kayip_pct=0.0)
                    if _rb:
                        if model_registry.rollback_yap(s, "rf", _rb, _MDIR):
                            log.info(f"[VALIDATOR] {s} modeli v{_rb['versiyon']}'e "
                                     f"geri alındı (dayanıklılık reddi sonrası)")
                            karar.sebepler.append(
                                f"Model v{_rb['versiyon']}'e otomatik rollback yapıldı")
                except Exception as _rbe:
                    log.debug(f"[VALIDATOR rollback] {s}: {_rbe}")
            else:
                log.info(f"[VALIDATOR] ✅ {s} onaylı (skor={karar.skor}/100)")
        except Exception as e:
            log.error(f"[VALIDATOR] {s} doğrulama hatası: {e}")
            _strateji_onay[s] = True   # hata → engelleme yapma (güvenli varsayılan)

    return sonuclar


# v58 (K-64): Online öğrenmenin en son gördüğü KAPANMIŞ bar (sembol → open_time).
# Etiket yalnızca bar değiştiğinde üretilir; aynı bar tekrar öğretilmez.
_online_son_bar: dict = {}
_retrain_aktif: set = set()       # v29: o an retrain edilen semboller
_retrain_aktif_lock = threading.Lock()

def _self_train_tetikle(sembol: str, pnl_pct: float, gercek_islem: bool = False):
    """Pozisyon kapandığında background'da retrain başlat.
    v17: feedback_ekle + RETRAIN_MIN_FEEDBACK kontrolü eklendi.
    v29: Aynı coin için eşzamanlı retrain engellendi (model dosyası race fix).
    """
    # v29: Bu coin zaten retrain ediliyorsa ikinci thread'i açma.
    # Aksi halde iki thread aynı .pkl'e yazıp modeli bozardı.
    with _retrain_aktif_lock:
        if sembol in _retrain_aktif:
            log.info(f"[SELF-TRAIN] {sembol} zaten retrain ediliyor — atlandı")
            return
        _retrain_aktif.add(sembol)

    def _retrain():
        try:
            log.info(f"[SELF-TRAIN] {sembol} retrain başlıyor (pnl={pnl_pct:+.2f}%)")
            # ── v58 (K-22): EĞİTİM/SERVİS ZAMAN DİLİMİ UYUŞMAZLIĞI ──
            # Burası "14d/1h" ile eğitiyordu. Ama ana döngü
            # `coin_analiz(period=ANA_PERIOD, interval=ANA_INTERVAL)` çağırıyor ve
            # modeli 5m feature'larıyla ÇALIŞTIRIYOR. Model dosya adı
            # aynı olduğu için (rf_BTCUSDT.pkl) drift retrain, 5m ile
            # eğitilmiş modeli 1h ile eğitilmiş olanla EZİYORDU.
            #
            # ATR, Momentum_5, Volatility_10, MA20 gibi feature'ların
            # ölçeği 1h ve 5m'de tamamen farklıdır — model, eğitildiği
            # dağılımdan bambaşka bir girdi görüyordu.
            #
            # v58 (K-25): Pencere artık TEK KAYNAKTAN geliyor. Ana döngü
            # de aynı değerleri kullanıyor; model hangi yolun tetiklediğine
            # bağlı olarak farklı veriyle eğitilmiyor.
            from config import MODEL_EGITIM_PERIOD, MODEL_EGITIM_INTERVAL
            df = veri_indir(sembol, period=MODEL_EGITIM_PERIOD,
                            interval=MODEL_EGITIM_INTERVAL)
            if df is None: return
            X, y = feature_olustur(df, sembol)
            if X.empty: return

            # ── v58 (K-17): FEEDBACK YALNIZCA GERÇEK İŞLEMDEN ────
            # Eskiden bu blok KOŞULSUZ çalışıyordu. Drift tespiti de
            # `_self_train_tetikle(sembol, 0.0)` ile buraya giriyordu
            # (main.py'de iki çağrı) ve `1 if pnl_pct > 0 else 0` kuralı
            # gereği her seferinde UYDURMA bir `target=0` kaydı yazıyordu.
            #
            # ÖLÇÜM (2026-09-03): feedback_BTCUSDT.jsonl → 222 kayıt,
            # target dağılımı {0: 221, 1: 1}, 214'ünde pnl_pct=0.0.
            # Yani kayıtların %96'sı hiç gerçekleşmemiş bir "kayıp"tı.
            # Bu satırlar test setini tek sınıfa çevirip accuracy'yi
            # 0.52'den 0.96'ya şişiriyordu (bkz. model_engine K-18).
            if not gercek_islem:
                log.debug(f"[SELF-TRAIN] {sembol} drift retrain — feedback "
                          f"YAZILMADI (gerçek işlem yok)")
            else:
                son_features = _son_features_cache.get(sembol, {})
                if son_features:
                    gercek_sonuc = 1 if pnl_pct > 0 else 0
                    feedback_ekle(sembol, son_features, gercek_sonuc, pnl_pct)
                    log.info(f"[SELF-TRAIN] {sembol} feedback eklendi: sonuc={gercek_sonuc} pnl={pnl_pct:.2f}%")

            # Min feedback kontrolü
            try:
                from config import RETRAIN_MIN_FEEDBACK as _min_fb
            except ImportError:
                _min_fb = 20
            import os as _os2
            from config import MODEL_DIR as _mdir
            fb_path = _os2.path.join(_mdir, f"feedback_{sembol.replace('-','_')}.jsonl")
            fb_count = 0
            if _os2.path.exists(fb_path):
                with open(fb_path) as _f:
                    fb_count = sum(1 for _ in _f)
            if fb_count < _min_fb:
                log.info(f"[SELF-TRAIN] {sembol} feedback yetersiz ({fb_count}<{_min_fb}), retrain atlandı")
                return

            # Feedback verisi dahil edilerek yeniden eğit
            en_iyi_model_yukle_veya_egit(X, y, sembol, yeniden_egit_suresi=0)
            log.info(f"[SELF-TRAIN] {sembol} retrain tamamlandı (feedback={fb_count})")
        except Exception as e:
            log.error(f"[SELF-TRAIN] {sembol} retrain hatası: {e}")
        finally:
            # v29: retrain bitti → kilidi serbest bırak
            with _retrain_aktif_lock:
                _retrain_aktif.discard(sembol)
    threading.Thread(target=_retrain, daemon=True, name=f"retrain_{sembol}").start()

bus.subscribe(Event.ORDER_FILLED,       _on_order_filled)
bus.subscribe(Event.RISK_LIMIT_HIT,     _on_risk_limit)
bus.subscribe(Event.RISK_DRAWDOWN,      _on_risk_drawdown)
bus.subscribe(Event.RISK_LIQUIDATION,   _on_risk_liquidation)
bus.subscribe(Event.EXCHANGE_FAILOVER,  _on_exchange_failover)
bus.subscribe(Event.ALERT,              _on_alert)
bus.subscribe(Event.POSITION_CLOSED,    _on_position_closed)

# ── Feature Seti ──────────────────────────────────────────




# ── Coin Analizi ──────────────────────────────────────────
_son_analizler: dict = {}
_son_analizler_lock = threading.Lock()  # v15: thread-safe erişim

def coin_analiz(sembol="BTCUSDT", period="7d", interval="1h",
                grafik=False, lstm=False, market_data_al=True):
    try:
        with metrics.analiz_suresi.time():
            df = veri_indir(sembol, period, interval)
            if df is None: return None
            close = close_al(df)
            if close.empty or len(close) < 40: return None

            rsi = hesapla_rsi(close); stoch = hesapla_stoch_rsi(close)
            macd, sig, hist = hesapla_macd(close); ma, upper, lower = hesapla_bollinger(close)
            atr = hesapla_atr(df, sembol); wil = hesapla_williams_r(df, sembol)
            cci_s = hesapla_cci(df, sembol); vwap = hesapla_vwap(df, sembol)
            fib = hesapla_fibonacci(close); ichimoku = hesapla_ichimoku(df, sembol)
            adx_s, plus_di, minus_di = hesapla_adx(df, sembol)
            pivots = hesapla_pivot_points(df, sembol)
            try: _, st_dir = hesapla_supertrend(df, sembol)
            except (AttributeError, ValueError, KeyError): st_dir = pd.Series(1, index=close.index)

            son_close = float(close.iloc[-1]); son_rsi = float(rsi.iloc[-1])
            # v58 (K-16): `son_close` artık KAPANMIŞ son barın kapanışı.
            # SL/TP kontrolü ise canlıdaki gibi en taze fiyatı ister —
            # borsada duran STOP_MARKET her tick'te tetiklenir, bar
            # kapanışını beklemez. Oluşmakta olan barın anlık fiyatı
            # `df.attrs` ile taşınır (yoksa kapanışa düşer).
            _ob = (df.attrs.get("olusan_bar") or {}) if hasattr(df, "attrs") else {}
            anlik_fiyat = float(_ob.get("Close", son_close))
            son_stoch = float(stoch.iloc[-1]) if not stoch.dropna().empty else 50.0
            son_ma    = float(ma.iloc[-1]);    son_macd = float(macd.iloc[-1]); son_sig = float(sig.iloc[-1])
            son_atr   = float(atr.iloc[-1])   if not atr.dropna().empty else son_close * 0.01
            son_wil   = float(wil.iloc[-1])   if not wil.dropna().empty else -50.0
            son_cci   = float(cci_s.iloc[-1]) if not cci_s.dropna().empty else 0.0
            son_vwap  = float(vwap.iloc[-1])  if not vwap.dropna().empty else son_close
            son_adx   = float(adx_s.iloc[-1]) if not adx_s.dropna().empty else 20.0
            son_st_dir= int(st_dir.iloc[-1])  if not st_dir.dropna().empty else 1
            son_pivot = float(pivots["pivot"].iloc[-1]) if not pivots["pivot"].dropna().empty else son_close

            hacim_col   = df["Volume"]; ort_hacim = float(hacim_col.mean())
            son_hacim   = float(hacim_col.iloc[-1])
            volume_ratio = son_hacim / ort_hacim if ort_hacim > 0 else 1.0
            whale = {"whale": son_hacim > ort_hacim * 2.5, "oran": round(volume_ratio, 2)}

            # v16: Circuit breaker ATR kontrolü
            if circuit_breaker:
                try:
                    circuit_breaker.atr_guncelle(sembol, float(atr.iloc[-1]), son_close)
                    if not circuit_breaker.kontrol(sembol):
                        log.info(f"[{sembol}] Circuit Breaker aktif — analiz atlandı")
                        return None
                except Exception: pass

            rejim          = piyasa_rejimi_tespit(close, df, sembol)
            mtf_confluence = mtf_confluence_skoru(sembol, veri_indir)

            # v19: HMM rejim — kural bazlı rejimi istatistiksel olarak doğrula/düzelt
            hmm_sonuc = {"rejim": "UNKNOWN", "hmm_aktif": False}
            try:
                vol_series = df["Volume"] if "Volume" in df.columns else None
                atr_series = hesapla_atr(df, sembol)
                # HMM eğitilmemişse veya 6 saatte bir yeniden eğit
                import time as _time_hmm
                if (not hmm_detector._egitildi or
                        _time_hmm.time() - hmm_detector._egitim_ts > 21600):
                    if sembol == COINS[0]:   # Sadece BTC ile eğit (ana veri)
                        df_long = veri_indir(sembol, period="30d", interval="1h")
                        if df_long is not None:
                            hmm_detector.egit(close_al(df_long),
                                              df_long.get("Volume") if hasattr(df_long, "get") else None,
                                              hesapla_atr(df_long, sembol))
                hmm_sonuc = hmm_detector.rejim_tahmin(close, vol_series, atr_series)
                # HMM + kural birleştir
                rejim = hmm_detector.piyasa_rejimi_birlestir(rejim, hmm_sonuc)
                log.debug(f"[HMM/{sembol}] {hmm_sonuc.get('rejim')} "
                          f"p={hmm_sonuc.get('olasilik', 0):.2f} → rejim={rejim}")
            except Exception as _hmm_e:
                # v58 K-36: §5.2 ihlaliydi — bu blok AĞ ÇAĞRISI DEĞİL, yerel
                # hesaplama. log.debug'a gidince HMM birleştirmesi her turda
                # çökse bile hiçbir iz kalmazdı; rejim sessizce kural-bazlıya
                # düşer ve "HMM doğruluyor" sanılırdı.
                log.warning(f"[HMM] {sembol} rejim birleştirme başarısız: "
                            f"{type(_hmm_e).__name__}: {_hmm_e} "
                            f"→ kural rejimi kullanılıyor")
            mkt_data = {}
            if market_data_al:
                try: mkt_data = market_veri_topla(sembol)
                except Exception as md_e:
                    log.warning(f"Market data alınamadı ({sembol}): {md_e}")

            # v18: Likidasyon Isı Haritası — SL/TP yerleşimi için
            likit_harita = {}
            try:
                likit_harita = likidasyon_isi_haritasi(sembol, son_close)
                magnet       = likit_harita.get("magnet_seviye", son_close)
                yogunluk     = likit_harita.get("yogunluk_skoru", 0)
                if yogunluk >= 5:
                    log.info(f"[LİKİT ISI/{sembol}] Yüksek likidasyon yoğunluğu "
                             f"(skor={yogunluk}) magnet={magnet:,.2f}")
            except Exception as _lh_e:
                log.debug(f"[LİKİT ISI] {sembol}: {_lh_e}")

            X, y = feature_olustur(df, sembol)
            # v17 FIX: feedback_veri_yukle burada çağrılmıyor — en_iyi_model_yukle_veya_egit
            # kendi içinde çağırıyor; burada tekrar çağırılırsa veri 2x katlanır
            yukselis_guveni = 50.0; model_adi = "Yok"; model_meta = {}
            model_belirsizlik = 0.0   # v18: Ensemble belirsizlik skoru
            if not X.empty:
                try:
                    model, acc, model_meta, model_adi = en_iyi_model_yukle_veya_egit(X, y, sembol)
                except Exception as _me:
                    log.error(f"[MODEL] {sembol} eğitim hatası: {type(_me).__name__}: {_me}")
                    model, acc, model_meta, model_adi = None, 0, {}, "Hata"
                if model is not None:
                    try: metrics.model_accuracy.labels(sembol=sembol, model=model_adi).set(acc)
                    except Exception as _e: log.debug(f"[SUPPRESS] {_e}")
                    _, X_te, _, _ = train_test_split(X, y, test_size=0.2, shuffle=False)
                    try:
                        batch_prob_raw  = float(model.predict_proba(X_te)[-1][1])
                        yukselis_guveni = batch_prob_raw * 100

                        # v18: Ensemble Confidence Interval
                        from engines.model_engine import StackingWrapper
                        if isinstance(model, StackingWrapper) and model.base_models:
                            try:
                                _probas = []
                                _son_X  = X_te.iloc[[-1]]
                                for _bm, _, _, _ in model.base_models:
                                    try:
                                        _p = float(_bm.predict_proba(_son_X)[0][1])
                                        _probas.append(_p)
                                    except Exception:
                                        pass
                                if len(_probas) >= 2:
                                    model_belirsizlik = float(np.std(_probas))
                                    if model_belirsizlik > 0.15:
                                        log.warning(f"[ENSEMBLE/{sembol}] Belirsizlik std={model_belirsizlik:.3f}")
                            except Exception as _ci_e:
                                log.debug(f"[CI] {sembol}: {_ci_e}")

                        # v20: Online Learning blend
                        try:
                            # v23: cache yerine GÜNCEL bar feature'larını kullan
                            # (cache bu noktada henüz bir önceki döngünün verisini tutuyor)
                            guncel_features = X.iloc[-1].to_dict() if not X.empty else {}
                            if guncel_features:
                                ol = get_online_learner(sembol)
                                # ── v58 (K-64): UYDURMA ETİKET — K-17'nin ONLINE İKİZİ ──
                                # Etiket "son_close bir önceki TURA göre arttı mı?"
                                # diye soruyordu. Ama K-16'dan beri `son_close`
                                # KAPANMIŞ barın kapanışıdır ve 4h ufkunda 4
                                # SAAT boyunca DEĞİŞMEZ. Analiz turu ise ~1 dk'da
                                # bir dönüyor → tur başına "arttı mı?" sorusunun
                                # cevabı yapısal olarak HAYIR (etiket 0).
                                #
                                # ÖLÇÜM (2026-09-06, 5 dk, 20 örnekleme):
                                #   son_close değişimi      : 0 (5 sembolün hepsi)
                                #   online eğitim adımı     : +6 / sembol
                                #   → 6 adımın 6'sı da uydurma "0" etiketi
                                # Oran: ~288 eğitim adımına 1 gerçek etiket
                                # (240 dk / bar ÷ ~0.83 dk / tur).
                                #
                                # Sonuç: online model "fiyat asla yükselmez"i
                                # öğreniyor, P(yükseliş)→0 veriyor ve bu
                                # `birlesik_tahmin` ile güvene %10-35 ağırlıkla
                                # karışıyordu — güveni sistematik olarak
                                # AŞAĞI çekiyordu.
                                #
                                # DÜZELTME: yalnızca BAR DEĞİŞTİĞİNDE öğren.
                                # Bar kimliği feature çerçevesinin son indeksi
                                # (kapanmış barın open_time'ı) — değerden değil
                                # KİMLİKTEN bakılır, çünkü iki bar aynı fiyatla
                                # kapanabilir.
                                # Mantık `etiket_uret`te — satır içi hâli
                                # davranışsal olarak test edilemiyordu (K-37 dersi).
                                _bar_ts = X.index[-1] if len(X.index) else None
                                _onceki_fiyat = _son_analizler.get(sembol, {}).get("son_close", 0)
                                _gercek = etiket_uret(_bar_ts,
                                                      _online_son_bar.get(sembol),
                                                      son_close, _onceki_fiyat)
                                if _bar_ts is not None:
                                    _online_son_bar[sembol] = _bar_ts
                                online_sonuc  = ol.guncelle_ve_tahmin(guncel_features, _gercek, son_close)
                                birlesik_prob = ol.birlesik_tahmin(batch_prob_raw, online_sonuc)
                                yukselis_guveni = birlesik_prob * 100
                                if online_sonuc.get("drift"):
                                    log.info(f"[ONLINE/{sembol}] Drift tespit — batch ağırlığı artırıldı")
                        except Exception as _ol_e:
                            # v58 (K-45): log.debug İDİ — online learner her
                            # çağrıda AttributeError atıyordu (river API
                            # değişikliği) ve bu satır onu SESSİZCE yutuyordu.
                            # Aylarca online öğrenme çalışmadı, panelde
                            # `online_learning: {}` görünüyordu ve "veri yok"
                            # sanılıyordu. §5.2: ağ çağrısı olmayan istisna
                            # debug'a yazılmaz.
                            log.warning(f"[ONLINE BLEND] {sembol} başarısız: "
                                        f"{type(_ol_e).__name__}: {_ol_e}")

                    except (AttributeError, ValueError): pass

                    # v58 (K-37): beceri anlamlı değilse model güveni
                    # NÖTRLENİR. Mantık `guven_notrle`'de — satır içi hâli
                    # davranışsal olarak test edilemiyordu (mutasyon testi
                    # bloğu kaldırdığında testler yeşil kalmıştı, K-29 tuzağı).
                    from engines.model_engine import guven_notrle
                    yukselis_guveni = guven_notrle(
                        yukselis_guveni, model_meta, sembol)

                    if acc < 0.50:
                        try: bus.publish(Event.MODEL_DEGRADED, {"sembol": sembol, "acc": acc}, "Analysis")
                        except Exception as _e: log.debug(f"[SUPPRESS] {_e}")

                # Son feature'ları self-training için cache'le + drift kontrol
                try:
                    son_satir = X.iloc[-1].to_dict()
                    _son_features_cache[sembol] = son_satir
                    # v17: Feature drift dedektörü
                    if _feature_drift_kontrol(sembol, son_satir):
                        # Drift tespit edildi — adaptif retrain tetikle
                        log.info(f"[DRIFT/{sembol}] Drift tespit edildi, retrain tetikleniyor")
                        _self_train_tetikle(sembol, 0.0)  # pnl=0 ile tetikle (drift retrain)
                except Exception:
                    pass

            rl_reward     = rl_ortalama_reward(sembol)
            lstm_tahmin   = None
            if lstm:
                df_l = veri_indir(sembol, period="60d", interval="1h")
                if df_l is not None: lstm_tahmin = lstm_tahmin_yap(close_al(df_l), sembol)

            ai_score = ai_score_hesapla(son_rsi, son_close, son_ma, son_macd, son_sig,
                                         yukselis_guveni, son_stoch, son_wil, son_cci,
                                         son_adx, rejim, mkt_data,
                                         mtf_confluence.get("skor", 0), son_st_dir)

            # ── v12: RegimeAdapter ile parametre adaptasyonu ─
            try:
                regime_adapter.rejim_guncelle(rejim, sembol)
                regime_konfig = regime_adapter.aktif_konfig(sembol)
                if regime_konfig:
                    log.debug(f"[REGIME] {sembol} {rejim}: {regime_konfig.aciklama}")
            except Exception as re_e:
                log.debug(f"[REGIME] {sembol} konfig hatası: {re_e}")
                regime_konfig = None

            # ── v14: Chop + Fake Breakout filtresi ──────────
            try:
                from config import CHOP_FILTER_ENABLED, CHOP_MAX, FAKE_BREAKOUT_FILTER
                if CHOP_FILTER_ENABLED or FAKE_BREAKOUT_FILTER:
                    _vol_series = df["Volume"] if "Volume" in df.columns else None
                    _ra = regime_detector.tespit_et(df, close, _vol_series)
                    if not _ra.islem_yapilabilir:
                        log.info(f"[CHOP FILTER] {sembol} atlandı: {_ra.aciklama}")
                        # return None DEĞİL — panel için analiz devam eder
                        # sadece _execution_isle çağrılmayacak (sonuc'a flag ekle)
                        pass  # regime filtresi edge engine zaten halleder
            except Exception as _e: log.debug(f"[SUPPRESS] {_e}")

            # ── v12: EdgeEngine ile sinyal kalite filtresi ───
            strateji_adi = strateji_engine.strateji_sec(
                rejim, mtf_confluence.get("skor", 0),
                mkt_data.get("funding_rate", 0)
            )
            edge_sonuc = edge_engine.filtrele(
                ai_score      = ai_score,
                rejim         = rejim,
                mtf_skor      = mtf_confluence.get("skor", 0),
                market_data   = mkt_data,
                yukselis_guveni = yukselis_guveni,
                son_atr       = son_atr,
                son_close     = son_close,
                strateji      = strateji_adi,
            )

            conf = 50
            if ai_score >= 5:   conf += 25
            elif ai_score >= 3: conf += 15
            if volume_ratio > 1.5: conf += 10
            if abs(mtf_confluence.get("skor", 0)) >= 3: conf += 10
            if mkt_data.get("market_sentiment", 0) != 0: conf += 5
            if edge_sonuc.get("gecti"):               conf += 10
            conf = min(conf, 100)

            karar    = karar_ver(ai_score)
            risk_obj = risk_hesapla(son_close, son_atr)
            metrics.ai_score.labels(sembol=sembol).set(ai_score)
            metrics.heartbeat_guncelle()
            if watchdog: watchdog.heartbeat(sembol)

            grafik_yolu = None
            if grafik:
                try: grafik_yolu = _grafik_olustur(close, rsi, macd, sig, upper, lower, ma, sembol)
                except Exception as g_e: log.warning(f"Grafik oluşturulamadı: {g_e}")

            sig_id = sinyal_kaydet(sembol, son_close, ai_score, karar, rsi=son_rsi, macd=son_macd,
                                   confidence=conf, sentiment=int(mkt_data.get("market_sentiment", 0) * 10),
                                   model_adi=model_adi)
            bus.publish(Event.SIGNAL_GENERATED, {"sembol": sembol, "ai_score": ai_score,
                                                  "karar": karar, "confidence": conf}, "Analysis")
            metrics.sinyal_sayisi.labels(sembol=sembol, karar=karar, rejim=rejim).inc()

            sonuc = {
                "sembol": sembol, "son_close": son_close, "son_rsi": son_rsi, "son_stoch": son_stoch,
                "anlik_fiyat": anlik_fiyat,      # v58 K-16: oluşan barın anlık fiyatı (SL/TP için)
                "sinyal_ts": time.time(),   # v28: sinyalin doğduğu an (gecikme ölçümü)
                "son_ma": son_ma, "son_macd": son_macd, "son_sig": son_sig, "son_wil": son_wil,
                "son_cci": son_cci, "son_vwap": son_vwap, "son_atr": son_atr, "son_adx": son_adx,
                "son_st_dir": son_st_dir, "son_pivot": son_pivot, "volume_ratio": volume_ratio,
                "rejim": rejim, "mtf_confluence": mtf_confluence, "market_data": mkt_data,
                "ai_score": ai_score, "confidence": conf, "karar": karar, "model_adi": model_adi,
                "yukselis_guveni": yukselis_guveni, "lstm_tahmin": lstm_tahmin,
                "model_meta": model_meta, "rl_reward": round(rl_reward, 3),
                "model_belirsizlik": round(model_belirsizlik, 4),   # v18: Ensemble CI
                "cvd_data": mkt_data.get("cvd", {}),                # v18: CVD verisi
                "likit_harita": likit_harita,                        # v18: Likidasyon ısı haritası
                "hmm_sonuc": hmm_sonuc,                              # v19: HMM rejim
                "mtf_bloklu": mtf_confluence.get("bloklu", False),  # v19: MTF cascade blok
                "tft_tahmin": {},                                     # v21: TFT (aşağıda doldurulur)
                "rl_aksiyon": {},                                     # v21: PPO RL ajanı
                "ab_varyant": ab_manager.varyant_sec(sembol, _global_dongu_sayaci),  # v23: global sayaç
                "risk": risk_obj, "whale": whale, "fib": fib, "sig_id": sig_id,
                "edge_sonuc": edge_sonuc, "strateji": strateji_adi,
                "ichimoku": {k: (None if (val := float(v.iloc[-1])) != val else val)
                             for k, v in ichimoku.items()
                             if hasattr(v, "iloc") and len(v) > 0},
                "close_obj": close, "rsi_obj": rsi, "macd_obj": macd, "sig_obj": sig,
                "upper_obj": upper, "lower_obj": lower, "ma_obj": ma, "grafik_yolu": grafik_yolu,
            }
            def _temizle_deger(v):
                import math
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    return None
                return v
            _yeni_analiz = {
                k: (_temizle_deger(v) if isinstance(v, float) else v)
                for k, v in sonuc.items()
                if not k.endswith("_obj") and k != "grafik_yolu"
            }

            # v21: TFT tahmini — X'in son LOOKBACK satırıyla
            try:
                if not X.empty and len(X) >= LOOKBACK:
                    tft_sonuc = tft_tahmin_yap(X, sembol, LOOKBACK)
                    sonuc["tft_tahmin"] = tft_sonuc
                    _yeni_analiz["tft_tahmin"] = tft_sonuc
                    if tft_sonuc.get("aktif"):
                        log.debug(f"[TFT/{sembol}] prob={tft_sonuc['prob']:.3f}")
            except Exception as _tft_e:
                log.debug(f"[TFT] {sembol}: {_tft_e}")

            # v21: RL ajanı tahmini
            try:
                son_feat = _son_features_cache.get(sembol, {})
                if son_feat:
                    rl_sonuc = rl_tahmin(son_feat, sembol,
                                         poz_yon=0, pnl_pct=0.0,
                                         drawdown=risk_manager.drawdown_pct())
                    sonuc["rl_aksiyon"] = rl_sonuc
                    _yeni_analiz["rl_aksiyon"] = rl_sonuc
                    if rl_sonuc.get("aktif"):
                        log.debug(f"[RL/{sembol}] aksiyon={rl_sonuc['aksiyon_adi']}")
            except Exception as _rl_e:
                log.debug(f"[RL] {sembol}: {_rl_e}")

            with _son_analizler_lock:
                _son_analizler[sembol] = _yeni_analiz
            # Paper modda gerçek Binance API'si çalışmaz; paper_trader'dan da al
            _futures_pozlar = acik_futures_pozisyonlar()
            _paper_pozlar   = []
            if not _futures_pozlar:
                try:
                    from data.database import acik_tradeler
                    _raw = acik_tradeler("PAPER")
                    _paper_pozlar = _paper_pozlari_esle(_raw)
                except Exception as _e: log.debug(f"[SUPPRESS] {_e}")
            _gosterilecek_pozlar = _futures_pozlar or _paper_pozlar
            # v55: bakiye TEK kez çekilir. Eskiden aynı blokta iki ayrı
            # futures_bakiye() ağ isteği vardı (coin başına, her turda).
            _bakiye_anlik = futures_bakiye()
            state_guncelle(son_analiz=_son_analizler,
                            acik_pozisyonlar=_gosterilecek_pozlar,
                            futures_bakiye=_bakiye_anlik or paper_trader.bakiye,
                            paper_bakiye=paper_trader.bakiye,
                            para_dokumu=paper_trader.para_dokumu(),   # v58 K-42
                            gunluk_pnl=risk_manager.gunluk_pnl,
                            risk_durumu=_risk_durum_str())
            metrics.futures_bakiye.set(_bakiye_anlik)
            metrics.gunluk_pnl.set(risk_manager.gunluk_pnl)
            metrics.drawdown.set(risk_manager.drawdown_pct())

            edge_str = "✅ EDGE" if edge_sonuc.get("gecti") else "❌ EDGE"
            log.info(f"[{sembol}] {son_close:,.2f} | AI:{ai_score} | "
                     f"%{conf} | {rejim} | {karar} | {edge_str}")
            return sonuc

    except Exception as e:
        log.error(f"[ANALIZ] {sembol} hata: {type(e).__name__}: {e}", exc_info=True)
        if watchdog: watchdog.hata_bildir(e, f"coin_analiz/{sembol}")
        try: metrics.hata_sayisi.labels(kaynak=sembol, tip="analiz").inc()
        except Exception as _e: log.debug(f"[SUPPRESS] {_e}")
        return None

def _risk_durum_str():
    dd = risk_manager.drawdown_pct(); pnl = risk_manager.gunluk_pnl
    if dd >= 10 or pnl <= -BALANCE * 0.04: return "🛑 Kritik"
    if dd >= 5  or pnl <= -BALANCE * 0.02: return "⚠️ Dikkat"
    return "✅ Normal"


def _gelismis_state_topla() -> dict:
    """
    v25: Tüm gelişmiş motorların (v18-v24) durumunu dashboard için topla.
    Her motor opsiyonel — yoksa boş dict döner, panel kendiliğinden gizlenir.
    """
    g = {}
    # ── Performans metrikleri (Sharpe/Sortino/Calmar/Omega) ──
    try:
        g["performans"] = risk_manager.performans.rapor()
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── Kelly engine (per-coin canlı) ────────────────────
    try:
        kelly = {}
        for s in COINS:
            f, wr, rr, n = risk_manager.kelly_engine.kelly_fraksiyon(s)
            if n > 0:
                kelly[s] = {"kelly_f": round(f, 3), "win_rate": round(wr*100, 1),
                            "avg_rr": round(rr, 2), "n": n}
        g["kelly"] = kelly
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── Validator kararları (v24) ────────────────────────
    try:
        val = {}
        for s in COINS:
            karar = _strateji_karar_cache.get(s)
            if karar:
                val[s] = {"onay": karar.onay, "skor": round(karar.skor, 0)}
        g["validator"] = val
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── Portfolio MVO ağırlıkları (v20) ──────────────────
    try:
        if hasattr(portfolio_optimizer, "_agirliklar") and portfolio_optimizer._agirliklar:
            g["portfolio"] = {
                "yontem": portfolio_optimizer._yontem,
                "sharpe": round(portfolio_optimizer._sharpe, 3),
                "agirliklar": {k: round(v*100, 1) for k, v in portfolio_optimizer._agirliklar.items()},
            }
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── Online learning (v20) ────────────────────────────
    try:
        from engines.online_learner import _online_learners
        ol = {}
        for s, learner in _online_learners.items():
            ol[s] = {"egitim": learner._egitim_sayisi, "drift": learner._drift_sayisi}
        g["online_learning"] = ol
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── Model registry (v22) ─────────────────────────────
    try:
        reg = {}
        for s in COINS:
            gecmis = model_registry.gecmis(s, "rf", limit=1)
            if gecmis:
                aktif = gecmis[0]
                canli = (aktif["canli_pnl"]/aktif["canli_islem"]) if aktif["canli_islem"] > 0 else 0
                reg[s] = {"versiyon": aktif["versiyon"], "acc": round(aktif["accuracy"], 3),
                          "canli_pnl": round(canli, 2), "islem": aktif["canli_islem"]}
        g["model_registry"] = reg
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── Smart execution (v22) ────────────────────────────
    try:
        g["smart_exec"] = smart_executor.istatistik()
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── A/B test (v21) ───────────────────────────────────
    try:
        ta = ab_manager.istatistik_test()
        g["ab_test"] = {
            "a": ab_manager.a.ozet(), "b": ab_manager.b.ozet(),
            "kazanan": ta.get("kazanan", "?"), "anlamli": ta.get("anlamli", False),
            "p": ta.get("p_value", 1.0),
        }
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── Çoklu borsa (v26) ────────────────────────────────
    try:
        g["multiex"] = multiexchange.istatistik()
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── Giriş gecikme (v28) ──────────────────────────────
    try:
        g["gecikme"] = giris_gecikme_ozet()
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    # ── Veto teşhisi (v32) ───────────────────────────────
    try:
        g["veto"] = veto_ozet()
    except Exception as _e:
        # v58 (K-48): `except Exception: pass` İDİ. Bir metrik
        # çökerse panel {} gösteriyordu ve "veri yok" ile
        # "çöktü" AYIRT EDİLEMİYORDU. Online learner tam bu
        # yüzden aylarca kırık kaldı (K-45). §5.2: ağ çağrısı
        # olmayan istisna sessiz geçilmez.
        log.warning(f"[PANEL METRİK] toplanamadı: "
                    f"{type(_e).__name__}: {_e}")

    return g


def _grafik_olustur(close, rsi, macd, signal, upper, lower, ma, sembol):
    """Teknik analiz grafiği üret (thread-safe).

    v57 DÜZELTME — Telegram'a giden grafikler bazen SİMSİYAH, bazen
    BEMBEYAZ geliyordu.

    KÖK NEDEN: Eski kod pyplot'un GLOBAL durumunu kullanıyordu:
        fig, axes = plt.subplots(...)   # global "current figure" olur
        plt.tight_layout()              # global
        plt.savefig(yol); plt.close()   # global

    Ama coin analizi 5 sembol için EŞZAMANLI çalışıyor:
        loop.run_in_executor(None, coin_analiz, ...)   # main.py:1777
        asyncio.gather(*[_tek_coin_isle(s) for s in COINS])
    Yani bu fonksiyon aynı anda 5 THREAD'den çağrılıyor ve pyplot'un
    figür kaydı thread-safe DEĞİL. Yarış senaryosu:

        Thread A: plt.subplots()  → figür A "current"
        Thread B: plt.subplots()  → figür B "current" oldu
        Thread A: plt.savefig()   → B'yi ya da yarım tuvali kaydeder
        Thread A: plt.close()     → B'yi KAPATIR
        Thread B: plt.savefig()   → ortada figür yok → BOŞ görüntü

    Belirtiyle birebir uyuşuyor:
      • "simsiyah" = facecolor #0d1117 basılmış, içerik çizilmemiş
      • "bembeyaz" = hiç figür yok, varsayılan boş tuval

    ÇÖZÜM: pyplot'a hiç dokunma. `Figure` nesnesi + `FigureCanvasAgg`
    tamamen yerel; global kayıt yok, `close()` gerekmez (çöp toplayıcı
    halleder), thread'ler birbirini göremez.
    """
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(14, 18), facecolor="#0d1117")
    FigureCanvasAgg(fig)          # savefig için tuval bağla
    axes = fig.subplots(4, 1)
    for ax in axes:
        ax.set_facecolor("#0d1117"); ax.tick_params(colors="white")
        for sp in ax.spines.values(): sp.set_edgecolor("#30363d")
    axes[0].plot(close.values, color="#58a6ff", lw=1.5, label="Close")
    axes[0].plot(ma.values, color="#f0883e", lw=1, ls="--", label="MA20")
    axes[0].fill_between(range(len(upper)), upper.values, lower.values, alpha=0.1, color="#58a6ff")
    axes[0].set_title(f"{sembol} — Fiyat & Bollinger", color="white")
    axes[0].legend(facecolor="#161b22", labelcolor="white", fontsize=8)
    axes[1].plot(rsi.values, color="#d2a8ff", lw=1.5)
    axes[1].axhline(70, color="#f85149", ls="--", lw=0.8); axes[1].axhline(30, color="#3fb950", ls="--", lw=0.8)
    axes[1].set_title("RSI", color="white"); axes[1].set_ylim(0, 100)
    hist_v = (macd - signal).values
    axes[2].bar(range(len(hist_v)), hist_v, color=["#3fb950" if v >= 0 else "#f85149" for v in hist_v], alpha=0.6)
    axes[2].plot(macd.values, color="#58a6ff", lw=1.2, label="MACD")
    axes[2].plot(signal.values, color="#f0883e", lw=1.2, label="Signal")
    axes[2].set_title("MACD", color="white")
    axes[2].legend(facecolor="#161b22", labelcolor="white", fontsize=8)
    deg = close.pct_change().fillna(0).values * 100
    axes[3].bar(range(len(deg)), deg, color=["#3fb950" if v >= 0 else "#f85149" for v in deg], alpha=0.7)
    axes[3].set_title("Dönemsel Değişim (%)", color="white")
    # v57: fig.* — pyplot global durumu KULLANILMIYOR (bkz. docstring).
    fig.tight_layout(pad=2.5)
    # v58 K-34: yol SABİT KODLU idi ("logs/...") — logging kurulumu
    # `_LOG_DIR` (ASTRA_LOG_DIR) kullanırken grafik yazımı bu
    # yönlendirmenin DIŞINDA kalıyordu. Test koşusu üretim `logs/`
    # dizinine PNG bırakıyordu; gerçek bir sembolle çağrılsaydı botun
    # Telegram'a gönderdiği grafiği sessizce ezerdi (§4.6).
    yol = os.path.join(_LOG_DIR, f"astra_{sembol.replace('-','_')}.png")
    fig.savefig(yol, dpi=130, bbox_inches="tight", facecolor="#0d1117")
    # plt.close() GEREKMİYOR: figür global kayda hiç girmedi, referans
    # bırakılmadığı an çöp toplayıcı alır. plt.close() çağırmak BAŞKA bir
    # thread'in figürünü kapatma riski taşırdı — hatanın parçasıydı.
    return yol

def monte_carlo_raporu(sembol="BTCUSDT", chat_id=CHAT_ID):
    try:
        # ── v58 (K-46): BİRİM UYUŞMAZLIĞI ──────────────────────────
        # Eskiden `interval="1h"` idi: SAATLİK getiriler üretiliyor,
        # sonra `var_hesapla(..., gun=1)` ile "1 GÜNLÜK VaR" diye
        # raporlanıyordu. Yani ekrandaki rakam 1 SAATLİK riskti.
        # Ölçüm (BTCUSDT, 3 yıl): aynı çağrı 4-saatlik getiriyle 157.86,
        # GÜNLÜK getiriyle 377.63 USDT veriyor → 2.38×. Saatlikte fark
        # ~√24 ≈ 4.9× olur, yani risk 5 kat DÜŞÜK gösteriliyordu.
        #
        # Yan etkisi daha sinsi: `pozisyon_icin_tam_analiz` risk
        # seviyesini `var_pct > 3 → YÜKSEK` ile belirliyor. Bu eşik
        # günlük VaR için kalibre; saatlik değer neredeyse hiç 3'ü
        # geçmediği için risk seviyesi PRATİKTE HEP "DÜŞÜK" çıkıyordu.
        # (K-29/K-30/K-40/K-43 ile aynı sınıf: birime bağlı sabit.)
        df = veri_indir(sembol, period="365d", interval="1d")
        if df is None: return "MC veri yok"
        close  = close_al(df); bakiye = futures_bakiye() or BALANCE
        pozlar = acik_futures_pozisyonlar()
        analiz = mc_risk.pozisyon_icin_tam_analiz(close, bakiye, pozlar)
        var    = analiz["var"]; dd = analiz["drawdown"]; tavsiyeler = "\n".join(analiz["tavsiye"])
        likit_str = "".join(
            f"\n  {'⚠️' if not lr.get('guvenli') else '✅'} {lr['sembol']}: "
            f"{lr['likidasyon_fiyat']:,.4f} (%{lr['uzaklik_pct']:.1f})"
            for lr in analiz.get("likidasyon", [])
        )
        mesaj = (f"🎲 <b>MONTE CARLO — {sembol}</b>\n"
                 f"Risk:{analiz['risk_seviyesi']} | Bakiye:{bakiye:.2f}USDT\n"
                 f"1G VaR:{var['var_usdt']:.2f}$ (%{var['var_pct']:.2f})\n"
                 f"30G Worst DD: %{dd['worst_case_dd_pct']:.2f}\n"
                 f"Likidasyon:{likit_str if likit_str else ' Yok'}\n"
                 f"💡 {tavsiyeler}\n🔢 {MC_SIMULATIONS:,} sim")
        telegram_gonder(mesaj, chat_id)
        metrics.var_usdt.set(var["var_usdt"])
        return mesaj
    except Exception as e:
        hata = f"MC hatası: {type(e).__name__}: {e}"
        log.error(hata); return hata

def _paper_pozlari_esle(ham) -> list:
    """PAPER işlemlerini futures pozisyon şemasına çevirir.

    v58 (K-56): Bu eşleme main.py'da İKİ AYRI YERDE duplike edilmişti
    (panel güncellemesinin iki kolu) ve `/fpoz` hiç kullanmıyordu.
    Tek kaynağa çıkarıldı — "iki yol aynı işi yapıyor" bu kod tabanında
    tekrar eden hata sınıfı (K-13 paper/canlı çıkış, K-32 çift bildirim).
    """
    out = []
    for t in (ham if isinstance(ham, list) else []):
        giris = t.get("giris_fiyat", t.get("giris", 0)) or 0
        miktar = float(t.get("miktar") or 0)
        sembol = t.get("sembol", "-")
        yon = t.get("yon", "LONG")
        guncel = (_son_analizler.get(sembol, {}) or {}).get("son_close", 0) or 0
        if guncel and giris and miktar:
            pnl = round((guncel - giris) * miktar if yon == "LONG"
                        else (giris - guncel) * miktar, 4)
        else:
            pnl = t.get("pnl", 0) or 0
        # v58 (K-90): KORUMA SEVİYELERİ PANELE TAŞINIYOR.
        # Bu alanların hepsi `trades` satırında ZATEN duruyordu; panel
        # hiçbirini okumuyordu. Kaldıraçlı bir pozisyonda bakılacak asıl
        # sayılar bunlar — SL/TP nerede, tasfiye ne kadar uzakta, ne
        # kadar sermaye bağlı, zaman stopa ne kaldı.
        #
        # ⚠️ EKSİK = None, 0 DEĞİL (§5.1). "SL yok" ile "SL bilinmiyor"
        # farklı; 0 yazmak paneli "stop sıfırda" diye okutur ve canlı
        # pozisyonda (futures yolu bu alanları göndermiyor) yanlış
        # güvence verir. UI None'ı "—" gösteriyor.
        try:
            from engines.futures_trade_engine import zaman_stop_doldu_mu
            _doldu, _gecen = zaman_stop_doldu_mu(t.get("ts_ac"))
        except Exception as e:
            # Ufuk okunamadıysa UYDURMA — görünür bırak (§5.2).
            log.debug(f"[PANEL] zaman stop okunamadı {sembol}: {e}")
            _doldu, _gecen = False, None

        def _f(alan):
            """Sayıya çevir; yoksa None döndür (0'a düşürme)."""
            v = t.get(alan)
            try:
                return float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        out.append({"sembol": sembol, "yon": yon, "giris": giris,
                    "pnl": pnl, "miktar": miktar,
                    "kaldirac": _kaldirac_goster(t),   # v58 K-89
                    # v58 K-90 — panelin gösteremediği her şey:
                    "guncel":      guncel or None,
                    "stop_loss":   _f("stop_loss"),
                    "take_profit": _f("take_profit"),
                    "tasfiye":     _f("tasfiye_fiyat"),
                    "marjin":      _f("marjin"),
                    "funding":     _f("funding_maliyet"),
                    "gecen_saat":  round(_gecen, 2) if _gecen is not None else None,
                    "zaman_stop_saat": _zaman_stop_saat(),
                    "zaman_stop_doldu": bool(_doldu),
                    "kaynak": "PAPER"})
    return out


def acik_pozisyonlar_birlesik() -> tuple:
    """(pozisyonlar, kaynak) — canlıda futures, paper modda paper.

    v58 (K-56): `futures_pozisyon_raporu` (/fpoz) pozisyonları KOŞULSUZ
    `acik_futures_pozisyonlar()`'dan okuyordu. Paper modda bot futures'ta
    hiç işlem yapmadığı için liste HEP BOŞ geliyor ve rapor
    "📭 AÇIK POZİSYON YOK" diyordu — panelde 2 açık pozisyon dururken.

    Daha kötüsü: K-33 aynı raporun BAKİYESİNİ paper'a çevirmişti. Yani
    rapor PAPER bakiyesini FUTURES pozisyonlarıyla birlikte gösteriyordu
    — iki farklı kaynak tek raporda, ve tutarlı görünüyordu.
    Kullanıcı bildirdi (2026-09-06). K-33'ün YARIM KALMIŞ hâli:
    etiket düzeltilmiş, veri kaynağı düzeltilmemişti.
    """
    try:
        futures = acik_futures_pozisyonlar()
    except Exception as e:
        log.warning(f"[POZİSYON] futures listesi alınamadı: "
                    f"{type(e).__name__}: {e}")
        futures = []
    if futures:
        return futures, "FUTURES"
    try:
        from data.database import acik_tradeler
        return _paper_pozlari_esle(acik_tradeler("PAPER")), "PAPER"
    except Exception as e:
        # fail-loud (§5.2): sessizce boş dönmek "pozisyon yok" diye
        # okunur ve tam da bu hatanın tekrarı olur.
        log.error(f"[POZİSYON] paper listesi alınamadı: "
                  f"{type(e).__name__}: {e}")
        return [], "HATA"


def futures_pozisyon_raporu(chat_id=CHAT_ID):
    """Açık futures pozisyon raporu.

    v58 (K-33): PAPER MODDA BAKİYE YANILTICIYDI. Bu rapor koşulsuz
    `futures_bakiye()` gösteriyordu — testnet futures hesabının
    bakiyesi (ölçülen: 4999.60). Ama paper modda bot futures'ta HİÇ
    işlem yapmıyor; gerçek paper bakiyesi 9819.16'ydı.
    Kullanıcı panelde 10000, Telegram'da 5k görüp haklı olarak
    "hangisi doğru?" diye sordu. İkisi de doğruydu ama FARKLI ŞEYİ
    ölçüyordu ve rapor bunu söylemiyordu.
    """
    try:
        # v58 (K-56): kaynak MODA göre seçilir. Eskiden koşulsuz
        # futures'tan okuyordu; paper modda liste hep boş geldiği için
        # rapor "AÇIK POZİSYON YOK" diyordu (panelde 2 pozisyon varken).
        pozlar, _poz_kaynak = acik_pozisyonlar_birlesik()
        if LIVE_TRADING:
            bakiye = futures_bakiye()
            bakiye_etiket = "Futures Bakiye"
        else:
            bakiye = paper_trader.bakiye
            bakiye_etiket = "Paper Bakiye"
        metrics.acik_pozisyon.set(len(pozlar))
        if not pozlar:
            mesaj = f"📭 <b>AÇIK POZİSYON YOK</b>\n💰 {bakiye_etiket}:{bakiye:.2f}USDT"
        else:
            satirlar = ""; mevcut_fiyatlar = {}
            for p in pozlar:
                guncel = guncel_fiyat_al(p["sembol"]); mevcut_fiyatlar[p["sembol"]] = guncel
                emoji  = "🟢" if p["yon"] == "LONG" else "🔴"
                # ── v58 (K-57): PnL, RAPORUN KENDİ ÇEKTİĞİ FİYATTAN ────
                # Eskiden `p["pnl"]` kullanılıyordu: rapor `guncel`i taze
                # çekiyor ama PnL'i BAŞKA bir kaynaktan (analiz cache'i)
                # alıyordu. İki fiyat kaynağı tek satırda.
                # Gözlenen sonuç: "Giriş:765.0995 Güncel:758.2000
                # ✅ PnL:+0.0000USDT" — pozisyon zararda, rapor kârda
                # gösteriyor. Cache boşsa PnL sessizce 0 kalıyordu.
                # Artık aynı satırdaki `guncel` ile hesaplanıyor →
                # gösterilen fiyat ile gösterilen PnL TUTARLI.
                _mik = float(p.get("miktar") or 0)
                _gir = float(p.get("giris") or 0)
                if guncel and _gir and _mik:
                    _pnl = round((guncel - _gir) * _mik if p["yon"] == "LONG"
                                 else (_gir - guncel) * _mik, 4)
                else:
                    _pnl = float(p.get("pnl") or 0)
                pnl_e  = "✅" if _pnl >= 0 else "❌"
                satirlar += (f"\n{emoji} <b>{p['sembol']}</b> {p['yon']} x{p['kaldirac']}\n"
                             f"  Giriş:{p['giris']:,.4f} Güncel:{guncel:,.4f}\n"
                             f"  {pnl_e} PnL:{_pnl:+.4f}USDT\n")
            tehlikeli = risk_manager.likidasyon_guard(pozlar, mevcut_fiyatlar)
            likit_str = "".join(f"\n🚨 {t['sembol']} likit uzaklık:%{t['uzaklik_pct']:.1f}"
                                for t in tehlikeli)
            mesaj = (f"📊 <b>AÇIK {_poz_kaynak} POZİSYONLAR</b>\n━━━━━━━━━━━━━━━━━━\n"
                     f"{satirlar}━━━━━━━━━━━━━━━━━━\n"
                     f"💰 {bakiye_etiket}:{bakiye:.2f}USDT | Toplam:{len(pozlar)}\n"
                     f"📉 DD:%{risk_manager.drawdown_pct():.2f}{likit_str}")
        telegram_gonder(mesaj, chat_id); return mesaj
    except Exception as e:
        log.error(f"Pozisyon raporu hatası: {e}"); return ""

def multi_coin_tara(coins=COINS, chat_id=CHAT_ID):
    en_iyi_skor = -999; en_iyi = None
    for sembol in coins:
        s = coin_analiz(sembol, period=ANA_PERIOD, interval=ANA_INTERVAL)
        if s and s["ai_score"] > en_iyi_skor:
            en_iyi_skor = s["ai_score"]; en_iyi = s
    if en_iyi:
        telegram_gonder(f"🔍 <b>SCANNER v12</b>\n🏆 {en_iyi['sembol']}:{en_iyi['son_close']:,.2f}\n"
                        f"AI:{en_iyi_skor} | {en_iyi.get('rejim')} | {en_iyi['karar']}", chat_id)
    return en_iyi

def backtest_calistir_full(sembol="BTCUSDT"):
    log.info(f"Backtest v12 başlıyor: {sembol}")
    df = veri_indir(sembol, period="90d", interval="1h")
    if df is None: return
    close = close_al(df); X, y = feature_olustur(df, sembol)
    if X.empty: return
    model, acc, _, model_adi = en_iyi_model_yukle_veya_egit(X, y, sembol)
    if model is None: return
    from sklearn.ensemble import RandomForestClassifier
    pkf = purged_kfold_cv(X, y, RandomForestClassifier,
                           {"n_estimators": 200, "max_depth": 8, "random_state": 42, "n_jobs": -1})
    ew  = expanding_window_cv(X, y, RandomForestClassifier,
                               {"n_estimators": 200, "max_depth": 8, "random_state": 42, "n_jobs": -1})
    tahmin_seri = pd.Series(model.predict(X), index=X.index)
    sinyaller   = tahmin_seri.map({1: 1, 0: -1}).reindex(close.index).fillna(0)
    sonuc       = backtest_calistir(df, sinyaller, close)
    backtest_kaydet(sembol=sembol, baslangic=str(close.index[0]), bitis=str(close.index[-1]),
                    toplam_islem=sonuc["toplam_islem"], kazanan=sonuc["kazanan"],
                    kaybeden=sonuc["kaybeden"], win_rate=sonuc["win_rate"],
                    toplam_getiri=sonuc["toplam_getiri"], max_drawdown=sonuc["max_drawdown"],
                    sharpe=sonuc["sharpe"], params={"model": model_adi})
    mesaj = (f"📊 <b>BACKTEST v12 — {sembol}</b>\nModel:{model_adi}\n"
             f"İşlem:{sonuc['toplam_islem']} WR:%{sonuc['win_rate']}\n"
             f"Getiri:%{sonuc['toplam_getiri']} Sharpe:{sonuc['sharpe']}\n"
             f"Max DD:%{sonuc['max_drawdown']}\n"
             f"Purged K-Fold:{pkf['ortalama']:.3f}±{pkf['std']:.3f} AUC:{pkf['auc_ort']:.3f}\n"
             f"Expanding WF:{ew['ortalama']:.3f} Trend:{ew['trend']}")
    print(mesaj); telegram_gonder(mesaj)


# ── v28: Giriş gecikme ölçümü (kanıtlama için) ────────────
# v31: Gecikme artık işlem SONUCU (PnL) ile ilişkilendiriliyor.
# Böylece "gecikme gerçekten zarar veriyor mu?" sorusu veriyle yanıtlanır.
from config import (MAX_GIRIS_KAYMA_PCT, MAX_GIRIS_KAYMA_STOP_PAYI,
                        FUTURES_SL_ATR_MULT, HIZLI_TARAMA, STATE_RECOVERY)
# v41: Teşhis fonksiyonları core/teshis.py'ye taşındı (modülerleştirme).
# main.py'deki tüm mevcut çağrılar geriye dönük uyumlu olarak çalışır.
from core.teshis import (
    _giris_gecikme_kaydet, gecikme_pnl_esle, giris_gecikme_ozet,
    _veto_kaydet, _islem_acildi_kaydet, veto_ozet,
    _giris_gecikme_log, _acik_giris_gecikme, _veto_sayac,
)


def _execution_isle(sonuc: dict) -> None:
    """
    v12: EdgeEngine filtresi + self-training feature iletimi.
    Execution Layer üzerinden futures işlem açar/kapatır.
    """
    if not LIVE_TRADING:
        return

    sembol  = sonuc["sembol"]
    karar   = sonuc.get("karar", "")
    is_buy  = "BUY" in karar
    is_sell = "SELL" in karar
    if not is_buy and not is_sell:
        return

    try:
        # ── v28: CANLI FİYAT + GECİKME ÖLÇÜMÜ ─────────────
        # Eski sorun: sonuc["son_close"] = kapanmış mumun fiyatı (stale).
        # Sinyal doğduktan sonra analiz+kontrol katmanları saniyeler alıyordu;
        # işlem stale fiyatla açılınca gerçekte geç giriliyordu.
        _stale_fiyat = sonuc["son_close"]
        _sinyal_ts   = sonuc.get("sinyal_ts", time.time())
        _canli = None
        try:
            _canli = futures_anlık_fiyat(sembol)
        except Exception as _cf_e:
            log.debug(f"[EXEC ISLE] {sembol} canlı fiyat alınamadı: {_cf_e}")

        if _canli and _canli > 0:
            # Sinyal anından bu ana kadar fiyat ne kadar kaçmış?
            _kayma_pct = abs(_canli - _stale_fiyat) / _stale_fiyat * 100
            _gecikme_sn = time.time() - _sinyal_ts
            log.info(f"[EXEC ISLE] {sembol} sinyal→emir gecikme={_gecikme_sn:.1f}s "
                     f"fiyat kayması=%{_kayma_pct:.3f} "
                     f"(stale={_stale_fiyat:.2f} → canlı={_canli:.2f})")

            # SLIPPAGE GUARD: fiyat sinyal yönünün ALEYHİNE çok kaçtıysa iptal et
            # (geç kaldık, artık iyi giriş değil — kovalama yapma)
            # v31: Eşik volatiliteye uyarlanır. Volatil coinde sabit %0.35 fazla
            # işlemi iptal eder; ATR'nin küçük bir oranını taban eşiğe ekle.
            _yon_buy = "BUY" in karar
            _aleyhte = ((_yon_buy and _canli > _stale_fiyat) or
                        (not _yon_buy and _canli < _stale_fiyat))
            _atr_pct = (sonuc.get("son_atr", 0) / _stale_fiyat * 100) if _stale_fiyat > 0 else 0
            # Uyarlanabilir eşik: taban + ATR'nin %15'i.
            #
            # ── v58 (K-95): TAVAN ARTIK ATR İLE ÖLÇEKLENİYOR ──────────
            # Eski tavan `MAX_GIRIS_KAYMA_PCT * 2` = %0.70 MUTLAK sabitti
            # ve uyarlamayı SÖNDÜRÜYORDU. ÖLÇÜLDÜ (§0.35 Bulgu 2):
            #   tavanın bağladığı nokta : ATR% > 2.33
            #   medyan 4h ATR%          : 2.43   ← medyan coin ZATEN tavanda
            #   tavana dayanan          : 27/50 (%54)
            #   ETHFIUSDT ATR%=6.81     : amaçlanan %1.37 → kırpılmış %0.70
            #
            # Kök neden K-78/K-82/K-83 ile aynı sınıf: %0.35 tabanı 5m
            # döneminde kalibre edilmişti. 5m'de sinyal fiyatı en fazla
            # 5 dk bayat; 4h'de 4 SAATE kadar bayat olabilir.
            #
            # Tavan artık STOP MESAFESİNDEN türüyor (SL = SL_MULT × ATR):
            # girişten önce stop mesafesinin en fazla 1/3'ünü veririz.
            # Normal ATR aralığında bağlayıcı olan asıl uyarlama terimidir;
            # tavan yalnızca bozuk/absürt ATR'ye karşı akıl sağlığı sınırı.
            # TEK KAYNAK: hesap `futures_trade_engine`'de (davranışsal
            # olarak test edilebilsin ve iki yerde ayrışmasın diye).
            from engines.futures_trade_engine import giris_kayma_esigi
            _kayma_esik = giris_kayma_esigi(_atr_pct)
            if _aleyhte and _kayma_pct > _kayma_esik:
                log.warning(f"[EXEC ISLE] ⏱️ {sembol} GEÇ GİRİŞ İPTALİ: fiyat "
                            f"%{_kayma_pct:.2f} aleyhe kaçtı (eşik %{_kayma_esik:.2f}, "
                            f"ATR-uyarlı) — kovalama yapılmıyor")
                _giris_gecikme_kaydet(sembol, _gecikme_sn, _kayma_pct, iptal=True)
                _veto_kaydet("slippage_gec_giris", sembol)
                return
            _giris_gecikme_kaydet(sembol, _gecikme_sn, _kayma_pct, iptal=False)
            fiyat = _canli   # CANLI fiyattan gir
        else:
            fiyat = _stale_fiyat   # canlı alınamazsa stale'e düş (güvenli)

        atr    = sonuc.get("son_atr", fiyat * 0.01)
        rejim  = sonuc.get("rejim", "RANGE")
        ai_score = sonuc.get("ai_score", 0)

        # ── v12: EdgeEngine filtresi ──────────────────────
        # ── v16: Kill Switch + Circuit Breaker + Correlation ─
        if kill_switch and not kill_switch.kontrol():
            log.warning(f"[EXEC ISLE] {sembol} Kill Switch — durduruldu")
            _veto_kaydet("kill_switch", sembol)
            return
        if circuit_breaker and not circuit_breaker.kontrol(sembol):
            log.warning(f"[EXEC ISLE] {sembol} Circuit Breaker — durduruldu")
            _veto_kaydet("circuit_breaker", sembol)
            return
        # BUG FIX v17: yon, correlation_eng kontrolünden ÖNCE tanımlanmalı
        yon = "LONG" if is_buy else "SHORT"

        # v26: Çoklu borsa fiyat doğrulama — manipülasyon/hatalı fiyat vetosu
        # v58 (K-103): ORTAK MODÜLE ÇIKARILDI — paper da aynı kapıdan geçiyor.
        # Bu kapı yalnızca burada olduğu için paper canlıdan %4 gevşekti.
        _mex_ok, _mex_sebep = coklu_borsa_gecerli_mi(sembol, fiyat, yon, sonuc)
        if not _mex_ok:
            log.warning(f"[EXEC ISLE] 🛡️ {sembol} ÇOKLU BORSA VETO: {_mex_sebep}")
            _veto_kaydet("coklu_borsa", sembol)
            return
        if sonuc.get("_mex_celiski"):
            log.info(f"[EXEC ISLE] {sembol} arbitraj sinyali işlem yönüyle "
                     f"({yon}) çelişiyor — dikkatli")

        # v24: Strateji dayanıklılık kapısı — reddedilen coin'de YENİ pozisyon açma
        if _strateji_onay.get(sembol, True) is False:
            _karar = _strateji_karar_cache.get(sembol)
            _skor  = _karar.skor if _karar else 0
            log.info(f"[EXEC ISLE] ⛔ {sembol} dayanıklılık reddi (skor={_skor}/100) "
                     f"— yeni pozisyon açılmıyor")
            _veto_kaydet("validator_dayaniklilik", sembol)
            return

        if correlation_eng:
            try:
                from data.binance_futures_client import acik_futures_pozisyonlar as _afp
                _pozlar = _afp()
                _acilabilir, _sebep = correlation_eng.pozisyon_acilabilir_mi(sembol, yon, _pozlar)
                if not _acilabilir:
                    log.info(f"[EXEC ISLE] {sembol} Korelasyon: {_sebep}")
                    _veto_kaydet("korelasyon", sembol)
                    return
            except Exception: pass

        # ── v58 (K-97): SİNYAL VETO ZİNCİRİ ORTAK MODÜLDE ────────
        # MTF cascade + MTF hizalama + EdgeEngine artık
        # `futures_trade_engine.sinyal_veto_zinciri()`'nde. Bu üç kapı
        # BURAYA GÖMÜLÜ olduğu ve `_execution_isle`
        # `if not LIVE_TRADING: return` ile başladığı için PAPER YOLUNDA
        # HİÇ ÇALIŞMIYORLARDI — paper, canlının reddedeceği işlemleri
        # açıyordu (ölçüm: 2026-09-14 07:15, aynı saniyede paper AÇTI /
        # canlı REDDETTİ). §6.0'da v58'den beri açık duran iş.
        #
        # ⚠️ CANLI DAVRANIŞ DEĞİŞMEDİ: sıra, eşikler ve varsayılanlar
        # birebir taşındı. Loglama burada kaldı çünkü mesajlar
        # `[EXEC ISLE]` etiketli ve canlı yola özgü.
        mtf = sonuc.get("mtf_confluence", {})
        # v58 (K-98): `bakiye_fn` TEMBEL — zincir strateji kapısına
        # ULAŞIRSA çağrılır. Bakiyeyi peşinen çekmek, MTF/edge'de
        # zaten ölecek sinyaller için gereksiz REST isteği olurdu
        # (v55 notu; zaten HTTP 429 alıyoruz).
        _gecti, _sebep, _mtf_damp = sinyal_veto_zinciri(
            sonuc, yon, bakiye_fn=futures_bakiye)
        if not _gecti:
            if _sebep == "mtf_cascade":
                # v58 (K-94): TF ADLARI SABİT DEĞİL — hiyerarşiden türer.
                # "?" bilerek: ad gelmiyorsa UYDURMA (§5.1).
                _taban = mtf.get("taban_tf", "?")
                _ust   = mtf.get("ana_trend_tf", "?")
                log.info(f"[EXEC ISLE] {sembol} MTF CASCADE BLOK: "
                         f"{_taban} yönü {_ust} ana trendi ile çelişiyor "
                         f"({_ust}={mtf.get('ana_trend_yon')} {_taban}={yon})")
            elif _sebep == "mtf_hizalama_yok":
                log.info(f"[EXEC ISLE] {sembol} MTF hizalama yok → işlem atlandı")
            elif _sebep == "edge_engine":
                _edge = sonuc.get("edge_sonuc") or {}
                log.info(f"[EXEC ISLE] {sembol} EdgeEngine veto: {_edge.get('sebep','?')}")
            elif _sebep == "strateji_red":
                log.info(f"[EXEC ISLE] {sembol}: {sonuc.get('_strateji_sebep','?')}")
            _veto_kaydet(_sebep, sembol)
            return

        # v55: bakiye bu fonksiyonda TEK kez çekilir (eskiden iki ayrı
        # futures_bakiye() ağ isteği vardı: burada ve pozisyon boyutu
        # hesabında). Sinyal başına gereksiz REST çağrısı + rate-limit tüketimi.
        bakiye = futures_bakiye()

        # v58 (K-98): STRATEJİ ve SİNYAL FİLTRESİ kapıları buradan
        # `sinyal_veto_zinciri`'ye TAŞINDI (yukarıda çağrılıyor).
        # Sebep: ikisi de paper'da YOKTU. `strateji_red` canlı vetoların
        # %12'siydi (804 kez) ve K-97'den sonra açılan İLK paper işlemi
        # (PAXGUSDT) tam buraya takılmıştı. `sinyal_filtresi` sayacı 0
        # görünüyordu ama bu MASKELEMEYDİ — zincirde strateji'den sonra
        # geldiği için sinyaller ona ulaşmıyordu.
        from engines.futures_trade_engine import sl_tp_hesapla

        # Zıt pozisyon kapat (self-training feature'larıyla)
        son_features = _son_features_cache.get(sembol, {})
        if is_buy and pozisyon_var_mi(sembol, "SHORT"):
            exec_engine.pozisyon_kapat(sembol, "SHORT", "BUY_SİNYALİ",
                                       ai_score=ai_score, son_features=son_features)
            time.sleep(0.5)
        elif is_sell and pozisyon_var_mi(sembol, "LONG"):
            exec_engine.pozisyon_kapat(sembol, "LONG", "SELL_SİNYALİ",
                                       ai_score=ai_score, son_features=son_features)
            time.sleep(0.5)

        if pozisyon_var_mi(sembol, yon):
            return

        # ── v58 (K-C): YENİDEN GİRİŞ BEKLEME SÜRESİ ──────────
        # Paper yolundaki kapının CANLI karşılığı (§5.3 — tek tarafta
        # olursa paper canlıyı temsil etmez).
        # Ölçüm (2026-09-02): kapanış→açılış boşluğu medyan 92 sn,
        # minimum 0 sn. Stop yiyen işlemden 1 sn sonra yeni pozisyon
        # açılıyordu; aynı sembolde ters dönüş aynı saniyede oluyordu.
        # Kapanışı DEĞİL yalnızca açılışı engeller.
        try:
            from config import YENIDEN_GIRIS_BEKLEME_SN
            from data.database import son_kapanis_yasi_sn
            # Koşul bugün hep "LIVE" verir (fonksiyon başındaki
            # `if not LIVE_TRADING: return` yüzünden buraya paper modda
            # hiç gelinmez). Yine de sabit yazılmadı: o erken çıkış
            # kaldırılırsa mod sessizce yanlış olurdu.
            _yas = son_kapanis_yasi_sn(sembol, "LIVE" if LIVE_TRADING else "PAPER")
            if _yas is not None and _yas < YENIDEN_GIRIS_BEKLEME_SN:
                log.info(f"[EXEC ISLE] {sembol} son kapanıştan {_yas:.0f}sn "
                         f"geçti < {YENIDEN_GIRIS_BEKLEME_SN}sn → atlandı "
                         f"(yeniden giriş beklemesi)")
                _veto_kaydet("yeniden_giris_beklemesi", sembol)
                return
        except Exception as _ye:
            log.error(f"[EXEC ISLE] {sembol} yeniden giriş beklemesi "
                      f"doğrulanamadı: {_ye} → işlem ATLANDI")
            _veto_kaydet("yeniden_giris_beklemesi_hata", sembol)
            return   # fail-closed (§5.1)

        # Dinamik kaldıraç
        kaldirac = FUTURES_LEVERAGE
        if risk_manager:
            kaldirac = risk_manager.dinamik_kaldirac_hesapla(fiyat, atr)

        # ── v18 + v20: Dynamic Kelly → MVO limiti → Dampening ─
        win_rate = sonuc.get("yukselis_guveni", 55) / 100
        usdt = risk_manager.pozisyon_buyuklugu_hesapla(
            bakiye, fiyat, atr, win_rate, sembol=sembol) if risk_manager else TRADE_USDT

        # v20: MVO portfolio limiti — Kelly'yi yukarıdan kırpar
        try:
            _mvo_limit = portfolio_optimizer.coin_usdt_limiti(
                sembol, _portfolio_getiri_serileri, bakiye, fallback_usdt=usdt
            )
            if _mvo_limit < usdt:
                log.info(f"[MVO] {sembol} Kelly={usdt:.1f} → MVO={_mvo_limit:.1f} USDT")
                usdt = _mvo_limit
        except Exception as _mvo_e:
            log.debug(f"[MVO] {sembol}: {_mvo_e}")

        # ── v27: BİRLEŞİK DAMPENİNG (çarpımsal yığılma önlendi) ──
        try:
            from config import POZ_MIN_DAMP_TABANI, POZ_AGRESIFLIK
        except ImportError:
            POZ_MIN_DAMP_TABANI, POZ_AGRESIFLIK = 0.45, 1.0
        _damp = 1.0
        _damp_sebep = []

        # v18: Ensemble belirsizlik
        _belirsizlik = sonuc.get("model_belirsizlik", 0.0)
        if _belirsizlik > 0.20:
            _damp *= 0.65; _damp_sebep.append(f"belirsizlik-yüksek")
        elif _belirsizlik > 0.15:
            _damp *= 0.85; _damp_sebep.append(f"belirsizlik-orta")

        # v18: CVD Divergence
        if sonuc.get("cvd_data", {}).get("divergence", False):
            _damp *= 0.85; _damp_sebep.append("cvd-divergence")

        # RegimeAdapter risk çarpanı + kaldıraç
        try:
            regime_adapter.rejim_guncelle(rejim, sembol)
            rkonfig = regime_adapter.aktif_konfig(sembol)
            if rkonfig:
                kaldirac = min(kaldirac, rkonfig.kaldirac_max)
                _damp *= rkonfig.risk_carpani
                _damp_sebep.append(f"rejim({rkonfig.risk_carpani:.2f})")
        except Exception:
            pass

        # v19: MTF hizalama
        if _mtf_damp < 1.0:
            _damp *= _mtf_damp; _damp_sebep.append(f"mtf({_mtf_damp:.2f})")

        # v26: Çoklu borsa çelişkisi
        if sonuc.get("_mex_celiski"):
            _damp *= 0.7; _damp_sebep.append("multiex-çelişki")

        # ── TABAN KORUMASI: birleşik dampening tabanın altına inemez ──
        _damp = max(_damp, POZ_MIN_DAMP_TABANI)
        usdt *= _damp

        # v26: Çoklu borsa teyidi → küçük artış (tabandan SONRA, ödül olarak)
        if sonuc.get("_mex_teyit", 0) > 0:
            usdt *= (1.0 + min(sonuc["_mex_teyit"] * 0.15, 0.15))

        # v27: Genel agresiflik çarpanı (kullanıcı ayarı)
        usdt *= POZ_AGRESIFLIK

        if _damp_sebep:
            log.info(f"[EXEC ISLE] {sembol} dampening={_damp:.2f} "
                     f"[{', '.join(_damp_sebep)}] (taban {POZ_MIN_DAMP_TABANI})")

        usdt = min(usdt, bakiye * 0.9)
        levels = sl_tp_hesapla(fiyat, yon, atr, rejim)

        # Execution Engine üzerinden aç (ACK + fill verify + SL doğrulama dahil)
        sonuc_exec = exec_engine.pozisyon_ac(
            sembol   = sembol,
            yon      = yon,
            usdt     = usdt,
            sl       = levels["sl"],
            tp1      = levels["tp1"],
            tp2      = levels["tp2"],
            kaldirac = kaldirac,
            rejim    = rejim,
            ai_score = ai_score,
            kaynak   = sonuc.get("strateji", "SIGNAL"),
        )

        if sonuc_exec.basarili:
            log.info(f"[EXEC ISLE] ✅ {sonuc_exec}")
            _islem_acildi_kaydet()   # v32: başarılı açılış sayacı
            # v23: R:R hesabı için risk metadata'yı cache'e yaz
            # (pozisyon kapanınca _on_position_closed bunu okuyacak)
            try:
                _sl_mesafe_pct = abs(fiyat - levels["sl"]) / fiyat * 100 if fiyat > 0 else 1.0
                _tp_mesafe_pct = abs(levels["tp1"] - fiyat) / fiyat * 100 if fiyat > 0 else 1.5
                _rr = _tp_mesafe_pct / max(_sl_mesafe_pct, 0.01)
                with _son_analizler_lock:
                    if sembol in _son_analizler:
                        _son_analizler[sembol]["risk_usdt"]   = round(usdt * _sl_mesafe_pct / 100, 4)
                        _son_analizler[sembol]["rr_planlanan"] = round(_rr, 3)
                        _son_analizler[sembol]["giris"]        = fiyat
            except Exception as _rm_e:
                log.debug(f"[RR META] {_rm_e}")
            if _tg_bildirilmeli(sonuc):
                _telegram_rapor(sonuc)
        else:
            log.warning(f"[EXEC ISLE] ❌ {sembol}: {sonuc_exec.hata}")

    except FuturesAPIError as e:
        log.error(f"[EXEC ISLE] {sembol} API hatası: {e}")
        if watchdog: watchdog.hata_bildir(e, sembol)
    except Exception as e:
        log.error(f"[EXEC ISLE] {sembol} hata: {type(e).__name__}: {e}", exc_info=True)
        if watchdog: watchdog.hata_bildir(e, sembol, kritik=True)


def _analytics_rapor_gonder(chat_id=CHAT_ID):
    try:
        sonuclar = {}; fiyat_serileri = {}
        # v55: bakiye döngü DIŞINDA tek kez çekilir. Eskiden her coin için
        # ayrı bir futures_bakiye() ağ isteği yapılıyordu; ayrıca aşağıda
        # hiç kullanılmayan dördüncü bir çağrı daha vardı.
        bakiye = futures_bakiye() or BALANCE
        for sembol in COINS[:3]:
            df = veri_indir(sembol, period="30d", interval="1h")
            if df is None: continue
            close = close_al(df)
            if close.empty: continue
            close.name = sembol
            fiyat_serileri[sembol] = close
            analiz = analytics_engine.tam_analiz(
                sembol=sembol, close=close,
                bakiye=bakiye,
                fiyat_serileri=fiyat_serileri,
            )
            sonuclar[sembol] = analiz
        if not sonuclar: return
        en_riskli = max(sonuclar.items(), key=lambda x: x[1]["var"].var_agirlikli)
        rapor = analytics_engine.telegram_raporu(en_riskli[1])
        telegram_gonder(rapor, chat_id)
        for sembol, analiz in sonuclar.items():
            try:
                from data.db_manager import risk_analytics_kaydet
                risk_analytics_kaydet(
                    sembol=sembol,
                    var_hist=analiz["var"].var_historical,
                    var_param=analiz["var"].var_parametric,
                    var_mc=analiz["var"].var_mc,
                    var_agirlikli=analiz["var"].var_agirlikli,
                    expected_shortfall=analiz["var"].expected_shortfall,
                    portfolio_corr=analiz["korelasyon"].korelasyon_matrix if analiz["korelasyon"] else {},
                    volatility_regime=analiz["rejim"].rejim,
                    drawdown_pct=risk_manager.drawdown_pct(),
                )
            except Exception as e:
                log.warning(f"[ANALYTICS] {sembol} DB kayıt: {e}")
    except Exception as e:
        log.error(f"[ANALYTICS RAPOR] {type(e).__name__}: {e}", exc_info=True)


async def cmd_analytics(u, c):
    cid = str(u.effective_chat.id)
    await _yanitla(u, "⏳ VaR + ES + Korelasyon + HMM analizi yapılıyor...")
    try: _analytics_rapor_gonder(cid)
    except Exception as e: await _yanitla(u, f"❌ Analytics hatası: {e}")

async def cmd_senaryo(u, c):
    cid = str(u.effective_chat.id)
    senaryo = c.args[0].upper() if c.args else "NORMAL"
    gecerli = ["NORMAL", "STRESS", "CRASH", "LATENCY"]
    if senaryo not in gecerli:
        await _yanitla(u, f"Geçerli senaryolar: {', '.join(gecerli)}"); return
    simulator.senaryo_degistir(senaryo)
    await _yanitla(u, f"✅ Simulator senaryo: {senaryo}")

async def cmd_sim(u, c):
    cid = str(u.effective_chat.id)
    sembol = _sembol_normalize(c.args[0] if c.args else None)   # v58 K-52
    await _yanitla(u, f"⏳ {sembol} senaryo testi başlıyor...")
    try:
        fiyat   = anlık_fiyat(sembol) or 50000
        sonuclar = simulator.senaryo_testi(sembol, "LONG", 100, fiyat, n_per_senaryo=50)
        satirlar = [f"🎭 <b>SENARYO TESTİ — {sembol}</b>"]
        for sn, s in sonuclar.items():
            satirlar.append(f"<b>{sn}</b>")
            satirlar.append(f"  Kabul: %{s['kabul_pct']} | Slip: {round(s['p95_slippage_bps'],1)}bps (p95)")
            satirlar.append(f"  Lat: {round(s['p95_latency_ms'],0)}ms (p95) | Fill: %{round(s['ort_fill_pct'],0)}")
        telegram_gonder("\n".join(satirlar), cid, force=True)
    except Exception as e: await _yanitla(u, f"❌ Sim test hatası: {e}")

def heartbeat_loop():
    while True:
        try:
            time.sleep(300)
            oe  = order_engine.istatistik; fo = failover.durum
            wd_dur = watchdog.durum if watchdog else {}
            st_poz = len(state_manager.acik_pozisyonlar())
            ee     = exec_engine.istatistik
            sim_s  = simulator.istatistik
            rc     = order_reconciler.istatistik if order_reconciler else {}
            fs     = failsafe_guard.istatistik
            log.info(f"[HEARTBEAT v12] OE:{oe['basarili']}/{oe['toplam']} "
                     f"Q:{oe['kuyruk_boyutu']} Failover:{'ON' if fo['failover_on'] else 'OFF'} "
                     f"StatePoz:{st_poz} DD:%{risk_manager.drawdown_pct():.1f} "
                     f"WD:{wd_dur.get('saglikli','?')} "
                     f"EXEC:✅{ee['acma_basarili']} ❌{ee['acma_basarisiz']} "
                     f"Reconcile:{rc.get('sync_sayisi',0)} Failsafe:{fs['failsafe_kapatma']} "
                     f"Sim:{sim_s['toplam']}({sim_s['kabul_pct']}%) DB:{db_durum()['backend']}")
            bus.publish("system.heartbeat",
                        {"ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}, "Heartbeat")
        except Exception as e:
            log.error(f"[HEARTBEAT] Hata: {e}")

def futures_dashboard():
    global watchdog
    tablolari_olustur()
    watchdog = get_watchdog(telegram_fn=telegram_gonder)
    # v15: Binance sync burada yapılıyor (import sırasında değil)
    state_manager.binance_ile_sync()
    state_manager.orphan_sl_tp_temizle()

    # ── v28: AÇILIŞ POZİSYON GÜVENLİK KONTROLÜ ────────────
    # Bot çökmüş/yeniden başlamışsa, borsadaki açık pozisyonların
    # SL koruması hâlâ var mı? Korumasız pozisyon = kontrolsüz risk.
    if STATE_RECOVERY:
        try:
            _acik = acik_futures_pozisyonlar()
            if _acik:
                log.warning(f"[RECOVERY] {len(_acik)} açık pozisyon bulundu — "
                            f"SL koruması kontrol ediliyor...")
                # v57: koşullu emirler Algo Service'te; klasik listede yok.
                from data.binance_futures_client import koruma_emirleri
                _korumasiz = []
                for _poz in _acik:
                    _sem = _poz.get("sembol") or _poz.get("symbol", "")
                    try:
                        _emirler = koruma_emirleri(_sem, strict=True)
                        _sl_var = any((e.get("type") or "").upper() in
                                      ("STOP_MARKET", "STOP", "STOP_LOSS_LIMIT",
                                       "TRAILING_STOP_MARKET")
                                      for e in (_emirler or []))
                        if not _sl_var:
                            _korumasiz.append(_sem)
                    except Exception as _ce:
                        log.debug(f"[RECOVERY] {_sem} emir kontrolü: {_ce}")
                if _korumasiz:
                    _msg = ("⚠️ <b>RECOVERY UYARISI</b>\n"
                            f"SL korumasız açık pozisyon(lar): {', '.join(_korumasiz)}\n"
                            "Bot çökmüş olabilir. /fpoz ile kontrol edin, "
                            "gerekirse /fkapat ile kapatın veya manuel SL koyun.")
                    log.critical(f"[RECOVERY] Korumasız pozisyonlar: {_korumasiz}")
                    try: telegram_gonder(_msg)
                    except Exception: pass
                else:
                    log.info("[RECOVERY] ✅ Tüm açık pozisyonların SL koruması mevcut")
        except Exception as _rec_e:
            log.error(f"[RECOVERY] Açılış kontrolü hatası: {_rec_e}")

    # ── v16: Tüm yeni motorlar ───────────────────────────
    global kill_switch, circuit_breaker, correlation_eng, shadow_manager
    global edge_analytics, trade_journal, adaptive_sizing, order_reconciler
    kill_switch     = get_kill_switch(telegram_fn=telegram_gonder)
    circuit_breaker = get_circuit_breaker(telegram_fn=telegram_gonder)
    correlation_eng = get_correlation_engine()
    shadow_manager  = get_shadow_manager()
    edge_analytics  = get_edge_analytics()

    # ── v14: Trade Journal ────────────────────────────────
    # v55: JOURNAL_DB_PATH artık modül düzeyinde import ediliyor (yukarıda),
    # buradaki yerel import kaldırıldı — yerel import global ismi tanımlamıyor
    # ve _strateji_dayaniklilik_dogrula()'yı NameError ile kırıyordu.
    try:
        trade_journal = get_journal(JOURNAL_DB_PATH)
    except Exception as _je:
        log.warning(f"Trade journal başlatılamadı: {_je}")

    # ── v14: Adaptive Sizing ──────────────────────────────
    try:
        from config import TRADE_USDT, MAX_POSITION_USDT
        adaptive_sizing = get_adaptive_sizing(TRADE_USDT, MAX_POSITION_USDT)
    except Exception as _ase:
        log.warning(f"Adaptive sizing başlatılamadı: {_ase}")

    # ── v14: Order Reconciler ─────────────────────────────
    try:
        from config import RECONCILER_INTERVAL
        order_reconciler = get_order_reconciler(state_manager, RECONCILER_INTERVAL)
        order_reconciler.start()
    except Exception as _re:
        log.warning(f"Order reconciler başlatılamadı: {_re}")

    # ── v30: Audit + Failsafe açıkça başlat (artık fabrika otomatik başlatmıyor) ─
    try:
        state_audit.start()
        failsafe_guard.start()
        order_engine.start()      # v30: order engine de açıkça başlatılır
        failover.start()          # v30: failover da açıkça başlatılır
    except Exception as _se:
        log.warning(f"Servis başlatma uyarısı: {_se}")

    # v55: Heartbeat thread'i process başına YALNIZCA BİR KEZ başlatılır.
    # futures_dashboard() live/bot modunda çökme sonrası yeniden çağrıldığında
    # her seferinde yeni bir kalıcı thread doğuyordu (thread sızıntısı).
    global _heartbeat_basladi
    if not _heartbeat_basladi:
        threading.Thread(target=heartbeat_loop, daemon=True, name="Heartbeat").start()
        _heartbeat_basladi = True

    # Demo Binance bağlantı testi
    _demo_bagli = False
    try:
        from data.binance_futures_client import futures_bakiye as _fb
        _demo_bakiye = _fb()
        _demo_bagli = _demo_bakiye > 0
    except Exception as _e: log.debug(f"[SUPPRESS] {_e}")

    telegram_gonder(
        f"🚀 <b>{ASTRA_SURUM_ETIKET}</b>\n"
        f"{'✅ Demo Binance BAĞLI: ' + str(round(_demo_bakiye if _demo_bagli else 0,2)) + ' USDT' if _demo_bagli else '❌ Demo Binance BAĞLANAMADI — API key IP kısıtlamasını kaldırın'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔧 Order Engine  : {'LIVE' if LIVE_TRADING else 'PAPER'}\n"
        f"🔄 Event Bus     : {'Redis' if __import__('config').REDIS_ENABLED else 'Memory'}\n"
        f"📡 WebSocket     : {'Aktif' if _ws_fiyat_fn else 'Pasif'}\n"
        f"🌐 Failover      : {'Aktif' if __import__('config').FAILOVER_ENABLED else 'Pasif'}\n"
        f"💾 State Sync    : Aktif\n"
        f"🐕 Watchdog      : Aktif\n"
        f"🛡️ Execution Layer: Aktif (ACK+Reconcile+Failsafe)\n"
        f"🧠 Self-Training  : Aktif (feedback_ekle + rl_reward)\n"
        f"🔬 EdgeEngine     : Aktif (çok katmanlı sinyal filtresi)\n"
        f"🎯 RegimeAdapter  : Aktif (rejim bazlı parametre adaptasyonu)\n"
        f"📊 Analytics      : VaR+ES+Korrel+HMM\n"
        f"🎭 Simulator      : {simulator.senaryo} senaryo\n"
        f"💾 Database       : {db_durum()['backend'].upper()}\n"
        f"📊 Prometheus    : {'Aktif' if PROMETHEUS_ENABLED else 'Pasif'}\n"
        f"🎲 Monte Carlo   : {MC_SIMULATIONS:,} sim\n"
        f"🪙 Coins         : {len(COINS)} | {', '.join(COINS)}"
    )

    tracker  = PerformanceTracker("BTCUSDT")
    dongu    = 0; son_egitim = {}

    while True:
        try:
            _dongu_baslangic = time.time()
            globals()["_global_dongu_sayaci"] = dongu   # v23: A/B varyant senkronizasyonu
            log.info(f"\n{'='*55}\n[v30] #{dongu} — {datetime.now().strftime('%H:%M:%S')}\n{'='*55}")
            # Watchdog: döngü başında heartbeat — analiz süresince sessiz kalmayı önler
            if watchdog: watchdog.heartbeat("ana_dongu")

            # ── v20: Async Paralel Coin Analizi ──────────────────
            # Eski: sıralı for döngüsü → 5 coin × ~3s = 15s gecikme
            # Yeni: asyncio.gather → tüm coinler paralel → ~3s toplam
            _grafik_iste = (dongu % 3 == 0)

            # v58 (K-75): eşzamanlı ağır analiz TAVANI. Ayrıntı config.py.
            try:
                from config import ANALIZ_ESZAMANLI as _ES
            except ImportError:
                _ES = 3
            _analiz_semaforu = asyncio.Semaphore(max(1, _ES))

            async def _tek_coin_isle(sembol: str) -> None:
                loop = asyncio.get_event_loop()
                async with _analiz_semaforu:
                    await _tek_coin_isle_govde(sembol, loop)

            async def _tek_coin_isle_govde(sembol: str, loop) -> None:
                try:
                    sonuc = await loop.run_in_executor(
                        None,
                        lambda s=sembol: _analiz_al(
                            s, period=ANA_PERIOD, interval=ANA_INTERVAL,
                            grafik=_grafik_iste, market_data_al=True
                        )
                    )
                    if not sonuc:
                        return
                    # v47 KRİTİK DÜZELTME: İşlem kaydı GRAFİKTEN ÖNCE.
                    # Eski sıra: analiz → grafik (yavaş) → sinyal_isle.
                    # 150s tur iptali grafik sırasında vurunca sinyal_isle hiç
                    # çalışmıyordu → 42 sinyal ama 0 paper işlem. Artık işlem
                    # önce kaydedilir; grafik gecikse/iptal olsa bile işlem açılır.
                    paper_trader.sinyal_isle(sonuc)
                    paper_trader.stop_tp_kontrol(sembol, sonuc.get("anlik_fiyat", sonuc["son_close"]))
                    _execution_isle(sonuc)
                    futures_pozisyon_izle(sembol, atr=sonuc.get("son_atr", 0.0))
                    # Grafik (kozmetik) — artık kritik yoldan SONRA
                    # v58 K-40: sabit 5 idi. Rapor eşiğiyle AYNI kaynaktan
                    # türemeli — aksi halde grafik üretilmeden rapor gidebilir
                    # ya da boşuna grafik üretilir.
                    # v58 (K-72): grafik de bildirim kapısına bağlı;
                    # gönderilmeyecek bir grafiği üretmek boşuna CPU.
                    if (abs(sonuc.get("ai_score", 0)) >= TG_MIN_AI_SINYAL
                            and not sonuc.get("grafik_yolu")):
                        try:
                            sonuc["grafik_yolu"] = await loop.run_in_executor(
                                None,
                                lambda s=sonuc: _grafik_olustur(
                                    s["close_obj"], s["rsi_obj"], s["macd_obj"],
                                    s["sig_obj"], s["upper_obj"], s["lower_obj"],
                                    s["ma_obj"], sembol
                                )
                            )
                        except Exception as _ge:
                            log.warning(f"[GRAFİK] {sembol}: {_ge}")
                    try:
                        _gerekli, _sebep = _adaptif_retrain_gerekli_mi(sembol)
                        if _gerekli:
                            log.info(f"[ADAPTIF-TRAIN] {sembol}: {_sebep}")
                            _self_train_tetikle(sembol, 0.0)
                    except Exception:
                        pass
                    # v58 K-40: sabit 7 idi ve ULAŞILAMAZ hale gelmişti.
                    # K-37 sonrası gözlenen en yüksek |AI| = 4 (model katkısı
                    # ±2 nötrlendiği için). Yani grafik/rapor bir daha ASLA
                    # gönderilmezdi — sessizce. Eşik artık girişin kendisiyle
                    # aynı: bot işlem açacak kadar güçlü bulduysa raporlar.
                    if _tg_bildirilmeli(sonuc):
                        _telegram_rapor(sonuc)
                except FuturesAPIError as fe:
                    log.error(f"[DÖNGÜ] {sembol} API hatası: {fe}")
                    if watchdog: watchdog.hata_bildir(fe, sembol)
                except Exception as e:
                    log.error(f"[DÖNGÜ] {sembol}: {type(e).__name__}: {e}", exc_info=True)
                    if watchdog: watchdog.hata_bildir(e, sembol, kritik=True)
                    try:
                        fiyat = guncel_fiyat_al(sembol)
                        if fiyat and sembol not in _son_analizler:
                            _son_analizler[sembol] = {
                                "sembol": sembol, "son_close": fiyat,
                                "ai_score": 0, "confidence": 0,
                                "karar": "⚠️ HATA", "rejim": "?",
                                "edge_sonuc": {"gecti": False},
                                "hata": str(e)[:80]
                            }
                    except Exception as _e:
                        log.debug(f"[SUPPRESS] {_e}")

            try:
                _loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_loop)
                # v34: Tüm coin turu için TAVAN SÜRE. Testnet/ağ yavaşlığında
                # döngünün dakikalarca takılıp watchdog alarmı vermesini önler.
                # 150s'de bitmezse iptal et, bir sonraki tura geç (heartbeat korunur).
                try:
                    from config import COIN_TUR_TIMEOUT as _CTT
                except ImportError:
                    _CTT = 150
                _loop.run_until_complete(
                    asyncio.wait_for(
                        # v58 (K-82): SIRA HER TURDA KAYDIRILIYOR.
                        # Tur iptal edilirse hep AYNI kuyruk analiz
                        # edilmeden kalıyordu (ölçüm: 39/50'de takıldı,
                        # eksiklerin 10'u listenin son 10 coini).
                        # Kaydırma, iptal olsa bile her coinin sırayla
                        # öne geçmesini garanti eder.
                        asyncio.gather(*[_tek_coin_isle(s)
                                         for s in _tur_sirasi(COINS, dongu)],
                                       return_exceptions=True),
                        timeout=_CTT
                    )
                )
                log.info(f"[PARALEL] {len(COINS)} coin "
                         f"{time.time()-_dongu_baslangic:.1f}s'de tamamlandı")
            except asyncio.TimeoutError:
                log.warning(f"[PARALEL] Coin turu {_CTT}s tavanını aştı — "
                            f"iptal edildi, sonraki tura geçiliyor (ağ yavaş olabilir)")
                if watchdog: watchdog.heartbeat("ana_dongu_timeout")
            except Exception as _pe:
                log.error(f"[PARALEL] {_pe} — sıralı fallback devrede")
                for sembol in COINS:
                    try:
                        sonuc = _analiz_al(sembol, period=ANA_PERIOD, interval=ANA_INTERVAL,
                                           grafik=(dongu % 3 == 0), market_data_al=True)
                        if not sonuc: continue
                        paper_trader.sinyal_isle(sonuc)
                        paper_trader.stop_tp_kontrol(sembol, sonuc.get("anlik_fiyat", sonuc["son_close"]))
                        _execution_isle(sonuc)
                        futures_pozisyon_izle(sembol, atr=sonuc.get("son_atr", 0.0))
                        if _tg_bildirilmeli(sonuc):   # v58 K-72
                            _telegram_rapor(sonuc)
                    except Exception as _fe:
                        log.error(f"[FALLBACK] {sembol}: {_fe}")
            finally:
                # v34: Event loop'u her turda kapat — sızıntı önle.
                # (wait_for timeout'ta bekleyen task'ları da iptal eder)
                try:
                    _bekleyen = asyncio.all_tasks(_loop)
                    for _t in _bekleyen:
                        _t.cancel()
                    if _bekleyen:
                        _loop.run_until_complete(
                            asyncio.gather(*_bekleyen, return_exceptions=True))
                except Exception:
                    pass
                try:
                    _loop.close()
                except Exception:
                    pass

            # v20: Portfolio getiri serilerini güncelle (MVO için)
            # v23 fix: log-return serisi + son fiyatı AYRI sakla (önceki sürümde
            # son log-return değeri yanlışlıkla fiyat olarak kullanılıyordu)
            try:
                import numpy as _np_pgo
                import pandas as _pd_pgo
                with _son_analizler_lock:
                    _snapshot = {s: a.get("son_close", 0)
                                 for s, a in _son_analizler.items()}
                for _s, _fiyat in _snapshot.items():
                    if not _fiyat or _fiyat <= 0:
                        continue
                    _kayit   = _portfolio_getiri_serileri.get(_s)
                    _son_fiyat = _portfolio_son_fiyat.get(_s, 0)
                    if _kayit is None:
                        _portfolio_getiri_serileri[_s] = _pd_pgo.Series(dtype=float)
                        _portfolio_son_fiyat[_s] = _fiyat
                        continue
                    if _son_fiyat > 0:
                        _lr  = float(_np_pgo.log(_fiyat / _son_fiyat))
                        _yeni= _pd_pgo.concat([_kayit, _pd_pgo.Series([_lr])],
                                               ignore_index=True).iloc[-500:]
                        _portfolio_getiri_serileri[_s] = _yeni
                    _portfolio_son_fiyat[_s] = _fiyat
            except Exception as _pgo_e:
                log.debug(f"[PORTFOLIO GETİRİ] {_pgo_e}")

            # Panel: döngü sonunda state'i garantili güncelle
            try:
                _futures_pozlar = acik_futures_pozisyonlar()
                _paper_pozlar = []
                if not _futures_pozlar:
                    try:
                        from data.database import acik_tradeler
                        _raw = acik_tradeler("PAPER")
                        _paper_pozlar = _paper_pozlari_esle(_raw)
                    except Exception as _pe:
                        log.debug(f"[PAPER POZ] {_pe}")

                # Paper toplam PnL hesapla
                _paper_toplam_pnl = sum(p.get("pnl", 0) for p in _paper_pozlar)

                # Kill switch + adaptive sizing durumunu da gönder
                _ks_durum = kill_switch.durum if kill_switch else {"aktif": True, "consecutive_loss": 0}
                _as_durum = adaptive_sizing.durum if adaptive_sizing else {"kayip_seri": 0, "base_usdt": 20}
                # Paper toplam PnL
                try:
                    from data.database import toplam_pnl as _db_pnl
                    _paper_total = _db_pnl("PAPER")
                except Exception as _ex:
                    log.debug(f"[SUPPRESS] {_ex}")
                    _paper_total = _paper_toplam_pnl
                _fb2 = futures_bakiye()
                _gelismis = _gelismis_state_topla()   # v25: yeni motor durumları
                state_guncelle(
                    son_analiz=_son_analizler,
                    acik_pozisyonlar=_futures_pozlar or _paper_pozlar,
                    futures_bakiye=_fb2 or paper_trader.bakiye,
                    paper_bakiye=paper_trader.bakiye,
                    para_dokumu=paper_trader.para_dokumu(),   # v58 K-42
                    live_trading=LIVE_TRADING and _fb2 > 0,
                    gunluk_pnl=risk_manager.gunluk_pnl or _paper_toplam_pnl,
                    toplam_pnl=risk_manager.toplam_pnl or _paper_total,
                    risk_durumu=_risk_durum_str(),
                    kill_switch=_ks_durum,
                    adaptive_sizing=_as_durum,
                    **_gelismis,
                )
                log.debug(f"[PANEL] {len(_son_analizler)} coin, {len(_paper_pozlar)} poz")
            except Exception as _se:
                log.warning(f"[STATE_GUNCELLE] {_se}")

            if dongu % 6 == 0:
                for sembol in COINS:
                    try:
                        gecen = time.time() - son_egitim.get(sembol, 0)
                        if gecen > MODEL_RETRAIN_INTERVAL:
                            df_r = veri_indir(sembol, period="14d", interval="1h")
                            if df_r is not None:
                                X_r, y_r = feature_olustur(df_r, sembol)
                                if not X_r.empty:
                                    en_iyi_model_yukle_veya_egit(X_r, y_r, sembol, yeniden_egit_suresi=0)
                                    son_egitim[sembol] = time.time()
                    except Exception as e:
                        log.error(f"[RETRAIN] {sembol}: {e}")

            if dongu % 12 == 0 and dongu > 0:
                try:
                    telegram_gonder(tracker.telegram_raporu())
                    futures_pozisyon_raporu()
                    # v49: bakiye TEK kez çekilir (eskiden 2 ayrı ağ isteği vardı)
                    bakiye = futures_bakiye()
                    telegram_gonder(risk_manager.durum_raporu(bakiye))
                    pozlar = acik_futures_pozisyonlar()
                    portfolio_state_kaydet(
                        bakiye=bakiye, acik_poz=len(pozlar),
                        toplam_pnl=risk_manager.toplam_pnl,
                        gunluk_pnl=risk_manager.gunluk_pnl,
                        drawdown_pct=risk_manager.drawdown_pct(),
                        marjin_kullanim=0, snapshot={"pozlar": pozlar}
                    )
                except Exception as e:
                    log.error(f"[PERİYODİK] Rapor hatası: {e}")

            if dongu % 24 == 0 and dongu > 0:
                try: monte_carlo_raporu()
                except Exception as e: log.error(f"[MC] {e}")
                try: _analytics_rapor_gonder()
                except Exception as e: log.error(f"[ANALYTICS] {e}")

            # v24: Periyodik strateji dayanıklılık doğrulaması (~her 6 saat = 36 döngü)
            if dongu % 36 == 0 and dongu > 0:
                try:
                    log.info("[VALIDATOR] Periyodik dayanıklılık doğrulaması...")
                    _vsonuc = _strateji_dayaniklilik_dogrula()
                    _reddedilen = [s for s, k in _vsonuc.items() if not k.onay]
                    if _reddedilen:
                        telegram_gonder(
                            f"🛡️ <b>DAYANIKLILIK UYARISI</b>\n"
                            f"Şu coin'lerde yeni pozisyon durduruldu (zayıf dayanıklılık):\n"
                            f"{', '.join(_reddedilen)}\n"
                            f"Detay: /validate [coin]",
                            tip="validator"
                        )
                except Exception as e:
                    log.error(f"[VALIDATOR] Periyodik doğrulama hatası: {e}")

            # v21: Haftalık RL eğitimi (~7 gün × 24h × 6 döngü/saat = 1008)
            if dongu % 1008 == 0 and dongu > 0:
                try:
                    log.info("[RL] Haftalık PPO eğitimi başlatılıyor...")
                    for _rl_sembol in COINS[:2]:   # Önce BTC + ETH
                        _rl_df = veri_indir(_rl_sembol, period="60d", interval="1h")
                        if _rl_df is not None:
                            _rl_X, _rl_y = feature_olustur(_rl_df, _rl_sembol)
                            if not _rl_X.empty:
                                rl_arka_plan_egitim(
                                    _rl_sembol,
                                    close_al(_rl_df),
                                    _rl_X,
                                    baslangic_bakiye=futures_bakiye() or BALANCE
                                )
                except Exception as _rl_e:
                    log.error(f"[RL HAFTALIK] {_rl_e}")

            # v21: A/B test raporu (her 12 döngü = ~2 saat)
            if dongu % 12 == 1 and dongu > 30:   # 30 döngü sonra başla
                try:
                    rapor = ab_manager.telegram_raporu()
                    telegram_gonder(rapor, tip="ab_test")
                except Exception as _ab_pe: log.debug(f"[A/B RAPOR] {_ab_pe}")

            if dongu % 30 == 0 and dongu > 0:
                try:
                    oe  = order_engine.istatistik; wd = watchdog.durum if watchdog else {}
                    # v55: `reconciler` diye bir global yok — doğru isim
                    # `order_reconciler`. Bu NameError yüzünden periyodik
                    # sistem durumu raporu hiç gönderilmiyordu.
                    ee  = exec_engine.istatistik
                    rc  = order_reconciler.istatistik if order_reconciler else {}
                    fs  = failsafe_guard.istatistik; sa = state_audit.istatistik
                    telegram_gonder(
                        f"⚙️ <b>SİSTEM DURUMU v12</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"OE: ✅{oe.get('basarili',0)} ❌{oe.get('basarisiz',0)} "
                        f"Q:{oe.get('kuyruk_boyutu',0)}\n"
                        f"Failover:{'🔴 Backup' if failover.durum['failover_on'] else '🟢 Primary'}\n"
                        f"StatePoz:{len(state_manager.acik_pozisyonlar())}\n"
                        f"WD Sağlık:{'✅' if wd.get('saglikli', True) else '⚠️'}\n"
                        f"DD:%{risk_manager.drawdown_pct():.2f}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🛡️ Execution Layer:\n"
                        f"  Açma: ✅{ee.get('acma_basarili',0)} ❌{ee.get('acma_basarisiz',0)} "
                        f"SL fail:{ee.get('sl_basarisiz',0)}\n"
                        f"  Slippage red:{ee.get('slippage_red',0)} "
                        f"Dup:{ee.get('duplicate_engel',0)}\n"
                        # v55: Bu satırlar kaldırılmış FillReconciler'ın anahtarlarını
                        # (orphan_iptal/sl_yeniden/tp_yeniden) kullanıyordu; isim
                        # düzeltilse bile KeyError verirdi. OrderReconciler'ın
                        # gerçek anahtarlarına eşlendi + .get() ile korundu.
                        f"  Reconcile sync:{rc.get('sync_sayisi',0)} "
                        f"Phantom:{rc.get('phantom_duzeltme',0)}\n"
                        f"  SL onarım:{rc.get('sl_onarim',0)} TP onarım:{rc.get('tp_onarim',0)}\n"
                        f"  Audit uyarı:{sa.get('uyari_sayisi',0)} Kritik:{sa.get('kritik_sayisi',0)}\n"
                        f"  Failsafe:{fs.get('failsafe_kapatma',0)} Acil:{fs.get('acil_kapatma',0)}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🧠 Self-Training: feedback.jsonl aktif | rl_reward takibi aktif\n"
                        f"💾 DB: {db_durum()['backend'].upper()}\n"
                        f"🎭 Sim: {simulator.istatistik['toplam']} işlem, "
                        f"%{simulator.istatistik['kabul_pct']} kabul, "
                        f"{simulator.istatistik['ort_slippage_bps']:.2f}bps slip"
                    )
                except Exception as e:
                    log.error(f"[DURUM] {e}")

            dongu += 1
        except Exception as e:
            log.critical(f"[ANA DÖNGÜ] KRİTİK HATA: {type(e).__name__}: {e}", exc_info=True)
            if watchdog: watchdog.hata_bildir(e, "ana_döngü", kritik=True)
        finally:
            # v15: Döngü süresini hesaba kat — gerçek bekleme
            _dongu_suresi = time.time() - _dongu_baslangic
            # v28: HIZLI TARAMA — güçlü sinyal varken bekleme süresini kısalt.
            # Sinyal doğduğu an ile bir sonraki kontrol arası gecikmeyi azaltır.
            _aktif_interval = SCAN_INTERVAL
            if HIZLI_TARAMA:
                try:
                    with _son_analizler_lock:
                        _guclu = any(abs(a.get("ai_score", 0)) >= 5
                                     for a in _son_analizler.values())
                    if _guclu:
                        _aktif_interval = max(15, SCAN_INTERVAL // 3)  # 60s → 20s
                except Exception:
                    pass
            _bekle = max(1.0, _aktif_interval - _dongu_suresi)
            log.debug(f"[DÖNGÜ] Süre:{_dongu_suresi:.1f}s Bekleme:{_bekle:.1f}s "
                      f"(interval:{_aktif_interval}s)")
            time.sleep(_bekle)

def _telegram_rapor(sonuc, chat_id=CHAT_ID):
    r   = sonuc.get("risk", {}); mkt = sonuc.get("market_data", {}); mtf = sonuc.get("mtf_confluence", {})
    if not r:
        r = {"stop_loss": 0, "take_profit": 0, "rr_ratio": 0}
    rejim_e = {"TREND_UP": "📈", "TREND_DOWN": "📉", "RANGE": "↔️", "VOLATILE": "🌊", "BEAR": "🐻"}.get(
        sonuc.get("rejim", "?"), "❓")
    edge = sonuc.get("edge_sonuc", {}); edge_str = "✅" if edge.get("gecti") else "❌"
    telegram_gonder(
        f"📊 <b>ASTRA {ASTRA_VERSION} — {sonuc['sembol']}</b>\n"
        f"💰 {sonuc['son_close']:,.4f} | {rejim_e} {sonuc.get('rejim')}\n"
        f"🤖 AI:{sonuc['ai_score']} | %{sonuc['confidence']} | {sonuc['model_adi']}\n"
        f"🔬 Edge:{edge_str} Strateji:{sonuc.get('strateji','?')}\n"
        f"📡 MTF:{mtf.get('skor',0)} | 🏆 RL:{sonuc.get('rl_reward',0):+.3f}\n"
        f"🌐 Funding:{mkt.get('funding_rate',0)*100:.4f}% | Sent:{mkt.get('market_sentiment',0):+.1f}\n"
        f"🛑 SL:{r['stop_loss']:,.2f} 🎯 TP:{r['take_profit']:,.2f} ⚖️ {r['rr_ratio']:.2f}\n"
        f"🚦 <b>{sonuc['karar']}</b>", chat_id, tip=f"sinyal_{sonuc.get('sembol','?')}")
    if sonuc.get("grafik_yolu") and os.path.exists(sonuc["grafik_yolu"]):
        telegram_grafik_gonder(sonuc["grafik_yolu"],
                               f"{sonuc['sembol']} | AI:{sonuc.get('ai_score',0)} | {sonuc['karar']}",
                               chat_id)

def tek_seferlik_analiz():
    tablolari_olustur()
    sonuc = coin_analiz("BTCUSDT", period="7d", interval="1h", grafik=True, market_data_al=True)
    if sonuc is None: return
    _telegram_rapor(sonuc); paper_trader.sinyal_isle(sonuc)
    print(f"\n{'='*55}\n{ASTRA_SURUM_ETIKET}\n{'='*55}")
    print(f"Coin:{sonuc['sembol']} | {sonuc['son_close']:,.4f}")
    print(f"Rejim:{sonuc.get('rejim')} | AI:{sonuc['ai_score']} | %{sonuc['confidence']}")
    print(f"Karar:{sonuc['karar']} | Model:{sonuc['model_adi']}")
    edge = sonuc.get("edge_sonuc", {})
    print(f"Edge:{'✅ GEÇTİ' if edge.get('gecti') else '❌ VETO'} | Strateji:{sonuc.get('strateji','?')}")
    m = sonuc.get("market_data", {})
    print(f"Funding:{m.get('funding_rate',0)*100:.4f}% F&G:{m.get('fear_greed',50)} "
          f"OI Δ:{m.get('oi_degisim_pct',0):+.2f}%")

# ── Telegram Bot ──────────────────────────────────────────
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler
    TELEGRAM_BOT_AVAILABLE = True
except ImportError: TELEGRAM_BOT_AVAILABLE = False

import functools







# v56: _tg_parcala / _yanitla / TG_MAX_UZUNLUK core/telegram_gonderim.py'de
#      (yukarıda import ediliyor)

def _yetkili_komut(fn):
    """v38 GÜVENLİK: Sadece yetkili CHAT_ID'den gelen komutları işle.
    Satılan üründe kritik — token'ı bilen yabancılar bota komut gönderemesin.
    CHAT_ID boşsa (kurulum testi) kısıtlama uygulanmaz."""
    @functools.wraps(fn)
    async def sarmalayici(u, c):
        try:
            gelen_id = str(u.effective_chat.id)
        except Exception:
            return
        if CHAT_ID and gelen_id != str(CHAT_ID):
            log.warning(f"[GÜVENLİK] Yetkisiz komut denemesi: chat_id={gelen_id} "
                        f"(beklenen: {CHAT_ID})")
            try:
                await _yanitla(u, "⛔ Bu bot özeldir. Yetkiniz yok.")
            except Exception:
                pass
            return
        return await fn(u, c)
    return sarmalayici

async def _analiz_timeout_ile(loop, sembol, cid, u, sure=90):
    """v43: coin_analiz'i timeout ile çalıştır — ağ yavaşken komut takılmasın.
    sure saniye içinde bitmezse kullanıcıya bilgi ver, sonsuza kadar bekleme."""
    try:
        s = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: coin_analiz(sembol, grafik=True, market_data_al=True)),
            timeout=sure)
        if s:
            _telegram_rapor(s, cid)
        else:
            await _yanitla(u, f"⚠️ {sembol} analizi sonuç döndürmedi.")
    except asyncio.TimeoutError:
        await _yanitla(u, 
            f"⏱️ {sembol} analizi {sure}s içinde tamamlanamadı (ağ yavaş olabilir). "
            f"Lütfen biraz sonra tekrar deneyin.")
    except Exception as e:
        await _yanitla(u, f"⚠️ {sembol} analiz hatası: {type(e).__name__}")

async def cmd_btc(u, c):
    cid = str(u.effective_chat.id); await _yanitla(u, "⏳ BTC...")
    loop = asyncio.get_running_loop()
    await _analiz_timeout_ile(loop, "BTCUSDT", cid, u)

async def cmd_coin(u, c):
    cid = str(u.effective_chat.id)
    sembol = _sembol_normalize(c.args[0] if c.args else None)   # v58 K-52
    await _yanitla(u, f"⏳ {sembol}...")
    loop = asyncio.get_running_loop()
    await _analiz_timeout_ile(loop, sembol, cid, u)

async def cmd_scan(u, c):
    cid = str(u.effective_chat.id); await _yanitla(u, "⏳ Taranıyor...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: multi_coin_tara(COINS, cid))

async def cmd_mc(u, c):
    cid = str(u.effective_chat.id)
    sembol = _sembol_normalize(c.args[0] if c.args else None)   # v58 K-52
    await _yanitla(u, f"🎲 {sembol} MC analizi...")
    monte_carlo_raporu(sembol, cid)

async def cmd_state(u, c):
    cid = str(u.effective_chat.id)
    pozlar = state_manager.acik_pozisyonlar()
    if not pozlar:
        await _yanitla(u, "📭 State'de açık pozisyon yok")
    else:
        satirlar = "\n".join(f"{p['sembol']} {p['yon']} @ {p.get('giris',0):.4f} "
                              f"SL:{p.get('sl_aktif','?')}" for p in pozlar)
        telegram_gonder(f"💾 <b>POSITION STATE</b>\n{satirlar}", cid, force=True)

async def cmd_sync(u, c):
    await _yanitla(u, "🔄 Binance ile sync başlıyor...")
    state_manager.binance_ile_sync()
    state_manager.orphan_sl_tp_temizle()
    await _yanitla(u, "✅ Sync tamamlandı")

async def cmd_watchdog(u, c):
    cid = str(u.effective_chat.id)
    if watchdog:
        d = watchdog.durum
        telegram_gonder(f"🐕 <b>WATCHDOG</b>\nSağlık:{'✅' if d['saglikli'] else '❌'}\n"
                        f"Son HB:{d['son_heartbeat_once']}\nUyarı:{d['uyari_sayisi']}\n"
                        f"Kritik hata:{d['kritik_hata_sayisi']}", cid)
    else: await _yanitla(u, "Watchdog başlatılmamış")

async def cmd_engine(u, c):
    cid = str(u.effective_chat.id)
    try:
        parcalar = [exec_engine.telegram_raporu()]
        if order_reconciler:
            parcalar.append(order_reconciler.anlık_rapor())
        parcalar.append(failsafe_guard.telegram_raporu())
        parcalar.append(state_audit.telegram_raporu())
        parcalar.append(simulator.telegram_raporu())
        await _yanitla(u, "\n".join(parcalar), parse_mode="HTML")
    except Exception as e:
        await _yanitla(u, f"⚠️ Engine rapor hatası: {type(e).__name__}")

async def cmd_audit(u, c):
    cid = str(u.effective_chat.id)
    await _yanitla(u, "⏳ Binance state denetimi yapılıyor...")
    telegram_gonder(state_audit.telegram_raporu(), cid, force=True)

async def cmd_edge(u, c):
    """v12: EdgeEngine durumu."""
    cid = str(u.effective_chat.id)
    sembol = _sembol_normalize(c.args[0] if c.args else None)   # v58 K-52
    s = _son_analizler.get(sembol, {})
    edge = s.get("edge_sonuc", {})
    if edge:
        telegram_gonder(
            f"🔬 <b>EDGE ENGINE — {sembol}</b>\n"
            f"Durum:{'✅ GEÇTİ' if edge.get('gecti') else '❌ VETO'}\n"
            f"Edge Skor:{edge.get('edge_score',0):.1f}\n"
            f"Strateji:{edge.get('strateji','?')}\n"
            f"Sebep:{edge.get('sebep','?')}", cid)
    else:
        await _yanitla(u, f"❓ {sembol} için son analiz bulunamadı")

async def cmd_selflearn(u, c):
    """v20: Self-learning + Online Learning durumu."""
    cid = str(u.effective_chat.id)
    from config import MODEL_DIR as _MD
    satirlar = ["🧠 <b>SELF-TRAINING DURUMU v20</b>", "━━━━━━━━━━━━━━━━"]
    for sembol in COINS:
        rl = rl_ortalama_reward(sembol)
        fb_path = os.path.join(_MD, f"feedback_{sembol.replace('-','_')}.jsonl")
        fb_sayisi = 0
        if os.path.exists(fb_path):
            try:
                with open(fb_path) as f: fb_sayisi = sum(1 for _ in f)
            except Exception as _e: log.debug(f"[SUPPRESS] {_e}")
        m = _ogrenme_metrikleri.get(sembol, {})
        win = m.get("win", 0); loss = m.get("loss", 0)
        toplam = win + loss
        wr_str   = f"%{win/toplam*100:.0f}" if toplam > 0 else "-%"
        son25    = m.get("son_25", [])
        son25_wr = f"%{sum(son25)/len(son25)*100:.0f}" if son25 else "-%"
        drift_emoji = "⚠️DRIFT" if m.get("drift_uyari") else "✅"
        # v20: Online learning istatistikleri
        ol_str = ""
        try:
            ol = get_online_learner(sembol)
            ol_str = f" | 🧬OL:n={ol._egitim_sayisi},d={ol._drift_sayisi}"
        except Exception: pass
        satirlar.append(
            f"<b>{sembol}</b>: RL={rl:+.2f} | FB:{fb_sayisi} | "
            f"WR:{wr_str} ({toplam}i) | S25:{son25_wr} | {drift_emoji}{ol_str}"
        )
    try:
        await _yanitla(u, "\n".join(satirlar), parse_mode="HTML")
    except Exception as e:
        await _yanitla(u, f"⚠️ Self-learn rapor hatası: {type(e).__name__}")

async def cmd_abtest(u, c):
    """v21: A/B test karşılaştırma raporu."""
    cid = str(u.effective_chat.id)
    try:
        telegram_gonder(ab_manager.telegram_raporu(), cid, force=True)
    except Exception as e:
        await _yanitla(u, f"❌ A/B rapor hatası: {e}")

async def cmd_tft(u, c):
    """v21: TFT model durumu + eğitim tetikle."""
    cid  = str(u.effective_chat.id)
    sembol = _sembol_normalize(c.args[0] if c.args else None)   # v58 K-52
    await _yanitla(u, f"⏳ {sembol} TFT eğitimi başlatılıyor (arka plan)...")
    try:
        loop = asyncio.get_running_loop()
        def _egit():
            df = veri_indir(sembol, period="30d", interval="1h")
            if df is None: return "Veri alınamadı"
            X, y = feature_olustur(df, sembol)
            if X.empty: return "Feature boş"
            m, acc, sc = tft_egit_ve_kaydet(X, y, sembol, LOOKBACK)
            return f"TFT/{sembol}: acc={acc:.3f}" if m else "Eğitim başarısız"
        sonuc = await loop.run_in_executor(None, _egit)
        telegram_gonder(f"🔬 {sonuc}", cid, force=True)
    except Exception as e:
        await _yanitla(u, f"❌ TFT hatası: {e}")

async def cmd_registry(u, c):
    """v22: Model registry — versiyon geçmişi."""
    cid = str(u.effective_chat.id)
    sembol = _sembol_normalize(c.args[0], None) if c.args else None   # v58 K-52
    try:
        telegram_gonder(model_registry.telegram_raporu(sembol), cid, force=True)
    except Exception as e:
        await _yanitla(u, f"❌ Registry hatası: {e}")

async def cmd_onchain(u, c):
    """v22: On-chain sentiment durumu."""
    cid = str(u.effective_chat.id)
    sembol = _sembol_normalize(c.args[0] if c.args else None)   # v58 K-52
    try:
        oc = onchain_sentiment(sembol)
        nf = oc.get("netflow", {}); wh = oc.get("whale", {})
        mesaj = (
            f"⛓️ <b>ON-CHAIN — {sembol}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Skor: {oc['onchain_skor']:+.2f}"
            f"{' (karara giriyor)' if oc.get('aktif') else ' (olcum yok, karara girmiyor)'}\n"
            f"Balina: {wh.get('whale_skoru',0):+.3f}  "
            f"islem boyu z={wh.get('islem_boyu_z',0):+.2f}  "
            f"taker alis %{wh.get('taker_alis_payi',0)*100:.1f}\n"
            f"Kaynak: {wh.get('kaynak','?')}\n"
            # v58 (K-68): global piyasa hareketi BAGLAM olarak duruyor,
            # skora GIRMIYOR (bes coinde ayni deger; ayirt edici degil).
            f"---\n"
            f"Global piyasa 24s: {oc.get('global_piyasa_24s',0):+.2f} "
            f"({nf.get('yorum','?')}) — sadece baglam, karara girmez"
            # v58 (K-67): netflow proxy'si CoinGecko /global'den gelir —
            # BES SEMBOLDE DE AYNI deger; coine ozgu degil.
        )
        telegram_gonder(mesaj, cid, force=True)
    except Exception as e:
        await _yanitla(u, f"❌ On-chain hatası: {e}")

async def cmd_smartexec(u, c):
    """v22: Smart execution istatistikleri."""
    cid = str(u.effective_chat.id)
    try:
        telegram_gonder(smart_executor.telegram_raporu(), cid, force=True)
    except Exception as e:
        await _yanitla(u, f"❌ {e}")

async def cmd_multiex(u, c):
    """v26: Çoklu borsa fiyat doğrulama + canlı fiyat karşılaştırma."""
    cid = str(u.effective_chat.id)
    try:
        rapor = multiexchange.telegram_raporu()
        # İstenen coin için canlı karşılaştırma ekle
        sembol = _sembol_normalize(c.args[0] if c.args else None)   # v58 K-52
        try:
            from data.binance_futures_client import futures_anlık_fiyat
            bf = futures_anlık_fiyat(sembol)
            if bf:
                k = multiexchange.karsilastir(sembol, bf)
                rapor += (f"\n\n<b>{sembol} canlı:</b>\n"
                          f"  Binance: {k.binance:.4f}\n"
                          f"  Bybit  : {k.bybit if k.bybit else '—'}\n"
                          f"  OKX    : {k.okx if k.okx else '—'}\n"
                          f"  Sapma  : %{k.binance_sapma:.3f} "
                          f"{'✅' if k.guvenilir else '🛑 VETO'}")
                if k.arbitraj_yon:
                    rapor += f"\n  Arbitraj: {k.arbitraj_yon} (güç {k.arbitraj_gucu:.2f})"
        except Exception as _e:
            log.debug(f"[MULTIEX cmd] {_e}")
        telegram_gonder(rapor, cid, force=True)
    except Exception as e:
        await _yanitla(u, f"❌ {e}")

async def cmd_neden(u, c):
    """v32: İşlem neden açılmıyor? Veto dağılımı teşhisi."""
    cid = str(u.effective_chat.id)
    try:
        o = veto_ozet()
        if o["toplam_deneme"] == 0:
            # v58 (K-66): paper yolu da sayıyor. Burası artık gerçekten
            # "hiç sinyal gelmedi" demek — eskiden paper modda KALICI
            # olarak bu satır dönüyordu (sayaç yalnızca canlı yolda vardı).
            telegram_gonder("📊 Henüz işlem denemesi yok — bot yeniden "
                            "başlatıldıktan sonra hiç sinyal üretilmemiş "
                            "(sayaç bellekte tutulur).", cid, force=True)
            return
        mesaj = (
            f"📊 <b>İŞLEM TEŞHİSİ v32 — neden açılmıyor?</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ Açılan işlem : {o['acilan_islem']}\n"
            f"⛔ Reddedilen   : {o['toplam_red']}\n"
            f"📈 Açılma oranı : %{o['acilma_oran_pct']}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"<b>Red nedenleri (en çok → en az):</b>\n"
        )
        # Okunabilir isimler
        isim = {
            "slippage_gec_giris": "⏱️ Geç giriş (slippage)",
            "kill_switch": "🛑 Kill switch",
            "circuit_breaker": "⚡ Circuit breaker",
            "coklu_borsa": "🌐 Çoklu borsa veto",
            "validator_dayaniklilik": "🛡️ Dayanıklılık reddi",
            "korelasyon": "🔗 Korelasyon limiti",
            "mtf_cascade": "📊 MTF cascade blok",
            "mtf_hizalama_yok": "📊 MTF hizalama yok",
            "edge_engine": "🔬 EdgeEngine veto",
            "strateji_red": "🎯 Strateji reddi",
            "sinyal_filtresi": "🔎 Sinyal filtresi",
            # v58 (K-66): paper yolunun redleri
            "guven_dusuk": "📉 Güven eşiği",
            "ai_skor_dusuk": "🤖 AI skor eşiği",
            "rr_yetersiz": "⚖️ R/R kapısı (MIN_RR)",
            "yeniden_giris_beklemesi": "⏳ Yeniden giriş beklemesi",
            "yeniden_giris_beklemesi_hata": "⚠️ Yeniden giriş doğrulanamadı",
            "max_acik_pozisyon": "📦 Max açık pozisyon",
            "acik_pozisyon_okunamadi": "⚠️ Açık pozisyon okunamadı",
            "bakiye_yetersiz": "💰 Bakiye yetersiz",
            "miktar_sifir": "🔢 Miktar sıfıra yuvarlandı",
        }
        for neden, sayi in o["red_dagilim"].items():
            ad = isim.get(neden, neden)
            oran = round(sayi/o["toplam_red"]*100, 0) if o["toplam_red"] else 0
            mesaj += f"  {ad}: {sayi} (%{oran:.0f})\n"
        mesaj += (f"━━━━━━━━━━━━━━━━\n"
                  f"💡 En çok reddeden katman, işlem sayısını en çok\n"
                  f"   kısıtlayandır. Çok agresif ise .env'den gevşetebilirsin.")
        telegram_gonder(mesaj, cid, force=True)
    except Exception as e:
        await _yanitla(u, f"❌ {e}")

async def cmd_gecikme(u, c):
    """v28: Sinyal→emir giriş gecikme raporu (kanıtlama)."""
    cid = str(u.effective_chat.id)
    try:
        o = giris_gecikme_ozet()
        if o.get("n", 0) == 0:
            telegram_gonder("⏱️ Henüz giriş gecikme verisi yok "
                            "(işlem açıldıkça birikecek).", cid)
            return
        mesaj = (
            f"⏱️ <b>GİRİŞ GECİKME RAPORU v31</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Örneklem: {o['n']} giriş denemesi\n"
            f"Ort. gecikme : {o['ort_gecikme_sn']}s\n"
            f"Medyan       : {o['medyan_gecikme_sn']}s\n"
            f"Maks         : {o['max_gecikme_sn']}s\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Ort. fiyat kayması: %{o['ort_kayma_pct']}\n"
            f"Geç giriş iptali  : {o['iptal_sayisi']} (%{o['iptal_oran_pct']})\n"
        )
        # v31: Gecikme-PnL analizi (yeterli sonuçlu işlem varsa)
        a = o.get("analiz", {})
        if a:
            hizli = a["hizli_giris_ort_pnl"]; yavas = a["yavas_giris_ort_pnl"]
            fark = hizli - yavas
            mesaj += (
                f"━━━━━━━━━━━━━━━━\n"
                f"🔬 <b>GECİKME-PnL ANALİZİ</b> ({a['eslenen_islem']} işlem)\n"
                f"Hızlı giriş (≤{a['medyan_esik_sn']}s) ort PnL: {hizli:+.3f}%\n"
                f"Yavaş giriş (>{a['medyan_esik_sn']}s) ort PnL: {yavas:+.3f}%\n"
            )
            if fark > 0.05:
                mesaj += (f"⚠️ Hızlı girişler %{fark:.3f} daha iyi → "
                          f"gecikme ZARAR veriyor. Eşiği sıkılaştırmayı düşün "
                          f"(MAX_GIRIS_KAYMA_PCT düşür).")
            elif fark < -0.05:
                mesaj += (f"ℹ️ Yavaş girişler daha iyi → gecikme şu an "
                          f"zarar vermiyor. Eşik gevşetilebilir.")
            else:
                mesaj += f"✅ Hız ile PnL arasında belirgin fark yok ({fark:+.3f}%)."
        else:
            mesaj += (f"━━━━━━━━━━━━━━━━\n"
                      f"🔬 Gecikme-PnL analizi için en az 6 kapanmış işlem "
                      f"gerekli (şu an birikiyor).")
        mesaj += (f"\n━━━━━━━━━━━━━━━━\n"
                  f"💡 İptaller, fiyat aleyhe çok kaçtığı için kovalamaktan\n"
                  f"   kaçınılan işlemler — kötü girişleri önler.")
        telegram_gonder(mesaj, cid, force=True)
    except Exception as e:
        await _yanitla(u, f"❌ {e}")

async def cmd_validate(u, c):
    """v24: Strateji dayanıklılık doğrulaması. /validate [coin] veya tümü."""
    cid = str(u.effective_chat.id)
    sembol = _sembol_normalize(c.args[0], None) if c.args else None   # v58 K-52
    await _yanitla(u, "🛡️ Dayanıklılık testi çalışıyor (Monte Carlo + walk-forward)...")
    try:
        loop = asyncio.get_running_loop()
        sonuclar = await loop.run_in_executor(
            None, lambda: _strateji_dayaniklilik_dogrula(sembol)
        )
        if not sonuclar:
            telegram_gonder("Yeterli işlem geçmişi yok (min 30 işlem/coin gerekli).", cid, force=True)
            return
        for s, karar in sonuclar.items():
            telegram_gonder(f"<b>{s}</b>\n{karar.telegram_raporu()}", cid, force=True)
    except Exception as e:
        await _yanitla(u, f"❌ Doğrulama hatası: {e}")

async def cmd_risk(u, c):
    cid = str(u.effective_chat.id)
    try:
        # v56: futures_bakiye() bloklayan bir REST çağrısı. Doğrudan async
        # handler içinde çağrılınca yavaş ağda (HTTP timeout 15s) event
        # loop'u kilitliyor → o süre boyunca HİÇBİR Telegram komutu yanıt
        # vermiyordu. Executor'a taşındı.
        _bak = await asyncio.get_running_loop().run_in_executor(None, futures_bakiye)
        mesaj = risk_manager.durum_raporu(_bak)
        try:
            mesaj += "\n\n" + portfolio_optimizer.durum_raporu()
        except Exception: pass
        await _yanitla(u, mesaj, parse_mode="HTML")
    except Exception as e:
        await _yanitla(u, f"⚠️ Risk raporu hatası: {type(e).__name__}. "
                                    f"Binance bağlantısını kontrol edin.")
async def cmd_paper(u, c):
    try: await _yanitla(u, paper_trader.rapor_str())
    except Exception as e: await _yanitla(u, f"⚠️ Paper rapor hatası: {type(e).__name__}")
async def cmd_ai_rapor(u, c):
    try: await _yanitla(u, PerformanceTracker("BTCUSDT").telegram_raporu(), parse_mode="HTML")
    except Exception as e: await _yanitla(u, f"⚠️ AI rapor hatası: {type(e).__name__}")
async def cmd_market(u, c):
    cid = str(u.effective_chat.id)
    sembol = _sembol_normalize(c.args[0] if c.args else None)   # v58 K-52
    try:
        m = market_veri_topla(sembol)
        telegram_gonder(f"🌐 <b>MARKET — {sembol}</b>\n"
                        f"Funding:{m['funding_rate']*100:.4f}% OI Δ:%{m['oi_degisim_pct']:+.2f}\n"
                        f"L/S:{m['ls_ratio']:.2f} F&G:{m['fear_greed']} ({m['fg_sinif']})\n"
                        f"OB:{m['order_book']['baskı']} Sent:{m['market_sentiment']:+.2f}", cid)
    except Exception as e: await _yanitla(u, f"❌ {e}")

async def cmd_fpoz(u, c):
    try: futures_pozisyon_raporu(str(u.effective_chat.id))
    except Exception as e: await _yanitla(u, f"⚠️ Pozisyon raporu hatası: {type(e).__name__}")
async def cmd_fkapat(u, c):
    cid = str(u.effective_chat.id); args = c.args
    if len(args) < 2: await _yanitla(u, "Kullanım: /fkapat BTCUSDT LONG"); return
    req = OrderRequest(args[0].upper(), "CLOSE_" + args[1].upper(), 0, kaynak="MANUEL")
    order_engine.submit(req)
    await _yanitla(u, f"✅ {args[0]} {args[1]} kapatma kuyruğa eklendi")

async def cmd_bakiye(u, c):
    cid = str(u.effective_chat.id)
    try:
        # v56: İki bloklayan REST çağrısı executor'a taşındı (bkz. cmd_risk)
        _loop = asyncio.get_running_loop()
        spot = await _loop.run_in_executor(None, lambda: bakiye_al("USDT"))
        fut  = await _loop.run_in_executor(None, futures_bakiye)
        await _yanitla(u, 
            f"💰 Spot:{spot:.2f} Futures:{fut:.2f} Toplam:{spot+fut:.2f}USDT\n"
            f"DD:%{risk_manager.drawdown_pct():.2f}\n{risk_manager.durum_raporu(spot+fut)}")
    except Exception as e:
        await _yanitla(u, f"⚠️ Bakiye alınamadı: {type(e).__name__}. "
                                    f"Binance bağlantısı/saat ayarını kontrol edin.")

async def cmd_circuit(u, c):
    """v16: Volatilite circuit breaker durumu."""
    cid = str(u.effective_chat.id)
    try:
        if circuit_breaker:
            telegram_gonder(circuit_breaker.telegram_raporu(), cid, force=True)
        else:
            await _yanitla(u, "Circuit breaker henüz başlatılmadı.")
    except Exception as e:
        await _yanitla(u, f"❌ {e}")

async def cmd_correlation(u, c):
    """v16: Portföy korelasyon durumu."""
    cid = str(u.effective_chat.id)
    try:
        from data.binance_futures_client import acik_futures_pozisyonlar
        # v56: bloklayan REST çağrısı executor'a taşındı (bkz. cmd_risk)
        pozlar = await asyncio.get_running_loop().run_in_executor(
            None, acik_futures_pozisyonlar)
        if correlation_eng:
            telegram_gonder(correlation_eng.telegram_raporu(pozlar), cid, force=True)
        else:
            await _yanitla(u, "Korelasyon motoru henüz başlatılmadı.")
    except Exception as e:
        await _yanitla(u, f"❌ {e}")

async def cmd_shadow(u, c):
    """v16: Shadow model durumu."""
    cid = str(u.effective_chat.id)
    try:
        if shadow_manager:
            telegram_gonder(shadow_manager.telegram_raporu(), cid, force=True)
        else:
            await _yanitla(u, "Shadow model henüz başlatılmadı.")
    except Exception as e:
        await _yanitla(u, f"❌ {e}")

async def cmd_shadow_approve(u, c):
    """v16: Shadow model manuel onay. /shadow_approve BTC"""
    cid = str(u.effective_chat.id)
    if not c.args:
        await _yanitla(u, "Kullanım: /shadow_approve BTC")
        return
    sembol = _sembol_normalize(c.args[0])   # v58 K-52
    try:
        if shadow_manager and shadow_manager.manuel_onayla(sembol):
            telegram_gonder(f"✅ {sembol} shadow modeli onaylandı, canlıya alındı.", cid, force=True)
        else:
            await _yanitla(u, f"{sembol} için onay bekleyen shadow model yok.")
    except Exception as e:
        await _yanitla(u, f"❌ {e}")

async def cmd_saglik(u, c):
    """v38: Canlı sistem sağlık kontrolü."""
    try:
        from core.preflight import (_kontrol_binance_baglanti, _kontrol_config,
                                     _kontrol_opsiyonel_paketler, _kontrol_dosya_sistemi)
        satirlar = ["🏥 <b>SİSTEM SAĞLIĞI v38</b>", "━━━━━━━━━━━━━━━━"]
        tum = []
        tum.extend(_kontrol_config())
        tum.append(_kontrol_dosya_sistemi())
        tum.append(_kontrol_opsiyonel_paketler())
        tum.append(_kontrol_binance_baglanti())
        for s in tum:
            ikon = "✅" if s.gecti else ("❌" if s.kritik else "⚠️")
            satirlar.append(f"{ikon} <b>{s.ad}</b>: {s.mesaj}")
        # Çalışma süresi + thread sayısı
        import threading as _th
        satirlar.append("━━━━━━━━━━━━━━━━")
        satirlar.append(f"🧵 Aktif thread: {_th.active_count()}")
        kritik = [s for s in tum if not s.gecti and s.kritik]
        satirlar.append("✅ Sistem sağlıklı" if not kritik
                        else f"🛑 {len(kritik)} kritik sorun var")
        await _yanitla(u, "\n".join(satirlar), parse_mode="HTML")
    except Exception as e:
        await _yanitla(u, f"⚠️ Sağlık kontrolü hatası: {type(e).__name__}")

async def cmd_yardim(u, c):
    await _yanitla(u, 
        f"🤖 <b>{ASTRA_SURUM_ETIKET}</b>\n\n"
        "<b>📊 Analiz</b>\n"
        "/btc · /coin ETH · /scan · /market BTC\n\n"
        "<b>💰 Hesap & Pozisyon</b>\n"
        "/bakiye · /fpoz · /fkapat BTC LONG · /paper\n\n"
        "<b>🛡️ Risk & Güvenlik</b>\n"
        "/risk · /circuit · /correlation · /validate\n"
        "/multiex BTC — çoklu borsa fiyat doğrulama\n\n"
        "<b>🧠 Model & Öğrenme</b>\n"
        "/selflearn · /tft BTC · /registry · /shadow\n"
        "/shadow_approve BTC · /edge BTC\n\n"
        "<b>⚡ Execution & Strateji</b>\n"
        "/smartexec · /abtest · /onchain BTC\n\n"
        "<b>🔬 Analitik & Test</b>\n"
        "/analytics · /senaryo · /sim · /mc BTC · /ai_rapor\n\n"
        "<b>🔧 Sistem</b>\n"
        "/state · /sync · /watchdog · /engine · /audit\n"
        "/gecikme — giriş gecikme/kayma raporu (v28)\n"
        "/neden — işlem neden açılmıyor? veto teşhisi (v32)\n"
        "/saglik — sistem sağlık kontrolü (v38)",
        parse_mode="HTML")

def telegram_bot_baslat():
    if not TELEGRAM_BOT_AVAILABLE:
        log.warning("[TELEGRAM] python-telegram-bot yüklü değil — bot devre dışı")
        return
    if not BOT_TOKEN:
        log.warning("[TELEGRAM] BOT_TOKEN tanımlı değil — bot başlatılamadı")
        return
    # v56 GÜVENLİK: CHAT_ID boşsa _yetkili_komut dekoratörü NO-OP olur
    # (`if CHAT_ID and ...` koşulu hiç çalışmaz) — yani token'ı ele geçiren
    # veya bot kullanıcı adını tahmin eden HERKES /fkapat, /killswitch_reset
    # gibi komutları çalıştırabilir. Sessiz kalmak kabul edilemez.
    if not CHAT_ID:
        log.critical(
            "[TELEGRAM] 🚨 CHAT_ID BOŞ — KOMUT YETKİLENDİRMESİ DEVRE DIŞI! "
            "Bot token'ını bilen herkes pozisyon kapatabilir. "
            ".env'de CHAT_ID tanımlayın (bulmak için: python telegram_chat_id_bul.py)")
    # v27: run_polling ana thread'de çalışmalı + kendi event loop'unu kurmalı.
    # Ayrı thread'den çağrılırsa "no current event loop" hatası olur; bunu önle.
    try:
        import asyncio as _aio
        try:
            _aio.get_event_loop()
        except RuntimeError:
            _aio.set_event_loop(_aio.new_event_loop())

        # v46 KÖK ÇÖZÜM: Telegram ağ katmanı (httpx) global requests
        # timeout'undan ETKİLENMEZ — kendi timeout'larını açıkça ayarla.
        # Bunlar olmadan getUpdates/sendMessage ağ yavaşken sonsuza kadar
        # asılı kalıp ana thread'i kilitliyordu (uzun watchdog donmaları).
        app = (Application.builder()
               .token(BOT_TOKEN)
               .connect_timeout(15.0)      # bağlantı kurma tavanı
               .read_timeout(20.0)         # yanıt okuma tavanı
               .write_timeout(20.0)        # gönderme tavanı
               .pool_timeout(5.0)          # bağlantı havuzu bekleme tavanı
               .get_updates_connect_timeout(15.0)
               .get_updates_read_timeout(30.0)   # polling long-poll için biraz uzun
               .build())
        komutlar = [("btc", cmd_btc), ("coin", cmd_coin), ("scan", cmd_scan),
                    ("circuit", cmd_circuit), ("shadow", cmd_shadow),
                    ("shadow_approve", cmd_shadow_approve),
                    ("correlation", cmd_correlation),
                    ("mc", cmd_mc), ("state", cmd_state), ("sync", cmd_sync),
                    ("watchdog", cmd_watchdog), ("engine", cmd_engine), ("audit", cmd_audit),
                    ("analytics", cmd_analytics), ("senaryo", cmd_senaryo), ("sim", cmd_sim),
                    ("risk", cmd_risk), ("market", cmd_market), ("paper", cmd_paper),
                    ("ai_rapor", cmd_ai_rapor), ("fpoz", cmd_fpoz), ("fkapat", cmd_fkapat),
                    ("bakiye", cmd_bakiye), ("yardim", cmd_yardim), ("help", cmd_yardim),
                    ("start", cmd_yardim),
                    ("edge", cmd_edge), ("selflearn", cmd_selflearn),
                    ("abtest", cmd_abtest), ("tft", cmd_tft),
                    ("registry", cmd_registry), ("onchain", cmd_onchain),
                    ("smartexec", cmd_smartexec), ("validate", cmd_validate),
                    ("multiex", cmd_multiex), ("gecikme", cmd_gecikme),
                    ("neden", cmd_neden), ("saglik", cmd_saglik)]
        for cmd, fn in komutlar:
            app.add_handler(CommandHandler(cmd, _yetkili_komut(fn)))

        # v37: Global hata yakalayıcı — komut handler'ında hata olursa
        # sessizce yutulmasın; logla + kullanıcıya bildir.
        async def _hata_yakalayici(update, context):
            log.error(f"[TELEGRAM] Komut hatası: {context.error}", exc_info=context.error)
            try:
                if update and getattr(update, "effective_message", None):
                    await update.effective_message.reply_text(
                        f"⚠️ Komut işlenirken hata: {type(context.error).__name__}. "
                        f"Loglara bakın veya tekrar deneyin.")
            except Exception:
                pass
        app.add_error_handler(_hata_yakalayici)

        log.info(f"🤖 Telegram Bot {ASTRA_VERSION} başlatıldı — {len(komutlar)} komut aktif")
        # close_loop=False: paralel daemon thread'lerdeki loop'ları kapatmasın
        app.run_polling(close_loop=False, drop_pending_updates=True)
    except Exception as e:
        log.critical(f"[TELEGRAM] Bot başlatma hatası: {type(e).__name__}: {e}", exc_info=True)


def telegram_denetimli_calistir():
    """Telegram'ı denetimli çalıştır ve ANA THREAD'İ CANLI TUT.

    v57 KRİTİK DÜZELTME — sessiz tam ölüm:
      Eskiden `bot` modu şunu yapıyordu:

          threading.Thread(target=_denetimli_dashboard, daemon=True).start()
          telegram_bot_baslat()

      `telegram_bot_baslat()` hatayı KENDİ İÇİNDE yutup `return` eder.
      Dönünce ana thread biter, Python çıkar ve AstraEngine thread'i
      DAEMON olduğu için ÖLDÜRÜLÜR. Yani trading motorunun kendi koruyucu
      `while True` döngüsü tamamen etkisizdi: onu öldüren şey kendi
      istisnası değil, ana thread'in bitmesiydi.

      Gerçekleşen senaryo: oturum açılışında ağ/DNS henüz hazır değilken
      Telegram `getaddrinfo failed` alıyor → bot komple ölüyor. 2026-08-21
      ile 08-23 arasında bot bu yüzden 2+ gün hiç veri toplamadı
      (log kanıtı: 8022 `getaddrinfo failed`, 325 NetworkError).

    Tasarım:
      - Telegram KASITLI kapalıysa (paket yok / BOT_TOKEN boş) yeniden
        denemenin anlamı yok; ana thread yalnızca motoru canlı tutar.
      - Geçici hatada üstel artan bekleme ile yeniden denenir; trading
        motoru bu süre boyunca ETKİLENMEZ.
      - Hiçbir koşulda return ETMEZ — dönerse motor yine ölür.
    """
    if (not TELEGRAM_BOT_AVAILABLE) or (not BOT_TOKEN):
        log.warning("[TELEGRAM] Devre dışı (paket veya BOT_TOKEN yok) — "
                    "ana thread yalnızca trading motorunu canlı tutuyor.")
        while True:
            time.sleep(3600)

    deneme = 0
    while True:
        try:
            # Başarılıysa run_polling burada süresiz bloklar.
            telegram_bot_baslat()
        except Exception as _te:
            log.critical(f"[TELEGRAM] Denetimli katmanda beklenmeyen hata: "
                         f"{type(_te).__name__}: {_te}", exc_info=True)
        deneme += 1
        bekle = min(60 * deneme, 900)          # 60s → en fazla 15 dk
        log.error(f"[TELEGRAM] Polling durdu (deneme #{deneme}) — "
                  f"{bekle}s sonra yeniden denenecek. "
                  f"TRADING MOTORU ETKİLENMEDİ, çalışmaya devam ediyor.")
        time.sleep(bekle)


# ── Ana Giriş ─────────────────────────────────────────────
if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "analiz"
    # v38: Başlangıç sağlık kontrolü (bot/live modlarında)
    if mod in ("bot", "live", "futures"):
        try:
            from core.preflight import preflight_calistir
            if not preflight_calistir():
                log.critical("Preflight başarısız — çıkılıyor. Yukarıdaki hataları düzeltin.")
                sys.exit(1)
        except SystemExit:
            raise
        except Exception as _pf:
            log.warning(f"Preflight çalıştırılamadı (atlanıyor): {_pf}")
    if mod == "futures":
        futures_dashboard()
    elif mod == "bot":
        # v55: Eskiden futures_dashboard doğrudan thread target'ıydı.
        # Kurulum kodu (satır ~1780-1900) koruyucu while/try bloğunun DIŞINDA
        # olduğu için oradaki tek bir hata thread'i sessizce öldürüyor, Telegram
        # botu ise çalışmaya devam ederek "her şey yolunda" izlenimi veriyordu.
        # Artık denetimli: çökerse loglanır, Telegram'a alarm gider, yeniden başlar.
        def _denetimli_dashboard():
            while True:
                try:
                    futures_dashboard()
                except Exception as _de:
                    log.critical(f"[ENGINE THREAD] Trading motoru çöktü: "
                                 f"{type(_de).__name__}: {_de}", exc_info=True)
                    try:
                        telegram_gonder(
                            f"🛑 <b>TRADING MOTORU ÇÖKTÜ</b>\n"
                            f"{type(_de).__name__}: {_de}\n"
                            f"{SCAN_INTERVAL}s sonra yeniden başlatılıyor.",
                            tip="sistem", force=True)
                    except Exception as _te:
                        log.error(f"[ENGINE THREAD] alarm gönderilemedi: {_te}")
                log.info(f"[ENGINE THREAD] {SCAN_INTERVAL}s sonra yeniden başlıyor...")
                time.sleep(SCAN_INTERVAL)

        threading.Thread(target=_denetimli_dashboard, daemon=True,
                         name="AstraEngine").start()
        # v57: DOĞRUDAN telegram_bot_baslat() ÇAĞIRMA. O fonksiyon hata
        # durumunda return eder, ana thread biter ve yukarıdaki daemon
        # motor thread'i sessizce ÖLDÜRÜLÜR. Bkz. telegram_denetimli_calistir.
        telegram_denetimli_calistir()
    elif mod == "backtest":
        tablolari_olustur()
        sembol = sys.argv[2] if len(sys.argv) > 2 else "BTCUSDT"
        backtest_calistir_full(sembol)
    elif mod == "paper":
        tablolari_olustur(); print(paper_trader.rapor_str())
    elif mod == "pozisyon":
        print(futures_pozisyon_raporu())
    elif mod == "mc":
        sembol = sys.argv[2] if len(sys.argv) > 2 else "BTCUSDT"
        monte_carlo_raporu(sembol)
    elif mod == "sync":
        state_manager.binance_ile_sync()
        state_manager.orphan_sl_tp_temizle()
        print("✅ Sync tamamlandı")

    elif mod == "live":
        tablolari_olustur()
        log.info(f"🚀 ASTRA {ASTRA_VERSION} LIVE MODE başlatıldı")

        while True:
            try:
                futures_dashboard()
            except KeyboardInterrupt:
                log.info("🛑 Live mode kullanıcı tarafından durduruldu")
                break
            except Exception as e:
                log.error(f"[LIVE LOOP] {type(e).__name__}: {e}", exc_info=True)

            log.info(f"⏳ {SCAN_INTERVAL}s bekleniyor...")
            time.sleep(SCAN_INTERVAL)

    else:
        tek_seferlik_analiz()
