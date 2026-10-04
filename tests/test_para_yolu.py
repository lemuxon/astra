# =========================================================
# ASTRA — PARA YOLU TESTLERİ (v56)
# Çalıştırma: python tests/test_para_yolu.py
#
# Bu paket, GERÇEK PARANIN geçtiği kod yollarını hedefler:
#   emir boyutlandırma · lot/tick yuvarlama · risk limitleri ·
#   acil SL matematiği · state ↔ borsa senkronizasyonu
#
# Denetimde bu modüllerin kapsamı en düşüktü:
#   binance_futures_client %22 · order_reconciler %14 ·
#   fill_reconciler %0 · order_engine %25 · futures_trade_engine %17
#
# Borsa tamamen mock'lanır — hiçbir test ağa çıkmaz, emir göndermez.
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

import math


# ═════════════════════════════════════════════════════════
# 1. LOT / TICK YUVARLAMA — yanlış yuvarlama = yanlış boyut
# ═════════════════════════════════════════════════════════
def _filtre_yerlestir(sembol="BTCUSDT", step=0.001, tick=0.1,
                      qty_prec=3, prc_prec=1, min_notional=50.0):
    """exchangeInfo cache'ini doldur — ağa çıkmadan test için."""
    import data.binance_futures_client as bfc
    bfc._exchange_info_cache[sembol] = {
        "step_size": step, "tick_size": tick,
        "qty_prec": qty_prec, "prc_prec": prc_prec,
        "min_notional": min_notional,
    }
    return bfc


def test_miktar_hep_asagi_yuvarlanir():
    """Miktar ASLA yukarı yuvarlanmamalı — aksi halde hesaptaki
    paradan büyük pozisyon açılır ve borsa emri reddeder."""
    bfc = _filtre_yerlestir(step=0.001, qty_prec=3)
    for ham in (0.0019, 0.0011, 0.9999, 1.0009, 0.123456):
        d = bfc.miktar_duzelt_futures("BTCUSDT", ham)
        assert d <= ham + 1e-12, f"{ham} → {d} YUKARI yuvarlandı!"
        # step katı olmalı
        assert abs(d / 0.001 - round(d / 0.001)) < 1e-6, f"{d} step katı değil"


def test_miktar_step_altinda_sifir_doner():
    """step_size altındaki miktar 0'a düşer — çağıran bunu kontrol etmeli."""
    bfc = _filtre_yerlestir(step=0.001, qty_prec=3)
    assert bfc.miktar_duzelt_futures("BTCUSDT", 0.0009) == 0.0


def test_fiyat_tick_katina_yuvarlanir():
    """SL/TP fiyatı tick_size katı olmalı, yoksa borsa reddeder."""
    bfc = _filtre_yerlestir(tick=0.1, prc_prec=1)
    for ham in (63000.04, 63000.06, 62999.97, 1.23456):
        d = bfc.fiyat_duzelt_futures("BTCUSDT", ham)
        assert abs(d / 0.1 - round(d / 0.1)) < 1e-6, f"{ham} → {d} tick katı değil"


def test_yuvarlama_sifir_step_cokmez():
    """step/tick 0 gelirse (bozuk exchangeInfo) çökmemeli."""
    bfc = _filtre_yerlestir(step=0.0, tick=0.0)
    assert bfc.miktar_duzelt_futures("BTCUSDT", 1.23456) > 0
    assert bfc.fiyat_duzelt_futures("BTCUSDT", 1.23456) > 0


# ═════════════════════════════════════════════════════════
# 2. RİSK LİMİTLERİ — sermayeyi koruyan kapılar
# ═════════════════════════════════════════════════════════
def test_max_acik_pozisyon_limiti():
    from engines.risk_manager import RiskManager
    from config import MAX_OPEN_POSITIONS
    rm = RiskManager()
    az = [{"sembol": f"C{i}", "yon": "LONG"} for i in range(MAX_OPEN_POSITIONS - 1)]
    cok = [{"sembol": f"C{i}", "yon": "LONG"} for i in range(MAX_OPEN_POSITIONS)]
    assert rm.acik_pozisyon_kontrol(az) is False, "Limit altında engellendi"
    assert rm.acik_pozisyon_kontrol(cok) is True, "Limit aşıldı ama engellenmedi!"


