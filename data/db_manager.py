# =========================================================
# ASTRA v30.0 — DATABASE MANAGER
# SQLite (geliştirme) / PostgreSQL / TimescaleDB backend
# Backend-agnostic API — üst katman fark etmez
# =========================================================
import logging, json, os, time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import sys; sys.path.append("..")
from config import (DB_BACKEND, DB_PATH, DB_HOST, DB_PORT,
                    DB_NAME, DB_USER, DB_PASSWORD, DB_POOL_MIN, DB_POOL_MAX)

log = logging.getLogger("ASTRA.DB")

# ── Driver yükle ──────────────────────────────────────────
_PG_AVAILABLE = False
try:
    import psycopg2
    import psycopg2.pool
    import psycopg2.extras
    _PG_AVAILABLE = True
except ImportError:
    pass

# ── Bağlantı Havuzu ───────────────────────────────────────
class DBConnection:
    """Backend-agnostic bağlantı yöneticisi."""

    def __init__(self):
        self._backend  = DB_BACKEND.lower()
        self._pool     = None
        self._sqlite_conn = None
        self._lock     = __import__("threading").Lock()
        self._init()

    def _init(self):
        if self._backend in ("postgres","timescale"):
            if not _PG_AVAILABLE:
                log.warning("[DB] psycopg2 kurulu değil → SQLite fallback")
                self._backend = "sqlite"
            else:
                try:
                    self._pool = psycopg2.pool.ThreadedConnectionPool(
                        minconn=DB_POOL_MIN, maxconn=DB_POOL_MAX,
                        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                        user=DB_USER, password=DB_PASSWORD,
                        connect_timeout=5
                    )
                    log.info(f"[DB] {self._backend.upper()} bağlantı havuzu: "
                             f"{DB_HOST}:{DB_PORT}/{DB_NAME} (pool {DB_POOL_MIN}-{DB_POOL_MAX})")
                    self._init_pg_schema()
                    return
                except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
                    log.error(f"[DB] PostgreSQL bağlanamadı: {e} → SQLite fallback")
                    self._backend = "sqlite"

        # SQLite
        import sqlite3
        os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
        self._sqlite_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        self._sqlite_conn.row_factory = sqlite3.Row
        try:
            self._sqlite_conn.execute("PRAGMA journal_mode=WAL")
            self._sqlite_conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        log.info(f"[DB] SQLite: {DB_PATH}")
        self._init_sqlite_schema()

    @contextmanager
    def cursor(self):
        """Context manager: otomatik commit/rollback."""
        if self._backend == "sqlite":
            with self._lock:
                cur = self._sqlite_conn.cursor()
                try:
                    yield cur
                    self._sqlite_conn.commit()
                except Exception as e:
                    self._sqlite_conn.rollback()
                    log.error(f"[DB] SQLite hata: {e}")
                    raise
                finally:
                    cur.close()
        else:
            conn = None
            try:
                conn = self._pool.getconn()
                conn.autocommit = False
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                try:
                    yield cur
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    log.error(f"[DB] PG hata: {e}")
                    raise
                finally:
                    cur.close()
            finally:
                if conn: self._pool.putconn(conn)

    def execute(self, sql: str, params: tuple = None) -> bool:
        try:
            with self.cursor() as cur:
                cur.execute(self._adapt_sql(sql), params or ())
            return True
        except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
            log.error(f"[DB] execute hatası: {e}")
            return False

    def fetchall(self, sql: str, params: tuple = None) -> List[Dict]:
        try:
            with self.cursor() as cur:
                cur.execute(self._adapt_sql(sql), params or ())
                rows = cur.fetchall()
                if self._backend == "sqlite":
                    return [dict(r) for r in rows]
                return [dict(r) for r in rows]
        except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
            log.error(f"[DB] fetchall hatası: {e}")
            return []

    def fetchone(self, sql: str, params: tuple = None) -> Optional[Dict]:
        rows = self.fetchall(sql, params)
        return rows[0] if rows else None

    def _adapt_sql(self, sql: str) -> str:
        """SQLite %s → ? dönüşümü."""
        if self._backend == "sqlite":
            return sql.replace("%s", "?")
        return sql

    # ── Schema Oluşturma ──────────────────────────────────

    def _init_sqlite_schema(self):
        schema = """
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, sembol TEXT, fiyat REAL, ai_score INTEGER,
            karar TEXT, rsi REAL, macd REAL, confidence INTEGER,
            sentiment INTEGER, model_adi TEXT
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ac TEXT NOT NULL,
            ts_kapat TEXT,
            sembol TEXT NOT NULL,
            yon TEXT NOT NULL,
            giris_fiyat REAL NOT NULL,
            cikis_fiyat REAL,
            miktar REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            pnl REAL,
            pnl_yuzde REAL,
            durum TEXT DEFAULT 'ACIK',
            mod TEXT DEFAULT 'PAPER',
            signal_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS risk_analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, sembol TEXT,
            var_hist REAL, var_param REAL, var_mc REAL, var_agirlıklı REAL,
            expected_shortfall REAL, portfolio_corr TEXT,
            volatility_regime TEXT, drawdown_pct REAL
        );
        CREATE TABLE IF NOT EXISTS portfolio_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, bakiye REAL, acik_poz_sayisi INTEGER,
            toplam_pnl REAL, gunluk_pnl REAL, drawdown_pct REAL,
            marjin_kullanim REAL, snapshot TEXT
        );
        CREATE TABLE IF NOT EXISTS sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, sembol TEXT, yon TEXT, senaryo TEXT,
            beklenen_fiyat REAL, sim_fiyat REAL, slippage_bps REAL,
            latency_ms REAL, fill_pct REAL, kabul_edildi INTEGER
        );
        CREATE TABLE IF NOT EXISTS backtests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, sembol TEXT, baslangic TEXT, bitis TEXT,
            toplam_islem INTEGER, kazanan INTEGER, kaybeden INTEGER,
            win_rate REAL, toplam_getiri REAL, max_drawdown REAL,
            sharpe REAL, params TEXT
        );
        CREATE TABLE IF NOT EXISTS model_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, sembol TEXT, model_adi TEXT, accuracy REAL
        );
        """
        try:
            with self._lock:
                self._sqlite_conn.executescript(schema)
                self._sqlite_conn.commit()
            log.info("[DB] SQLite schema hazır")
        except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
            log.error(f"[DB] SQLite schema hatası: {e}")

    def _init_pg_schema(self):
        """PostgreSQL / TimescaleDB schema."""
        tables = """
        CREATE TABLE IF NOT EXISTS signals (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            sembol TEXT, fiyat DOUBLE PRECISION, ai_score INTEGER,
            karar TEXT, rsi DOUBLE PRECISION, macd DOUBLE PRECISION,
            confidence INTEGER, sentiment INTEGER, model_adi TEXT
        );
        CREATE TABLE IF NOT EXISTS trades (
            id BIGSERIAL PRIMARY KEY,
            ts_ac TIMESTAMPTZ DEFAULT NOW(), ts_kapat TIMESTAMPTZ,
            sembol TEXT, yon TEXT, giris DOUBLE PRECISION,
            cikis DOUBLE PRECISION, miktar DOUBLE PRECISION,
            kaldirac INTEGER, pnl_usdt DOUBLE PRECISION,
            pnl_pct DOUBLE PRECISION, sebep TEXT, strateji TEXT
        );
        CREATE TABLE IF NOT EXISTS risk_analytics (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(), sembol TEXT,
            var_hist DOUBLE PRECISION, var_param DOUBLE PRECISION,
            var_mc DOUBLE PRECISION, var_agirlıklı DOUBLE PRECISION,
            expected_shortfall DOUBLE PRECISION,
            portfolio_corr JSONB, volatility_regime TEXT,
            drawdown_pct DOUBLE PRECISION
        );
        CREATE TABLE IF NOT EXISTS portfolio_state (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            bakiye DOUBLE PRECISION, acik_poz_sayisi INTEGER,
            toplam_pnl DOUBLE PRECISION, gunluk_pnl DOUBLE PRECISION,
            drawdown_pct DOUBLE PRECISION, marjin_kullanim DOUBLE PRECISION,
            snapshot JSONB
        );
        CREATE TABLE IF NOT EXISTS sim_trades (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(), sembol TEXT, yon TEXT,
            senaryo TEXT, beklenen_fiyat DOUBLE PRECISION,
            sim_fiyat DOUBLE PRECISION, slippage_bps DOUBLE PRECISION,
            latency_ms DOUBLE PRECISION, fill_pct DOUBLE PRECISION,
            kabul_edildi BOOLEAN
        );
        CREATE TABLE IF NOT EXISTS backtests (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(), sembol TEXT,
            baslangic TEXT, bitis TEXT, toplam_islem INTEGER,
            kazanan INTEGER, kaybeden INTEGER, win_rate DOUBLE PRECISION,
            toplam_getiri DOUBLE PRECISION, max_drawdown DOUBLE PRECISION,
            sharpe DOUBLE PRECISION, params JSONB
        );
        CREATE TABLE IF NOT EXISTS model_performance (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ DEFAULT NOW(),
            sembol TEXT, model_adi TEXT, accuracy DOUBLE PRECISION
        );
        """
        try:
            with self.cursor() as cur:
                cur.execute(tables)
            # TimescaleDB hypertables
            if self._backend == "timescale":
                self._init_hypertables()
            log.info(f"[DB] {self._backend.upper()} schema hazır")
        except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
            log.error(f"[DB] PG schema hatası: {e}")

    def _init_hypertables(self):
        """TimescaleDB zaman serisi optimizasyonu."""
        hyper = [
            "SELECT create_hypertable('signals',       'ts', if_not_exists => TRUE);",
            "SELECT create_hypertable('risk_analytics','ts', if_not_exists => TRUE);",
            "SELECT create_hypertable('portfolio_state','ts',if_not_exists => TRUE);",
            "SELECT create_hypertable('sim_trades',    'ts', if_not_exists => TRUE);",
        ]
        for sql in hyper:
            try:
                with self.cursor() as cur: cur.execute(sql)
            except Exception as e:
                log.debug(f"[DB] Hypertable atlandı: {e}")

    @property
    def backend(self) -> str:
        return self._backend

