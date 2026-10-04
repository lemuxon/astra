#!/usr/bin/env python3
# =========================================================
# ASTRA v58 — 7. SIFIRLAMA (K-37 davranış değişikliği)
#
# NEDEN:
#   K-37 model seçimini ve model güveninin ai_score'a katkısını
#   DEĞİŞTİRDİ. §5.3 gereği toplanan tüm veri TEK bir yapılandırmayı
#   yansıtmalıdır; iki farklı model-seçim davranışının ürettiği işlemleri
#   aynı 100'lük örneklemde toplamak, o örneklemi yorumlanamaz kılar.
#
#   Değişen üç şey:
#     1. Aday seçimi ham accuracy yerine BECERİ (acc − taban çizgisi)
#     2. walk_forward_cv beceri/taban raporluyor
#     3. Beceri kendi belirsizliğinden büyük değilse model güveni
#        NÖTRLENİYOR (yukselis_guveni = 50) → ai_score'a katkı vermiyor
#
#   (3) doğrudan sinyal üretimini etkiliyor: model katkısı ±2 puandı,
#   giriş eşiği |ai| >= 4. Yani eski işlemler ile yenileri AYNI sistemin
#   ürünü değil.
#
# NEDEN ŞİMDİ:
#   Elde yalnızca 2 kapanmış + 2 açık işlem var. Aynı kusuru 50 işlem
#   sonra bulup sıfırlamak çok daha pahalı olurdu. Sıfırlama maliyetinin
#   en düşük olduğu an bu.
#
# MODELLER DE SİLİNİYOR:
#   Diskteki wf_*.json dosyaları K-37 ÖNCESİ formatta (beceri_ort alanı
#   yok). Seçim bunları görünce "ESKİ FORMAT" uyarısıyla ham accuracy'ye
#   düşer. Silinmezlerse düzeltme, modeller doğal olarak yenilenene kadar
#   KISMEN etkisiz kalır — sessiz değil (uyarı basılıyor) ama gereksiz.
#
# GERİ ALMA: yedek dizinindekileri data/ ve saved_models/ üzerine kopyala.
# =========================================================
import os
import shutil
import sqlite3
import sys
from datetime import datetime

if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
for _a in (sys.stdout, sys.stderr):
    try:
        _a.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

DURUM_DOSYALARI = ("data/astra.db", "data/journal.db",
                   "data/ab_test.json", "data/position_state.json")


