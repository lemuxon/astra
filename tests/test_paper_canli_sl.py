# =========================================================
# ASTRA v57 — PAPER ↔ CANLI SL/TP EŞİTLİĞİ
# Çalıştırma: python tests/test_paper_canli_sl.py
#
# NE KORUYOR (DEVAM_NOTLARI §5.3):
#   Paper trading, canlıda çalışacak sistemi BİREBİR yansıtmalıdır.
#   Yansıtmıyorsa toplanan 100 işlem, canlıda var olmayan bir sistemin
#   verisidir ve canlıya geçiş kararı temelsiz kalır.
#
#   v56'ya kadar paper SL/TP'yi ŞÖYLE hesaplıyordu:
#       if yon == "LONG":
#           stop = risk.get("stop_loss") or (fiyat - atr*2)
#       else:
#           stop = fiyat + atr*2
#
#   ÜÇ AYRI AYRIŞMA:
#
#   1) LONG ve SHORT FARKLI KAYNAKTAN besleniyordu. LONG, `risk_hesapla()`
#      çıktısını kullanıyordu; o fonksiyon **yön parametresi almıyor**
#      ve yukarıdaki `atr` değişkenine uygulanan **%0.5 tabanını**
#      BYPASS ediyordu.
#      ÖLÇÜM (20 işlem): 8/8 LONG tabanı atladı, stop %0.11'e kadar indi,
#      **8 LONG'un 8'i de kaybetti**. Mekanik sonuç, şanssızlık değil.
#
#   2) Çarpanlar farklıydı: paper SL 2×ATR / TP 3×ATR,
#      canlı SL 1.5×ATR / TP1 2.0×ATR.
#
#   3) Canlı VOLATILE rejimde SL'i genişletiyor (×1.3), paper yapmıyordu.
#
#   ÇÖZÜM: Paper artık canlının `sl_tp_hesapla()` fonksiyonunu kullanıyor.
#   Tek kaynak → yeniden ayrışmaları imkânsız.
#
# §4.1: Muhafızların yanına KONTROL testleri var — "her zaman aynı sabiti
#   döndüren" bir fonksiyon simetri testlerini de geçerdi.
# =========================================================
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "test")
os.environ.setdefault("BINANCE_API_SECRET", "test")


# ─────────────────────────────────────────────
# 1. MUHAFIZ — yön simetrisi
# ─────────────────────────────────────────────
def test_long_ve_short_ayni_sl_mesafesini_alir():
    """LONG ve SHORT stop mesafesi EŞİT olmalı.

    Eskiden LONG `risk_hesapla`'dan, SHORT ATR formülünden besleniyordu →
    LONG stop'ları %0.11'e kadar iniyordu ve hepsi kaybediyordu.
    """
    from engines.futures_trade_engine import sl_tp_hesapla
    fiyat = 100.0
    for atr in (0.05, 0.2, 0.5, 1.0, 2.0):
        L = sl_tp_hesapla(fiyat, "LONG", atr, "RANGE")
        S = sl_tp_hesapla(fiyat, "SHORT", atr, "RANGE")
        mL = abs(fiyat - L["sl"]) / fiyat
        mS = abs(fiyat - S["sl"]) / fiyat
        assert abs(mL - mS) < 1e-9, (
            f"ATR={atr}: LONG stop %{mL*100:.3f}, SHORT %{mS*100:.3f} — "
            f"yön asimetrisi geri gelmiş")


def test_long_ve_short_ayni_tp_mesafesini_alir():
    """TP tarafında da simetri şart — yoksa R/R yöne göre değişir."""
    from engines.futures_trade_engine import sl_tp_hesapla
    fiyat = 100.0
    for atr in (0.2, 1.0):
        L = sl_tp_hesapla(fiyat, "LONG", atr, "RANGE")
        S = sl_tp_hesapla(fiyat, "SHORT", atr, "RANGE")
        assert abs(abs(fiyat - L["tp1"]) - abs(fiyat - S["tp1"])) < 1e-9, (
            f"ATR={atr}: TP mesafeleri yöne göre farklı")