# ── CRUD Fonksiyonları ────────────────────────────────────

def sinyal_kaydet(sembol, fiyat, ai_score, karar, rsi=0, macd=0,
                   confidence=0, sentiment=0, model_adi="") -> Optional[int]:
    try:
        db = get_db()
        sql = """INSERT INTO signals
                 (ts,sembol,fiyat,ai_score,karar,rsi,macd,confidence,sentiment,model_adi)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        with db.cursor() as cur:
            cur.execute(db._adapt_sql(sql),
                        (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), sembol, fiyat, ai_score,
                         karar, rsi, macd, confidence, sentiment, model_adi))
            if db.backend == "sqlite":
                return cur.lastrowid
            cur.execute("SELECT lastval()")
            return cur.fetchone()[0]
    except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
        log.error(f"[DB] sinyal_kaydet: {e}"); return None

def trade_ac(sembol, yon, giris, miktar, kaldirac=5, strateji="") -> Optional[int]:
    """v55 DÜZELTME: Sütun adları backend'e göre seçilir.

    Eskiden HER İKİ backend için de Postgres sütun adları (giris, kaldirac,
    strateji) kullanılıyordu. SQLite şeması ise giris_fiyat/miktar/mod
    sütunlarına sahip → varsayılan (sqlite) backend'de bu fonksiyon
    `sqlite3.OperationalError: table trades has no column named giris`
    ile patlıyordu. Modülün "backend-agnostic API" vaadi tutulmuyordu.
    """
    try:
        db = get_db()
        ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        if db.backend == "sqlite":
            sql = """INSERT INTO trades (ts_ac,sembol,yon,giris_fiyat,miktar,mod)
                     VALUES (%s,%s,%s,%s,%s,%s)"""
            params = (ts, sembol, yon, giris, miktar, strateji or "LIVE")
        else:
            sql = """INSERT INTO trades (ts_ac,sembol,yon,giris,miktar,kaldirac,strateji)
                     VALUES (%s,%s,%s,%s,%s,%s,%s)"""
            params = (ts, sembol, yon, giris, miktar, kaldirac, strateji)
        with db.cursor() as cur:
            cur.execute(db._adapt_sql(sql), params)
            if db.backend == "sqlite": return cur.lastrowid
            cur.execute("SELECT lastval()"); return cur.fetchone()[0]
    except Exception as e:
        # v55: sqlite3.Error / psycopg2.Error OSError veya ValueError alt sınıfı
        # DEĞİLDİR — eski dar except bu hataları hiç yakalamıyordu.
        log.error(f"[DB] trade_ac: {type(e).__name__}: {e}"); return None

def trade_kapat(trade_id, cikis, pnl_usdt, pnl_pct, sebep=""):
    """v55: bkz. trade_ac — sütun adları backend'e göre seçilir."""
    try:
        db = get_db()
        ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        if db.backend == "sqlite":
            sql = """UPDATE trades SET ts_kapat=%s,cikis_fiyat=%s,pnl=%s,
                                        pnl_yuzde=%s,durum=%s
                     WHERE id=%s"""
            params = (ts, cikis, pnl_usdt, pnl_pct, sebep or "KAPALI", trade_id)
        else:
            sql = """UPDATE trades SET ts_kapat=%s,cikis=%s,pnl_usdt=%s,pnl_pct=%s,sebep=%s
                     WHERE id=%s"""
            params = (ts, cikis, pnl_usdt, pnl_pct, sebep, trade_id)
        return db.execute(db._adapt_sql(sql), params)
    except Exception as e:
        log.error(f"[DB] trade_kapat: {type(e).__name__}: {e}"); return False

