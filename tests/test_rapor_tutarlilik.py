# =========================================================
# ASTRA v58 — RAPOR TUTARLILIK TESTLERİ (K-32 / K-33)
# Çalıştırma: python tests/test_rapor_tutarlilik.py
#
# NE KORUYOR — kullanıcı iki kaynağın ÇELİŞTİĞİNİ fark etti:
#
#   K-32: ÇİFT SAYIM
#     Telegram : 2 işlem, %50   ← DB'den okur, DOĞRU
#     Panel    : 3 işlem, %66.7 ← ŞİŞMİŞ
#     Sebep: `paper_trading._kapat_ve_bakiye_guncelle` hem doğrudan
#     `pozisyon_kapandi_bildir()` çağırıyor HEM DE event bus'a
#     POSITION_CLOSED yayınlıyordu; `main.py::_on_position_closed`
#     dinleyicisi de aynı fonksiyonu çağırıyordu → her paper kapanışı
#     panele İKİ KEZ gidiyordu.
#     Ölçülen panel çıktısı: BNBUSDT TP · BNBUSDT TP · BTCUSDT STOP
#
#   K-33: BAKİYE ETİKETİ
#     Telegram : 5k     ← futures TESTNET hesabı (4999.60)
#     Panel    : 10000  ← gerçek paper bakiyesi (9819.16)
#     İkisi de doğruydu ama FARKLI ŞEYİ ölçüyordu; rapor bunu
#     söylemiyordu. Paper modda bot futures'ta hiç işlem yapmıyor,
#     yani o rakam alakasızdı.
#
# ⚠️ Bu sınıf ("iki yol aynı şeyi yapıyor" / "etiket neyi ölçtüğünü
#   söylemiyor") bu kod tabanında TEKRAR EDİYOR. §5.2: istenen ≠
#   yapılan olduğu her yerde sesli ol.
#
# §4.1: Muhafızların yanına kontrol testleri.
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


def _kod(dosya):
    yol = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       dosya)
    with open(yol, encoding="utf-8") as fh:
        return "\n".join(l for l in fh.read().splitlines()
                         if not l.strip().startswith("#"))


def _sifirla():
    from api import dashboard as db
    with db._lock:
        db._kapanan_islemler.clear()
        db._son_kapanis_imza.clear()
        ist = db._state["bot_istatistik"]
        ist["toplam_islem"] = 0; ist["kazanan"] = 0
        ist["kaybeden"] = 0;     ist["win_rate"] = 0


# ─────────────────────────────────────────────
# 1. MUHAFIZ (K-32) — aynı kapanış iki kez sayılmamalı
# ─────────────────────────────────────────────
def test_ayni_kapanis_iki_kez_sayilmaz():
    """Gerçek vakanın kopyası: BNBUSDT TP iki kez bildirildi."""
    from api.dashboard import pozisyon_kapandi_bildir, _state
    _sifirla()
    for _ in range(2):          # iki yoldan aynı kapanış
        pozisyon_kapandi_bildir(sembol="BNBUSDT", yon="LONG", giris=714.71,
                                cikis=733.12, pnl_usdt=2.5755, pnl_pct=2.58,
                                sebep="TP", miktar=0.14)
    ist = _state["bot_istatistik"]
    assert ist["toplam_islem"] == 1, (
        f"Aynı kapanış {ist['toplam_islem']} kez sayıldı — panel "
        f"istatistiği şişer (gerçek vaka: 2 işlem yerine 3)")
    assert len(_state["kapanan_islemler"]) == 1, \
        "Aynı işlem listede iki kez görünüyor"


def test_paper_trading_dogrudan_bildirim_yapmiyor():
    """Kök neden: doğrudan çağrı kaldırılmış olmalı.

    Tekrar koruması savunma katmanı; asıl düzeltme tek yol bırakmaktır.
    """
    kod = _kod(os.path.join("engines", "paper_trading.py"))
    assert "pozisyon_kapandi_bildir(" not in kod, (
        "paper_trading hâlâ dashboard'a DOĞRUDAN bildiriyor — event "
        "bus dinleyicisiyle birlikte çift sayım olur (K-32)")
    assert "POSITION_CLOSED" in kod, \
        "paper_trading event bus'a yayınlamıyor — panel hiç haber almaz"


