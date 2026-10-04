#!/usr/bin/env python3
# =========================================================
# ASTRA v57 — PAPER SAYACINI SIFIRLA (tek seferlik)
#
# NEDEN (2026-08-24):
#   Biriken 3 kapanmış paper işlemi, ARTIK GEÇERSİZ bir sistemin ürünü:
#
#   1. #1 XRPUSDT ve #2 BNBUSDT, ESKİ SL dolum modeliyle kapandı
#      (pozisyon stop SEVİYESİNDEN değil, bar kapanışından kapatılıyordu).
#      BNBUSDT −%3.27 yazdı; yeni modelle ≈−%1.09 olurdu — 3 KAT fark.
#   2. #2 BNBUSDT, botun 2 gün 8 saat ölü kaldığı pencerede açık kaldı
#      (v57 K-3). SL hiç kontrol edilmedi.
#   3. Bu işlemler v57'nin K-3/K-5/K-7 düzeltmelerinden ÖNCEki koddan geldi.
#
#   100 işlemlik veri seti canlıya geçiş kararını belirliyor
#   (CANLI_GECIS_PROTOKOLU.md Aşama 1). %3 bilinen kirliliği taşımak yerine
#   stabil koddan temiz başlamak doğru — 3 işlem ucuz, yanlış karar değil.
#
# BUNDAN SONRA sayaç yalnızca şu koşullarda birikir:
#   - SL/TP seviyeden dolum (K-5 düzeltmesi)
#   - Ana thread ölmüyor (K-3 düzeltmesi)
#   - Watchdog uykuyu donma sanmıyor (K-7 düzeltmesi)
#   - Testler üretim verisine yazmıyor (K-1/K-6 düzeltmeleri)
#
# NOT: Bot çalışırken çalıştırılabilir ama AÇIK pozisyon varsa uyarır —
# açık pozisyonu silmek bakiye tutarsızlığı yaratır.
# =========================================================
import os
import shutil
import sqlite3
import sys
from datetime import datetime

DURUM_DOSYALARI = ("data/astra.db", "data/journal.db",
                   "data/ab_test.json", "data/position_state.json")


def yedekle() -> str:
    zaman = datetime.now().strftime("%Y%m%d_%H%M%S")
    dizin = f"data/_yedek_sayac_{zaman}"
    os.makedirs(dizin, exist_ok=True)
    for f in DURUM_DOSYALARI:
        if os.path.exists(f):
            shutil.copy2(f, dizin)
    return dizin


def main():
    print("=" * 62)
    print("  ASTRA v57 — PAPER SAYACINI SIFIRLA")
    print("=" * 62)

    if not os.path.exists("data/astra.db"):
        print("  ✗ data/astra.db yok — proje kökünden çalıştırın.")
        sys.exit(1)

    c = sqlite3.connect("data/astra.db")
    acik = c.execute(
        "SELECT COUNT(*) FROM trades WHERE mod='PAPER' AND durum='ACIK'"
    ).fetchone()[0]
    kapali = c.execute(
        "SELECT COUNT(*) FROM trades WHERE mod='PAPER' AND durum!='ACIK'"
    ).fetchone()[0]
    print(f"  Mevcut: {kapali} kapanmış, {acik} açık")

    if acik:
        print(f"\n  ⚠️  {acik} AÇIK pozisyon var. Bunları silmek bakiye")
        print("      tutarsızlığı yaratır (PaperTrader bakiyeyi DB'den türetir).")
        print("      Botu durdurup pozisyon kapanınca tekrar çalıştırın,")
        print("      ya da açık pozisyonu manuel kapatın.")
        c.close()
        sys.exit(2)

    dizin = yedekle()
    print(f"  Yedek : {dizin}")

    c.execute("DELETE FROM trades WHERE mod='PAPER'")
    c.execute("DELETE FROM sqlite_sequence WHERE name='trades'")
    c.commit()
    kalan = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    c.execute("VACUUM")
    c.close()
    print(f"  astra.db trades : {kapali + acik} -> {kalan}")

    if os.path.exists("data/journal.db"):
        j = sqlite3.connect("data/journal.db")
        j0 = j.execute("SELECT COUNT(*) FROM journal WHERE mod='PAPER'").fetchone()[0]
        j.execute("DELETE FROM journal WHERE mod='PAPER'")
        j.commit()
        j1 = j.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
        j.execute("VACUUM")
        j.close()
        print(f"  journal PAPER   : {j0} -> 0  (toplam kalan {j1})")

    print("=" * 62)
    print("  ✅ Sayaç 0/100. Sayım stabil koddan (v57) itibaren geçerli.")
    print(f"  Geri alma: {dizin} içindekileri data/ üzerine kopyalayın.")
    print("=" * 62)


if __name__ == "__main__":
    main()
