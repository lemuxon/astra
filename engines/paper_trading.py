# =========================================================
# ASTRA v30.0 — PAPER TRADING ENGINE (Tam Düzeltme)
# Düzeltmeler:
#   1. Pozisyon boyutu: sabit TRADE_USDT kullan, astronomik miktar yok
#   2. stop_tp_kontrol bakiyeyi güncellliyor (kapanışta geri ekleniyor)
#   3. Bakiye DB'den başlatılıyor (restart sonrası kaybolmuyor)
#   4. Açık pozisyon maliyetleri restart'ta hesaplanıyor
# =========================================================
import logging
from datetime import datetime

import sys
sys.path.append("..")
from config import (BALANCE, RISK_PERCENT, TRADE_USDT,
                    MIN_AI_SCORE_BUY, MIN_AI_SCORE_SELL,
                    MIN_CONFIDENCE, SHORT_ENABLED,
                    PAPER_KOMISYON, PAPER_SLIPPAGE_BPS,
                    # v56: paper de canlıyla AYNI portföy limitlerine uymalı
                    MAX_OPEN_POSITIONS, MAX_SAME_DIRECTION)
from engines.futures_trade_engine import sinyal_kalitesi_degerlendir
# ── v58 (K-66): VETO SAYACI PAPER YOLUNA DA BAĞLI ────────────
# `_veto_kaydet` çağrılarının TAMAMI main.py::_execution_isle içindeydi
# ve o fonksiyon `if not LIVE_TRADING: return` ile başlıyor. Yani paper
# modda (bugünkü mod) hiçbir red sayılmıyordu: /neden ve panel kalıcı
# olarak "Henüz işlem denemesi yok" diyordu — oysa logda binlerce
# gerçek red vardı (ölçüm: 2026-09-04..06 arası 1347 red satırı).
from core.teshis import _veto_kaydet, _islem_acildi_kaydet
from data.database import (trade_ac, trade_kapat, acik_tradeler,
                             toplam_pnl, win_rate_hesapla,
                             son_kapanis_yasi_sn)

log = logging.getLogger("ASTRA.PAPER")


def _para_blogu(para: dict) -> str:
    """v58 (K-42): para dökümünü Telegram satırlarına çevirir.

    Ayrı fonksiyon: `rapor_str` içine gömülü olsaydı test edilemezdi
    (K-37'de tam bu tuzağa düşüldü — mantık satır içindeyken mutasyon
    testi onu kaldıran değişikliği yakalayamamıştı).
    """
    if not para or "hata" in para:
        return f"⚠️  Para dökümü alınamadı: {para.get('hata', 'bilinmiyor')}\n"
    s = (
        f"🏦 Başlangıç   : {para['baslangic']:,.2f} USDT\n"
        f"💵 Nakit       : {para['nakit']:,.2f} USDT\n"
        f"🔒 Bağlı serm. : {para['bagli_sermaye']:,.2f} USDT "
        f"({para['acik_pozisyon']} pozisyon)\n"
        f"🧮 Toplam varlık: {para['toplam_varlik']:,.2f} USDT\n"
        f"📊 Brüt PnL    : {para['brut_pnl']:+.4f} USDT\n"
        f"💸 Komisyon    : −{para['odenen_komisyon']:.4f} USDT\n"
        f"💱 Fonlama     : −{para.get('odenen_fonlama', 0):.4f} USDT"
    )
    if para["komisyon_payi_pct"]:
        s += f" (brütün %{para['komisyon_payi_pct']}'i)"
    s += (f"\n✅ Net PnL     : {para['gerceklesen_pnl']:+.4f} USDT "
          f"({para['kapanan_islem']} kapanan)\n")
    # K-42 öncesi kayıtlarda komisyon NULL — sessizce eksik göstermeyelim
    eksik = para["kapanan_islem"] - para["komisyonu_bilinen"]
    if eksik > 0:
        s += (f"⚠️  {eksik} eski işlemin komisyonu kayıtlı değil "
              f"(K-42 öncesi) — komisyon toplamı EKSİK\n")
    s += "━━━━━━━━━━━━━━━━━━\n"
    return s


