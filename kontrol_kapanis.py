#!/usr/bin/env python3
"""Kapanış türü · fonlama · kaldıraç bütünlüğü — K-85/K-86/K-87/K-88 takibi.

Kullanım: python kontrol_kapanis.py

`kontrol_4h.py` KAPANIŞ HIZINI ölçer (ölçüm 1). Bu betik geri kalan ikisini:
  2. ERKEN KESME BEDELİ — ZAMAN_STOP ile kapananların ortalaması SL/TP'ye
     göre nasıl? (§0.14'te erken kesme zararın %22'siydi; K-85 aynı riski
     taşıyor — bu betik onu ÖLÇÜLEBİLİR tutuyor.)
  3. FONLAMA — K-87'ye kadar hiç modellenmiyordu, 24 saat tutulan pozisyon
     3 fonlama dönemi öder.

Ayrıca kaldıraç muhasebesinin BÜTÜNLÜĞÜNÜ denetler: K-86 öncesi paper
`kaldirac=1` sabit koduyla 1x spot gibi davranıyordu ve bunu hiçbir şey
fark etmemişti. marjin == notional/kaldıraç özdeşliği bozulursa burada
görünür.

Hüküm VERMEZ (o `karar_kurali.py`'nin işi, 100 kapanmış işlem gerekiyor).
"""
import sqlite3, os, sys

# K-35: Windows konsolu cp1254 açıldığında "✅"/"→" ÇÖKERTİYOR.
# kontrol_4h.py ile aynı savunma — teşhis betiği erişilemez olmamalı.
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass          # konsol yok (yönlendirilmiş çıktı) — zararsız

for _akis in (sys.stdout, sys.stderr):
    try:
        _akis.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# §4.6: yol sabit kodlanmaz — yoksa izolasyon altında da üretim verisine bakar.
try:
    from config import DB_PATH
except ImportError:
    DB_PATH = "data/astra.db"

# `islem_kaldiraci()` son satırı: max(FUTURES_LEVERAGE_MIN, ...) — yani
# bunun ALTI yapısal olarak imkânsızdır. Sabit yazılmaz, config'ten okunur:
# kullanıcı tabanı değiştirirse muhafız sessizce yanlış eşiğe bakmasın.
try:
    from config import FUTURES_LEVERAGE_MIN as KALDIRAC_TABAN
except ImportError:
    KALDIRAC_TABAN = 2

BAKIM_MARJIN = 0.004      # risk_manager.py:337 ve tasfiye_fiyati() ile AYNI


def _olcum2(c):
    """Kapanış türüne göre sonuç — erken kesme bedeli görünür olsun."""
    print("\n  -- 2. KAPANIŞ TÜRÜ (erken kesme bedeli) ------------------")
    satirlar = list(c.execute(
        "SELECT durum, COUNT(*), AVG(pnl_yuzde), SUM(pnl), "
        "       AVG((julianday(ts_kapat)-julianday(ts_ac))*24) "
        "FROM trades WHERE mod='PAPER' AND durum!='ACIK' "
        "GROUP BY durum ORDER BY COUNT(*) DESC"))
    if not satirlar:
        print("     henüz kapanmış işlem YOK — bu ölçüm yapılamaz.")
        print("     (zaman stop 24 saat; ilk ZAMAN_STOP kapanışı o süreden önce olamaz)")
        return
    print(f"     {'durum':<16}{'n':>4}{'ort pnl%':>10}{'top pnl':>10}{'ort saat':>10}")
    for d, n, ort, top, saat in satirlar:
        print(f"     {str(d)[:14]:<16}{n:>4}{(ort or 0):>10.3f}"
              f"{(top or 0):>10.3f}{(saat or 0):>10.1f}")

    # ASIL SORU: zaman stop, kazanmaya giden pozisyonu kesiyor mu?
    zs = [(n, ort) for d, n, ort, _, _ in satirlar if "ZAMAN" in str(d).upper()]
    dg = [(n, ort) for d, n, ort, _, _ in satirlar if "ZAMAN" not in str(d).upper()]
    if zs and dg:
        zs_n = sum(n for n, _ in zs)
        zs_ort = sum(n * (o or 0) for n, o in zs) / zs_n
        dg_n = sum(n for n, _ in dg)
        dg_ort = sum(n * (o or 0) for n, o in dg) / dg_n
        print(f"\n     ZAMAN_STOP  n={zs_n:<4} ortalama {zs_ort:+.3f}%")
        print(f"     SL/TP       n={dg_n:<4} ortalama {dg_ort:+.3f}%")
        print(f"     fark        {zs_ort - dg_ort:+.3f} puan  "
              f"<- negatifse zaman stop zarara çalışıyor OLABİLİR (n küçükse hüküm YOK)")
    elif zs:
        print("\n     !! yalnızca ZAMAN_STOP kapanışı var — karşılaştırma tabanı yok")
    else:
        print("\n     henüz ZAMAN_STOP ile kapanan işlem yok")


