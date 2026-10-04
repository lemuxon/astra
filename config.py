# =========================================================
# ASTRA AI TRADER — MASTER CONFIG
# =========================================================
import os
from dotenv import load_dotenv
load_dotenv()

# ── Sürüm (tek kaynak — her yerde bunu kullan) ────────────
ASTRA_VERSION = "v55.0"
ASTRA_SURUM_ETIKET = f"ASTRA {ASTRA_VERSION} PRODUCTION"

# ── Telegram ──────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID   = os.getenv("CHAT_ID", "")

# ── Binance ───────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_BASE_URL   = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
FUTURES_BASE_URL   = os.getenv("FUTURES_BASE_URL", "https://fapi.binance.com")

# ── v58 (K-15): PİYASA VERİSİ ≠ İŞLEM BORSASI ─────────────
# NEDEN VAR — ölçülen vaka (2026-09-02, paper işlemi #21):
#   Bot SOLUSDT'yi 99.89'dan SHORT açtı. O anki 5m barlar:
#       TESTNET  O=98.79  H=99.94  C=98.47
#       GERÇEK   O=98.55  H=98.63  C=98.47
#   Testnet'te GERÇEK PİYASADA OLMAYAN bir sıçrama vardı (99.94).
#   Bot henüz kapanmamış bara baktığı için o anki "close" 99.92'ydi.
#   TP 99.14 zaten piyasanın altında kaldı → 2.9 dakikada "TP" oldu ve
#   +%0.64 yazıldı. 21 işlemlik veri setindeki 5 kazançtan biri, gerçek
#   piyasada hiç var olmayan bir fiyattan geliyordu.
#
#   Fiyat BAYAT DEĞİLDİ — tazeydi ama testnet'e özgüydü. Testnet spot
#   likiditesi ince olduğu için tek bir test emri fiyatı %1.5 oynatıyor.
#   Ölçüm: sinyallerin %2.3'ü gerçek piyasadan >%0.5, %0.54'ü >%1 sapıyor.
#
# ÇÖZÜM: Halka açık PİYASA VERİSİ her zaman gerçek borsadan okunur;
#   hesap/emir işlemleri BINANCE_BASE_URL'de kalır. Klines ve ticker
#   anahtar gerektirmez, yani bu ek bir risk getirmez.
#
# ⚠️ `exchangeInfo` BİLEREK bunun DIŞINDA: o, emrin gönderileceği
#   borsanın kurallarıdır (min_notional, lot adımı). Testnet'te emir
#   verirken gerçek borsanın filtrelerini kullanmak yanlış olurdu.
BINANCE_DATA_URL   = os.getenv("BINANCE_DATA_URL", "https://api.binance.com")
# v35: Testnet otomatik tespiti — bazı endpoint'ler (allForceOrders, L/S ratio)
# testnet'te 400/boş döner; testnet'teyken bunları atlayıp gereksiz hata logunu önle.
IS_TESTNET = "testnet" in FUTURES_BASE_URL.lower() or "testnet" in BINANCE_BASE_URL.lower()
# Testnet için backup = aynı testnet URL; mainnet için fapi2.binance.com
BACKUP_FUTURES_URL = os.getenv("BACKUP_FUTURES_URL", FUTURES_BASE_URL)
EXCHANGE_TIMEOUT   = int(os.getenv("EXCHANGE_TIMEOUT", "8"))
FAILOVER_ENABLED   = os.getenv("FAILOVER_ENABLED", "true").lower() == "true"

# ── Kaldıraç ──────────────────────────────────────────────
FUTURES_LEVERAGE         = int(os.getenv("FUTURES_LEVERAGE", "5"))
FUTURES_MARGIN_TYPE      = os.getenv("FUTURES_MARGIN_TYPE", "ISOLATED")
FUTURES_DYNAMIC_LEVERAGE = os.getenv("FUTURES_DYNAMIC_LEVERAGE", "true").lower() == "true"
FUTURES_LEVERAGE_MIN     = int(os.getenv("FUTURES_LEVERAGE_MIN", "2"))
FUTURES_LEVERAGE_MAX     = int(os.getenv("FUTURES_LEVERAGE_MAX", "10"))

# ── SL / TP ───────────────────────────────────────────────
FUTURES_SL_ATR_MULT      = float(os.getenv("FUTURES_SL_ATR_MULT", "1.5"))
FUTURES_TP_ATR_MULT      = float(os.getenv("FUTURES_TP_ATR_MULT", "2.0"))
FUTURES_TP2_ATR_MULT     = float(os.getenv("FUTURES_TP2_ATR_MULT", "3.5"))
FUTURES_PARTIAL_TP       = os.getenv("FUTURES_PARTIAL_TP", "true").lower() == "true"
FUTURES_PARTIAL_TP_PCT   = float(os.getenv("FUTURES_PARTIAL_TP_PCT", "50"))
FUTURES_TRAILING_STOP    = os.getenv("FUTURES_TRAILING_STOP", "true").lower() == "true"
FUTURES_TRAILING_CALLBACK= float(os.getenv("FUTURES_TRAILING_CALLBACK", "1.5"))

# ── Risk ──────────────────────────────────────────────────
BALANCE              = float(os.getenv("BALANCE", "10000"))
RISK_PERCENT         = float(os.getenv("RISK_PERCENT", "0.015"))
TRADE_USDT           = float(os.getenv("TRADE_USDT", "20"))
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "4.0"))
# ── v58 (K-80): EŞZAMANLI POZİSYON TAVANI 3 → 10 (kullanıcı kararı) ──
# AMAÇ: 100 işlemlik örnekleme daha hızlı ulaşmak.
#
# ÖLÇÜLEN DARBOĞAZ (2026-09-10, §0.27): işlem hızının tavanını coin
# sayısı DEĞİL, slot sayısı × tutuş süresi belirliyor:
#     ortalama tutuş 13.6 saat
#     3 slot  → 3 × 24 / 13.6 = 5.3 işlem/gün → 100 işlem 19 gün
#    10 slot  → 17.6 işlem/gün                → 100 işlem  6 gün
# 5 → 50 coine çıkmak bu tavanı değiştirmemişti; 3 slot doluyken
# 50. coinin sinyali de reddediliyordu.
#
# ⚠️ MAX_SAME_DIRECTION DE ÖLÇEKLENMELİ, YOKSA 10 ANLAMSIZ:
# Eski değer 2 idi. 10 slot + aynı yönde 2 tavanı = pratikte en fazla
# 2 LONG + 2 SHORT = 4 pozisyon. Yani slot artışı sessizce yutulurdu.
# (Ölçüm: 5 coinli dönemde "Aynı yönde 2/2 → ATLANDI" günde 130 kez
#  tetiklenmiş, en baskın red sebebiydi.)
#
# Yeni değer MEVCUT RİSK ORANINI KORUYARAK ölçeklendi: 2/3 ≈ %67,
# 10 × %67 ≈ 7. Yani yeni bir risk iştahı icat edilmedi, var olan
# oran büyütüldü. Amacı korelasyon riski: kripto yüksek korelasyonlu,
# 10 LONG tek bir yönlü bahistir; piyasa düşerse hepsi birlikte stop olur.
#
# SERMAYE ETKİSİ (bind etmiyor): pozisyon boyutu
#   min(TRADE_USDT=60, bakiye*0.20, bakiye-5) = 60 USDT sabit
#   10 × 60 = 600 USDT / 10000 bakiye = %6  (MAX_MARGIN_PCT=50 çok uzak)
#
# ⚠️ §5.3: davranış değişikliği — eldeki paper örneklemi geçersiz.
MAX_OPEN_POSITIONS   = int(os.getenv("MAX_OPEN_POSITIONS", "10"))
MAX_SAME_DIRECTION   = int(os.getenv("MAX_SAME_DIRECTION", "7"))
MAX_MARGIN_PCT       = float(os.getenv("MAX_MARGIN_PCT", "50.0"))
DRAWDOWN_REDUCE_THRESHOLD = float(os.getenv("DRAWDOWN_REDUCE_THRESHOLD", "10.0"))
LIQUIDATION_BUFFER_PCT    = float(os.getenv("LIQUIDATION_BUFFER_PCT", "20.0"))