class PaperTrader:
    def __init__(self, baslangic_bakiye: float = BALANCE):
        self.baslangic = baslangic_bakiye
        # Bakiyeyi DB'den hesapla: başlangıç - açık pozisyon maliyetleri + kapalı PnL
        self.bakiye = self._bakiye_hesapla(baslangic_bakiye)
        log.info(
            f"PaperTrader başlatıldı | Bakiye: {self.bakiye:,.2f} | "
            f"Min BUY skor: {MIN_AI_SCORE_BUY} | Min SELL skor: {MIN_AI_SCORE_SELL} | "
            f"Min güven: %{MIN_CONFIDENCE} | SHORT: {'Açık' if SHORT_ENABLED else 'Kapalı'}"
        )

    def _bakiye_hesapla(self, baslangic: float) -> float:
        """Restart sonrası bakiyeyi DB'den hesapla."""
        try:
            kapali_pnl   = toplam_pnl("PAPER") or 0.0
            aciklar      = acik_tradeler("PAPER")
            # ── v58 (K-86): AÇIK POZİSYONDA BAĞLANAN TUTAR = MARJİN ──
            # Açılışta bakiyeden MARJİN düşülüyor (notional değil), bu
            # yüzden restart'ta da marjin düşülmeli. Notional düşülseydi
            # yeniden başlatılan bakiye ÇALIŞAN bakiyeden sapardı —
            # K-59'un düzelttiği hatanın birebir tekrarı.
            #
            # Eski kayıtlarda `marjin` alanı yoksa notional'a düşülür:
            # o pozisyonlar 1x döneminde açılmıştı, marjin = notional.
            def _bagli(t):
                m = t.get("marjin")
                if m and float(m) > 0:
                    return float(m)
                return float(t.get("giris_fiyat") or 0) * float(t.get("miktar") or 0)
            acik_maliyet = sum(_bagli(t) for t in aciklar)
            bakiye = baslangic + kapali_pnl - acik_maliyet
            # ── v58 (K-59): SAHTE PARA ÜRETEN TABAN KALDIRILDI ────────
            # Eskiden `bakiye = max(bakiye, baslangic * 0.05)` vardı.
            # Ölçüm: %99 zarardan sonra gerçek bakiye 100 USDT olmalıyken
            # bu satır 500 döndürüyordu — **400 USDT SAHTE PARA**.
            #
            # Neden ciddi:
            #  1. Felaket zararı GİZLİYOR. 100 işlemlik protokolün görmek
            #     istediği şeylerden biri tam da bu: kill switch davranışı
            #     ve zarar dönemi (§3 ENGEL 2).
            #  2. Yalnızca YENİDEN BAŞLATMADA devreye giriyor → çalışan
            #     bakiye ile yeniden başlatılmış bakiye AYRIŞIYOR.
            #  3. Sessiz. §5.1: "bilmiyorum"/"kötü" durumu iyi göstermek
            #     bu kod tabanının ana hastalığı.
            #
            # Doğru davranış: gerçek rakamı döndür, anormallikte SESLİ ol.
            if bakiye <= 0:
                log.critical(
                    f"[PAPER] BAKİYE TÜKENDİ: {bakiye:.4f}$ "
                    f"(başlangıç:{baslangic} pnl:{kapali_pnl:+.4f} "
                    f"açık:{acik_maliyet:.4f}). Hesap patlamış — yeni "
                    f"pozisyon açılmayacak.")
                return 0.0
            if bakiye < baslangic * 0.05:
                log.warning(
                    f"[PAPER] Bakiye başlangıcın %5'inin ALTINDA: "
                    f"{bakiye:.4f}$ (başlangıç {baslangic}). Eskiden bu "
                    f"değer sessizce {baslangic * 0.05:.2f}'e yükseltiliyordu "
                    f"(K-59) — artık GERÇEK değer kullanılıyor.")
            # v58 (K-59): `round(...,2)` KALDIRILDI. Artımlı bakiye tam
            # hassasiyette tutuluyor; her yeniden başlatmada 2 basamağa
            # yuvarlamak ikisini ayrıştırıyordu (ölçüm: 0.0027$/restart).
            log.info(f"[PAPER] Bakiye hesaplandı: {bakiye:.4f}$ "
                     f"(başlangıç:{baslangic} pnl:{kapali_pnl:+.4f} açık:{acik_maliyet:.4f})")
            return bakiye
        except Exception as e:
            log.warning(f"[PAPER] Bakiye hesaplama hatası: {e} → başlangıç kullanılıyor")
            return baslangic

    def _slippage_uygula(self, fiyat: float, yon: str, giris_mi: bool) -> float:
        """v56: Gerçekçi slippage — her zaman ALEYHTE yönde.

        Giriş: LONG biraz pahalıya, SHORT biraz ucuza alınır.
        Çıkış: LONG biraz ucuza, SHORT biraz pahalıya kapanır.
        backtest_engine ile aynı mantık (orada _slippage_uygula mevcuttu,
        paper trading'de hiç yoktu).
        """
        if PAPER_SLIPPAGE_BPS <= 0 or fiyat <= 0:
            return fiyat
        oran = PAPER_SLIPPAGE_BPS / 10000.0
        long_pozisyon = (yon == "LONG")
        # Giriş LONG → yukarı, çıkış LONG → aşağı (ikisi de aleyhte)
        yukari = long_pozisyon if giris_mi else (not long_pozisyon)
        return fiyat * (1 + oran) if yukari else fiyat * (1 - oran)

    def _sinyal_kalitesi_gecer(self, sonuc: dict, yon: str, etiket="PAPER",
                                sayacli: bool = True) -> bool:
        """Sinyalin kendisi bu yönde işlem yapmaya yetecek güçte mi?

        v58 (K-A): AYRI BİR METODA ÇIKARILDI çünkü hem AÇILIŞ hem
        KAPANIŞ yolunun AYNI barı kullanması gerekiyor. Eskiden bu
        kontroller `_filtre_gec` içine gömülüydü ve `_filtre_gec`
        yalnızca açılış yolunda çağrılıyordu → kapanış eşiksizdi.

        Portföy limitleri (MAX_OPEN_POSITIONS vb.) burada YOK: onlar
        yeni RİSK almayı sınırlar, pozisyon KAPATMAYI değil. Kapanışın
        önüne konulsalardı slot doluyken pozisyon kapatılamazdı.

        `sayacli` — v58 (K-66): teşhis sayacı YALNIZCA açılış yolunda
        yazar. Bu metot ÇIKIŞ yolundan da çağrılıyor (`_cikis_gecerli`);
        oradaki redler "pozisyon açılmadı" değil "pozisyon kapatılmadı"
        demektir. Ayrımı yapmazsak `/neden`in açılma oranı paydası
        şişer ve teşhis yanlış yeri gösterir — K-56 ile aynı sınıf
        (farklı olayı aynı sayaca yazmak).
        """
        # v58 (K-69): paper'ın sabit ±4 kapısı ile canlı yolun rejim
        # bazlı 3/5/6/7 kapısı ayrışmıştı. Karar mantığı burada yeniden
        # yazılmaz; iki mod aynı ortak fonksiyonu çağırır.
        gecti, neden, esik = sinyal_kalitesi_degerlendir(sonuc, yon)
        if gecti:
            return True

        ai = sonuc.get("ai_score", 0)
        conf = sonuc.get("confidence", 0)
        rejim = sonuc.get("rejim", "RANGE")
        if neden == "guven_dusuk":
            log.info(f"[{etiket}] {sonuc['sembol']} | Güven %{conf} < %{MIN_CONFIDENCE} → ATLANDI")
        elif yon == "LONG":
            log.info(f"[{etiket}] {sonuc['sembol']} | AI skor {ai} < {esik} ({rejim}) → ATLANDI")
        else:
            log.info(f"[{etiket}] {sonuc['sembol']} | AI skor {ai} > {-esik} ({rejim}) → ATLANDI")
        if sayacli:
            _veto_kaydet(neden, sonuc["sembol"])
        return False

    def _cikis_gecerli(self, sonuc: dict, kapatilacak_yon: str) -> bool:
        """Zıt sinyal, AÇIK pozisyonu kapatmaya yetecek güçte mi?

        ── v58 K-A: ÇIKIŞ KAPISI, GİRİŞ KAPISINDAN ZAYIFTI ──────────
        `sinyal_isle` zıt sinyalde kapatırken HİÇBİR eşik uygulamıyordu;
        kapatma bloğu `_filtre_gec`'ten ÖNCE çalışıyor ve `_filtre_gec`
        yalnızca açılış yolunda devrede. Asimetri:
            AÇILIŞ  : |ai| >= 4 VE conf >= 62
            KAPANIŞ : karar metninde "BUY"/"SELL" geçmesi YETERLİ
        Yani ai=3 / conf=55 bir sinyal pozisyon AÇAMAZ ama AÇIK
        pozisyonu KAPATABİLİRDİ.

        ÖLÇÜM (2026-09-02, 21 işlem): zıt sinyalle kapanan 11 işlemin
        11'i de açılış eşiğinin ALTINDAKİ bir sinyalle kesilmişti
        (ai=±3/±4; üçünde conf=55 < 62). Toplam %-1.62. Gerçek 1m
        barlarla karşı-olgusal: SL/TP'ye kadar tutulsalardı %-0.83 →
        erken kesme 0.79 puan, toplam zararın %22'si.

        ── v58 K-B: PAPER ↔ CANLI ÇIKIŞ AYRIŞMASI (§5.3) ───────────
        Canlı yol (main.py::_execution_isle) zıt pozisyonu ancak
        chop → MTF → EdgeEngine → strateji → `sinyal_gecerli_mi`
        zincirinin TAMAMI geçildikten SONRA kapatıyor. Paper ise ham
        coin_analiz çıktısıyla, veto zincirinin DIŞINDA çağrılıyor
        (main.py:1829). Sonuç: paper, canlının asla yapmayacağı
        kesmeleri yapıyordu → 21 işlemin tamamı canlıyı temsil etmiyordu.

        Burada İKİ bar birden uygulanır:
          1. `_sinyal_kalitesi_gecer` — paper'ın kendi açılış barı
          2. `sinyal_gecerli_mi`      — canlının barı (rejim eşiği dahil)
        İkisini de geçmeyen bir sinyal pozisyon kapatamaz.

        ⚠️ TAM EŞİTLİK DEĞİL: chop/MTF/EdgeEngine/strateji vetoları hâlâ
        paper'da çalışmıyor (onlar main.py::_execution_isle içinde
        gömülü). Yani paper çıkışı canlıdan hâlâ bir miktar GEVŞEK —
        ama artık "herhangi bir gürültü kapatır" durumunda değil.
        Tam eşitlik için veto zincirinin ortak bir modüle çıkarılması
        gerekir (§6 açık iş).
        """
        # Kapatma yönü ile SİNYAL yönü terstir: SHORT'u BUY kapatır.
        sinyal_yonu = "LONG" if kapatilacak_yon == "SHORT" else "SHORT"

        # sayacli=False: bu bir ÇIKIŞ reddi, giriş reddi değil (K-66).
        if not self._sinyal_kalitesi_gecer(sonuc, sinyal_yonu,
                                          etiket="PAPER ÇIKIŞ", sayacli=False):
            return False

        try:
            from engines.futures_trade_engine import sinyal_gecerli_mi
            if not sinyal_gecerli_mi(sonuc, sinyal_yonu):
                log.info(f"[PAPER ÇIKIŞ] {sonuc['sembol']} | canlı sinyal "
                         f"filtresi geçilemedi → pozisyon KAPATILMADI (§5.3)")
                return False
        except Exception as e:
            # fail-closed (§5.1): kapıyı doğrulayamıyorsak açık saymayız.
            log.error(f"[PAPER ÇIKIŞ] {sonuc['sembol']} | sinyal_gecerli_mi "
                      f"doğrulanamadı: {e} → pozisyon KAPATILMADI")
            return False

        return True

    def _filtre_gec(self, sonuc: dict, yon: str) -> bool:
        if not self._sinyal_kalitesi_gecer(sonuc, yon):
            return False

        # ── v58 (K-97): SİNYAL VETO ZİNCİRİ — canlıyla ORTAK ─────
        # MTF cascade + MTF hizalama + EdgeEngine `_execution_isle`
        # içine gömülüydü ve o fonksiyon `if not LIVE_TRADING: return`
        # ile başlıyor → PAPER'DA HİÇ ÇALIŞMIYORLARDI.
        #
        # ÖLÇÜLDÜ (2026-09-14 07:15, saniyesi saniyesine):
        #   07:15:13.392 [TRADE AÇILDI] #1 ASTERUSDT     ← paper AÇTI
        #   07:15:14.640 [EXEC ISLE] ASTERUSDT MTF hizalama yok → atlandı
        # Aynı sembol, aynı saniye: paper açtı, canlı reddetti. Paper
        # canlının REDDEDECEĞİ işlemleri açıyordu → 100 işlemlik örneklem
        # canlıyı temsil etmiyordu (§5.3). §6.0'ın kapanışı.
        #
        # `carpan` pozisyon boyutuna uygulanır (zayıf hizalamada 0.6) —
        # canlı yol da aynısını yapıyor, yoksa boyutlar ayrışırdı.
        # ── v58 (K-98): KILL SWITCH KONTROLÜ ────────────────────
        # Paper kill switch'i BESLİYORDU (`trade_sonucu_bildir`, aşağıda)
        # ama HİÇ KONTROL ETMİYORDU. Yani switch tetiklendiğinde canlı
        # durur, paper işlem açmaya DEVAM ederdi — örneklem canlıyı
        # temsil etmezdi. Besleyip okumamak, sayaç tutup bakmamaktır.
        try:
            from engines.kill_switch import get_kill_switch
            if not get_kill_switch().kontrol():
                log.warning(f"[PAPER] {sonuc.get('sembol')} Kill Switch — "
                            f"durduruldu (canlı yol da durdururdu)")
                _veto_kaydet("kill_switch", sonuc.get("sembol", ""))
                return False
        except Exception as e:
            # §5.1: durumu okuyamıyorsak "açık" SAYMA — canlı bu kapıyı
            # uyguluyor, paper'ın atlaması ayrışma demektir.
            log.error(f"[PAPER] {sonuc.get('sembol')} kill switch "
                      f"okunamadı: {type(e).__name__}: {e}")
            _veto_kaydet("kill_switch_hata", sonuc.get("sembol", ""))
            return False

        # ── v58 (K-103): ÇOKLU BORSA FİYAT DOĞRULAMA ────────────
        # Binance fiyatı Bybit/OKX medyanından çok sapıyorsa işlem veto.
        # Amacı "başka borsada işlem yap" DEĞİL — kimsenin görmediği bir
        # Binance fiyatına güvenmemek (K-15'te tam bu yaşandı: testnet'te
        # gerçek piyasada olmayan sıçrama sahte "TP" üretmişti).
        #
        # K-98'de "0 ateşleme" gerekçesiyle paper'a eklenmemişti; sonra
        # 347 kez ateşledi (%4) ve paper canlıdan gevşek kaldı.
        # ➜ "Şu an ateşlemiyor" KALICI BİR GEREKÇE DEĞİL.
        #
        # Ağ yükü: `multi_exchange` 3 sn önbellekli; paper ve canlı aynı
        # sembolde saniyeler içinde çalıştığı için ikinci çağrı önbellekten.
        try:
            from engines.futures_trade_engine import coklu_borsa_gecerli_mi
            _fiyat = float(sonuc.get("anlik_fiyat") or sonuc.get("son_close") or 0)
            _ok, _sebep = coklu_borsa_gecerli_mi(
                sonuc.get("sembol", ""), _fiyat, yon, sonuc)
            if not _ok:
                log.warning(f"[PAPER] 🛡️ {sonuc.get('sembol')} ÇOKLU BORSA "
                            f"VETO: {_sebep} (canlı yol da reddederdi)")
                _veto_kaydet("coklu_borsa", sonuc.get("sembol", ""))
                return False
        except Exception as e:
            # Fonksiyonun kendisi zaten fail-open; buraya düşmek import
            # hatası demektir — görünür bırak (§5.2), işlemi engelleme
            # (canlı da engellemiyor, §5.3).
            log.warning(f"[PAPER] çoklu borsa kapısı çağrılamadı: "
                        f"{type(e).__name__}: {e}")

        try:
            from engines.futures_trade_engine import sinyal_veto_zinciri
            # v58 (K-98): `bakiye_fn` TEMBEL — strateji kapısına ulaşılırsa
            # çağrılır. Paper'ın bakiyesi yerelde, ağ isteği yok.
            gecti, sebep, carpan = sinyal_veto_zinciri(
                sonuc, yon, bakiye_fn=lambda: self.bakiye)
        except Exception as e:
            # §5.1 fail-CLOSED: veto zinciri değerlendirilemiyorsa
            # "sorun yok" SAYMA — canlı bu kapıları uyguluyor, paper'ın
            # atlaması §5.3 ihlalinin ta kendisi olurdu.
            log.error(f"[PAPER] {sonuc.get('sembol')} veto zinciri "
                      f"değerlendirilemedi: {type(e).__name__}: {e}")
            _veto_kaydet("veto_zinciri_hata", sonuc.get("sembol", ""))
            return False
        if not gecti:
            log.info(f"[PAPER] {sonuc.get('sembol')} | {sebep} → ATLANDI "
                     f"(canlı yol da reddederdi)")
            _veto_kaydet(sebep, sonuc.get("sembol", ""))
            return False
        sonuc["_mtf_carpan"] = carpan

        # ── v58 (K-C): YENİDEN GİRİŞ BEKLEME SÜRESİ ──────────
        # Motor kapattığı sembolde ANINDA ters pozisyon açabiliyordu
        # (#15 LONG kapanış → #16 SHORT açılış, AYNI saniye; ikisi
        # toplam %-0.45 saf maliyet). Kapanış→açılış medyanı 92 sn,
        # minimumu 0 sn'ydi. Aynı kapı canlı yolda da var (main.py).
        try:
            from config import YENIDEN_GIRIS_BEKLEME_SN
            yas = son_kapanis_yasi_sn(sonuc["sembol"], "PAPER")
            if yas is not None and yas < YENIDEN_GIRIS_BEKLEME_SN:
                log.info(f"[PAPER] {sonuc['sembol']} | son kapanıştan "
                         f"{yas:.0f}sn geçti < {YENIDEN_GIRIS_BEKLEME_SN}sn "
                         f"→ ATLANDI (yeniden giriş beklemesi)")
                _veto_kaydet("yeniden_giris_beklemesi", sonuc["sembol"])
                return False
        except Exception as e:
            log.error(f"[PAPER] {sonuc['sembol']} | yeniden giriş beklemesi "
                      f"doğrulanamadı: {e} → işlem ATLANDI")
            _veto_kaydet("yeniden_giris_beklemesi_hata", sonuc["sembol"])
            return False   # fail-closed (§5.1)

        # ── v56: PORTFÖY RİSK LİMİTLERİ ──────────────────────
        # Eskiden paper trading MAX_OPEN_POSITIONS ve MAX_SAME_DIRECTION'ı
        # HİÇ kontrol etmiyordu; canlı yol (risk_manager.tum_kontroller)
        # ise uyguluyordu. Sonuç: paper aynı anda 3 pozisyon açarken canlı
        # 1 tanesine izin veriyordu → paper işlem sayısı, PnL, drawdown ve
        # korelasyon riski canlıyı TEMSİL ETMİYORDU.
        # CANLI_GECIS_PROTOKOLU'nun tüm paper↔canlı karşılaştırması bu
        # eşitliğe dayandığı için limitler burada da uygulanır.
        try:
            acik = acik_tradeler("PAPER")
        except Exception as e:
            log.error(f"[PAPER] Açık pozisyon listesi alınamadı: {e} → "
                      f"risk limiti doğrulanamadı, işlem ATLANDI")
            _veto_kaydet("acik_pozisyon_okunamadi", sonuc["sembol"])
            return False   # fail-closed

        if len(acik) >= MAX_OPEN_POSITIONS:
            log.info(f"[PAPER] {sonuc['sembol']} | Max açık pozisyon "
                     f"{len(acik)}/{MAX_OPEN_POSITIONS} → ATLANDI")
            _veto_kaydet("max_acik_pozisyon", sonuc["sembol"])
            return False

        ayni_yon = sum(1 for t in acik if t.get("yon") == yon)
        if ayni_yon >= MAX_SAME_DIRECTION:
            log.info(f"[PAPER] {sonuc['sembol']} | Aynı yönde {ayni_yon}/"
                     f"{MAX_SAME_DIRECTION} pozisyon ({yon}) → ATLANDI "
                     f"(korelasyon riski)")
            _veto_kaydet("korelasyon", sonuc["sembol"])
            return False

        return True

    def _giris_fiyati(self, sonuc: dict, yon: str):
        """Giriş fiyatı = ANLIK fiyat. Çok kaçmışsa None (işlem iptal).

        ── v58 (K-31): BAYAT GİRİŞ FİYATI — ÖLÇÜLEN ZARAR ───────────
        K-16'da `son_close` KAPANMIŞ barın kapanışına çevrildi
        (göstergeler için doğru). Ama giriş fiyatı da ondan okunuyordu
        ve GÜNCELLENMEDİ. Öncesinde `son_close` zaten oluşan barın anlık
        fiyatıydı, bu yüzden sorun görünmüyordu.

        4h'de bu, girişin **4 saate kadar bayat** olması demek.

        ÖLÇÜLEN VAKA (paper #7, 2026-09-04 14:56 XRPUSDT):
            son kapanmış 4h bar kapanışı : 1.45070
            bot giriş fiyatı             : 1.45114   ← bayat
            o anki gerçek fiyat          : 1.39120   (%-4.13)
            SL 1.40440 → pozisyon **59 milisaniyede** stop, -%3.33
        Piyasada var olmayan bir fiyattan girilip anında stop olundu.

        ── AYRICA: PAPER ↔ CANLI EŞİTLİĞİ (§5.3) ────────────────────
        Canlı yol (v28, main.py) bunu ZATEN doğru yapıyordu:
          1. `futures_anlık_fiyat()` ile canlı fiyattan girer
          2. Fiyat sinyalin ALEYHİNE çok kaçtıysa işlemi İPTAL eder
             ("geç giriş — kovalama yapma")
        Paper'da ikisi de yoktu. Bu yüzden paper, canlının REDDEDECEĞİ
        işlemleri açıyordu — ölçüm canlıyı temsil etmiyordu.

        Eşik canlıyla aynı formül: taban + ATR'nin %15'i, tabanın 2
        katını geçmemek üzere.
        """
        sinyal_fiyat = float(sonuc.get("son_close") or 0)
        anlik = float(sonuc.get("anlik_fiyat") or 0) or sinyal_fiyat
        if sinyal_fiyat <= 0 or anlik <= 0:
            return sinyal_fiyat or None

        kayma_pct = abs(anlik - sinyal_fiyat) / sinyal_fiyat * 100
        aleyhte = ((yon == "LONG" and anlik > sinyal_fiyat) or
                   (yon == "SHORT" and anlik < sinyal_fiyat))
        atr_pct = (float(sonuc.get("son_atr", 0)) / sinyal_fiyat * 100) if sinyal_fiyat > 0 else 0
        # v58 (K-95): EŞİK ARTIK TEK KAYNAKTAN.
        # Burada formülün AYNISI ikinci kez yazılıydı (`min(taban+ATR*0.15,
        # taban*2)`) ve docstring "canlıyla aynı formül" diye SÖZ VERİYORDU.
        # Canlı taraf ATR-ölçekli tavana geçerken burası güncellenmeseydi
        # iki yol ayrışır, o söz sessizce yalan olurdu — §5.3'ün bu kod
        # tabanında defalarca kırıldığı desen (K-13, K-69, K-78, K-85, K-86).
        from engines.futures_trade_engine import giris_kayma_esigi
        esik = giris_kayma_esigi(atr_pct)

        if aleyhte and kayma_pct > esik:
            log.info(f"[PAPER] {sonuc.get('sembol')} GEÇ GİRİŞ İPTALİ: fiyat "
                     f"%{kayma_pct:.2f} aleyhe kaçtı (eşik %{esik:.2f}) — "
                     f"kovalama yapılmıyor (canlı yol da reddederdi)")
            _veto_kaydet("slippage_gec_giris", sonuc.get("sembol", ""))
            return None
        return anlik

    def _pozisyon_ac(self, sonuc: dict, yon: str, sig_id):
        """Pozisyon aç — Adaptive Sizing ile."""
        sembol = sonuc["sembol"]
        # v58 (K-31): ANLIK fiyattan gir; çok kaçmışsa hiç açma.
        sinyal_fiyat = self._giris_fiyati(sonuc, yon)
        if not sinyal_fiyat:
            return
        atr    = max(sonuc.get("son_atr", sinyal_fiyat * 0.01), sinyal_fiyat * 0.005)

        # v56: Giriş de slippage'a maruz — market emri sinyal fiyatından
        # değil, biraz aleyhte bir fiyattan dolar. SL/TP bundan SONRA,
        # gerçek giriş fiyatına göre hesaplanır: stop mesafesi girişe göre
        # ölçülmeli, yoksa risk/ödül oranı olduğundan farklı çıkar.
        fiyat = self._slippage_uygula(sinyal_fiyat, yon, giris_mi=True)

        # ── SL/TP hesapla ───────────────────────────────────
        # v57 KRİTİK DÜZELTME — paper ↔ canlı ayrışması (§5.3):
        #
        #   ESKİ KOD:
        #       if yon == "LONG":
        #           stop = risk.get("stop_loss") or (fiyat - atr*2)
        #       else:
        #           stop = fiyat + atr*2
        #
        #   ÜÇ AYRI SORUN vardı:
        #
        #   1) LONG ve SHORT stop'ları FARKLI KAYNAKTAN geliyordu.
        #      LONG, yukarıda hesaplanan `risk` sözlüğünü kullanıyordu;
        #      o da `risk_hesapla(son_close, son_atr)` ile ÜRETİLİYOR ve
        #      **yön parametresi almıyor** (core/sinyal_skor.py:181).
        #      Daha kötüsü: yukarıdaki `atr` değişkenine uygulanan
        #      **%0.5 tabanı** (`max(son_atr, fiyat*0.005)`) o yolda
        #      BYPASS ediliyordu.
        #      ÖLÇÜLEN SONUÇ (20 işlem): 8/8 LONG tabanı atladı, stop'lar
        #      %0.11'e kadar indi (ima edilen ATR: fiyatın %0.056'sı) ve
        #      **8 LONG işlemin 8'i de kaybetti**. Şanssızlık değil —
        #      piyasa gürültüsü o stop'u kesin vurur.
        #
        #   2) Çarpanlar canlıdan farklıydı: paper SL 2×ATR / TP 3×ATR,
        #      canlı SL 1.5×ATR / TP1 2.0×ATR. R/R bile uyuşmuyordu
        #      (paper 1.5:1, canlı 1.33:1).
        #
        #   3) Canlı rejime göre SL genişletiyor (VOLATILE ×1.3),
        #      paper hiç yapmıyordu.
        #
        #   ÇÖZÜM: Canlının KULLANDIĞI FONKSİYONU kullan. Böylece üç
        #   ayrım da kapanır ve gelecekte yeniden ayrışamazlar — tek
        #   kaynak, tek davranış.
        from engines.futures_trade_engine import sl_tp_hesapla, rr_yeterli_mi
        _rejim = sonuc.get("rejim", "RANGE")
        _sl_tp = sl_tp_hesapla(fiyat, yon, atr, _rejim)
        stop = _sl_tp["sl"]
        tp   = _sl_tp["tp1"]

        # v57: MİNİMUM R/R KAPISI — canlı yolla AYNI kontrol (§5.3).
        # VOLATILE rejimde çarpanlar R/R'ı 0.77'ye düşürüyor; o oranda
        # başabaş için %57 isabet gerekir. Ölçülen isabet %50 → matematiksel
        # olarak kayıp. Bu kapı olmadan sistem negatif beklentili işlem açar.
        if not rr_yeterli_mi(_sl_tp["rr"], sembol, _rejim):
            _veto_kaydet("rr_yetersiz", sembol)
            return

        # ── v14: Adaptive Sizing ────────────────────────────
        try:
            from engines.adaptive_sizing import get_adaptive_sizing
            atr_pct    = (atr / fiyat * 100) if fiyat > 0 else 1.0
            edge_score = float((sonuc.get("edge_sonuc") or {}).get("edge_score", 50))
            usdt_boyut = get_adaptive_sizing().hesapla(
                confidence  = sonuc.get("confidence", 60),
                rejim       = sonuc.get("rejim", "RANGE"),
                atr_pct     = atr_pct,
                ai_score    = sonuc.get("ai_score", 0),
                edge_score  = edge_score,
                bakiye      = self.bakiye,
            )
        except Exception:
            usdt_boyut = min(TRADE_USDT, self.bakiye * 0.20, self.bakiye - 5.0)

        # ── v58 (K-97): MTF ZAYIF HİZALAMA ÇARPANI ──────────
        # Canlı yol `_mtf_damp` ile hizalama_skoru==1 durumunda pozisyonu
        # %60'a indiriyor (main.py, "v19: MTF hizalama"). Paper bunu
        # uygulamazsa aynı sinyalde İKİ FARKLI BOYUT açılır — veto
        # zincirini eşitleyip boyutu ayrık bırakmak §5.3'ü yarım
        # kapatmak olurdu.
        _carpan = sonuc.get("_mtf_carpan", 1.0)
        if _carpan < 1.0:
            usdt_boyut *= _carpan
            log.info(f"[PAPER] {sembol} MTF zayıf hizalama → pozisyon "
                     f"×{_carpan:.2f} ({usdt_boyut:.2f}$)")

        if usdt_boyut < 5.0:
            log.warning(f"[PAPER] Bakiye çok düşük ({self.bakiye:.2f}), işlem atlandı")
            _veto_kaydet("bakiye_yetersiz", sembol)
            return

        miktar = round(usdt_boyut / fiyat, 6)
        if miktar <= 0:
            log.warning(f"[PAPER] {sembol} miktar 0'a yuvarlandı "
                        f"(usdt={usdt_boyut:.2f} fiyat={fiyat:.2f}) — işlem atlandı")
            _veto_kaydet("miktar_sifir", sembol)
            return

        # v56 DÜZELTME — BAKİYE SIZINTISI:
        # Eskiden bakiyeden yuvarlanmamış `usdt_boyut` düşülüyordu, ama
        # kapanışta `_kapat_ve_bakiye_guncelle` maliyeti YUVARLANMIŞ miktardan
        # (giris_fiyat * miktar) hesaplayıp iade ediyordu. Aradaki yuvarlama
        # farkı her işlemde sessizce bakiyeden siliniyor, PnL'de HİÇ görünmüyordu.
        #   20 USDT'lik BTC işleminde ~%0.145 kayıp → 1000 işlemde ~18 USDT.
        # Sonuç: `bakiye` ile `toplam_pnl` zamanla ayrışıyor ve paper sonuçları
        # sistematik olarak kötümser çıkıyordu — canlıya geçiş kararının
        # dayandığı sinyal bozuluyordu.
        # Artık borçlandırma ile iade AYNI değeri kullanıyor.
        # ── v58 (K-86): MARJİN MUHASEBESİ — notional DEĞİL ──────
        # Eskiden bakiyeden NOTIONAL'in tamamı düşülüyordu; bu SPOT
        # davranışıdır (varlığı satın alıp elde tutmak). Gerçek futures'ta
        # yalnızca MARJİN bağlanır:
        #     marjin = notional / kaldıraç
        # Canlı yol bunu zaten biliyor (futures_trade_engine.py:308
        # "Gerekli marjin = notional/kaldıraç"), paper bilmiyordu.
        #
        # Kaldıraç AYNI kaynaktan geliyor (`islem_kaldiraci`) — canlı
        # yolun kullandığı dinamik kaldıraç + rejim tavanı. Paper'da
        # `kaldirac=1` sabit koduydu; §5.3 ihlaliydi.
        #
        # ⚠️ PnL'in USDT tutarı DEĞİŞMEZ (notional üzerinden hesaplanır).
        # Kaldıracın değiştirdiği şey BAĞLANAN SERMAYE — yani aynı
        # bakiyeyle kaç pozisyon taşınabildiği ve tasfiye riski.
        from engines.futures_trade_engine import islem_kaldiraci, tasfiye_fiyati
        kaldirac = islem_kaldiraci(fiyat, atr, sembol)
        notional = fiyat * miktar
        marjin   = notional / max(1.0, float(kaldirac))
        self.bakiye -= marjin
        trade_id_db = trade_ac(
            sembol      = sembol,
            yon         = yon,
            giris_fiyat = fiyat,
            miktar      = miktar,
            stop_loss   = stop,
            take_profit = tp,
            mod         = "PAPER",
            signal_id   = sig_id,
            kaldirac    = kaldirac,
            marjin      = marjin,
            # v58 (K-87): giriş anındaki fonlama oranı saklanır; kapanışta
            # tutulan süreye göre maliyet hesaplanır.
            funding_rate= float((sonuc.get("market_data") or {}).get("funding_rate", 0) or 0),
            # v58 (K-88): tasfiye fiyatı açılışta hesaplanıp saklanır.
            tasfiye_fiyat = tasfiye_fiyati(fiyat, yon, kaldirac),
        )
        # v58 (K-66): açılış sayacı — /neden'in "açılma oranı" paydası.
        _islem_acildi_kaydet()
        log.info(
            f"[PAPER] {sembol} {yon} açıldı @ {fiyat:.4f} | "
            f"Miktar:{miktar} | SL:{stop:.4f} | TP:{tp:.4f} | "
            f"Notional:{notional:.2f}$ | Kaldıraç:{kaldirac}x | "
            f"Marjin:{marjin:.2f}$ | Kalan bakiye:{self.bakiye:.2f}$"
        )
        # ── v14: Trade Journal kaydı ──────────────────────
        try:
            import time as _t
            from engines.trade_journal import get_journal, TradeKayit
            atr_pct_j = (atr / fiyat * 100) if fiyat > 0 else 1.0
            edge_j    = sonuc.get("edge_sonuc") or {}
            kayit = TradeKayit(
                trade_id     = f"PAPER_{trade_id_db}_{sembol}",
                sembol       = sembol, yon=yon, mod="PAPER",
                giris_ts     = _t.time(), giris_fiyat=fiyat,
                # v58 (K-86): journal'a BAĞLANAN SERMAYE (marjin) yazılır.
                # Alan adı `maliyet_usdt` ama artık anlamı marjin —
                # notional yazmak bağlanan sermayeyi kaldıraç katı
                # fazla gösterirdi.
                miktar       = miktar, maliyet_usdt=marjin,
                rejim        = sonuc.get("rejim","?"),
                ai_score     = sonuc.get("ai_score",0),
                confidence   = sonuc.get("confidence",0),
                volatility   = round(atr_pct_j, 3),
                strateji     = sonuc.get("strateji","?"),
                mtf_skor     = int(sonuc.get("mtf_confluence",{}).get("skor",0)),
                funding_rate = float(sonuc.get("market_data",{}).get("funding_rate",0)),
                edge_score   = float(edge_j.get("edge_score",0)),
                sl=stop, tp1=tp, tp2=tp, kaldirac=1,
            )
            get_journal().trade_ac(kayit)
        except Exception: pass

    def sinyal_isle(self, sonuc: dict):
        sembol = sonuc["sembol"]
        karar  = sonuc["karar"]
        # v58 (K-31): Zıt-sinyal KAPANIŞI da anlık fiyattan olmalı.
        # `son_close` kapanmış barın kapanışıdır (K-16) ve 4h'de 4 saate
        # kadar bayattır; canlıda pozisyon o fiyattan değil, emrin
        # gittiği andaki fiyattan kapanır.
        fiyat  = float(sonuc.get("anlik_fiyat") or 0) or sonuc["son_close"]
        sig_id = sonuc.get("sig_id")

        aciklar       = acik_tradeler("PAPER")
        sembol_pozlar = [t for t in aciklar if t["sembol"] == sembol]
        is_buy  = "BUY" in karar or "AL"  in karar
        is_sell = "SELL" in karar or "SAT" in karar

        long_pozlar  = [t for t in sembol_pozlar if t.get("yon") == "LONG"]
        short_pozlar = [t for t in sembol_pozlar if t.get("yon") == "SHORT"]

        # ── Ters sinyalde kapat — v58 (K-A/K-B): EŞİĞE BAĞLI ──
        # Eskiden bu blok koşulsuzdu: karar metninde "BUY"/"SELL"
        # geçmesi yetiyordu. Açılış eşiğinin altındaki gürültü açık
        # pozisyonları kesiyordu (11/11 vaka). `_cikis_gecerli` artık
        # hem paper'ın hem canlının sinyal barını uyguluyor.
        zit_kapatildi = False
        if long_pozlar and is_sell and self._cikis_gecerli(sonuc, "LONG"):
            for trade in long_pozlar:
                self._kapat_ve_bakiye_guncelle(trade, fiyat, "SELL_SİNYALİ")
            zit_kapatildi = True

        if short_pozlar and is_buy and self._cikis_gecerli(sonuc, "SHORT"):
            for trade in short_pozlar:
                self._kapat_ve_bakiye_guncelle(trade, fiyat, "BUY_SİNYALİ")
            zit_kapatildi = True

        # Aynı yönde zaten pozisyon varsa açma
        # v48 optimizasyon: yukarıda çekilen listeler yeniden kullanılır
        # (BUY sadece SHORT kapatır → LONG listesi hâlâ geçerli, tersi de öyle).
        # Eski kod burada 2 ek DB sorgusu yapıyordu.
        if is_buy and long_pozlar:
            return
        if is_sell and short_pozlar:
            return

        # ── v58 (K-A yan etkisi): ZIT POZİSYON HÂLÂ AÇIKSA AÇMA ──
        # Kapatma artık eşiğe bağlı, yani BAŞARISIZ olabiliyor. O durumda
        # devam edilirse aynı sembolde ters yönde İKİNCİ pozisyon açılır
        # (hedge) — bu sistem tek yönlü çalışıyor, öyle bir durum yok.
        # Canlı yol bu riski taşımıyor: `sinyal_gecerli_mi` başarısızsa
        # `_execution_isle` komple `return` ediyor, ne kapatıyor ne açıyor.
        # Paper'ın da aynı şekilde davranması gerekir (§5.3).
        # NOT: MAX_OPEN_POSITIONS=1 bugün bunu zaten engelliyor ama bu
        # tesadüfi koruma — limit yükseltilirse sessizce kaybolurdu.
        # `zit_kapatildi` ŞART: long_pozlar/short_pozlar kapatma ÖNCESİ
        # listelerdir. Kapatma başarılıysa bayatlarlar ve bu koşul meşru
        # dönüşü de engellerdi.
        if not zit_kapatildi and ((is_buy and short_pozlar) or (is_sell and long_pozlar)):
            log.info(f"[PAPER] {sembol} | zıt pozisyon kapatılamadı "
                     f"(sinyal eşiği) → yeni pozisyon da AÇILMADI")
            return

        # Yeni pozisyon aç
        if is_buy:
            if self._filtre_gec(sonuc, "LONG"):
                self._pozisyon_ac(sonuc, "LONG", sig_id)
        elif is_sell and SHORT_ENABLED:
            if self._filtre_gec(sonuc, "SHORT"):
                self._pozisyon_ac(sonuc, "SHORT", sig_id)

    def _kapat_ve_bakiye_guncelle(self, trade: dict, fiyat: float, sebep: str):
        """Pozisyonu kapat, bakiyeyi güncelle, dashboard ve event bus'a bildir."""
        giris  = float(trade.get("giris_fiyat", 0) or 0)
        miktar = float(trade.get("miktar", 0) or 0)
        yon    = trade.get("yon", "LONG")
        sembol = trade.get("sembol", "")

        # ── v56: İŞLEM MALİYETİ MODELLEMESİ ──────────────────
        # Eskiden paper trading komisyon ve slippage'ı HİÇ modellemiyordu
        # (backtest_engine ikisini de modelliyor — tutarsızlık).
        # Sonuç: paper sonuçları sistematik olarak İYİMSER çıkıyor, canlıya
        # geçince aynı strateji daha kötü görünüyor ve kullanıcı "strateji
        # bozuldu" sanıyordu. Oysa fark yalnızca modellenmemiş maliyetti.
        # CANLI_GECIS_PROTOKOLU paper↔canlı karşılaştırmasına dayandığı için
        # bu boşluk doğrudan yanlış "canlıya geç" kararına yol açabilirdi.
        # Round-trip maliyet ≈ %0.08 (taker×2) + slippage.
        cikis_exec = self._slippage_uygula(fiyat, yon, giris_mi=False)

        pnl_brut = ((cikis_exec - giris) * miktar if yon == "LONG"
                    else (giris - cikis_exec) * miktar)
        maliyet  = giris * miktar
        # Komisyon: giriş + çıkış notional üzerinden
        komisyon = (maliyet + cikis_exec * miktar) * PAPER_KOMISYON

        # ── v58 (K-87): FONLAMA (funding) MALİYETİ ──────────────
        # Perpetual futures 8 saatte bir fonlama öder/alır. Paper bunu
        # HİÇ modellemiyordu — komisyon (K-42) modelleniyordu ama fonlama
        # unutulmuştu. K-85 ile pozisyonlar 24 saate kadar tutuluyor,
        # yani 3 fonlama dönemi.
        #
        # ÖLÇÜLEN GERÇEK ORANLAR (2026-09-13, Binance premiumIndex):
        #     BTC %0.0032 · ETH %0.0039 · ZEC %0.0057 · FET %0.0100 (8 saatte)
        #     SOL %-0.0033  → NEGATİF oranda SHORT öder, LONG alır
        #
        # İŞARET: LONG pozitif oranda ÖDER, SHORT ALIR.
        #
        # ⚠️ YAKLAŞIKLIK, bilerek: gerçekte her 8 saatlik sınırda O ANKİ
        # oran üzerinden kesilir. Burada GİRİŞ anındaki oran tutulan süreye
        # oranlanıyor. Oranlar gün içinde değiştiği için tam değil — ama
        # SIFIR saymaktan (eski davranış) çok daha gerçekçi ve sistematik
        # olarak iyimser tarafa kaçmıyor.
        funding_maliyet = 0.0
        try:
            _fr = float(trade.get("funding_rate") or 0)
            if _fr:
                from datetime import datetime as _dt
                _ts = trade.get("ts_ac")
                _saat = 0.0
                if _ts:
                    _a = _dt.fromisoformat(str(_ts))
                    if _a.tzinfo is not None:
                        _a = _a.replace(tzinfo=None)
                    _saat = max(0.0, (_dt.utcnow() - _a).total_seconds() / 3600.0)
                _donem = _saat / 8.0
                _isaret = 1.0 if yon == "LONG" else -1.0
                funding_maliyet = maliyet * _fr * _donem * _isaret
        except Exception as _f_e:
            # §5.2: sessizce sıfır saymak "fonlama yok" demektir — görünür olsun.
            log.warning(f"[PAPER] {sembol} fonlama maliyeti hesaplanamadı: "
                        f"{type(_f_e).__name__}: {_f_e}")
        # v56: PnL TEK noktada yuvarlanır ve bu değer hem bakiyeye hem DB'ye
        # gider. Aksi halde DB round(pnl,4), bakiye tam hassasiyet kullanıyor
        # ve toplam_pnl() ile bakiye yavaşça ayrışıyordu.
        # v58 (K-87): fonlama da net PnL'e dahil — komisyon gibi.
        pnl      = round(pnl_brut - komisyon - funding_maliyet, 4)

        # ── v58 (K-86): İADE MARJİN ÜZERİNDEN ───────────────
        # Açılışta bakiyeden marjin düşüldü; kapanışta marjin + PnL
        # iade edilir. Eskiden notional düşülüp notional+PnL iade
        # ediliyordu (spot davranışı).
        #
        # `marjin` kayıttan okunur — kaldıraç ayarı sonradan değişse
        # bile bu pozisyonun iadesi AÇILIŞTAKİ marjinle hesaplanır.
        # Eski kayıtlarda alan yoksa notional'a düşülür (kaldıraç 1x
        # döneminde açılmış pozisyonlar doğru kapanır).
        marjin = trade.get("marjin")
        if not marjin or marjin <= 0:
            marjin = maliyet
        # ⚠️ pnl_yuzde NOTIONAL üzerinden kalır. `karar_kurali.py`
        # beklentiyi bu alandan hesaplıyor ve %0.10 eşiği kaldıraçsız
        # getiriye göre yazıldı; tabanı marjine çevirmek eşiği sessizce
        # kaldıraç katı kadar kolaylaştırır ve protokolü geçersiz kılar.
        # v58 (K-88): TASFİYEDE zarar MARJİNLE SINIRLIDIR.
        # Borsa pozisyonu kapatır ve marjinin tamamı gider; bakiyeye
        # iade olmaz. Hesaplanan PnL marjinden daha kötüyse marjine
        # kırpılır — gerçekte bakiyenin eksiye düşmesi (borç) izole
        # marjinde OLMAZ.
        if sebep == "TASFIYE" and pnl < -marjin:
            log.critical(f"[PAPER] {sembol} tasfiye: hesaplanan zarar "
                         f"{pnl:.4f} marjini ({marjin:.4f}) aşıyor → "
                         f"marjine kırpıldı")
            pnl = round(-marjin, 4)
        pnl_pct = (pnl / maliyet * 100) if maliyet > 0 else 0
        geri_gelen = marjin + pnl

        # v56: NET PnL (komisyon düşülmüş) DB'ye de yazılır — aksi halde
        # toplam_pnl() brüt, bakiye net tutar ve ikisi birbirinden sapar.
        # v58 (K-42): komisyon artık DB'ye de yazılıyor — öncesinde
        # yalnızca PnL'den düşülüyor ve kayboluyordu.
        trade_kapat(trade["id"], cikis_exec, sebep,
                    pnl=pnl, pnl_yuzde=round(pnl_pct, 4),
                    komisyon=komisyon, funding_maliyet=funding_maliyet)
        # v58 (K-59): `max(geri_gelen, 0)` sessizce para YARATIYORDU —
        # zarar pozisyon maliyetini aşarsa (kaldıraç/gap) fark bakiyeye
        # eklenmiyor ama eksilmiyordu da. 1x kaldıraçta oluşmaz, ama
        # sessiz bir muhasebe kaçağı olarak duruyordu.
        if geri_gelen < 0:
            log.warning(f"[PAPER] {sembol} kapanışında iade NEGATİF "
                        f"({geri_gelen:.4f}$) — zarar pozisyon maliyetini "
                        f"aştı. Bakiyeye gerçek değer yansıtılıyor.")
        self.bakiye += geri_gelen
        log.info(
            f"[PAPER] {sembol} {yon} kapatıldı @ {cikis_exec:.4f} | "
            f"PnL:{pnl:+.4f}$ (%{pnl_pct:+.2f}) | "
            f"komisyon:{komisyon:.4f}$ | Bakiye:{self.bakiye:.2f}$"
        )
        fiyat = cikis_exec   # aşağıdaki bildirimler gerçek çıkış fiyatını kullansın

        # ── v58 (K-32): DOĞRUDAN DASHBOARD BİLDİRİMİ KALDIRILDI ──
        # Burada hem `pozisyon_kapandi_bildir()` çağrılıyor HEM DE aşağıda
        # event bus'a POSITION_CLOSED yayınlanıyordu. `main.py`'deki
        # `_on_position_closed` dinleyicisi de aynı fonksiyonu çağırıyor
        # → her paper kapanışı dashboard'a İKİ KEZ bildiriliyordu.
        #
        # ÖLÇÜLEN (2026-09-05, canlı panel):
        #   kapanan_islemler: BNBUSDT TP · BNBUSDT TP · BTCUSDT STOP
        #   bot_istatistik  : 3 işlem, 2 kazanan, %66.7
        #   GERÇEK (DB)     : 2 işlem, 1 kazanan, %50.0
        # Telegram DB'den okuduğu için doğruydu; panel şişiyordu.
        #
        # Event yükü dashboard'ın ihtiyacı olan TÜM alanları taşıyor
        # (sembol/yon/giris/cikis/pnl_usdt/pnl_pct/sebep/miktar), yani
        # tek kaynak olarak event bus yeterli. Canlı yol da aynı olaydan
        # geçiyor — böylece iki mod tek yoldan raporlanıyor.

        # ── Event bus'a bildir (dashboard buradan haber alır) ──
        try:
            from engines.event_bus import get_bus, Event
            get_bus().publish(Event.POSITION_CLOSED, {
                "sembol": sembol, "yon": yon,
                "pnl_pct": round(pnl_pct, 3),
                "pnl_usdt": round(pnl, 4),
                "sebep": sebep,
                "giris": giris, "cikis": fiyat, "miktar": miktar,
            }, "PaperTrader")
        except Exception: pass
        # v14: Journal + Kill switch + Adaptive sizing bildir
        try:
            from engines.trade_journal import get_journal
            get_journal().trade_kapat(
                f"PAPER_{trade['id']}_{sembol}",
                fiyat, sebep, round(pnl,4),
                round(pnl/maliyet*100,3) if maliyet>0 else 0
            )
        except Exception: pass
        try:
            from engines.kill_switch import get_kill_switch
            get_kill_switch().trade_sonucu_bildir(pnl > 0, pnl)
        except Exception: pass
        try:
            from engines.adaptive_sizing import get_adaptive_sizing
            get_adaptive_sizing().sonuc_bildir(pnl > 0)
        except Exception: pass

    def stop_tp_kontrol(self, sembol: str, guncel_fiyat: float):
        """SL/TP kontrolü — tetiklenince bakiyeyi de güncelle.

        v57 KRİTİK (paper ↔ canlı eşitliği, DEVAM_NOTLARI §5.3):
          Eskiden pozisyon `guncel_fiyat`tan kapatılıyordu. Ama canlıda SL,
          borsada DURAN bir `STOP_MARKET` emridir: fiyat seviyeye DEĞDİĞİ
          anda tetiklenir ve stop seviyesine yakın dolar — bot kapalı olsa
          bile. TP ise limit emri, TP seviyesinden dolar (daha iyisinden
          değil).

          `guncel_fiyat` kullanmak iki tarafı da abartıyordu:
            - SL: kontrol anına kadarki TÜM aleyhte hareket zarar yazılıyordu
            - TP: seviyeyi aşan lehte hareket kâr yazılıyordu

          Ölçülen vaka (2026-08-23): BNBUSDT SHORT giriş 678.4264, SL
          685.2127. Bot 2 gün 8 saat kapalı kaldı (v57 K-3), fiyat 700.06'ya
          çıktı ve zarar **%3.27** yazıldı — olması gereken ≈%1.09'un
          3 KATI. 100 işlemlik veri seti bu şekilde sistematik olarak
          kötümser oluyordu ve canlıya geçiş kararı buna dayanıyor.

          Artık tetikleyen SEVİYEDEN kapatılıyor; `_kapat_ve_bakiye_guncelle`
          üzerine ALEYHTE slippage uyguluyor (canlıdaki dolum kaymasının
          karşılığı).

          NOT: Gerçek bir fiyat boşluğunda (gap) canlı dolum stop'tan daha
          kötü olabilir. Bu model onu yakalamaz — yani hafif iyimser. Ama
          `guncel_fiyat` modelinin sınırsız kötümserliğinden çok daha
          gerçekçi. Bot kesintisi ne kadar uzarsa eski model o kadar
          saçmalıyordu.
        """
        aciklar = [t for t in acik_tradeler("PAPER") if t["sembol"] == sembol]
        for trade in aciklar:
            yon = trade.get("yon", "LONG")
            sl  = trade.get("stop_loss")
            tp  = trade.get("take_profit")

            tetiklendi = False
            sebep = ""
            tetik_fiyat = guncel_fiyat        # dolumun baz alacağı fiyat
            if yon == "LONG":
                if sl and guncel_fiyat <= sl:
                    tetiklendi = True; sebep = "STOP"; tetik_fiyat = sl
                elif tp and guncel_fiyat >= tp:
                    tetiklendi = True; sebep = "TP";   tetik_fiyat = tp
            else:
                if sl and guncel_fiyat >= sl:
                    tetiklendi = True; sebep = "STOP"; tetik_fiyat = sl
                elif tp and guncel_fiyat <= tp:
                    tetiklendi = True; sebep = "TP";   tetik_fiyat = tp

            # ── v58 (K-88): TASFİYE — SON ÇARE ───────────────────
            # SL/TP tetiklenmediyse tasfiye seviyesine bakılır.
            #
            # ⚠️ SIRA: SL/TP ÖNCE. Tasfiye HER ZAMAN SL'den UZAKTADIR
            # (3x → %32.9, SL %3-5), yani normal işleyişte SL önce dolar
            # ve buraya hiç gelinmez. Tasfiye, SL'in dolmadığı durumun
            # (fiyat boşluğu) karşılığıdır.
            #
            # ⚠️ ZARAR MARJİNLE SINIRLI: tasfiyede pozisyonun tamamı
            # kaybedilir — bakiyeye İADE YOKTUR. K-59'da "zarar pozisyon
            # maliyetini aşarsa" diye bırakılan uyarının gerçek karşılığı
            # budur; artık sessiz bir muhasebe kaçağı değil, modellenmiş
            # bir sonuç.
            if not tetiklendi:
                _tf = trade.get("tasfiye_fiyat")
                if _tf and float(_tf) > 0:
                    _tf = float(_tf)
                    _vurdu = (guncel_fiyat <= _tf) if yon == "LONG" else (guncel_fiyat >= _tf)
                    if _vurdu:
                        tetiklendi = True
                        sebep = "TASFIYE"
                        tetik_fiyat = _tf
                        log.critical(
                            f"[PAPER] {sembol} {yon} TASFİYE! fiyat {guncel_fiyat:.6f} "
                            f"tasfiye seviyesi {_tf:.6f} — marjinin TAMAMI kaybedildi")

            # ── v58 (K-85): ZAMAN STOP ───────────────────────────
            # SL/TP tetiklenmediyse süreye bak. Kural ORTAK fonksiyonda
            # (`zaman_stop_doldu_mu`) — canlı yol da aynısını çağırıyor,
            # §5.3 gereği ikisi ayrışmamalı.
            #
            # ⚠️ SIRA ÖNEMLİ: SL/TP ÖNCE kontrol edilir. Fiyat stop
            # seviyesindeyse gerçekte stop dolmuştur; zaman stop onu
            # ezerse zarar yanlış fiyattan yazılır.
            #
            # ⚠️ DOLUM FİYATI FARKLI: SL/TP seviyeden dolar (borsada duran
            # emir), zaman stop ise botun PİYASA emriyle kapatmasıdır —
            # bu yüzden `guncel_fiyat` kullanılır, seviye değil.
            if not tetiklendi:
                try:
                    from engines.futures_trade_engine import zaman_stop_doldu_mu
                    _doldu, _saat = zaman_stop_doldu_mu(trade.get("ts_ac"))
                    if _doldu:
                        tetiklendi = True
                        sebep = "ZAMAN_STOP"
                        tetik_fiyat = guncel_fiyat
                        log.info(f"[PAPER] {sembol} {yon} ZAMAN STOP — "
                                 f"{_saat:.1f} saattir açık, model ufku aşıldı")
                except Exception as _zs_e:
                    log.warning(f"[PAPER] {sembol} zaman stop kontrolü "
                                f"başarısız: {_zs_e}")

            if tetiklendi:
                self._kapat_ve_bakiye_guncelle(trade, tetik_fiyat, sebep)

    def para_dokumu(self) -> dict:
        """v58 (K-42): paranın nereye gittiğinin AYRINTILI dökümü.

        Öncesinde yalnızca tek bir "bakiye" rakamı vardı; komisyonun ne
        kadar yediği görünmüyordu ve DB'de saklanmadığı için geriye
        dönük hesaplanamıyordu da.

        `brut_pnl = gerceklesen_pnl + odenen_komisyon` özdeşliği raporun
        kendi iç tutarlılık kontrolüdür. Tutmuyorsa muhasebe kaçağı var —
        bu kod tabanında daha önce oldu (v56: bakiye net, DB brüt tutuyordu
        ve ikisi yavaşça ayrışıyordu).
        """
        from data.database import baglanti
        net = kom = fon = 0.0
        n_top = n_kom = 0
        try:
            with baglanti() as conn:
                # v58 (K-87): fonlama da toplanıyor — aksi halde aşağıdaki
                # `brut = net + kom` özdeşliği fonlama kadar SAPARDI ve
                # raporun kendi iç tutarlılık kontrolü sahte kaçak gösterirdi.
                r = conn.execute(
                    "SELECT COALESCE(SUM(pnl),0), COALESCE(SUM(komisyon),0), "
                    "COUNT(*), COUNT(komisyon), "
                    "COALESCE(SUM(funding_maliyet),0) FROM trades "
                    "WHERE mod='PAPER' AND durum!='ACIK'").fetchone()
                net, kom = float(r[0]), float(r[1])
                n_top, n_kom = int(r[2]), int(r[3])
                fon = float(r[4])
        except Exception as e:
            # fail-loud (§5.2): sessizce sıfır göstermek "komisyon yok"
            # diye okunur ve tam da ölçmek istediğimiz şeyi gizler.
            log.error(f"[PARA DÖKÜMÜ] okunamadı: {type(e).__name__}: {e}")
            return {"hata": str(e)}

        aciklar = acik_tradeler("PAPER")
        # v58 (K-86): BAĞLI SERMAYE = MARJİN, notional değil. Gerçek
        # futures'ta pozisyon notional'ı değil marjini bağlar; notional
        # yazmak "toplam varlık"ı olduğundan düşük gösterirdi.
        def _bagli_tutar(t):
            m = t.get("marjin")
            if m and float(m) > 0:
                return float(m)
            return float(t.get("giris_fiyat") or 0) * float(t.get("miktar") or 0)
        bagli = sum(_bagli_tutar(t) for t in aciklar)
        # v58 (K-87): özdeşlik artık fonlamayı da içeriyor.
        #   brut = net + komisyon + fonlama
        brut = net + kom + fon
        return {
            "baslangic":         round(self.baslangic, 2),
            "nakit":             round(self.bakiye, 2),
            "bagli_sermaye":     round(bagli, 2),
            "toplam_varlik":     round(self.bakiye + bagli, 2),
            "gerceklesen_pnl":   round(net, 4),
            "odenen_komisyon":   round(kom, 4),
            "odenen_fonlama":    round(fon, 4),
            "brut_pnl":          round(brut, 4),
            "komisyon_payi_pct": (round(kom / abs(brut) * 100, 1)
                                  if abs(brut) > 1e-9 else 0.0),
            "kapanan_islem":     n_top,
            "komisyonu_bilinen": n_kom,      # K-42 öncesi kayıtlarda NULL
            "acik_pozisyon":     len(aciklar),
        }

    def durum_raporu(self) -> dict:
        aciklar    = acik_tradeler("PAPER")
        istatistik = win_rate_hesapla("PAPER")
        pnl        = toplam_pnl("PAPER")
        return {
            "bakiye":        round(self.bakiye, 2),
            "baslangic":     self.baslangic,
            "toplam_pnl":    pnl,
            "pnl_yuzde":     round(pnl / self.baslangic * 100, 2) if self.baslangic else 0,
            "acik_pozisyon": len(aciklar),
            "aciklar":       aciklar,
            "istatistik":    istatistik,
            "para":          self.para_dokumu(),      # v58 K-42
        }

    def rapor_str(self) -> str:
        d   = self.durum_raporu()
        ist = d["istatistik"]
        return (
            f"📋 <b>PAPER TRADING RAPORU v13</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Bakiye      : {d['bakiye']:,.2f} USDT\n"
            f"📈 Toplam PnL  : {d['toplam_pnl']:+.4f} USDT\n"
            f"📊 PnL %       : {d['pnl_yuzde']:+.2f}%\n"
            f"🔢 Toplam İşlem: {ist.get('toplam', 0)}\n"
            f"✅ Kazanan     : {ist.get('kazanan', 0)}\n"
            f"❌ Kaybeden    : {ist.get('kaybeden', 0)}\n"
            f"🎯 Win Rate    : %{ist.get('win_rate', 0)}\n"
            f"📂 Açık Poz.   : {d['acik_pozisyon']}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            # v58 (K-42): PARA DÖKÜMÜ. Tek bir "bakiye" rakamı komisyonun
            # ne kadar yediğini gizliyordu. Brüt = net + komisyon özdeşliği
            # aynı zamanda muhasebe tutarlılık kontrolüdür.
            f"{_para_blogu(d.get('para', {}))}"
            f"⚙️  Min BUY skor : {MIN_AI_SCORE_BUY}\n"
            f"⚙️  Min güven    : %{MIN_CONFIDENCE}\n"
            f"⚙️  Pozisyon     : {TRADE_USDT} USDT sabit\n"
        )