def test_ayni_yon_korelasyon_limiti():
    from engines.risk_manager import RiskManager
    from config import MAX_SAME_DIRECTION
    rm = RiskManager()
    pozlar = [{"sembol": f"C{i}", "yon": "LONG"} for i in range(MAX_SAME_DIRECTION)]
    assert rm.korrelasyon_kontrol(pozlar, "LONG") is True, \
        "Aynı yönde limit aşıldı ama engellenmedi (korelasyon riski)"
    assert rm.korrelasyon_kontrol(pozlar, "SHORT") is False, \
        "Ters yön gereksiz engellendi"


def test_gunluk_zarar_limiti_tetiklenir():
    """Günlük zarar limiti aşılınca işlem DURMALI."""
    from engines.risk_manager import RiskManager
    from config import DAILY_LOSS_LIMIT_PCT
    rm = RiskManager(baslangic_bakiye=1000.0)
    bakiye = 1000.0
    limit = bakiye * (DAILY_LOSS_LIMIT_PCT / 100)
    assert rm.gunluk_limit_kontrol(bakiye) is False, "Zarar yokken durdurdu"
    rm.pnl_guncelle(-(limit * 1.05), pnl_pct=-5.0, sembol="BTCUSDT")
    assert rm.gunluk_limit_kontrol(bakiye) is True, \
        f"Günlük limit ({limit:.2f}) aşıldı ama işlem DURDURULMADI!"


def test_marjin_bilinmezse_fail_closed():
    """Bakiye 0/bilinmiyorsa işlem ENGELLENMELİ (fail-closed).

    İmza: marjin_kontrol(acik_pozisyonlar, yeni_marjin, toplam_bakiye)
    Ağ hatasında futures_bakiye() 0 dönebilir; o durumda marjin oranı
    hesaplanamaz ve izin vermek marjin korumasını tamamen devre dışı bırakır.
    """
    from engines.risk_manager import RiskManager
    from config import MAX_MARGIN_PCT
    rm = RiskManager()
    # bakiye = 0 → ENGELLE
    assert rm.marjin_kontrol([], 10.0, 0.0) is True, \
        "Bakiye 0 iken işleme izin verildi — fail-open!"
    # normal bakiye, küçük marjin → izin ver
    assert rm.marjin_kontrol([], 1.0, 1000.0) is False, \
        "Küçük marjin gereksiz engellendi"
    # marjin limitini aşan istek → engelle
    asiri = 1000.0 * (MAX_MARGIN_PCT / 100) * 1.5
    assert rm.marjin_kontrol([], asiri, 1000.0) is True, \
        f"Marjin limiti %{MAX_MARGIN_PCT} aşıldı ama engellenmedi"


def test_drawdown_hesabi_dogru():
    from engines.risk_manager import RiskManager
    rm = RiskManager(baslangic_bakiye=1000.0)
    rm.pnl_guncelle(+200.0, pnl_pct=20.0, sembol="X")   # zirve 1200
    rm.pnl_guncelle(-300.0, pnl_pct=-25.0, sembol="X")  # mevcut 900
    dd = rm.drawdown_pct()
    beklenen = (1200 - 900) / 1200 * 100
    assert abs(dd - beklenen) < 0.01, f"drawdown {dd:.2f} ≠ {beklenen:.2f}"


