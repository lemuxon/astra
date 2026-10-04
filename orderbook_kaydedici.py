#!/usr/bin/env python3
"""ORDER BOOK DERİNLİĞİ KAYDEDİCİ (v58, K-38)

NEDEN VAR:
  DEVAM_NOTLARI.md §0.6'da ölçüldü: Binance **geçmiş order book
  snapshot'ı SUNMUYOR**. Bir feature ancak geçmişi varsa eğitilebilir.
  Order book derinliği, denenmemiş tek gerçek yeni bilgi kaynağı —
  mevcut 34 feature'ın TAMAMI fiyat/hacim türevi.

  Bu, "beklemenin kendisi maliyet olan" tek iş: bugün başlatmazsak
  üç hafta sonra da elimizde veri olmaz. Kaydetmeye başlamak ucuz,
  başlamamış olmak pahalı.

NE YAPMAZ:
  • Bot davranışına DOKUNMAZ. Ayrı süreç, ayrı dosya, salt-okunur API.
  • Karar üretmez, sinyal vermez, işlem açmaz.
  • Üretim durum dosyalarına yazmaz (§4.6) — yolu env ile yönlendirilebilir.

VERİ:
  Her örnekte, her sembol için ilk N seviye bid/ask.
  Türetilmiş büyüklükler HAM DEĞİL, K-26 dersine uygun kaydedilir:
  ham fiyat seviyesi feature değildir; mid'e göre normalize edilir.

KULLANIM:
  python orderbook_kaydedici.py               # sürekli kaydet
  python orderbook_kaydedici.py --tek         # tek örnek al ve çık (test)
  python orderbook_kaydedici.py --ozet        # birikeni özetle

  ORDERBOOK_DIR   kayıt dizini (varsayılan data/orderbook)
  ORDERBOOK_ARALIK_SN  örnekleme aralığı (varsayılan 60)
"""
import os
import sys
import json
import time
import gzip
import signal
import datetime as dt

# Konsol kodlaması — K-35 ile aynı sebep (Windows cp1254'te çökmesin)
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
for _akis in (sys.stdout, sys.stderr):
    try:
        _akis.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

KAYIT_DIR = os.getenv("ORDERBOOK_DIR",
                      os.path.join("data", "orderbook"))
ARALIK_SN = int(os.getenv("ORDERBOOK_ARALIK_SN", "60"))
DERINLIK = 20               # Binance ücretsiz limit kademesi: 5/10/20/50/100
_calisiyor = True


def _dur(signum, frame):
    global _calisiyor
    _calisiyor = False
    print("\n  durduruluyor (açık dosya kapatılıyor)...")


def semboller():
    try:
        from config import COINS
        return list(COINS)
    except Exception:
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]


def derinlik_al(sembol):
    """Order book snapshot — GERÇEK borsadan (K-15: testnet likiditesi ince).

    `depth` halka açık uç nokta, anahtar gerektirmiyor.
    """
    import requests
    from config import BINANCE_DATA_URL
    r = requests.get(f"{BINANCE_DATA_URL}/api/v3/depth",
                     params={"symbol": sembol, "limit": DERINLIK}, timeout=10)
    r.raise_for_status()
    return r.json()


def ozetle(sembol, ham):
    """Snapshot'tan DURAĞAN büyüklükler türet.

    K-26 dersi burada da geçerli: ham fiyat seviyesi feature değildir
    (model mutlak eşikte böler, eğitim aralığı dışına ekstrapole edemez).
    Bu yüzden her şey mid'e göre yüzde ya da oran olarak saklanıyor.

    HAM SEVİYELER DE saklanıyor (`bids`/`asks`) — bugün hangi türetmenin
    işe yarayacağını bilmiyoruz ve snapshot geri alınamaz. Türetilmiş
    alanlar kolaylık; ham veri sigortadır.
    """
    bids = [(float(p), float(q)) for p, q in ham.get("bids", [])]
    asks = [(float(p), float(q)) for p, q in ham.get("asks", [])]
    if not bids or not asks:
        return None
    en_iyi_bid, en_iyi_ask = bids[0][0], asks[0][0]
    mid = (en_iyi_bid + en_iyi_ask) / 2.0
    if mid <= 0:
        return None
    bid_hacim = sum(q for _, q in bids)
    ask_hacim = sum(q for _, q in asks)
    toplam = bid_hacim + ask_hacim

    def _yakinlik_hacmi(taraf, pct):
        sinir = mid * (pct / 100.0)
        return sum(q for p, q in taraf if abs(p - mid) <= sinir)

    return {
        "sembol": sembol,
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lastUpdateId": ham.get("lastUpdateId"),
        "mid": mid,
        # ── durağan türetmeler ────────────────────────────────
        "spread_pct": (en_iyi_ask - en_iyi_bid) / mid * 100.0,
        # Dengesizlik: −1 (tamamen satış) .. +1 (tamamen alış)
        "imbalance": (bid_hacim - ask_hacim) / toplam if toplam else 0.0,
        "bid_hacim": bid_hacim,
        "ask_hacim": ask_hacim,
        # Duvar yakınlığı: mid'in %0.1 / %0.5 içindeki likidite
        "bid_010pct": _yakinlik_hacmi(bids, 0.1),
        "ask_010pct": _yakinlik_hacmi(asks, 0.1),
        "bid_050pct": _yakinlik_hacmi(bids, 0.5),
        "ask_050pct": _yakinlik_hacmi(asks, 0.5),
        # ── HAM (geri alınamaz veri; türetmeler sonradan değişebilir) ──
        "bids": [[p, q] for p, q in bids],
        "asks": [[p, q] for p, q in asks],
    }


