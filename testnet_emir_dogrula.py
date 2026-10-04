#!/usr/bin/env python3
# =========================================================
# ASTRA — TESTNET EMİR YAŞAM DÖNGÜSÜ DOĞRULAMASI
# =========================================================
# Kullanım:  python testnet_emir_dogrula.py
#
# NE YAPAR:
#   Gerçek paraya geçmeden ÖNCE, emir gönderme yolunun uçtan uca
#   çalıştığını borsaya karşı kanıtlar. Kod okuyarak veya birim testiyle
#   doğrulanamayan tek katman budur.
#
# GÜVENLİK:
#   • Yalnızca TESTNET'e karşı çalışır. Production URL tespit ederse
#     HİÇBİR ŞEY yapmadan çıkar.
#   • En küçük geçerli pozisyonu açar, doğrular, sonra KAPATIR.
#   • Her adım tek tek raporlanır; bir adım başarısızsa durur ve
#     pozisyonu temizlemeye çalışır.
# =========================================================
import sys, os, time, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(message)s")

SEMBOL   = os.getenv("DOGRULAMA_SEMBOL", "BTCUSDT")
YON      = "LONG"

_sonuclar = []


def adim(no, ad):
    def dekorator(fn):
        def sarmalayici(*a, **kw):
            print(f"\n[{no}] {ad}")
            print("─" * 60)
            try:
                sonuc = fn(*a, **kw)
                _sonuclar.append((no, ad, True, ""))
                return sonuc
            except AssertionError as e:
                print(f"  ❌ BAŞARISIZ: {e}")
                _sonuclar.append((no, ad, False, str(e)))
                raise
            except Exception as e:
                print(f"  ❌ HATA: {type(e).__name__}: {e}")
                _sonuclar.append((no, ad, False, f"{type(e).__name__}: {e}"))
                raise
        return sarmalayici
    return dekorator


# ── 0: Güvenlik kapısı ────────────────────────────────────
@adim(0, "GÜVENLİK KAPISI — testnet mi?")
def guvenlik_kapisi():
    import config as c
    print(f"  FUTURES_BASE_URL : {c.FUTURES_BASE_URL}")
    print(f"  IS_TESTNET       : {c.IS_TESTNET}")
    print(f"  LIVE_TRADING     : {c.LIVE_TRADING}")

    url = (c.FUTURES_BASE_URL or "").lower()
    assert "testnet" in url, (
        f"BU SCRIPT YALNIZCA TESTNET'TE ÇALIŞIR.\n"
        f"     Mevcut URL production görünüyor: {c.FUTURES_BASE_URL}\n"
        f"     .env dosyanıza şunu yazın:\n"
        f"       FUTURES_BASE_URL=https://testnet.binancefuture.com")
    assert c.BINANCE_API_KEY and c.BINANCE_API_SECRET, (
        "BINANCE_API_KEY / BINANCE_API_SECRET boş. .env dosyasını doldurun.")
    assert c.LIVE_TRADING, (
        "LIVE_TRADING=false — emir gönderilmez, döngü doğrulanamaz.\n"
        "     Testnet'te doğrulama için .env'de LIVE_TRADING=true yapın\n"
        "     (testnet parası sahtedir, risk yoktur).")
    print("  ✅ Testnet doğrulandı, gerçek para riski yok")
    return c


# ── 1: Kimlik doğrulama + saat ────────────────────────────
@adim(1, "KİMLİK DOĞRULAMA + SUNUCU SAATİ")
def kimlik_dogrula():
    from data.binance_futures_client import futures_bakiye, _sunucu_zaman_senkronize
    offset = _sunucu_zaman_senkronize()
    print(f"  Saat farkı (offset): {offset} ms")
    assert abs(offset) < 5000, (
        f"Saat {offset}ms kaymış — imzalı istekler reddedilebilir. "
        f"İşletim sisteminde NTP senkronizasyonunu açın.")
    # v56: strict=True — "bakiye 0" ile "sorgulayamadım" AYRI şeylerdir.
    # Eskiden futures_bakiye() kimlik hatasını yutup 0.0 dönüyordu ve bu
    # script "test parası ekleyin" diye YANLIŞ teşhis koyuyordu.
    try:
        bakiye = futures_bakiye(strict=True)
    except Exception as e:
        kod = getattr(e, "kod", None)
        if kod == -2015 or "-2015" in str(e) or "Invalid API-key" in str(e):
            raise AssertionError(
                "API ANAHTARI REDDEDİLDİ (-2015). Bakiye sorunu DEĞİL.\n"
                "     En sık üç sebep:\n"
                "       1) Anahtar SPOT testnet'ten (testnet.binance.vision) alınmış.\n"
                "          FUTURES testnet AYRI bir sistemdir ve AYRI anahtar ister:\n"
                "          → https://testnet.binancefuture.com  (sağ üst → API Key)\n"
                "       2) Anahtarda IP kısıtlaması var — 'Unrestricted' seçin.\n"
                "       3) Anahtar/secret eksik kopyalanmış (baş/son karakter kaybı,\n"
                "          araya boşluk veya tırnak girmiş).") from e
        raise AssertionError(
            f"Bakiye sorgulanamadı: {type(e).__name__}: {e}") from e

    print(f"  Testnet bakiye     : {bakiye:.2f} USDT")
    assert bakiye > 0, (
        "Kimlik doğrulama BAŞARILI ama bakiye 0.\n"
        "     testnet.binancefuture.com hesabınıza test USDT ekleyin.")
    return bakiye


