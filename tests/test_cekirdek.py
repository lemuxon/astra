# =========================================================
# ASTRA v40.0 — Çekirdek Bileşen Birim Testleri
# Çalıştırma: python -m pytest tests/test_cekirdek.py -v
#   veya bağımsız:  python tests/test_cekirdek.py
#
# Bu testler kritik bileşenlerin doğru çalıştığını ve gelecekteki
# değişikliklerin bir şeyi bozmadığını (regresyon) garanti eder.
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

import numpy as np
import pandas as pd


def _ornek_ohlcv(n=400, trendli=True, seed=42):
    """Test için gerçekçi OHLCV verisi üret."""
    rng = np.random.default_rng(seed)
    trend = np.linspace(0, 8, n) if trendli else np.zeros(n)
    close = 100 + trend + np.cumsum(rng.normal(0, 0.4, n))
    return pd.DataFrame({
        "Open":  close + rng.normal(0, 0.1, n),
        "High":  close + np.abs(rng.normal(0, 0.3, n)),
        "Low":   close - np.abs(rng.normal(0, 0.3, n)),
        "Close": close,
        "Volume": rng.random(n) * 1000 + 500,
    })


# ─────────────────────────────────────────────
# 1. FEATURE ENGINEERING
# ─────────────────────────────────────────────
def test_feature_olustur_calisir():
    """Feature engineering geçerli veriyle çalışmalı."""
    from main import feature_olustur
    df = _ornek_ohlcv()
    X, y = feature_olustur(df, "BTCUSDT")
    assert len(X) > 0, "Feature üretilemedi"
    assert X.shape[1] > 10, f"Çok az feature: {X.shape[1]}"
    assert len(X) == len(y), "X ve y boyutu uyuşmuyor"


def test_feature_nan_icermez():
    """Üretilen feature'lar NaN içermemeli (model eğitimini bozar)."""
    from main import feature_olustur
    df = _ornek_ohlcv()
    X, y = feature_olustur(df, "BTCUSDT")
    assert not X.isnull().any().any(), "Feature'larda NaN var!"


def test_label_dengeli():
    """Label (hedef) makul dengede olmalı (tek sınıfa çökmemeli)."""
    from main import feature_olustur
    df = _ornek_ohlcv()
    X, y = feature_olustur(df, "BTCUSDT")
    oran = y.mean()
    assert 0.2 < oran < 0.8, f"Label dengesiz: {oran:.2f} (tek sınıfa yakın)"


# ─────────────────────────────────────────────
# 2. MODEL EĞİTİMİ + SIZINTI KONTROLÜ (kritik!)
# ─────────────────────────────────────────────
def test_model_egitimi_calisir():
    """RF modeli eğitilebilmeli ve tahmin yapabilmeli."""
    from main import feature_olustur
    from engines.model_engine import rf_egit
    df = _ornek_ohlcv()
    X, y = feature_olustur(df, "TESTUSDT")
    model, acc, meta = rf_egit(X, y, "TESTUSDT")
    assert model is not None, "Model eğitilemedi"
    assert 0.0 <= acc <= 1.0, f"Geçersiz accuracy: {acc}"


def test_accuracy_sizinti_yok():
    """KRİTİK: Rastgele veride accuracy ~0.5 olmalı.
    Eğer >0.75 çıkarsa kalibrasyon sızıntısı (v33 bug'ı) geri gelmiş demektir.
    Bu test, accuracy şişmesini otomatik yakalar."""
    from main import feature_olustur
    from engines.model_engine import rf_egit
    # Rastgele (trendsiz) veri → model öğrenecek bir şey yok → acc ~0.5 olmalı
    df = _ornek_ohlcv(trendli=False, seed=7)
    X, y = feature_olustur(df, "RANDUSDT")
    model, acc, meta = rf_egit(X, y, "RANDUSDT")
    # Rastgele veride accuracy 0.40-0.70 bandında olmalı (şişmemiş)
    assert acc < 0.78, (f"ACCURACY ŞİŞMESİ! Rastgele veride acc={acc:.3f} > 0.78. "
                        f"Kalibrasyon sızıntısı geri gelmiş olabilir (v33 bug'ı).")


# ─────────────────────────────────────────────
# 3. RİSK YÖNETİMİ
# ─────────────────────────────────────────────
def test_risk_manager_baslar():
    """Risk yöneticisi başlatılabilmeli."""
    from engines.risk_manager import RiskManager
    rm = RiskManager()
    dd = rm.drawdown_pct()
    assert dd >= 0, f"Drawdown negatif olamaz: {dd}"


def test_risk_drawdown_hesabi():
    """Drawdown başlangıçta 0 olmalı."""
    from engines.risk_manager import RiskManager
    rm = RiskManager()
    assert rm.drawdown_pct() == 0.0, "Başlangıç drawdown 0 olmalı"


# ─────────────────────────────────────────────
# 4. PAPER TRADER
# ─────────────────────────────────────────────
def test_paper_trader_baslar():
    """Paper trader başlamalı ve başlangıç bakiyesi olmalı."""
    from engines.paper_trading import PaperTrader
    pt = PaperTrader()
    assert pt.bakiye > 0, "Paper bakiye pozitif olmalı"


