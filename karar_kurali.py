#!/usr/bin/env python3
# =========================================================
# ASTRA — CANLIYA GEÇİŞ KARAR KURALI
#
# Kullanım:  python karar_kurali.py
#
# NEDEN VAR:
#   Karar kuralı, VERİ GELMEDEN yazıldı (2026-08-26, n=7 iken).
#   Sebep: eşikleri veriye baktıktan sonra belirlemek, insanın kendini
#   kandırmasının en yaygın yoludur. Sayılar iyi göründüğünde eşik
#   düşürülür, kötü göründüğünde "biraz daha bekleyelim" denir.
#
#   Bu betik objektif bir hüküm verir. Hükmü beğenmediğiniz için eşikleri
#   değiştirirseniz, protokolün tamamı anlamını yitirir.
#
# TASARIM NOTLARI — protokoldeki eşikler NEDEN değiştirildi:
#
#   1) WIN RATE TEK BAŞINA ÖLÇÜT DEĞİL.
#      CANLI_GECIS_PROTOKOLU.md "%42 altı = KIRMIZI" diyor. Ama bu sistem
#      ~4.5:1 risk/ödül ile çalışıyor (kazanç ~%1.40, kayıp ~%0.31).
#      Başabaş win rate = 0.31/(1.40+0.31) = **%18**.
#      Yani %30 win rate'li, fazlasıyla kârlı bir sistem reddedilirdi.
#      → Ana ölçüt BEKLENTİ (expectancy), win rate yalnızca bilgi.
#
#   2) İSTATİSTİKSEL ANLAMLILIK ŞART.
#      "Beklenti pozitif" yetmez; gürültüden ayırt edilebilmeli.
#      t = beklenti / standart_hata > 2  (≈ %95 güven)
#      100 işlemde bu, beklentinin sıfırdan gerçekten farklı olduğunu
#      söyleyebileceğimiz eşiktir.
#
#   3) TABAN BEKLENTİ = %0.10/işlem.
#      Sadece "sıfırdan büyük" yetmez: testnet'te ölçülen round-trip
#      maliyet %0.089, model %0.08 kullanıyor — işlem başına %0.009
#      modelleme hatası var. %0.10 tabanı buna ~10x pay bırakır.
#      Daha ince bir edge, canlıda maliyet farkıyla silinir.
#
#   4) ARD ARDA KAYIP EŞİĞİ YENİDEN HESAPLANDI.
#      %57 kayıp oranında 100 işlemde beklenen en uzun seri:
#        log(100×0.43)/log(1/0.57) ≈ 6.7
#      Protokolün "6'dan az = yeşil" kuralı NORMAL davranışı sarıya
#      düşürürdü. Kırmızı eşiği beklentinin belirgin üstüne alındı (>12).
#
#   5) VERİ GEÇERLİLİĞİ KAPILARI (bu projeye özgü).
#      v57'de sayacın test artefaktıyla dolduğu, botun 2 gün ölü kaldığı
#      ve SL dolum modelinin yanlış olduğu bulundu. Veri temiz değilse
#      metrikler anlamsızdır — bu yüzden önce veri doğrulanır.
# =========================================================
import sqlite3
import statistics
import sys
from datetime import datetime

DB = "data/astra.db"

# ── EŞİKLER (veriye bakmadan belirlendi — değiştirmeyin) ──
MIN_ISLEM            = 100      # protokol Aşama 1
MIN_BEKLENTI_PCT     = 0.10     # işlem başına, maliyet modellemesi payıyla
MIN_T_ISTATISTIGI    = 2.0      # ≈ %95 güven, beklenti > 0
MAX_DRAWDOWN_PCT     = 15.0     # kill switch MaxDD ile hizalı
MAX_ARDARDA_KAYIP    = 12       # beklenen ~7; 12 belirgin sapma
SENTETIK_FIYATLAR    = {63018.9, 2000.6, 0.50015}   # test artefaktı imzası
MIN_SURE_SANIYE      = 60       # gerçek işlem dakikalar sürer