# ── Fill / Execution ──────────────────────────────────────
FILL_VERIFY_TIMEOUT  = int(os.getenv("FILL_VERIFY_TIMEOUT", "30"))
FILL_VERIFY_INTERVAL = float(os.getenv("FILL_VERIFY_INTERVAL", "2"))
ORPHAN_CHECK_INTERVAL= int(os.getenv("ORPHAN_CHECK_INTERVAL", "300"))
MAX_SLIPPAGE_PCT     = float(os.getenv("MAX_SLIPPAGE_PCT", "0.3"))
SLIPPAGE_WARN_PCT    = float(os.getenv("SLIPPAGE_WARN_PCT", "0.15"))

# ── Monte Carlo ───────────────────────────────────────────
MC_SIMULATIONS   = int(os.getenv("MC_SIMULATIONS", "10000"))
MC_CONFIDENCE    = float(os.getenv("MC_CONFIDENCE", "0.95"))
MC_LOOKBACK_DAYS = int(os.getenv("MC_LOOKBACK_DAYS", "30"))

# ── Coins & Tarama ────────────────────────────────────────
COINS        = os.getenv("COINS","BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT").split(",")
SCAN_INTERVAL= int(os.getenv("SCAN_INTERVAL", "60"))

# ── v58 (K-73): BAR BAŞINA BİR AĞIR ANALİZ ─────────────────────
# ÖLÇÜLEN UYUMSUZLUK: ANA_BAR_DK=240 (4 saat = 14400 sn) iken
# SCAN_INTERVAL=60 sn. Yani her KAPANMIŞ bar için 240 kez tam analiz
# yapılıyordu. K-16'dan beri göstergeler kapanmış bardan hesaplandığı
# için bu 240 analizin sonucu AYNI; yalnızca model sürümü ve online
# blend değiştiği için rakamlar oynuyordu.
#
# Yan zararları ölçüldü (2026-09-10, tek gün, 5 coin):
#   • HTTP 418 (IP ban)      : 279 kez, her biri 300 sn bekletiyor
#   • sahte rejim değişimi   : 3446 (K-71)
#   • Telegram mesajı        : 2303 (K-72)
#   • model sürümü           : ~378/gün, 1.33 GB/gün (K-39)
#
# Not: yeniden giriş beklemesi 4h'e göre GÜNCELLENMİŞTİ
# (YENIDEN_GIRIS_BEKLEME_SN=14400); tarama aralığı unutulmuştu.
#
# Açıkken: ağır analiz bar başına BİR kez; aradaki turlarda yalnızca
# ANLIK FİYAT tazelenir (SL/TP kontrolü bundan besleniyor, o yüzden
# sık olmalı). Kapatmak için BAR_ONBELLEK=false.
BAR_ONBELLEK = os.getenv("BAR_ONBELLEK", "true").lower() == "true"
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
SHORT_ENABLED= os.getenv("SHORT_ENABLED", "true").lower() == "true"

# ── Sinyal Filtreleri ─────────────────────────────────────
MIN_AI_SCORE_BUY       = int(os.getenv("MIN_AI_SCORE_BUY", "4"))
MIN_AI_SCORE_SELL      = int(os.getenv("MIN_AI_SCORE_SELL", "-4"))
MIN_CONFIDENCE         = int(os.getenv("MIN_CONFIDENCE", "62"))
REGIME_TREND_MIN_AI    = int(os.getenv("REGIME_TREND_MIN_AI", "3"))
# ── v58 (K-77): RANGE EŞİĞİ 5 → 4 (kullanıcı kararı) ───────────
# K-76 ölçümü RANGE'in de ÖLÜ olduğunu gösterdi: 1137 gözlemin
# hiçbiri 5'i geçmiyordu (rejim-içi max |AI| = 4).
#
# REJİM-İÇİ ÖLÇÜM (2026-09-10, 4321 gözlem):
#     rejim         n     eşik3    eşik4    eşik5   max|AI|
#     RANGE      1137    %53      %25      %0        4
#     VOLATILE   1031    %65      %2       %0        4
#
# 4, RANGE'i açar. AMA güven kapısı (MIN_CONFIDENCE=62) da uygulanınca
# gerçek sayı %25 DEĞİL:
#     yalnız AI eşiği      : 295 / 1137  (%25)
#     AI + güven>=62       :  92 / 1137  (%8)   ← gerçekleşecek olan
# Yani |AI|=4 olan RANGE sinyallerinin çoğunun güveni zaten düşük.
# Toplamda eşiği geçen gözlem 697 → 789 (+%13).
#
# Bu GERÇEK bir davranış değişikliğidir (K-76'nın aksine — o inertti).
# Ayrıca RANGE'de R/R = 1.33 > MIN_RR = 1.2 (§0), yani bu sinyaller
# R/R kapısına TAKILMAZ — VOLATILE'den farkı bu.
#
# Skor cezası hesaba katılınca: RANGE'de s −1 uygulanıyor, yani
# eşik 4 için ham 5 gerekiyor (TREND'de ham 3). Yani RANGE hâlâ
# TREND'den SEÇİCİ — çift ceza kaldırılmadı, dengelendi.
#
# VOLATILE bilerek 5'te BIRAKILDI: 4'e çekmek yalnızca %2 açardı ve
# orada R/R kapısı zaten bağımsız engelliyor (MIN_RR=1.2 vs ölçülen
# 0.77 — §0 K-11, kârsızlığın asıl sebebi olarak bulunmuştu).
#
# ⚠️ DENEMEDİR. Hüküm 100 işlemde `karar_kurali.py` ile verilir;
# sonuca bakılarak eşik DEĞİŞTİRİLMEZ (§0). Sayaç sıfırlanmalı (§5.3).
REGIME_RANGE_MIN_AI    = int(os.getenv("REGIME_RANGE_MIN_AI", "4"))
# ── v58 (K-76): BEAR/VOLATILE EŞİKLERİ 7/6 → 5 (kullanıcı kararı) ──
# ESKİ DEĞERLER ULAŞILAMAZDI — tahmin değil, ölçüm:
#   2026-09-10, 4321 analiz satırı, 5 coin:
#     |AI| dağılımı : 0→245 · 1→823 · 2→872 · 3→1157 · 4→1105 · 5→119
#     |AI| >= 6     : 0 kez
#     |AI| >= 7     : 0 kez
# Yani gözlenen tavan 5. BEAR(7) ve VOLATILE(6) eşikleri hiçbir zaman
# geçilemiyordu → bot bu iki rejimde ÖLÜ. Tarihsel olarak barların
# %35'i BEAR+VOLATILE (§0.8). Ölü bir kapı "bilinçli olarak işlem
# yok" demek değildir; kalibrasyon hatasıdır.
#
# NEDEN TAM 5: RANGE zaten 5. Ölçek K-37 ile [-3,+6]'ya daraldığında
# TREND=3 / RANGE=5 güncellenmiş, bu ikisi eski geniş ölçekten kalmıştı.
#
# ⚠️ REJİM-İÇİ ÖLÇÜM (aynı gün, |AI| >= eşik geçen gözlem oranı):
#     rejim         n     eşik3    eşik4    eşik5   max|AI|
#     RANGE      1137    %53      %25      %0        4
#     VOLATILE   1031    %65      %2       %0        4
#     TREND_DOWN 1102    %61      %45      %10       5
#     TREND_UP   1051    %39      %37      %0        5
#
# Yani 5, RANGE ve VOLATILE'de HÂLÂ ULAŞILAMAZ. 7/6 → 5 değişikliği
# bu iki rejimde davranışı DEĞİŞTİRMEZ; yalnızca kanıtlanmış ölü bir
# değeri kaldırır ve eşik haritasını tutarlı yapar.
#
# SEBEBİ ÇİFT CEZA: `core/sinyal_skor.py` skoru zaten rejime göre
# düşürüyor (BEAR −3, VOLATILE −2, RANGE −1) ve eşik AYNI rejim için
# bir kez daha yükseltiliyordu. VOLATILE'de −2 ceza yendikten sonra
# 5'e ulaşmak ham +7 gerektirir.
#
# BEAR bugünkü logda HİÇ gözlenmedi, ölçülemedi. Ama yapısal olarak
# değişiklik orada ETKİLİ: −3 ceza nedeniyle SHORT için eşik 7 iken
# ham −4, eşik 5 iken ham −2 gerekiyor.
#
# ➜ RANGE/VOLATILE'i gerçekten açmak isteniyorsa ilk anlamlı değer 4
#    (RANGE %25, VOLATILE %2). Bu AYRI bir karardır; kullanıcı 5 dedi,
#    5 uygulandı. Not: VOLATILE'de R/R kapısı (MIN_RR=1.2 vs ölçülen
#    0.77) zaten bağımsız olarak engelliyor — §0 K-11.
#
# ⚠️ BU BİR DENEMEDİR, kanıt değil. Hüküm 100 işlemde
# `karar_kurali.py` ile verilir; eşikler sonuca bakılarak DEĞİŞTİRİLMEZ
# (§0 protokolü). Davranış değişikliği olduğu için sayaç sıfırlanmalı (§5.3).
REGIME_BEAR_MIN_AI     = int(os.getenv("REGIME_BEAR_MIN_AI", "5"))
REGIME_VOLATILE_MIN_AI = int(os.getenv("REGIME_VOLATILE_MIN_AI", "5"))

