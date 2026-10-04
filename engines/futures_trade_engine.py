# =========================================================
# ASTRA v30.0 — FUTURES TRADE ENGINE
# v19 YENİLİKLER:
#   • Chandelier Exit — dinamik ATR trailing stop
#   • MTF Cascade blok bilgisi sl_tp_hesapla'ya aktarıldı
#   • Chandelier güncelleme state takibi per-pozisyon
# =========================================================
import logging
from datetime import datetime, time
from collections import deque
from typing import Optional
import sys; sys.path.append("..")
from config import (LIVE_TRADING, FUTURES_LEVERAGE,
                    FUTURES_TRAILING_STOP, FUTURES_TRAILING_CALLBACK,
                    FUTURES_PARTIAL_TP, FUTURES_PARTIAL_TP_PCT,
                    FUTURES_SL_ATR_MULT, FUTURES_TP_ATR_MULT, FUTURES_TP2_ATR_MULT,
                    MIN_CONFIDENCE, REGIME_TREND_MIN_AI, REGIME_RANGE_MIN_AI,
                    REGIME_BEAR_MIN_AI, REGIME_VOLATILE_MIN_AI)
from data.binance_futures_client import (
    futures_market_kapat, futures_trailing_stop_koy,
    futures_bakiye, acik_futures_pozisyonlar,
    pozisyon_var_mi, duplicate_kontrol,
    futures_anlık_fiyat, sembol_tum_emirleri_iptal,
    kaldirac_ayarla, FuturesAPIError
)
from engines.event_bus import get_bus, Event

log = logging.getLogger("ASTRA.FUTURES_ENGINE")

_risk_manager   = None
_strategy_engine= None
_tp1_tamamlandi: set = set()
_state_abone_kuruldu = False   # v55: POSITION_CLOSED aboneliği tek sefer

# v19: Chandelier Exit state — her pozisyon için fiyat geçmişi ve mevcut stop
_chandelier_state: dict = {}   # {sembol_yon: {"high_deque": deque, "low_deque": deque, "stop": float}}
_CHANDELIER_PERIOD  = 22       # Standart: 22 mum
_CHANDELIER_MULT    = 3.0      # 3x ATR (agresif trend yakalama)

def risk_manager_set(rm):   global _risk_manager;    _risk_manager = rm
def strategy_engine_set(se):global _strategy_engine; _strategy_engine = se


def sl_tp_hesapla(fiyat: float, yon: str, atr: float, rejim: str = "RANGE") -> dict:
    sl_mult  = FUTURES_SL_ATR_MULT
    tp1_mult = FUTURES_TP_ATR_MULT
    tp2_mult = FUTURES_TP2_ATR_MULT
    if rejim in ("TREND_UP","TREND_DOWN"):
        tp2_mult = FUTURES_TP2_ATR_MULT * 1.4
    elif rejim == "VOLATILE":
        sl_mult  = FUTURES_SL_ATR_MULT * 1.3
        tp1_mult = FUTURES_TP_ATR_MULT * 0.75
    sl_m=atr*sl_mult; tp1_m=atr*tp1_mult; tp2_m=atr*tp2_mult
    if yon=="LONG":
        sl=round(fiyat-sl_m,4); tp1=round(fiyat+tp1_m,4); tp2=round(fiyat+tp2_m,4)
    else:
        sl=round(fiyat+sl_m,4); tp1=round(fiyat-tp1_m,4); tp2=round(fiyat-tp2_m,4)
    rr=tp1_m/sl_m if sl_m>0 else 0
    return {"sl":sl,"tp1":tp1,"tp2":tp2,"rr":round(rr,2)}


def rr_yeterli_mi(rr: float, sembol: str = "", rejim: str = "") -> bool:
    """Planlanan risk/ödül oranı işlemi açmaya değer mi?

    v57 — HİÇ OLMAYAN KAPI:
      `sl_tp_hesapla` R/R'ı zaten hesaplayıp döndürüyordu ama hiçbir yer
      KONTROL ETMİYORDU. Sistem "bu işlem 0.77 oranında" diye hesaplayıp
      yine de açıyordu.

      VOLATILE rejimde çarpanlar R/R'ı ters çeviriyor (SL 1.95×ATR,
      TP 1.50×ATR → 0.77). Başabaş için %57 isabet gerekir.

      ÖLÇÜM (2026-09-02, 21 işlem): TP/STOP ile kapanan 10 işlemde isabet
      **%50** — yani sinyal yazı tura kadar isabetli. Ama beklenti
      −%0.197. Kayıp sinyalden değil ARİTMETİKTEN geliyordu.

      Kural: R/R > (1-p)/p. p=%50 → başabaş 1.0. MIN_RR=1.2 pay bırakır.

    ⚠️ Bu kapı PAPER ve CANLI yollarının İKİSİNDE de çağrılmalıdır (§5.3).
      Yalnızca birinde olursa paper canlıyı temsil etmez.
    """
    from config import MIN_RR
    if rr >= MIN_RR:
        return True
    log.info(f"[R/R KAPISI] {sembol} {rejim} R/R={rr:.2f} < {MIN_RR} — "
             f"işlem AÇILMADI (bu oranda başabaş için "
             f"%{100/(1+rr):.0f} isabet gerekir)")
    return False


def rejim_ai_esigi(rejim: str) -> int:
    """Rejime göre yönlü sinyal için gereken mutlak AI skorunu döndür.

    Paper ve canlı yolun farklı eşiklerle karar vermesi, paper verisinin
    canlı davranışı temsil etmesini engeller. Bu nedenle eşik haritası tek
    bir yerde tutulur; bilinmeyen rejim mevcut davranışla uyumlu olarak 4'e
    düşer.
    """
    esik_map = {
        "TREND_UP": REGIME_TREND_MIN_AI,
        "TREND_DOWN": REGIME_TREND_MIN_AI,
        "RANGE": REGIME_RANGE_MIN_AI,
        "BEAR": REGIME_BEAR_MIN_AI,
        "VOLATILE": REGIME_VOLATILE_MIN_AI,
    }
    return esik_map.get(rejim, 4)