def _renk(ok, uyari=False):
    return "🟡 SARI " if uyari else ("✅ GEÇTİ" if ok else "❌ KALDI")


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    işlemler = [dict(r) for r in c.execute(
        "SELECT * FROM trades WHERE mod='PAPER' AND durum!='ACIK' ORDER BY id")]

    print("=" * 68)
    print("  ASTRA — CANLIYA GEÇİŞ KARAR KURALI")
    print("=" * 68)
    print(f"  Kapanmış paper işlem: {len(işlemler)}")

    kritik_hata = []
    uyari       = []

    # ══ BÖLÜM 1: VERİ GEÇERLİLİĞİ ══════════════════════════
    print("\n── 1. VERİ GEÇERLİLİĞİ (metrikler bundan sonra anlamlı) ──")

    sentetik = [t for t in işlemler if t["giris_fiyat"] in SENTETIK_FIYATLAR]
    ok = not sentetik
    print(f"  {_renk(ok)}  test artefaktı yok  ({len(sentetik)} şüpheli)")
    if not ok:
        kritik_hata.append(f"{len(sentetik)} test artefaktı işlem — sayaç güvenilmez")

    kisa = []
    for t in işlemler:
        if t["ts_ac"] and t["ts_kapat"]:
            sn = (datetime.fromisoformat(t["ts_kapat"])
                  - datetime.fromisoformat(t["ts_ac"])).total_seconds()
            if sn < MIN_SURE_SANIYE:
                kisa.append(sn)
    ok = not kisa
    print(f"  {_renk(ok)}  işlem süreleri gerçekçi  ({len(kisa)} adet <{MIN_SURE_SANIYE}s)")
    if not ok:
        kritik_hata.append(f"{len(kisa)} işlem {MIN_SURE_SANIYE}s'den kısa — artefakt olabilir")

    ok = len(işlemler) >= MIN_ISLEM
    print(f"  {_renk(ok)}  yeterli örneklem  ({len(işlemler)}/{MIN_ISLEM})")
    if not ok:
        kritik_hata.append(f"Sadece {len(işlemler)} işlem — {MIN_ISLEM} gerekli")

    if not işlemler:
        print("\n  Veri yok — değerlendirme yapılamıyor.")
        return 1

    # ══ BÖLÜM 2: ANA ÖLÇÜT — BEKLENTİ ══════════════════════
    print("\n── 2. ANA ÖLÇÜT: BEKLENTİ (win rate DEĞİL) ──")

    getiriler = [t["pnl_yuzde"] for t in işlemler if t["pnl_yuzde"] is not None]
    beklenti  = statistics.mean(getiriler)
    sapma     = statistics.stdev(getiriler) if len(getiriler) > 1 else 0.0
    se        = sapma / (len(getiriler) ** 0.5) if getiriler else 0.0
    t_ist     = beklenti / se if se else 0.0

    kaz = [t for t in işlemler if t["pnl"] > 0]
    kay = [t for t in işlemler if t["pnl"] <= 0]
    wr  = len(kaz) / len(işlemler) * 100
    ok_ort = statistics.mean([t["pnl_yuzde"] for t in kaz]) if kaz else 0
    ky_ort = statistics.mean([t["pnl_yuzde"] for t in kay]) if kay else 0
    rr     = abs(ok_ort / ky_ort) if ky_ort else 0
    basabas = (abs(ky_ort) / (ok_ort + abs(ky_ort)) * 100) if (ok_ort or ky_ort) else 0

    print(f"  beklenti/işlem : %{beklenti:+.3f}   (eşik: >%{MIN_BEKLENTI_PCT})")
    print(f"  t istatistiği  : {t_ist:.2f}        (eşik: >{MIN_T_ISTATISTIGI})")
    print(f"  %95 güven aralığı: %{beklenti-2*se:+.3f} … %{beklenti+2*se:+.3f}")
    print(f"  ── bilgi ──")
    print(f"  win rate       : %{wr:.1f}  (başabaş: %{basabas:.1f} — R/R {rr:.1f}:1)")
    print(f"  ort kazanç/kayıp: %{ok_ort:+.2f} / %{ky_ort:+.2f}")

    ok = beklenti > MIN_BEKLENTI_PCT
    print(f"\n  {_renk(ok)}  beklenti eşiği")
    if not ok:
        kritik_hata.append(f"Beklenti %{beklenti:+.3f} < %{MIN_BEKLENTI_PCT} — edge yetersiz")

    ok = t_ist > MIN_T_ISTATISTIGI
    print(f"  {_renk(ok)}  istatistiksel anlamlılık")
    if not ok:
        kritik_hata.append(
            f"t={t_ist:.2f} < {MIN_T_ISTATISTIGI} — sonuç gürültüden ayırt edilemiyor")

    if wr < basabas:
        uyari.append(f"win rate %{wr:.1f}, başabaşın (%{basabas:.1f}) ALTINDA")

    # ══ BÖLÜM 3: RİSK ══════════════════════════════════════
    print("\n── 3. RİSK ──")

    bakiye, zirve, maxdd = 10000.0, 10000.0, 0.0
    for t in işlemler:
        bakiye += t["pnl"]
        zirve = max(zirve, bakiye)
        maxdd = max(maxdd, (zirve - bakiye) / zirve * 100)

    seri = enuzun = 0
    for t in işlemler:
        seri = seri + 1 if t["pnl"] <= 0 else 0
        enuzun = max(enuzun, seri)

    ok = maxdd < MAX_DRAWDOWN_PCT
    print(f"  {_renk(ok)}  maks. drawdown %{maxdd:.2f}  (eşik: <%{MAX_DRAWDOWN_PCT})")
    if not ok:
        kritik_hata.append(f"Drawdown %{maxdd:.1f} — kill switch eşiğini aşıyor")

    ok = enuzun <= MAX_ARDARDA_KAYIP
    print(f"  {_renk(ok)}  en uzun kayıp serisi {enuzun}  (eşik: ≤{MAX_ARDARDA_KAYIP})")
    if not ok:
        kritik_hata.append(f"{enuzun} ardışık kayıp — beklenenin (~7) belirgin üstünde")

    print(f"  toplam PnL     : {sum(t['pnl'] for t in işlemler):+.2f} USDT")

    # ══ BÖLÜM 4: DAVRANIŞ ══════════════════════════════════
    print("\n── 4. DAVRANIŞ DOĞRULAMASI (elle onaylanır) ──")
    print("  [ ] Kill switch en az bir kez tetiklendi ve doğru resetlendi")
    print("      → 100 işlemde ~2-3 kez BEKLENİR (5 ardışık kayıp eşiği).")
    print("        Hiç tetiklenmediyse ŞÜPHELEN: kill switch ölü olabilir.")
    print("  [ ] Bir zarar dönemi gözlemlendi, bot mantıklı davrandı (§1.4)")
    print("  [ ] Botun uzun kesintisi olmadı (kesinti SL davranışını bozar)")
    print("  [ ] 100 işlemin tamamı AYNI kod sürümüyle toplandı")

    # ══ HÜKÜM ══════════════════════════════════════════════
    print("\n" + "=" * 68)
    if kritik_hata:
        print("  ❌ AŞAMA 2'YE GEÇME")
        for h in kritik_hata:
            print(f"     • {h}")
    else:
        print("  ✅ İSTATİSTİKSEL KAPILAR GEÇİLDİ")
        print("     Bölüm 4'teki 4 maddeyi elle onaylayın, sonra Aşama 2:")
        print("     TRADE_USDT=10, kaldıraç 3x, minimum 2 hafta.")
    if uyari:
        print("\n  🟡 Uyarılar:")
        for u in uyari:
            print(f"     • {u}")
    print("=" * 68)
    print("  NOT: Bu kural 2026-08-26'da, n=7 iken yazıldı. Eşikleri")
    print("  veriye bakarak değiştirmek protokolü geçersiz kılar.")
    print("=" * 68)
    return 0 if not kritik_hata else 1


if __name__ == "__main__":
    sys.exit(main())