def test_paper_canlinin_fonksiyonunu_kullanir():
    """Kaynak düzeyi: paper, `sl_tp_hesapla` çağırmalı; `risk_hesapla`
    çıktısını SL için KULLANMAMALI.

    İki ayrı hesap yolu kalırsa er geç yeniden ayrışırlar.
    """
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(kok, "engines", "paper_trading.py"),
              encoding="utf-8") as fh:
        kod = "\n".join(l for l in fh.read().splitlines()
                        if not l.strip().startswith("#"))
    assert "sl_tp_hesapla" in kod, (
        "paper canlının sl_tp_hesapla() fonksiyonunu kullanmıyor — "
        "paper↔canlı eşitliği yok")
    assert 'risk.get("stop_loss")' not in kod, (
        "paper hâlâ risk_hesapla çıktısını SL için kullanıyor — "
        "o fonksiyon yön almıyor ve ATR tabanını bypass ediyor")


def test_atr_tabani_her_iki_yonde_de_gecerli():
    """Çok küçük ATR'de bile stop makul kalmalı.

    Paper `atr = max(son_atr, fiyat*0.005)` ile taban uyguluyor.
    Eskiden LONG bu tabanı atlıyordu.
    """
    from engines.futures_trade_engine import sl_tp_hesapla
    fiyat = 100.0
    taban_atr = max(0.001, fiyat * 0.005)      # paper'daki taban mantığı
    for yon in ("LONG", "SHORT"):
        r = sl_tp_hesapla(fiyat, yon, taban_atr, "RANGE")
        m = abs(fiyat - r["sl"]) / fiyat * 100
        assert m >= 0.5, (
            f"{yon}: taban ATR ile stop mesafesi %{m:.3f} — gürültü bunu "
            f"vurur. Ölçülen vakada %0.11'lik stop'lar 8/8 kaybetti.")


