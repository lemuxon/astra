# =========================================================
# ASTRA v58 — PARA DÖKÜMÜ ve KOMİSYON KAYDI (K-42)
# Çalıştırma: python tests/test_para_dokumu.py
#
# NE KORUYOR:
#   Komisyon kapanışta hesaplanıp PnL'den düşülüyordu ama `trades`
#   tablosunda KOLONU YOKTU — yani hiç saklanmıyordu. Sonuç: "ne kadar
#   komisyon ödedim" sorusunun geriye dönük cevabı yoktu.
#
#   Bu, maliyet optimizasyonunun ilk gereği: göremediğin şeyi
#   optimize edemezsin. Ayrıca 4h'de maliyet hedefin %3.1'i (§0.8) —
#   küçük ama ölçülmeden yönetilemez.
#
#   `brut_pnl = gerceklesen_pnl + odenen_komisyon` özdeşliği raporun
#   kendi iç tutarlılık kontrolü. Bu kod tabanında muhasebe kaçağı
#   DAHA ÖNCE oldu (v56: bakiye net, DB brüt tutuyordu ve ikisi
#   yavaşça ayrışıyordu) — bu yüzden özdeşlik teste bağlandı.
#
# §4.1: Muhafızların yanına KONTROL testleri var — "komisyonu hep 0 yaz"
#   ya da "dökümü hiç üretme" davranışları da muhafızları geçerdi.
# =========================================================
import sys, os, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

from config import DB_PATH
from data.database import tablolari_olustur, trade_kapat
from engines.paper_trading import PaperTrader, _para_blogu


def _temiz_db():
    tablolari_olustur()
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM trades")
        c.commit()


def _islem_ac(sembol="BTCUSDT", giris=100.0, miktar=1.0):
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "INSERT INTO trades (ts_ac,sembol,yon,giris_fiyat,miktar,durum,mod) "
            "VALUES ('2026-09-05T00:00:00',?,'LONG',?,?,'ACIK','PAPER')",
            (sembol, giris, miktar))
        c.commit()
        return cur.lastrowid


# ─────────────────────────────────────────────
# 1. KOMİSYON SAKLANIYOR MU
# ─────────────────────────────────────────────
def test_trades_tablosunda_komisyon_kolonu_var():
    """Migrasyon çalışmalı — kolon yoksa komisyon hiç yazılamaz."""
    tablolari_olustur()
    with sqlite3.connect(DB_PATH) as c:
        kol = {r[1] for r in c.execute("PRAGMA table_info(trades)")}
    assert "komisyon" in kol, (
        "trades.komisyon kolonu yok — ALTER TABLE migrasyonu çalışmamış. "
        "Komisyon PnL'den düşülür ama kaydedilmez, geriye dönük ölçülemez.")


def test_trade_kapat_komisyonu_yaziyor():
    """DAVRANIŞSAL: geçilen komisyon DB'ye ulaşmalı."""
    _temiz_db()
    tid = _islem_ac()
    trade_kapat(tid, 102.0, "TP", pnl=1.92, pnl_yuzde=1.92, komisyon=0.08)
    with sqlite3.connect(DB_PATH) as c:
        v = c.execute("SELECT komisyon FROM trades WHERE id=?", (tid,)).fetchone()[0]
    assert v is not None, "komisyon NULL kaldı — trade_kapat onu yazmıyor"
    assert abs(v - 0.08) < 1e-6, f"komisyon {v} yazıldı, 0.08 bekleniyordu"


def test_komisyon_gecilmezse_NULL_kalir():
    """Geçilmezse 0 DEĞİL NULL olmalı.

    0 yazmak "komisyon ödenmedi" anlamına gelir ve K-42 öncesi eski
    kayıtlarla ayırt edilemez hale gelir — rapor sessizce eksik toplar.
    """
    _temiz_db()
    tid = _islem_ac()
    trade_kapat(tid, 102.0, "TP", pnl=2.0, pnl_yuzde=2.0)
    with sqlite3.connect(DB_PATH) as c:
        v = c.execute("SELECT komisyon FROM trades WHERE id=?", (tid,)).fetchone()[0]
    assert v is None, f"komisyon {v!r} yazıldı — geçilmediğinde NULL kalmalı"


# ─────────────────────────────────────────────
# 2. DÖKÜMÜN TUTARLILIĞI
# ─────────────────────────────────────────────
def test_brut_net_komisyon_ozdesligi():
    """brut_pnl == gerceklesen_pnl + odenen_komisyon.

    Muhasebe kaçağı dedektörü. v56'da bakiye net / DB brüt tutuyordu ve
    ikisi yavaşça ayrışmıştı; bu özdeşlik o sınıfı yakalar.
    """
    _temiz_db()
    for pnl, kom in ((1.92, 0.08), (-3.10, 0.09), (0.50, 0.07)):
        tid = _islem_ac()
        trade_kapat(tid, 101.0, "TP", pnl=pnl, pnl_yuzde=pnl, komisyon=kom)
    d = PaperTrader().para_dokumu()
    assert abs(d["brut_pnl"] - (d["gerceklesen_pnl"] + d["odenen_komisyon"])) < 1e-6, (
        f"özdeşlik BOZUK: brüt={d['brut_pnl']} ≠ net={d['gerceklesen_pnl']} "
        f"+ komisyon={d['odenen_komisyon']}")
    assert abs(d["odenen_komisyon"] - 0.24) < 1e-6, (
        f"komisyon toplamı {d['odenen_komisyon']}, 0.24 bekleniyordu")
    assert d["kapanan_islem"] == 3