def _yedekle(kaynak: str, hedef_dizin: str) -> None:
    """Tek dosyayı yedekle — SQLite ise WAL DAHİL (v58 K-92).

    ── NEDEN VAR ────────────────────────────────────────────────
    `shutil.copy2("data/astra.db", ...)` YETMEZ. Veritabanı **WAL
    modunda** (`PRAGMA journal_mode` = wal) ve bot 7/24 açık bir
    bağlantı tuttuğu için checkpoint kendiliğinden olmuyor: son
    saatlerin işlemleri `astra.db-wal` dosyasında durur, ana `.db`
    dosyasında DEĞİLDİR.

    ÖLÇÜLDÜ (2026-09-13, 10. sıfırlamanın yedeği):
        yedek dizini oluşturuldu : 15:02
        içindeki astra.db tarihi : 14:35   ← son checkpoint
        içindeki en yeni işlem   : 12:43
        -wal dosyası             : YOK
    ➜ Sıfırlama anında var olan ~2 sa 20 dk'lık işlem HİÇBİR YERDE
    yok: canlı DB'den silindi, yedeğe hiç girmedi. Aynı imza 13
    yedeğin HEPSİNDE vardı (her birinin en yeni işlemi, yedeğin
    alındığı saatten saatlerce geride).

    Yedek, sıfırlamanın tek güvenlik ağıdır; dolu görünüp eksik
    olması §10'un tarif ettiği kör noktanın ta kendisidir.

    `sqlite3.Connection.backup()` WAL'i de kapsayan TUTARLI bir anlık
    görüntü alır (bot yazmaya devam ederken bile).
    """
    hedef = os.path.join(hedef_dizin, os.path.basename(kaynak))
    if not kaynak.endswith(".db"):
        shutil.copy2(kaynak, hedef)
        return
    src = sqlite3.connect(f"file:{kaynak}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(hedef)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def bot_calisiyor_mu() -> bool:
    """Bot açıkken sıfırlamak yarış durumu yaratır (bakiye DB'den türer).

    ── K-93: BU KAPI ETKİSİZDİ (v58, 2026-09-13) ────────────────
    Eski hâli `(... | Where-Object {...}).Count` kullanıyordu.
    PowerShell 5.1 tek nesneli sonucu diziden ÇIKARIR ve `.Count`
    **BOŞ STRING** döner:

        (...).Count  -> ''     @(...).Count -> '1'

    `.strip() not in ("", "0")` boş stringi "bot yok" sayıyordu.
    ÖLÇÜLDÜ: bot PID 13760 ile çalışırken fonksiyon **False** döndü.

    ➜ Tam olarak korumak istediği durumda — TEK bot çalışırken, yani
    NORMAL durumda — kapı açıktı. Sıfırlama sessizce devam eder ve
    K-59'un tarif ettiği bakiye yarışını yaratırdı.

    ⚠️ `except` dalı da fail-OPEN'dı (§5.1): kontrol patlarsa "bot
    çalışmıyor" diyordu. Yıkıcı bir işlemi koruyan kapıda doğru
    varsayılan TERSİDİR — bilmiyorsak DURDUR.
    """
    try:
        import subprocess
        o = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "@(Get-CimInstance Win32_Process -Filter \"name='python.exe'\" "
             "-ErrorAction SilentlyContinue | Where-Object "
             "{ $_.CommandLine -like '*main.py bot*' }).Count"],
            capture_output=True, text=True, timeout=60)
        ham = (o.stdout or "").strip()
        if ham == "":
            # @() ile bu olmamalı; olduysa ölçemedik demektir → fail-closed
            print("  ⚠️  Bot durumu OKUNAMADI (boş yanıt) — güvenli tarafta "
                  "kalınıyor, çalışıyor varsayılıyor.")
            return True
        return ham != "0"
    except Exception as e:
        print(f"  ⚠️  Bot durumu kontrol edilemedi ({type(e).__name__}: {e}) — "
              f"güvenli tarafta kalınıyor, çalışıyor varsayılıyor.")
        return True          # §5.1 fail-CLOSED: bilmiyorsak sıfırlama


