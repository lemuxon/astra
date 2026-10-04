# =========================================================
# ASTRA v30.0 — ON-CHAIN VERİ ENTEGRASYONU
# Büyük cüzdan hareketleri + borsa giriş/çıkış akışı.
# Fiyattan 4-12 saat önce sinyal verebilir.
#
# Veri kaynakları (ücretsiz tier öncelikli):
#   - Binance exchange netflow (deposit/withdraw API'si yok → proxy)
#   - Whale Alert benzeri: büyük transfer tespiti (on-chain API)
#   - Stablecoin supply değişimi (piyasaya giren likidite)
#
# Tüm API'ler opsiyonel — anahtar yoksa nötr değer döner.
# Sentiment skoruna ek katkı sağlar.
# =========================================================
import logging, requests, time, os
from typing import Dict, Optional
import numpy as np

log = logging.getLogger("ASTRA.ONCHAIN")

# API anahtarları (.env'den) — yoksa devre dışı
GLASSNODE_API_KEY = os.getenv("GLASSNODE_API_KEY", "")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")

_cache: dict = {}
_CACHE_TTL = 1800   # 30 dakika (on-chain veri yavaş değişir)
import threading as _threading
_cache_lock = _threading.Lock()   # v23: paralel coin analizinde thread-safe cache


def _cache_gecerli(anahtar: str) -> Optional[dict]:
    with _cache_lock:
        c = _cache.get(anahtar)
        if c and time.time() - c["ts"] < _CACHE_TTL:
            return c["veri"]
    return None


def _cache_yaz(anahtar: str, veri: dict):
    with _cache_lock:
        _cache[anahtar] = {"veri": veri, "ts": time.time()}


def exchange_netflow_proxy(sembol: str) -> dict:
    """
    Borsa netflow proxy'si.
    Gerçek netflow API'si ücretli; bunun yerine açık-erişimli verilerle
    yaklaşık tahmin yaparız:
      - Funding rate trendi
      - Open interest değişimi yönü
      - Stablecoin dominance

    Pozitif netflow = borsaya para giriyor = satış baskısı potansiyeli
    Negatif netflow = borsadan çekiliyor = HODL / yükseliş eğilimi
    """
    # v23: Coingecko /global tüm coinler için AYNI — tek global cache kullan
    # (per-symbol cache 5 coin için 5 özdeş API çağrısı yapıyordu)
    cached = _cache_gecerli("netflow_GLOBAL")
    if cached: return cached

    try:
        # Coingecko global market verisi (ücretsiz)
        r = requests.get(
            "https://api.coingecko.com/api/v3/global",
            timeout=8
        )
        netflow_skoru = 0.0
        if r.status_code == 200:
            data = r.json().get("data", {})
            # Stablecoin market cap değişimi (piyasaya giren likidite proxy'si)
            mcap_pct = data.get("market_cap_change_percentage_24h_usd", 0)
            netflow_skoru = float(np.clip(mcap_pct / 5.0, -1, 1))

        sonuc = {
            "netflow_skoru":  round(netflow_skoru, 3),
            "yorum":          ("Para girişi" if netflow_skoru > 0.2
                               else "Para çıkışı" if netflow_skoru < -0.2
                               else "Nötr"),
            "kaynak":         "coingecko_proxy",
        }
        _cache_yaz("netflow_GLOBAL", sonuc)
        return sonuc
    except Exception as e:
        log.debug(f"[ONCHAIN] Netflow proxy hatası: {e}")
        return {"netflow_skoru": 0.0, "yorum": "Veri yok", "kaynak": "yok"}


