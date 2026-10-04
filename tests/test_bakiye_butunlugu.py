# =========================================================
# ASTRA v58 — PAPER BAKİYE BÜTÜNLÜĞÜ (K-59)
# Çalıştırma: python tests/test_bakiye_butunlugu.py
#
# NE KORUYOR — kullanıcı şüphesi (2026-09-06):
#   "Çektiği para ile eksilen para, veya kazanılan parayla yansıyan
#    para aynı olmamasından şüpheliyim."
#
#   Uçtan uca ölçüldü. Temel muhasebe SAĞLAM çıktı (artımlı bakiye ile
#   DB'den türetilen bakiye farkı: 0.000000). AMA üç gerçek kusur vardı:
#
#   1. `max(bakiye, baslangic * 0.05)` — SAHTE PARA ÜRETİYORDU.
#      %99 zarar senaryosunda gerçek bakiye 100 USDT olmalıyken bu satır
#      **500** döndürüyordu → 400 USDT yoktan var oluyordu.
#      Yalnızca YENİDEN BAŞLATMADA devreye giriyordu, yani çalışan
#      bakiye ile yeniden başlatılan bakiye ayrışıyordu.
#      ⚠️ 100 işlemlik protokolün görmek istediği şeyi (kill switch,
#      zarar dönemi — §3 ENGEL 2) tam olarak GİZLİYORDU.
#
#   2. `round(bakiye, 2)` — her yeniden başlatmada 0.0027$ sapma.
#      Bot bugün ~12 kez yeniden başlatıldı.
#
#   3. `max(geri_gelen, 0)` — zarar pozisyon maliyetini aşarsa fark
#      sessizce yutuluyordu (1x kaldıraçta oluşmaz, ama kaçak).
#
# §4.1: Muhafızın yanına KONTROL testleri var.
# =========================================================
import sys, os, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

from config import DB_PATH, PAPER_KOMISYON
from data.database import tablolari_olustur, trade_ac, trade_kapat, toplam_pnl
from engines.paper_trading import PaperTrader


def _temiz():
    tablolari_olustur()
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM trades"); c.commit()


# ─────────────────────────────────────────────
# 1. SAHTE PARA ÜRETİLMİYOR
# ─────────────────────────────────────────────
def test_buyuk_zarar_gizlenmiyor():
    """%99 zarardan sonra bakiye GERÇEK değeri göstermeli.

    Eskiden `max(bakiye, baslangic*0.05)` 500 döndürüyordu (gerçek: 100).
    """
    _temiz()
    bas = PaperTrader().baslangic
    tid = trade_ac(sembol="BIGLOSS", yon="LONG", giris_fiyat=100.0,
                   miktar=1.0, stop_loss=1.0, take_profit=200.0, mod="PAPER")
    trade_kapat(tid, 1.0, "STOP", pnl=-(bas * 0.99), pnl_yuzde=-99.0,
                komisyon=0.0)
    bakiye = PaperTrader().bakiye
    beklenen = bas - bas * 0.99
    assert abs(bakiye - beklenen) < 0.01, (
        f"Bakiye {bakiye:.2f}, gerçek {beklenen:.2f} olmalıydı — "
        f"{bakiye - beklenen:+.2f} USDT SAHTE PARA (taban koruması "
        f"felaket zararı gizliyor)")


def test_bakiye_tukendiginde_sifir():
    """Zarar başlangıcı aşarsa bakiye 0 olmalı, uydurma bir değer değil."""
    _temiz()
    bas = PaperTrader().baslangic
    tid = trade_ac(sembol="WIPE", yon="LONG", giris_fiyat=100.0, miktar=1.0,
                   stop_loss=1.0, take_profit=200.0, mod="PAPER")
    trade_kapat(tid, 1.0, "STOP", pnl=-(bas * 1.5), pnl_yuzde=-150.0,
                komisyon=0.0)
    assert PaperTrader().bakiye == 0.0, (
        f"Bakiye {PaperTrader().bakiye} — hesap patladığında 0 dönmeli")


