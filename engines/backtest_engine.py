# =========================================================
# ASTRA v30.0 — REALISTIC BACKTEST ENGINE
# Fee, slippage, partial fill, latency, liquidation simülasyonu
# =========================================================
import logging
import numpy as np
import pandas as pd
import sys; sys.path.append("..")
from config import RISK_PERCENT, BALANCE

log = logging.getLogger("ASTRA.BACKTEST")


def walk_forward_cv(X, y, model_cls, model_params, n_splits=5, embargo=0):
    """Genişleyen pencere walk-forward.

    v58 (K-23): `embargo` — train'in SON `embargo` satırını atar.
    Üçlü bariyer etiketleri ileriye baktığı için train'in son satırlarının
    etiketi test dönemi fiyatlarından hesaplanmıştır; atılmazsa model test
    dönemini dolaylı görür ve WF skoru sahte şekilde yükselir.
    Varsayılan 0 → eski çağıranlar için davranış değişmez.
    """
    n = len(X); step = n // (n_splits + 1)
    dogruluklar = []
    beceriler   = []      # v58 (K-37): accuracy − çoğunluk sınıfı taban çizgisi
    tabanlar    = []
    for i in range(1, n_splits + 1):
        train_end = i * step; test_end = min(train_end + step, n)
        tr_son = max(0, train_end - embargo)
        X_tr = X.iloc[:tr_son]; y_tr = y.iloc[:tr_son]
        X_te = X.iloc[train_end:test_end]; y_te = y.iloc[train_end:test_end]
        if len(X_te) < 5 or len(X_tr) < 20: continue
        model = model_cls(**model_params); model.fit(X_tr, y_tr)
        acc = (model.predict(X_te) == y_te.values).mean()
        # v58 (K-37): HAM ACCURACY TEK BAŞINA ANLAMSIZDIR.
        # Sınıf dengesi katmandan katmana oynuyor (ölçüm: 4h/3 yıl/5 sembol,
        # 40 katman → taban ort 0.5151, aralık 0.5007–0.5351). Taban çizgisi
        # 0.5351 olan bir katmanda 0.54 accuracy neredeyse hiçbir şey, taban
        # 0.5007 olan katmanda aynı sayı gerçek beceridir. Sabit bir eşikle
        # (MIN_USEFUL_ACC=0.52) karşılaştırmak, beceriyi değil SINIF
        # DENGESİZLİĞİNİ ödüllendirir; katmanların %25'inde taban zaten
        # 0.52'nin üstünde, yani orada eşiği geçen model sabit tahminciden
        # KÖTÜdür ve yine de "faydalı" sayılıyordu.
        taban = float(max(y_te.mean(), 1 - y_te.mean()))
        dogruluklar.append(acc)
        tabanlar.append(taban)
        beceriler.append(acc - taban)
    return {
        "splits": n_splits,
        "ortalama": round(float(np.mean(dogruluklar)), 4) if dogruluklar else 0,
        "std":      round(float(np.std(dogruluklar)), 4)  if dogruluklar else 0,
        "min":      round(float(np.min(dogruluklar)), 4)  if dogruluklar else 0,
        "max":      round(float(np.max(dogruluklar)), 4)  if dogruluklar else 0,
        "auc_ort":  0,
        "detay":    [round(a, 4) for a in dogruluklar],
        # v58 (K-37) — SEÇİM ARTIK BUNLARA BAKIYOR. Yukarıdaki ham
        # değerler raporlama için KORUNDU (registry + eski testler).
        "beceri_ort": round(float(np.mean(beceriler)), 4) if beceriler else 0.0,
        "beceri_std": round(float(np.std(beceriler)), 4)  if beceriler else 0.0,
        "taban_ort":  round(float(np.mean(tabanlar)), 4)  if tabanlar else 0.0,
    }


def overfitting_skoru(train_acc, test_acc, wf_std):
    fark = train_acc - test_acc
    if fark > 0.15 or wf_std > 0.08: risk = "YÜKSEK"
    elif fark > 0.08 or wf_std > 0.05: risk = "ORTA"
    else: risk = "DÜŞÜK"
    return {"fark": round(fark, 4), "wf_std": round(wf_std, 4), "risk": risk}


