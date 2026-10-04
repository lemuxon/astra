# =========================================================
# ASTRA v30.0 — WEB DASHBOARD (Tam Yeniden Yazım)
# =========================================================
import json, logging, threading, time, base64, hmac
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from collections import deque
import sys; sys.path.append("..")
from config import (DASHBOARD_PORT, LIVE_TRADING, ASTRA_VERSION,
                    PANEL_USER, PANEL_PASS, PANEL_CORS_ORIGIN,
                    PANEL_SADECE_LOCALHOST, DB_PATH)

log = logging.getLogger("ASTRA.DASHBOARD")

_lock = threading.Lock()
_state: dict = {
    "son_analiz":        {},
    "acik_pozisyonlar":  [],
    "kapanan_islemler":  [],   # son 50 kapanan işlem — PnL geçmişi
    "futures_bakiye":    0.0,
    "paper_bakiye":      0.0,
    # v58 (K-42): ayrıntılı para dökümü — nakit / bağlı sermaye /
    # brüt PnL / ödenen komisyon / net PnL. Tek bir "bakiye" rakamı
    # komisyonun ne kadar yediğini gizliyordu.
    "para_dokumu":       {},
    "gunluk_pnl":        0.0,
    "toplam_pnl":        0.0,
    "risk_durumu":       "Başlatılıyor...",
    "toplam_sinyal":     0,
    "son_guncelleme":    "",
    # ── v58 (K-60): ZAMAN TABANI KARIŞIKLIĞI ────────────────────
    # `son_guncelleme` UTC üretiliyordu ("13:00:37 UTC") ama
    # `sinyal_gecmisi`/`kapanan_islemler` YEREL saatti ("16:00:37").
    # Kullanıcı UTC+3'te panele bakınca başlık 3 saat geride
    # görünüyordu — "saati yanlış gösteriyor" bildirimi (2026-09-06).
    # Çözüm: epoch gönder, tarayıcı KENDİ yerel saatinde biçimlendirsin.
    "son_guncelleme_ts": 0.0,      # epoch — tarayıcı biçimlendirir
    # ── v58 (K-61): ANALİZ TAZELİĞİ ─────────────────────────────
    # `son_guncelleme` HER state güncellemesinde ilerliyordu (bakiye,
    # risk vb.) ama `son_analiz` yalnızca analiz turu bitince yenilenir.
    # Sonuç: saat ilerlerken coin verisi DONABİLİYOR ve kullanıcı bunu
    # ayırt edemiyordu ("canlı coin analizleri bazen duruyor").
    "son_analiz_ts":     0.0,      # yalnızca son_analiz gelince güncellenir
    "live_trading":      LIVE_TRADING,
    "sinyal_gecmisi":    [],
    "kill_switch":       {"aktif": True, "consecutive_loss": 0},
    "adaptive_sizing":   {"kayip_seri": 0, "base_usdt": 20},
    "bot_istatistik":    {"toplam_islem": 0, "kazanan": 0, "kaybeden": 0, "win_rate": 0},
    # ── v25: Gelişmiş motor durumları ────────────────────
    "performans":        {},   # Sharpe/Sortino/Calmar/Omega
    "validator":         {},   # {sembol: {karar, skor}}
    "portfolio":         {},   # MVO ağırlıkları
    "online_learning":   {},   # {sembol: {egitim, drift}}
    "model_registry":    {},   # {sembol: {versiyon, canli_pnl}}
    "smart_exec":        {},   # TWAP/VWAP istatistik
    "ab_test":           {},   # A/B varyant karşılaştırma
    "kelly":             {},   # {sembol: {win_rate, kelly_f}}
    "multiex":           {},   # v26: çoklu borsa istatistik
}
_sinyal_gecmisi:   deque = deque(maxlen=50)
import time as _t
_kapanan_islemler: deque = deque(maxlen=50)
# v58 (K-32): aynı kapanışın iki yoldan bildirilmesini engelleyen imza
_son_kapanis_imza: dict = {}


def _db_gecmisini_yukle():
    """Başlangıçta DB'deki son 50 kapanan işlemi yükle."""
    try:
        import sqlite3, os
        # v55: config.DB_PATH kullanılıyor (eskiden os.environ doğrudan
        # okunuyordu; config path'i dönüştürürse ikisi ayrışırdı).
        db_path = DB_PATH
        if not os.path.exists(db_path):
            return
        # v55: try/finally — execute/fetchall hata verirse (örn. DB kilitli)
        # bağlantı sızıyordu. Kod tabanındaki tek istisnaydı.
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("""
                SELECT sembol, yon, giris_fiyat, cikis_fiyat,
                       pnl, pnl_yuzde, durum, ts_ac, ts_kapat
                FROM trades
                WHERE durum != 'ACIK' AND mod = 'PAPER'
                ORDER BY id DESC LIMIT 50
            """)
            rows = c.fetchall()
        finally:
            conn.close()
        # v58 (K-32): Sayaçlar SIFIRLANIR. Eskiden `+= 1` ile birikiyordu;
        # bu fonksiyon ikinci kez çalışsaydı (yeniden bağlanma, elle
        # çağrı) tüm istatistik ikiye katlanırdı. Ayrıca canlı bildirimle
        # DB yüklemesi üst üste binebiliyordu.
        ist = _state["bot_istatistik"]
        ist["toplam_islem"] = 0; ist["kazanan"] = 0
        ist["kaybeden"] = 0;     ist["win_rate"] = 0
        _kapanan_islemler.clear()
        for r in reversed(rows):
            pnl_v = float(r["pnl"] or 0)
            _kapanan_islemler.appendleft({
                "ts":       (r["ts_kapat"] or r["ts_ac"] or "")[:8],
                "sembol":   r["sembol"] or "?",
                "yon":      r["yon"] or "LONG",
                "giris":    float(r["giris_fiyat"] or 0),
                "cikis":    float(r["cikis_fiyat"] or 0),
                "pnl_usdt": round(pnl_v, 4),
                "pnl_pct":  round(float(r["pnl_yuzde"] or 0), 2),
                "sebep":    r["durum"] or "?",
                "kazandi":  pnl_v > 0,
            })
            ist["toplam_islem"] += 1
            if pnl_v > 0: ist["kazanan"] += 1
            else: ist["kaybeden"] += 1
        if ist["toplam_islem"] > 0:
            ist["win_rate"] = round(ist["kazanan"] / ist["toplam_islem"] * 100, 1)
        _state["kapanan_islemler"] = list(_kapanan_islemler)
        _state["toplam_pnl"] = round(sum(t["pnl_usdt"] for t in _kapanan_islemler), 4)
        log.info(f"[DASHBOARD] DB'den {len(rows)} kapalı işlem yüklendi")
    except Exception as e:
        log.debug(f"[DASHBOARD] DB geçmişi yüklenemedi: {e}")


def state_guncelle(**kwargs):
    with _lock:
        _state.update(kwargs)
        # v58 (K-60): epoch DA gönderiliyor; metin geriye uyumluluk için
        # kalıyor ama tarayıcı epoch'u kendi yerel saatinde biçimlendirir.
        _state["son_guncelleme_ts"] = _t.time()
        _state["son_guncelleme"] = datetime.now(
            timezone.utc).replace(tzinfo=None).strftime("%H:%M:%S UTC")
        if "son_analiz" in kwargs:
            # v58 (K-61): analiz damgası YALNIZCA burada ilerler
            _state["son_analiz_ts"] = _t.time()
            _state["toplam_sinyal"] = len(kwargs["son_analiz"])
            for sembol, v in kwargs["son_analiz"].items():
                ai = v.get("ai_score", 0)
                if abs(ai) >= 4:
                    _sinyal_gecmisi.append({
                        "ts":    datetime.now().strftime("%H:%M:%S"),
                        "sembol": sembol,
                        "ai":    ai,
                        "karar": v.get("karar", "?"),
                        "rejim": v.get("rejim", "?"),
                        "conf":  v.get("confidence", 0),
                    })
            _state["sinyal_gecmisi"] = list(_sinyal_gecmisi)


