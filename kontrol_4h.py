#!/usr/bin/env python3
"""4h ufkuna geçişten bu yana ilerleme — tek komutla sağlık kontrolü.

Kullanım: python kontrol_4h.py

Hüküm VERMEZ (o `karar_kurali.py`'nin işi, 100 işlem gerekiyor).
Bunun işi: bot 4h'de SAĞLIKLI mı, yoksa bir kapıda tıkalı mı?
"""
import sqlite3, json, os, sys, datetime as dt

# v58 K-35: Windows konsolu cp1254 ile açıldığında bu betik "→" / "✅"
# karakterlerinde UnicodeEncodeError ile ÇÖKÜYORDU — üstelik
# DEVAM_NOTLARI.md §1'in "önce bunu çalıştır" dediği betikte. Bot
# `python -X utf8 main.py bot` ile başlatıldığı için sorun uzun süre
# görünmedi; teşhis betiği elle çalıştırıldığında ortaya çıktı.
# errors="replace" ikinci savunma: kodlama yine de UTF-8 olamazsa
# çıktı bozulur ama betik ÇÖKMEZ (sağlık kontrolü erişilebilir kalır).
# Windows konsolu ayrıca UTF-8 kod sayfasına alınır: yalnızca akışı
# UTF-8 yapmak ÇÖKMEYİ önler ama konsol hâlâ cp1254 çözerse Türkçe
# karakterler mojibake görünür. "Çökmüyor" ile "okunabiliyor" farklı
# iddialardır (§5.2 — istenen ≠ yapılan olduğu her yerde sesli ol).
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
        pass          # yönlendirilmiş/eski akış — yedek yol yok, devam

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# §4.6: yol sabit kodlanmaz — config'ten okunur, yoksa izolasyon altında
# üretim verisine bakan bir teşhis betiği olurdu.
try:
    from config import DB_PATH
except ImportError:
    DB_PATH = "data/astra.db"

TEMEL = os.path.join(os.path.dirname(DB_PATH) or "data", "4h_baslangic.json")


def main():
    if not os.path.exists(TEMEL):
        print(f"⚠️  {TEMEL} yok — karşılaştırma yapılamaz")
        return
    with open(TEMEL) as f:
        t = json.load(f)
    bas = dt.datetime.fromisoformat(t["kayit_zamani_yerel"])
    gecen = (dt.datetime.now() - bas).total_seconds() / 3600

    c = sqlite3.connect(DB_PATH)
    kapali = c.execute("SELECT COUNT(*) FROM trades WHERE mod='PAPER' AND durum!='ACIK'").fetchone()[0]
    acik = c.execute("SELECT COUNT(*) FROM trades WHERE mod='PAPER' AND durum='ACIK'").fetchone()[0]

    print(f"\n{'='*60}")
    print(f"  4h UFKU — SAĞLIK KONTROLÜ ({gecen:.1f} saattir çalışıyor)")
    print(f"{'='*60}")
    print(f"  Kapanmış: {kapali}   Açık: {acik}   (başlangıç: "
          f"{t['paper_kapali']}/{t['paper_acik']})")
    if gecen > 0:
        # ── v58 (K-84): TEMPO YANLIŞ BÜYÜKLÜĞÜ ÖLÇÜYORDU ─────────────
        # Eski satır (kapali+acik), yani AÇILAN işlemleri sayıyordu ama
        # "100 işlem" hedefiyle kıyaslıyordu. Oysa `karar_kurali.py`
        # MIN_ISLEM=100'ü KAPANMIŞ işlemler üzerinden uyguluyor —
        # kapanmamış pozisyonun PnL'i yok, hükme giremez.
        #
        # ÖLÇÜLEN SAPMA (2026-09-13, 37.4 saat): 11 açılan / 1 kapanmış
        #     gösterilen : 7.1 işlem/gün →  13 gün
        #     GERÇEK     : 0.64 kapanış/gün → 156 gün
        # 12 KAT iyimser. Kullanıcı "10 pozisyon açık, ilerlemiyor"
        # derken tam olarak bunu fark etmişti.
        acilma  = (kapali + acik) * 24 / gecen
        kapanma = kapali * 24 / gecen
        print(f"  Açılma  : {acilma:.1f} işlem/gün "
              f"({kapali+acik} işlem / {gecen:.1f} saat)")
        if kapanma > 0:
            print(f"  KAPANMA : {kapanma:.2f} işlem/gün → "
                  f"100 KAPANMIŞ işlem ≈ {100/kapanma:.0f} gün  ← hüküm buna bakar")
        else:
            print(f"  KAPANMA : 0 — hiç işlem kapanmadı, süre tahmini YAPILAMAZ")
        if acik >= 1 and kapanma > 0 and acilma > kapanma * 3:
            print(f"  ⚠️  Açılma kapanmanın {acilma/kapanma:.0f} katı — slotlar "
                  f"doluyor, akış KAPANIŞ hızıyla sınırlı.")

    if kapali + acik == 0:
        print("\n  ⚠️  HİÇ İŞLEM YOK — 24 saatten fazla geçtiyse bir kapı tıkıyor.")
        print("      Kontrol: grep -E 'CHOP FILTER|R/R KAPISI|FİLTRE' logs/astra.log | tail -20")
        return

    print(f"\n  {'id':>3} {'sembol':<9}{'yön':<6}{'SL%':>6}{'TP%':>6}"
          f"{'pnl%':>8}  {'durum':<14}{'süre_saat':>10}")
    for r in c.execute("SELECT id,ts_ac,ts_kapat,sembol,yon,giris_fiyat,"
                       "stop_loss,take_profit,pnl_yuzde,durum FROM trades "
                       "WHERE mod='PAPER' ORDER BY id"):
        i, ta, tk, s, y, g, sl, tp, p, d = r
        sl_p = abs(sl - g) / g * 100 if sl and g else 0
        tp_p = abs(tp - g) / g * 100 if tp and g else 0
        sure = ((dt.datetime.fromisoformat(tk) - dt.datetime.fromisoformat(ta))
                .total_seconds() / 3600) if tk else \
               (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                - dt.datetime.fromisoformat(ta)).total_seconds() / 3600
        print(f"  {i:>3} {s:<9}{y:<6}{sl_p:>6.2f}{tp_p:>6.2f}"
              f"{(f'{p:+.2f}' if p is not None else '-'):>8}  {d[:12]:<14}{sure:>10.1f}")

    # SAĞLIK KONTROLLERİ — hüküm değil, artefakt avı
    print("\n  SAĞLIK:")
    kisa = c.execute("SELECT COUNT(*) FROM trades WHERE mod='PAPER' "
                     "AND durum!='ACIK' AND ts_kapat IS NOT NULL AND "
                     "(julianday(ts_kapat)-julianday(ts_ac))*86400 < 600").fetchone()[0]
    print(f"    {'✅' if kisa == 0 else '❌'} 10 dk'dan kısa işlem: {kisa} "
          f"(4h'de olmamalı — artefakt işareti)")
    dar = c.execute("SELECT COUNT(*) FROM trades WHERE mod='PAPER' AND "
                    "stop_loss IS NOT NULL AND "
                    "ABS(stop_loss-giris_fiyat)/giris_fiyat*100 < 1.0").fetchone()[0]
    print(f"    {'✅' if dar == 0 else '⚠️ '} SL < %1 olan işlem: {dar} "
          f"(4h'de %2-4 beklenir)")
    print(f"\n  Hüküm için: python karar_kurali.py  (100 işlem gerekiyor)\n")


if __name__ == "__main__":
    main()
