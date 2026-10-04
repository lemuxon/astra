#!/usr/bin/env python3
# =========================================================
# ASTRA — Tüm Testleri Çalıştırıcı
# Kullanım: python testleri_calistir.py
# =========================================================
import sys, os, subprocess

KOK = os.path.dirname(os.path.abspath(__file__))

def main():
    print("\n" + "█" * 56)
    print("  ASTRA — TÜM TEST PAKETLERİ")
    print("█" * 56)

    test_dosyalari = [
        "tests/test_cekirdek.py",
        "tests/test_execution.py",
        "tests/test_validator.py",
        "tests/test_para_yolu.py",     # v56: para yolu (boyutlandırma/risk/SL/sync)
        "tests/test_guvenlik_agi.py",  # v56: güvenlik ağı (SL zorla-kapat/reconciler)
        "tests/test_imza_retry.py",    # v56: HMAC imza + idempotent retry + rate limit
        "tests/test_veto_zinciri.py",  # v56: _execution_isle 13 güvenlik kapısı
        "tests/test_izolasyon.py",     # v57: testler ÜRETİM verisine yazmamalı
        "tests/test_ana_thread.py",    # v57: ana thread ölürse motor da ölür
        "tests/test_sl_dolum.py",      # v57: SL/TP seviyeden dolmalı (paper↔canlı)
        "tests/test_algo_emir.py",     # v57: koşullu emirler Algo Service'e taşındı
        "tests/test_state_kayit.py",   # v57: bot açtığı pozisyonu state'e kaydetmeli
        "tests/test_paper_canli_sl.py",# v57: paper↔canlı SL/TP eşitliği
        "tests/test_grafik_thread.py", # v57: grafik üretimi thread-safe
        "tests/test_rr_kapisi.py",     # v57: minimum R/R kapısı (negatif beklenti engeli)
        "tests/test_watchdog_uyku.py", # v57: uyku ≠ donma (sahte alarm + SIGTERM)
        "tests/test_cikis_kapisi.py",  # v58: çıkış kapısı girişten zayıf olmamalı (K-A/K-B)
        "tests/test_yeniden_giris.py", # v58: kapanış sonrası bekleme (K-C)
        "tests/test_veri_kaynagi.py",  # v58: piyasa verisi gerçek borsadan (K-15)
        "tests/test_kapanmis_bar.py",  # v58: göstergeler kapanmış bara bakar (K-16)
        "tests/test_model_olcum.py",   # v58: sahte accuracy / feedback sızıntısı (K-17..21)
        "tests/test_ucgen_bariyer.py", # v58: üçlü bariyer hedefi + embargo (K-23)
        "tests/test_sayfalama.py",     # v58: 1000 bar kırpması + eğitim penceresi (K-24/25)
        "tests/test_feature_duraganlik.py",  # v58: ham fiyat seviyesi feature değildir (K-26)
        "tests/test_ufuk_tutarlilik.py",     # v58: ana işlem ufku tek kaynak (K-29)
        "tests/test_giris_fiyati.py",        # v58: giriş anlık fiyattan + geç giriş iptali (K-31)
        "tests/test_rapor_tutarlilik.py",    # v58: panel/Telegram çift sayım + bakiye etiketi (K-32/33)
        "tests/test_kontrol_betigi.py",      # v58: sağlık betiği cp1254 konsolda çökmemeli (K-35)
        "tests/test_rejim_birlestirme.py",   # v58: HMM yönsüz etiketten yön uydurmamalı (K-36)
        "tests/test_model_beceri.py",        # v58: seçim beceriye baksın, beceri yoksa nötrle (K-37)
        "tests/test_para_dokumu.py",         # v58: komisyon kaydı + para dökümü tutarlılığı (K-42)
        "tests/test_drift_dedektoru.py",     # v58: drift z-skoru patlaması + aynı bar tekrarı (K-43)
        "tests/test_denetim_duzeltmeleri.py",# v58: online learner/MC birimi/AB Sharpe/sessiz yutma (K-45..49)
        "tests/test_veri_tutarliligi.py",    # v58: kaynaklar arası eşleşme + muhasebe özdeşlikleri (K-51)
        "tests/test_komut_sembol.py",        # v58: /market BTCUSDT → BTCUSDTUSDT hatası (K-52)
        "tests/test_panel_esszamanlilik.py", # v58: panel 56s donuyordu — tek iş parçacıklı sunucu (K-53)
        "tests/test_komut_kaydi.py",         # v58: ilan/kayıt/tanım üçlüsü ayrışmasın (K-54)
        "tests/test_model_onbellek.py",      # v58: acc eşiği taze modeli yeniden eğitmesin (K-55)
        "tests/test_pozisyon_kaynagi.py",    # v58: /fpoz paper pozisyonu göstermiyordu + PnL (K-56/57)
        "tests/test_bakiye_butunlugu.py",    # v58: taban sahte para üretiyordu, restart sapması (K-59)
        "tests/test_ogrenme_ve_teshis.py",   # v58: bayat timestamp/uydurma etiket/veto körlüğü (K-63..68)
        "tests/test_kapasite_ve_bildirim.py",# v58: rejim/telegram/bar önbelleği/panel/arşiv (K-39, K-71..74)
        "tests/test_rejim_esigi_essitligi.py", # v58: paper ↔ canlı rejim kapısı (K-69)
        "tests/test_kaldirac_gosterimi.py",   # v58: panel gerçek kaldıracı göstermeli (K-89)
        "tests/test_panel_koruma_alanlari.py",# v58: SL/TP/tasfiye/marjin/zaman panele taşınır (K-90)
        "tests/test_kosucu_kapsami.py",       # v58: listeye eklenmeyen test sessizce atlanmasın (K-91)
        "tests/test_yedek_butunlugu.py",      # v58: sıfırlama yedeği WAL dahil olmalı (K-92)
        "tests/test_sifirlama_kapisi.py",     # v58: bot çalışırken sıfırlama reddedilmeli (K-93)
        "tests/test_mtf_teshis_kaydi.py",     # v58: MTF veto mesajı hiyerarşiden türesin (K-94)
        "tests/test_giris_kayma_esigi.py",    # v58: geç giriş eşiği ATR ile ölçeklenir (K-95)
        "tests/test_mtf_hizalama.py",         # v58: ana trend nötrken hizalama sayılsın (K-96)
        "tests/test_veto_zinciri_ortak.py",   # v58: veto zinciri paper↔canlı ortak (K-97)
        "tests/test_reconciler_state.py",     # v58: reconciler orphan'ı state'e ekleyebilmeli (K-99)
        "tests/test_strateji_secimi.py",      # v58: MR ancak koşulu sağlanıyorsa seçilsin (K-102)
    ]

    toplam_basari = True
    for td in test_dosyalari:
        yol = os.path.join(KOK, td)
        if not os.path.exists(yol):
            print(f"\n  ⚠ {td} bulunamadı, atlanıyor")
            continue
        print(f"\n▶ {td} çalıştırılıyor...")
        # v55 DÜZELTME: Windows'ta (Türkçe locale, cp1254) alt sürecin çıktısı
        # UTF-8 olarak çözülemiyordu → reader thread UnicodeDecodeError atıyor,
        # sonuc.stdout None kalıyor ve bir satır sonra
        # `AttributeError: 'NoneType' object has no attribute 'split'`
        # ile TÜM test çalıştırıcısı çöküyordu. Yani "testleri çalıştır"
        # komutu Windows'ta hiç çalışmıyordu.
        # Çözüm: alt sürece UTF-8 zorla + çözülemeyen baytları değiştir.
        ortam = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        sonuc = subprocess.run([sys.executable, "-X", "utf8", yol],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               env=ortam)
        # Sadece özet satırlarını göster
        for satir in (sonuc.stdout or "").split("\n"):
            # v56: test_validator.py "✅ ... / N/N test geçti" formatında
            # yazıyor; eski filtre bunu yakalamadığı için o paketin sonucu
            # ekranda hiç görünmüyordu (sessizce "boş" geçiyordu).
            if any(x in satir for x in ["GEÇTİ", "HATA", "ÇÖKTÜ", "SONUÇ",
                                         "===", "TEST", "geçti", "✅", "❌"]):
                print("  " + satir)
        if sonuc.returncode != 0:
            toplam_basari = False
            # v55: Başarısızlıkta stderr'i de göster — eskiden sessizce
            # yutuluyordu ve neden başarısız olduğu görünmüyordu.
            hata_ciktisi = (sonuc.stderr or "").strip()
            if hata_ciktisi:
                print("  ── stderr ──")
                for satir in hata_ciktisi.split("\n")[-15:]:
                    print("  " + satir)

    print("\n" + "█" * 56)
    if toplam_basari:
        print("  ✅ TÜM TESTLER BAŞARILI")
    else:
        print("  ❌ BAZI TESTLER BAŞARISIZ — yukarıyı inceleyin")
    print("█" * 56 + "\n")
    sys.exit(0 if toplam_basari else 1)

if __name__ == "__main__":
    main()