def test_pnl_guncelle_thread_guvenli():
    """v56: risk_manager'a kilit eklendi — eşzamanlı güncellemede kayıp olmamalı."""
    import threading
    from engines.risk_manager import RiskManager
    rm = RiskManager(baslangic_bakiye=10000.0)
    N, ADIM = 40, -1.0

    def isci():
        for _ in range(N):
            rm.pnl_guncelle(ADIM, pnl_pct=-0.1, sembol="BTCUSDT")

    tl = [threading.Thread(target=isci) for _ in range(4)]
    for t in tl: t.start()
    for t in tl: t.join(timeout=30)
    beklenen = 4 * N * ADIM
    assert abs(rm.gunluk_pnl - beklenen) < 1e-6, (
        f"Eşzamanlı PnL güncellemesinde kayıp: {rm.gunluk_pnl} ≠ {beklenen} "
        f"— kilit çalışmıyor, günlük zarar limiti eksik sayabilir")


# ═════════════════════════════════════════════════════════
# 3. ACİL SL MATEMATİĞİ — v55'te kritik bug'dı
# ═════════════════════════════════════════════════════════
def test_acil_sl_kaldiraca_duyarli():
    """Acil SL mesafesi kaldıraçla ölçeklenmeli.

    v55 öncesi sabit %5 kullanılıyordu: 20x kaldıraçta %5 fiyat hareketi
    = %100 sermaye kaybı (likidasyon). Formül: min(%5, (1/kaldıraç)*0.5)
    """
    for kald, azami_kayip_pct in [(1, 5.0), (5, 50.0), (10, 50.0), (20, 50.0)]:
        mesafe = min(0.05, (1.0 / kald) * 0.5)
        sermaye_kaybi = mesafe * kald * 100
        assert sermaye_kaybi <= azami_kayip_pct + 1e-9, (
            f"{kald}x kaldıraçta SL mesafesi %{mesafe*100:.2f} → "
            f"sermaye kaybı %{sermaye_kaybi:.0f} (azami %{azami_kayip_pct})")


def test_likidasyon_fiyati_borsadan_oncelikli():
    """v56: Borsanın kendi liquidationPrice'ı varsa O kullanılmalı."""
    from execution.failsafe_liquidation import likidasyon_fiyati
    poz = {"sembol": "BTCUSDT", "yon": "LONG", "giris": 60000.0,
           "kaldirac": 5, "likidasyon_fiyat": 48123.45}
    assert likidasyon_fiyati(poz) == 48123.45, "Borsa değeri yok sayıldı"


def test_likidasyon_fiyati_fallback():
    """Borsa değeri yoksa elle yaklaşım kullanılmalı, 0 dönmemeli."""
    from execution.failsafe_liquidation import likidasyon_fiyati
    lon = likidasyon_fiyati({"yon": "LONG", "giris": 60000.0,
                             "kaldirac": 5, "likidasyon_fiyat": 0})
    sho = likidasyon_fiyati({"yon": "SHORT", "giris": 60000.0,
                             "kaldirac": 5, "likidasyon_fiyat": 0})
    assert 0 < lon < 60000, f"LONG likidasyon girişin altında olmalı: {lon}"
    assert sho > 60000, f"SHORT likidasyon girişin üstünde olmalı: {sho}"


def test_likidasyon_bozuk_veride_sifir_doner():
    """kaldirac=0 / giris=0 gibi bozuk veride ZeroDivisionError olmamalı."""
    from execution.failsafe_liquidation import likidasyon_fiyati
    for poz in ({"yon": "LONG", "giris": 0, "kaldirac": 5},
                {"yon": "LONG", "giris": 60000, "kaldirac": 0},
                {}, {"yon": "SHORT"}):
        assert likidasyon_fiyati(poz) == 0.0


# ═════════════════════════════════════════════════════════
# 4. STATE ↔ BORSA SENKRONİZASYONU — C-2'nin kalbi
# ═════════════════════════════════════════════════════════
def test_pozisyon_sorgusu_strict_ayrimi():
    """'Sıfır pozisyon' ile 'sorgulayamadım' AYRI olmalı."""
    import data.binance_futures_client as bfc
    from utils.exceptions import NetworkError
    orij = bfc._futures_istek
    bfc._futures_istek = lambda *a, **kw: (_ for _ in ()).throw(
        NetworkError("kesinti", "test"))
    try:
        assert bfc.acik_futures_pozisyonlar() == [], "strict=False uyumu bozuldu"
        try:
            bfc.acik_futures_pozisyonlar(strict=True)
            raise AssertionError("strict=True istisna YÜKSELTMEDİ — fail-open!")
        except NetworkError:
            pass
    finally:
        bfc._futures_istek = orij