# ─────────────────────────────────────────────
# 1b. DAVRANIŞSAL MUHAFIZ — asıl önemli olan bu
#
# Yukarıdaki testlerin çoğu `sl_tp_hesapla`'nın KENDİ özelliklerini
# ölçüyor; paper'ın onu KULLANDIĞINI değil. Mutasyon denemesinde
# (paper v56 davranışına döndürüldü) 7 testin 6'sı GEÇTİ — yalnızca
# kaynak kontrolü yakaladı. Bu yeterli değil: kaynak kontrolü, kodun
# başka bir yerde eski hesabı yapmasına kör.
#
# Aşağıdaki test GERÇEK paper pozisyonu açar ve DB'ye yazılan SL'e bakar.
# ─────────────────────────────────────────────
def test_paper_pozisyonu_simetrik_ve_tabanli_sl_aliyor():
    """GERÇEK paper işlemi aç → DB'deki SL mesafesini ölç.

    Çok küçük ATR verilir. Eski kodda LONG tabanı bypass edip %0.1'lik
    stop alırdı; SHORT %1.0 alırdı. Doğru kodda ikisi de eşit ve tabanlı.
    """
    import sqlite3
    from engines.paper_trading import PaperTrader
    from engines.kill_switch import get_kill_switch
    from data.database import tablolari_olustur, acik_tradeler

    tablolari_olustur()
    db = os.environ["DB_PATH"]
    olculen = {}

    for yon, karar, sembol in (("LONG",  "🚀 STRONG BUY", "SLTESTLUSDT"),
                               ("SHORT", "📉 SELL",       "SLTESTSUSDT")):
        pt = PaperTrader()
        get_kill_switch().reset()
        fiyat = 100.0
        sinyal = {
            "sembol": sembol, "karar": karar, "son_close": fiyat,
            "ai_score": 8 if yon == "LONG" else -8,
            "confidence": 88,
            # ÇOK küçük ATR — taban devreye girmeli
            "atr": fiyat * 0.0005, "son_atr": fiyat * 0.0005,
            # v58 (K-97): veto zinciri paper yoluna da bağlandı (§6.0).
            # `edge_sonuc` ve `mtf_confluence` artık ZORUNLU: üretimde
            # `coin_analiz` ikisini de HER ZAMAN üretiyor (ölçüldü 50/50),
            # onlarsız bir `sonuc` üretimde İMKÂNSIZDIR. Fikstür üretim
            # kuralına uymalı (§0.1) — kapı zayıflatılmadı.
            "edge_sonuc": {"gecti": True, "edge_score": 70, "sebep": ""},
            "mtf_confluence": {"bloklu": False, "hizalama_skoru": 3,
                               "ana_trend_yon": "LONG", "yon": "LONG"},
            "rejim": "RANGE", "yukselis_guveni": 88,
            # Eski kodun LONG'da kullandığı tuzak: tabansız, çok dar stop
            "risk": {"stop_loss": fiyat * 0.999, "take_profit": fiyat * 1.001},
        }
        pt.sinyal_isle(sinyal)
        kayit = [t for t in acik_tradeler("PAPER") if t["sembol"] == sembol]
        if not kayit:
            continue
        t = kayit[0]
        olculen[yon] = abs(t["giris_fiyat"] - t["stop_loss"]) / t["giris_fiyat"] * 100
        sqlite3.connect(db).execute(
            "DELETE FROM trades WHERE sembol=?", (sembol,)).connection.commit()

    assert "LONG" in olculen and "SHORT" in olculen, (
        f"Her iki yönde de pozisyon açılamadı: {olculen} — test önkoşulu")

    assert abs(olculen["LONG"] - olculen["SHORT"]) < 0.05, (
        f"LONG stop %{olculen['LONG']:.3f}, SHORT %{olculen['SHORT']:.3f} — "
        f"yön asimetrisi VAR. Eski kodda LONG, risk_hesapla çıktısını alıp "
        f"ATR tabanını bypass ediyordu ve 8/8 LONG kaybetmişti.")

    assert olculen["LONG"] >= 0.5, (
        f"LONG stop %{olculen['LONG']:.3f} — ATR tabanı (%0.5) uygulanmamış, "
        f"piyasa gürültüsü bu stop'u vurur")


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_sl_atr_ile_gercekten_degisiyor():
    """Stop mesafesi ATR ile ORANTILI değişmeli.

    "Her zaman sabit döndür" gibi bozuk bir kod, yukarıdaki simetri
    testlerinin HEPSİNİ geçerdi.
    """
    from engines.futures_trade_engine import sl_tp_hesapla
    fiyat = 100.0
    m1 = abs(fiyat - sl_tp_hesapla(fiyat, "LONG", 0.5, "RANGE")["sl"])
    m2 = abs(fiyat - sl_tp_hesapla(fiyat, "LONG", 1.0, "RANGE")["sl"])
    assert m2 > m1 * 1.5, (
        f"ATR iki katına çıktı ama stop {m1:.4f} → {m2:.4f} — "
        f"ATR'ye duyarlı değil, sabit dönüyor olabilir")


def test_kontrol_carpanlar_configten_geliyor():
    """SL/TP çarpanları config'ten okunmalı, sabit kodlu olmamalı."""
    from config import FUTURES_SL_ATR_MULT, FUTURES_TP_ATR_MULT
    from engines.futures_trade_engine import sl_tp_hesapla
    fiyat, atr = 100.0, 1.0
    r = sl_tp_hesapla(fiyat, "LONG", atr, "RANGE")
    beklenen_sl = fiyat - atr * FUTURES_SL_ATR_MULT
    assert abs(r["sl"] - beklenen_sl) < 0.01, (
        f"SL {r['sl']}, config'e göre {beklenen_sl} olmalıydı "
        f"(FUTURES_SL_ATR_MULT={FUTURES_SL_ATR_MULT})")


def test_kontrol_rejim_volatilde_stop_genisliyor():
    """VOLATILE rejimde SL genişlemeli — canlı bunu yapıyor.

    Paper yapmazsa iki sistem oynak piyasada ayrışır.
    """
    from engines.futures_trade_engine import sl_tp_hesapla
    fiyat, atr = 100.0, 1.0
    normal = abs(fiyat - sl_tp_hesapla(fiyat, "LONG", atr, "RANGE")["sl"])
    oynak  = abs(fiyat - sl_tp_hesapla(fiyat, "LONG", atr, "VOLATILE")["sl"])
    assert oynak > normal, (
        f"VOLATILE rejimde stop genişlemiyor ({oynak:.3f} vs {normal:.3f})")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA PAPER ↔ CANLI SL/TP EŞİTLİĞİ — {len(testler)} test")
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
