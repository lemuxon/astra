# =========================================================
# ASTRA v58 — VERİ TUTARLILIĞI (K-51)
# Çalıştırma: python tests/test_veri_tutarliligi.py
#
# NE KORUYOR:
#   §0.12 (K-32/K-33): panel ile Telegram AYNI büyüklüğü FARKLI
#   gösteriyordu (3 işlem / %66.7 vs 2 işlem / %50) ve İKİSİ DE yeşil
#   testlerden geçiyordu. Hata ancak kullanıcı iki ekrana bakıp
#   sayıları karşılaştırınca ortaya çıktı.
#
#   §0.12'nin dersi: "Aynı büyüklüğü raporlayan her iki kaynak,
#   düzenli olarak karşılaştırılmalı." Bu dosya o karşılaştırmayı
#   OTOMATİKLEŞTİRİR — artık insana bağlı değil.
#
#   Ayrıca MUHASEBE ÖZDEŞLİKLERİ kilitleniyor:
#     brüt PnL      = net PnL + ödenen komisyon
#     toplam varlık = nakit + bağlı sermaye
#     nakit         = başlangıç − bağlı + net
#   v56'da tam bu sınıftan hata olmuştu (bakiye net, DB brüt tutuyordu,
#   ikisi yavaşça ayrışıyordu).
#
# ⚠️ İZOLE ORTAMDA çalışır: kendi sahne verisini kurar. Üretim
#   verisine bakmaz — aksi halde bot çalışırken rastgele kırmızıya
#   döner ve §4.6'nın uyardığı "görmezden gelinen muhafız" olurdu.
# =========================================================
import sys, os, sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

from config import DB_PATH
from data.database import (tablolari_olustur, trade_kapat, win_rate_hesapla,
                           toplam_pnl, acik_tradeler)
from engines.paper_trading import PaperTrader

TOL = 0.01



def _borsayi_izole_et():
    """Testler GERÇEK borsayı sorgulamamalı — v58 (K-101).

    `acik_pozisyonlar_birlesik()` önce canlı borsayı sorguluyor; burada
    hiç taklit yoktu, yani testler sessizce "hesap BOŞ" varsayımına
    dayanıyordu. 2026-09-15 00:17'de ilk canlı emir açılınca 6 test
    birden kırmızıya döndü — kod değil TESTLER kusurluydu.
    Borsa hesabı da üretim durumudur; test sonucu ona bağlı olmamalı.
    """
    import main
    asil = main.acik_futures_pozisyonlar
    main.acik_futures_pozisyonlar = lambda *a, **kw: []
    return lambda: setattr(main, "acik_futures_pozisyonlar", asil)


def _sahne(kapanan=None, acik=None):
    """Bilinen bir durum kur: kapanan=[(pnl,komisyon)], acik=[(fiyat,miktar)]."""
    tablolari_olustur()
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM trades")
        c.commit()
    for pnl, kom in (kapanan or []):
        with sqlite3.connect(DB_PATH) as c:
            cur = c.execute(
                "INSERT INTO trades (ts_ac,sembol,yon,giris_fiyat,miktar,"
                "durum,mod) VALUES ('2026-09-06T00:00:00','BTCUSDT','LONG',"
                "100.0,1.0,'ACIK','PAPER')")
            c.commit(); tid = cur.lastrowid
        trade_kapat(tid, 101.0, "TP", pnl=pnl, pnl_yuzde=pnl, komisyon=kom)
    for fiyat, miktar in (acik or []):
        with sqlite3.connect(DB_PATH) as c:
            c.execute(
                "INSERT INTO trades (ts_ac,sembol,yon,giris_fiyat,miktar,"
                "durum,mod) VALUES ('2026-09-06T00:00:00','ETHUSDT','LONG',"
                "?,?,'ACIK','PAPER')", (fiyat, miktar))
            c.commit()
    return PaperTrader()


def _sql(q):
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute(q).fetchone()
    return r[0] if r else None


# ─────────────────────────────────────────────
# 1. KAYNAKLAR ARASI EŞLEŞME
# ─────────────────────────────────────────────
def test_kapanan_islem_sayisi_tum_kaynaklarda_ayni():
    pt = _sahne(kapanan=[(1.0, 0.05), (-2.0, 0.06), (0.5, 0.04)])
    para = pt.para_dokumu()
    kaynaklar = {
        "para_dokumu": para["kapanan_islem"],
        "win_rate_hesapla": win_rate_hesapla("PAPER").get("toplam") or 0,
        "SQL COUNT": _sql("SELECT COUNT(*) FROM trades WHERE mod='PAPER' "
                          "AND durum!='ACIK'"),
    }
    assert len(set(kaynaklar.values())) == 1, (
        f"Kapanan işlem sayısı kaynaklara göre FARKLI: {kaynaklar} — "
        f"K-32 sınıfı hata (panel çift sayıyordu)")
    assert kaynaklar["para_dokumu"] == 3


