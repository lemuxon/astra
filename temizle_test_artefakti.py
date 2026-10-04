#!/usr/bin/env python3
# =========================================================
# ASTRA v57 — TEST ARTEFAKTI TEMİZLİĞİ (tek seferlik)
#
# NEDEN:
#   v56'ya kadar test paketi ÜRETİM durum dosyalarına yazıyordu. Biriken
#   sahte kayıtlar canlıya geçiş sayacını (CANLI_GECIS_PROTOKOLU.md Aşama 1,
#   "100 kapanmış paper işlem") şişiriyordu. 2026-08-20'de sayaç 33
#   gösteriyordu; GERÇEK paper işlem sayısı 0'dı.
#
# KANIT (bu betiğin sildiği verinin sahte olduğunun gerekçesi):
#   - trades: 67 satırın en uzun süresi 0.255 SANİYE, yalnızca 3 farklı
#     giriş fiyatı (63018.9 / 2000.6 / 0.50015) — gerçek işlem dakikalar sürer
#   - performance: 10 satırın tamamı 'RANDUSDT'/'TESTUSDT' (uydurma sembol)
#   - journal: 6 satır mod='LIVE', hepsi giriş 50000.0 / miktar 0.04 /
#     cikis_ts=NULL. Bot hiç canlı işlem yapmadı → tanım gereği sahte
#   - model_registry: 60 satır RANDUSDT/TESTUSDT; 70 gerçek satır KORUNUR
#   - ab_test.json: yalnızca sentetik 0.26/-0.44 döngüsü, b_pnl boş
#
# İZOLASYON:
#   Kirliliğin kaynağı v57'de kapatıldı (tests/izolasyon.py + muhafız
#   testleri: tests/test_izolasyon.py). Bu betik yalnızca GEÇMİŞ kirliliği
#   temizler; tekrarlanması gerekmez.
#
# ÖNCE YEDEK AL:
#   Betik kendi yedeğini alır (data/_yedek_v57_<zaman>/).
# =========================================================
import glob
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

SAHTE_SEMBOLLER = ("RANDUSDT", "TESTUSDT")
DURUM_DOSYALARI = ("data/astra.db", "data/journal.db",
                   "data/model_registry.db", "data/ab_test.json",
                   "data/position_state.json")


def yedekle() -> str:
    zaman = datetime.now().strftime("%Y%m%d_%H%M%S")
    dizin = f"data/_yedek_v57_{zaman}"
    os.makedirs(dizin, exist_ok=True)
    for f in DURUM_DOSYALARI:
        if os.path.exists(f):
            shutil.copy2(f, dizin)
    return dizin


def main():
    print("=" * 62)
    print("  ASTRA v57 — TEST ARTEFAKTI TEMİZLİĞİ")
    print("=" * 62)

    if not os.path.exists("data/astra.db"):
        print("  ✗ data/astra.db bulunamadı — proje kökünden çalıştırın.")
        sys.exit(1)

    dizin = yedekle()
    print(f"  Yedek: {dizin}\n")

    # ---------- 1) astra.db ----------
    c = sqlite3.connect("data/astra.db")
    t0 = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    p0 = c.execute("SELECT COUNT(*) FROM performance").fetchone()[0]
    c.execute("DELETE FROM trades")
    c.execute(
        f"DELETE FROM performance WHERE sembol IN ({','.join('?' * len(SAHTE_SEMBOLLER))})",
        SAHTE_SEMBOLLER)
    c.execute("DELETE FROM sqlite_sequence WHERE name IN ('trades','performance')")
    c.commit()
    t1 = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    p1 = c.execute("SELECT COUNT(*) FROM performance").fetchone()[0]
    c.execute("VACUUM")
    c.close()
    print(f"  astra.db  trades       : {t0:>4} -> {t1}")
    print(f"  astra.db  performance  : {p0:>4} -> {p1}")

    # ---------- 2) journal.db ----------
    j = sqlite3.connect("data/journal.db")
    j0 = j.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
    j.execute("DELETE FROM journal")
    j.commit()
    j1 = j.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
    j.execute("VACUUM")
    j.close()
    print(f"  journal.db journal     : {j0:>4} -> {j1}")

    # ---------- 3) model_registry.db (SEÇİCİ — gerçek kayıtlar korunur) ----------
    m = sqlite3.connect("data/model_registry.db")
    m0 = m.execute("SELECT COUNT(*) FROM model_versions").fetchone()[0]
    m.execute(
        f"DELETE FROM model_versions WHERE sembol IN ({','.join('?' * len(SAHTE_SEMBOLLER))})",
        SAHTE_SEMBOLLER)
    m.commit()
    m1 = m.execute("SELECT COUNT(*) FROM model_versions").fetchone()[0]
    kalan = m.execute("SELECT sembol,COUNT(*) FROM model_versions "
                      "GROUP BY sembol ORDER BY 2 DESC").fetchall()
    m.execute("VACUUM")
    m.close()
    print(f"  model_registry versions: {m0:>4} -> {m1}")
    print(f"       korunan gerçek kayıtlar: {kalan}")

    # ---------- 4) sahte model dosyaları ----------
    silinen = 0
    for sembol in SAHTE_SEMBOLLER:
        for f in glob.glob(f"saved_models/versions/*{sembol}*"):
            os.remove(f)
            silinen += 1
    print(f"  saved_models/versions  : {silinen} sahte .pkl silindi")

    # ---------- 5) ab_test.json ----------
    with open("data/ab_test.json", "w", encoding="utf-8") as fh:
        json.dump({"a_pnl": [], "b_pnl": [],
                   "ts": datetime.now(timezone.utc).isoformat()}, fh)
    print("  ab_test.json           : sıfırlandı (a_pnl/b_pnl boş)")

    print("=" * 62)
    print("  ✅ Temizlik bitti. Paper sayacı artık GERÇEK 0'dan başlıyor.")
    print(f"  Geri almak için: {dizin} içindekileri data/ üzerine kopyalayın.")
    print("=" * 62)


if __name__ == "__main__":
    main()