def main():
    print("=" * 64)
    print("  ASTRA v58 — 7. SIFIRLAMA (K-37)")
    print("=" * 64)

    if not os.path.exists("data/astra.db"):
        print("  ✗ data/astra.db yok — proje kökünden çalıştırın.")
        sys.exit(1)

    if bot_calisiyor_mu():
        print("\n  ✗ BOT ÇALIŞIYOR. Önce durdurun:")
        print("      Stop-ScheduledTask -TaskName ASTRA_Bot")
        print("      (ve python main.py bot sürecini sonlandırın)")
        print("    Çalışan bot sıfırlamadan sonra eski bakiyeyi geri yazabilir.")
        sys.exit(2)

    c = sqlite3.connect("data/astra.db")
    kapali = c.execute("SELECT COUNT(*) FROM trades WHERE mod='PAPER' "
                       "AND durum!='ACIK'").fetchone()[0]
    acik = c.execute("SELECT COUNT(*) FROM trades WHERE mod='PAPER' "
                     "AND durum='ACIK'").fetchone()[0]
    print(f"  Mevcut: {kapali} kapanmış, {acik} açık")

    zaman = datetime.now().strftime("%Y%m%d_%H%M%S")
    yedek = f"data/_yedek_k37_{zaman}"
    os.makedirs(yedek, exist_ok=True)
    for f in DURUM_DOSYALARI:
        if os.path.exists(f):
            _yedekle(f, yedek)      # v58 K-92: .db için WAL dahil
    if os.path.isdir("saved_models"):
        # `versions/` YEDEKLENMİYOR: bu betik oraya DOKUNMUYOR (yalnızca
        # saved_models altındaki DOSYALARI siliyor, alt dizinleri değil).
        # İlk sürüm onu da kopyalıyordu ve yedek 22 GB oldu — 6431 dosyalık
        # model kayıt defteri. Dokunulmayan bir dizini yedeklemek saf israf.
        shutil.copytree("saved_models", os.path.join(yedek, "saved_models"),
                        ignore=shutil.ignore_patterns("_yedek_*", "versions"),
                        dirs_exist_ok=True)
    print(f"  Yedek : {yedek}")

    # ── PAPER işlemleri sil (açık dahil) ──────────────────────────
    # Açık pozisyonu silmek normalde bakiye tutarsızlığı yaratır, ama
    # burada TÜM paper geçmişi siliniyor → bakiye başlangıç değerine
    # döner, tutarsızlık oluşmaz. Bot da durdurulmuş durumda.
    c.execute("DELETE FROM trades WHERE mod='PAPER'")
    c.execute("DELETE FROM sqlite_sequence WHERE name='trades'")
    c.commit()
    kalan = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    c.execute("VACUUM")
    c.close()
    print(f"  astra.db trades : {kapali + acik} → {kalan}")

    if os.path.exists("data/journal.db"):
        j = sqlite3.connect("data/journal.db")
        j0 = j.execute("SELECT COUNT(*) FROM journal "
                       "WHERE mod='PAPER'").fetchone()[0]
        j.execute("DELETE FROM journal WHERE mod='PAPER'")
        j.commit()
        j1 = j.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
        j.execute("VACUUM")
        j.close()
        print(f"  journal PAPER   : {j0} → 0 (toplam kalan {j1})")

    if os.path.exists("data/position_state.json"):
        os.remove("data/position_state.json")
        print("  position_state.json silindi (silinen pozisyonlara işaret ediyordu)")

    # v58 (K-49): A/B test birikimi de SIFIRLANIR.
    # İlk sürümde yedekleniyor ama SİLİNMİYORDU. Sonuç: 2026-08-27
    # tarihli 5+5 örnek, 4h geçişinden VE K-37'den ÖNCEki koddan gelmesine
    # rağmen panelde güncelmiş gibi gösteriliyordu. §5.3: toplanan tüm
    # veri TEK yapılandırmayı yansıtmalı — A/B karşılaştırması da veri.
    if os.path.exists("data/ab_test.json"):
        os.remove("data/ab_test.json")
        print("  ab_test.json silindi (farklı yapılandırmadan kalma)")

    # ── Eski format modeller ──────────────────────────────────────
    silinen = 0
    if os.path.isdir("saved_models"):
        for ad in os.listdir("saved_models"):
            yol = os.path.join("saved_models", ad)
            if not os.path.isfile(yol):
                continue
            if ad.startswith("feedback_"):
                continue          # gerçek kapanışlardan gelen eğitim verisi
            if (ad.endswith(".pkl") or ad.endswith(".keras")
                    or ad.startswith("wf_")):
                os.remove(yol)
                silinen += 1
    print(f"  Model dosyası   : {silinen} silindi (K-37 öncesi WF formatı)")

    # 4h başlangıç noktasını tazele — kontrol_4h.py farkı buradan ölçüyor
    try:
        import json
        with open("data/4h_baslangic.json", "w", encoding="utf-8") as f:
            json.dump({"kayit_zamani_yerel": datetime.now().isoformat(),
                       "paper_kapali": 0, "paper_acik": 0,
                       "not": "K-37 sıfırlaması (7.)"}, f, ensure_ascii=False)
        print("  4h_baslangic.json tazelendi (tempo buradan ölçülür)")
    except OSError as e:
        print(f"  ⚠️  4h_baslangic.json yazılamadı: {e}")

    print("=" * 64)
    print("  ✅ Sayaç 0/100. Sayım K-37 kodundan itibaren geçerli.")
    print(f"  Geri alma: {yedek} içindekiler data/ ve saved_models/ üzerine.")
    print("  ŞİMDİ: botu yeniden başlatın (baslat_bot.bat).")
    print("=" * 64)


if __name__ == "__main__":
    main()