def sinyal_kalitesi_degerlendir(sonuc: dict, yon: str) -> tuple[bool, str, int]:
    """Giriş/çıkış sinyalini iki mod için AYNI kuralla değerlendir.

    Döner: ``(gecti, neden, esik)``. ``neden`` yalnızca ``guven_dusuk``
    veya ``ai_skor_dusuk`` olabilir. Ayrı bir neden döndürmek, paper'ın
    ``/neden`` sayacını doğru sınıflandırmasına izin verirken karar kuralını
    çoğaltmamayı sağlar.
    """
    ai = sonuc.get("ai_score", 0)
    conf = sonuc.get("confidence", 0)
    esik = rejim_ai_esigi(sonuc.get("rejim", "RANGE"))

    if conf < MIN_CONFIDENCE:
        return False, "guven_dusuk", esik
    if yon == "LONG" and ai < esik:
        return False, "ai_skor_dusuk", esik
    if yon == "SHORT" and ai > -esik:
        return False, "ai_skor_dusuk", esik
    return True, "", esik


def sinyal_gecerli_mi(sonuc: dict, yon: str) -> bool:
    """Canlı yol için ortak sinyal kalitesi kapısı."""
    gecti, neden, esik = sinyal_kalitesi_degerlendir(sonuc, yon)
    if gecti:
        return True

    ai = sonuc.get("ai_score", 0)
    conf = sonuc.get("confidence", 0)
    rejim = sonuc.get("rejim", "RANGE")
    if neden == "guven_dusuk":
        log.info(f"[FİLTRE] {sonuc.get('sembol')} güven düşük: %{conf} < %{MIN_CONFIDENCE}")
    elif yon == "LONG":
        log.info(f"[FİLTRE] LONG ai={ai} < {esik} ({rejim})")
    else:
        log.info(f"[FİLTRE] SHORT ai={ai} > {-esik} ({rejim})")
    return False


def _pozisyon_state_temizle(sembol: str, yon: str):
    """v23: Pozisyon kapandığında chandelier + tp1 state'ini temizle.
    Aksi halde aynı sembol_yon ile açılan yeni pozisyon eski stop değerini
    miras alır (tehlikeli) ve dict sınırsız büyür (memory leak)."""
    poz_key = f"{sembol}_{yon}"
    _chandelier_state.pop(poz_key, None)
    _tp1_tamamlandi.discard(poz_key)


def _on_position_closed(msg):
    """v55: Pozisyon NASIL kapanırsa kapansın state temizlenir.

    Eskiden _pozisyon_state_temizle YALNIZCA futures_pozisyon_kapat() içinden
    çağrılıyordu (motor kaynaklı kapanış). Oysa pozisyonların normal kapanış
    yolu Binance'in SL/TP/trailing emrini doldurmasıdır; bunu position_state
    /reconciler asenkron tespit eder ve temizlik hiç çalışmazdı.
    Sonuç: aynı sembol+yön ile açılan YENİ pozisyon, ESKİ işlemin chandelier
    stop'unu miras alıyordu. Stop yeni giriş fiyatının üstündeyse ilk izleme
    turunda anında hatalı stop-out tetikleniyordu.
    """
    try:
        data = getattr(msg, "data", None) or {}
        sembol = str(data.get("sembol", "")).upper()
        yon    = str(data.get("yon", "")).upper()
        if not sembol:
            return
        if yon in ("LONG", "SHORT"):
            _pozisyon_state_temizle(sembol, yon)
        else:
            # Yön bildirilmemişse (bazı sync event'leri) her iki yönü de temizle
            _pozisyon_state_temizle(sembol, "LONG")
            _pozisyon_state_temizle(sembol, "SHORT")
    except Exception as e:
        log.error(f"[FUTURES ENGINE] state temizleme hatası: {e}")


def _state_temizleyici_kaydol():
    """POSITION_CLOSED aboneliğini bir kez kurar."""
    global _state_abone_kuruldu
    if _state_abone_kuruldu:
        return
    try:
        get_bus().subscribe(Event.POSITION_CLOSED, _on_position_closed)
        _state_abone_kuruldu = True
        log.info("[FUTURES ENGINE] Chandelier state temizleyici POSITION_CLOSED'a abone oldu")
    except Exception as e:
        log.error(f"[FUTURES ENGINE] state temizleyici abone olamadı: {e}")