def test_eski_kayitlar_EKSIK_olarak_isaretlenir():
    """K-42 öncesi (komisyon NULL) kayıtlar sayılmalı ve UYARILMALI.

    Sessizce eksik toplamak, komisyonu olduğundan düşük gösterir —
    yani maliyeti olduğundan iyi gösterir. §5.2: istenen ≠ yapılan
    olduğu her yerde sesli ol.
    """
    _temiz_db()
    t1 = _islem_ac(); trade_kapat(t1, 101.0, "TP", pnl=1.0, pnl_yuzde=1.0)          # eski
    t2 = _islem_ac(); trade_kapat(t2, 101.0, "TP", pnl=1.0, pnl_yuzde=1.0, komisyon=0.05)
    d = PaperTrader().para_dokumu()
    assert d["kapanan_islem"] == 2
    assert d["komisyonu_bilinen"] == 1, (
        f"komisyonu_bilinen={d['komisyonu_bilinen']} — NULL kayıtlar "
        f"bilinen sayılmış olabilir")
    blok = _para_blogu(d)
    assert "kayıtlı değil" in blok, (
        "Rapor eksik komisyonu UYARMIYOR — toplam sessizce düşük görünür")


def test_acik_pozisyon_bagli_sermaye_olarak_sayilir():
    """Açık pozisyonun notional'ı 'bağlı sermaye' olmalı, nakit değil."""
    _temiz_db()
    _islem_ac(giris=100.0, miktar=2.0)        # 200 USDT bağlı, ACIK kalıyor
    d = PaperTrader().para_dokumu()
    assert abs(d["bagli_sermaye"] - 200.0) < 1e-6, (
        f"bagli_sermaye={d['bagli_sermaye']}, 200.0 bekleniyordu")
    assert d["acik_pozisyon"] == 1
    assert abs(d["toplam_varlik"] - (d["nakit"] + d["bagli_sermaye"])) < 1e-6


# ─────────────────────────────────────────────
# 3. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_dokum_gercekten_uretiliyor():
    """AŞIRI DÜZELTME KONTROLÜ: boş/hatalı sözlük dönmemeli.

    "Hiç döküm üretme" davranışı yukarıdaki özdeşlik testini de
    geçerdi (0 == 0 + 0).
    """
    _temiz_db()
    d = PaperTrader().para_dokumu()
    assert "hata" not in d, f"döküm hata döndü: {d.get('hata')}"
    for alan in ("baslangic", "nakit", "bagli_sermaye", "toplam_varlik",
                 "gerceklesen_pnl", "odenen_komisyon", "brut_pnl",
                 "kapanan_islem", "komisyonu_bilinen", "acik_pozisyon"):
        assert alan in d, f"döküm '{alan}' alanını içermiyor"
    assert d["baslangic"] > 0, "başlangıç bakiyesi 0 — döküm anlamsız"


def test_kontrol_komisyon_sifir_diye_gecistirilmiyor():
    """Gerçek komisyon yazıldığında döküm onu SIFIR göstermemeli.

    "Komisyonu hep 0 yaz" da özdeşlik testini geçerdi (net==brüt).
    """
    _temiz_db()
    tid = _islem_ac()
    trade_kapat(tid, 101.0, "TP", pnl=0.90, pnl_yuzde=0.9, komisyon=0.10)
    d = PaperTrader().para_dokumu()
    assert d["odenen_komisyon"] > 0, (
        "komisyon 0 raporlandı — döküm komisyonu okumuyor olabilir")
    assert d["komisyon_payi_pct"] > 0, "komisyon payı hesaplanmıyor"


def test_kontrol_telegram_blogu_rakamlari_iceriyor():
    """Blok gerçekten sayı basmalı — boş şablon dönmemeli."""
    _temiz_db()
    tid = _islem_ac()
    trade_kapat(tid, 101.0, "TP", pnl=0.90, pnl_yuzde=0.9, komisyon=0.10)
    blok = _para_blogu(PaperTrader().para_dokumu())
    for beklenen in ("Başlangıç", "Nakit", "Komisyon", "Net PnL"):
        assert beklenen in blok, f"blokta '{beklenen}' satırı yok"
    assert "0.1000" in blok or "0.10" in blok, (
        f"komisyon rakamı blokta görünmüyor:\n{blok}")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA PARA DÖKÜMÜ — {len(testler)} test")
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