# ── Model ─────────────────────────────────────────────────
MODEL_RETRAIN_INTERVAL = int(os.getenv("MODEL_RETRAIN_INTERVAL", "3600"))
WALK_FORWARD_SPLITS    = int(os.getenv("WALK_FORWARD_SPLITS", "8"))
# v58 (K-21): env ile yönlendirilebilir. Sabit kodluyken test paketi
# ÜRETİM saved_models/ dizinine yazıyordu (rf_TESTUSDT.pkl kalıntısı
# bunun kanıtıydı) ve feedback dosyaları da korumasızdı — §4.6'daki
# "yeni kalıcı dosya eklersen env'e aç" kuralının atlanmış hali.
MODEL_DIR              = os.getenv("MODEL_DIR", "saved_models/")
MIN_USEFUL_ACC         = 0.52
LOOKBACK               = 30

# ── v58 (K-23): MODEL HEDEFİ ──────────────────────────────
# "sonraki_bar"    → eski davranış: bir sonraki mum yeşil mi?
# "ucgen_bariyer"  → SL/TP'den hangisine ÖNCE değer? (López de Prado)
#
# NEDEN DEĞİŞTİ: Bot bir sonraki mumun rengine göre değil, SL/TP
# seviyelerine göre para kazanıyor. Eski hedef, kazanmakla ilgisi
# olmayan bir soruyu tahmin ediyordu — ve tek barlık yön, sinyal/gürültü
# oranı en düşük hedeftir. Ölçüldü: dürüst accuracy 0.516, çoğunluk
# sınıfı taban çizgisi 0.518 (DEVAM_NOTLARI §0.2).
#
# Bariyerler İŞLEMİN KENDİ çarpanlarını kullanır (FUTURES_SL/TP_ATR_MULT)
# — etiket ile gerçek emir aynı geometriye bakar.
#
# ⚠️ VARSAYILAN "sonraki_bar" — ÖLÇÜM SONUCU (2026-09-03):
#   Üçlü bariyer denendi ve BEKLENTİYİ KARŞILAMADI. 60 günlük 5m veri,
#   5 sembol, örtüşmeyen örneklem (embargo uygulanmış):
#       SHORT n=1259  fark +0.0044  p=0.386  beklenti %-0.094
#       LONG  n=1390  fark +0.0035  p=0.406  beklenti %-0.069
#   Baş başa karşılaştırmada (aynı ekonomik yargıç) eski hedeften hafif
#   KÖTÜ çıktı. 7 günlük pencerede short tarafında görülen +0.108 (p=0.06,
#   n=57) 60 günde KAYBOLDU — küçük örneklem gürültüsüydü.
#
#   Varsayılanı kanıtsız değiştirmek, VOLATILE çarpanlarını buraya
#   getiren hatanın aynısı olurdu (§0). Makine duruyor; denemek için
#   `HEDEF_TIPI=ucgen_bariyer` yeterli.
HEDEF_TIPI             = os.getenv("HEDEF_TIPI", "sonraki_bar")
# Dikey bariyer: kaç bar sonra pozisyon "zaman aşımı" sayılsın.
# 5m barda 24 bar = 2 saat. Ölçülen gerçek işlem süresi medyanı ~90 dk
# (21 paper işlemi), yani 2 saat makul bir üst sınır.
# ⚠️ Bu değer aynı zamanda EMBARGO uzunluğudur: etiketler örtüştüğü için
# train'in son HEDEF_MAX_BAR satırı test'ten önce atılır.
HEDEF_MAX_BAR          = int(os.getenv("HEDEF_MAX_BAR", "24"))

# ── v58 (K-25): MODEL EĞİTİM PENCERESİ — TEK KAYNAK ───────
# Eskiden iki farklı yol iki farklı pencere kullanıyordu ve İKİSİ DE
# aynı model dosyasına yazıyordu:
#   ana döngü      → coin_analiz(2d/5m)  =  576 bar
#   drift retrain  → 14d/1h              =  336 bar (üstelik farklı TF!)
# Yani modelin neyle eğitildiği, hangi yolun son çalıştığına bağlıydı.
#
# PENCERE UZUNLUĞU ÖLÇÜLDÜ (60 gün 5m, 5 sembol, sabit 1 günlük test
# pencereleri, 40 ölçüm — accuracy eksi çoğunluk sınıfı taban çizgisi):
#     2 gün ( 576 bar): -0.0039  p=0.51   20 sn
#     7 gün (2016 bar): -0.0043  p=0.48  107 sn
#    15 gün (4320 bar): +0.0017  p=0.71  387 sn
#    30 gün (8640 bar): -0.0001  p=0.99  776 sn
#
# HİÇBİR uzunluk edge üretmiyor. Tek kazanç varyansın düşmesi
# (std 0.037 → 0.029) ve o da ancak 15 günden sonra, 19× hesap
# maliyetiyle. Retrain zaten sembol başına dakikalar sürüyor.
# ➜ Uzatmak kanıtla DESTEKLENMİYOR; 2 günde kalındı.
#
# Denemek isteyen `MODEL_EGITIM_PERIOD` değiştirir; K-24 sayfalaması
# sayesinde 1000 bardan fazlası artık gerçekten çekiliyor.
# ── v58 (K-29): ANA İŞLEM UFKU — TEK KAYNAK ───────────────
# ÖLÇÜM (2026-09-04, 3 yıl 5 sembol) — gereken BECERİ FARKI:
#   `başabaş P(TP) − ölçülen taban oran`
#
#   ufuk   ATR%    maliyet/TP   başabaş   taban    BECERİ FARKI
#   5m     0.148     %37.2       0.6412   0.4350   +20.6 puan  ← İMKÂNSIZ
#   1h     0.846      %6.5       0.4657   0.4363   +2.9 puan
#   4h     1.788      %3.1       0.4462   0.4332   +1.3 puan
#   1d     4.806      %1.1       0.4351   0.4328   +0.2 puan
#
# 5m barda ATR medyanı %0.148; TP %0.30, SL %0.22 ve gidiş-dönüş
# maliyet %0.11 → HEDEFİN %37'Sİ MALİYETE GİDİYOR. Başabaş için %64.1
# isabet gerekir; taban oran %43.5. Model taban oranı 20.6 puan
# geçmeliydi — finansal piyasalarda böyle bir tahmin gücü yoktur.
#
# Bu, beş ayrı hipotezin (R/R, üçlü bariyer, uzun pencere, feature
# azaltma, piyasa yapısı) neden reddedildiğinin ORTAK AÇIKLAMASIDIR:
# sorun modelde değil, oynanan oyundaydı.
#
# 4h'de gereklilik 1.3 puana düşüyor (~16× daha kolay) ve eğitim
# verisi 60 günden 3 YILA çıkıyor (6599 bar, birden çok rejim).
#
# ⚠️ UFUK DEĞİŞİKLİĞİ GEREKLİ AMA YETERLİ DEĞİL. Model her ufukta
# taban oranın ALTINDA (4h: −0.0205, p=0.015). 4h zemini kazanmayı
# mümkün kılar, garanti etmez.
#
# ⚠️ ÖRNEKLEM BOĞA PİYASASI (2023-08→2026-09, ort +%207). LONG taban
# oranı sürüklenmeyle şişik; tablodaki rakamlar SHORT tarafından
# alındı. Bu veriyle long-only sistem kurulmamalı.
ANA_INTERVAL           = os.getenv("ANA_INTERVAL", "4h")
# 4h'de 180 gün = 1080 bar. EMA200 için 200+ bar şart; 1080 hem ısınma
# hem eğitim için yeterli. (K-24 sayfalaması 1000 barı aşmayı sağlıyor.)
ANA_PERIOD             = os.getenv("ANA_PERIOD", "180d")