def whale_hareket_tespit(sembol: str) -> dict:
    """
    Büyük cüzdan hareketleri (whale tracking).

    ⚠️ v58 (K-67): Glassnode API anahtarı YOKSA bu fonksiyon sabit 0.0
    döner — "hacim-tabanlı proxy" diye bir yol KODDA YOK (docstring
    yanlıştı). Anahtar yoksa balina tespiti çalışmıyor demektir;
    `kaynak: "yok"` bunun tek göstergesidir.

    Büyük çıkış + fiyat düşüşü = dağıtım (bearish)
    Büyük giriş + fiyat yükselişi = birikim (bullish)
    """
    cached = _cache_gecerli(f"whale_{sembol}")
    if cached: return cached

    if GLASSNODE_API_KEY:
        try:
            # Glassnode large transactions count
            coin = sembol.replace("USDT", "").lower()
            r = requests.get(
                f"https://api.glassnode.com/v1/metrics/transactions/transfers_volume_large_relative",
                params={"a": coin.upper(), "api_key": GLASSNODE_API_KEY,
                        "i": "1h", "f": "JSON"},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                if data and len(data) >= 2:
                    son   = float(data[-1].get("v", 0))
                    onceki= float(data[-2].get("v", 0))
                    degisim = (son - onceki) / max(onceki, 1e-10)
                    whale_skoru = float(np.clip(degisim, -1, 1))
                    sonuc = {
                        "whale_skoru": round(whale_skoru, 3),
                        "buyuk_islem_orani": round(son, 4),
                        "kaynak": "glassnode",
                    }
                    _cache_yaz(f"whale_{sembol}", sonuc)
                    return sonuc
        except Exception as e:
            log.debug(f"[ONCHAIN] Glassnode hatası: {e}")

    # ── v58 (K-68): ANAHTAR YOKSA GERÇEK HACİM PROXY'Sİ ─────────
    # Eskiden burası sabit 0.0 döndürüyordu (docstring "hacim-tabanlı
    # proxy" vaat etse de kodda öyle bir yol YOKTU). Artık Binance'in
    # ÜCRETSİZ kline alanlarından coine özgü bir tahmin üretiliyor:
    #
    #   ortalama_islem_boyu = quote_volume / islem_sayisi
    #
    # Balina mantığı: aynı hacim 10.000 küçük emirle de gelebilir,
    # 200 büyük emirle de. İkincisi büyük katılımcı demektir. Yön ise
    # taker alış payından okunur (agresif alan mı satan mı).
    #
    #   buyukluk = ortalama işlem boyunun kendi geçmişine göre z-skoru
    #              (yalnızca POZİTİF taraf: küçük işlem "negatif balina"
    #               değildir, bilgi yokluğudur → 0)
    #   yon      = 2 × (taker_alis_payı − 0.5)      → [-1, +1]
    #   skor     = buyukluk × yon
    #
    # Büyük işlemler + alış baskısı = BİRİKİM (+)
    # Büyük işlemler + satış baskısı = DAĞITIM (−)
    # İşlem boyu olağansa skor ≈ 0 — yani "bilmiyorum" (§5.1 fail-closed).
    return _hacim_tabanli_whale_proxy(sembol)


def whale_skor_hesapla(boy: list, alis_payi: list) -> dict:
    """Balina skorunun SAF hesabı — ağ yok, test edilebilir (K-37 dersi).

    boy       : bar başına ortalama işlem büyüklüğü (quote_vol / islem_sayisi)
    alis_payi : bar başına taker alış payı (0..1)

    Skor = buyukluk × yon
      buyukluk : son barın işlem boyunun geçmişe göre z-skoru,
                 [0,1]'e kırpılır — NEGATİF taraf sıfırlanır çünkü
                 "işlemler küçüldü" balina yokluğudur, ters balina değil.
      yon      : 2 × (taker_alis_payı − 0.5), [-1,+1]

    Büyük işlem + alış = birikim (+) · Büyük işlem + satış = dağıtım (−)
    İşlem boyu olağansa 0 döner: "bilmiyorum" (§5.1).
    """
    if len(boy) < 12 or len(alis_payi) != len(boy):
        raise ValueError(f"yetersiz veri (bar={len(boy)})")
    gecmis = np.array(boy[:-1], dtype=float)
    son    = float(boy[-1])
    std    = float(gecmis.std())
    if std <= 0:
        raise ValueError("işlem boyu varyansı sıfır")
    z = (son - float(gecmis.mean())) / std

    buyukluk = float(np.clip(z / 3.0, 0.0, 1.0))
    yon      = float(np.clip((float(alis_payi[-1]) - 0.5) * 2.0, -1.0, 1.0))
    skor     = float(np.clip(buyukluk * yon, -1.0, 1.0))
    return {
        "whale_skoru":       round(skor, 3),
        "buyuk_islem_orani": round(son, 2),
        "islem_boyu_z":      round(z, 2),
        "taker_alis_payi":   round(float(alis_payi[-1]), 3),
        "kaynak":            "binance_hacim_proxy",
    }


def _hacim_tabanli_whale_proxy(sembol: str, bar_sayisi: int = 48) -> dict:
    """Glassnode yokken coine özgü balina tahmini (ücretsiz Binance verisi).

    Binance kline yanıtının 8. ve 10. alanları (`quote_asset_volume`,
    `taker_buy_quote_asset_volume`) ve 9. alan (`num_trades`) kullanılır.
    Bunlar `_klines_df` tarafından ATILIYOR (yalnızca OHLCV tutuluyor),
    bu yüzden burada ayrı çekiliyor.
    """
    try:
        from config import BINANCE_DATA_URL
        r = requests.get(f"{BINANCE_DATA_URL}/api/v3/klines",
                         params={"symbol": sembol, "interval": "1h",
                                 "limit": bar_sayisi},
                         timeout=8)
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        ham = r.json()
        if not isinstance(ham, list) or len(ham) < 12:
            raise ValueError(f"yetersiz bar ({len(ham) if ham else 0})")

        # Son bar HENÜZ KAPANMAMIŞ olabilir — K-16 ile aynı kural.
        simdi_ms = int(time.time() * 1000)
        barlar = [b for b in ham if int(b[6]) <= simdi_ms]
        if len(barlar) < 12:
            raise ValueError(f"yetersiz kapanmış bar ({len(barlar)})")

        boy, alis_payi = [], []
        for b in barlar:
            q_vol   = float(b[7])          # quote_asset_volume
            n_islem = float(b[8])          # num_trades
            tb_quote= float(b[10])         # taker_buy_quote_asset_volume
            if n_islem <= 0 or q_vol <= 0:
                continue
            boy.append(q_vol / n_islem)
            alis_payi.append(tb_quote / q_vol)
        if len(boy) < 12:
            raise ValueError(f"yetersiz geçerli bar ({len(boy)})")

        sonuc = whale_skor_hesapla(boy, alis_payi)
        _cache_yaz(f"whale_{sembol}", sonuc)
        return sonuc

    except Exception as e:
        # §5.1: ölçemiyorsak "sorun yok" demeyiz — kaynak "yok" kalır ve
        # `onchain_sentiment` bu yüzden skoru sentiment'e EKLEMEZ.
        log.warning(f"[ONCHAIN] {sembol} hacim proxy'si hesaplanamadı: "
                    f"{type(e).__name__}: {e}")
        sonuc = {"whale_skoru": 0.0, "buyuk_islem_orani": 0.0, "kaynak": "yok"}
        _cache_yaz(f"whale_{sembol}", sonuc)
        return sonuc


def onchain_sentiment(sembol: str) -> dict:
    """
    Tüm on-chain sinyallerini birleştir.
    Döner: {onchain_skor: -2..+2, detay: {...}}
    market_data sentiment skoruna eklenir.
    """
    netflow = exchange_netflow_proxy(sembol)
    whale   = whale_hareket_tespit(sembol)

    # ── v58 (K-68): SKORA YALNIZCA COİNE ÖZGÜ ÖLÇÜM GİRER ───────
    # ESKİ HÂLİ:  skor = −netflow + whale
    #
    # İki sorun vardı:
    #
    # 1) `netflow` ASLINDA NETFLOW DEĞİL. CoinGecko /global'den
    #    `market_cap_change_percentage_24h_usd` alınıyor — TÜM PİYASA
    #    için tek bir sayı. Beş sembolde de AYNI (+0.59 ölçüldü).
    #    Aynı sabiti beş coine de eklemek hiçbir coini diğerinden
    #    ayırmaz; yalnızca hepsinin skorunu birlikte kaydırır.
    #    §0.8/§0.11'in dersi: ortak kayma (sürüklenme) edge DEĞİLDİR.
    #
    # 2) İŞARETİ TERSTİ. "−" çarpanı gerçek netflow semantiğinden
    #    miras: "borsadan para çıkışı = HODL = boğa". Ama uygulandığı
    #    büyüklük piyasa değeri değişimi. Sonuç: piyasa DÜŞERKEN
    #    skor +boğa oluyordu (2026-09-06: piyasa −%2.95 → skor +0.59).
    #    Bu gerekçelendirilmiş bir sinyal değil, kazara ters momentum.
    #
    # YENİ: skoru YALNIZCA balina proxy'si belirler — o coine özgü ve
    # ölçülmüş bir büyüklük. Global piyasa hareketi `netflow` alanında
    # RAPORLANMAYA devam eder (/onchain'de bağlam olarak görünür) ama
    # karara girmez. Kaldırılmadı; yanlış yerde kullanılması durduruldu.
    skor = 0.0
    whale_gecerli = whale.get("kaynak", "yok") != "yok"
    if whale_gecerli:
        skor += float(whale.get("whale_skoru", 0) or 0)

    skor = float(np.clip(skor, -2, 2))

    # ── v58 (K-67): "aktif" BAYRAĞI YANILTIYORDU ────────────────
    # Eski koşul OR idi: netflow proxy'si çalıştığı sürece `aktif=True`
    # dönüyordu — whale tarafı TAMAMEN ölü olsa bile.
    #
    # ÖLÇÜM (2026-09-06, canlı çağrı):
    #   whale : {"whale_skoru": 0.0, "kaynak": "yok"}   ← Glassnode
    #           anahtarı yok, sabit sıfır. Docstring "hacim-tabanlı
    #           proxy" diyor ama kodda öyle bir yol YOK.
    #   skor  : +0.59 — BEŞ SEMBOLÜN HEPSİNDE AYNI (netflow proxy'si
    #           CoinGecko /global'den geliyor, coine özgü değil).
    #
    # `aktif=True` görünce `market_data` bu skoru sentiment'e ekliyor
    # (±2 kontribüsyon) ve `main.py` sentiment≠0 olduğu için güvene
    # +5 veriyor. Yani ölü bir balina dedektörü karar zincirini
    # etkiliyordu. §5.1: "bilmiyorum" ≠ "sorun yok".
    kaynak_sayisi = sum(1 for k in (netflow.get("kaynak"), whale.get("kaynak"))
                        if k and k != "yok")
    return {
        "onchain_skor": round(skor, 2),
        "netflow":      netflow,
        "whale":        whale,
        # `aktif` = "bu skor sentiment'e eklenebilir mi?" demektir.
        # Yalnızca COİNE ÖZGÜ bir ölçüm varsa True. Global piyasa
        # proxy'sinin çalışıyor olması bunu True yapmaz — §5.1:
        # "bir şey ölçebiliyorum" ≠ "bu coin hakkında bir şey biliyorum".
        "aktif":        whale_gecerli,
        "whale_aktif":  whale_gecerli,
        "coine_ozgu":   whale_gecerli,
        "kaynak_sayisi": kaynak_sayisi,
        # Global bağlam — raporlanır, KARARA GİRMEZ.
        "global_piyasa_24s": netflow.get("netflow_skoru", 0),
    }


def durum_raporu() -> str:
    aktif_apiler = []
    if GLASSNODE_API_KEY: aktif_apiler.append("Glassnode")
    if ETHERSCAN_API_KEY: aktif_apiler.append("Etherscan")
    if not aktif_apiler:
        aktif_apiler.append("Sadece proxy (Coingecko)")
    return (
        f"⛓️ <b>ON-CHAIN DURUM v22</b>\n"
        f"Aktif kaynaklar: {', '.join(aktif_apiler)}\n"
        f"Cache: {len(_cache)} kayıt"
    )