def futures_pozisyon_kapat(sembol: str, yon: str, sebep: str = "SİNYAL") -> Optional[dict]:
    if not LIVE_TRADING:
        return None

    sembol = sembol.upper()
    pozlar = acik_futures_pozisyonlar()
    poz    = next((p for p in pozlar if p["sembol"]==sembol and p["yon"]==yon), None)

    if not poz:
        log.warning(f"[FUTURES ENGINE] Kapatılacak pozisyon yok: {sembol} {yon}")
        return None

    try:
        guncel  = futures_anlık_fiyat(sembol) or poz["giris"]
        pnl_pct = ((guncel-poz["giris"])/poz["giris"]*100)*(1 if yon=="LONG" else -1)
        order   = futures_market_kapat(sembol, yon)

        if order and order.get("orderId"):
            # v55: PnL artık GERÇEK dolum fiyatından hesaplanıyor.
            # Eskiden `guncel` (emir gönderilmeden ÖNCEKİ fiyat) kullanılıyor,
            # `exec_fiyat` hesaplanıp hiç kullanılmıyordu. Market emirlerinde
            # slippage nedeniyle gerçek çıkış farklıdır; zararlar olduğundan
            # AZ kaydediliyordu. Bu event risk_manager.pnl_guncelle()'nin tek
            # beslemesi olduğu için günlük zarar limiti ve Kelly yanlış besleniyordu.
            exec_fiyat = float(order.get("avgPrice",0)) or guncel
            giris_f    = float(poz["giris"])
            miktar_f   = abs(float(poz.get("miktar", 0) or 0))
            yon_carpan = 1 if yon == "LONG" else -1
            if giris_f > 0:
                pnl_pct = ((exec_fiyat - giris_f) / giris_f * 100) * yon_carpan
            pnl_usdt = ((exec_fiyat - giris_f) * miktar_f * yon_carpan
                        if miktar_f > 0 else float(poz.get("pnl", 0) or 0))

            # v23: pnl_guncelle BURADA çağrılmıyor — POSITION_CLOSED event'ini
            # dinleyen _on_position_closed (main.py) Kelly+performans ile birlikte
            # tek noktadan günceller. Burada da çağrılırsa PnL çift sayılırdı.

            # RL reward
            try:
                from engines.model_engine import rl_reward_kaydet
                rl_reward_kaydet(sembol, pnl_pct, 0)
            except Exception as rl_e:
                log.warning(f"[RL] Reward kayıt hatası: {rl_e}")

            # v23: Chandelier + tp1 state temizle (memory leak + stale stop önleme)
            _pozisyon_state_temizle(sembol, yon)

            # Position state güncelle
            try:
                from engines.position_state import get_state_manager
                get_state_manager().pozisyon_kapat(sembol, sebep)
            except Exception as state_e:
                log.error(f"[STATE] Pozisyon kapat state hatası: {state_e}")

            bus = get_bus()
            bus.publish(Event.POSITION_CLOSED, {
                "sembol":sembol,"yon":yon,"pnl_pct":round(pnl_pct,3),
                "pnl_usdt":round(pnl_usdt,4),"sebep":sebep
            }, "FuturesEngine")

            log.info(f"[FUTURES ENGINE] ✅ {sembol} {yon} kapatıldı "
                     f"PnL:{pnl_pct:+.2f}% ({sebep})")
        else:
            log.error(f"[FUTURES ENGINE] {sembol} {yon} kapatma başarısız")

        return order

    except FuturesAPIError as e:
        log.error(f"[FUTURES ENGINE] {sembol} kapatma API hatası: {e}")
        return None
    except Exception as e:
        log.critical(f"[FUTURES ENGINE] {sembol} kapatma beklenmedik hata: "
                     f"{type(e).__name__}: {e}", exc_info=True)
        return None


def futures_otomatik_isle(sonuc: dict, emir_tipi: str = "MARKET") -> None:
    if not LIVE_TRADING:
        return

    sembol = sonuc["sembol"]; karar = sonuc.get("karar","")
    is_buy="BUY" in karar; is_sell="SELL" in karar
    if not is_buy and not is_sell:
        return

    try:
        bakiye = futures_bakiye()
        pozlar = acik_futures_pozisyonlar()
        fiyat  = sonuc["son_close"]
        atr    = sonuc.get("son_atr", fiyat*0.01)
        rejim  = sonuc.get("rejim","RANGE")

        if _strategy_engine:
            karar_dict = _strategy_engine.karar_ver(sonuc, bakiye)
            if not karar_dict.get("islem_yap", False):
                log.info(f"[STRATEJI] {sembol}: {karar_dict.get('sebep')}")
                return
            sonuc["strateji"]   = karar_dict.get("strateji","TREND_FOLLOW")
            sonuc["trade_usdt"] = karar_dict.get("usdt", 20)

        yon = "LONG" if is_buy else "SHORT"

        if not sinyal_gecerli_mi(sonuc, yon):
            return
        if duplicate_kontrol(sembol, yon):
            return

        # ── v55: Nihai kaldıraç ve pozisyon boyutu ÖNCE hesaplanır ──
        # Eskiden marjin kontrolü STATİK FUTURES_LEVERAGE ve GEÇİCİ trade_usdt
        # ile yapılıyor, emir ise dinamik kaldıraç + Kelly boyutuyla gidiyordu.
        # Gerekli marjin = notional/kaldıraç olduğundan, gerçek kaldıraç
        # varsayılandan DÜŞÜKSE (dinamik kaldıraç tam da drawdown döneminde
        # düşürür) emir kontrol edilenden FAZLA marjin tüketiyordu — yani
        # MAX_MARGIN_PCT kontrolü geçerken gerçek sınır aşılabiliyordu.
        nihai_kaldirac = FUTURES_LEVERAGE
        nihai_usdt     = sonuc.get("trade_usdt", 20)
        if _risk_manager:
            nihai_kaldirac = _risk_manager.dinamik_kaldirac_hesapla(fiyat, atr)
            win_rate       = sonuc.get("yukselis_guveni", 55) / 100
            nihai_usdt     = _risk_manager.pozisyon_buyuklugu_hesapla(
                bakiye, fiyat, atr, win_rate)
        nihai_usdt = min(nihai_usdt, bakiye * 0.9)

        # v55: Sizing motoru 0 döndürdüyse (negatif Kelly / drawdown damping)
        # işlem AÇILMAZ. Bu kontrol marjin hesabından ÖNCE olmalı — aksi halde
        # `max(nihai_usdt, 5)` sıfır boyut için sahte bir marjin üretir.
        if nihai_usdt <= 0:
            log.info(f"[RISK] {sembol} pozisyon boyutu 0 → işlem atlandı")
            return

        if _risk_manager:
            # Marjin kontrolü artık emrin GERÇEK değerleriyle yapılıyor
            marjin = max(nihai_usdt, 5) / max(nihai_kaldirac, 1)
            engelle, sebep = _risk_manager.tum_kontroller(yon, pozlar, bakiye, marjin)
            if engelle:
                log.warning(f"[RISK ENGEL] {sembol} {yon}: {sebep}")
                return

            mevcut_fiyatlar = {sembol: fiyat}
            tehlikeli = _risk_manager.likidasyon_guard(pozlar, mevcut_fiyatlar)
            if any(t.get("KRITIK") for t in tehlikeli):
                log.warning(f"[LİKİDASYON GUARD] Kritik pozisyon var — yeni emir engellendi")
                return

        # Zıt pozisyon kapat
        if is_buy and pozisyon_var_mi(sembol, "SHORT"):
            futures_pozisyon_kapat(sembol, "SHORT", "BUY SİNYALİ")
            time.sleep(0.5)
        elif is_sell and pozisyon_var_mi(sembol, "LONG"):
            futures_pozisyon_kapat(sembol, "LONG", "SELL SİNYALİ")
            time.sleep(0.5)

        if (is_buy and not pozisyon_var_mi(sembol, "LONG")) or \
           (is_sell and not pozisyon_var_mi(sembol, "SHORT")):

            from engines.order_engine import get_order_engine, OrderRequest
            # v55: kaldıraç ve boyut yukarıda, risk kontrollerinden ÖNCE
            # hesaplandı — burada yeniden hesaplanmıyor.
            kaldirac = nihai_kaldirac
            kaldirac_ayarla(sembol, kaldirac)
            usdt = nihai_usdt

            levels = sl_tp_hesapla(fiyat, yon, atr, rejim)

            # v57: MİNİMUM R/R KAPISI — paper yoluyla AYNI kontrol (§5.3).
            # Bu kapı olmadan sistem, R/R'ı 0.77 olarak HESAPLAYIP yine de
            # emir gönderiyordu. Gerçek parada bu, matematiksel olarak
            # kaybetmesi garanti işlemler demek.
            if not rr_yeterli_mi(levels["rr"], sembol, rejim):
                return

            req    = OrderRequest(
                sembol=sembol, yon=yon, usdt=usdt,
                emir_tipi=emir_tipi, kaynak=sonuc.get("strateji","SIGNAL"),
                ai_score=sonuc["ai_score"], confidence=sonuc["confidence"],
                sl=levels["sl"], tp1=levels["tp1"], tp2=levels["tp2"],
                kaldirac=kaldirac, rejim=rejim
            )
            get_order_engine().submit(req)

    except FuturesAPIError as e:
        log.error(f"[FUTURES ENGINE AUTO] {sembol} API hatası: {e}")
    except Exception as e:
        log.critical(f"[FUTURES ENGINE AUTO] {sembol} beklenmedik hata: "
                     f"{type(e).__name__}: {e}", exc_info=True)