def test_bakiye_strict_ayrimi():
    """v56: futures_bakiye de aynı ayrımı yapmalı (R-1)."""
    import data.binance_futures_client as bfc
    from utils.exceptions import FatalExchangeError
    orij = bfc._futures_istek
    bfc._son_bilinen_bakiye[0] = None
    bfc._futures_istek = lambda *a, **kw: (_ for _ in ()).throw(
        FatalExchangeError(-2015, "Invalid API-key", "/x"))
    try:
        assert bfc.futures_bakiye() == 0.0, "strict=False uyumu bozuldu"
        try:
            bfc.futures_bakiye(strict=True)
            raise AssertionError(
                "strict=True istisna YÜKSELTMEDİ — kimlik hatası "
                "'bakiye 0' gibi görünür, teşhis yanlış yöne sapar")
        except FatalExchangeError:
            pass
    finally:
        bfc._futures_istek = orij
        bfc._son_bilinen_bakiye[0] = None


def test_pozisyon_listesi_likidasyon_alanini_tasiyor():
    """v56: positionRisk'ten liquidationPrice okunmalı (H-11)."""
    import data.binance_futures_client as bfc
    orij = bfc._futures_istek
    bfc._futures_istek = lambda *a, **kw: [{
        "symbol": "BTCUSDT", "positionAmt": "0.5", "entryPrice": "60000",
        "unRealizedProfit": "12.3", "leverage": "5", "liquidationPrice": "48500.5"}]
    try:
        p = bfc.acik_futures_pozisyonlar(strict=True)[0]
        assert p["likidasyon_fiyat"] == 48500.5, \
            "liquidationPrice atılıyor — failsafe elle hesaba düşer"
        assert p["yon"] == "LONG" and p["kaldirac"] == 5
    finally:
        bfc._futures_istek = orij


def test_sifir_miktarli_pozisyon_filtreleniyor():
    """positionAmt=0 olan kayıtlar açık pozisyon SAYILMAMALI."""
    import data.binance_futures_client as bfc
    orij = bfc._futures_istek
    bfc._futures_istek = lambda *a, **kw: [
        {"symbol": "BTCUSDT", "positionAmt": "0", "entryPrice": "0",
         "unRealizedProfit": "0", "leverage": "5", "liquidationPrice": "0"},
        {"symbol": "ETHUSDT", "positionAmt": "-1.5", "entryPrice": "2000",
         "unRealizedProfit": "-3", "leverage": "3", "liquidationPrice": "2600"}]
    try:
        p = bfc.acik_futures_pozisyonlar(strict=True)
        assert len(p) == 1 and p[0]["sembol"] == "ETHUSDT"
        assert p[0]["yon"] == "SHORT", "Negatif positionAmt SHORT olmalı"
    finally:
        bfc._futures_istek = orij


# ═════════════════════════════════════════════════════════
# 5. HATA SINIFLANDIRMA — retry/fatal kararını belirler
# ═════════════════════════════════════════════════════════
def test_fatal_kodlar_retry_edilmez():
    """Yetersiz bakiye gibi fatal hatalarda retry YAPILMAMALI."""
    from utils.exceptions import exchange_hata_siniflandir, FatalExchangeError
    for kod in (-2010, -1121, -4003, -1100):
        e = exchange_hata_siniflandir(kod, "test", "/x")
        assert e.retryable is False, f"{kod} retryable işaretlendi — çift emir riski"


def test_gecici_kodlar_retry_edilir():
    from utils.exceptions import exchange_hata_siniflandir
    e = exchange_hata_siniflandir(-1001, "internal error", "/x")
    assert e.retryable is True


