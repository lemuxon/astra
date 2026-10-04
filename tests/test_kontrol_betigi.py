# =========================================================
# ASTRA v58 — SAĞLIK BETİĞİ ÇALIŞABİLİRLİĞİ (K-35)
# Çalıştırma: python tests/test_kontrol_betigi.py
#
# NE KORUYOR:
#   `kontrol_4h.py`, DEVAM_NOTLARI.md §1'in "yeni sohbette İLK bunu
#   çalıştır" dediği teşhis betiği. Windows konsolu cp1254 ile
#   açıldığında "→" karakterinde UnicodeEncodeError ile ÇÖKÜYORDU:
#
#       print(f"  Tempo   : {...:.1f} işlem/gün → ...")
#       UnicodeEncodeError: 'charmap' codec can't encode '→'
#
#   Bot `python -X utf8 main.py bot` ile başlatıldığı için üretimde
#   görünmedi; betik ELLE çalıştırıldığında çıktı (2026-09-05).
#
#   Neden önemli: sağlık kontrolü erişilemezse artefakt avı (K-31 tipi
#   bayat giriş fiyatı) yapılamaz. O vakayı bulan bu betikti.
#
# §4.1: Muhafızın yanına KONTROL testleri var — hiçbir şey yazdırmayan
#   ya da hiç Türkçe karakter içermeyen bir betik de "çökmedi" testini
#   geçerdi.
# =========================================================
import sys, os, json, sqlite3, tempfile, subprocess, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BETIK = os.path.join(KOK, "kontrol_4h.py")