# Model eğitimi ANA UFUKLA aynı olmalı (K-22: eğitim/servis uyuşmazlığı)
MODEL_EGITIM_PERIOD    = os.getenv("MODEL_EGITIM_PERIOD", ANA_PERIOD)
MODEL_EGITIM_INTERVAL  = os.getenv("MODEL_EGITIM_INTERVAL", ANA_INTERVAL)

# Bir barın dakika karşılığı — bar-göreli ayarlar bundan türer
_INTERVAL_DK = {"1m":1,"3m":3,"5m":5,"15m":15,"30m":30,"1h":60,
                "2h":120,"4h":240,"6h":360,"8h":480,"12h":720,"1d":1440}
ANA_BAR_DK             = _INTERVAL_DK.get(ANA_INTERVAL, 240)


# ── Strateji ──────────────────────────────────────────────
STRATEGY_MODE    = os.getenv("STRATEGY_MODE", "AUTO")
GRID_LEVELS      = int(os.getenv("GRID_LEVELS", "5"))
GRID_SPACING_PCT = float(os.getenv("GRID_SPACING_PCT", "0.5"))

# ── Altyapı ───────────────────────────────────────────────
WS_ENABLED        = os.getenv("WS_ENABLED", "true").lower() == "true"
DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "true").lower() == "true"
DASHBOARD_PORT    = int(os.getenv("DASHBOARD_PORT", "8080"))
# v50 GÜVENLİK: Panel kimlik doğrulaması. İkisi de doluysa Basic Auth
# zorunlu olur; boşsa (varsayılan) kısıtlama yok — geriye dönük uyumlu.
PANEL_USER        = os.getenv("PANEL_USER", "")
PANEL_PASS        = os.getenv("PANEL_PASS", "")
# v55: Panel varsayılan olarak yalnızca localhost'a bağlanır. Eskiden koşulsuz
# 0.0.0.0'a bağlanıyordu; PANEL_USER boşken auth da atlandığı için bakiye/
# pozisyon/PnL verisi porta erişebilen herkese açık oluyordu.
PANEL_SADECE_LOCALHOST = os.getenv("PANEL_SADECE_LOCALHOST", "true").lower() == "true"
# v55: Yarım yapılandırma tehlikeli — PANEL_USER dolu ama PANEL_PASS boşsa
# boş şifreyle kimlik doğrulaması geçilebiliyordu. Bunu başlangıçta yakala.
if bool(PANEL_USER) != bool(PANEL_PASS):
    raise ValueError(
        "PANEL_USER ve PANEL_PASS ya İKİSİ birden dolu ya İKİSİ birden boş "
        "olmalıdır. Yalnızca biri doluyken panel boş şifreyle erişilebilir hale gelir."
    )
# CORS: boş = header hiç gönderilmez (en güvenli). Gerekirse tam origin yazın.
PANEL_CORS_ORIGIN = os.getenv("PANEL_CORS_ORIGIN", "")
if PANEL_CORS_ORIGIN.strip() == "*":
    raise ValueError(
        "PANEL_CORS_ORIGIN='*' güvenli değil — panel finansal veri gösteriyor. "
        "Tam origin yazın (örn. https://benimsite.com) veya boş bırakın."
    )
REDIS_ENABLED     = os.getenv("REDIS_ENABLED", "false").lower() == "true"
REDIS_HOST        = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT        = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB          = int(os.getenv("REDIS_DB", "0"))
PROMETHEUS_ENABLED= os.getenv("PROMETHEUS_ENABLED", "false").lower() == "true"
PROMETHEUS_PORT   = int(os.getenv("PROMETHEUS_PORT", "9090"))
# v55 GÜVENLİK: Metrics endpoint bakiye/PnL/drawdown yayınlar ve kimlik
# doğrulaması YOKTUR. Varsayılan olarak yalnızca localhost'a bağlanır.
PROMETHEUS_ADDR   = os.getenv("PROMETHEUS_ADDR", "127.0.0.1")
WATCHDOG_INTERVAL   = int(os.getenv("WATCHDOG_INTERVAL", "60"))

# ── State Persistence ─────────────────────────────────────
STATE_FILE          = os.getenv("STATE_FILE", "data/position_state.json")
STATE_SYNC_INTERVAL = int(os.getenv("STATE_SYNC_INTERVAL", "30"))

# ── v10: Database Backend ─────────────────────────────────
# "sqlite" (default) | "postgres" | "timescale"
DB_BACKEND  = os.getenv("DB_BACKEND", "sqlite")
DB_PATH     = os.getenv("DB_PATH", "data/astra.db")          # SQLite
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "astra")
DB_USER     = os.getenv("DB_USER", "astra")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

# ── v16: Circuit Breaker + Correlation + Shadow Model + Edge Analytics + Spesifik Exception ───────────────────────────────
# VaR hesaplama yöntemleri ağırlıkları (toplamı 1.0 olmalı)
ANALYTICS_VAR_HIST_W  = float(os.getenv("ANALYTICS_VAR_HIST_W",  "0.30"))
ANALYTICS_VAR_PARAM_W = float(os.getenv("ANALYTICS_VAR_PARAM_W", "0.20"))
ANALYTICS_VAR_MC_W    = float(os.getenv("ANALYTICS_VAR_MC_W",    "0.50"))
# Portföy korelasyon eşiği — bu değerin üstündeyse yeni pozisyon engellenir
PORTFOLIO_MAX_CORR    = float(os.getenv("PORTFOLIO_MAX_CORR", "0.70"))

# ── v57: MİNİMUM RİSK/ÖDÜL KAPISI ────────────────────────────────────
# NEDEN EKLENDİ (2026-09-02, 21 işlemlik veriyle):
#   `sl_tp_hesapla` R/R'ı hesaplayıp döndürüyordu ama HİÇBİR YER
#   KONTROL ETMİYORDU. Sistem "bu işlem 0.77 oranında" diye hesaplayıp
#   yine de açıyordu.
#
#   VOLATILE rejimde çarpanlar R/R'ı TERS ÇEVİRİYOR:
#       sl_mult = 1.5 × 1.3  = 1.95×ATR   (stop GENİŞLER)
#       tp1_mult= 2.0 × 0.75 = 1.50×ATR   (hedef DARALIR)
#       → R/R 0.77, yani başabaş için %57 isabet gerekir.
#
#   ÖLÇÜM: TP/STOP ile kapanan 10 işlemde isabet **%50** (yazı tura) ama
#   beklenti −%0.197. Yani kayıp sinyal kalitesinden DEĞİL, aritmetikten
#   geliyordu: hedef stop'tan yakınken %50 isabet bile kaybettirir.
#
# EŞİK NASIL SEÇİLDİ:
#   Kural: R/R > (1-p)/p olmalı. Gözlenen p=%50 → başabaş R/R = 1.0.
#   1.2 seçildi: VOLATILE'i (0.77) engeller, RANGE/TREND'i (1.33) geçirir,
#   %50 isabette pay bırakır. Veriye BAKARAK değil, matematikle belirlendi.
MIN_RR                = float(os.getenv("MIN_RR", "1.2"))