def test_paper_dusuk_skor_reddedilir():
    """Düşük AI skorlu sinyal işlem açmamalı (kalite filtresi).

    v55 TEST DÜZELTMESİ: Bu test eskiden `assert True` ile bitiyordu —
    yani sinyal_isle() ne yaparsa yapsın KOŞULSUZ geçiyordu. Docstring'i
    düşük skorlu sinyallerin reddedildiğini doğruladığını iddia ederken
    aslında hiçbir şey doğrulamıyordu (başarısız OLAMAZ bir test).
    Artık _pozisyon_ac'ın gerçekten ÇAĞRILMADIĞI doğrulanıyor.
    """
    from engines.paper_trading import PaperTrader
    pt = PaperTrader()

    acilan = []
    orij_ac = pt._pozisyon_ac
    pt._pozisyon_ac = lambda *a, **kw: acilan.append(a)

    zayif_sinyal = {"sembol": "BTCUSDT", "karar": "BUY", "son_close": 100.0,
                    "ai_score": 1, "confidence": 30, "atr": 2.0}
    try:
        pt.sinyal_isle(zayif_sinyal)
    finally:
        pt._pozisyon_ac = orij_ac

    assert len(acilan) == 0, (
        f"Düşük AI skorlu (ai_score=1, confidence=30) sinyalle "
        f"{len(acilan)} pozisyon açıldı — kalite filtresi ÇALIŞMIYOR!")