# ─────────────────────────────────────────────
# 2. ARTIMLI == YENİDEN HESAPLANAN
# ─────────────────────────────────────────────
def test_yeniden_baslatma_bakiyeyi_kaydirmıyor():
    """Artımlı bakiye ile DB'den türetilen bakiye AYNI olmalı.

    `round(...,2)` her restart'ta sapma üretiyordu.
    """
    _temiz()
    pt = PaperTrader()
    bas = pt.bakiye
    import random
    random.seed(11)
    bekl_pnl = 0.0
    for _ in range(25):
        f = random.uniform(50, 80000)
        m = round(random.uniform(0.0001, 2.0), 6)
        n = f * m
        t = trade_ac(sembol="TESTX", yon="LONG", giris_fiyat=f, miktar=m,
                     stop_loss=f * 0.98, take_profit=f * 1.03, mod="PAPER")
        pt.bakiye -= n
        c = f * random.uniform(0.97, 1.04)
        kom = (n + c * m) * PAPER_KOMISYON
        p = round((c - f) * m - kom, 4)
        trade_kapat(t, c, "TP", pnl=p, pnl_yuzde=p / n * 100, komisyon=kom)
        pt.bakiye += n + p
        bekl_pnl += p
    yeniden = PaperTrader().bakiye
    assert abs(pt.bakiye - yeniden) < 1e-6, (
        f"artımlı {pt.bakiye:.6f} ≠ yeniden {yeniden:.6f} "
        f"(fark {pt.bakiye - yeniden:+.6f}) — restart'ta bakiye kayıyor")
    assert abs(yeniden - (bas + bekl_pnl)) < 1e-6, (
        f"bakiye {yeniden:.6f} ≠ başlangıç+PnL {bas + bekl_pnl:.6f}")


def test_acik_pozisyon_bakiyeden_dusuluyor():
    """Açık pozisyonun notional'ı nakitten düşülmüş olmalı."""
    _temiz()
    bas = PaperTrader().baslangic
    trade_ac(sembol="ETHUSDT", yon="LONG", giris_fiyat=2510.673,
             miktar=0.03983, stop_loss=2470.0, take_profit=2564.0,
             mod="PAPER")
    beklenen = bas - 2510.673 * 0.03983
    assert abs(PaperTrader().bakiye - beklenen) < 1e-6


def test_db_pnl_ile_bakiye_tutarli():
    """bakiye == başlangıç + DB toplam PnL − açık notional."""
    _temiz()
    bas = PaperTrader().baslangic
    t = trade_ac(sembol="A", yon="LONG", giris_fiyat=100.0, miktar=1.0,
                 stop_loss=98.0, take_profit=103.0, mod="PAPER")
    trade_kapat(t, 102.0, "TP", pnl=1.92, pnl_yuzde=1.92, komisyon=0.08)
    trade_ac(sembol="B", yon="LONG", giris_fiyat=50.0, miktar=2.0,
             stop_loss=49.0, take_profit=52.0, mod="PAPER")
    bakiye = PaperTrader().bakiye
    beklenen = bas + float(toplam_pnl("PAPER")) - 100.0
    assert abs(bakiye - beklenen) < 1e-6, (
        f"bakiye {bakiye} ≠ {beklenen} — muhasebe kaçağı")


# ─────────────────────────────────────────────
# 3. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_normal_bakiye_bozulmuyor():
    """AŞIRI DÜZELTME KONTROLÜ: kârlı durumda bakiye doğru kalmalı.

    "Her zaman 0 dön" davranışı yukarıdaki zarar testlerini geçerdi.
    """
    _temiz()
    bas = PaperTrader().baslangic
    t = trade_ac(sembol="WIN", yon="LONG", giris_fiyat=100.0, miktar=1.0,
                 stop_loss=98.0, take_profit=110.0, mod="PAPER")
    trade_kapat(t, 110.0, "TP", pnl=9.9, pnl_yuzde=9.9, komisyon=0.1)
    bakiye = PaperTrader().bakiye
    assert abs(bakiye - (bas + 9.9)) < 1e-6, (
        f"Kârlı işlemden sonra bakiye {bakiye}, {bas + 9.9} olmalıydı")
    assert bakiye > bas, "Kâr bakiyeye yansımadı"


def test_kontrol_taban_kaynakta_yok():
    """Kaynak: sahte para üreten taban GERİ GELMEMELİ."""
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import ast
    with open(os.path.join(kok, "engines", "paper_trading.py"),
              encoding="utf-8") as fh:
        agac = ast.parse(fh.read())
    fn = next((d for d in ast.walk(agac) if isinstance(d, ast.FunctionDef)
               and d.name == "_bakiye_hesapla"), None)
    assert fn is not None, "_bakiye_hesapla bulunamadı"
    kod = ast.unparse(fn)
    assert "max(bakiye" not in kod.replace(" ", ""), (
        "Bakiye tabanı geri gelmiş — büyük zarar gizlenir, sahte para üretilir")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA BAKİYE BÜTÜNLÜĞÜ — {len(testler)} test")
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