def pozisyon_kapandi_bildir(sembol: str, yon: str, giris: float,
                             cikis: float, pnl_usdt: float, pnl_pct: float,
                             sebep: str = "", miktar: float = 0):
    """Kapanan her işlemi panele bildir.

    v58 (K-32): TEKRAR KORUMASI. Bu fonksiyon iki ayrı yoldan
    çağrılabiliyordu (paper_trading doğrudan + event bus dinleyicisi) ve
    her paper kapanışı panelde İKİ KEZ görünüyordu — 2 işlem/%50 yerine
    3 işlem/%66.7. Kök neden düzeltildi (doğrudan çağrı kaldırıldı) ama
    bu kod tabanında "iki yol aynı şeyi yapıyor" TEKRAR EDEN bir hata
    sınıfı; bu yüzden fonksiyonun kendisi de aynı kapanışı reddediyor.
    """
    with _lock:
        # Aynı kapanış 60 sn içinde tekrar gelirse yoksay
        _anahtar = (sembol, yon, round(float(cikis or 0), 8),
                    round(float(pnl_usdt or 0), 6))
        _simdi = _t.time()
        _onceki = _son_kapanis_imza.get(_anahtar)
        if _onceki is not None and _simdi - _onceki < 60:
            log.debug(f"[DASHBOARD] {sembol} kapanışı zaten bildirilmiş "
                      f"({_simdi - _onceki:.1f}s önce) — tekrar yoksayıldı")
            return
        _son_kapanis_imza[_anahtar] = _simdi
        if len(_son_kapanis_imza) > 200:      # sınırsız büyümesin
            for _k in sorted(_son_kapanis_imza,
                             key=_son_kapanis_imza.get)[:100]:
                _son_kapanis_imza.pop(_k, None)

        _kapanan_islemler.appendleft({
            "ts":       datetime.now().strftime("%H:%M:%S"),
            "sembol":   sembol,
            "yon":      yon,
            "giris":    giris,
            "cikis":    cikis,
            "pnl_usdt": round(pnl_usdt, 4),
            "pnl_pct":  round(pnl_pct, 2),
            "sebep":    sebep,
            "kazandi":  pnl_usdt > 0,
        })
        _state["kapanan_islemler"] = list(_kapanan_islemler)
        # İstatistik güncelle
        ist = _state["bot_istatistik"]
        ist["toplam_islem"] += 1
        if pnl_usdt > 0:
            ist["kazanan"] += 1
        else:
            ist["kaybeden"] += 1
        ist["win_rate"] = round(ist["kazanan"] / ist["toplam_islem"] * 100, 1)
        _state["toplam_pnl"] = round(_state.get("toplam_pnl", 0) + pnl_usdt, 4)


def _nan_temizle(obj, _d=0):
    if _d > 20: return None
    if isinstance(obj, float):
        import math
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _nan_temizle(v, _d+1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_nan_temizle(v, _d+1) for v in obj]
    return obj


def _get_state_json() -> bytes:
    with _lock:
        return json.dumps(_nan_temizle(_state), default=str, ensure_ascii=False).encode("utf-8")


HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ASTRA __ASTRA_VERSION__ Dashboard</title>
<style>
:root{
  --bg:#0d1117;--card:#161b22;--card2:#1c2128;--border:#30363d;
  --text:#e6edf3;--muted:#8b949e;
  --green:#3fb950;--red:#f85149;--blue:#58a6ff;
  --yellow:#d29922;--purple:#bc8cff;--orange:#f0883e;
}
*{box-sizing:border-box;margin:0;padding:0}
/* v56: Bağlantı koptuğunda veriler görsel olarak "bayat" işaretlenir —
   ekrandaki rakamların artık güncel OLMADIĞI bir bakışta anlaşılsın. */
body.bayat .kpi-grid,body.bayat .coin-grid,body.bayat .panel,body.bayat table{
  opacity:.38;filter:grayscale(.7);transition:opacity .3s,filter .3s}
body.bayat::before{content:"⚠ BAĞLANTI YOK — aşağıdaki veriler GÜNCEL DEĞİL";
  display:block;background:var(--red);color:#fff;font-weight:700;
  text-align:center;padding:8px;margin:-16px -16px 12px -16px;
  font-size:.85rem;letter-spacing:.3px}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);padding:16px;min-height:100vh}

/* HEADER */
.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:8px}
.logo{display:flex;align-items:center;gap:10px}
.logo h1{color:var(--blue);font-size:1.25rem;font-weight:700}
.logo .ver{font-size:.7rem;background:#1f6feb30;color:var(--blue);border:1px solid #1f6feb50;
  border-radius:4px;padding:1px 7px;font-weight:600}
.header-right{display:flex;align-items:center;gap:10px;font-size:.75rem;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);
  animation:pulse 2s infinite;display:inline-block;flex-shrink:0}
.dot.red{background:var(--red);animation:none}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.75)}}