def _chandelier_stop_hesapla(sembol: str, yon: str,
                               guncel_fiyat: float, atr: float) -> float:
    """
    v19: Chandelier Exit — dinamik ATR trailing stop.
    LONG: stop = rolling_high(22) - 3 * ATR(22)
    SHORT: stop = rolling_low(22)  + 3 * ATR(22)

    Sabit callback yerine piyasa ATR'sini kullanır:
    - Trend döneminde geniş stop (volatiliteye uyumlu)
    - Sıkışık piyasada dar stop (sıkı koruma)
    """
    poz_key = f"{sembol}_{yon}"
    if poz_key not in _chandelier_state:
        _chandelier_state[poz_key] = {
            "high_deque": deque(maxlen=_CHANDELIER_PERIOD),
            "low_deque":  deque(maxlen=_CHANDELIER_PERIOD),
            "stop":       0.0,
        }
    state = _chandelier_state[poz_key]
    state["high_deque"].append(guncel_fiyat)
    state["low_deque"].append(guncel_fiyat)

    if len(state["high_deque"]) < 5:
        # Yeterli veri yok → basit ATR stop
        if yon == "LONG":
            return guncel_fiyat - atr * _CHANDELIER_MULT
        else:
            return guncel_fiyat + atr * _CHANDELIER_MULT

    rolling_high = max(state["high_deque"])
    rolling_low  = min(state["low_deque"])

    if yon == "LONG":
        yeni_stop = rolling_high - atr * _CHANDELIER_MULT
        # Chandelier sadece YUKARI hareket eder (trailing)
        state["stop"] = max(state["stop"], yeni_stop) if state["stop"] > 0 else yeni_stop
    else:
        yeni_stop = rolling_low + atr * _CHANDELIER_MULT
        # SHORT için stop sadece AŞAĞI hareket eder
        state["stop"] = min(state["stop"], yeni_stop) if state["stop"] > 0 else yeni_stop

    return round(state["stop"], 4)


