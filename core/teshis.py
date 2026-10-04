# =========================================================
# ASTRA v41.0 — TEŞHİS MODÜLÜ
# main.py'den ayrıldı (modülerleştirme).
# İçerik: Giriş gecikmesi ölçümü (v28/v31) + Veto sayacı (v32).
# Bu modül bağımsızdır; sadece standart kütüphanelere bağlıdır.
# =========================================================
import time
import threading
from collections import deque

# ── Giriş gecikme ölçümü (v28/v31) ──────────────────────
# "Gecikme gerçekten zarar veriyor mu?" sorusunu veriyle yanıtlar.
_giris_gecikme_log: deque = deque(maxlen=300)
_giris_gecikme_lock = threading.Lock()
_acik_giris_gecikme: dict = {}   # {sembol: {gecikme_sn, kayma_pct, kayit_ref}}


def _giris_gecikme_kaydet(sembol: str, gecikme_sn: float,
                           kayma_pct: float, iptal: bool):
    """Her giriş denemesinin gecikme + fiyat kaymasını biriktir.
    v31: iptal edilmeyen girişler, PnL ile eşlenmek üzere saklanır."""
    kayit = {
        "ts": time.time(), "sembol": sembol,
        "gecikme_sn": round(gecikme_sn, 2),
        "kayma_pct": round(kayma_pct, 4),
        "iptal": iptal, "pnl_pct": None,
    }
    with _giris_gecikme_lock:
        _giris_gecikme_log.append(kayit)
        if not iptal:
            _acik_giris_gecikme[sembol] = {
                "gecikme_sn": round(gecikme_sn, 2),
                "kayma_pct": round(kayma_pct, 4),
                "kayit_ref": kayit,
            }


def gecikme_pnl_esle(sembol: str, pnl_pct: float):
    """v31: Pozisyon kapandığında, o girişin gecikmesine PnL'i yaz."""
    with _giris_gecikme_lock:
        info = _acik_giris_gecikme.pop(sembol, None)
        if info and "kayit_ref" in info:
            info["kayit_ref"]["pnl_pct"] = round(pnl_pct, 4)


def giris_gecikme_ozet() -> dict:
    """Gecikme istatistikleri — /gecikme komutu ve dashboard için.
    v31: gecikme-PnL korelasyonu (geç girişler daha mı kötü?)."""
    with _giris_gecikme_lock:
        kayitlar = list(_giris_gecikme_log)
    if not kayitlar:
        return {"n": 0}
    gecikmeler = [k["gecikme_sn"] for k in kayitlar]
    kaymalar   = [k["kayma_pct"] for k in kayitlar]
    iptaller   = sum(1 for k in kayitlar if k["iptal"])
    n = len(kayitlar)
    gecikmeler_s = sorted(gecikmeler)

    # Sonucu bilinen (PnL eşlenmiş) işlemleri analiz et
    sonuclu = [k for k in kayitlar if k.get("pnl_pct") is not None]
    analiz = {}
    if len(sonuclu) >= 6:
        medyan_gecikme = sorted(k["gecikme_sn"] for k in sonuclu)[len(sonuclu)//2]
        hizli = [k["pnl_pct"] for k in sonuclu if k["gecikme_sn"] <= medyan_gecikme]
        yavas = [k["pnl_pct"] for k in sonuclu if k["gecikme_sn"] >  medyan_gecikme]
        if hizli and yavas:
            analiz = {
                "eslenen_islem": len(sonuclu),
                "hizli_giris_ort_pnl": round(sum(hizli)/len(hizli), 4),
                "yavas_giris_ort_pnl": round(sum(yavas)/len(yavas), 4),
                "medyan_esik_sn": round(medyan_gecikme, 2),
            }
    return {
        "n": n,
        "ort_gecikme_sn": round(sum(gecikmeler)/n, 2),
        "medyan_gecikme_sn": round(gecikmeler_s[n//2], 2),
        "max_gecikme_sn": round(max(gecikmeler), 2),
        "ort_kayma_pct": round(sum(kaymalar)/n, 4),
        "iptal_sayisi": iptaller,
        "iptal_oran_pct": round(iptaller/n*100, 1),
        "analiz": analiz,
    }


# ── Veto sayacı (v32) ───────────────────────────────────
# "İşlem neden açılmıyor?" — her reddi nedeniyle sayar.
_veto_sayac: dict = {}
_veto_sayac_lock = threading.Lock()
_islem_acildi_sayac = [0]   # liste = mutable sayaç


def _veto_kaydet(neden: str, sembol: str = ""):
    """Bir işlemin hangi katmanda reddedildiğini say."""
    with _veto_sayac_lock:
        _veto_sayac[neden] = _veto_sayac.get(neden, 0) + 1


def _islem_acildi_kaydet():
    with _veto_sayac_lock:
        _islem_acildi_sayac[0] += 1


def veto_ozet() -> dict:
    """Veto istatistikleri — /neden komutu ve dashboard için."""
    with _veto_sayac_lock:
        sayac = dict(_veto_sayac)
        acilan = _islem_acildi_sayac[0]
    toplam_red = sum(sayac.values())
    toplam_deneme = toplam_red + acilan
    return {
        "acilan_islem": acilan,
        "toplam_red": toplam_red,
        "toplam_deneme": toplam_deneme,
        "red_dagilim": dict(sorted(sayac.items(), key=lambda x: -x[1])),
        "acilma_oran_pct": round(acilan/toplam_deneme*100, 1) if toplam_deneme else 0,
    }