def _olcum3(c):
    """Fonlama — K-87 öncesi SIFIR sayılıyordu."""
    print("\n  -- 3. FONLAMA + KOMİSYON ---------------------------------")
    n, fon, kom, pnl = c.execute(
        "SELECT COUNT(*), COALESCE(SUM(funding_maliyet),0), "
        "COALESCE(SUM(komisyon),0), COALESCE(SUM(pnl),0) "
        "FROM trades WHERE mod='PAPER' AND durum!='ACIK'").fetchone()
    print(f"     kapanmış {n} · net PnL {pnl:+.4f} · "
          f"komisyon {kom:.4f} · fonlama {fon:+.4f} USDT")
    if n == 0:
        print("     (fonlama kapanışta yazılır — kapanış yoksa 0 BEKLENEN değerdir,")
        print("      'fonlama çalışmıyor' anlamına GELMEZ)")
    elif fon == 0:
        print("     !! n>0 ama fonlama tam 0 — K-87 üretimde çalışmıyor OLABİLİR")
    else:
        print(f"     fonlamanın net PnL'e oranı: %{abs(100*fon/pnl) if pnl else 0:.1f}")

    # Açık pozisyonlardan ileriye dönük projeksiyon (24 saat = 3 dönem)
    acik = list(c.execute(
        "SELECT sembol, yon, giris_fiyat*miktar, funding_rate, marjin "
        "FROM trades WHERE mod='PAPER' AND durum='ACIK'"))
    if acik:
        eksik = [s for s, _, _, fr, _ in acik if fr is None]
        toplam = sum((notional or 0) * (fr or 0) * 3 *
                     (1 if str(y).upper() in ("LONG", "BUY") else -1)
                     for _, y, notional, fr, _ in acik)
        marjin = sum((m or 0) for *_, m in acik)
        print(f"\n     açık {len(acik)} pozisyon · 24 saatlik fonlama projeksiyonu "
              f"{toplam:+.4f} USDT (marjinin %{100*toplam/marjin if marjin else 0:+.3f}'i)")
        if eksik:
            print(f"     !! funding_rate KAYIP: {', '.join(eksik)} — giriş anında yazılmamış")


def _butunluk(c):
    """Kaldıraç muhasebesi — K-86 regresyonu sessiz kalmasın."""
    print("\n  -- KALDIRAÇ BÜTÜNLÜĞÜ (K-86/K-88) ------------------------")
    satirlar = list(c.execute(
        "SELECT id, sembol, yon, giris_fiyat, miktar, kaldirac, marjin, tasfiye_fiyat "
        "FROM trades WHERE mod='PAPER' AND durum='ACIK'"))
    if not satirlar:
        print("     açık pozisyon yok")
        return
    bozuk, dusuk_kaldirac, tasfiye_yok = [], [], []
    tot_n = tot_m = 0.0
    for i, s, y, gf, mik, kal, mar, tas in satirlar:
        notional = (gf or 0) * (mik or 0)
        tot_n += notional
        tot_m += (mar or 0)
        if not kal:
            bozuk.append(f"#{i} {s}: kaldirac YOK")
            continue
        # ⚠️ MUTASYON TESTİNİN AÇIĞA ÇIKARDIĞI BOŞLUK:
        # marjin == notional/kaldıraç özdeşliği kaldirac=1'de KENDİLİĞİNDEN
        # sağlanır (notional/1 == notional). Yani "kaldıraç sessizce 1'e
        # düştü" — K-86'nın ta kendisi — özdeşlik kontrolünden GÖRÜNMEDEN
        # geçer. Tabanın altını AYRICA aramak gerekiyor; ve tek bir
        # pozisyon bile yeterli sinyaldir (hepsinin birden 1x olmasını
        # beklemek kısmi gerilemeyi kaçırırdı).
        if kal < KALDIRAC_TABAN:
            dusuk_kaldirac.append(f"#{i} {s}: {kal}x")
        beklenen = notional / kal
        if mar is None or abs(beklenen - mar) > max(0.01, beklenen * 0.001):
            bozuk.append(f"#{i} {s}: marjin {mar} != notional/kaldıraç {beklenen:.2f}")
        # tasfiye: LONG giriş×(1−(1/k−bakım)), SHORT giriş×(1+…). 1x'te tasfiye YOK.
        if kal > 1:
            if tas is None:
                tasfiye_yok.append(f"#{i} {s}")
            else:
                oran = 1 / kal - BAKIM_MARJIN
                bek = gf * (1 - oran) if str(y).upper() in ("LONG", "BUY") else gf * (1 + oran)
                if abs(bek - tas) > max(1e-9, abs(bek) * 0.001):
                    bozuk.append(f"#{i} {s}: tasfiye {tas:.6f} != beklenen {bek:.6f}")

    print(f"     toplam marjin {tot_m:.2f} · notional {tot_n:.2f} · "
          f"ortalama kaldıraç {tot_n/tot_m if tot_m else 0:.2f}x")
    if bozuk:
        print("     [X] BÜTÜNLÜK BOZUK:")
        for b in bozuk:
            print(f"        {b}")
    else:
        print("     [OK] marjin == notional/kaldıraç ve tasfiye formülü TUTUYOR")
    if dusuk_kaldirac:
        print(f"     [X] KALDIRAÇ TABANIN ALTINDA (<{KALDIRAC_TABAN}x) — "
              f"islem_kaldiraci() bunu ÜRETEMEZ, K-86 gerilemesi işareti:")
        for d in dusuk_kaldirac:
            print(f"        {d}")
    if tasfiye_yok:
        print(f"     !! tasfiye_fiyat yazılmamış: {', '.join(tasfiye_yok)}")


def main():
    if not os.path.exists(DB_PATH):
        print(f"!! {DB_PATH} yok — ölçüm yapılamaz")
        return
    c = sqlite3.connect(DB_PATH)
    print("\n" + "=" * 60)
    print("  KAPANIŞ · FONLAMA · KALDIRAÇ — K-85/86/87/88 TAKİBİ")
    print("=" * 60)
    _olcum2(c)
    _olcum3(c)
    _butunluk(c)
    print("\n  Kapanış hızı için: python kontrol_4h.py")
    print("  Hüküm için       : python karar_kurali.py  (100 KAPANMIŞ işlem)\n")
    c.close()


if __name__ == "__main__":
    main()