def test_acik_pozisyon_sayisi_tum_kaynaklarda_ayni():
    pt = _sahne(acik=[(100.0, 2.0), (50.0, 1.0)])
    para = pt.para_dokumu()
    kaynaklar = {
        "para_dokumu": para["acik_pozisyon"],
        "durum_raporu": pt.durum_raporu()["acik_pozisyon"],
        "acik_tradeler": len(acik_tradeler("PAPER")),
        "SQL COUNT": _sql("SELECT COUNT(*) FROM trades WHERE mod='PAPER' "
                          "AND durum='ACIK'"),
    }
    assert len(set(kaynaklar.values())) == 1, (
        f"Açık pozisyon sayısı kaynaklara göre FARKLI: {kaynaklar}")
    assert kaynaklar["para_dokumu"] == 2


def test_toplam_pnl_tum_kaynaklarda_ayni():
    pt = _sahne(kapanan=[(1.5, 0.05), (-2.25, 0.06)])
    para = pt.para_dokumu()
    kaynaklar = {
        "toplam_pnl()": round(float(toplam_pnl("PAPER")), 4),
        "para_dokumu": round(para["gerceklesen_pnl"], 4),
        "durum_raporu": round(float(pt.durum_raporu()["toplam_pnl"]), 4),
        "SQL SUM": round(float(_sql("SELECT COALESCE(SUM(pnl),0) FROM trades "
                                    "WHERE mod='PAPER' AND durum!='ACIK'")), 4),
    }
    yayilim = max(kaynaklar.values()) - min(kaynaklar.values())
    assert yayilim <= TOL, (
        f"Toplam PnL kaynaklara göre FARKLI (yayılım {yayilim}): {kaynaklar} — "
        f"v56'da bakiye net / DB brüt tutuyordu ve yavaşça ayrışıyordu")


# ─────────────────────────────────────────────
# 2. MUHASEBE ÖZDEŞLİKLERİ
# ─────────────────────────────────────────────
def test_ozdeslik_brut_esittir_net_arti_komisyon():
    pt = _sahne(kapanan=[(1.0, 0.07), (-3.0, 0.09), (0.25, 0.05)])
    p = pt.para_dokumu()
    assert abs(p["brut_pnl"] - (p["gerceklesen_pnl"] + p["odenen_komisyon"])) <= 1e-6, (
        f"brüt({p['brut_pnl']}) ≠ net({p['gerceklesen_pnl']}) + "
        f"komisyon({p['odenen_komisyon']}) — muhasebe kaçağı")
    assert abs(p["odenen_komisyon"] - 0.21) <= 1e-6


def test_ozdeslik_toplam_varlik():
    pt = _sahne(acik=[(100.0, 2.0)])
    p = pt.para_dokumu()
    assert abs(p["toplam_varlik"] - (p["nakit"] + p["bagli_sermaye"])) <= 1e-6, (
        f"toplam varlık ({p['toplam_varlik']}) ≠ nakit ({p['nakit']}) + "
        f"bağlı ({p['bagli_sermaye']})")


def test_ozdeslik_bagli_sermaye_notional():
    pt = _sahne(acik=[(100.0, 2.0), (50.0, 3.0)])       # 200 + 150 = 350
    p = pt.para_dokumu()
    sql = float(_sql("SELECT COALESCE(SUM(giris_fiyat*miktar),0) FROM trades "
                     "WHERE mod='PAPER' AND durum='ACIK'"))
    assert abs(p["bagli_sermaye"] - sql) <= TOL, (
        f"bağlı sermaye ({p['bagli_sermaye']}) ≠ SQL notional ({sql})")
    assert abs(p["bagli_sermaye"] - 350.0) <= TOL


def test_ozdeslik_nakit_turetimi():
    """nakit = başlangıç − bağlı sermaye + gerçekleşen PnL."""
    pt = _sahne(kapanan=[(5.0, 0.10)], acik=[(100.0, 1.0)])
    p = pt.para_dokumu()
    bekl = p["baslangic"] - p["bagli_sermaye"] + p["gerceklesen_pnl"]
    assert abs(p["nakit"] - bekl) <= 0.05, (
        f"nakit ({p['nakit']}) ≠ başlangıç({p['baslangic']}) − "
        f"bağlı({p['bagli_sermaye']}) + net({p['gerceklesen_pnl']}) "
        f"= {bekl} — bakiye sızıntısı")


# ─────────────────────────────────────────────
# 3. TELEGRAM RAPORLARI da KARŞILAŞTIRMA SETİNDE (K-58)
# ─────────────────────────────────────────────
# ⚠️ NEDEN EKLENDİ: K-56'da `/fpoz` "açık pozisyon yok" derken panel
# 2 pozisyon gösteriyordu. Bu dosyanın ÖNCEKİ hâli bunu YAKALAYAMAZDI:
# yalnızca paper kaynaklarını (panel, DB, para_dokumu) karşılaştırıyordu
# ve hepsi doğruydu. `/fpoz` FARKLI bir kaynaktan (futures) okuduğu için
# karşılaştırma kümesinin DIŞINDAYDI.
#
# Ders: "aynı büyüklüğü raporlayan HER kaynak" ifadesindeki *her*,
# kullanıcının GÖRDÜĞÜ her yüzeyi kapsamalı — panel + Telegram.