/* BADGES */
.badge{padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:600;letter-spacing:.3px;white-space:nowrap}
.b-live{background:#1a3a1f;color:var(--green);border:1px solid #2ea04340}
.b-paper{background:#1a2535;color:var(--blue);border:1px solid #1f6feb40}
.b-long{background:#1a3a1f;color:var(--green)}
.b-short{background:#3a1a1a;color:var(--red)}
.b-wait{background:#2a2a1a;color:var(--yellow)}
.b-info{background:#1a2535;color:var(--blue)}
.b-ok{background:#1a3a1f;color:var(--green)}
.b-warn{background:#3a2a1a;color:var(--orange)}
.b-dead{background:#2a1a1a;color:var(--red);border:1px solid var(--red)}

/* KPI GRID */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:20px}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;transition:.2s}
.kpi:hover{border-color:var(--blue);background:var(--card2)}
.kpi-label{color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.7px;margin-bottom:6px}
.kpi-value{font-size:1.45rem;font-weight:700;line-height:1.1}
.kpi-sub{font-size:.67rem;color:var(--muted);margin-top:4px}
.green{color:var(--green)}.red{color:var(--red)}.blue{color:var(--blue)}
.yellow{color:var(--yellow)}.muted{color:var(--muted)}

/* WIN RATE ÇUBUĞU */
.wr-bar{height:6px;border-radius:3px;background:var(--border);overflow:hidden;margin-top:6px}
.wr-fill{height:100%;border-radius:3px;transition:width .6s}

/* BÖLÜM */
.section{margin-bottom:22px}
.sec-title{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.7px;
  margin-bottom:10px;display:flex;align-items:center;gap:10px}
.sec-title::after{content:'';flex:1;height:1px;background:var(--border)}
.sec-badge{background:var(--card2);border:1px solid var(--border);border-radius:4px;
  padding:1px 7px;font-size:.68rem;color:var(--muted)}

/* TABLOLAR */
.tablo-kaydir{overflow-x:auto;-webkit-overflow-scrolling:touch}
.tablo-kaydir table{min-width:900px}
table{width:100%;border-collapse:collapse;background:var(--card);
  border-radius:10px;overflow:hidden;border:1px solid var(--border)}
th{background:var(--card2);color:var(--muted);padding:9px 12px;text-align:left;
  font-size:.7rem;text-transform:uppercase;letter-spacing:.5px}
td{padding:9px 12px;border-bottom:1px solid #21262d25;font-size:.82rem}
tr:last-child td{border-bottom:none}
tr.data-row:hover td{background:#1c212860}
.mono{font-family:'SF Mono',monospace;font-size:.82rem}

/* COİN KARTLARI */
.coin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(195px,1fr));gap:10px;margin-bottom:4px}
.coin-card{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:12px 14px;transition:.2s;border-left:3px solid var(--border)}
.coin-card:hover{background:var(--card2);transform:translateY(-1px)}
/* v58 (K-62): kart <a> oldu — varsayılan bağlantı stili notrlenir */
a.coin-card{text-decoration:none;color:inherit;display:block}
a.coin-card:hover{border-color:var(--blue)}
.coin-card.buy{border-left-color:var(--green)}
.coin-card.sell{border-left-color:var(--red)}
.coin-card.wait{border-left-color:var(--border)}
.coin-card.err{border-left-color:var(--yellow)}
.coin-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px}
.coin-name{font-weight:700;font-size:.88rem}
.coin-price{font-size:1.05rem;font-weight:600;margin-bottom:6px}
.coin-row{display:flex;gap:5px;flex-wrap:wrap;align-items:center}
.ai-bar{height:3px;border-radius:2px;margin-top:8px;background:var(--border);overflow:hidden}
.ai-fill{height:100%;border-radius:2px;transition:width .6s}

/* PNL SATIRI */
.pnl-pos{color:var(--green);font-weight:600}
.pnl-neg{color:var(--red);font-weight:600}
.pnl-neu{color:var(--muted)}

/* TAB */
.tabs{display:flex;gap:4px;margin-bottom:10px}
.tab{padding:5px 14px;border-radius:6px;font-size:.75rem;cursor:pointer;
  background:var(--card);border:1px solid var(--border);color:var(--muted);transition:.15s}
.tab.active{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
.tab-content{display:none}.tab-content.active{display:block}

/* FOOTER */
.footer{color:var(--muted);font-size:.7rem;margin-top:20px;
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px}

/* v25: SİSTEM ZEKASI PANELİ */
.intel-section{margin-top:22px}
.intel-title{font-size:1.05rem;color:var(--purple);margin-bottom:12px;
  display:flex;align-items:center;gap:8px;font-weight:700}
.intel-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.intel-card{background:var(--card);border:1px solid var(--border);
  border-radius:12px;padding:14px;min-height:120px}
.intel-card-h{font-size:.82rem;font-weight:700;color:var(--text);
  margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.intel-body{font-size:.78rem;line-height:1.75}
.intel-body .im{color:var(--muted);font-size:.74rem}
.intel-row{display:flex;justify-content:space-between;gap:8px;padding:2px 0}
.intel-row .k{color:var(--muted)}
.intel-row .v{font-weight:600}
.mini-bar{height:5px;background:var(--card2);border-radius:3px;margin-top:3px;overflow:hidden}
.mini-fill{height:5px;border-radius:3px}
.pill{display:inline-block;font-size:.66rem;padding:1px 7px;border-radius:10px;font-weight:700}
.pill.ok{background:#3fb95025;color:var(--green);border:1px solid #3fb95050}
.pill.no{background:#f8514925;color:var(--red);border:1px solid #f8514950}

/* RESPONSIVE */
@media(max-width:640px){
  .kpi-grid{grid-template-columns:1fr 1fr}
  .coin-grid{grid-template-columns:1fr 1fr}
  .header{flex-direction:column;align-items:flex-start}
  .intel-grid{grid-template-columns:1fr}
}
@media(max-width:980px) and (min-width:641px){
  .intel-grid{grid-template-columns:1fr 1fr}
}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="logo">
    <span class="dot" id="live-dot"></span>
    <h1>ASTRA</h1>
    <span class="ver">__ASTRA_VERSION__</span>
  </div>
  <div class="header-right">
    <span class="badge" id="mod-badge">...</span>
    <span id="conn-status">Bağlanıyor...</span>
    <span id="update-time" style="font-size:.68rem"></span>
  </div>
</div>

<!-- KPI KARTLARI -->
<div class="kpi-grid">
  <div class="kpi">
    <div class="kpi-label">Bakiye</div>
    <div class="kpi-value blue" id="k-bakiye">—</div>
    <div class="kpi-sub" id="k-bakiye-sub">—</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Toplam PnL</div>
    <div class="kpi-value" id="k-pnl">—</div>
    <div class="kpi-sub" id="k-pnl-sub">Tüm işlemler</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Günlük PnL</div>
    <div class="kpi-value" id="k-gunluk">—</div>
    <div class="kpi-sub">Bugün</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Win Rate</div>
    <div class="kpi-value" id="k-wr">—</div>
    <div class="kpi-sub" id="k-wr-sub">0 işlem</div>
    <div class="wr-bar"><div class="wr-fill" id="wr-fill" style="width:0%;background:var(--muted)"></div></div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Açık Pozisyon</div>
    <div class="kpi-value blue" id="k-poz">0</div>
    <div class="kpi-sub" id="k-poz-sub">Yok</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Risk / Kill Switch</div>
    <div class="kpi-value" id="k-risk">—</div>
    <div class="kpi-sub" id="k-kill">✅ İşlem Aktif</div>
  </div>
</div>

<!-- COİN ANALİZLERİ -->
<div class="section">
  <div class="sec-title">Canlı Coin Analizleri <span class="sec-badge" id="analiz-zaman"></span></div>
  <div class="coin-grid" id="coin-grid">
    <div style="color:var(--muted);padding:20px;font-size:.85rem;grid-column:1/-1">
      Analiz bekleniyor — bot başlatılıyor...
    </div>
  </div>
</div>

<!-- SEKMELER: POZİSYONLAR / GEÇMİŞ / SİNYALLER -->
<div class="section">
  <div class="tabs">
    <button class="tab active" onclick="switchTab('acik')">📊 Açık Pozisyonlar <span id="tab-acik-n"></span></button>
    <button class="tab" onclick="switchTab('gecmis')">📋 İşlem Geçmişi <span id="tab-gecmis-n"></span></button>
    <button class="tab" onclick="switchTab('sinyaller')">📡 Sinyal Geçmişi <span id="tab-sig-n"></span></button>
  </div>

  <!-- AÇIK POZİSYONLAR -->
  <div class="tab-content active" id="tab-acik">
    <!-- v58 K-90: 13 sütun dar ekrana sığmıyor. Tablo KENDİ içinde
         kayar; sayfa gövdesi yatay kaymaz. -->
    <div class="tablo-kaydir">
    <table>
      <thead><tr>
        <th>Coin</th><th>Yön</th><th>Giriş</th><th>Güncel</th>
        <th>Stop (SL)</th><th>Hedef (TP)</th><th>Tasfiye</th>
        <th>PnL (USDT)</th><th>PnL %</th>
        <th>Kald.</th><th>Marjin</th><th>Zaman stop</th><th>Kaynak</th>
      </tr></thead>
      <tbody id="poz-tbody">
        <tr><td colspan="13" style="color:var(--muted);text-align:center;padding:24px">Açık pozisyon yok</td></tr>
      </tbody>
    </table>
    </div>
  </div>

  <!-- İŞLEM GEÇMİŞİ -->
  <div class="tab-content" id="tab-gecmis">
    <table>
      <thead><tr>
        <th>Saat</th><th>Coin</th><th>Yön</th><th>Giriş</th><th>Çıkış</th>
        <th>PnL</th><th>PnL %</th><th>Sebep</th>
      </tr></thead>
      <tbody id="gecmis-tbody">
        <tr><td colspan="8" style="color:var(--muted);text-align:center;padding:24px">Henüz kapanan işlem yok</td></tr>
      </tbody>
    </table>
  </div>

  <!-- SİNYAL GEÇMİŞİ -->
  <div class="tab-content" id="tab-sinyaller">
    <table>
      <thead><tr>
        <th>Saat</th><th>Coin</th><th>AI Skor</th><th>Rejim</th><th>Karar</th><th>Güven</th>
      </tr></thead>
      <tbody id="sig-tbody">
        <tr><td colspan="6" style="color:var(--muted);text-align:center;padding:24px">Güçlü sinyal bekleniyor (AI ≥ 4)...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ═══ v25: SİSTEM ZEKASI PANELİ ═══ -->
<div class="intel-section">
  <h2 class="intel-title">🧠 Sistem Zekası <span style="font-size:.65rem;color:var(--muted)">canlı motor durumları</span></h2>
  <div class="intel-grid">
    <!-- Performans metrikleri -->
    <div class="intel-card">
      <div class="intel-card-h">📊 Performans</div>
      <div id="intel-perf" class="intel-body"><span class="im">veri bekleniyor...</span></div>
    </div>
    <!-- Validator (v24) -->
    <div class="intel-card">
      <div class="intel-card-h">🛡️ Dayanıklılık Kapısı</div>
      <div id="intel-val" class="intel-body"><span class="im">veri bekleniyor...</span></div>
    </div>
    <!-- Portfolio MVO -->
    <div class="intel-card">
      <div class="intel-card-h">⚖️ Portföy Dağılımı</div>
      <div id="intel-port" class="intel-body"><span class="im">veri bekleniyor...</span></div>
    </div>
    <!-- Online learning + Kelly -->
    <div class="intel-card">
      <div class="intel-card-h">🧬 Öğrenme & Kelly</div>
      <div id="intel-learn" class="intel-body"><span class="im">veri bekleniyor...</span></div>
    </div>
    <!-- A/B test -->
    <div class="intel-card">
      <div class="intel-card-h">🧪 A/B Test</div>
      <div id="intel-ab" class="intel-body"><span class="im">veri bekleniyor...</span></div>
    </div>
    <!-- Smart execution + registry -->
    <div class="intel-card">
      <div class="intel-card-h">⚡ Execution & Model</div>
      <div id="intel-exec" class="intel-body"><span class="im">veri bekleniyor...</span></div>
    </div>
    <!-- v36: İşlem teşhisi (neden açılmıyor) -->
    <div class="intel-card">
      <div class="intel-card-h">📊 İşlem Teşhisi</div>
      <div id="intel-veto" class="intel-body"><span class="im">veri bekleniyor...</span></div>
    </div>
    <!-- v36: Giriş gecikmesi -->
    <div class="intel-card">
      <div class="intel-card-h">⏱️ Giriş Gecikmesi</div>
      <div id="intel-gecikme" class="intel-body"><span class="im">veri bekleniyor...</span></div>
    </div>
  </div>
</div>

<div class="footer">
  <span>ASTRA AI Trader <b style="color:var(--blue)">__ASTRA_VERSION__</b> — Kendi Kendini Eğiten Futures Botu</span>
  <span id="refresh-info" style="color:var(--muted)">0 güncelleme</span>
</div>

<script>
'use strict';
let refreshCount = 0;
let sonBasariliMs = 0;   // v56: son başarılı /api/state zamanı (bayatlık için)

// ── Yardımcılar ──────────────────────────────────────────
// v55 SAVUNMA DERİNLİĞİ: innerHTML'e yazılan her dinamik metin bundan geçmeli.
// Bugün bu değerler yalnızca botun kendi sabit sembol listesinden ve
// dahili karar dizgelerinden geliyor (sömürülebilir değil), ancak ileride
// borsadan gelen serbest metin bir alana girerse bu XSS'e dönüşürdü.
const esc = v => String(v == null ? '' : v)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const fmt = (n, d=2) => parseFloat(n||0).toLocaleString('tr-TR',{minimumFractionDigits:d,maximumFractionDigits:d});
const pnlClass  = n => n > 0 ? 'pnl-pos' : n < 0 ? 'pnl-neg' : 'pnl-neu';
// v56 DÜZELTME: Bu iki yardımcı `Math.abs()` kullanıp negatifte HİÇ işaret
// koymuyordu → 12.34$ ZARAR, panelde "12,3400 USDT" olarak (artı gibi)
// görünüyordu. Yalnızca CSS rengi ayırt ediyordu; renk körü bir kullanıcı
// veya ekran görüntüsü paylaşımı için kâr ile zarar AYIRT EDİLEMEZDİ.
// Finansal panelde işaretsiz sayı kabul edilemez.
const pnlSign   = n => (n >= 0 ? '+' : '−') + fmt(Math.abs(n), 4);
const pnlSignPct= n => (n >= 0 ? '+' : '−') + fmt(Math.abs(n), 2) + '%';
// v56: Tüm $ tutarlı PnL göstergeleri BU yardımcıdan geçmeli. Aynı
// "işaretsiz negatif" hatası 4 ayrı yerde tekrarlanmıştı (toplam PnL,
// günlük PnL, açık PnL, pozisyon satırı) çünkü her biri formatı elle
// yazıyordu. Tek noktaya bağlandı.
const pnlSignUsd= n => (n >= 0 ? '+' : '−') + '$' + fmt(Math.abs(n), 2);
const cls       = n => n > 0 ? 'green' : n < 0 ? 'red' : 'muted';
// ── v58 K-41: BU SATIR "WEAK BUY" ROZETİNİ BOZUYORDU ──────────
// Eski hali:  .replace(/[🚀✅📈💀🔴📉⏳⚠️]/g,'')
// İki hata birden:
//  1. Listede 📊 YOK — WEAK BUY / WEAK SELL kararları onu kullanıyor.
//  2. `u` bayrağı olmadan astral emoji karakter sınıfı BOZUKTUR.
//     JavaScript'te bu emoji'ler VEKİL ÇİFTİ (surrogate pair) ile
//     temsil edilir. `u` bayrağı yokken karakter sınıfı çiftleri
//     ayrıştıramaz ve tek tek vekil kodlarına dağılır. 📊 ile 🚀 AYNI
//     yüksek vekili paylaştığı için 📊'nın yüksek vekili siliniyor,
//     geriye YALNIZ KALAN düşük vekil kalıyor — ve yalnız vekil
//     ekranda U+FFFD, yani � olarak görünür.
//     Ölçüldü: "📊 WEAK BUY" -> "� WEAK BUY" (kullanıcı bildirimi).
//     Diğer kararlarda emoji tam eşleştiği için temiz siliniyordu;
//     bu yüzden sorun YALNIZCA WEAK BUY/SELL'de görünüyordu.
//
// Düzeltme: emoji artık SİLİNMİYOR. Kullanıcı görünmesini istedi
// ("logoları görünsün"), ve silmeye zaten gerek yok — rozet metni
// ikonla birlikte daha okunaklı. Sadece fazla boşluk normalize edilir.
// Not: emoji silmek gerekirse doğru yol /\p{Extended_Pictographic}/gu.
const cleanKarar= s => (s||'').replace(/\s+/g,' ').trim();

// v58 (K-60): epoch → TARAYICININ yerel saati.
// Sunucu UTC metni gönderiyordu; UTC+3'teki kullanıcı 3 saat geride
// görüyordu. Epoch tek doğru kaynak, biçimlendirme istemcide.
function yerelSaat(ts) {
  if (!ts) return '';
  try {
    return new Date(ts * 1000).toLocaleTimeString('tr-TR', {hour12: false});
  } catch (e) { return ''; }
}

// v58 (K-62): Coin kartından Binance'e git.
// Kullanıcı isteği: "bazı coinlerin üzerine tıkladığımda beni o coinle
// ilgili binance bağlantısına götürsün."
// Bot FUTURES'ta işlem yapıyor, o yüzden futures grafiğine gidiliyor.
// `encodeURIComponent`: sembol dahili dizgelerden geliyor ama URL'e
// giren her değer yine de kaçırılır.
function binanceUrl(sym) {
  const s = String(sym || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  if (!s) return '#';
  return 'https://www.binance.com/tr/futures/' + encodeURIComponent(s);
}

// ── Tab geçişi ────────────────────────────────────────────
function switchTab(id) {
  document.querySelectorAll('.tab').forEach((t,i) => {
    const ids = ['acik','gecmis','sinyaller'];
    t.classList.toggle('active', ids[i] === id);
  });
  document.querySelectorAll('.tab-content').forEach(c => {
    c.classList.toggle('active', c.id === 'tab-'+id);
  });
}

// ── Ana güncelleme ────────────────────────────────────────
const BAYAT_ESIK_SN = 30;      // v58 (K-74): bu kadar saniye veri gelmezse GERÇEK kesinti
let _istekUcuyor = false;      // v58 (K-74): çakışan istekleri engelle
async function guncelle() {
  // Yavaş bir yanıt sürerken yenisini başlatmak kuyruğu büyütür ve
  // gecikmeyi ARTIRIR (ölçümde p95 10 sn idi).
  if (_istekUcuyor) return;
  _istekUcuyor = true;
  try {
    const r = await fetch('/api/state', {cache:'no-store'});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const s = await r.json();

    // Bağlantı
    sonBasariliMs = Date.now();          // v56: bayatlık takibi
    document.body.classList.remove('bayat');
    document.getElementById('live-dot').className = 'dot';
    const cs = document.getElementById('conn-status');
    cs.textContent = '● Canlı'; cs.style.color = 'var(--green)';
    // v58 (K-60): epoch'tan TARAYICININ yerel saatinde biçimlendir.
    // Eskiden sunucunun ürettiği UTC metni basılıyordu; kullanıcı
    // UTC+3'te başlığı 3 saat geride görüyordu.
    document.getElementById('update-time').textContent = yerelSaat(s.son_guncelleme_ts) || s.son_guncelleme || '';

    // Mod badge
    const mb = document.getElementById('mod-badge');
    if (s.live_trading) { mb.textContent = '🔴 LIVE'; mb.className = 'badge b-live'; }
    else                { mb.textContent = '📄 PAPER'; mb.className = 'badge b-paper'; }

    // ── KPI: Bakiye ──────────────────────────────────────
    const bak = s.live_trading
      ? parseFloat(s.futures_bakiye||0)
      : parseFloat(s.paper_bakiye||s.futures_bakiye||0);
    document.getElementById('k-bakiye').textContent = '$' + fmt(bak);
    document.getElementById('k-bakiye-sub').textContent = s.live_trading ? 'Futures Bakiye' : 'Paper Bakiye';

    // ── KPI: Toplam PnL ──────────────────────────────────
    const tpnl = parseFloat(s.toplam_pnl||0);
    const tpnlEl = document.getElementById('k-pnl');
    tpnlEl.textContent = pnlSignUsd(tpnl);   // v56: negatifte işaret düşüyordu
    tpnlEl.className = 'kpi-value ' + cls(tpnl);

    // ── KPI: Günlük PnL ──────────────────────────────────
    const gpnl = parseFloat(s.gunluk_pnl||0);
    const gpnlEl = document.getElementById('k-gunluk');
    // v56: negatifte işaret düşüyordu — günlük ZARAR, kâr gibi görünüyordu
    gpnlEl.textContent = pnlSignUsd(gpnl);
    gpnlEl.className = 'kpi-value ' + cls(gpnl);

    // ── KPI: Win Rate ─────────────────────────────────────
    const ist = s.bot_istatistik || {};
    const wr  = parseFloat(ist.win_rate||0);
    const wrEl = document.getElementById('k-wr');
    wrEl.textContent = wr > 0 ? '%' + fmt(wr,1) : '—';
    wrEl.className = 'kpi-value ' + (wr >= 55 ? 'green' : wr >= 40 ? 'yellow' : wr > 0 ? 'red' : 'muted');
    document.getElementById('k-wr-sub').textContent =
      `${ist.kazanan||0}K / ${ist.kaybeden||0}K (${ist.toplam_islem||0} işlem)`;
    const wrFill = document.getElementById('wr-fill');
    wrFill.style.width = wr + '%';
    wrFill.style.background = wr >= 55 ? 'var(--green)' : wr >= 40 ? 'var(--yellow)' : 'var(--red)';

    // ── KPI: Açık Pozisyon ────────────────────────────────
    const pozlar = s.acik_pozisyonlar || [];
    document.getElementById('k-poz').textContent = pozlar.length || '0';
    const pozPnl = pozlar.reduce((a,p) => a + parseFloat(p.pnl||0), 0);
    document.getElementById('k-poz-sub').className = 'kpi-sub ' + (pozPnl >= 0 ? 'green' : 'red');
    document.getElementById('k-poz-sub').textContent = pozlar.length > 0
      ? pnlSignUsd(pozPnl) + ' açık PnL'   // v56: negatifte işaret düşüyordu
      : 'Pozisyon yok';

    // ── KPI: Risk / Kill Switch ───────────────────────────
    const riskStr = s.risk_durumu || 'Normal';
    const ks = s.kill_switch || {};
    const rEl = document.getElementById('k-risk');
    rEl.textContent = riskStr;
    rEl.className = 'kpi-value ' +
      (riskStr.includes('Kritik')||riskStr.includes('Dur') ? 'red' :
       riskStr.includes('Dikkat') ? 'yellow' : 'green');
    const killEl = document.getElementById('k-kill');
    if (ks.aktif === false) {
      killEl.textContent = '🛑 KİLL SWITCH AKTİF';
      killEl.className = 'kpi-sub red';
    } else {
      const loss = ks.consecutive_loss || 0;
      killEl.textContent = loss > 0 ? `⚠️ Ard arda kayıp: ${loss}` : '✅ İşlem Aktif';
      killEl.className = 'kpi-sub ' + (loss >= 3 ? 'yellow' : 'muted');
    }

    // ── COİN KARTLARI ─────────────────────────────────────
    const analizler = s.son_analiz || {};
    const coinGrid  = document.getElementById('coin-grid');
    const entries   = Object.entries(analizler);
    // ── v58 (K-61): ANALİZ TAZELİĞİ ───────────────────────
    // Eskiden burada `son_guncelleme` yazıyordu — o HER state
    // güncellemesinde (bakiye, risk...) ilerliyor. Analiz turu dursa
    // bile saat akmaya devam ediyordu ve kullanıcı donmayı göremiyordu.
    // Artık YALNIZCA analiz geldiğinde ilerleyen damga + yaş rozeti.
    (function(){
      const el = document.getElementById('analiz-zaman');
      const ts = s.son_analiz_ts || 0;
      if (!ts) { el.textContent = '—'; el.style.color = 'var(--muted)'; return; }
      const yasSn = Math.max(0, Math.floor(Date.now()/1000 - ts));
      let yasMetin;
      if (yasSn < 90)      yasMetin = yasSn + ' sn önce';
      else if (yasSn < 5400) yasMetin = Math.round(yasSn/60) + ' dk önce';
      else                 yasMetin = (yasSn/3600).toFixed(1) + ' sa önce';
      el.textContent = yerelSaat(ts) + '  ·  ' + yasMetin;
      // 4h barda tur ~1 dk sürer; 10 dk sessizlik analiz DURMUŞ demektir
      el.style.color = yasSn > 600 ? 'var(--red)'
                     : yasSn > 300 ? 'var(--yellow)' : 'var(--muted)';
    })();

    if (entries.length === 0) {
      coinGrid.innerHTML = '<div style="color:var(--muted);padding:20px;grid-column:1/-1">Analiz bekleniyor...</div>';
    } else {
      coinGrid.innerHTML = entries.map(([sym, v]) => {
        const ai    = v.ai_score || 0;
        const karar = v.karar || '?';
        const isBuy = karar.includes('BUY');
        const isSell= karar.includes('SELL');
        const isErr = karar.includes('HATA');
        const cardCls = isErr ? 'err' : isBuy ? 'buy' : isSell ? 'sell' : 'wait';
        const bCls    = isBuy ? 'b-long' : isSell ? 'b-short' : isErr ? 'b-warn' : 'b-wait';
        const aiPct   = Math.min(Math.abs(ai)/12*100, 100);
        const aiColor = ai > 0 ? 'var(--green)' : ai < 0 ? 'var(--red)' : 'var(--muted)';
        const edge    = (v.edge_sonuc||{}).gecti;
        const rejim   = v.rejim || '?';
        const conf    = v.confidence || 0;
        // v25: CVD divergence + validator durumu
        const cvd     = v.cvd_data || {};
        const cvdDiv  = cvd.divergence === true;
        const valOk   = (s.validator||{})[sym];
        const valBadge = valOk ? (valOk.onay
            ? '<span class="pill ok" style="font-size:.6rem">🛡️</span>'
            : '<span class="pill no" style="font-size:.6rem">⛔</span>') : '';
        // v58 (K-62): kart tıklanabilir — Binance futures sayfasına gider.
        // `rel="noopener noreferrer"`: yeni sekme açan bağlantı, açan
        // sayfaya `window.opener` üzerinden erişememeli.
        return `<a class="coin-card ${cardCls}" href="${binanceUrl(sym)}"
                   target="_blank" rel="noopener noreferrer"
                   title="Binance'de ${esc(sym)} grafiğini aç">
          <div class="coin-header">
            <span class="coin-name">${esc(sym.replace('USDT',''))}<span style="color:var(--muted);font-size:.68rem;font-weight:400">USDT</span> ${valBadge}<span style="color:var(--muted);font-size:.62rem;margin-left:4px">↗</span></span>
            <span class="badge ${bCls}">${cleanKarar(karar)||'WAIT'}</span>
          </div>
          <div class="coin-price ${cls(ai)}">$${fmt(v.son_close||0, 2)}</div>
          <div class="coin-row">
            <span style="font-size:.72rem">AI <b style="color:${aiColor}">${ai>0?'+':''}${ai}</b></span>
            <span style="font-size:.72rem;color:var(--muted)">%${conf}</span>
            <span style="font-size:.72rem;color:var(--muted)">${rejim}</span>
            <span style="font-size:.68rem">${edge===true?'✅':'❌'} Edge</span>
            ${cvdDiv?'<span style="font-size:.66rem;color:var(--orange)">⚠CVD</span>':''}
          </div>
          <div class="ai-bar"><div class="ai-fill" style="width:${aiPct}%;background:${aiColor}"></div></div>
        </a>`;
      }).join('');
    }

    // ── AÇIK POZİSYONLAR ─────────────────────────────────
    document.getElementById('tab-acik-n').textContent = pozlar.length > 0 ? `(${pozlar.length})` : '';
    const pozTbody = document.getElementById('poz-tbody');
    if (pozlar.length === 0) {
      pozTbody.innerHTML = '<tr><td colspan="13" style="color:var(--muted);text-align:center;padding:24px">Açık pozisyon yok</td></tr>';
    } else {
      pozTbody.innerHTML = pozlar.map(p => {
        const yon    = p.yon || '?';
        const pnlV   = parseFloat(p.pnl || 0);
        // v56 DÜZELTME: Eskiden yüzde `(p.cikis||p.guncel||0)` üzerinden
        // hesaplanıyordu, ancak main.py açık pozisyonlarda NE cikis NE guncel
        // gönderiyor → ifade daima (0 - giris)/giris*100 = -100 veriyordu.
        // İşaret ise pnlV'den alındığı için her satır "±100,00%" gösteriyordu
        // (kârlı pozisyonda +100%, zararlıda −100%) — tamamen anlamsız.
        // Doğrusu: PnL'i pozisyonun maliyetine (giriş × miktar) oranlamak.
        const giris  = parseFloat(p.giris || 0);
        const miktar = Math.abs(parseFloat(p.miktar || 0));
        const notional = giris * miktar;
        const pnlPct = notional > 0 ? (pnlV / notional * 100) : 0;
        const kaynak = p.kaynak || 'LIVE';
        // v58 (K-90): koruma seviyeleri. Bu alanlar `trades` satırında
        // zaten duruyordu; panel hiçbirini okumuyordu. Kaldıraçlı bir
        // pozisyonda bakılacak asıl sayılar bunlar.
        //
        // ⚠️ EKSİK ALAN "—" GÖSTERİLİR, 0 DEĞİL (§5.1). Canlı (futures)
        // yolu bu alanları göndermiyor; 0 basmak "stop sıfırda" diye
        // okunur ve korumasız pozisyonda YANLIŞ güvence verirdi.
        const guncel = (p.guncel==null) ? null : parseFloat(p.guncel);
        // Mesafe GÜNCEL fiyattan ölçülür — "buradan ne kadar uzakta"
        // sorusu, girişten olan mesafeden daha kullanışlı.
        const ref = (guncel && guncel>0) ? guncel : giris;
        const uzaklik = (v) => (v==null || !ref) ? '' :
          `<span class="muted" style="font-size:.85em"> ${((v-ref)/ref*100).toFixed(1)}%</span>`;
        const seviye = (v, kritik) => (v==null)
          ? '<span class="muted">—</span>'
          : `<span class="mono${kritik?' '+pnlClass(-1):''}">$${fmt(v,4)}</span>${uzaklik(v)}`;
        // Zaman stop: motorun `zaman_stop_doldu_mu()` ufkuyla AYNI değer
        // (main.py `_zaman_stop_saat()` config.ZAMAN_STOP_SN'den okur).
        let zaman = '<span class="muted">—</span>';
        if (p.gecen_saat != null && p.zaman_stop_saat) {
          const kalan = p.zaman_stop_saat - p.gecen_saat;
          zaman = p.zaman_stop_doldu
            ? `<span class="${pnlClass(-1)}">doldu</span>`
            : `<span class="mono">${p.gecen_saat.toFixed(1)}</span>` +
              `<span class="muted">/${p.zaman_stop_saat}s</span>` +
              (kalan <= 2 ? `<span class="${pnlClass(-1)}" style="font-size:.85em"> ${kalan.toFixed(1)}s</span>` : '');
        }
        return `<tr class="data-row">
          <td><b>${esc(p.sembol||'?')}</b></td>
          <td><span class="badge ${yon==='LONG'?'b-long':'b-short'}">${yon}</span></td>
          <td class="mono">$${fmt(p.giris||0, 4)}</td>
          <td class="mono">${guncel!=null ? '$'+fmt(guncel,4) : '<span class="muted">—</span>'}</td>
          <td>${seviye(p.stop_loss)}</td>
          <td>${seviye(p.take_profit)}</td>
          <td>${seviye(p.tasfiye, true)}</td>
          <td class="mono ${pnlClass(pnlV)}">${pnlSign(pnlV)} USDT</td>
          <td class="${pnlClass(pnlPct)}">${pnlSignPct(pnlPct)}</td>
          <td>${(p.kaldirac==null||p.kaldirac==='')?'?':p.kaldirac+'x'}</td>
          <td class="mono">${p.marjin!=null ? '$'+fmt(p.marjin,2) : '<span class="muted">—</span>'}</td>
          <td>${zaman}</td>
          <td><span class="badge ${kaynak==='PAPER'?'b-paper':kaynak==='LIVE'?'b-live':'b-info'}">${kaynak}</span></td>
        </tr>`;
      }).join('');
    }

    // ── İŞLEM GEÇMİŞİ (Kar/Zarar dengesi) ───────────────
    const kapanan = s.kapanan_islemler || [];
    document.getElementById('tab-gecmis-n').textContent = kapanan.length > 0 ? `(${kapanan.length})` : '';
    const gecmisTbody = document.getElementById('gecmis-tbody');
    if (kapanan.length === 0) {
      gecmisTbody.innerHTML = '<tr><td colspan="8" style="color:var(--muted);text-align:center;padding:24px">Henüz kapanan işlem yok</td></tr>';
    } else {
      gecmisTbody.innerHTML = kapanan.map(t => {
        const yon  = t.yon || '?';
        const pnlV = parseFloat(t.pnl_usdt || 0);
        const pPct = parseFloat(t.pnl_pct  || 0);
        const sebepMap = {'TP':'🎯 TP','SL':'🛑 SL','SIGNAL':'📡 Sinyal',
          'SELL_SİNYALİ':'📉 Ters','BUY_SİNYALİ':'📈 Ters','MANUEL':'👤 Manuel'};
        const sebepStr = sebepMap[t.sebep] || t.sebep || '?';
        return `<tr class="data-row">
          <td class="mono muted">${t.ts||'?'}</td>
          <td><b>${esc(t.sembol||'?')}</b></td>
          <td><span class="badge ${yon==='LONG'?'b-long':'b-short'}">${yon}</span></td>
          <td class="mono">$${fmt(t.giris||0,4)}</td>
          <td class="mono">$${fmt(t.cikis||0,4)}</td>
          <td class="mono ${pnlClass(pnlV)}">${pnlSign(pnlV)} USDT</td>
          <td class="${pnlClass(pPct)}">${pnlSignPct(pPct)}</td>
          <td>${sebepStr}</td>
        </tr>`;
      }).join('');
    }

    // ── SİNYAL GEÇMİŞİ ───────────────────────────────────
    const gecmis = (s.sinyal_gecmisi || []).slice().reverse();
    document.getElementById('tab-sig-n').textContent = gecmis.length > 0 ? `(${gecmis.length})` : '';
    const sigTbody = document.getElementById('sig-tbody');
    if (gecmis.length === 0) {
      sigTbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:24px">Güçlü sinyal bekleniyor (AI ≥ 4)...</td></tr>';
    } else {
      sigTbody.innerHTML = gecmis.map(g => {
        const ai   = g.ai || 0;
        const bCls = (g.karar||'').includes('BUY') ? 'b-long' : (g.karar||'').includes('SELL') ? 'b-short' : 'b-wait';
        return `<tr class="data-row">
          <td class="mono muted">${g.ts||'?'}</td>
          <td><b>${esc(g.sembol||'?')}</b></td>
          <td class="${cls(ai)}">${ai>0?'+':''}${ai}</td>
          <td>${g.rejim||'?'}</td>
          <td><span class="badge ${bCls}">${cleanKarar(g.karar)}</span></td>
          <td>%${g.conf||0}</td>
        </tr>`;
      }).join('');
    }

    // ── v25: SİSTEM ZEKASI PANELLERİ ─────────────────────
    renderIntel(s);

    refreshCount++;
    document.getElementById('refresh-info').textContent = `${refreshCount} güncelleme`;

  } catch(e) {
    // v56: Eskiden yalnızca küçük bağlantı göstergesi kırmızıya dönüyordu;
    // BAKİYE / PNL / POZİSYON değerleri ekranda AYNEN kalıyordu. Bota şöyle
    // bir bakan operatör bayat rakamları güncel sanabilirdi — bot çökmüşken
    // "her şey yolunda" izlenimi, korumasız kalmaktan daha tehlikelidir.
    // Artık veri görsel olarak soluklaşıyor ve kaç saniyedir bayat olduğu yazıyor.
    // ── v58 (K-74): TEK YAVAŞ YANIT "BAĞLANTI YOK" DEMEK DEĞİLDİR ──
    // Eskiden ilk başarısız istekte kırmızıya dönüyordu. Ölçümde
    // isteklerin %43'ü 2 sn'yi aşıyordu (analiz turunun CPU yükü),
    // yani kullanıcı sürekli "internet kesildi" görüyordu — oysa bot
    // ve bağlantı SAĞLAMDI. Sahte alarm, gerçek alarmı değersizleştirir.
    //
    // Artık eşik VERİNİN BAYATLIĞI: veri hâlâ tazeyse (< BAYAT_ESIK_SN)
    // sarı "gecikme" gösterilir, veri gerçekten eskiyince kırmızı.
    const saniye = sonBasariliMs ? Math.round((Date.now() - sonBasariliMs)/1000) : null;
    const cs = document.getElementById('conn-status');
    if (saniye !== null && saniye < BAYAT_ESIK_SN) {
      // Geçici yavaşlık — veriler hâlâ geçerli, soluklaştırma YAPMA.
      document.getElementById('live-dot').className = 'dot';
      cs.textContent = '● Yanıt gecikti (' + saniye + 's) — veriler geçerli';
      cs.style.color = 'var(--orange)';
    } else {
      document.body.classList.add('bayat');
      document.getElementById('live-dot').className = 'dot red';
      cs.textContent = saniye === null
        ? '● BAĞLANTI YOK — veri alınamadı (' + e.message + ')'
        : '● BAĞLANTI YOK — veriler ' + saniye + 's bayat (' + e.message + ')';
      cs.style.color = 'var(--red)';
    }
  } finally {
    // v58 (K-74): bayrak HER durumda inmeli — aksi halde ilk hatadan
    // sonra panel kalıcı olarak donar (kendi eklediğim tek-uçuş
    // korumasının sessiz kilitlenmesi).
    _istekUcuyor = false;
  }
}

// ── v25: Sistem Zekası render ──────────────────────────────
function row(k, v, color) {
  return `<div class="intel-row"><span class="k">${k}</span><span class="v" ${color?`style="color:${color}"`:''}>${v}</span></div>`;
}
function renderIntel(s) {
  // Performans
  const p = s.performans || {};
  const perfEl = document.getElementById('intel-perf');
  if (p.orneklem) {
    const sh = p.sharpe||0, so = p.sortino||0;
    perfEl.innerHTML =
      row('Sharpe', (sh>=0?'+':'')+fmt(sh,2), sh>0?'var(--green)':'var(--red)') +
      row('Sortino', (so>=0?'+':'')+fmt(so,2), so>0?'var(--green)':'var(--red)') +
      row('Calmar', fmt(p.calmar||0,2)) +
      row('Omega', fmt(p.omega||0,2)) +
      row('Max DD', '%'+fmt(p.max_drawdown_pct||0,1), 'var(--orange)') +
      `<div class="im">${p.orneklem} işlem örneklemi</div>`;
  } else { perfEl.innerHTML = '<span class="im">yeterli işlem yok</span>'; }

  // Validator (v24)
  const val = s.validator || {};
  const valEl = document.getElementById('intel-val');
  const vk = Object.entries(val);
  if (vk.length) {
    valEl.innerHTML = vk.map(([sym,v]) =>
      `<div class="intel-row"><span class="k">${esc(sym.replace('USDT',''))}</span>`+
      `<span class="v"><span class="pill ${v.onay?'ok':'no'}">${v.onay?'ONAY':'RED'}</span> ${fmt(v.skor,0)}/100</span></div>`
    ).join('');
  } else { valEl.innerHTML = '<span class="im">henüz doğrulama yok (yeterli işlem birikince)</span>'; }

  // Portfolio MVO
  const port = s.portfolio || {};
  const portEl = document.getElementById('intel-port');
  if (port.agirliklar) {
    const entries = Object.entries(port.agirliklar).sort((a,b)=>b[1]-a[1]);
    portEl.innerHTML =
      `<div class="im">${port.yontem||''} · Sharpe ${fmt(port.sharpe||0,2)}</div>` +
      entries.map(([sym,w]) =>
        `<div style="margin-top:5px"><div class="intel-row"><span class="k">${esc(sym.replace('USDT',''))}</span><span class="v">%${fmt(w,1)}</span></div>`+
        `<div class="mini-bar"><div class="mini-fill" style="width:${Math.min(w,100)}%;background:var(--blue)"></div></div></div>`
      ).join('');
  } else { portEl.innerHTML = '<span class="im">portföy optimize edilmedi</span>'; }

  // Online learning + Kelly
  const ol = s.online_learning || {}, kel = s.kelly || {};
  const learnEl = document.getElementById('intel-learn');
  const coins = [...new Set([...Object.keys(ol), ...Object.keys(kel)])];
  if (coins.length) {
    learnEl.innerHTML = coins.map(sym => {
      const o = ol[sym]||{}, k = kel[sym]||{};
      const driftTxt = o.drift ? ` <span style="color:var(--orange)">⚠${o.drift}</span>` : '';
      const kellyTxt = k.kelly_f!=null ? ` K:${fmt(k.kelly_f,2)} WR%${fmt(k.win_rate,0)}` : '';
      return `<div class="intel-row"><span class="k">${esc(sym.replace('USDT',''))}</span>`+
             `<span class="v" style="font-size:.72rem">${o.egitim!=null?'n='+o.egitim:''}${driftTxt}${kellyTxt}</span></div>`;
    }).join('');
  } else { learnEl.innerHTML = '<span class="im">öğrenme verisi birikiyor</span>'; }

  // A/B test
  const ab = s.ab_test || {};
  const abEl = document.getElementById('intel-ab');
  if (ab.a && (ab.a.n || ab.b.n)) {
    const a = ab.a, b = ab.b;
    abEl.innerHTML =
      row('[A] '+a.isim, `n=${a.n} WR%${fmt(a.win_rate*100,0)} ${(a.ort_pnl>=0?'+':'')}${fmt(a.ort_pnl,2)}%`) +
      row('[B] '+b.isim, `n=${b.n} WR%${fmt(b.win_rate*100,0)} ${(b.ort_pnl>=0?'+':'')}${fmt(b.ort_pnl,2)}%`) +
      `<div style="margin-top:6px" class="im">${ab.anlamli?'✅ Anlamlı fark · Kazanan: <b>'+ab.kazanan+'</b>':'⏳ Fark anlamlı değil (p='+fmt(ab.p,3)+')'}</div>`;
  } else { abEl.innerHTML = '<span class="im">A/B verisi birikiyor</span>'; }

  // Smart exec + registry
  const se = s.smart_exec || {}, reg = s.model_registry || {};
  const execEl = document.getElementById('intel-exec');
  let html = '';
  if (se.market!=null) {
    html += row('Market / TWAP', `${se.market||0} / ${se.twap||0}`);
    html += row('VWAP / Iceberg', `${se.vwap||0} / ${se.iceberg||0}`);
  }
  const rk = Object.entries(reg);
  if (rk.length) {
    html += `<div class="im" style="margin-top:6px">Model versiyonları:</div>`;
    html += rk.map(([sym,r]) =>
      `<div class="intel-row"><span class="k">${esc(sym.replace('USDT',''))}</span>`+
      `<span class="v" style="font-size:.72rem">v${r.versiyon} acc${fmt(r.acc,2)} ${(r.canli_pnl>=0?'+':'')}${fmt(r.canli_pnl,2)}%</span></div>`
    ).join('');
  }
  // v26: Çoklu borsa
  const mx = s.multiex || {};
  if (mx.veto!=null) {
    html += `<div class="im" style="margin-top:6px">🌐 Çoklu borsa:</div>`;
    html += row('Fiyat veto', mx.veto||0, (mx.veto>0?'var(--orange)':'var(--muted)'));
    html += row('Arbitraj L/S', `${mx.arbitraj_long||0} / ${mx.arbitraj_short||0}`);
  }
  execEl.innerHTML = html || '<span class="im">execution verisi yok</span>';

  // v36: İşlem teşhisi (neden açılmıyor)
  const veto = s.veto || {};
  const vetoEl = document.getElementById('intel-veto');
  if (veto.toplam_deneme > 0) {
    const isimMap = {
      "slippage_gec_giris":"⏱️ Geç giriş","kill_switch":"🛑 Kill switch",
      "circuit_breaker":"⚡ Circuit","coklu_borsa":"🌐 Çoklu borsa",
      "validator_dayaniklilik":"🛡️ Dayanıklılık","korelasyon":"🔗 Korelasyon",
      "mtf_cascade":"📊 MTF blok","mtf_hizalama_yok":"📊 MTF hizalama",
      "edge_engine":"🔬 Edge","strateji_red":"🎯 Strateji","sinyal_filtresi":"🔎 Sinyal",
      "guven_dusuk":"📉 Güven eşiği","ai_skor_dusuk":"🤖 AI skor eşiği",
      "rr_yetersiz":"⚖️ R/R kapısı","yeniden_giris_beklemesi":"⏳ Yeniden giriş",
      "yeniden_giris_beklemesi_hata":"⚠️ Yeniden giriş hatası",
      "max_acik_pozisyon":"📦 Max açık pozisyon",
      "acik_pozisyon_okunamadi":"⚠️ Pozisyon okunamadı",
      "bakiye_yetersiz":"💰 Bakiye yetersiz","miktar_sifir":"🔢 Miktar sıfır"
    };
    let h = row('✅ Açılan', veto.acilan_islem, 'var(--green)') +
            row('⛔ Reddedilen', veto.toplam_red, 'var(--orange)') +
            row('Açılma oranı', '%'+veto.acilma_oran_pct);
    const dag = veto.red_dagilim || {};
    const top3 = Object.entries(dag).slice(0,3);
    if (top3.length) {
      h += '<div class="im" style="margin-top:5px">En çok reddeden:</div>';
      top3.forEach(([k,v])=>{ h += row(isimMap[k]||k, v); });
    }
    vetoEl.innerHTML = h;
  } else { vetoEl.innerHTML = '<span class="im">henüz işlem denemesi yok</span>'; }

  // v36: Giriş gecikmesi
  const g = s.gecikme || {};
  const gEl = document.getElementById('intel-gecikme');
  if (g.n > 0) {
    let h = row('Örneklem', g.n+' giriş') +
            row('Ort. gecikme', g.ort_gecikme_sn+'s') +
            row('Maks', g.max_gecikme_sn+'s') +
            row('İptal oranı', '%'+g.iptal_oran_pct, g.iptal_oran_pct>30?'var(--orange)':'');
    const a = g.analiz || {};
    if (a.eslenen_islem) {
      const fark = a.hizli_giris_ort_pnl - a.yavas_giris_ort_pnl;
      h += '<div style="margin-top:5px" class="im">Hızlı vs Yavaş PnL:</div>';
      h += row('Hızlı giriş', a.hizli_giris_ort_pnl.toFixed(3)+'%', 'var(--green)');
      h += row('Yavaş giriş', a.yavas_giris_ort_pnl.toFixed(3)+'%',
               a.yavas_giris_ort_pnl<0?'var(--red)':'');
      if (fark > 0.05) h += '<div style="font-size:.7rem;color:var(--orange)">⚠️ Gecikme zarar veriyor</div>';
    }
    gEl.innerHTML = h;
  } else { gEl.innerHTML = '<span class="im">gecikme verisi birikiyor</span>'; }
}

guncelle();
// ── v58 (K-74): 2 sn UFKA GÖRE ANLAMSIZDI ve SAHTE ALARM ÜRETİYORDU ──
// ÖLÇÜM (2026-09-10, 7 dk, panelin kendi temposunda 86 istek):
//     medyan 0.01s · p95 10.28s · max 13.50s
//     2 sn'yi AŞAN: 86 istekte 37  (%43)
// Yani isteklerin neredeyse yarısı yenileme aralığından UZUN sürüyordu;
// her biri tarayıcıda "BAĞLANTI YOK" olarak görünüyordu. Kuyruk gecikmesi
// analiz turunun CPU yükünden geliyor (model eğitimi) — K-73 onu bar
// başına bire indirdi, bu da panel tarafını dayanıklı yapıyor.
// 4h ufkunda 2 sn'de bir yenilemenin bilgi değeri de yoktu.
setInterval(guncelle, 5000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):

    def _yetki_kontrol(self) -> bool:
        """v50 GÜVENLİK: Basic Auth. PANEL_USER/PANEL_PASS .env'de
        tanımlıysa kimlik doğrulaması zorunlu olur. Tanımlı değilse
        (varsayılan) kısıtlama uygulanmaz — geriye dönük uyumluluk.

        Panel bakiye, pozisyon ve strateji verisi gösterdiği için
        internete açık bırakılması bilgi ifşası riskidir."""
        if not PANEL_USER:
            return True   # ayar yok → kısıtlama yok (eski davranış)
        baslik = self.headers.get("Authorization", "")
        if not baslik.startswith("Basic "):
            return False
        try:
            cozulen = base64.b64decode(baslik[6:]).decode("utf-8")
            kullanici, _, sifre = cozulen.partition(":")
        except Exception:
            return False
        # Zamanlama saldırısına karşı sabit süreli karşılaştırma
        return (hmac.compare_digest(kullanici, PANEL_USER) and
                hmac.compare_digest(sifre, PANEL_PASS))

    def _yetkisiz_yanit(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="ASTRA Panel"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _guvenlik_basliklari(self):
        """v56: Panel finansal veri gösteriyor — temel tarayıcı korumaları.
        Eskiden hiçbiri gönderilmiyordu."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")          # clickjacking
        self.send_header("Referrer-Policy", "no-referrer")
        # Panel tamamen self-contained (inline CSS/JS, dış kaynak yok)
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; connect-src 'self'")

    def do_GET(self):
        if not self._yetki_kontrol():
            self._yetkisiz_yanit()
            return

        # v56: Yol eşleştirmesi sıkılaştırıldı. Eskiden `/api/state` DIŞINDAKİ
        # HER yol (örn. /olmayan, /admin, /.env) HTTP 200 + panel HTML'i
        # döndürüyordu. Artık yalnızca bilinen yollar yanıtlanıyor.
        yol = self.path.split("?", 1)[0].rstrip("/") or "/"

        if yol == "/api/state":
            data = _get_state_json()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            # v50 GÜVENLİK: '*' yerine kısıtlı CORS. Eskiden herhangi bir
            # web sitesi tarayıcı üzerinden panel verinizi okuyabilirdi.
            if PANEL_CORS_ORIGIN:
                self.send_header("Access-Control-Allow-Origin", PANEL_CORS_ORIGIN)
            self.send_header("Cache-Control", "no-cache")
            self._guvenlik_basliklari()
            self.end_headers()
            self.wfile.write(data)

        elif yol == "/saglik":
            # v56: Basit liveness endpoint'i (Docker healthcheck için)
            data = b'{"durum":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._guvenlik_basliklari()
            self.end_headers()
            self.wfile.write(data)

        elif yol == "/":
            html = HTML.replace("__ASTRA_VERSION__", ASTRA_VERSION).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self._guvenlik_basliklari()
            self.end_headers()
            self.wfile.write(html)

        else:
            govde = b"404"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(govde)))
            self._guvenlik_basliklari()
            self.end_headers()
            self.wfile.write(govde)

    def do_POST(self):
        """v56: Panel salt-okunur. POST açıkça reddediliyor
        (eskiden BaseHTTPRequestHandler varsayılanı 501 dönüyordu)."""
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def dashboard_baslat():
    _db_gecmisini_yukle()  # DB'deki geçmişi yükle

    # v55 GÜVENLİK: Bağlanma adresi ve auth durumu artık AÇIKÇA bildiriliyor.
    # Eskiden koşulsuz 0.0.0.0'a bağlanıyor ve PANEL_USER boşken auth sessizce
    # atlanıyordu — kullanıcı panelinin korumasız olduğunu hiç öğrenmiyordu.
    host = "127.0.0.1" if PANEL_SADECE_LOCALHOST else "0.0.0.0"

    if not PANEL_USER:
        if host == "0.0.0.0":
            log.critical(
                "[DASHBOARD] 🚨 PANEL KİMLİK DOĞRULAMASIZ ve TÜM ARAYÜZLERDE "
                f"(0.0.0.0:{DASHBOARD_PORT})! Bakiye, açık pozisyon ve PnL "
                "verisi porta erişebilen HERKESE açık. .env'de PANEL_USER ve "
                "PANEL_PASS tanımlayın veya PANEL_SADECE_LOCALHOST=true yapın."
            )
        else:
            log.warning(
                f"[DASHBOARD] ⚠️ Panel kimlik doğrulaması KAPALI "
                f"(yalnızca localhost:{DASHBOARD_PORT} — dışarıya kapalı). "
                f"Uzaktan erişim için PANEL_USER/PANEL_PASS tanımlayın."
            )
    else:
        log.info(f"[DASHBOARD] 🔒 Basic Auth aktif (kullanıcı: {PANEL_USER})")

    def _run():
        try:
            # ── v58 (K-53): TEK İŞ PARÇACIKLI SUNUCU → THREADING ────────
            # `HTTPServer` aynı anda TEK bağlantı işler. Ölçüm (2026-09-06,
            # 25 çift istek): kilit ALMAYAN `/saglik` uç noktası — sabit
            # 14 bayt döndürüyor — periyodik olarak **56–58 saniye** bloke
            # oluyordu; kilidi alan `/api/state` ise hep milisaniyeydi.
            #
            # Bu, sorunun kilit çekişmesi ya da handler gövdesi OLMADIĞINI
            # kanıtladı: takılma bağlantı/kuyruk seviyesinde. Tek iş
            # parçacıklı sunucuda bir bağlantı takılırsa ARDINDAKİ HER
            # İSTEK bekler (head-of-line blocking) — tarayıcı paneli
            # saniyede bir yokladığı için bu pratikte panelin donması
            # demek.
            #
            # ⚠️ DÜRÜST NOT: bu değişiklik takılmanın KÖK NEDENİNİ
            # çözmüyor (hangi işlemin ~56s tuttuğu henüz belirlenmedi).
            # Yaptığı şey, tek bir takılmanın DİĞER istekleri de
            # kilitlemesini engellemek. Kök neden ayrıca aranmalı.
            #
            # daemon_threads: sunucu thread'i ölürse yavru thread'ler
            # süreci canlı tutmasın (§5.2.1 — daemon olmayan thread
            # süreci beklemede bırakır).
            server = ThreadingHTTPServer((host, DASHBOARD_PORT), DashboardHandler)
            server.daemon_threads = True
            log.info(f"[DASHBOARD] http://{host}:{DASHBOARD_PORT} — {ASTRA_VERSION} aktif")
            server.serve_forever()
        except OSError as e:
            log.error(f"[DASHBOARD] Port {DASHBOARD_PORT} açılamadı: {e}")
        except Exception as e:
            log.error(f"[DASHBOARD] Hata: {e}")

    threading.Thread(target=_run, daemon=True, name="AstraDashboard").start()