# ── 2: Sembol kuralları ───────────────────────────────────
@adim(2, "SEMBOL KURALLARI (lot size / tick size)")
def sembol_kurallari():
    from data.binance_futures_client import (miktar_duzelt_futures,
                                              fiyat_duzelt_futures,
                                              futures_anlık_fiyat)
    fiyat = futures_anlık_fiyat(SEMBOL)
    assert fiyat and fiyat > 0, f"{SEMBOL} fiyatı alınamadı"
    print(f"  {SEMBOL} fiyat     : {fiyat:,.2f}")

    ham_miktar = 0.00123456
    duzeltilmis = miktar_duzelt_futures(SEMBOL, ham_miktar)
    print(f"  Miktar yuvarlama   : {ham_miktar} → {duzeltilmis}")
    assert duzeltilmis > 0, "Miktar 0'a yuvarlandı — lot size sorunu"
    assert duzeltilmis <= ham_miktar, (
        "Miktar YUKARI yuvarlanmış — beklenenden büyük pozisyon riski")

    ham_fiyat = fiyat * 1.00137
    d_fiyat = fiyat_duzelt_futures(SEMBOL, ham_fiyat)
    print(f"  Fiyat yuvarlama    : {ham_fiyat:.4f} → {d_fiyat}")
    assert d_fiyat > 0, "Fiyat 0'a yuvarlandı — tick size sorunu"
    return fiyat


# ── 3: Pozisyon aç (execution engine üzerinden) ───────────
@adim(3, "POZİSYON AÇ — tam execution yolu")
def pozisyon_ac(fiyat):
    from execution.execution_engine import get_execution_engine
    from data.binance_futures_client import futures_sembol_filtre
    from config import TRADE_USDT

    # v56: Borsanın min_notional filtresine UY. Sembole göre değişir
    # (BTCUSDT=50, ETHUSDT=20, SOL/XRP=5 USDT). Altında kalan emir
    # borsaya hiç gitmez — doğrulama anlamsız olur.
    filtre = futures_sembol_filtre(SEMBOL)
    min_notional = float(filtre.get("min_notional", 5.0))
    usdt = max(TRADE_USDT, min_notional * 1.15)   # %15 güvenlik payı
    print(f"  min_notional={min_notional} → test tutarı {usdt:.2f} USDT")
    atr  = fiyat * 0.01
    sl   = fiyat - atr * 1.5
    tp1  = fiyat + atr * 2.0
    tp2  = fiyat + atr * 3.5
    print(f"  Tutar:{usdt} USDT | SL:{sl:,.2f} | TP1:{tp1:,.2f}")

    # v57: state_manager GEÇİLMELİ. Argümansız çağrılırsa ExecutionEngine'in
    # `self._state`'i None kalır, pozisyon_ac() içindeki state kaydı ATLANIR
    # ve adım 6 (state ↔ borsa uyumu) YANLIŞ SEBEPLE başarısız olur.
    # Üretimde main.py:191 argümanları doğru geçiriyor; betik onu taklit etmeli.
    from engines.position_state import get_state_manager
    from engines.risk_manager import RiskManager
    from config import BALANCE
    ee = get_execution_engine(RiskManager(BALANCE), get_state_manager())
    sonuc = ee.pozisyon_ac(
        sembol=SEMBOL, yon=YON, usdt=usdt,
        sl=sl, tp1=tp1, tp2=tp2, kaldirac=3,
        rejim="TEST", ai_score=8, kaynak="DOGRULAMA")

    print(f"  Sonuç: basarili={sonuc.basarili}")
    print(f"         exec_fiyat={sonuc.exec_fiyat} miktar={sonuc.exec_miktar}")
    print(f"         slippage=%{sonuc.slippage_pct:.3f}")
    print(f"         sl_aktif={sonuc.sl_aktif} tp_aktif={sonuc.tp_aktif}")
    if sonuc.hata:
        print(f"         hata={sonuc.hata}")

    assert sonuc.basarili, f"Pozisyon açılamadı: {sonuc.hata}"
    assert sonuc.exec_miktar > 0, "Dolum miktarı 0"
    assert sonuc.exec_fiyat > 0, "Dolum fiyatı 0"
    return sonuc