# ── v58 (K-C): YENİDEN GİRİŞ BEKLEME SÜRESİ ───────────────
# NEDEN VAR:
#   Motor bir pozisyonu kapattığı ANDA aynı sembolde ters yönde yenisini
#   açabiliyordu. Ölçüm (2026-09-02, 21 işlem):
#     #15 XRPUSDT LONG kapandı  04:07:50
#     #16 XRPUSDT SHORT açıldı  04:07:50   ← aynı saniye
#     ikisinin toplamı: %-0.45 (saf gidiş-dönüş maliyeti)
#   Kapanış→açılış boşluğu medyan 92 sn, MİNİMUM 0 sn. Stop yiyen
#   işlemden 1 sn sonra yeni pozisyon açılıyordu (#12→#13, #19→#20).
#
# NEDEN 300 SANİYE:
#   Analiz 5m barla çalışıyor. Seni yeni stop'lamış BARIN İÇİNDE tekrar
#   girmek yeni bilgi değil, aynı barın gürültüsüdür. Bir bar minimum
#   ilkeli seçim. Veriye bakılarak seçilmedi.
#
# KAPSAM: SEMBOL BAZLI ve yalnızca AÇILIŞI engeller — kapanış her zaman
#   serbesttir. Global olsaydı (piyasa %92 VOLATILE + R/R kapısı) veri
#   toplama tamamen dururdu.
#
# v58 (K-29): Süre artık BAR-GÖRELİ. Sabit 300 sn, 5m barda "bir bar"
# demekti; 4h barda aynı barın içinde 48 kez yeniden girmeye izin
# verirdi. Ufuk değişince sessizce anlamsızlaşan bir sabitti.
YENIDEN_GIRIS_BEKLEME_SN = int(os.getenv("YENIDEN_GIRIS_BEKLEME_SN", "0"))
# 0 verilirse BİR BAR olarak türetilir (ANA_BAR_DK yukarıda tanımlı).
if YENIDEN_GIRIS_BEKLEME_SN <= 0:
    YENIDEN_GIRIS_BEKLEME_SN = ANA_BAR_DK * 60

# v58 (K-29): Üçlü bariyer dikey ufku da bar cinsinden. 5m'de 24 bar
# = 2 saatti; 4h'de 24 bar = 4 GÜN olurdu. Uzun ufukta 6 bar (4h'de
# 1 gün) daha makul. HEDEF_TIPI=sonraki_bar iken kullanılmaz.
if os.getenv("HEDEF_MAX_BAR") is None and ANA_BAR_DK >= 240:
    HEDEF_MAX_BAR = 6

# ── v58 (K-85): ZAMAN STOP — POZİSYON SÜRESİZ AÇIK KALMASIN ────
# SORUN (§0.29, 2026-09-13 ölçüldü): SL/TP ATR tabanlı (%3-5 uzakta)
# ve zaman-stop YOKTU. Yatay piyasada seviyeler günlerce tetiklenmiyor:
#     10 açık pozisyon · 24-34 saattir açık · 10/10'u SL/TP'ye DEĞMEMİŞ
#     kapanış hızı 0.70/gün → 100 kapanmış işlem ~144 gün
# Slotlar doluyor, akış duruyor. Hüküm KAPANMIŞ işlem istiyor.
#
# SÜRE NEDEN HEDEF_MAX_BAR: bu, üçlü bariyerin DİKEY UFKU — modelin
# etiketleri "önümüzdeki HEDEF_MAX_BAR bar içinde ne olacak" sorusuna
# göre üretiliyor. O ufkun ÖTESİNDE pozisyon tutmak, modelin hakkında
# HİÇBİR İDDİASI OLMAYAN bir pozisyonu tutmaktır. K-22 dersi ile aynı
# ilke: eğitim ufku ile servis ufku ayrışmamalı.
#   4h barda HEDEF_MAX_BAR=6 → 24 saat
#
# ⚠️ BEDELİ VAR: §0.14'te "erken kesme" ölçülmüş bir zarar kalemiydi
# (zıt sinyalle kesilen 11 işlemde toplam zararın %22'si). Zaman stop
# farklı bir mekanizma (sinyal değil süre) ama aynı riski taşır:
# kazanmaya giden bir pozisyonu erken kesebilir. Bu bir DENEMEDİR;
# hüküm 100 işlemde `karar_kurali.py` ile verilir.
# ── v58 (K-88): TASFİYE (liquidation) MODELİ ───────────────────
# Paper tasfiyeyi HİÇ uygulamıyordu. `risk_manager` tasfiye MESAFESİNİ
# izliyordu (uyarı için, bakım marjı 0.004) ama pozisyon hiç tasfiye
# edilmiyordu — 1x muhasebesinde zaten olamazdı.
#
# K-86 ile kaldıraç gerçek oldu; artık tasfiye de gerçek bir risk:
#     3x  → tasfiye ~%32.9 aleyhte hareket
#    10x  → tasfiye  ~%9.5
# SL %3-5'te olduğu için PRATİKTE her zaman SL önce dolar. Ama:
#   • SL emri dolmazsa (gap/boşluk) tasfiye devreye girer
#   • zarar HİÇBİR ZAMAN marjini aşamaz — bu muhasebe güvencesidir
# K-59'da "zarar pozisyon maliyetini aşarsa" diye uyarı bırakılmıştı;
# tasfiye modeli o durumu artık gerçekçi biçimde kapatıyor.
#
# 0.004 değeri `risk_manager.py:337` ile AYNI — iki yer ayrışmasın.
BAKIM_MARJIN_ORANI = float(os.getenv("BAKIM_MARJIN_ORANI", "0.004"))

ZAMAN_STOP_BAR = int(os.getenv("ZAMAN_STOP_BAR", str(HEDEF_MAX_BAR)))
ZAMAN_STOP_SN  = ZAMAN_STOP_BAR * ANA_BAR_DK * 60

# HMM rejim sayısı: CALM / NORMAL / STRESSED
HMM_N_STATES          = int(os.getenv("HMM_N_STATES", "3"))

# ── v10: Exchange Simulation ──────────────────────────────
SIM_LATENCY_MEAN_MS  = float(os.getenv("SIM_LATENCY_MEAN_MS", "45"))
SIM_LATENCY_STD_MS   = float(os.getenv("SIM_LATENCY_STD_MS",  "20"))
SIM_LATENCY_SPIKE_P  = float(os.getenv("SIM_LATENCY_SPIKE_P", "0.05"))  # %5 spike
SIM_SLIPPAGE_BASE_BP = float(os.getenv("SIM_SLIPPAGE_BASE_BP", "3.0"))  # 3 bps
SIM_PARTIAL_FILL_P   = float(os.getenv("SIM_PARTIAL_FILL_P",  "0.08"))  # %8 kısmi fill
# Senaryo tipleri: NORMAL | STRESS | CRASH | LATENCY
SIM_DEFAULT_SCENARIO = os.getenv("SIM_DEFAULT_SCENARIO", "NORMAL")

# ── Timeframes ────────────────────────────────────────────
TIMEFRAMES = {
    "1m":  {"period":"1d",  "interval":"1m"},
    "5m":  {"period":"2d",  "interval":"5m"},
    "15m": {"period":"5d",  "interval":"15m"},
    "1h":  {"period":"7d",  "interval":"1h"},
    "4h":  {"period":"30d", "interval":"4h"},
}
RSI_PERIOD=14; MA_PERIOD=20; ATR_PERIOD=14

# ── v13: Telegram Rate Limiting ───────────────────────────
TG_MIN_ARALIK_SINYAL  = int(os.getenv("TG_MIN_ARALIK_SINYAL", "30"))   # aynı coin sinyali için min saniye