def coklu_borsa_gecerli_mi(sembol: str, fiyat: float, yon: str,
                           sonuc: dict) -> tuple:
    """Binance fiyatı OTHER borsalarla doğrulanıyor mu? — v58 K-103.

    Döner: ``(gecerli, sebep)``

    ── NE YAPAR ─────────────────────────────────────────────────
    Binance + Bybit + OKX fiyatlarının MEDYANI alınır; Binance ondan
    `MULTIEX_MAX_SAPMA_PCT`'den fazla sapıyorsa işlem veto edilir.

    ⚠️ Bu kapı "başka borsada işlem yap" DEMEZ. Amacı, **kimsenin
    görmediği bir Binance fiyatına güvenmemek.** K-15'te tam bu yaşandı:
    testnet'te gerçek piyasada OLMAYAN bir sıçrama sahte bir "TP"
    üretmişti. Yani kapı, "sadece Binance verisi önemli" ilkesiyle
    çelişmez — onu KORUR.

    Diğer borsalara erişilemezse (`kaynak == 1`) doğrulama atlanır ve
    Binance'e güvenilir — o mantık `multi_exchange.py` içinde.

    ── NEDEN ORTAK ──────────────────────────────────────────────
    Bu kapı yalnızca `_execution_isle`'daydı; paper'da YOKTU.
    K-98'de "0 ateşleme" gerekçesiyle bırakılmıştı — sonra **347 kez**
    ateşledi (%4) ve paper yine canlıdan gevşek kaldı.
    ➜ *"Şu an ateşlemiyor" kalıcı bir gerekçe değil.* Koşullar
    değişince ayrışma geri geliyor.

    ⚠️ HATA HÂLİNDE FAIL-OPEN — canlının mevcut davranışı birebir
    korundu. Gerekçesi var: erişilemeyen borsa durumu `karsilastir`
    içinde zaten ele alınıyor; buradaki istisna gerçek bir arızadır ve
    OKX'in API'si bozuk diye tüm işlemleri durdurmak yanlış olurdu.
    ⚠️ Ama SESSİZ değil: canlıda `log.debug` ile yutuluyordu (§5.2'nin
    tarif ettiği desen), `warning`'e yükseltildi.
    """
    try:
        from data.multi_exchange import get_multiexchange
        mex = get_multiexchange().karsilastir(sembol, fiyat)
    except Exception as e:
        log.warning(f"[MULTIEX] {sembol} doğrulanamadı "
                    f"({type(e).__name__}: {e}) — kapı atlanıyor")
        return True, ""

    if not mex.guvenilir:
        return False, mex.sebep

    # Arbitraj yön sinyali — pozisyon boyutunu etkiler (veto DEĞİL)
    if mex.arbitraj_yon and mex.arbitraj_yon != yon and mex.arbitraj_gucu > 0.5:
        sonuc["_mex_celiski"] = True
    elif mex.arbitraj_yon == yon:
        sonuc["_mex_teyit"] = mex.arbitraj_gucu
    return True, ""


def sinyal_veto_zinciri(sonuc: dict, yon: str, bakiye_fn=None) -> tuple:
    """Sinyal kalitesi vetoları — PAPER ve CANLI için TEK KAYNAK. v58 K-97/K-98.

    Sıra (canlıdaki sırayla birebir):
      MTF cascade → MTF hizalama → EdgeEngine → strateji → sinyal filtresi

    `bakiye_fn` — strateji motoru için bakiye. TEMBEL çağrılır (callable
    verilebilir): MTF/edge'de ölecek sinyaller için gereksiz REST
    isteği yapılmasın diye (v55 notu; zaten HTTP 429 alıyoruz).

    Döner: ``(gecti, sebep, pozisyon_carpani)``
      gecti   — False ise işlem AÇILMAMALI
      sebep   — veto sayacı etiketi ("" ise veto yok)
      carpan  — pozisyon boyutu çarpanı (zayıf hizalamada 0.6)

    ── NEDEN VAR ────────────────────────────────────────────────
    Bu üç kapı `main.py::_execution_isle` içine gömülüydü ve
    `_execution_isle` `if not LIVE_TRADING: return` ile başlıyor —
    yani PAPER YOLUNDA HİÇ ÇALIŞMIYORLARDI.

    ÖLÇÜLEN SONUÇ (2026-09-14 07:15, saniyesi saniyesine):
        07:15:13.392  [TRADE AÇILDI] #1 ASTERUSDT      ← paper AÇTI
        07:15:14.640  [EXEC ISLE] ASTERUSDT MTF hizalama yok → atlandı
        07:16:01.493  [TRADE AÇILDI] #2 AAVEUSDT       ← paper AÇTI
        07:16:02.776  [EXEC ISLE] AAVEUSDT MTF hizalama yok → atlandı
    Aynı sembol, aynı saniye: paper açtı, canlı reddetti.

    ➜ Paper, canlının REDDEDECEĞİ işlemleri açıyordu. Toplanan 100
    işlemlik örneklem canlıyı TEMSİL ETMİYORDU — §5.3'ün tam olarak
    önlemek için var olduğu durum. §6.0'da "veto zincirini ortak
    modüle çıkar" diye v58'den beri açık duran iş.

    ⚠️ CANLI DAVRANIŞ DEĞİŞMEZ: sıra, eşikler ve varsayılanlar
    `_execution_isle`'dakiyle birebir aynı tutuldu. Değişen tek şey,
    paper'ın da bu kapılardan geçmesi.

    ⚠️ VARSAYILANLAR FAIL-CLOSED/OPEN AYRIMI KORUNDU:
      - `hizalama_skoru` yoksa 2 sayılır (veto yok) — eski davranış
      - `edge_sonuc` yoksa `gecti=False` → VETO (eski davranış)
    İkisi de bilerek; değiştirmek davranış değişikliği olurdu.
    """
    mtf = sonuc.get("mtf_confluence") or {}

    # 1) MTF cascade — taban TF, ana trend TF'siyle ters yönde
    if mtf.get("bloklu", False):
        return False, "mtf_cascade", 1.0

    # 2) MTF hizalama — hiç hizalı TF yoksa veto, tek TF varsa küçült
    hizalama = mtf.get("hizalama_skoru", 2)
    carpan = 1.0
    if hizalama == 0:
        return False, "mtf_hizalama_yok", 1.0
    elif hizalama == 1:
        carpan = 0.6

    # 3) EdgeEngine
    edge = sonuc.get("edge_sonuc") or {}
    if not edge.get("gecti", False):
        return False, "edge_engine", carpan

    # 4) STRATEJİ MOTORU — v58 (K-98)
    # ÖLÇÜLDÜ: canlı vetoların %12'si (804 kez) buradan geliyordu ve
    # paper'da HİÇ YOKTU. K-97'den SONRA açılan ilk paper işlemi
    # (PAXGUSDT SHORT, 2026-09-14 19:21) canlı tarafta tam bu kapıya
    # takıldı: "[EXEC ISLE] PAXGUSDT: Trend follow koşulu sağlanmadı".
    # Yani K-97 üç kapıyı kapattı ama ayrışma bir kapı aşağıda sürüyordu.
    #
    # ⚠️ `bakiye_fn` TEMBEL: strateji motoru bakiye istiyor ama bakiyeyi
    # ÖNCEDEN çekmek, MTF/edge'de zaten ölecek sinyaller için gereksiz
    # REST çağrısı demektir (v55 notu: "sinyal başına gereksiz REST +
    # rate-limit tüketimi"; zaten 429 alıyoruz). Bu yüzden çağrı buraya
    # kadar ERTELENİYOR.
    if _strategy_engine is not None:
        try:
            _bakiye = bakiye_fn() if callable(bakiye_fn) else (bakiye_fn or 0.0)
        except Exception as e:
            log.warning(f"[VETO] bakiye alınamadı, strateji kapısı "
                        f"atlanamaz: {type(e).__name__}: {e}")
            return False, "strateji_bakiye_hata", carpan   # §5.1 fail-closed
        karar = _strategy_engine.karar_ver(sonuc, _bakiye)
        if not karar.get("islem_yap", False):
            sonuc["_strateji_sebep"] = karar.get("sebep", "")
            return False, "strateji_red", carpan
        # Canlı yol bu iki alanı karardan yazıyordu — taşınırken korundu.
        sonuc["strateji"]   = karar.get("strateji", "TREND_FOLLOW")
        sonuc["trade_usdt"] = karar.get("usdt", 20)

    # 5) SİNYAL FİLTRESİ (rejim eşiği dahil) — v58 (K-98)
    # Canlı bunu GİRİŞTE uyguluyordu; paper yalnızca ÇIKIŞTA
    # (`_cikis_gecerli`, K-13). Sayacı 0 görünüyordu ama bu MASKELEMEYDİ:
    # zincirde `strateji_red`'den SONRA geldiği için sinyaller ona
    # ulaşmadan ölüyordu.
    if not sinyal_gecerli_mi(sonuc, yon):
        return False, "sinyal_filtresi", carpan

    return True, "", carpan