def _sahne():
    """İzole bir data/ dizini kur: astra.db + 4h_baslangic.json.

    Üretim verisine HİÇ dokunulmaz (§4.6) — betiğe kendi DB'sini
    gösteriyoruz, yani test bot çalışsa da çalışmasa da deterministik.
    """
    d = tempfile.mkdtemp(prefix="astra_kontrol_")
    veri = os.path.join(d, "data")
    os.makedirs(veri)
    db = os.path.join(veri, "astra.db")

    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE trades (
        id INTEGER PRIMARY KEY, mod TEXT, sembol TEXT, yon TEXT,
        giris_fiyat REAL, stop_loss REAL, take_profit REAL,
        pnl_yuzde REAL, durum TEXT, ts_ac TEXT, ts_kapat TEXT)""")
    # Bir kapanmış + bir açık işlem — tablo ve süre yollarının ikisi de
    # çalışsın (açıkta ts_kapat NULL, farklı kod dalı).
    c.execute("INSERT INTO trades VALUES (1,'PAPER','BTCUSDT','LONG',"
              "100.0,98.0,102.7,+2.58,'TP',"
              "'2026-09-04 08:00:00','2026-09-04 20:00:00')")
    c.execute("INSERT INTO trades VALUES (2,'PAPER','ETHUSDT','LONG',"
              "50.0,48.6,51.9,NULL,'ACIK','2026-09-05 04:00:00',NULL)")
    c.commit()
    c.close()

    with open(os.path.join(veri, "4h_baslangic.json"), "w",
              encoding="utf-8") as f:
        json.dump({"kayit_zamani_yerel": "2026-09-04T01:29:00",
                   "paper_kapali": 0, "paper_acik": 0}, f)
    return d, db


def _calistir(kodlama):
    """Betiği verilen konsol kodlamasıyla ayrı süreçte çalıştır.

    Ayrı süreç ŞART: `sys.stdout.reconfigure` süreç geneli bir durum,
    test sürecinde yapılırsa ölçtüğümüz şeyi bozardık.
    """
    d, db = _sahne()
    try:
        ortam = dict(os.environ)
        ortam["PYTHONIOENCODING"] = kodlama
        ortam["DB_PATH"] = db
        ortam["LIVE_TRADING"] = "false"
        ortam.setdefault("BOT_TOKEN", "")
        # İzolasyon değişkenleri sızmasın — betik kendi DB_PATH'ini alsın.
        ortam.pop("ASTRA_TEST_DIZINI", None)
        s = subprocess.run([sys.executable, BETIK], cwd=KOK, env=ortam,
                           capture_output=True, timeout=180)
        # Çıktı HER ZAMAN utf-8 çözülür: düzeltmenin iddiası tam da
        # "konsol kodlaması ne olursa olsun UTF-8 yaz". `kodlama` ile
        # çözmek düzeltilmiş betiği mojibake sanardı (testin ilk hatası).
        return s.returncode, s.stdout.decode("utf-8", errors="replace"), \
            s.stderr.decode("utf-8", errors="replace")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ─────────────────────────────────────────────
# 1. MUHAFIZ
# ─────────────────────────────────────────────
def test_cp1254_konsolunda_cokmuyor():
    """Windows varsayılan kodlamasında betik ÇÖKMEMELİ.

    Düzeltmeden önce: UnicodeEncodeError, exit 1, tablo hiç basılmıyor.
    """
    kod, cikti, hata = _calistir("cp1254")
    assert "UnicodeEncodeError" not in hata, (
        f"cp1254 konsolunda UnicodeEncodeError — sağlık betiği "
        f"çalıştırılamıyor:\n{hata[-400:]}")
    assert kod == 0, f"Betik {kod} ile çıktı. stderr:\n{hata[-400:]}"


def test_cp1254te_tam_rapor_basiliyor():
    """Çökmemek yetmez — raporun TAMAMI çıkmalı.

    Çökme, çıktının ORTASINDA oluyordu (başlık ve işlem sayısı basılmış,
    tempo satırından itibaren yok). Sadece exit koduna bakan bir test,
    betik yarıda kesilse de yeşil kalabilirdi; son satırı arıyoruz.
    """
    kod, cikti, hata = _calistir("cp1254")
    # v58 (K-84): "Tempo" satırı ikiye ayrıldı — "Açılma" (açılan işlem
    # hızı) ve "KAPANMA" (hükmün baktığı kapanış hızı). Çapalar raporun
    # BAŞINDAN SONUNA yayılmalı ki yarıda kesilme yakalansın.
    for beklenen in ("SAĞLIK KONTROLÜ", "Açılma", "KAPANMA", "SAĞLIK:",
                     "karar_kurali.py"):
        assert beklenen in cikti, (
            f"cp1254 çıktısında '{beklenen}' yok — rapor yarıda kesilmiş:\n"
            f"{cikti[-400:]}")


# ─────────────────────────────────────────────
# 2. KONTROL TESTLERİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_cikti_ascii_disi_karakter_iceriyor():
    """AŞIRI DÜZELTME KONTROLÜ: emoji/ok işaretleri SİLİNMEMELİ.

    Çökmeyi "tüm Türkçe karakterleri ve ✅/→ işaretlerini at" diyerek de
    çözebilirdik; yukarıdaki iki test buna da yeşil verirdi. Ama o
    zaman raporun okunabilirliği (§1'deki ✅/❌ tablosu) giderdi.
    """
    kod, cikti, hata = _calistir("utf-8")
    ascii_disi = [ch for ch in cikti if ord(ch) > 127]
    assert ascii_disi, (
        "Çıktıda hiç ASCII dışı karakter yok — betik sadeleştirilerek "
        "'düzeltilmiş' olabilir; ✅/❌ sağlık işaretleri kayboldu")
    assert "→" in cikti or "≈" in cikti, (
        "Tempo satırındaki ok/yaklaşık işareti yok — çökme, karakteri "
        "silerek değil kodlamayı düzelterek çözülmeliydi")


def test_kontrol_uretim_verisine_dokunulmuyor():
    """Bu testin KENDİSİ üretim DB'sini okumamalı (§4.6).

    Betiğe kendi DB'mizi veriyoruz; sahne verisi çıktıya yansımalı.
    Yansımıyorsa test aslında üretim verisini ölçüyordur ve bot
    çalışırken rastgele kırmızıya döner.
    """
    kod, cikti, hata = _calistir("utf-8")
    assert "BTCUSDT" in cikti and "ETHUSDT" in cikti, (
        f"Sahne işlemleri çıktıda yok — betik başka bir DB okuyor:\n"
        f"{cikti[-400:]}")
    # Sahnede tam 2 işlem var; üretimde başka sayı olurdu.
    assert "Kapanmış: 1" in cikti and "Açık: 1" in cikti, (
        f"Sahne sayıları uyuşmuyor — DB_PATH yönlendirmesi etkisiz:\n"
        f"{cikti[:400]}")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA SAĞLIK BETİĞİ — {len(testler)} test")
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