def risk_analytics_kaydet(sembol, var_hist, var_param, var_mc,
                            var_agirlikli, expected_shortfall,
                            portfolio_corr: dict, volatility_regime, drawdown_pct):
    try:
        db = get_db()
        corr_json = json.dumps(portfolio_corr, default=str)
        sql = """INSERT INTO risk_analytics
                 (ts,sembol,var_hist,var_param,var_mc,var_agirlıklı,
                  expected_shortfall,portfolio_corr,volatility_regime,drawdown_pct)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        return db.execute(db._adapt_sql(sql),
                          (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), sembol,
                           var_hist, var_param, var_mc, var_agirlikli,
                           expected_shortfall, corr_json,
                           volatility_regime, drawdown_pct))
    except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
        log.error(f"[DB] risk_analytics_kaydet: {e}"); return False

def portfolio_state_kaydet(bakiye, acik_poz, toplam_pnl, gunluk_pnl,
                            drawdown_pct, marjin_kullanim, snapshot: dict):
    try:
        db = get_db()
        sql = """INSERT INTO portfolio_state
                 (ts,bakiye,acik_poz_sayisi,toplam_pnl,gunluk_pnl,
                  drawdown_pct,marjin_kullanim,snapshot)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"""
        return db.execute(db._adapt_sql(sql),
                          (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), bakiye, acik_poz,
                           toplam_pnl, gunluk_pnl, drawdown_pct,
                           marjin_kullanim, json.dumps(snapshot, default=str)))
    except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
        log.error(f"[DB] portfolio_state_kaydet: {e}"); return False

def sim_trade_kaydet(sembol, yon, senaryo, beklenen_fiyat, sim_fiyat,
                      slippage_bps, latency_ms, fill_pct, kabul_edildi):
    try:
        db = get_db()
        sql = """INSERT INTO sim_trades
                 (ts,sembol,yon,senaryo,beklenen_fiyat,sim_fiyat,
                  slippage_bps,latency_ms,fill_pct,kabul_edildi)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        return db.execute(db._adapt_sql(sql),
                          (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), sembol, yon, senaryo,
                           beklenen_fiyat, sim_fiyat, slippage_bps,
                           latency_ms, fill_pct, int(kabul_edildi)))
    except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
        log.error(f"[DB] sim_trade_kaydet: {e}"); return False