# ── v58 (K-72): TELEGRAM YALNIZCA "ÇOK EMİN" SİNYALLERİ ─────────
# ÖLÇÜM (2026-09-10, tek gün, 5 coin):
#     Telegram mesajı : 2303  (1166 metin + 1137 grafik)
#     dağılım         : 848 rejim · 209 sinyal · 106 genel
# İki ayrı kök neden vardı:
#   • rejim seli  → K-71 (sembol bazlı rejim) çözdü
#   • sinyal seli → BU: 4h ufkunda analiz sonucu bar boyunca (4 SAAT)
#     sabit kalıyor ama tur 60 sn'de bir dönüyor ve rapor eşiği
#     GİRİŞ eşiğine bağlıydı. Giriş bir kez olur, rapor her turda.
#     30 sn'lik throttle bunu bar başına ~48 mesaja indiriyordu.
#
# ÇÖZÜM İKİ KATMANLI:
#   1. Bar başına tekilleştirme — aynı (sembol, kapanmış bar) için
#      en fazla BİR bildirim. Kararı değişirse yeniden gönderilir.
#   2. Kalite kapısı — girişten DAHA YÜKSEK eşik ("çok emin").
#
# ÖLÇÜLEN ETKİ (aynı günün verisiyle, bar başına tekilleştirilmiş):
#     |AI|>=4              : 20 bildirim/gün
#     |AI|>=4 & güven>=70  : 11 bildirim/gün
#     |AI|>=5              :  2 bildirim/gün
#     |AI|>=5 & güven>=70  :  2 bildirim/gün   ← seçilen
# Not: gözlenen en yüksek |AI| = 5 (|AI|>=6 hiç görülmedi), yani
# 5 pratikte "tavan" demektir. 50 coine çıkınca sayı ~10x artar.
TG_MIN_AI_SINYAL      = int(os.getenv("TG_MIN_AI_SINYAL", "5"))    # bildirim için min |AI|
TG_MIN_CONF_SINYAL    = int(os.getenv("TG_MIN_CONF_SINYAL", "70")) # bildirim için min güven %
TG_BAR_BASINA_TEK     = os.getenv("TG_BAR_BASINA_TEK", "true").lower() == "true"

# ── v58 (K-81): REJİM DEĞİŞİMİ TELEGRAM'A GİTMESİN ─────────────
# K-71 rejimi sembol bazlı yaptı (doğru). Ama 50 coinde her sembolün
# İLK ataması da bir "değişim"dir → açılışta 50'ye kadar bildirim.
# ÖLÇÜM (2026-09-10, yeniden başlatmadan 20 dk sonra): 15 Telegram
# mesajının 13'ü rejim bildirimiydi.
#
# Kullanıcının açık isteği: Telegram'a YALNIZCA çok emin sinyaller,
# fotoğraflı. FORMUSDT'nin RANGE→VOLATILE geçişi operasyonel gürültü;
# kullanıcı ona bakıp bir şey yapmıyor.
#
# Log HER değişimi yazmaya devam ediyor (teşhis kaybolmaz) — yalnızca
# Telegram susturuldu. Açmak için: TG_REJIM_BILDIRIMI=true
TG_REJIM_BILDIRIMI = os.getenv("TG_REJIM_BILDIRIMI", "false").lower() == "true"
TG_MIN_ARALIK_REJIM   = int(os.getenv("TG_MIN_ARALIK_REJIM", "120"))   # rejim değişimi min saniye
TG_MIN_ARALIK_SISTEM  = int(os.getenv("TG_MIN_ARALIK_SISTEM", "300"))  # sistem raporu min saniye

# ── v13: Dinamik Edge Eşiği ───────────────────────────────
EDGE_SCORE_MIN        = float(os.getenv("EDGE_SCORE_MIN", "35.0"))     # minimum edge skoru
EDGE_VOLATILITY_MAX   = float(os.getenv("EDGE_VOLATILITY_MAX", "5.0")) # max ATR/fiyat % (çok volatile = dur)

# ── v13: Self-Training Geliştirmeleri ─────────────────────
MAX_FEEDBACK_KAYIT    = int(os.getenv("MAX_FEEDBACK_KAYIT", "1000"))   # coin başına max feedback

# ── v58 (K-39): MODEL SÜRÜM SAKLAMA POLİTİKASI ─────────────────
# `saved_models/versions/` her yeniden eğitimde bir kopya arşivliyor
# ve HİÇBİR temizlik yoktu. ÖLÇÜM: 2026-09-05'te 6431 dosya / 22.7 GB,
# 2026-09-10'da 7174 dosya / 26.3 GB (5 coinle ~0.7 GB/gün).
# 50 coine çıkınca ~7 GB/gün → boş 355 GB ~50 günde dolar.
#
# ⚠️ SÜRÜMLER KULLANILIYOR, hepsi silinemez: `rollback_yap()`
# performans düşünce eski sürümü geri yüklüyor. Bu yüzden politika:
#   • (sembol, model_tipi) başına son N sürüm KORUNUR
#   • aktif=1 olan KORUNUR
#   • en_iyi_versiyon()'un işaret ettiği KORUNUR
#   • gerisi silinir (DB kaydı kalır, yalnızca .pkl gider)
MODEL_SAKLANAN_SURUM  = int(os.getenv("MODEL_SAKLANAN_SURUM", "20"))
RETRAIN_MIN_FEEDBACK  = int(os.getenv("RETRAIN_MIN_FEEDBACK", "20"))   # retrain için min yeni veri

# ── v13: Pozisyon Yönetimi ────────────────────────────────
TRAIL_AFTER_PCT       = float(os.getenv("TRAIL_AFTER_PCT", "1.5"))     # %1.5 karda trailing başlat
PARTIAL_CLOSE_PCT     = float(os.getenv("PARTIAL_CLOSE_PCT", "50.0"))  # TP1'de %50 kapat

# ── v14: Hard Kill Switch ──────────────────────────────────
MAX_CONSECUTIVE_LOSS   = int(os.getenv("MAX_CONSECUTIVE_LOSS", "5"))
MAX_DRAWDOWN_PCT_KILL  = float(os.getenv("MAX_DRAWDOWN_PCT_KILL", "15.0"))
MAX_API_ERRORS_KILL    = int(os.getenv("MAX_API_ERRORS_KILL", "10"))
MAX_WS_DISCONNECTS     = int(os.getenv("MAX_WS_DISCONNECTS", "5"))

# ── v14: Adaptive Sizing ───────────────────────────────────
ADAPTIVE_SIZING        = os.getenv("ADAPTIVE_SIZING", "true").lower() == "true"
MAX_POSITION_USDT      = float(os.getenv("MAX_POSITION_USDT", "100.0"))
# v55: Risk modeli bu tutarın altında bir boyut hesaplarsa işlem AÇILMAZ.
# (Eskiden 5.0'a yuvarlanıyordu; bu, drawdown dampening'ini etkisiz kılıyordu.)
MIN_POZISYON_USDT      = float(os.getenv("MIN_POZISYON_USDT", "5.0"))

# ── v14: Trade Filtering ──────────────────────────────────
CHOP_FILTER_ENABLED    = os.getenv("CHOP_FILTER_ENABLED", "true").lower() == "true"
CHOP_MAX               = float(os.getenv("CHOP_MAX", "61.8"))
MIN_VOLATILITY_PCT     = float(os.getenv("MIN_VOLATILITY_PCT", "0.3"))  # ATR/fiyat min %
MAX_VOLATILITY_PCT     = float(os.getenv("MAX_VOLATILITY_PCT", "5.0"))  # ATR/fiyat max %
FAKE_BREAKOUT_FILTER   = os.getenv("FAKE_BREAKOUT_FILTER", "true").lower() == "true"

# ── v14: Backtest ─────────────────────────────────────────
BACKTEST_KOMISYON      = float(os.getenv("BACKTEST_KOMISYON", "0.0004"))
BACKTEST_SLIPPAGE_BPS  = float(os.getenv("BACKTEST_SLIPPAGE_BPS", "3.0"))
# v56: Paper trading de artık gerçek işlem maliyetini modelliyor.
# Eskiden paper SIFIR maliyetle çalışıyordu → sonuçlar iyimser çıkıyor,
# canlıya geçişte "strateji bozuldu" yanılgısına yol açıyordu.
# Varsayılanlar backtest ile AYNI tutuldu ki üç ortam kıyaslanabilir olsun.
PAPER_KOMISYON         = float(os.getenv("PAPER_KOMISYON", str(BACKTEST_KOMISYON)))
PAPER_SLIPPAGE_BPS     = float(os.getenv("PAPER_SLIPPAGE_BPS", str(BACKTEST_SLIPPAGE_BPS)))
BACKTEST_KALDIRAC      = int(os.getenv("BACKTEST_KALDIRAC", "5"))

