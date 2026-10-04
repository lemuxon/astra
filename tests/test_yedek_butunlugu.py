# =========================================================
# ASTRA — SIFIRLAMA YEDEĞİ WAL DAHİL OLMALI (v58, K-92)
# Çalıştırma: python tests/test_yedek_butunlugu.py
#
# `sifirla_k37.py` yedeği `shutil.copy2("data/astra.db", ...)` ile
# alıyordu. Veritabanı WAL modunda ve bot 7/24 açık bağlantı tuttuğu
# için checkpoint kendiliğinden olmuyor: son saatlerin işlemleri
# `astra.db-wal` dosyasında durur, ana `.db` dosyasında DEĞİLDİR.
#
# ÖLÇÜLDÜ (10. sıfırlamanın yedeği): dizin 15:02'de oluşturulmuş,
# içindeki astra.db 14:35 tarihli, en yeni işlem 12:43 — ve `-wal`
# dosyası yok. Sıfırlama anında var olan ~2sa20dk'lık işlem hiçbir
# yerde kalmadı. Aynı imza 13 yedeğin HEPSİNDE vardı.
#
# Yedek, sıfırlamanın TEK güvenlik ağıdır; dolu görünüp eksik olması
# §10'un tarif ettiği kör noktanın ta kendisidir.
# Ağ ve üretim verisi kullanılmaz — kendi geçici DB'sini kurar.
# =========================================================
import os
import shutil
import sqlite3
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et
izole_et()

import importlib.util

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sifirla_modulu():
    """`sifirla_k37.py`'yi main() çalıştırmadan yükle."""
    yol = os.path.join(KOK, "sifirla_k37.py")
    spec = importlib.util.spec_from_file_location("_sifirla_k37_test", yol)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wal_db_kur(dizin: str, n: int = 50) -> tuple:
    """Botu taklit et: WAL modu + AÇIK KALAN bağlantı (checkpoint olmaz)."""
    db = os.path.join(dizin, "astra.db")
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=wal")
    con.execute("CREATE TABLE trades(id INTEGER PRIMARY KEY, mod TEXT)")
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")      # ana dosyaya yaz
    for _ in range(n):                                   # bunlar WAL'de kalır
        con.execute("INSERT INTO trades(mod) VALUES('PAPER')")
    con.commit()
    return db, con          # ⚠️ bağlantı BİLEREK açık bırakılıyor


def _say(yol: str) -> int:
    c = sqlite3.connect(f"file:{yol}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    finally:
        c.close()


def test_yedek_wal_icindeki_islemleri_de_alir():
    """K-92'nin ta kendisi: açık bağlantı varken yedek EKSİKSİZ olmalı."""
    sf = _sifirla_modulu()
    with tempfile.TemporaryDirectory() as td:
        kaynak_dizin = os.path.join(td, "data"); os.makedirs(kaynak_dizin)
        hedef = os.path.join(td, "yedek"); os.makedirs(hedef)
        db, con = _wal_db_kur(kaynak_dizin)
        try:
            sf._yedekle(db, hedef)
            alinan = _say(os.path.join(hedef, "astra.db"))
        finally:
            con.close()
        assert alinan == 50, (
            f"yedekte {alinan}/50 işlem var — WAL kapsanmamış (K-92 geri gelmiş)")


def test_eski_yontem_gercekten_kaybediyordu():
    """KONTROL: hatanın VAR olduğunu kanıtla.

    Bu test olmadan üstteki "50 == 50" iddiası, `shutil.copy2`'nin de
    yeterli olduğu bir dünyada da geçerdi — yani neyi koruduğunu
    kanıtlamazdı. §4.1'in kontrol testi kuralı.
    """
    with tempfile.TemporaryDirectory() as td:
        kaynak_dizin = os.path.join(td, "data"); os.makedirs(kaynak_dizin)
        hedef = os.path.join(td, "yedek"); os.makedirs(hedef)
        db, con = _wal_db_kur(kaynak_dizin)
        try:
            shutil.copy2(db, hedef)          # ESKİ yöntem
            alinan = _say(os.path.join(hedef, "astra.db"))
        finally:
            con.close()
        assert alinan < 50, (
            "shutil.copy2 WAL'i kaçırmıyor görünüyor — bu testin kurulumu "
            "botun durumunu artık temsil etmiyor, gözden geçir")


def test_db_disi_dosyalar_hala_kopyalaniyor():
    """KONTROL: .json gibi dosyalar da yedeklenmeye devam etmeli.

    `_yedekle` yalnızca .db'yi özel ele alır; JSON'ları düşürseydi
    position_state.json / ab_test.json sessizce yedeksiz kalırdı.
    """
    sf = _sifirla_modulu()
    with tempfile.TemporaryDirectory() as td:
        kaynak = os.path.join(td, "ab_test.json")
        with open(kaynak, "w", encoding="utf-8") as f:
            f.write('{"deneme": 1}')
        hedef = os.path.join(td, "yedek"); os.makedirs(hedef)
        sf._yedekle(kaynak, hedef)
        kopya = os.path.join(hedef, "ab_test.json")
        assert os.path.exists(kopya)
        with open(kopya, encoding="utf-8") as f:
            assert f.read() == '{"deneme": 1}'


def test_sifirla_betigi_yedekleme_fonksiyonunu_kullaniyor():
    """Fonksiyon var ama ÇAĞRILMIYORSA hiçbir işe yaramaz.

    (Metin araması değil davranış istenirdi; ancak burada test edilen
    şey "betik hangi yolu seçiyor" — kaynak tek kanıt. Bu yüzden
    `shutil.copy2`'nin yedek döngüsünde ARTIK OLMADIĞI da doğrulanıyor.)
    """
    kaynak = open(os.path.join(KOK, "sifirla_k37.py"), encoding="utf-8").read()
    assert "_yedekle(f, yedek)" in kaynak, "yedek döngüsü _yedekle kullanmıyor"
    assert "shutil.copy2(f, yedek)" not in kaynak, "eski kopyalama geri gelmiş"


if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'=' * 58}")
    print(f"  ASTRA YEDEK BÜTÜNLÜĞÜ (K-92) — {len(testler)} test")
    print(f"{'=' * 58}")
    basari, hata = 0, 0
    for test in testler:
        try:
            test()
            print(f"  [GEÇTİ]  {test.__name__}")
            basari += 1
        except AssertionError as exc:
            print(f"  [HATA]   {test.__name__}\n           → {str(exc)[:160]}")
            hata += 1
        except Exception as exc:
            print(f"  [ÇÖKTÜ]  {test.__name__}: {type(exc).__name__}: {str(exc)[:100]}")
            hata += 1
    print(f"{'=' * 58}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'=' * 58}\n")
    sys.exit(0 if hata == 0 else 1)