def test_fpoz_raporu_DB_ile_ayni_pozisyon_sayisi():
    """`/fpoz`'un saydığı pozisyon, DB'dekiyle AYNI olmalı.

    K-56: rapor koşulsuz futures'tan okuyordu; paper modda hep boş
    geliyordu ve "AÇIK POZİSYON YOK" diyordu.
    """
    pt = _sahne(acik=[(100.0, 2.0), (50.0, 1.0)])
    import main
    _geri = _borsayi_izole_et()
    try:
        pozlar, kaynak = main.acik_pozisyonlar_birlesik()
    finally:
        _geri()
    db_sayi = _sql("SELECT COUNT(*) FROM trades WHERE mod='PAPER' "
                   "AND durum='ACIK'")
    assert len(pozlar) == db_sayi, (
        f"/fpoz kaynağı {len(pozlar)} pozisyon görüyor, DB'de {db_sayi} "
        f"var (kaynak={kaynak}) — K-56 sınıfı: rapor başka kaynaktan okuyor")
    assert len(pozlar) == pt.para_dokumu()["acik_pozisyon"], (
        "/fpoz ile para_dokumu farklı sayıyor")


def test_fpoz_bagli_sermaye_ile_tutarli():
    """`/fpoz` pozisyonlarının notional'ı, para dökümündeki bağlı
    sermayeye eşit olmalı — iki yüzey aynı parayı anlatıyor."""
    pt = _sahne(acik=[(100.0, 2.0), (50.0, 3.0)])       # 200 + 150
    import main
    _geri = _borsayi_izole_et()
    try:
        pozlar, _ = main.acik_pozisyonlar_birlesik()
    finally:
        _geri()
    notional = sum((p.get("giris") or 0) * (p.get("miktar") or 0)
                   for p in pozlar)
    assert abs(notional - pt.para_dokumu()["bagli_sermaye"]) <= TOL, (
        f"/fpoz notional'ı {notional}, para_dokumu bağlı sermayesi "
        f"{pt.para_dokumu()['bagli_sermaye']} — aynı parayı farklı "
        f"gösteriyorlar")


def test_paper_raporu_ile_para_dokumu_ayni_bakiye():
    """`/paper` raporundaki bakiye ile para dökümü uyuşmalı."""
    pt = _sahne(kapanan=[(1.5, 0.05)], acik=[(100.0, 1.0)])
    d = pt.durum_raporu()
    p = pt.para_dokumu()
    assert abs(d["bakiye"] - p["nakit"]) <= TOL, (
        f"/paper bakiye={d['bakiye']} ≠ para_dokumu nakit={p['nakit']}")
    assert d["acik_pozisyon"] == p["acik_pozisyon"]


# ─────────────────────────────────────────────
# 4. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_gercek_celiskiyi_YAKALAR():
    """AŞIRI DÜZELTME KONTROLÜ: test gerçekten çelişki bulabiliyor mu?

    Bilerek DB'ye doğrudan bir işlem ekleyip para_dokumu'nun onu
    görmesini bekliyoruz. Görmezse (önbellek vs.) testler yanlış
    güvence verirdi.
    """
    pt = _sahne(kapanan=[(1.0, 0.05)])
    once = pt.para_dokumu()["kapanan_islem"]
    with sqlite3.connect(DB_PATH) as c:
        c.execute("INSERT INTO trades (ts_ac,ts_kapat,sembol,yon,giris_fiyat,"
                  "miktar,durum,mod,pnl,komisyon) VALUES "
                  "('2026-09-06T01:00:00','2026-09-06T02:00:00','XRPUSDT',"
                  "'LONG',1.0,1.0,'TP','PAPER',0.5,0.02)")
        c.commit()
    sonra = PaperTrader().para_dokumu()["kapanan_islem"]
    assert sonra == once + 1, (
        f"DB'ye eklenen işlem para_dokumu'na yansımadı ({once} → {sonra}) — "
        f"rapor bayat veri okuyor olabilir, tutarlılık testleri anlamsız")


def test_kontrol_eksik_komisyon_ozdesligi_bozmaz():
    """K-42 öncesi (komisyon NULL) kayıtlarda özdeşlik hâlâ tutmalı.

    NULL komisyon 0 sayılır; brüt = net + 0 olur. Yanlış olan bu değil,
    EKSİK olması — ve rapor onu ayrıca uyarıyor (test_para_dokumu).
    """
    pt = _sahne(kapanan=[(2.0, None), (1.0, 0.05)])
    p = pt.para_dokumu()
    assert abs(p["brut_pnl"] - (p["gerceklesen_pnl"] + p["odenen_komisyon"])) <= 1e-6
    assert p["komisyonu_bilinen"] == 1 and p["kapanan_islem"] == 2


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA VERİ TUTARLILIĞI — {len(testler)} test")
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