def test_fatal_kod_kumesi_tek_kaynak():
    """v56: exchange_hata_siniflandir FATAL_CODES'u kullanmalı (L-2)."""
    from utils.exceptions import (exchange_hata_siniflandir, FatalExchangeError)
    for kod in FatalExchangeError.FATAL_CODES:
        e = exchange_hata_siniflandir(kod, "t", "/x")
        assert e.retryable is False, (
            f"{kod} FATAL_CODES'ta ama retryable — iki liste ayrışmış")


# ═════════════════════════════════════════════════════════
# 6. GÖSTERGE MATEMATİĞİ — giriş kararlarını sürüyor
# ═════════════════════════════════════════════════════════
def _ohlcv(n=300, sabit=False, seed=1):
    import numpy as np, pandas as pd
    rng = np.random.default_rng(seed)
    close = (np.full(n, 100.0) if sabit
             else 100 + np.cumsum(rng.normal(0, 0.5, n)))
    return pd.DataFrame({
        "Open": close, "High": close + (0 if sabit else 0.5),
        "Low": close - (0 if sabit else 0.5), "Close": close,
        "Volume": np.full(n, 1000.0)})


def test_rsi_sinirlar_icinde():
    from core.indicators import hesapla_rsi
    r = hesapla_rsi(_ohlcv()["Close"])
    g = r.dropna()
    assert len(g) > 0 and g.min() >= 0 and g.max() <= 100, \
        f"RSI 0-100 dışına çıktı: {g.min()}-{g.max()}"


def test_duz_seride_sifira_bolme_yok():
    """Tamamen düz fiyat serisinde göstergeler NaN/inf üretmemeli."""
    import numpy as np
    from core.indicators import hesapla_rsi, hesapla_atr
    df = _ohlcv(sabit=True)
    r = hesapla_rsi(df["Close"]).dropna()
    a = hesapla_atr(df).dropna()
    assert not np.isinf(r).any(), "RSI'da inf — sıfıra bölme"
    assert not np.isinf(a).any(), "ATR'de inf — sıfıra bölme"


def test_atr_negatif_olamaz():
    from core.indicators import hesapla_atr
    a = hesapla_atr(_ohlcv()).dropna()
    assert (a >= 0).all(), "ATR negatif — mutlak değer hatası"


def test_gostergeler_gelecege_bakmiyor():
    """Bir barın göstergesi, SONRAKİ barlar değişince değişmemeli.

    Değişiyorsa look-ahead bias var demektir — backtest sonuçları
    gerçekte elde edilemeyecek performans gösterir.
    """
    from core.indicators import hesapla_rsi
    df = _ohlcv(200, seed=3)
    kesim = 150
    tam = hesapla_rsi(df["Close"])
    kismi = hesapla_rsi(df["Close"].iloc[:kesim])
    for i in range(kesim - 20, kesim):
        a, b = tam.iloc[i], kismi.iloc[i]
        if a == a and b == b:   # ikisi de NaN değilse
            assert abs(a - b) < 1e-6, (
                f"Bar {i}: RSI gelecek veriyle değişti ({a} → {b}) — LOOK-AHEAD BIAS")


# ═════════════════════════════════════════════════════════
# Bağımsız çalıştırma
# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA PARA YOLU TESTLERİ — {len(testler)} test")
    print(f"{'='*56}")
    basari, hata = 0, 0
    for t in testler:
        try:
            t()
            print(f"  [GEÇTİ]  {t.__name__}")
            basari += 1
        except AssertionError as e:
            print(f"  [HATA]   {t.__name__}")
            print(f"           → {str(e)[:90]}")
            hata += 1
        except Exception as e:
            print(f"  [ÇÖKTÜ]  {t.__name__}: {type(e).__name__}: {str(e)[:70]}")
            hata += 1
    print(f"{'='*56}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'='*56}\n")
    sys.exit(0 if hata == 0 else 1)
