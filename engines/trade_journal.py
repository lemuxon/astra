# =========================================================
# ASTRA v30.0 — TRADE JOURNAL (Gerçek Analytics)
# Her trade için tam veri kaydı + analiz
# =========================================================
import logging, os, time, sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path
import sys; sys.path.append("..")

log = logging.getLogger("ASTRA.JOURNAL")

@dataclass
class TradeKayit:
    # Kimlik
    trade_id:     str
    sembol:       str
    yon:          str          # LONG / SHORT
    mod:          str          # LIVE / PAPER

    # Giriş
    giris_ts:     float
    giris_fiyat:  float
    miktar:       float
    maliyet_usdt: float

    # Context
    rejim:        str
    ai_score:     int
    confidence:   int
    volatility:   float        # ATR %
    strateji:     str
    mtf_skor:     int
    funding_rate: float
    edge_score:   float

    # Execution
    sl:           float
    tp1:          float
    tp2:          float
    kaldirac:     int
    latency_ms:   float = 0.0  # signal→order ms
    slippage_pct: float = 0.0

    # Çıkış (kapatılınca dolar)
    cikis_ts:     Optional[float] = None
    cikis_fiyat:  Optional[float] = None
    cikis_sebep:  Optional[str]   = None   # SL/TP/SIGNAL/MANUEL
    pnl_usdt:     float = 0.0
    pnl_pct:      float = 0.0
    sure_dakika:  float = 0.0

    # Analiz
    max_mae:      float = 0.0   # Maximum Adverse Excursion
    max_mfe:      float = 0.0   # Maximum Favorable Excursion