def backtest_calistir(
    df: pd.DataFrame,
    sinyaller: pd.Series,
    close: pd.Series,
    stop_loss_atr_katsayi: float   = 2.0,
    take_profit_atr_katsayi: float = 3.0,
    baslangic_bakiye: float        = BALANCE,
    risk_yuzde: float              = RISK_PERCENT,
    komisyon: float                = 0.0004,      # Binance Futures maker %0.02 + taker %0.04
    slippage_bps: float            = 3.0,         # 3 bps ortalama
    latency_ms: float              = 50.0,        # 50ms simüle gecikme
    kaldirac: int                  = 5,
    partial_fill_prob: float       = 0.08,        # %8 kısmi fill
) -> dict:
    """
    v14 Gerçekçi backtest:
    - Komisyon (maker+taker)
    - Slippage simülasyonu
    - Partial fill
    - Likidasyon kontrolü
    - MAE/MFE takibi
    """
    bakiye      = baslangic_bakiye
    pozisyon    = 0.0
    giris_fiyat = 0.0
    giris_yon   = 0
    islemler    = []
    zirve       = baslangic_bakiye
    max_dd      = 0.0
    toplam_komisyon = 0.0
    toplam_slippage = 0.0

    # ATR hesapla
    try:
        h = df["High"]; l = df["Low"]; c = df["Close"]
        tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
        # v55: eskiden .fillna(tr.mean()) vardı — TÜM serinin (backtest sonuna
        # kadar olan) ortalaması, yani ilk ~13 bar henüz var olmayan GELECEK
        # veriyle dolduruluyordu → lookahead bias.
        # Artık ısınma barları NaN bırakılıyor ve aşağıdaki döngü o barlarda
        # işlem açmıyor. Uydurma değerle doldurmak yerine işlem yapmamak doğru.
        atr = tr.rolling(14).mean()
    except Exception:
        atr = pd.Series(close.std() * 1.5, index=close.index)

    def _slippage_uygula(fiyat, yon):
        """Slippage simülasyonu — BUY biraz yukarı, SELL biraz aşağı."""
        bps = slippage_bps * (1 + np.random.exponential(0.5))
        if yon == 1:   # BUY
            return fiyat * (1 + bps / 10000)
        else:          # SELL
            return fiyat * (1 - bps / 10000)

    def _partial_fill(miktar):
        """Kısmi fill simülasyonu."""
        if np.random.random() < partial_fill_prob:
            return miktar * np.random.uniform(0.7, 0.95)
        return miktar

    for i in range(1, len(close)):
        fiyat     = float(close.iloc[i])
        sinyal    = int(sinyaller.iloc[i])
        son_atr   = float(atr.iloc[i])
        # v55: ATR ısınma penceresi (ilk 13 bar) — geçerli ATR yokken
        # ne yeni pozisyon açılır ne de SL/TP hesaplanır.
        if not np.isfinite(son_atr) or son_atr <= 0:
            continue

        # Açık pozisyon yoksa yeni aç
        if pozisyon == 0 and sinyal != 0:
            exec_fiyat = _slippage_uygula(fiyat, sinyal)
            risk_usdt  = bakiye * risk_yuzde
            sl_mesafe  = son_atr * stop_loss_atr_katsayi
            if sl_mesafe <= 0: continue

            miktar = _partial_fill(risk_usdt / sl_mesafe)
            maliyet = exec_fiyat * miktar / kaldirac
            if maliyet > bakiye * 0.9: continue

            # Komisyon giriş
            giris_kom = exec_fiyat * miktar * komisyon
            toplam_komisyon += giris_kom

            slippage_maliyet = abs(exec_fiyat - fiyat) * miktar
            toplam_slippage  += slippage_maliyet

            giris_fiyat = exec_fiyat
            giris_yon   = sinyal
            pozisyon    = miktar
            bakiye     -= (maliyet + giris_kom)

        elif pozisyon != 0:
            # Likidasyon kontrolü
            # v55 DÜZELTME: Likidasyonda teminat İKİ KEZ düşülüyordu.
            # Girişte `bakiye -= (maliyet + giris_kom)` ile teminat zaten
            # bakiyeden çıkarılmış oluyor. Normal kapanışta `bakiye += maliyet + pnl`
            # ile iade ediliyor. Likidasyonda ise teminat iade EDİLMEMELİ —
            # ama eskiden ek olarak bir kez daha `bakiye -= kayip` yapılıyordu
            # (kayip == maliyet). Sonuç: her likidasyonda gerçek zararın 2 katı.
            # Bu, likidasyon içeren TÜM backtest sonuçlarını (drawdown, Sharpe,
            # win rate, toplam getiri) sistematik olarak kötümser gösteriyordu.
            if giris_yon == 1:
                likit = giris_fiyat * (1 - 1/kaldirac + 0.004)
                if fiyat <= likit:
                    kayip = pozisyon * giris_fiyat / kaldirac  # yalnızca raporlama
                    islemler.append({"pnl": -kayip, "sebep": "LİKİDASYON",
                                     "ts": close.index[i]})
                    pozisyon = 0; continue
            else:
                likit = giris_fiyat * (1 + 1/kaldirac - 0.004)
                if fiyat >= likit:
                    kayip = pozisyon * giris_fiyat / kaldirac  # yalnızca raporlama
                    islemler.append({"pnl": -kayip, "sebep": "LİKİDASYON",
                                     "ts": close.index[i]})
                    pozisyon = 0; continue

            # SL/TP kontrolü
            tp = giris_fiyat + son_atr * take_profit_atr_katsayi * giris_yon
            sl = giris_fiyat - son_atr * stop_loss_atr_katsayi * giris_yon

            # v57: Dolum, tetikleyen SEVİYEDEN yapılır (paper ile aynı model).
            # Eskiden bar kapanışı `fiyat` kullanılıyordu; bar içinde stop'u
            # aşan hareketin TAMAMI zarar/kâr yazılıyordu. Canlıda SL borsada
            # duran STOP_MARKET (seviyede tetiklenir), TP ise limit emri
            # (seviyeden dolar, daha iyisinden değil).
            # Bkz. engines/paper_trading.py::stop_tp_kontrol — gerekçe orada.
            kapan = False; sebep = ""
            tetik_fiyat = fiyat
            if giris_yon == 1:
                if fiyat >= tp: kapan = True; sebep = "TP"; tetik_fiyat = tp
                elif fiyat <= sl: kapan = True; sebep = "SL"; tetik_fiyat = sl
            else:
                if fiyat <= tp: kapan = True; sebep = "TP"; tetik_fiyat = tp
                elif fiyat >= sl: kapan = True; sebep = "SL"; tetik_fiyat = sl

            if sinyal != 0 and sinyal != giris_yon:
                # Sinyal çıkışında seviye yok — piyasa fiyatından kapanır.
                kapan = True; sebep = "SİNYAL"; tetik_fiyat = fiyat

            if kapan:
                exec_fiyat = _slippage_uygula(tetik_fiyat, -giris_yon)
                pnl = (exec_fiyat - giris_fiyat) * pozisyon * giris_yon
                cikis_kom = exec_fiyat * pozisyon * komisyon
                toplam_komisyon += cikis_kom
                pnl -= cikis_kom

                maliyet = giris_fiyat * pozisyon / kaldirac
                bakiye += maliyet + pnl

                islemler.append({
                    "pnl": round(pnl, 4),
                    "sebep": sebep,
                    "yon": "LONG" if giris_yon == 1 else "SHORT",
                    "ts": close.index[i],   # v55: Sharpe yıllıklandırması için
                })
                pozisyon = 0

        # Drawdown güncelle
        zirve = max(zirve, bakiye)
        dd    = (zirve - bakiye) / zirve * 100 if zirve > 0 else 0
        max_dd = max(max_dd, dd)

    if not islemler:
        return {"toplam_islem": 0, "win_rate": 0, "toplam_getiri": 0,
                "max_drawdown": 0, "sharpe": 0, "kazanan": 0, "kaybeden": 0,
                "komisyon_toplam": 0, "slippage_toplam": 0}

    kazananlar = [t for t in islemler if t["pnl"] > 0]
    pnl_seri   = pd.Series([t["pnl"] for t in islemler])

    # v55: Eskiden İŞLEM BAŞINA PnL, sanki her işlem bir gün gibi sqrt(252) ile
    # yıllıklandırılıyordu. İşlem sayısı 252'den çok farklı olduğunda (genelde
    # çok daha fazla) bu Sharpe'ı belirgin şekilde ŞİŞİRİYORDU — ve bu değer
    # overfitting_skoru / strateji karşılaştırmasını besliyor.
    # Doğrusu: gerçek işlem frekansına göre yıllıklandırma.
    if pnl_seri.std() > 0 and len(islemler) > 1:
        try:
            _ilk = pd.to_datetime(islemler[0].get("ts"))
            _son = pd.to_datetime(islemler[-1].get("ts"))
            _gun = max((_son - _ilk).days, 1)
            _islem_per_yil = len(islemler) * 365.0 / _gun
        except Exception:
            _islem_per_yil = 252.0   # tarih yoksa eski varsayıma dön
        _islem_per_yil = min(max(_islem_per_yil, 1.0), 8760.0)   # makul aralık
        sharpe = pnl_seri.mean() / pnl_seri.std() * np.sqrt(_islem_per_yil)
    else:
        sharpe = 0

    return {
        "toplam_islem":     len(islemler),
        "kazanan":          len(kazananlar),
        "kaybeden":         len(islemler) - len(kazananlar),
        "win_rate":         round(len(kazananlar) / len(islemler) * 100, 1),
        "toplam_getiri":    round((bakiye - baslangic_bakiye) / baslangic_bakiye * 100, 2),
        "son_bakiye":       round(bakiye, 2),
        "max_drawdown":     round(max_dd, 2),
        "sharpe":           round(float(sharpe), 3),
        "komisyon_toplam":  round(toplam_komisyon, 4),
        "slippage_toplam":  round(toplam_slippage, 4),
        "profit_factor":    round(
            sum(t["pnl"] for t in kazananlar) /
            abs(sum(t["pnl"] for t in islemler if t["pnl"] < 0))
            if any(t["pnl"] < 0 for t in islemler) else 999, 2
        ),
    }