# ── v14: Order Reconciler ─────────────────────────────────
RECONCILER_INTERVAL    = int(os.getenv("RECONCILER_INTERVAL", "15"))

# ── v14: Journal ─────────────────────────────────────────
JOURNAL_DB_PATH        = os.getenv("JOURNAL_DB_PATH", "data/journal.db")

# ── v16: Circuit Breaker ──────────────────────────────────
# ── v58 (K-79): MUTLAK ATR EŞİĞİ HETEROJEN EVRENDE ÇALIŞMAZ ────
# 4.0 değeri 5 büyük coin (BTC/ETH/SOL/BNB/XRP) için kalibre edilmişti.
# 50 coinlik evrende ATR aralığı ÖLÇÜLDÜ (2026-09-10, 4h, ATR14):
#     BTC %1.05 · ETH %1.37 · XRP %1.96 · medyan %3.65
#     DOT %4.42 · NEAR %5.18 · PUMP %5.98 · COTI %8.17 · HEMI %9.04
#     (uçlar ayrı ele alındı: IOST %29.5, SOPH %17.3 → evrenden çıkarıldı)
# Yani evren 30 KAT aralığa yayılıyor; tek mutlak eşik anlamsız.
#
# ÖLÇÜLEN ZARAR (19 saat): 19 coin eşiği aştı ve HER TURDA analizden
# atlandı — panelde 50 yerine 31 coin göründü, 894 tetiklenme oldu.
# Bunlar "acil durum" değil, o coinlerin NORMAL volatilitesiydi:
# her coin hep AYNI değerle tetikleniyordu (medyan = maksimum).
#
# Kullanıcının 50 coin koyma amacı işlem hızını artırmaktı; breaker
# coinlerin %38'ini sessizce devre dışı bırakarak tam tersini yapıyordu.
#
# YENİ DEĞER 10: en volatil KALAN coin HEMI %9.04. Yani eşik artık
# gerçek bir tavan (SL ≈ %15) — normal alt volatilitesini engellemiyor,
# ama çılgın bir harekette hâlâ devrede.
#
# ⚠️ ASIL DEDEKTÖR BU DEĞİL: `atr_spike` (s5/s20 > 2.5) coinin KENDİ
# geçmişine göre bakar ve taban seviyesinden bağımsızdır. Rejim
# değişimini o yakalar; mutlak eşik yalnızca akıl-sağlığı tavanıdır.
MAX_ATR_PCT           = float(os.getenv("MAX_ATR_PCT", "10.0"))
MAX_FUNDING_RATE         = float(os.getenv("MAX_FUNDING_RATE", "0.003"))
MAX_SPREAD_PCT           = float(os.getenv("MAX_SPREAD_PCT", "0.15"))
CIRCUIT_BREAKER_BEKLEME  = int(os.getenv("CIRCUIT_BREAKER_BEKLEME", "300"))

# ── v16: Correlation Engine ───────────────────────────────
MAX_MAJORS_SAME_DIR      = int(os.getenv("MAX_MAJORS_SAME_DIR", "1"))
MAX_ALTS_SAME_DIR        = int(os.getenv("MAX_ALTS_SAME_DIR", "2"))
MAX_TOPLAM_SAME_DIR      = int(os.getenv("MAX_TOPLAM_SAME_DIR", "3"))

# ── v16: Shadow Model ─────────────────────────────────────
SHADOW_AUTO_APPROVE      = os.getenv("SHADOW_AUTO_APPROVE", "true").lower() == "true"
SHADOW_MIN_IMPROVEMENT   = float(os.getenv("SHADOW_MIN_IMPROVEMENT", "0.5"))

# ── v16: Edge Analytics ───────────────────────────────────
EDGE_DECAY_ALARM_PCT     = float(os.getenv("EDGE_DECAY_ALARM_PCT", "30.0"))

# ── v22: Smart Execution (TWAP/VWAP) ──────────────────────
MIN_TWAP_USDT        = float(os.getenv("MIN_TWAP_USDT", "80.0"))      # Bu üstü emirler bölünür
TWAP_DILIM_SAYISI    = int(os.getenv("TWAP_DILIM_SAYISI", "4"))       # Kaç parça
TWAP_DILIM_ARALIK_SN = float(os.getenv("TWAP_DILIM_ARALIK_SN", "1.5"))# Dilimler arası saniye (v23: SL gecikmesini azaltmak için 3.0→1.5)
TWAP_MAX_SURE_SN     = float(os.getenv("TWAP_MAX_SURE_SN", "8.0"))    # v23: Toplam execution süresi tavanı (SL gecikme koruması)
SMART_EXEC_ENABLED   = os.getenv("SMART_EXEC_ENABLED", "true").lower() == "true"

# ── v22: On-Chain (opsiyonel API anahtarları) ─────────────
# GLASSNODE_API_KEY ve ETHERSCAN_API_KEY .env'den okunur (yoksa proxy)

# ── v24: Strateji Dayanıklılık Doğrulama ──────────────────
VALIDATOR_MIN_SKOR          = float(os.getenv("VALIDATOR_MIN_SKOR", "60.0"))     # 100 üzerinden geçme eşiği
VALIDATOR_MIN_DSR           = float(os.getenv("VALIDATOR_MIN_DSR", "0.0"))       # Deflated Sharpe > bu olmalı
VALIDATOR_MAX_DD_PCT        = float(os.getenv("VALIDATOR_MAX_DD_PCT", "35.0"))   # Worst-case drawdown tavanı %
VALIDATOR_MIN_WF_TUTARLILIK = float(os.getenv("VALIDATOR_MIN_WF_TUTARLILIK", "0.55"))  # WF pozitif pencere oranı
VALIDATOR_BOOTSTRAP_N       = int(os.getenv("VALIDATOR_BOOTSTRAP_N", "2000"))    # Bootstrap simülasyon sayısı

# ── v26: Çoklu Borsa Fiyat Doğrulama + Arbitraj ───────────
MULTIEX_ENABLED           = os.getenv("MULTIEX_ENABLED", "true").lower() == "true"
MULTIEX_MAX_SAPMA_PCT     = float(os.getenv("MULTIEX_MAX_SAPMA_PCT", "1.0"))      # Binance bu %'den fazla saparsa veto
MULTIEX_ARBITRAJ_ESIK_PCT = float(os.getenv("MULTIEX_ARBITRAJ_ESIK_PCT", "0.15")) # Borsa farkı bu %'den fazlaysa arbitraj sinyali
MULTIEX_CACHE_TTL         = float(os.getenv("MULTIEX_CACHE_TTL", "3.0"))           # Fiyat cache süresi (sn)

# ── v27: Pozisyon Boyutu Taban Koruması (agresiflik ayarı) ─
# Dampening katmanları (belirsizlik, CVD, MTF, rejim, çoklu borsa) çarpımsal
# uygulanınca pozisyon aşırı küçülüyordu. Bu taban, birleşik dampening'in
# Kelly değerini bu oranın altına indirmesini engeller.
POZ_MIN_DAMP_TABANI    = float(os.getenv("POZ_MIN_DAMP_TABANI", "0.45"))  # toplam dampening en fazla %55 kırpar
POZ_AGRESIFLIK         = float(os.getenv("POZ_AGRESIFLIK", "1.0"))        # 1.0=normal, >1 daha agresif, <1 temkinli