def giris_kayma_esigi(atr_pct: float) -> float:
    """Sinyal→giriş arası kabul edilebilir aleyhte kayma (%). v58 K-95.

    ── NEDEN VAR ────────────────────────────────────────────────
    Hesap `main.py::_execution_isle` içine gömülüydü ve yalnızca
    kaynak metni aranarak test edilebiliyordu. Bu oturumda o yöntemin
    bir davranışı KİLİTLEMEDİĞİ üç kez görüldü (§0.29, §0.36) — yorum
    satırını yakalayan, temiz kodda kırmızı kalan testler çıktı.
    Ayrı fonksiyon davranışsal teste açar ve tek kaynak olur.

    ── FORMÜL ───────────────────────────────────────────────────
        eşik = min(taban + ATR%×0.15,  tavan)
        tavan = max(taban×2,  ATR% × SL_ÇARPAN × STOP_PAYI)

    Normal ATR aralığında BAĞLAYICI OLAN asıl uyarlama terimidir;
    tavan yalnızca bozuk/absürt ATR'ye karşı akıl sağlığı sınırı.

    ── ESKİ HÂLİ NEDEN YANLIŞTI (§0.35 Bulgu 2) ────────────────
    Tavan `MAX_GIRIS_KAYMA_PCT * 2` = %0.70 MUTLAK sabitti:
        tavanın bağladığı nokta : ATR% > 2.33
        medyan 4h ATR%          : 2.43   ← medyan coin ZATEN tavanda
        tavana dayanan          : 27/50 (%54)
        ETHFIUSDT ATR%=6.81     : amaçlanan %1.37 → kırpılmış %0.70
    "Oynaklığa göre esne" diye yazılmış uyarlama, 4h'de esnemiyordu.
    Kök neden K-78/K-82/K-83 ile aynı sınıf: %0.35 tabanı 5m döneminde
    kalibre edilmişti (sinyal fiyatı ≤5 dk bayat); 4h'de aynı fiyat
    4 SAATE kadar bayat olabiliyor.

    ⚠️ TAVAN SL ÇARPANINDAN TÜRÜYOR, sabit değil: stop mesafesi
    SL_ÇARPAN×ATR, girişten önce onun en fazla STOP_PAYI kadarını
    veriyoruz. SL politikası değişirse tavan peşinden gelir.
    """
    try:
        from config import (MAX_GIRIS_KAYMA_PCT, MAX_GIRIS_KAYMA_STOP_PAYI,
                            FUTURES_SL_ATR_MULT as _SL_MULT)
    except ImportError:
        MAX_GIRIS_KAYMA_PCT, MAX_GIRIS_KAYMA_STOP_PAYI, _SL_MULT = 0.35, 0.3333, 1.5
    try:
        a = float(atr_pct)
    except (TypeError, ValueError):
        a = 0.0
    if a < 0 or a != a:          # negatif / NaN → ATR bilinmiyor
        a = 0.0
    tavan = max(MAX_GIRIS_KAYMA_PCT * 2,
                a * _SL_MULT * MAX_GIRIS_KAYMA_STOP_PAYI)
    return min(MAX_GIRIS_KAYMA_PCT + a * 0.15, tavan)


