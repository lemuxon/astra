from utils.exceptions import OrderRejectError, DBWriteError, TradingHaltedError
# =========================================================
# ASTRA v30.0 — EXECUTION ENGINE (Production Grade) — FIXED
# Düzeltmeler:
#   1. futures_emir_gonder → futures_market_ac (doğru fonksiyon adı)
#   2. futures_sl_tp_koy   → futures_stop_loss_koy + futures_take_profit_koy / futures_partial_tp_koy
#   3. guard.kontrol() + guard.kaydet() → guard.isle() context manager API'si
#   4. LIVE_TRADING=False'ta paper sonucu düzgün döndürülüyor
# =========================================================
import logging, time
from dataclasses import dataclass, field
from typing import Optional
import sys; sys.path.append("..")
from config import (LIVE_TRADING, FUTURES_LEVERAGE, MAX_SLIPPAGE_PCT,
                    FILL_VERIFY_TIMEOUT, FILL_VERIFY_INTERVAL,
                    FUTURES_SL_ATR_MULT, FUTURES_TP_ATR_MULT,
                    FUTURES_PARTIAL_TP, FUTURES_PARTIAL_TP_PCT)
from engines.event_bus import get_bus, Event

log = logging.getLogger("ASTRA.EXEC")

@dataclass
class ExecutionSonuc:
    basarili:     bool
    sembol:       str
    yon:          str
    exec_fiyat:   float
    exec_miktar:  float
    slippage_pct: float
    sl_aktif:     bool
    tp_aktif:     bool
    order_id:     str
    hata:         str         = ""
    sure_saniye:  float       = 0.0
    detay:        dict        = field(default_factory=dict)

    def __str__(self):
        if self.basarili:
            return (f"✅ {self.sembol} {self.yon} @ {self.exec_fiyat:.4f} "
                    f"slip:%{self.slippage_pct:.3f} SL:{'✓' if self.sl_aktif else '✗'} "
                    f"TP:{'✓' if self.tp_aktif else '✗'} ({self.sure_saniye:.1f}s)")
        return f"❌ {self.sembol} {self.yon}: {self.hata}"