class TradeJournal:
    def __init__(self, db_path: str = None):
        # v57: Varsayilan artik config'ten geliyor. Eskiden "data/journal.db"
        # SABIT KODLUYDU; .env'de JOURNAL_DB_PATH degistirilse bile argumansiz
        # cagiran 5 yer (bootstrap/app_init.py, paper_trading x2,
        # execution_engine x2) sessizce ESKI yola yaziyordu.
        if db_path is None:
            from config import JOURNAL_DB_PATH
            db_path = JOURNAL_DB_PATH
        self._db = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        log.info(f"[JOURNAL] Başlatıldı: {db_path}")

    def _baglanti(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        # v29: WAL mode → eşzamanlı okuma/yazma "database is locked" hatasını azaltır
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        return conn

    def _init_db(self):
        conn = self._baglanti()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS journal (
                trade_id TEXT PRIMARY KEY,
                sembol TEXT, yon TEXT, mod TEXT,
                giris_ts REAL, giris_fiyat REAL, miktar REAL, maliyet_usdt REAL,
                rejim TEXT, ai_score INTEGER, confidence INTEGER,
                volatility REAL, strateji TEXT, mtf_skor INTEGER,
                funding_rate REAL, edge_score REAL,
                sl REAL, tp1 REAL, tp2 REAL, kaldirac INTEGER,
                latency_ms REAL, slippage_pct REAL,
                cikis_ts REAL, cikis_fiyat REAL, cikis_sebep TEXT,
                pnl_usdt REAL, pnl_pct REAL, sure_dakika REAL,
                max_mae REAL, max_mfe REAL
            )
        """)
        conn.commit(); conn.close()

    def trade_ac(self, kayit: TradeKayit):
        conn = self._baglanti()
        d = asdict(kayit)
        cols = ", ".join(d.keys())
        plc  = ", ".join(["?"] * len(d))
        try:
            conn.execute(f"INSERT OR REPLACE INTO journal ({cols}) VALUES ({plc})",
                         list(d.values()))
            conn.commit()
        except Exception as e:
            log.error(f"[JOURNAL] Kayıt hatası: {e}")
        finally:
            conn.close()

    def trade_kapat(self, trade_id: str, cikis_fiyat: float,
                     cikis_sebep: str, pnl_usdt: float, pnl_pct: float,
                     max_mae: float = 0.0, max_mfe: float = 0.0):
        now = time.time()
        conn = self._baglanti()
        try:
            row = conn.execute("SELECT giris_ts, giris_fiyat FROM journal WHERE trade_id=?",
                               (trade_id,)).fetchone()
            sure = (now - row["giris_ts"]) / 60.0 if row else 0.0
            conn.execute("""
                UPDATE journal SET
                    cikis_ts=?, cikis_fiyat=?, cikis_sebep=?,
                    pnl_usdt=?, pnl_pct=?, sure_dakika=?,
                    max_mae=?, max_mfe=?
                WHERE trade_id=?
            """, (now, cikis_fiyat, cikis_sebep, pnl_usdt, pnl_pct,
                  sure, max_mae, max_mfe, trade_id))
            conn.commit()
        except Exception as e:
            log.error(f"[JOURNAL] Kapat hatası: {e}")
        finally:
            conn.close()

    def getiri_serisi(self, sembol: str = None, limit: int = 200) -> list:
        """v24: Kapanan işlemlerin % getiri serisi (validator için).
        sembol=None ise tüm coinler. En yeni `limit` işlem, kronolojik sırada."""
        conn = self._baglanti()
        try:
            if sembol:
                rows = conn.execute("""
                    SELECT pnl_pct FROM journal
                    WHERE cikis_ts IS NOT NULL AND sembol=?
                    ORDER BY cikis_ts DESC LIMIT ?
                """, (sembol, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT pnl_pct FROM journal
                    WHERE cikis_ts IS NOT NULL
                    ORDER BY cikis_ts DESC LIMIT ?
                """, (limit,)).fetchall()
            # DESC çektik → kronolojik için ters çevir
            return [float(r["pnl_pct"]) for r in reversed(rows)
                    if r["pnl_pct"] is not None]
        except Exception as e:
            log.error(f"[JOURNAL] Getiri serisi hatası: {e}")
            return []
        finally:
            conn.close()

    def analiz(self) -> dict:
        """Kapanan işlemlerin tam analizi."""
        conn = self._baglanti()
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM journal WHERE cikis_ts IS NOT NULL"
        ).fetchall()]
        conn.close()

        if not rows:
            return {"mesaj": "Henüz kapanan işlem yok"}

        toplam     = len(rows)
        kazananlar = [r for r in rows if r["pnl_usdt"] > 0]
        kaybedenler= [r for r in rows if r["pnl_usdt"] <= 0]
        win_rate   = len(kazananlar) / toplam * 100 if toplam else 0
        toplam_pnl = sum(r["pnl_usdt"] for r in rows)
        ort_kazanc = sum(r["pnl_usdt"] for r in kazananlar) / len(kazananlar) if kazananlar else 0
        ort_kayip  = sum(r["pnl_usdt"] for r in kaybedenler) / len(kaybedenler) if kaybedenler else 0
        profit_factor = abs(sum(r["pnl_usdt"] for r in kazananlar) /
                           sum(r["pnl_usdt"] for r in kaybedenler)) if kaybedenler else 999

        # Rejim analizi
        rejim_pnl = {}
        for r in rows:
            rejim = r.get("rejim", "?")
            rejim_pnl.setdefault(rejim, []).append(r["pnl_usdt"])
        rejim_analiz = {
            r: {"ort_pnl": round(sum(v)/len(v), 4), "sayi": len(v)}
            for r, v in rejim_pnl.items()
        }

        # Strateji analizi
        str_pnl = {}
        for r in rows:
            s = r.get("strateji", "?")
            str_pnl.setdefault(s, []).append(r["pnl_usdt"])
        str_analiz = {
            s: {"ort_pnl": round(sum(v)/len(v), 4), "sayi": len(v)}
            for s, v in str_pnl.items()
        }

        # AI score gerçekten işe yarıyor mu?
        yuksek_ai = [r for r in rows if r.get("ai_score", 0) >= 6]
        dusuk_ai  = [r for r in rows if abs(r.get("ai_score", 0)) < 4]
        ai_analiz = {
            "yuksek_ai_ort_pnl": round(sum(r["pnl_usdt"] for r in yuksek_ai)/len(yuksek_ai), 4) if yuksek_ai else 0,
            "dusuk_ai_ort_pnl":  round(sum(r["pnl_usdt"] for r in dusuk_ai)/len(dusuk_ai), 4) if dusuk_ai else 0,
        }

        return {
            "toplam_islem": toplam,
            "win_rate_pct": round(win_rate, 1),
            "toplam_pnl":   round(toplam_pnl, 4),
            "ort_kazanc":   round(ort_kazanc, 4),
            "ort_kayip":    round(ort_kayip, 4),
            "profit_factor":round(profit_factor, 2),
            "ort_sure_dk":  round(sum(r["sure_dakika"] for r in rows)/toplam, 1),
            "ort_slippage": round(sum(r["slippage_pct"] for r in rows)/toplam, 4),
            "rejim_analiz": rejim_analiz,
            "strateji_analiz": str_analiz,
            "ai_analiz":    ai_analiz,
        }

    def telegram_raporu(self) -> str:
        a = self.analiz()
        if "mesaj" in a:
            return f"📓 <b>JOURNAL</b>\n{a['mesaj']}"
        ra = a.get("rejim_analiz", {})
        rejim_str = "\n".join(
            f"  {r}: {v['ort_pnl']:+.4f}$ ({v['sayi']} işlem)"
            for r, v in sorted(ra.items(), key=lambda x: x[1]["ort_pnl"], reverse=True)
        )
        ai = a["ai_analiz"]
        return (
            f"📓 <b>TRADE JOURNAL v14</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 Toplam: {a['toplam_islem']} | WR: %{a['win_rate_pct']}\n"
            f"💰 PnL: {a['toplam_pnl']:+.4f}$ | PF: {a['profit_factor']:.2f}\n"
            f"⏱️ Ort süre: {a['ort_sure_dk']:.1f}dk\n"
            f"↕️ Ort slippage: %{a['ort_slippage']:.4f}\n"
            f"🏆 Kazanç/Kayıp: {a['ort_kazanc']:+.4f}$ / {a['ort_kayip']:+.4f}$\n"
            f"🧠 AI Analiz:\n"
            f"  Yüksek AI(≥6): {ai['yuksek_ai_ort_pnl']:+.4f}$\n"
            f"  Düşük AI(<4):  {ai['dusuk_ai_ort_pnl']:+.4f}$\n"
            f"📈 Rejim Analizi:\n{rejim_str}"
        )


_instance = None
def get_journal(db_path=None) -> TradeJournal:
    """Journal singleton'i dondur.

    v57: db_path varsayilani config'ten cozulur (bkz. TradeJournal.__init__).
    Ayrica singleton ILK cagriya gore sabitlendigi icin, sonraki bir cagri
    FARKLI bir yol isterse bu sessizce yok sayiliyordu — journal'in iki
    dosyaya bolunmesi demek. Artik uyari basiliyor
    (DEVAM_NOTLARI.md §5.2 "sessiz basarisizlik" kurali).
    """
    global _instance
    if db_path is None:
        from config import JOURNAL_DB_PATH
        db_path = JOURNAL_DB_PATH
    if _instance is None:
        _instance = TradeJournal(db_path)
    elif os.path.abspath(_instance._db) != os.path.abspath(db_path):
        log.error(
            f"[JOURNAL] Yol catismasi: singleton '{_instance._db}' ile acilmisti, "
            f"simdi '{db_path}' istendi. ESKI yol kullanilmaya devam ediyor — "
            f"cagri sirasina bagli sessiz bolunme riski."
        )
    return _instance