# ── 4: Borsada gerçekten SL var mı? (EN KRİTİK ADIM) ──────
@adim(4, "SL/TP BORSADA GERÇEKTEN VAR MI?")
def sl_tp_dogrula():
    # v57 KRİTİK: koşullu emirler Algo Service'e taşındı ve klasik
    # `GET /fapi/v1/openOrders` listesinde GÖRÜNMÜYOR. Bu adım eskiden
    # `acik_futures_emirler()` kullanıyordu — SL doğru konulmuş olsa bile
    # "STOP-LOSS BORSADA YOK, GERÇEK PARAYA GEÇMEYİN" diye YANLIŞ ALARM
    # verirdi. koruma_emirleri() klasik + algo listelerini birleştirir.
    from data.binance_futures_client import koruma_emirleri
    time.sleep(1.5)   # emirlerin borsaya işlenmesi için
    emirler = koruma_emirleri(SEMBOL, strict=True)
    tipler = [e.get("type") for e in emirler]
    print(f"  Açık emirler: {tipler}")

    sl_tipleri = {"STOP_MARKET", "STOP", "TRAILING_STOP_MARKET"}
    tp_tipleri = {"TAKE_PROFIT_MARKET", "TAKE_PROFIT"}

    sl_var = any(t in sl_tipleri for t in tipler)
    tp_var = any(t in tp_tipleri for t in tipler)

    for e in emirler:
        if e.get("type") in sl_tipleri | tp_tipleri:
            # v57: algo emirlerinde alan adları farklı —
            #   stopPrice → triggerPrice, orderId → algoId, origQty → quantity
            _tetik = e.get("triggerPrice") or e.get("stopPrice")
            _adet  = e.get("quantity") or e.get("origQty")
            _kaynak = "ALGO" if e.get("_algo") else "klasik"
            print(f"    {e.get('type'):22s} tetik={_tetik} "
                  f"side={e.get('side')} qty={_adet} "
                  f"workingType={e.get('workingType')} "
                  f"[{_kaynak} #{e.get('orderId')}]")

    assert sl_var, (
        "❗ STOP-LOSS BORSADA YOK! Pozisyon KORUMASIZ. "
        "Gerçek parada bu, sınırsız zarar demektir. GERÇEK PARAYA GEÇMEYİN.")
    print("  ✅ Stop-loss borsada doğrulandı")
    if not tp_var:
        print("  ⚠️  Take-profit emri görünmüyor (SL kadar kritik değil, "
              "ama beklenen davranış değil)")
    return emirler


# ── 5: Pozisyon durumu + likidasyon fiyatı ────────────────
@adim(5, "POZİSYON DURUMU + LİKİDASYON FİYATI")
def pozisyon_durumu():
    from data.binance_futures_client import acik_futures_pozisyonlar
    pozlar = acik_futures_pozisyonlar(strict=True)
    poz = next((p for p in pozlar if p["sembol"] == SEMBOL), None)
    assert poz, f"{SEMBOL} pozisyonu positionRisk'te görünmüyor"

    print(f"  Yön     : {poz['yon']}")
    print(f"  Giriş   : {poz['giris']:,.2f}")
    print(f"  Miktar  : {poz['miktar']}")
    print(f"  Kaldıraç: {poz['kaldirac']}x")
    print(f"  PnL     : {poz['pnl']:+.4f} USDT")
    print(f"  Likidasyon fiyatı (borsadan): {poz.get('likidasyon_fiyat')}")

    assert poz.get("likidasyon_fiyat", 0) > 0, (
        "Borsanın likidasyon fiyatı okunamadı — failsafe elle hesaba düşer "
        "(v56'da bu alanın okunması eklenmişti, regresyon olabilir)")
    print("  ✅ Likidasyon fiyatı borsadan okunuyor")
    return poz