# ── v28: Giriş Gecikme Kontrolü + Sağlamlaştırma ──────────
MAX_GIRIS_KAYMA_PCT  = float(os.getenv("MAX_GIRIS_KAYMA_PCT", "0.35"))  # Sinyal sonrası fiyat aleyhe bu %'den fazla kaçarsa giriş iptal
# v58 (K-95): Geç giriş eşiğinin TAVANI artık ATR ile ölçekleniyor.
# Eski tavan `MAX_GIRIS_KAYMA_PCT * 2` = %0.70 MUTLAK sabitti ve ATR
# uyarlamasını SÖNDÜRÜYORDU: medyan 4h ATR %2.43, tavanın devreye
# girdiği nokta %2.33 → coinlerin %54'ü zaten tavanda, ETHFIUSDT'de
# amaçlanan %1.37 eşik %0.70'e kırpılıyordu (§0.35 Bulgu 2).
#
# Bu değer bir ÇALIŞMA NOKTASI DEĞİL, akıl-sağlığı tavanıdır: normal
# ATR aralığında bağlayıcı olan, asıl uyarlama terimidir
# (MAX_GIRIS_KAYMA_PCT + ATR%*0.15). Tavan yalnızca bozuk ATR'ye karşı.
#
# ANKRAJ: stop mesafesi = FUTURES_SL_ATR_MULT × ATR. Girişten ÖNCE
# bu mesafenin en fazla 1/3'ünü vermeyi kabul ediyoruz — daha fazlası,
# işlem daha açılmadan R/R'ı bozar (§0 K-11'in aynı mantığı).
# Sabit yazmak yerine SL çarpanından türüyor: SL politikası değişirse
# tavan da peşinden gelir (K-82/K-83 sınıfı bayatlamayı önler).
MAX_GIRIS_KAYMA_STOP_PAYI = float(os.getenv("MAX_GIRIS_KAYMA_STOP_PAYI", "0.3333"))
HIZLI_TARAMA         = os.getenv("HIZLI_TARAMA", "true").lower() == "true"  # Güçlü sinyalde kontrolleri hızlandır
STATE_RECOVERY       = os.getenv("STATE_RECOVERY", "true").lower() == "true"  # Açılışta açık pozisyonları senkronize et

# ── v34: Ana Döngü Bloke Koruması (VDS 7/24 sağlamlık) ────
# ── v58 (K-30): TUR TAVANI BAR-GÖRELİ ─────────────────────
# 150 sn, 5m barı için ayarlanmış bir sabitti: bar 5 dakikada bir
# değiştiği için tur ondan hızlı bitmeliydi.
#
# ÖLÇÜLEN ARIZA (2026-09-04, 4h'e geçişten 8.3 saat sonra):
#     tamamlanan tur : 0
#     zaman aşımı    : 96
#     paper işlem    : 0
# 4h'de `coin_analiz` çok ağırlaştı (1081 bar + 1w MTF çekimi +
# 1081 barlık model eğitimi: Optuna 25 deneme × 4 model + 8 katman
# walk-forward + TFT). Tur 150 sn'yi HER SEFERİNDE aşıyor, asyncio
# görevleri iptal ediliyor ve `sinyal_isle` sonuçlara HİÇ ulaşmıyor.
#
# Bu, DEVAM_NOTLARI'ndaki v47 hatasının birebir tekrarı:
#   "150s tur iptali ... sinyal_isle hiç çalışmıyordu → 42 sinyal
#    ama 0 paper işlem."
# O sefer sebep grafikti; bu sefer model eğitimi. Ortak kök: tur
# tavanı, turun İÇİNDEKİ işten bağımsız sabit bir sayıydı.
#
# ÇÖZÜM: tavan bir barın 1/24'ü (en az 150 sn).
#   5m  → max(150, 12)  = 150 sn  (davranış DEĞİŞMEZ)
#   4h  → max(150, 600) = 600 sn
#   1d  → max(150, 3600)= 3600 sn
# Uzun ufukta acele etmenin anlamı yok: yeni bilgi 4 saatte bir
# geliyor, turun 10 dakika sürmesi barın %4'ü.
# ── v58 (K-82): TAVAN COİN SAYISIYLA ÖLÇEKLENMELİ ──────────────
# Eski formül yalnızca bar süresine bakıyordu: 4h → 600 sn. 5 coinde
# fazlasıyla yeterliydi (tur 66 sn). 50 coinde tur SÜREKLİ 600 sn'yi
# aşıp İPTAL EDİLİYORDU.
#
# ÖLÇÜLEN ZARAR (2026-09-10 22:28-22:52): kapsama 39/50'de TAKILDI.
# Eksik 11 coinin 10'u listenin SONUNDAKİ 10 coindi (COTI, HBAR,
# ATOM, ETC, BCH, HEMI, JUP, ICP, THE, ETHFI) — yani iptal hep aynı
# yerde vuruyor ve liste sonu HİÇ sıra alamıyordu. O coinler sinyal
# üretemiyordu; kullanıcının 50 coin koyma amacı boşa çıkıyordu.
#
# Yeni formül coin sayısını ve eşzamanlılığı hesaba katar; yine de
# barın YARISINI aşmaz (bir sonraki bar gelmeden tur bitmeli).
#   50 coin / 3 eşzamanlı x 40 sn ≈ 670 sn → tavan 1200 sn
# ANALIZ_ESZAMANLI bu satırdan SONRA tanımlanıyor; sıralamaya
# bağımlı olmamak için env'den doğrudan okunuyor.
_es = int(os.getenv("ANALIZ_ESZAMANLI", "3"))
_tur_tahmin = int(len(COINS) / max(1, _es) * 40 * 1.8)
COIN_TUR_TIMEOUT = int(os.getenv(
    "COIN_TUR_TIMEOUT",
    str(min(max(150, ANA_BAR_DK * 60 // 24, _tur_tahmin), ANA_BAR_DK * 60 // 2))))
# ── v58 (K-75): EŞZAMANLI ANALİZ TAVANI ────────────────────────
# `asyncio.gather(*[... for s in COINS])` TÜM coinleri aynı anda
# başlatıyordu. Eşzamanlılığı asyncio değil, varsayılan thread
# havuzu sınırlıyordu: min(32, cpu+4) = bu makinede 20.
#
# 5 coinle tavan zaten 5 idi. 50 coine çıkınca 20 coin AYNI ANDA
# analiz edilir; her biri kline + funding + OI + order book + whale
# çağrısı yapar → saniyeler içinde 100+ istek → HTTP 418 (IP ban).
# 2026-09-10 ölçümü: 5 coinle bile günde 279 kez 418 alınıyordu,
# her biri 300 sn bekletiyor.
#
# 4h ufkunda acele etmenin bir değeri yok: 50 coin × ~13 sn ÷ 3
# eşzamanlı ≈ 220 sn, tur tavanı ise 600 sn.
ANALIZ_ESZAMANLI = int(os.getenv("ANALIZ_ESZAMANLI", "3"))

# ── v58 (K-83): WATCHDOG EŞİĞİ TUR SÜRESİNDEN KISAYDI ──────────
# 600 sn, 5 coinli dönemde kalibre edilmişti (tur 66 sn). 50 coinde
# bar sınırındaki TAM analiz turu 948 sn sürüyor — yani watchdog her
# bar sınırında SAĞLIKLI botu donmuş sanıyor.
#
# ÖLÇÜLEN VAKA (2026-09-11 00:02): watchdog "2424s donma" deyip
# process'i yeniden başlattı. Ama bot DONMAMIŞTI — o 40 dakika
# boyunca dakikada 25-55 satır log yazıyordu (REGISTRY model eğitimi,
# AUDIT, WS). Heartbeat yalnızca BİR COİNİN analizi bitince atılıyor;
# ağır model eğitimi sırasında coin tamamlanmadığı için sessizlik
# uzuyor. 10 saatte İKİ kez oldu (00:02 ve 10:38, çıkış kodu 15).
#
# ZARARI: ısınma işi çöpe gidiyor, bot baştan başlıyor — ve yeniden
# ısınma yine uzun sürdüğü için DÖNGÜYE girme riski var.
#
# Eşik artık tur tavanından TÜRETİLİYOR: bir tur meşru olarak
# COIN_TUR_TIMEOUT kadar sürebilir; iki tur pay bırakmak tek yavaş
# turda sahte alarmı önler, gerçek (çok turluk) donmayı yakalamayı
# sürdürür.
WATCHDOG_MAX_SILENT = int(os.getenv("WATCHDOG_MAX_SILENT",
                                    str(max(600, COIN_TUR_TIMEOUT * 2))))
WS_STALE_ESIK_S  = int(os.getenv("WS_STALE_ESIK_S", "30"))   # WS bu süre veri gelmezse yenile (testnet için 30+ önerilir)