def _dosya_yolu(gun):
    os.makedirs(KAYIT_DIR, exist_ok=True)
    return os.path.join(KAYIT_DIR, f"ob_{gun}.jsonl.gz")


def yaz(kayitlar):
    """Güne göre gzip'li JSONL. Append — süreç ölse bile öncekiler durur."""
    gun = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    with gzip.open(_dosya_yolu(gun), "at", encoding="utf-8") as f:
        for k in kayitlar:
            f.write(json.dumps(k, separators=(",", ":")) + "\n")


def tek_tur(sessiz=False):
    alinan = []
    for s in semboller():
        try:
            o = ozetle(s, derinlik_al(s))
            if o:
                alinan.append(o)
        except Exception as e:
            # fail-loud (§5.2): sessizce atlarsak veri boşlukları
            # fark edilmez ve aylar sonra "neden eksik" diye aranır.
            print(f"  [HATA] {s}: {type(e).__name__}: {e}", flush=True)
    if alinan:
        yaz(alinan)
    if not sessiz:
        ozet = "  ".join(
            f"{k['sembol'][:3]} imb={k['imbalance']:+.3f} "
            f"sprd={k['spread_pct']:.4f}%" for k in alinan)
        print(f"  {dt.datetime.now().strftime('%H:%M:%S')}  "
              f"{len(alinan)}/{len(semboller())}  {ozet}", flush=True)
    return len(alinan)


def ozet_raporu():
    import glob
    dosyalar = sorted(glob.glob(os.path.join(KAYIT_DIR, "ob_*.jsonl.gz")))
    if not dosyalar:
        print(f"  {KAYIT_DIR} boş — kayıt henüz başlamamış.")
        return
    print(f"\n  {'dosya':<22}{'kayıt':>9}{'boyut':>11}")
    top = 0
    for d in dosyalar:
        with gzip.open(d, "rt", encoding="utf-8") as f:
            n = sum(1 for _ in f)
        top += n
        print(f"  {os.path.basename(d):<22}{n:>9}{os.path.getsize(d)/1024:>9.0f}K")
    gun = len(dosyalar)
    print(f"\n  TOPLAM {top} snapshot · {gun} gün")
    if gun and top:
        print(f"  Günlük ort: {top/gun:.0f} snapshot "
              f"({top/gun/len(semboller()):.0f} örnek/sembol)")
    print(f"\n  ⚠️  Feature olarak denemeden önce EN AZ birkaç hafta bekle.")
    print(f"     §0.6: order book'un geçmişi yok; biriktirmek tek yol.\n")


def main():
    if "--ozet" in sys.argv:
        ozet_raporu(); return
    if "--tek" in sys.argv:
        n = tek_tur()
        print(f"\n  {n} sembol kaydedildi → {KAYIT_DIR}")
        return

    signal.signal(signal.SIGINT, _dur)
    try:
        signal.signal(signal.SIGTERM, _dur)
    except (AttributeError, ValueError):
        pass

    print(f"\n{'='*60}")
    print(f"  ORDER BOOK KAYDEDİCİ — {len(semboller())} sembol, "
          f"{ARALIK_SN}s aralık, {DERINLIK} seviye")
    print(f"  Dizin: {KAYIT_DIR}")
    print(f"  Durdurmak için Ctrl+C")
    print(f"{'='*60}\n")

    tur = 0
    while _calisiyor:
        bas = time.time()
        tek_tur(sessiz=(tur % 10 != 0))     # her 10 turda bir satır bas
        tur += 1
        kalan = ARALIK_SN - (time.time() - bas)
        # Uyanık bekleme: Ctrl+C'ye hızlı cevap versin
        while kalan > 0 and _calisiyor:
            time.sleep(min(1.0, kalan))
            kalan -= 1.0
    print(f"  {tur} tur kaydedildi. Çıkılıyor.")


if __name__ == "__main__":
    main()