# ── 6: İç state ile borsa uyumlu mu? ──────────────────────
@adim(6, "İÇ STATE ↔ BORSA UYUMU")
def state_uyumu(poz):
    from engines.position_state import get_state_manager
    sm = get_state_manager()
    state_pozlar = sm.acik_pozisyonlar()
    print(f"  State'teki pozisyon sayısı: {len(state_pozlar)}")
    s = next((p for p in state_pozlar if p.get("sembol") == SEMBOL), None)
    assert s, (
        f"{SEMBOL} borsada AÇIK ama iç state'te YOK — "
        f"bot bu pozisyonu izlemiyor demektir")
    print(f"  State giriş : {s.get('giris')}")
    print(f"  State SL    : {s.get('sl')}  (sl_aktif={s.get('sl_aktif')})")
    assert s.get("sl_aktif"), "State SL'i aktif olarak işaretlememiş"
    print("  ✅ State ile borsa uyumlu")


# ── 7: Pozisyonu kapat ────────────────────────────────────
@adim(7, "POZİSYONU KAPAT")
def pozisyon_kapat():
    from execution.execution_engine import get_execution_engine
    ee = get_execution_engine()
    sonuc = ee.pozisyon_kapat(SEMBOL, YON, "DOGRULAMA_BITTI")
    print(f"  Kapatma sonucu: {sonuc}")
    time.sleep(2)

    from data.binance_futures_client import acik_futures_pozisyonlar
    pozlar = acik_futures_pozisyonlar(strict=True)
    kalan = [p for p in pozlar if p["sembol"] == SEMBOL]
    assert not kalan, f"{SEMBOL} pozisyonu KAPANMADI — manuel kontrol edin!"
    print("  ✅ Pozisyon kapandı")


# ── 8: Artık emir kaldı mı? ───────────────────────────────
@adim(8, "ARTIK (ORPHAN) EMİR TEMİZLİĞİ")
def orphan_kontrol():
    # v57: algo emirleri klasik listede görünmediği için eski kod duran
    # SL/TP'leri göremez ve YANLIŞ "temiz" raporu verirdi.
    from data.binance_futures_client import koruma_emirleri
    time.sleep(1.5)
    emirler = koruma_emirleri(SEMBOL, strict=True)
    tipler = [e.get("type") for e in emirler]
    print(f"  Kalan açık emir: {tipler or 'yok'}")
    if emirler:
        print("  ⚠️  Pozisyon kapandı ama emirler duruyor — reconciler "
              "bunları temizlemeli (15s içinde tekrar bakın).")
    else:
        print("  ✅ Artık emir yok")


def main():
    print("=" * 60)
    print("  ASTRA — TESTNET EMİR YAŞAM DÖNGÜSÜ DOĞRULAMASI")
    print("=" * 60)

    acildi = False
    try:
        guvenlik_kapisi()
        kimlik_dogrula()
        fiyat = sembol_kurallari()
        pozisyon_ac(fiyat)
        acildi = True
        sl_tp_dogrula()
        poz = pozisyon_durumu()
        state_uyumu(poz)
        pozisyon_kapat()
        acildi = False
        orphan_kontrol()
    except Exception:
        if acildi:
            print("\n⚠️  Doğrulama yarıda kesildi — AÇIK POZİSYON temizleniyor...")
            try:
                from data.binance_futures_client import futures_market_kapat
                futures_market_kapat(SEMBOL, YON)
                print("   Pozisyon kapatıldı.")
            except Exception as e:
                print(f"   ❗ KAPATILAMADI: {e}")
                print(f"   ❗ Binance testnet arayüzünden MANUEL kapatın: {SEMBOL}")

    # ── Özet ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ÖZET")
    print("=" * 60)
    basarili = sum(1 for *_, ok, _ in _sonuclar if ok)
    for no, ad, ok, hata in _sonuclar:
        print(f"  {'✅' if ok else '❌'} [{no}] {ad}")
        if hata:
            print(f"       └─ {hata}")
    print(f"\n  {basarili}/{len(_sonuclar)} adım başarılı")

    tum_ok = basarili == len(_sonuclar) and len(_sonuclar) >= 9
    if tum_ok:
        print("\n  ✅ EMİR DÖNGÜSÜ DOĞRULANDI (testnet)")
        print("     Bu, kodun çalıştığını gösterir — stratejinin kârlı")
        print("     olduğunu GÖSTERMEZ. CANLI_GECIS_PROTOKOLU.md Aşama 1'e geçin.")
    else:
        print("\n  ❌ DOĞRULAMA TAMAMLANMADI — gerçek paraya GEÇMEYİN.")
    print("=" * 60 + "\n")
    sys.exit(0 if tum_ok else 1)


if __name__ == "__main__":
    main()