def backtest_kaydet(sembol, baslangic, bitis, toplam_islem, kazanan,
                     kaybeden, win_rate, toplam_getiri, max_drawdown, sharpe, params):
    try:
        db = get_db()
        sql = """INSERT INTO backtests
                 (ts,sembol,baslangic,bitis,toplam_islem,kazanan,kaybeden,
                  win_rate,toplam_getiri,max_drawdown,sharpe,params)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        return db.execute(db._adapt_sql(sql),
                          (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), sembol, baslangic,
                           bitis, toplam_islem, kazanan, kaybeden, win_rate,
                           toplam_getiri, max_drawdown, sharpe,
                           json.dumps(params or {}, default=str)))
    except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
        log.error(f"[DB] backtest_kaydet: {e}"); return False

def performans_kaydet(sembol, model_adi, accuracy):
    try:
        db = get_db()
        sql = "INSERT INTO model_performance (ts,sembol,model_adi,accuracy) VALUES (%s,%s,%s,%s)"
        return db.execute(db._adapt_sql(sql),
                          (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), sembol, model_adi, accuracy))
    except Exception as e:   # v55: sqlite3.Error/psycopg2.Error OSError|ValueError DEĞİL
        log.error(f"[DB] performans_kaydet: {e}"); return False

def toplam_pnl() -> float:
    try:
        row = get_db().fetchone("SELECT COALESCE(SUM(pnl_usdt),0) AS t FROM trades")
        return float(row["t"]) if row else 0.0
    except (OSError, ValueError, KeyError, TypeError): return 0.0

def win_rate_hesapla() -> float:
    try:
        db = get_db()
        row = db.fetchone("""SELECT
            COUNT(*) FILTER (WHERE pnl_usdt > 0) AS k,
            COUNT(*) AS t FROM trades WHERE pnl_usdt IS NOT NULL""")
        if not row or not row.get("t"): return 0.0
        return round(float(row["k"] or 0) / float(row["t"]) * 100, 1)
    except (OSError, ValueError, KeyError, TypeError): return 0.0

def db_durum() -> dict:
    db = get_db()
    return {"backend": db.backend, "host": DB_HOST if db.backend != "sqlite" else DB_PATH}

def tablolari_olustur():
    """Geriye dönük uyumluluk için — DBConnection init'te otomatik oluşturuluyor."""
    get_db()
    log.info("[DB] Tablolar hazır")

# ── Singleton ─────────────────────────────────────────────
_db_instance: Optional[DBConnection] = None

def get_db() -> DBConnection:
    global _db_instance
    if _db_instance is None:
        _db_instance = DBConnection()
    return _db_instance