def test_db_yuklemesi_sayaclari_sifirliyor():
    """`_db_gecmisini_yukle` ikinci kez çalışırsa istatistik katlanmamalı."""
    kod = _kod(os.path.join("api", "dashboard.py"))
    i = kod.find("def _db_gecmisini_yukle")
    assert i > 0, "fonksiyon bulunamadı — test hedefi kaymış"
    govde = kod[i:i + 2500]
    assert 'ist["toplam_islem"] = 0' in govde, (
        "DB yüklemesi sayaçları sıfırlamıyor — ikinci çağrıda tüm "
        "istatistik ikiye katlanır")


# ─────────────────────────────────────────────
# 2. KONTROL — farklı kapanışlar AYRI sayılmalı
# ─────────────────────────────────────────────
def test_farkli_kapanislar_ayri_sayilir():
    """Kontrol testi (§4.1). "Hiçbirini sayma" da muhafızı geçerdi."""
    from api.dashboard import pozisyon_kapandi_bildir, _state
    _sifirla()
    pozisyon_kapandi_bildir(sembol="BNBUSDT", yon="LONG", giris=714.0,
                            cikis=733.0, pnl_usdt=2.57, pnl_pct=2.58,
                            sebep="TP")
    pozisyon_kapandi_bildir(sembol="BTCUSDT", yon="LONG", giris=80681.0,
                            cikis=79053.0, pnl_usdt=-2.09, pnl_pct=-2.10,
                            sebep="STOP")
    ist = _state["bot_istatistik"]
    assert ist["toplam_islem"] == 2, \
        f"İki farklı kapanış {ist['toplam_islem']} sayıldı"
    assert ist["kazanan"] == 1 and ist["kaybeden"] == 1, \
        f"kazanan/kaybeden yanlış: {ist}"
    assert ist["win_rate"] == 50.0, f"win_rate {ist['win_rate']}, 50.0 olmalı"


def test_ayni_sembol_farkli_kapanis_ayri_sayilir():
    """Kontrol: aynı sembolde İKİ GERÇEK işlem birleştirilmemeli."""
    from api.dashboard import pozisyon_kapandi_bildir, _state
    _sifirla()
    pozisyon_kapandi_bildir(sembol="BTCUSDT", yon="LONG", giris=80000.0,
                            cikis=81000.0, pnl_usdt=1.25, pnl_pct=1.25,
                            sebep="TP")
    pozisyon_kapandi_bildir(sembol="BTCUSDT", yon="LONG", giris=81000.0,
                            cikis=79500.0, pnl_usdt=-1.85, pnl_pct=-1.85,
                            sebep="STOP")
    assert _state["bot_istatistik"]["toplam_islem"] == 2, (
        "Aynı sembolde iki FARKLI kapanış tek sayıldı — tekrar koruması "
        "fazla geniş")


# ─────────────────────────────────────────────
# 3. MUHAFIZ (K-33) — bakiye etiketi moda uymalı
# ─────────────────────────────────────────────
def test_paper_modda_futures_bakiyesi_gosterilmiyor():
    """Paper modda rapor PAPER bakiyesini göstermeli.

    Bot paper modda futures'ta HİÇ işlem yapmıyor; testnet hesabının
    bakiyesini "Bakiye" diye göstermek yanıltıcıydı (5k vs 10000).
    """
    kod = _kod("main.py")
    i = kod.find("def futures_pozisyon_raporu")
    assert i > 0, "futures_pozisyon_raporu bulunamadı — test hedefi kaymış"
    govde = kod[i:i + 1200]
    assert "LIVE_TRADING" in govde, (
        "Rapor moda bakmıyor — paper modda futures bakiyesi gösterir")
    assert "paper_trader.bakiye" in govde, \
        "Paper modda paper bakiyesi kullanılmıyor"
    assert "bakiye_etiket" in govde, (
        "Bakiye etiketi yok — kullanıcı hangi bakiyeye baktığını bilemez")


def test_etiket_her_iki_modda_da_dolu():
    """Kontrol: etiket her iki dalda da atanmalı (NameError olmasın)."""
    kod = _kod("main.py")
    i = kod.find("def futures_pozisyon_raporu")
    govde = kod[i:i + 1200]
    assert govde.count("bakiye_etiket =") >= 2, (
        "Etiket yalnızca bir dalda atanmış — diğer modda NameError")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA RAPOR TUTARLILIK — {len(testler)} test")
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