def tasfiye_fiyati(giris: float, yon: str, kaldirac: float) -> float:
    """Pozisyonun tasfiye (liquidation) fiyatı — TEK KAYNAK (v58 K-88).

    İzole marjin yaklaşımı:
        aleyhte_oran = 1/kaldıraç − bakım_marjın_oranı
        LONG  → giriş × (1 − aleyhte_oran)
        SHORT → giriş × (1 + aleyhte_oran)

    3x → ~%32.9 · 10x → ~%9.5 aleyhte hareket.

    ⚠️ YAKLAŞIKLIK: Binance kademeli (tiered) bakım marjı uygular ve
    büyük notional'da oran yükselir. Bu model tek oran kullanıyor —
    küçük pozisyonlar için yeterince doğru, dev pozisyonlarda iyimser.
    `risk_manager` zaten borsanın verdiği `likidasyon_fiyat` varsa ONU
    tercih ediyor; bu fonksiyon paper simülasyonu içindir.

    Kaldıraç 1 ise tasfiye YOKTUR (spot gibi) → 0 döner.
    """
    try:
        from config import BAKIM_MARJIN_ORANI as _bm
    except ImportError:
        _bm = 0.004
    try:
        k = float(kaldirac)
    except (TypeError, ValueError):
        return 0.0
    if giris <= 0 or k <= 1.0:
        return 0.0
    aleyhte = (1.0 / k) - _bm
    if aleyhte <= 0:
        return 0.0
    return giris * (1 - aleyhte) if yon == "LONG" else giris * (1 + aleyhte)


def islem_kaldiraci(fiyat: float, atr: float, sembol: str = None) -> int:
    """Bu işlemde kullanılacak kaldıraç — TEK KAYNAK (v58 K-86).

    ── NEDEN VAR ────────────────────────────────────────────────
    Canlı yol `dinamik_kaldirac_hesapla()` + rejim tavanı ile gerçek
    kaldıracı hesaplayıp `kaldirac_ayarla()` ile borsaya kuruyordu.
    Paper ise `kaldirac=1` SABİT KODLUYDU (paper_trading.py:486).

    Sonuç: paper 1x spot gibi davranıyordu. Aynı fiyat hareketi
    canlıda bağlanan sermayenin KAT KAT fazlasını etkiler:
        notional 60 USDT · 3x  →  marjin 20 USDT
        %2 aleyhte hareket     →  -1.2 USDT = marjinin %6'sı
    Paper'da ise 60 USDT bağlanıp %2 = marjinin %2'si yazılıyordu.
    §5.3 gereği 100 işlemlik örneklem canlıyı temsil etmiyordu.

    ⚠️ PnL'in USDT tutarını kaldıraç DEĞİŞTİRMEZ — değiştirdiği şey
    BAĞLANAN SERMAYEDİR. Bu yüzden `pnl_yuzde` notional üzerinden
    kalır (karar kuralının eşiği ona göre yazıldı); kaldıracın etkisi
    bakiye/marjin tarafında görünür.
    """
    try:
        from config import FUTURES_LEVERAGE, FUTURES_LEVERAGE_MIN
    except ImportError:
        FUTURES_LEVERAGE, FUTURES_LEVERAGE_MIN = 3, 2
    kaldirac = FUTURES_LEVERAGE
    try:
        # Bu modülün kendi kaydettiği örnek (`risk_manager_set`) —
        # canlı yolun 313. satırda kullandığı AYNI nesne.
        if _risk_manager:
            kaldirac = _risk_manager.dinamik_kaldirac_hesapla(fiyat, atr)
    except Exception as e:
        log.warning(f"[KALDIRAÇ] dinamik hesap başarısız, varsayılan "
                    f"{FUTURES_LEVERAGE}x: {type(e).__name__}: {e}")
    try:
        from strategy.regime_adapter import get_regime_adapter
        kaldirac = get_regime_adapter().efektif_kaldirac(kaldirac, sembol)
    except Exception as e:
        log.debug(f"[KALDIRAÇ] rejim tavanı uygulanamadı: {e}")
    return max(int(FUTURES_LEVERAGE_MIN), int(kaldirac))


def zaman_stop_doldu_mu(acilis_ts) -> tuple:
    """Pozisyon, modelin etiket ufkunu AŞTI mı? (v58 K-85)

    ── NEDEN VAR ────────────────────────────────────────────────
    SL/TP ATR tabanlı ve %3-5 uzakta; yatay piyasada günlerce
    tetiklenmiyor. ÖLÇÜM (2026-09-13): 10 açık pozisyonun 10'u da
    24-34 saattir açık ve HİÇBİRİ SL/TP'ye değmemiş. Kapanış hızı
    0.70/gün → 100 kapanmış işlem ~144 gün. Slotlar dolu kalıyor.

    ── NEDEN BU SÜRE ────────────────────────────────────────────
    `ZAMAN_STOP_BAR` varsayılanı `HEDEF_MAX_BAR` — üçlü bariyerin
    DİKEY UFKU. Model etiketleri "önümüzdeki N bar içinde ne olacak"
    sorusuna göre üretiliyor; o ufkun ötesinde tutmak modelin hakkında
    iddiası olmayan bir pozisyonu tutmaktır (K-22 ile aynı ilke).

    ⚠️ TEK KAYNAK: paper ve canlı yol AYNI fonksiyonu çağırır.
    Ayrı ayrı yazılsaydı biri güncellenip diğeri unutulurdu — §5.3'ün
    bu kod tabanında defalarca kırıldığı yer tam olarak burası.

    Döner: (doldu_mu, gecen_saat)
    """
    try:
        from config import ZAMAN_STOP_SN
    except ImportError:
        return False, 0.0
    if not acilis_ts or ZAMAN_STOP_SN <= 0:
        return False, 0.0
    try:
        if isinstance(acilis_ts, str):
            ts = datetime.fromisoformat(acilis_ts)
        else:
            ts = acilis_ts
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        gecen = (datetime.utcnow() - ts).total_seconds()
    except (ValueError, TypeError) as e:
        # §5.1 fail-closed DEĞİL: zamanı okuyamıyorsak pozisyonu
        # kapatmak da yanlış olur. Görünür uyarı bırakıp dokunmuyoruz.
        log.warning(f"[ZAMAN STOP] açılış zamanı okunamadı ({acilis_ts!r}): {e}")
        return False, 0.0
    return gecen >= ZAMAN_STOP_SN, gecen / 3600.0