class ExecutionEngine:

    def __init__(self, risk_manager=None, state_manager=None):
        self._risk   = risk_manager
        self._state  = state_manager
        self._bus    = get_bus()
        self._istatistik = {
            "acma_girişim": 0, "acma_basarili": 0, "acma_basarisiz": 0,
            "kapama_girişim": 0, "kapama_basarili": 0, "kapama_basarisiz": 0,
            "sl_basarisiz": 0, "slippage_red": 0, "duplicate_engel": 0,
        }
        try:
            from execution.duplicate_guard import DuplicateGuard
            self._guard = DuplicateGuard()
        except Exception:
            self._guard = None
        # v22: Smart execution (TWAP/VWAP)
        try:
            from execution.smart_execution import get_smart_executor
            self._smart = get_smart_executor()
        except Exception:
            self._smart = None

    # ── Pozisyon Aç ───────────────────────────────────────
    def pozisyon_ac(self, sembol: str, yon: str, usdt: float,
                    sl: float, tp1: float, tp2: float,
                    kaldirac: int = FUTURES_LEVERAGE,
                    rejim: str = "RANGE",
                    ai_score: int = 0,
                    kaynak: str = "SIGNAL") -> ExecutionSonuc:

        self._istatistik["acma_girişim"] += 1
        baslangic = time.time()

        # ── v53 SON SAVUNMA: Minimum işlem boyutu kontrolü ──
        # Bu, TÜM çağıranları koruyan tek nokta. Yukarı katmanlar
        # (Kelly, adaptive sizing, MVO, damp çarpanları) 0 veya çok
        # küçük bir boyut üretebilir — örneğin negatif Kelly'de veya
        # düşük bakiyede. main.py'de bu kontrol YOKTU; 0 USDT'lik emir
        # borsaya gidip "min notional" hatası alırdı ya da miktar 0
        # hesaplanırdı. Burada tek noktadan engelleniyor.
        MIN_ISLEM_USDT = 5.0
        if not usdt or usdt < MIN_ISLEM_USDT:
            log.info(f"[EXEC] {sembol} {yon} pozisyon boyutu {usdt:.2f}$ < "
                     f"minimum {MIN_ISLEM_USDT}$ → işlem açılmadı "
                     f"(risk katmanları küçültmüş olabilir)")
            self._istatistik["acma_basarisiz"] += 1
            return ExecutionSonuc(
                basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                order_id="", hata=f"Pozisyon boyutu çok küçük ({usdt:.2f}$)"
            )

        if not LIVE_TRADING:
            return ExecutionSonuc(
                basarili=True, sembol=sembol, yon=yon, exec_fiyat=0,
                exec_miktar=0, slippage_pct=0, sl_aktif=True, tp_aktif=True,
                order_id="PAPER"
            )

        from data.binance_futures_client import (
            futures_market_ac, kaldirac_ayarla,
            futures_stop_loss_koy, futures_take_profit_koy, futures_partial_tp_koy,
            acik_futures_pozisyonlar, futures_anlık_fiyat,
            pozisyon_var_mi, duplicate_kontrol, FuturesAPIError
        )

        try:
            # ── DuplicateGuard: context manager API kullan ──
            if self._guard:
                with self._guard.isle(sembol, yon) as izin:
                    if not izin:
                        self._istatistik["duplicate_engel"] += 1
                        log.warning(f"[EXEC] Duplicate engellendi: {sembol} {yon}")
                        return ExecutionSonuc(
                            basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                            exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                            order_id="", hata="Duplicate engellendi"
                        )
                    return self._pozisyon_ac_impl(
                        sembol, yon, usdt, sl, tp1, tp2,
                        kaldirac, rejim, ai_score, kaynak, baslangic,
                        futures_market_ac, kaldirac_ayarla,
                        futures_stop_loss_koy, futures_take_profit_koy,
                        futures_partial_tp_koy, acik_futures_pozisyonlar,
                        futures_anlık_fiyat, FuturesAPIError
                    )
            else:
                return self._pozisyon_ac_impl(
                    sembol, yon, usdt, sl, tp1, tp2,
                    kaldirac, rejim, ai_score, kaynak, baslangic,
                    futures_market_ac, kaldirac_ayarla,
                    futures_stop_loss_koy, futures_take_profit_koy,
                    futures_partial_tp_koy, acik_futures_pozisyonlar,
                    futures_anlık_fiyat, FuturesAPIError
                )

        except Exception as e:
            self._istatistik["acma_basarisiz"] += 1
            log.critical(f"[EXEC] Açma beklenmedik hata: {type(e).__name__}: {e}", exc_info=True)
            return ExecutionSonuc(
                basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                order_id="", hata=f"{type(e).__name__}: {e}"
            )

    def _pozisyon_ac_impl(self, sembol, yon, usdt, sl, tp1, tp2,
                           kaldirac, rejim, ai_score, kaynak, baslangic,
                           futures_market_ac, kaldirac_ayarla,
                           futures_stop_loss_koy, futures_take_profit_koy,
                           futures_partial_tp_koy, acik_futures_pozisyonlar,
                           futures_anlık_fiyat, FuturesAPIError):
        try:
            # ── v51 FAIL-SAFE: SL/TP yön doğrulaması (emirden ÖNCE) ──
            # LONG'da SL girişin ALTINDA, TP ÜSTÜNDE olmalı; SHORT'ta tersi.
            # Yanlış taraftaki SL ya reddedilir ya da pozisyon açılır açılmaz
            # tetiklenir → her işlemde otomatik zarar. Şüphede işlem YAPMA.
            _ref_fiyat = 0.0
            try:
                _ref_fiyat = float(futures_anlık_fiyat(sembol) or 0)
            except Exception:
                _ref_fiyat = 0.0

            _sl_hata = ""
            if not sl or sl <= 0:
                _sl_hata = f"SL geçersiz ({sl}) — korumasız işlem açılmaz"
            elif _ref_fiyat > 0:
                if yon.upper() == "LONG":
                    if sl >= _ref_fiyat:
                        _sl_hata = (f"LONG SL ({sl}) fiyatın ({_ref_fiyat}) ÜSTÜNDE "
                                    f"— anında tetiklenirdi")
                    elif tp1 and tp1 <= _ref_fiyat:
                        _sl_hata = f"LONG TP ({tp1}) fiyatın ({_ref_fiyat}) ALTINDA"
                elif yon.upper() == "SHORT":
                    if sl <= _ref_fiyat:
                        _sl_hata = (f"SHORT SL ({sl}) fiyatın ({_ref_fiyat}) ALTINDA "
                                    f"— anında tetiklenirdi")
                    elif tp1 and tp1 >= _ref_fiyat:
                        _sl_hata = f"SHORT TP ({tp1}) fiyatın ({_ref_fiyat}) ÜSTÜNDE"

            if _sl_hata:
                log.critical(f"[EXEC] 🛑 {sembol} {yon} SL/TP DOĞRULAMA HATASI: "
                             f"{_sl_hata} → işlem AÇILMADI (fail-safe)")
                self._istatistik["acma_basarisiz"] += 1
                return ExecutionSonuc(
                    basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                    exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                    order_id="", hata=f"SL/TP doğrulama: {_sl_hata}"
                )

            # Risk kontrolleri
            if self._risk:
                from data.binance_futures_client import futures_bakiye
                bakiye = futures_bakiye()
                if self._risk.gunluk_limit_kontrol(bakiye):
                    return ExecutionSonuc(
                        basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                        exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                        order_id="", hata="Günlük kayıp limiti aşıldı"
                    )
                # v55: strict=True — ağ hatasında [] dönmesi, "hiç açık pozisyon
                # yok" anlamına gelirdi ve HEM max-pozisyon HEM korelasyon
                # limitleri sessizce geçilirdi (fail-open).
                try:
                    pozlar = acik_futures_pozisyonlar(strict=True)
                except Exception as pz_e:
                    log.error(f"[EXEC] Pozisyon listesi alınamadı: {pz_e} "
                              f"→ risk limitleri doğrulanamadı, işlem reddedildi")
                    return ExecutionSonuc(
                        basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                        exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                        order_id="", hata="Pozisyon durumu doğrulanamadı (fail-safe)"
                    )
                if self._risk.acik_pozisyon_kontrol(pozlar):
                    return ExecutionSonuc(
                        basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                        exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                        order_id="", hata="Max açık pozisyon limiti"
                    )
                if self._risk.korrelasyon_kontrol(pozlar, yon):
                    return ExecutionSonuc(
                        basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                        exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                        order_id="", hata="Korelasyon limiti"
                    )

            # Kaldıraç ayarla
            try:
                kaldirac_ayarla(sembol, kaldirac)
            except Exception as kl_e:
                log.warning(f"[EXEC] Kaldıraç ayar hatası: {kl_e}")

            # Güncel fiyat (slippage referansı için)
            guncel_fiyat = futures_anlık_fiyat(sembol) or 0

            # ── v22: Smart Execution (TWAP/VWAP) — büyük emirleri böl ──
            try:
                if self._smart:
                    # Volatilite hesapla (ATR proxy)
                    _vol_pct = 1.0
                    try:
                        from data.binance_futures_client import futures_anlık_fiyat as _faf
                        # rejim VOLATILE ise volatiliteyi yüksek varsay
                        _vol_pct = 3.5 if rejim == "VOLATILE" else 1.5
                    except Exception as _e:
                        log.debug(f"[EXEC] volatilite tahmini atlandı: {_e}")

                    plan = self._smart.plan_olustur(
                        sembol, yon, usdt,
                        volatilite_pct=_vol_pct,
                        likidite_dusuk=(rejim == "VOLATILE"),
                    )
                    if plan.yontem != "MARKET":
                        log.info(f"[EXEC] Smart execution: {plan}")
                        smart_sonuc = self._smart.calistir(
                            plan, futures_market_ac, futures_anlık_fiyat
                        )
                        if smart_sonuc.get("basarili"):
                            # Smart execution sonucunu order formatına çevir
                            order = {
                                "orderId": "SMART_" + str(int(time.time())),
                                "avgPrice": smart_sonuc["ort_fiyat"],
                                "executedQty": smart_sonuc["toplam_miktar"],
                                "_smart": smart_sonuc,
                            }
                            log.info(f"[EXEC] Smart exec tamamlandı: "
                                     f"{plan.yontem} ort={smart_sonuc['ort_fiyat']:.4f} "
                                     f"slippage={smart_sonuc['slippage_bps']:.1f}bps")
                        else:
                            # ── v54 KRİTİK: Fallback öncesi GERÇEK pozisyon kontrolü ──
                            # Senaryo: TWAP 1. dilim borsada DOLDU ama yanıt
                            # ayrıştırılamadı → basarili_dilim=0 → "başarısız".
                            # Fallback tam market emri gönderirse ya aşırı
                            # pozisyon açılır ya da duplicate_kontrol None döner
                            # ve sistem "işlem yok" sanar — oysa borsada SL'siz
                            # bir pozisyon durur (hayalet pozisyon).
                            _gercek_poz = None
                            try:
                                for _p in (acik_futures_pozisyonlar() or []):
                                    if (_p.get("sembol") or _p.get("symbol", "")).upper() == sembol \
                                       and abs(float(_p.get("miktar", 0) or _p.get("positionAmt", 0) or 0)) > 0:
                                        _gercek_poz = _p
                                        break
                            except Exception as _pe:
                                log.error(f"[EXEC] Fallback öncesi pozisyon sorgusu "
                                          f"başarısız: {_pe}")

                            if _gercek_poz:
                                # Kısmi dolum gerçekleşmiş → fallback GÖNDERME.
                                # Var olan pozisyonu tanı, SL/TP akışı devam etsin.
                                _mevcut_miktar = abs(float(
                                    _gercek_poz.get("miktar", 0)
                                    or _gercek_poz.get("positionAmt", 0) or 0))
                                _mevcut_giris = float(
                                    _gercek_poz.get("giris", 0)
                                    or _gercek_poz.get("entryPrice", 0) or 0)
                                log.warning(f"[EXEC] ⚠️ Smart exec 'başarısız' bildirdi AMA "
                                            f"borsada {sembol} pozisyonu VAR "
                                            f"({_mevcut_miktar} @ {_mevcut_giris}). "
                                            f"Fallback emri GÖNDERİLMİYOR (aşırı pozisyon "
                                            f"önlendi); mevcut pozisyona SL/TP konacak.")
                                order = {
                                    "orderId": f"RECOVERED_{int(time.time())}",
                                    "avgPrice": _mevcut_giris or guncel_fiyat,
                                    "executedQty": _mevcut_miktar,
                                    "_recovered": True,
                                }
                            else:
                                # Gerçekten pozisyon yok → güvenle fallback
                                order = futures_market_ac(sembol, yon, usdt)
                    else:
                        order = futures_market_ac(sembol, yon, usdt)
                else:
                    order = futures_market_ac(sembol, yon, usdt)
            except Exception as ac_e:
                log.error(f"[EXEC] futures_market_ac hatası: {ac_e}")
                self._istatistik["acma_basarisiz"] += 1
                return ExecutionSonuc(
                    basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                    exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                    order_id="", hata=f"Emir hatası: {ac_e}"
                )

            if not order or not order.get("orderId"):
                self._istatistik["acma_basarisiz"] += 1
                return ExecutionSonuc(
                    basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                    exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                    order_id="", hata="Emir gönderme başarısız"
                )

            exec_fiyat  = float(order.get("avgPrice", 0)) or guncel_fiyat
            exec_miktar = float(order.get("executedQty", 0))

            # ── v52 KRİTİK: SIFIR / KISMİ DOLUM TESPİTİ ──
            # Eskiden sadece orderId varlığı kontrol ediliyordu. Emir
            # gönderilip HİÇ dolmamış olabilir (executedQty=0) — o durumda
            # SL koymaya çalışmak anlamsızdır (ortada pozisyon yok) ve
            # v51 mantığı "pozisyonu kapat" derken var olmayan pozisyonu
            # kapatmaya çalışırdı. Kısmi dolumda ise SL/TP tam miktara
            # koyulup borsada miktar uyuşmazlığı oluşurdu.
            if exec_miktar <= 0:
                log.error(f"[EXEC] {sembol} {yon} emir gönderildi ama HİÇ DOLMADI "
                          f"(executedQty=0). Pozisyon açılmadı, iptal ediliyor.")
                try:
                    from data.binance_futures_client import futures_emir_iptal
                    futures_emir_iptal(sembol, order.get("orderId"))
                except Exception as _ie:
                    log.debug(f"[EXEC] Dolmayan emir iptali atlandı: {_ie}")
                self._istatistik["acma_basarisiz"] += 1
                return ExecutionSonuc(
                    basarili=False, sembol=sembol, yon=yon, exec_fiyat=exec_fiyat,
                    exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                    order_id=str(order.get("orderId", "")),
                    hata="Emir dolmadı (executedQty=0)"
                )

            # Kısmi dolum: beklenen miktarın %90'ından azı dolduysa uyar.
            # İşlem iptal edilmez (pozisyon gerçek), ancak SL/TP GERÇEK
            # dolan miktara göre yerleştirilmeli ve operatör bilgilendirilmeli.
            # v53 DÜZELTME: usdt burada NOTIONAL (pozisyon değeri), marjin
            # DEĞİL — futures_market_ac `miktar = usdt/fiyat` hesaplıyor.
            # v52'de yanlışlıkla kaldıraçla çarpılıyordu; bu her işlemde
            # sahte "kısmi dolum" uyarısı üretirdi (oran = 1/kaldıraç).
            if exec_fiyat > 0 and usdt > 0:
                beklenen_miktar = usdt / exec_fiyat
                if beklenen_miktar > 0:
                    dolum_orani = exec_miktar / beklenen_miktar
                    if dolum_orani < 0.90:
                        log.warning(f"[EXEC] ⚠️ {sembol} KISMİ DOLUM: beklenen "
                                    f"{beklenen_miktar:.6f}, dolan {exec_miktar:.6f} "
                                    f"(%{dolum_orani*100:.1f}). SL/TP gerçek "
                                    f"miktara göre koyulacak.")

            # Slippage hesapla
            slippage_pct = 0.0
            if guncel_fiyat > 0 and exec_fiyat > 0:
                slippage_pct = abs(exec_fiyat - guncel_fiyat) / guncel_fiyat * 100

            # v23: Smart execution (TWAP/VWAP) emirleri zaten ortalama fiyatla doldu;
            # çok-saniyeli execution sırasında fiyat hareketi normal slippage testini
            # yanlışlıkla tetikleyip doğru dolan pozisyonu kapatabilir → atla.
            _smart_dolduruldu = isinstance(order, dict) and "_smart" in order
            if _smart_dolduruldu and slippage_pct > MAX_SLIPPAGE_PCT:
                log.info(f"[EXEC] {sembol} smart-exec slippage %{slippage_pct:.3f} "
                         f"— TWAP ortalaması olduğu için kapatma atlandı")

            if slippage_pct > MAX_SLIPPAGE_PCT and not _smart_dolduruldu:
                self._istatistik["slippage_red"] += 1
                log.warning(f"[EXEC] Slippage aşıldı %{slippage_pct:.3f} > %{MAX_SLIPPAGE_PCT} — pozisyon kapatılıyor")
                # ── v52 KRİTİK: HAYALET POZİSYON ÖNLEME ──
                # Eskiden kapatma hatası `except: pass` ile yutuluyordu:
                # fonksiyon "başarısız" dönerken pozisyon borsada AÇIK
                # kalabiliyordu — üstelik SL/TP henüz koyulmamış olarak.
                # Sistem "işlem yok" sanır, borsada korumasız pozisyon durur.
                kapatildi = False
                for deneme in range(3):
                    try:
                        from data.binance_futures_client import futures_market_kapat
                        futures_market_kapat(sembol, yon)
                        kapatildi = True
                        break
                    except Exception as kapat_e:
                        log.error(f"[EXEC] Slippage kapatma denemesi {deneme+1}/3 "
                                  f"başarısız: {kapat_e}")
                        time.sleep(1)
                if not kapatildi:
                    log.critical(f"[EXEC] 🚨🚨 HAYALET POZİSYON: {sembol} {yon} "
                                 f"slippage nedeniyle kapatılmak istendi ama "
                                 f"KAPATILAMADI. Pozisyon borsada AÇIK ve KORUMASIZ! "
                                 f"MANUEL MÜDAHALE GEREKLİ!")
                    try:
                        self._bus.publish(Event.RISK_LIQUIDATION, {
                            "seviye": "KRITIK", "sembol": sembol, "yon": yon,
                            "mesaj": "Slippage kapatma başarısız — hayalet pozisyon!",
                        }, "ExecEngine")
                    except Exception as _be:
                        # v55: Eskiden sessizce yutuluyordu. Bu, motorun
                        # üretebileceği EN KRİTİK alarmdır; yayınlanamadığını
                        # bilmek operatör için hayati.
                        log.critical(f"[EXEC] 🚨 HAYALET POZİSYON ALARMI "
                                     f"YAYINLANAMADI: {_be} — {sembol} {yon} "
                                     f"borsada açık, bildirim gitmemiş olabilir!")
                return ExecutionSonuc(
                    basarili=False, sembol=sembol, yon=yon, exec_fiyat=exec_fiyat,
                    exec_miktar=exec_miktar, slippage_pct=slippage_pct,
                    sl_aktif=False, tp_aktif=False,
                    order_id=str(order["orderId"]),
                    hata=(f"Slippage %{slippage_pct:.3f}" if kapatildi else
                          f"Slippage %{slippage_pct:.3f} — KAPATILAMADI, MANUEL MÜDAHALE!")
                )

            # ── FİX: futures_sl_tp_koy → ayrı SL + TP fonksiyonları ──
            sl_aktif = False; tp_aktif = False
            sl_hata_mesaji = ""
            try:
                futures_stop_loss_koy(sembol, yon, sl)
                sl_aktif = True
            except Exception as sl_e:
                sl_hata_mesaji = str(sl_e)
                log.error(f"[EXEC] ⚠️ {sembol} SL koyulamadı: {sl_e}")
                self._istatistik["sl_basarisiz"] += 1

            # ── v51 KRİTİK GÜVENLİK: SL YOKSA POZİSYONU AÇIK BIRAKMA ──
            # Korumasız kaldıraçlı pozisyon = likidasyon riski. Piyasa
            # aleyhe dönerse zararı durduracak hiçbir şey yoktur.
            # Slippage senaryosunda olduğu gibi burada da güvenli çıkış:
            # SL yerleştirilemiyorsa pozisyonu DERHAL kapat.
            if not sl_aktif:
                log.critical(f"[EXEC] 🛑 {sembol} {yon} SL KORUMASIZ — pozisyon "
                             f"güvenlik gereği kapatılıyor. Sebep: {sl_hata_mesaji}")
                kapatildi = False
                for deneme in range(3):   # kapatma kritik: 3 kez dene
                    try:
                        from data.binance_futures_client import futures_market_kapat
                        futures_market_kapat(sembol, yon)
                        kapatildi = True
                        break
                    except Exception as kapat_e:
                        log.error(f"[EXEC] Acil kapatma denemesi {deneme+1}/3 "
                                  f"başarısız: {kapat_e}")
                        time.sleep(1)
                if not kapatildi:
                    # En kötü senaryo: pozisyon açık, SL yok, kapatılamıyor.
                    # Operatörü DERHAL uyar — manuel müdahale şart.
                    log.critical(f"[EXEC] 🚨🚨 ACİL: {sembol} {yon} pozisyonu SL'siz "
                                 f"AÇIK ve kapatılamıyor! MANUEL MÜDAHALE GEREKLİ!")
                    try:
                        self._bus.publish(Event.RISK_LIQUIDATION, {
                            "seviye": "KRITIK", "sembol": sembol, "yon": yon,
                            "mesaj": "SL'siz pozisyon kapatılamadı — manuel müdahale!",
                        }, "ExecEngine")
                    except Exception as _be:
                        # v55: bkz. yukarıdaki hayalet pozisyon notu
                        log.critical(f"[EXEC] 🚨 SL'SİZ POZİSYON ALARMI "
                                     f"YAYINLANAMADI: {_be} — {sembol} {yon} "
                                     f"korumasız, bildirim gitmemiş olabilir!")
                self._istatistik["acma_basarisiz"] += 1
                return ExecutionSonuc(
                    basarili=False, sembol=sembol, yon=yon, exec_fiyat=exec_fiyat,
                    exec_miktar=exec_miktar, slippage_pct=slippage_pct,
                    sl_aktif=False, tp_aktif=False,
                    order_id=str(order.get("orderId", "")),
                    hata=("SL koyulamadı → pozisyon kapatıldı"
                          if kapatildi else
                          "SL koyulamadı VE pozisyon kapatılamadı — MANUEL MÜDAHALE!")
                )

            try:
                if FUTURES_PARTIAL_TP:
                    tp_res = futures_partial_tp_koy(sembol, yon, tp1, FUTURES_PARTIAL_TP_PCT)
                else:
                    tp_res = futures_take_profit_koy(sembol, yon, tp1)
                tp_aktif = bool(tp_res and tp_res.get("orderId"))
            except Exception as tp_e:
                log.warning(f"[EXEC] TP koyulamadı: {tp_e}")

            # ── State kaydet ────────────────────────────────────
            # v57 KRİTİK DÜZELTME — sessiz izleme kaybı:
            #   Burada `self._state.pozisyon_ekle({...})` çağrılıyordu ama
            #   StateManager'da BÖYLE BİR METOT YOK. Doğrusu:
            #     pozisyon_ac(sembol, yon, giris, miktar, sl, tp1, kaldirac, order_id)
            #   — isim de imza da farklı (dict değil, konumlu argümanlar).
            #
            #   Sonuç: her pozisyon açılışında AttributeError fırlıyor,
            #   aşağıdaki `except Exception` onu yutuyor ve bot AÇTIĞI
            #   POZİSYONU KENDİ STATE'İNE HİÇ KAYDETMİYORDU. Hiçbir şey
            #   çökmediği için aylarca fark edilmemiş.
            #
            #   Etkisi: `position_state.sl_tp_dogrula()` boş state üzerinde
            #   dönüyor → gerçek pozisyonların SL/TP'si HİÇ doğrulanmıyor.
            #   `pozisyon_var_mi()` her zaman False → duplicate koruması
            #   bu katmanda çalışmıyor.
            #
            #   2026-08-26'da `testnet_emir_dogrula.py` adım 6 ile yakalandı:
            #   "borsada AÇIK ama iç state'te YOK".
            if self._state:
                try:
                    self._state.pozisyon_ac(
                        sembol=sembol, yon=yon, giris=exec_fiyat,
                        miktar=exec_miktar, sl=sl, tp1=tp1,
                        kaldirac=kaldirac,
                        order_id=str(order.get("orderId", "")
                                     if isinstance(order, dict) else ""),
                    )
                    if sl_aktif:
                        self._state.sl_aktif_isaretle(sembol)
                    if tp_aktif:
                        self._state.tp1_aktif_isaretle(sembol)
                except Exception as state_e:
                    # v57: Bu artık SESSİZ kalmamalı — state kaydı başarısızsa
                    # bot pozisyonu izlemiyor demektir, bu KRİTİK bir durumdur.
                    log.critical(
                        f"[EXEC] ❗ STATE KAYIT BAŞARISIZ: {sembol} {yon} — "
                        f"bot bu pozisyonu İZLEMİYOR. {type(state_e).__name__}: "
                        f"{state_e}", exc_info=True)

            self._istatistik["acma_basarili"] += 1
            sure = round(time.time() - baslangic, 2)

            # v15: Trade Journal kaydı (LIVE trade)
            try:
                from engines.trade_journal import get_journal, TradeKayit
                import time as _t
                _j = get_journal()
                _kayit = TradeKayit(
                    trade_id     = f"LIVE_{order['orderId']}_{sembol}",
                    sembol=sembol, yon=yon, mod="LIVE",
                    giris_ts     = _t.time(), giris_fiyat=exec_fiyat,
                    miktar=exec_miktar, maliyet_usdt=usdt,
                    rejim=rejim, ai_score=ai_score, confidence=0,
                    volatility=0, strateji=kaynak, mtf_skor=0,
                    funding_rate=0, edge_score=0,
                    sl=sl, tp1=tp1, tp2=tp2, kaldirac=kaldirac,
                    latency_ms=sure*1000, slippage_pct=slippage_pct,
                )
                _j.trade_ac(_kayit)
            except Exception as _e:
                log.debug(f"[EXEC] journal trade_ac atlandı: {_e}")

            self._bus.publish(Event.ORDER_FILLED, {
                "sembol": sembol, "yon": yon, "fiyat": exec_fiyat,
                "miktar": exec_miktar, "sl": sl, "tp1": tp1, "kaynak": kaynak
            }, "ExecEngine")

            log.info(f"[EXEC] ✅ {sembol} {yon} açıldı @ {exec_fiyat:.4f} "
                     f"sl:{sl:.4f} tp1:{tp1:.4f} ({sure:.1f}s)")

            return ExecutionSonuc(
                basarili=True, sembol=sembol, yon=yon,
                exec_fiyat=exec_fiyat, exec_miktar=exec_miktar,
                slippage_pct=slippage_pct, sl_aktif=sl_aktif, tp_aktif=tp_aktif,
                order_id=str(order["orderId"]), sure_saniye=sure
            )

        except FuturesAPIError as e:
            self._istatistik["acma_basarisiz"] += 1
            log.error(f"[EXEC] Açma API hatası: {e}")
            return ExecutionSonuc(
                basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                order_id="", hata=str(e)
            )
        except Exception as e:
            self._istatistik["acma_basarisiz"] += 1
            log.critical(f"[EXEC] Açma beklenmedik hata: {type(e).__name__}: {e}", exc_info=True)
            return ExecutionSonuc(
                basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                order_id="", hata=f"{type(e).__name__}: {e}"
            )

    # ── Pozisyon Kapat — Self-Training Entegrasyonlu ──────
    def pozisyon_kapat(self, sembol: str, yon: str,
                        sebep: str = "SIGNAL",
                        ai_score: int = 0,
                        son_features: dict = None) -> "ExecutionSonuc":
        self._istatistik["kapama_girişim"] += 1
        baslangic = time.time()

        if not LIVE_TRADING:
            return ExecutionSonuc(
                basarili=True, sembol=sembol, yon=yon, exec_fiyat=0,
                exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                order_id="PAPER"
            )

        from data.binance_futures_client import (
            futures_market_kapat, acik_futures_pozisyonlar,
            futures_anlık_fiyat, FuturesAPIError
        )

        try:
            pozlar = acik_futures_pozisyonlar()
            poz    = next((p for p in pozlar
                           if p["sembol"]==sembol.upper() and p["yon"]==yon.upper()), None)
            if not poz:
                log.warning(f"[EXEC] {sembol} {yon} kapatılacak pozisyon yok")
                return ExecutionSonuc(
                    basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                    exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                    order_id="", hata="Pozisyon bulunamadı"
                )

            guncel = futures_anlık_fiyat(sembol) or poz["giris"]
            order  = futures_market_kapat(sembol, yon)

            if order and order.get("orderId"):
                exec_fiyat = float(order.get("avgPrice", 0)) or guncel
                pnl_pct    = ((exec_fiyat - poz["giris"]) / poz["giris"] * 100) * \
                              (1 if yon == "LONG" else -1)

                if self._risk:
                    self._risk.pnl_guncelle(poz["pnl"])
                if self._state:
                    self._state.pozisyon_kapat(sembol, sebep)

                # DuplicateGuard cooldown sıfırla
                if self._guard:
                    self._guard.cooldown_sifirla(sembol, yon)

                # ── SELF-TRAINING: feedback_ekle + rl_reward_kaydet ──
                try:
                    from engines.model_engine import feedback_ekle, rl_reward_kaydet
                    rl_reward_kaydet(sembol, pnl_pct, ai_score or poz.get("ai_score", 0))
                    gercek_sonuc = 1 if pnl_pct > 0 else 0
                    features_dict = son_features or poz.get("son_features", {})
                    if features_dict:
                        feedback_ekle(sembol, features_dict, gercek_sonuc, pnl_pct)
                        log.info(f"[SELF-TRAIN] {sembol} feedback kaydedildi "
                                 f"pnl={pnl_pct:+.2f}% sonuc={gercek_sonuc}")
                    else:
                        log.debug(f"[SELF-TRAIN] {sembol} feature yok — feedback atlandı")
                except Exception as rl_e:
                    log.warning(f"[SELF-TRAIN] {sembol} hata: {rl_e}")

                self._bus.publish(Event.POSITION_CLOSED, {
                    "sembol":  sembol, "yon": yon,
                    "pnl_pct": round(pnl_pct, 3),
                    "pnl_usdt":round(poz.get("pnl", 0), 4),
                    "sebep":   sebep,
                    "giris":   float(poz.get("giris", poz.get("giris_fiyat", 0))),
                    "cikis":   float(exec_fiyat),
                    "miktar":  float(poz.get("miktar", 0)),
                }, "ExecEngine")

                self._istatistik["kapama_basarili"] += 1
                sure = round(time.time() - baslangic, 2)
                log.info(f"[EXEC] ✅ {sembol} {yon} kapatıldı PnL:{pnl_pct:+.2f}% ({sebep})")
                # v15: Trade Journal güncelle (LIVE kapanış)
                try:
                    from engines.trade_journal import get_journal
                    get_journal().trade_kapat(
                        f"LIVE_{order['orderId']}_{sembol}",
                        exec_fiyat, sebep,
                        round(pnl_pct * poz.get("maliyet_usdt", 0) / 100, 4),
                        round(pnl_pct, 3)
                    )
                except Exception as _e:
                    log.debug(f"[EXEC] journal kapanış kaydı atlandı: {_e}")
                return ExecutionSonuc(
                    basarili=True, sembol=sembol, yon=yon,
                    exec_fiyat=exec_fiyat, exec_miktar=abs(poz.get("miktar", 0)),
                    slippage_pct=0, sl_aktif=False, tp_aktif=False,
                    order_id=str(order["orderId"]), sure_saniye=sure
                )
            else:
                log.error(f"[EXEC] {sembol} kapatma başarısız")
                self._istatistik["kapama_basarisiz"] += 1
                return ExecutionSonuc(
                    basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                    exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                    order_id="", hata="Kapatma başarısız"
                )

        except FuturesAPIError as e:
            self._istatistik["kapama_basarisiz"] += 1
            log.error(f"[EXEC] Kapatma API hatası: {e}")
            return ExecutionSonuc(
                basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                order_id="", hata=str(e)
            )
        except Exception as e:
            self._istatistik["kapama_basarisiz"] += 1
            log.critical(f"[EXEC] Kapatma beklenmedik hata: {type(e).__name__}: {e}", exc_info=True)
            return ExecutionSonuc(
                basarili=False, sembol=sembol, yon=yon, exec_fiyat=0,
                exec_miktar=0, slippage_pct=0, sl_aktif=False, tp_aktif=False,
                order_id="", hata=str(e)
            )

    def _acil_kapat(self, sembol: str, yon: str, sebep: str):
        """Acil durum kapatma — risk kontrolü bypass."""
        log.critical(f"[EXEC] ACİL KAPAT: {sembol} {yon} ({sebep})")
        self.pozisyon_kapat(sembol, yon, sebep)

    @property
    def istatistik(self) -> dict:
        return dict(self._istatistik)

    def telegram_raporu(self) -> str:
        s = self._istatistik
        return (f"🛡️ <b>EXECUTION ENGINE v12</b>\n"
                f"Aç: ✅{s['acma_basarili']} ❌{s['acma_basarisiz']}\n"
                f"Kapat: ✅{s['kapama_basarili']} ❌{s.get('kapama_basarisiz',0)}\n"
                f"SL fail:{s['sl_basarisiz']} Slip red:{s['slippage_red']}\n"
                f"Dup engel:{s['duplicate_engel']}")