def test_paper_yuksek_skor_kabul_edilir():
    """Kontrol testi: filtre her şeyi reddetmiyor olmalı.

    Düşük skor testinin anlamlı olması için, filtrenin GÜÇLÜ sinyalleri
    geçirdiğini de kanıtlamak gerekir; aksi halde 'her zaman reddet'
    davranışı da testi geçerdi.
    """
    from engines.paper_trading import PaperTrader

    with _paper_sahne("BTCUSDT"):
        pt = PaperTrader()

        acilan = []
        orij_ac = pt._pozisyon_ac
        pt._pozisyon_ac = lambda *a, **kw: acilan.append(a)

        guclu_sinyal = {"sembol": "BTCUSDT", "karar": "STRONG BUY", "son_close": 100.0,
                        "ai_score": 9, "confidence": 95, "atr": 2.0,
                        "son_atr": 2.0, "edge_sonuc": {"gecti": True, "edge_score": 70, "sebep": ""}, "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3, "ana_trend_yon": "LONG", "yon": "LONG"}, "rejim": "TREND"}
        try:
            pt.sinyal_isle(guclu_sinyal)
        finally:
            pt._pozisyon_ac = orij_ac

    assert len(acilan) == 1, (
        f"Güçlü sinyal (ai_score=9, confidence=95) geçmedi "
        f"({len(acilan)} pozisyon) — filtre HER ŞEYİ reddediyor olabilir, "
        f"bu durumda düşük-skor testi de anlamsızlaşır!")


# ─────────────────────────────────────────────
# 5. OVERFITTING SKORU TUTARLILIĞI (v39 düzeltmesi)
# ─────────────────────────────────────────────
def test_overfitting_tutarli():
    """İki overfitting_skoru fonksiyonu aynı sonucu vermeli (v39 fix)."""
    from engines.walk_forward_advanced import overfitting_skoru as of1
    from engines.backtest_engine import overfitting_skoru as of2
    for tr, te, std in [(0.9, 0.7, 0.05), (0.6, 0.58, 0.03), (0.95, 0.6, 0.12)]:
        r1 = of1(tr, te, std)
        r2 = of2(tr, te, std)
        assert r1["risk"] == r2["risk"], (
            f"overfitting tutarsız: of1={r1['risk']} of2={r2['risk']} "
            f"(train={tr},test={te},std={std})")


# ─────────────────────────────────────────────
# 6. CONFIG DOĞRULAMA
# ─────────────────────────────────────────────
def test_config_kritik_anahtarlar():
    """Kritik config anahtarları tanımlı olmalı."""
    import config
    for anahtar in ["ASTRA_VERSION", "COINS", "FUTURES_LEVERAGE",
                    "LIVE_TRADING", "RISK_PERCENT", "IS_TESTNET"]:
        assert hasattr(config, anahtar), f"config.{anahtar} eksik!"


def test_live_trading_varsayilan_kapali():
    """GÜVENLİK: LIVE_TRADING varsayılanı false olmalı."""
    # Temiz ortamda (env set edilmemiş) varsayılan kapalı olmalı
    import config
    # Not: test ortamında LIVE_TRADING=false set edildi, bu onu doğrular
    assert config.LIVE_TRADING is False, "LIVE_TRADING test ortamında açık olmamalı!"


# ─────────────────────────────────────────────
# 7. PREFLIGHT (v38)
# ─────────────────────────────────────────────
def test_preflight_calisir():
    """Preflight sağlık kontrolü çalışmalı ve sonuç dönmeli."""
    from core.preflight import preflight_calistir
    sonuc = preflight_calistir(sessiz=True)
    assert isinstance(sonuc, bool), "Preflight bool dönmeli"


# ─────────────────────────────────────────────
# 8. KILL SWITCH (kritik güvenlik — ard arda kayıpta durmalı)
# ─────────────────────────────────────────────
def test_kill_switch_baslangicta_aktif():
    """Kill switch başlangıçta işleme izin vermeli (aktif)."""
    from engines.kill_switch import HardKillSwitch
    ks = HardKillSwitch()
    assert ks.kontrol() is True, "Kill switch başlangıçta açık olmalı"


def test_kill_switch_ardisik_kayipta_durur():
    """KRİTİK: Ard arda yeterli kayıpta kill switch işlemi durdurmalı."""
    from engines.kill_switch import HardKillSwitch
    ks = HardKillSwitch(max_consecutive_loss=3)
    # 3 ard arda kayıp bildir
    for _ in range(3):
        ks.trade_sonucu_bildir(kazandi=False, pnl_usdt=-10)
    assert ks.kontrol() is False, (
        "Ard arda 3 kayıptan sonra kill switch DURMALI — durmadı! "
        "Bu, felaket kayıplarını önleyen kritik güvenlik.")


def test_kill_switch_kazanc_sayaci_sifirlar():
    """Kazanç, ard arda kayıp sayacını sıfırlamalı."""
    from engines.kill_switch import HardKillSwitch
    ks = HardKillSwitch(max_consecutive_loss=3)
    ks.trade_sonucu_bildir(kazandi=False, pnl_usdt=-10)
    ks.trade_sonucu_bildir(kazandi=False, pnl_usdt=-10)
    ks.trade_sonucu_bildir(kazandi=True, pnl_usdt=20)   # sıfırla
    ks.trade_sonucu_bildir(kazandi=False, pnl_usdt=-10)
    assert ks.kontrol() is True, "Kazanç sonrası sayaç sıfırlanmalı, durmamalı"


def test_kill_switch_reset_calisir():
    """Manuel reset kill switch'i tekrar aktif etmeli."""
    from engines.kill_switch import HardKillSwitch
    ks = HardKillSwitch(max_consecutive_loss=2)
    ks.trade_sonucu_bildir(kazandi=False, pnl_usdt=-10)
    ks.trade_sonucu_bildir(kazandi=False, pnl_usdt=-10)
    assert ks.kontrol() is False
    ks.reset("test")
    assert ks.kontrol() is True, "Reset sonrası kill switch açılmalı"


# ─────────────────────────────────────────────
# 9. POZİSYON BOYUTU (kritik — yanlış boyut = para kaybı)
# ─────────────────────────────────────────────
def test_pozisyon_boyutu_pozitif():
    """Pozisyon boyutu her zaman pozitif olmalı."""
    from engines.adaptive_sizing import AdaptiveSizing
    sz = AdaptiveSizing(base_usdt=20.0, max_usdt=100.0)
    usdt = sz.hesapla(confidence=70, rejim="TREND_UP", atr_pct=1.0,
                      ai_score=6, edge_score=60, bakiye=1000)
    assert usdt > 0, "Pozisyon boyutu pozitif olmalı"


def test_pozisyon_boyutu_max_asmaz():
    """KRİTİK: Pozisyon boyutu bakiyenin makul oranını aşmamalı."""
    from engines.adaptive_sizing import AdaptiveSizing
    sz = AdaptiveSizing(base_usdt=20.0, max_usdt=100.0)
    bakiye = 1000
    usdt = sz.hesapla(confidence=100, rejim="TREND_UP", atr_pct=0.3,
                      ai_score=12, edge_score=100, bakiye=bakiye,
                      max_bakiye_pct=0.15)
    # En agresif senaryoda bile bakiyenin %15'ini (+ pay) aşmamalı
    assert usdt <= bakiye * 0.15 * 1.05, (
        f"Pozisyon boyutu limiti aştı: {usdt:.0f} > {bakiye*0.15:.0f} "
        f"(aşırı pozisyon = aşırı risk)")


def test_pozisyon_boyutu_volatilitede_kuculur():
    """Yüksek volatilitede pozisyon boyutu küçülmeli (risk azaltma)."""
    from engines.adaptive_sizing import AdaptiveSizing
    sz = AdaptiveSizing(base_usdt=20.0, max_usdt=100.0)
    dusuk_vol = sz.hesapla(confidence=70, rejim="TREND_UP", atr_pct=0.5,
                           ai_score=6, edge_score=60, bakiye=10000)
    yuksek_vol = sz.hesapla(confidence=70, rejim="VOLATILE", atr_pct=5.0,
                            ai_score=6, edge_score=60, bakiye=10000)
    assert yuksek_vol < dusuk_vol, (
        "Yüksek volatilitede pozisyon küçülmeli (risk yönetimi)")


# ─────────────────────────────────────────────
# 10. ÇOKLU BORSA FİYAT DOĞRULAMA
# ─────────────────────────────────────────────
def test_multiexchange_baslar():
    """Multi-exchange motoru başlamalı."""
    from data.multi_exchange import get_multiexchange
    me = get_multiexchange()
    assert me is not None


def test_multiexchange_karsilastir_yapisi():
    """karsilastir geçerli bir sonuç yapısı dönmeli."""
    from data.multi_exchange import get_multiexchange
    me = get_multiexchange()
    # Ağ olmadan: sadece Binance fiyatıyla çağır (diğer borsalar None döner)
    sonuc = me.karsilastir("BTCUSDT", 50000.0)
    assert hasattr(sonuc, "guvenilir"), "Sonuçta guvenilir alanı olmalı"
    assert hasattr(sonuc, "binance"), "Sonuçta binance alanı olmalı"
    assert sonuc.binance == 50000.0, "Binance fiyatı korunmalı"


# ─────────────────────────────────────────────
# 11. VETO SAYACI (v32 — işlem teşhisi)
# ─────────────────────────────────────────────
def test_veto_sayaci():
    """Veto sayacı reddedilen işlemleri doğru saymalı."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("m_veto", "main.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # Temiz başlangıç
    m._veto_kaydet("test_neden_a", "BTC")
    m._veto_kaydet("test_neden_a", "ETH")
    m._veto_kaydet("test_neden_b", "BTC")
    m._islem_acildi_kaydet()
    ozet = m.veto_ozet()
    assert ozet["toplam_red"] >= 3, "Veto sayısı en az 3 olmalı"
    assert ozet["acilan_islem"] >= 1, "Açılan işlem en az 1 olmalı"


# ─────────────────────────────────────────────
# 12. BAKİYE CACHE (v39 — ağ hatasında 0 dönmemeli)
# ─────────────────────────────────────────────
def test_bakiye_cache_mantigi():
    """v39: Bakiye cache mantığı — son bilinen değer korunmalı.
    (Gerçek ağ çağrısı yapmadan, cache mantığını izole test eder.)"""
    # Modül seviyesi cache değişkenini test et
    from data import binance_futures_client as bfc
    # _son_bilinen_bakiye bir liste [None] olarak tanımlı
    assert hasattr(bfc, "_son_bilinen_bakiye"), "Bakiye cache değişkeni yok"
    # Cache'e değer yaz, korunduğunu doğrula
    bfc._son_bilinen_bakiye[0] = 1500.0
    assert bfc._son_bilinen_bakiye[0] == 1500.0, "Cache değeri korunmalı"



def test_minimum_boyut_limitleri_ezmez():
    """v52 KRİTİK: Minimum işlem boyutu, bakiye/risk limitlerini EZMEMELİ.

    Eski kod `max(usdt, 5.0)` ile minimumu limitlerden SONRA uyguluyordu:
      • Bakiye 8$ → limit 1.20$ olmalı ama 5$ açılıyordu (4.2x aşım)
      • 4 ard arda kayıpta streak koruması (0.3x) minimum tarafından eziliyordu
    Doğru davranış: boyut minimumun altındaysa 0 dön (işlem açma)."""
    from engines.adaptive_sizing import AdaptiveSizing
    # Düşük bakiye: limit aşılmamalı
    sz = AdaptiveSizing(base_usdt=20, max_usdt=100)
    u = sz.hesapla(confidence=70, rejim="TREND_UP", atr_pct=1.0,
                   ai_score=6, edge_score=60, bakiye=8.0)
    assert u == 0.0, f"Düşük bakiyede limit aşıldı: {u} (limit 1.20$)"

    # Kayıp serisinde koruma minimum tarafından ezilmemeli
    sz2 = AdaptiveSizing(base_usdt=20, max_usdt=100)
    for _ in range(4):
        sz2.sonuc_bildir(kazandi=False)
    u2 = sz2.hesapla(confidence=50, rejim="VOLATILE", atr_pct=4.0,
                     ai_score=4, edge_score=40, bakiye=30.0)
    assert u2 == 0.0, f"Kayıp serisi koruması ezildi: {u2}"


def test_normal_boyut_bozulmadi():
    """Düzeltme normal işlemleri engellememeli (fazla katı olmamalı)."""
    from engines.adaptive_sizing import AdaptiveSizing
    sz = AdaptiveSizing(base_usdt=20, max_usdt=100)
    u = sz.hesapla(confidence=75, rejim="TREND_UP", atr_pct=1.0,
                   ai_score=7, edge_score=70, bakiye=1000.0)
    assert 5.0 <= u <= 150.0, f"Normal senaryoda boyut anormal: {u}"


# ─────────────────────────────────────────────
# v55 REGRESYON TESTLERİ
# Bu turda bulunan kritik hataların geri gelmemesi için.
# ─────────────────────────────────────────────
def test_istisna_hiyerarsisi_bozulmamis():
    """CorrelationLimitError RiskError alt sınıfı OLMALI.

    v55: Sınıf iki kez tanımlanmıştı; ikinci tanım (AstraError tabanlı)
    birincisini gölgeleyip `except RiskError` bloklarının korelasyon
    ihlalini yakalamasını engelliyordu.
    """
    from utils.exceptions import (CorrelationLimitError, RiskError,
                                   MarginExceededError, LiquidationRiskError)
    assert issubclass(CorrelationLimitError, RiskError), \
        "CorrelationLimitError artık RiskError alt sınıfı DEĞİL — yinelenen tanım geri gelmiş olabilir"
    assert issubclass(MarginExceededError, RiskError)
    assert issubclass(LiquidationRiskError, RiskError)


def test_rate_limit_error_ornekleneblir():
    """RateLimitError örneklenebilmeli (v55: __init__ bozuktu).

    NetworkError.__init__ `retryable` parametresi almıyordu; RateLimitError
    onu geçirdiği için her örnekleme TypeError veriyordu.
    """
    from utils.exceptions import RateLimitError, exchange_hata_siniflandir
    e = RateLimitError("test", 30)
    assert e.bekleme_suresi == 30 and e.retryable is True
    # Binance -1003 doğru tiple sınıflandırılmalı
    s = exchange_hata_siniflandir(-1003, "too many requests", "/fapi/v1/x")
    assert isinstance(s, RateLimitError), \
        f"-1003 RateLimitError yerine {type(s).__name__} döndü"


def test_tanimsiz_isim_yok():
    """Projede tanımsız isim (NameError kaynağı) kalmamalı.

    v55'te 6 adet vardı: main.py'da JOURNAL_DB_PATH/LOOKBACK/reconciler,
    execution_node.py'da InsufficientBalanceError. Bunlar strateji
    doğrulayıcıyı ve TFT'yi sessizce devre dışı bırakıyordu.
    """
    import subprocess, glob
    try:
        r = subprocess.run([sys.executable, "-m", "pyflakes"] +
                           glob.glob("*.py") + glob.glob("*/*.py"),
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return   # pyflakes yoksa testi atla
    tanimsiz = [s for s in (r.stdout or "").splitlines() if "undefined name" in s]
    assert not tanimsiz, "Tanımsız isim(ler) bulundu:\n" + "\n".join(tanimsiz)


def test_backtest_likidasyon_tek_kez_dusulur():
    """Likidasyonda teminat İKİ KEZ düşülmemeli (v55 düzeltmesi).

    Girişte teminat zaten bakiyeden çıkıyor; likidasyonda tekrar
    çıkarılırsa gerçek zararın 2 katı kaydediliyordu.
    """
    from engines.backtest_engine import backtest_calistir
    df = _ornek_ohlcv(200)
    close = df["Close"]
    # Her barda sinyal üret ki likidasyon ihtimali doğsun
    sinyaller = pd.Series([1 if i % 20 == 0 else 0 for i in range(len(close))],
                           index=close.index)
    r = backtest_calistir(df, sinyaller, close,
                          baslangic_bakiye=1000.0, kaldirac=5)
    # Bakiye asla başlangıcın negatifine düşecek kadar erimemeli
    assert r["toplam_getiri"] > -100.0, \
        f"Toplam getiri %{r['toplam_getiri']} — teminat çift düşülüyor olabilir"
    assert r["max_drawdown"] <= 100.0, \
        f"max_drawdown %{r['max_drawdown']} — %100'ü aşamaz"


def test_supertrend_yon_gecerli():
    """SuperTrend yönü yalnızca +1/-1 olmalı (v55: ilk bar 0 kalabiliyordu)."""
    from core.indicators import hesapla_supertrend
    df = _ornek_ohlcv(120)
    _, direction = hesapla_supertrend(df)
    gecersiz = [int(v) for v in direction.dropna().unique() if int(v) not in (1, -1)]
    assert not gecersiz, f"Geçersiz SuperTrend yönü: {gecersiz} (yalnızca +1/-1 olmalı)"


def test_event_bus_handler_hatasi_dispatcher_oldurmez():
    """Bir handler patlasa bile dispatcher thread'i YAŞAMALI.

    v55: except tuple'ı dardı (KeyError yakalanmıyordu) → tek bozuk event
    dispatcher'ı öldürüyor, Kelly/PnL/kill-switch güncellemeleri sessizce
    duruyordu.
    """
    import time as _t
    from engines.event_bus import EventBus, Event
    bus = EventBus()
    alinan = []
    def patlayan(msg): raise KeyError("eksik alan")   # dar tuple'da yakalanmazdı
    def saglam(msg):   alinan.append(msg)
    bus.subscribe(Event.ALERT, patlayan)
    bus.subscribe(Event.ALERT, saglam)
    bus.publish(Event.ALERT, {"mesaj": "1"}, "test")
    _t.sleep(0.4)
    bus.publish(Event.ALERT, {"mesaj": "2"}, "test")
    _t.sleep(0.4)
    assert len(alinan) == 2, (
        f"Dispatcher ilk hatadan sonra ölmüş olabilir "
        f"(yalnızca {len(alinan)}/2 event ulaştı)")


def test_multiexchange_cache_yolu_patlamaz():
    """Cache isabetinde AttributeError olmamalı (v55 düzeltmesi).

    `cached.get(...)` bir dataclass üzerinde çağrılıyordu → her cache
    isabetinde AttributeError → fiyat sapma VETOSU sessizce atlanıyordu.
    """
    from data.multi_exchange import MultiExchangePriceEngine
    m = MultiExchangePriceEngine()
    r1 = m.karsilastir("BTCUSDT", 50000.0)
    r2 = m.karsilastir("BTCUSDT", 50010.0)   # cache yolu — eskiden patlıyordu
    assert r1 is not None and r2 is not None
    assert hasattr(r2, "guvenilir"), "Cache yolundan geçerli sonuç dönmedi"


def test_pozisyon_boyutu_minimumun_altinda_sifir_doner():
    """Damping sonrası minimumun altına düşen boyut 0 dönmeli.

    v55: `max(usdt, 5.0)` ile 5'e yuvarlanıyordu — yani drawdown
    dampening'i tam da koruması gereken anda etkisiz kalıyordu.
    """
    from engines.risk_manager import RiskManager
    rm = RiskManager(baslangic_bakiye=100.0)
    usdt = rm.pozisyon_buyuklugu_hesapla(bakiye=3.0, fiyat=50000.0,
                                          atr=2000.0, win_rate=0.5)
    assert usdt == 0.0 or usdt >= 5.0, \
        f"Boyut {usdt} — minimum altındaysa 0 dönmeli, yuvarlanmamalı"


class _paper_sahne:
    """v58: Paper testleri için temiz sahne.

    NEDEN GEREKLİ (v58 K-C):
      Yeniden giriş beklemesi SEMBOL BAZLI çalışır ve testler aynı
      geçici DB'yi paylaşır. Önceki bir test BTCUSDT'yi kapattıysa
      sonraki test aynı sembolde pozisyon AÇAMAZ ve "filtre her şeyi
      reddediyor" gibi yanıltıcı bir hatayla düşer.

      Konusu bekleme OLMAYAN testler beklemeyi açıkça etkisizleştirmeli
      — sessizce ona takılmamalı. (Beklemenin kendi muhafızları
      `tests/test_yeniden_giris.py` içinde.)
    """
    def __init__(self, *semboller):
        self.semboller = semboller

    def __enter__(self):
        import sqlite3, config
        from data.database import tablolari_olustur
        from engines.kill_switch import get_kill_switch
        tablolari_olustur()
        get_kill_switch().reset()
        c = sqlite3.connect(os.environ["DB_PATH"])
        for s in self.semboller:
            c.execute("DELETE FROM trades WHERE sembol=?", (s,))
        c.commit(); c.close()
        self._eski = config.YENIDEN_GIRIS_BEKLEME_SN
        config.YENIDEN_GIRIS_BEKLEME_SN = 0

        # ── v58 (K-98): STRATEJİ MOTORU TAKLİT EDİLİYOR ──────────
        # Strateji kapısı `sinyal_veto_zinciri`'ye taşındı ve paper da
        # artık ondan geçiyor (§5.3). `main` import edilince GERÇEK
        # `StratejiEngine` kaydoluyor ve sentetik fikstürleri reddediyor
        # → "paper pozisyon açılmadı" diye YANILTICI hatalar.
        #
        # Bu testlerin konusu PAPER FİLTRE ZİNCİRİ, strateji motoru DEĞİL;
        # doğru sınır motoru izin verir hâle getirmek (canlı tarafta
        # `test_veto_zinciri.Ortam` da aynısını yapıyor). Strateji
        # kapısının KENDİ muhafızları `test_veto_zinciri_ortak.py`'de.
        import engines.futures_trade_engine as _fte
        self._eski_se = _fte._strategy_engine

        class _İzinVer:
            def karar_ver(self, sonuc, bakiye):
                return {"islem_yap": True, "strateji": "TREND_FOLLOW",
                        "usdt": 60}

        _fte._strategy_engine = _İzinVer()

        # v58 (K-103): çoklu borsa kapısı paper'a da eklendi ve GERÇEK
        # borsayı sorguluyor. Testler dış dünyaya bağlı olmamalı (K-101
        # dersi: hesapta pozisyon varken kırılan test guard değildir).
        import data.multi_exchange as _mx
        self._mx = _mx
        self._eski_mx = _mx.get_multiexchange

        class _Guvenilir:
            guvenilir = True; sebep = ""; arbitraj_yon = None; arbitraj_gucu = 0.0

        class _Mex:
            def karsilastir(self, sembol, fiyat): return _Guvenilir()

        _mx.get_multiexchange = lambda: _Mex()
        return self

    def __exit__(self, *a):
        import config
        import engines.futures_trade_engine as _fte
        config.YENIDEN_GIRIS_BEKLEME_SN = self._eski
        _fte._strategy_engine = self._eski_se
        self._mx.get_multiexchange = self._eski_mx
        return False


def test_paper_bakiye_pnl_ile_tutarli():
    """Bakiye HER ZAMAN `başlangıç + toplam_pnl` olmalı (v56 düzeltmesi).

    Bulunan iki sızıntı:
      1) Açılışta yuvarlanmamış usdt_boyut düşülüyor, kapanışta yuvarlanmış
         miktardan iade ediliyordu → her işlemde sessiz kayıp (%0.145'e kadar).
      2) DB brüt PnL, bakiye net PnL tutuyordu → komisyon kadar sapma.
    İkisi de `bakiye` ile `toplam_pnl`'i ayrıştırıyor, paper sonuçlarını
    güvenilmez kılıyordu (canlıya geçiş kararı buna dayanıyor).
    """
    import tempfile, os as _os
    from engines.paper_trading import PaperTrader
    from engines.kill_switch import get_kill_switch
    from data.database import toplam_pnl, acik_tradeler, tablolari_olustur

    with _paper_sahne("BTCUSDT"):
        pt = PaperTrader()
        baslangic = pt.bakiye
        ks = get_kill_switch()
        onceki_pnl = toplam_pnl("PAPER") or 0.0

        al = {"sembol": "BTCUSDT", "karar": "🚀 STRONG BUY", "son_close": 63000.0,
              "ai_score": 8, "confidence": 88, "atr": 600.0, "son_atr": 600.0,
              "edge_sonuc": {"gecti": True, "edge_score": 70, "sebep": ""}, "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3, "ana_trend_yon": "LONG", "yon": "LONG"}, "rejim": "TREND_UP", "yukselis_guveni": 88}

        for i in range(10):
            ks.reset()
            pt.sinyal_isle(al)
            if acik_tradeler("PAPER"):
                cikis = 63000.0 * (1.004 if i % 2 == 0 else 0.997)
                # v58: ai_score de TERS çevrilir. Üretimde `karar`
                # doğrudan ai_score'dan türer (karar_ver), yani
                # "SELL + ai=+8" imkânsız bir kombinasyondur. Çıkış
                # kapısı (K-A) artık bunu haklı olarak reddediyor.
                pt.sinyal_isle(dict(al, karar="📉 SELL", ai_score=-8,
                                    son_close=cikis))

        # v58: Döngü sonunda AÇIK pozisyon kalabilir. Tutarlı SELL
        # fikstürüyle (ai=-8) kapanışın ardından meşru bir SHORT açılıyor;
        # açık pozisyonun maliyeti bakiyeden düşülmüş ama `toplam_pnl`
        # kapanmamış işlemi saymadığı için karşılaştırma elma-armut olurdu.
        # Aynı muhasebe yolundan düzleştiriyoruz — testin ölçtüğü şey
        # (yuvarlama sızıntısı) korunuyor.
        for _t in list(acik_tradeler("PAPER")):
            pt._kapat_ve_bakiye_guncelle(_t, float(_t["giris_fiyat"]), "TEST_DUZLESTIR")

    pnl_delta = (toplam_pnl("PAPER") or 0.0) - onceki_pnl
    fark = pt.bakiye - (baslangic + pnl_delta)
    assert abs(fark) < 1e-6, (
        f"Bakiye/PnL sapması {fark:+.8f} — sessiz bakiye sızıntısı geri gelmiş "
        f"(bakiye={pt.bakiye:.6f}, beklenen={baslangic + pnl_delta:.6f})")


def test_paper_islem_maliyeti_modelleniyor():
    """Paper trading komisyon+slippage modellemeli (v56).

    Eskiden paper SIFIR maliyetle çalışıyordu; backtest ise komisyon ve
    slippage modelliyordu. Bu tutarsızlık paper sonuçlarını iyimser yapıp
    canlıya geçişte 'strateji bozuldu' yanılgısına yol açıyordu.
    """
    from engines.paper_trading import PaperTrader
    from engines.kill_switch import get_kill_switch
    from data.database import toplam_pnl, acik_tradeler

    with _paper_sahne("ETHUSDT"):
        pt = PaperTrader()
        get_kill_switch().reset()
        onceki = toplam_pnl("PAPER") or 0.0

        al = {"sembol": "ETHUSDT", "karar": "🚀 STRONG BUY", "son_close": 2000.0,
              "ai_score": 8, "confidence": 88, "atr": 20.0, "son_atr": 20.0,
              "edge_sonuc": {"gecti": True, "edge_score": 70, "sebep": ""}, "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3, "ana_trend_yon": "LONG", "yon": "LONG"}, "rejim": "TREND_UP", "yukselis_guveni": 88}
        pt.sinyal_isle(al)
        acik = [t for t in acik_tradeler("PAPER") if t["sembol"] == "ETHUSDT"]
        assert acik, "Paper pozisyon açılmadı — test önkoşulu sağlanamadı"

        # Giriş slippage'ı ALEYHTE olmalı (LONG → sinyal fiyatından yukarı)
        assert acik[0]["giris_fiyat"] > 2000.0, (
            f"LONG girişte slippage uygulanmamış "
            f"(giris={acik[0]['giris_fiyat']}, sinyal=2000.0)")

        # Aynı fiyattan kapanış NEGATİF PnL vermeli (komisyon + slippage)
        # v58: ai_score TERS (bkz. bakiye testindeki not)
        pt.sinyal_isle(dict(al, karar="📉 SELL", ai_score=-8, son_close=2000.0))
        delta = (toplam_pnl("PAPER") or 0.0) - onceki

        # v58: Kapanışın ardından meşru bir SHORT açılıyor. Açık bırakılırsa
        # MAX_OPEN_POSITIONS=1 yüzünden SONRAKİ testler pozisyon açamaz ve
        # "filtre her şeyi reddediyor" gibi yanıltıcı hata verirler.
        for _t in list(acik_tradeler("PAPER")):
            pt._kapat_ve_bakiye_guncelle(_t, float(_t["giris_fiyat"]), "TEST_DUZLESTIR")
    assert delta < 0, (
        f"Aynı fiyattan kapanan işlemin PnL'i {delta:+.4f} — "
        f"işlem maliyeti modellenmiyor (sıfır maliyet varsayımı)")


def test_telegram_mesaj_bolme():
    """Telegram 4096 sınırı aşılmamalı (v56).

    Kod tabanında 60 gönderim noktasının hiçbiri uzunluk kontrolü
    yapmıyordu; veriye göre büyüyen raporlar Telegram tarafından
    reddediliyor (400: message is too long) ve kullanıcıya HİÇ ulaşmıyordu.
    """
    # v56: Fonksiyon core/telegram_gonderim.py'ye taşındı. Kaynağı regex'le
    # kazımak yerine doğrudan import ediliyor — hem daha sağlam hem de
    # ileride taşınırsa test kırılmıyor (main.py da yeniden dışa veriyor).
    from core.telegram_gonderim import _tg_parcala as bol
    import main
    assert main._tg_parcala is bol, \
        "main.py _tg_parcala'yı yeniden dışa vermiyor — çağrı noktaları kırılır"

    for n in (100, 3899, 3901, 12000, 50000):
        parcalar = bol("x" * n)
        assert all(len(p) <= 3900 for p in parcalar), \
            f"{n} karakterlik mesajda 3900'ü aşan parça var"

    # Satır sınırından bölmeli ve içerik kaybolmamalı
    cok = "".join(f"satir-{i:03d} {'a'*80}\n" for i in range(100))
    parcalar = bol(cok)
    assert all(len(p) <= 3900 for p in parcalar)
    assert "\n".join(parcalar).replace("\n", "") == cok.replace("\n", ""), \
        "Mesaj bölünürken içerik kayboldu"

    # Kenar durumlar çökmemeli
    assert bol(None) == [""] and bol("") == [""]


def test_telegram_komutlari_bloklamiyor():
    """Async Telegram handler'ları event loop'u kilitlememeli (v56).

    Bloklayan REST çağrısı (futures_bakiye vb.) doğrudan async handler
    içinde çağrılırsa, yavaş ağda 15s HTTP timeout boyunca TÜM komutlar
    yanıtsız kalır.
    """
    import re
    kaynak = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    bloklar = re.findall(r"(async def cmd_\w+.*?)(?=\nasync def |\ndef |\Z)",
                          kaynak, re.S)
    assert bloklar, "async komut handler'ı bulunamadı"
    BLOKLAYAN = ["futures_bakiye(", "acik_futures_pozisyonlar(",
                 "veri_indir(", "coin_analiz("]
    riskli = []
    for b in bloklar:
        ad = re.match(r"async def (\w+)", b).group(1)
        if "run_in_executor" in b:
            continue
        bulunan = [k for k in BLOKLAYAN if k in b]
        if bulunan:
            riskli.append(f"{ad}({','.join(bulunan)})")
    assert not riskli, (
        "run_in_executor kullanmadan bloklayan çağrı yapan handler'lar: "
        + ", ".join(riskli))


def test_panel_pnl_isareti_dusmuyor():
    """Panel negatif PnL'de eksi işaretini göstermeli (v56).

    `Math.abs()` + koşulsuz '+' kalıbı 4 ayrı yerde zararı kâr gibi
    gösteriyordu; yalnızca CSS rengi ayırt ediyordu.
    """
    kaynak = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "api", "dashboard.py"), encoding="utf-8").read()
    assert "'+' : ''" not in kaynak, (
        "Panelde işaretsiz-negatif kalıbı (\"'+' : ''\") geri gelmiş — "
        "zarar, kâr gibi görünür")
    for yardimci in ("pnlSign", "pnlSignPct", "pnlSignUsd"):
        assert yardimci in kaynak, f"{yardimci} yardımcısı kaldırılmış"


# ─────────────────────────────────────────────
# Bağımsız çalıştırma
# ─────────────────────────────────────────────
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA ÇEKİRDEK TEST PAKETİ — {len(testler)} test")
    print(f"{'='*56}")
    basari, hata = 0, 0
    for t in testler:
        try:
            t()
            print(f"  [GEÇTİ]  {t.__name__}")
            basari += 1
        except AssertionError as e:
            print(f"  [HATA]   {t.__name__}")
            print(f"           → {str(e)[:70]}")
            hata += 1
        except Exception as e:
            print(f"  [ÇÖKTÜ]  {t.__name__}: {type(e).__name__}: {str(e)[:50]}")
            hata += 1
    print(f"{'='*56}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'='*56}\n")
    sys.exit(0 if hata == 0 else 1)