def futures_pozisyon_izle(sembol: str, atr: float = 0.0) -> None:
    """
    v19: Chandelier Exit ile geliştirilmiş pozisyon izleme.
    atr parametresi coin_analiz'den iletilir (anlık ATR).
    """
    try:
        pozlar = acik_futures_pozisyonlar()
        for poz in pozlar:
            if poz["sembol"] != sembol:
                continue
            guncel = futures_anlık_fiyat(sembol)
            if not guncel:
                continue
            giris   = poz["giris"]; yon = poz["yon"]
            pnl_pct = ((guncel - giris) / giris * 100) * (1 if yon == "LONG" else -1)

            # ── v58 (K-85): ZAMAN STOP (canlı yol) ───────────────
            # Paper ile AYNI fonksiyon — §5.3. Canlıda SL/TP borsada
            # DURAN emirlerdir, zaman stop ise botun aktif kapatmasıdır;
            # bu yüzden burada, izleme döngüsünde uygulanır.
            #
            # Açılış zamanı borsadan gelmiyor — botun KENDİ state'inden
            # okunuyor (`position_state.acilis_ts`). State yoksa zaman
            # stop uygulanmaz ve bu GÖRÜNÜR olur (sessizce atlanmaz).
            try:
                # `acik_pozisyonlar()` state'teki kayıtları döner;
                # ayrı bir getirici yok, sembolle eşleştiriyoruz.
                from engines.position_state import get_state_manager
                _st = next((x for x in get_state_manager().acik_pozisyonlar()
                            if x.get("sembol") == sembol), None)
                _ts = (_st or {}).get("acilis_ts")
                if not _ts:
                    log.warning(f"[ZAMAN STOP] {sembol} açılış zamanı state'te "
                                f"YOK — zaman stop uygulanamıyor")
                else:
                    _doldu, _saat = zaman_stop_doldu_mu(_ts)
                    if _doldu:
                        log.info(f"[ZAMAN STOP] {sembol} {yon} — {_saat:.1f} "
                                 f"saattir açık, model ufku aşıldı, kapatılıyor")
                        futures_pozisyon_kapat(sembol, yon, sebep="ZAMAN_STOP")
                        continue
            except Exception as _zs_e:
                log.warning(f"[ZAMAN STOP] {sembol} kontrol başarısız: {_zs_e}")

            if pnl_pct < -8:
                bus = get_bus()
                bus.publish(Event.ALERT, {
                    "sembol": sembol, "yon": yon, "pnl_pct": pnl_pct,
                    "mesaj":  f"YÜKSEK KAYIP: %{pnl_pct:.2f}"
                }, "FuturesEngine")

            poz_key = f"{sembol}_{yon}"

            # v19: Chandelier Exit — %1 karda devreye gir (eskisi %1.8)
            if FUTURES_TRAILING_STOP and pnl_pct > 1.0 and atr > 0:
                chandelier_stop = _chandelier_stop_hesapla(sembol, yon, guncel, atr)

                # Chandelier stop tetiklendi mi?
                stop_tetiklendi = (yon == "LONG"  and guncel < chandelier_stop) or \
                                  (yon == "SHORT" and guncel > chandelier_stop)

                if stop_tetiklendi:
                    log.warning(f"[CHANDELIER] {sembol} {yon} STOP TETİKLENDİ "
                                f"guncel={guncel:,.4f} stop={chandelier_stop:,.4f} "
                                f"PnL=%{pnl_pct:.2f}")
                    # Binance trailing stop yerleştir (callback hesapla)
                    try:
                        mesafe_pct = abs(guncel - chandelier_stop) / guncel * 100
                        callback   = max(round(mesafe_pct, 1), 0.5)  # min %0.5
                        sembol_tum_emirleri_iptal(sembol)
                        time.sleep(0.3)
                        futures_trailing_stop_koy(sembol, yon, callback)
                        log.info(f"[CHANDELIER] {sembol} trailing stop güncellendi "
                                 f"callback=%{callback:.1f}")
                    except FuturesAPIError as e:
                        log.error(f"[CHANDELIER] {sembol} trailing stop hatası: {e}")

                elif poz_key not in _tp1_tamamlandi and pnl_pct > 1.8:
                    # İlk %1.8 karda normal trailing başlat (fallback)
                    _tp1_tamamlandi.add(poz_key)
                    try:
                        sembol_tum_emirleri_iptal(sembol)
                        time.sleep(0.3)
                        futures_trailing_stop_koy(sembol, yon, FUTURES_TRAILING_CALLBACK)
                        log.info(f"[İZLE] {sembol} {yon} başlangıç trailing stop eklendi")
                    except FuturesAPIError as e:
                        log.error(f"[İZLE] {sembol} trailing stop hatası: {e}")

            elif FUTURES_TRAILING_STOP and poz_key not in _tp1_tamamlandi and pnl_pct > 1.8:
                # atr=0 ise eski davranış
                _tp1_tamamlandi.add(poz_key)
                try:
                    sembol_tum_emirleri_iptal(sembol)
                    time.sleep(0.3)
                    futures_trailing_stop_koy(sembol, yon, FUTURES_TRAILING_CALLBACK)
                    log.info(f"[İZLE] {sembol} {yon} trailing stop eklendi")
                except FuturesAPIError as e:
                    log.error(f"[İZLE] {sembol} trailing stop hatası: {e}")

    except FuturesAPIError as e:
        log.error(f"[FUTURES İZLE] {sembol} API hatası: {e}")
    except Exception as e:
        log.error(f"[FUTURES İZLE] {sembol} beklenmedik hata: {type(e).__name__}: {e}")