_exec_instance = None

def get_execution_engine(risk_manager=None, state_manager=None) -> ExecutionEngine:
    """ExecutionEngine singleton'ı döndür.

    v57 UYARI EKLENDİ — sessiz bağımlılık kaybı:
      Singleton İLK çağrıya göre sabitlenir. Bir modül bunu argümansız
      çağırırsa (`get_execution_engine()`), `self._state` None kalır ve
      `pozisyon_ac()` içindeki `if self._state:` bloğu ATLANIR — yani bot
      AÇTIĞI POZİSYONU KENDİ STATE'İNE KAYDETMEZ. Sonra `main.py:191`
      state_manager ile çağırsa bile argümanlar SESSİZCE YOK SAYILIR.

      Sonuç: reconciler/failsafe pozisyonu "izlenmeyen" sanır, SL/TP
      doğrulaması yapılamaz. Hiçbir hata mesajı çıkmaz.

      Bu, v57'de `get_journal()`'da bulunan hatanın (K-2) birebir aynısı.
      2026-08-26'da `testnet_emir_dogrula.py` bu yüzden adım 6'da
      başarısız oldu (betik argümansız çağırıyordu).

      Şu an üretim yolları (main.py, bootstrap/app_init.py) argümanları
      DOĞRU geçiriyor — bu uyarı regresyonu yakalamak için.
    """
    global _exec_instance
    if _exec_instance is None:
        _exec_instance = ExecutionEngine(risk_manager, state_manager)
        return _exec_instance

    # Zaten var: yeni bağımlılık isteniyorsa SESSİZ KALMA.
    if state_manager is not None and _exec_instance._state is None:
        log.error(
            "[EXEC] Singleton state_manager'sız oluşturulmuştu, şimdi "
            "state_manager isteniyor — pozisyonlar state'e KAYDEDİLMİYOR "
            "olabilir. Bağlanıyor.")
        _exec_instance._state = state_manager
    if risk_manager is not None and _exec_instance._risk is None:
        log.error("[EXEC] Singleton risk_manager'sız oluşturulmuştu — bağlanıyor.")
        _exec_instance._risk = risk_manager
    return _exec_instance
