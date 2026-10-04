# =========================================================
# ASTRA v30.0 — DATABASE KATMANI
# data/database.py
# =========================================================

import sqlite3
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

import sys
sys.path.append("..")
from config import DB_PATH

log = logging.getLogger("ASTRA.DB")


def baglanti_al() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    # v40: db_manager ile tutarlılık — aynı DB'ye yazıldığı için WAL şart.
    # Eksikliği "database is locked" hatalarına yol açabilirdi.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return conn


@contextmanager
def baglanti():
    """v49 GÜVENLİK: Bağlantı kapanışını GARANTİ eden context manager.

    Önceki kod `conn.close()`'u try/finally DIŞINDA çağırıyordu; execute
    veya commit hata fırlatırsa bağlantı sızıyordu. 7/24 çalışan sistemde
    bu birikir ve "too many open files" hatasına yol açar.

    Kullanım:
        with baglanti() as conn:
            conn.execute(...)
            conn.commit()
    """
    conn = baglanti_al()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass






def tablolari_olustur():
    with baglanti() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                sembol TEXT NOT NULL,
                timeframe TEXT DEFAULT '1h',
                fiyat REAL NOT NULL,
                ai_score INTEGER NOT NULL,
                karar TEXT NOT NULL,
                rsi REAL, macd REAL,
                confidence INTEGER, sentiment INTEGER,
                model_adi TEXT, extras TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ac TEXT NOT NULL,
                ts_kapat TEXT,
                sembol TEXT NOT NULL,
                yon TEXT NOT NULL,
                giris_fiyat REAL NOT NULL,
                cikis_fiyat REAL,
                miktar REAL NOT NULL,
                stop_loss REAL, take_profit REAL,
                pnl REAL, pnl_yuzde REAL,
                komisyon REAL,
                durum TEXT DEFAULT 'ACIK',
                mod TEXT DEFAULT 'PAPER',
                signal_id INTEGER,
                FOREIGN KEY (signal_id) REFERENCES signals(id)
            )
        """)

        # ── v58 (K-42): `komisyon` kolonu SONRADAN eklendi ──────────
        # Komisyon kapanışta hesaplanıp PnL'den düşülüyordu ama HİÇ
        # SAKLANMIYORDU. Sonuç: "ne kadar komisyon ödedim" sorusunun
        # geriye dönük cevabı yoktu — maliyet optimizasyonunun ilk
        # gereği tam olarak bu bilgi.
        # ALTER TABLE idempotent değil; kolon var mı diye bakıyoruz.
        try:
            _mevcut = {r[1] for r in c.execute("PRAGMA table_info(trades)")}
            if "komisyon" not in _mevcut:
                c.execute("ALTER TABLE trades ADD COLUMN komisyon REAL")
                log.info("[DB] trades.komisyon kolonu eklendi (K-42)")
            # ── v58 (K-86): KALDIRAÇ ve MARJİN saklanıyor ───────────
            # Paper `kaldirac=1` sabitiyle çalışıyordu; canlı yol ise
            # `kaldirac_ayarla()` ile gerçek kaldıraç kuruyor. Kapanışta
            # bakiyeye kaç USDT iade edileceği MARJİNE bağlı olduğu için
            # bu iki alan kayıtta DURMALI — aksi halde kaldıraç sonradan
            # değişirse eski pozisyonların iadesi yanlış hesaplanır.
            if "kaldirac" not in _mevcut:
                c.execute("ALTER TABLE trades ADD COLUMN kaldirac REAL")
                log.info("[DB] trades.kaldirac kolonu eklendi (K-86)")
            if "marjin" not in _mevcut:
                c.execute("ALTER TABLE trades ADD COLUMN marjin REAL")
                log.info("[DB] trades.marjin kolonu eklendi (K-86)")
            # ── v58 (K-87): FUNDING (fonlama) maliyeti ──────────────
            # Perpetual futures 8 saatte bir fonlama öder/alır. Paper bunu
            # HİÇ modellemiyordu; komisyon (K-42) modelleniyordu ama
            # fonlama unutulmuştu. 24 saatlik tutuşta 3 ödeme eder.
            # Gerçek oranlar (2026-09-13 ölçüldü): 8 saatte %0.0032-0.0100
            # → yıllık %3.5-11. LONG pozitif oranda ÖDER, SHORT ALIR.
            if "funding_rate" not in _mevcut:
                c.execute("ALTER TABLE trades ADD COLUMN funding_rate REAL")
                log.info("[DB] trades.funding_rate kolonu eklendi (K-87)")
            if "funding_maliyet" not in _mevcut:
                c.execute("ALTER TABLE trades ADD COLUMN funding_maliyet REAL")
                log.info("[DB] trades.funding_maliyet kolonu eklendi (K-87)")
            # v58 (K-88): tasfiye fiyatı kayıtta dursun — sonradan
            # "bu pozisyon tasfiyeye ne kadar yakındı" sorulabilsin.
            if "tasfiye_fiyat" not in _mevcut:
                c.execute("ALTER TABLE trades ADD COLUMN tasfiye_fiyat REAL")
                log.info("[DB] trades.tasfiye_fiyat kolonu eklendi (K-88)")
        except Exception as _me:
            # fail-loud (§5.2): sessizce geçersek komisyon hiç yazılmaz
            # ve rapor sessizce sıfır gösterir.
            log.error(f"[DB] komisyon kolonu eklenemedi: "
                      f"{type(_me).__name__}: {_me}")

        c.execute("""
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                sembol TEXT NOT NULL,
                model_adi TEXT NOT NULL,
                dogruluk REAL NOT NULL,
                toplam_sinyal INTEGER,
                dogru_sinyal INTEGER,
                win_rate REAL,
                toplam_pnl REAL,
                sharpe REAL,
                max_drawdown REAL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS backtest (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                sembol TEXT NOT NULL,
                baslangic TEXT, bitis TEXT,
                toplam_islem INTEGER,
                kazanan INTEGER, kaybeden INTEGER,
                win_rate REAL,
                toplam_getiri REAL,
                max_drawdown REAL,
                sharpe REAL,
                params TEXT
            )
        """)

        # v6.0: Günlük PnL takip tablosu
        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih TEXT NOT NULL UNIQUE,
                pnl_usdt REAL DEFAULT 0,
                islem_sayisi INTEGER DEFAULT 0,
                guncellendi TEXT
            )
        """)

        conn.commit()
        log.info("Veritabanı tabloları hazır.")


def sinyal_kaydet(sembol, fiyat, ai_score, karar,
                  rsi=None, macd=None, confidence=None,
                  sentiment=None, model_adi=None,
                  timeframe="1h", extras=None) -> int:
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO signals
                (ts,sembol,timeframe,fiyat,ai_score,karar,
                 rsi,macd,confidence,sentiment,model_adi,extras)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), sembol, timeframe, fiyat,
              ai_score, karar, rsi, macd, confidence, sentiment, model_adi,
              json.dumps(extras) if extras else None))
        conn.commit()
        row_id = c.lastrowid
        return row_id


def trade_ac(sembol, yon, giris_fiyat, miktar,
             stop_loss=None, take_profit=None,
             mod="PAPER", signal_id=None,
             kaldirac=1.0, marjin=None, funding_rate=0.0,
             tasfiye_fiyat=0.0) -> int:
    """v58 (K-86): `kaldirac` ve `marjin` de saklanır.

    Kapanışta bakiyeye iade edilecek tutar MARJİNE bağlıdır. Kayıtta
    durmazsa, kaldıraç ayarı sonradan değişince eski pozisyonların
    iadesi yanlış hesaplanır (sessiz para kaçağı — K-59 sınıfı).
    """
    if marjin is None:
        marjin = giris_fiyat * miktar / max(1.0, float(kaldirac))
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO trades
                (ts_ac,sembol,yon,giris_fiyat,miktar,
                 stop_loss,take_profit,mod,signal_id,kaldirac,marjin,funding_rate,
                 tasfiye_fiyat)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), sembol, yon, giris_fiyat,
              miktar, stop_loss, take_profit, mod, signal_id,
              float(kaldirac), float(marjin), float(funding_rate or 0.0),
              float(tasfiye_fiyat or 0.0)))
        conn.commit()
        row_id = c.lastrowid
        log.info(f"[TRADE AÇILDI] #{row_id} {sembol} {yon} @ {giris_fiyat:.2f} x{miktar}")
        return row_id


def trade_kapat(trade_id, cikis_fiyat, durum="KAPALI", pnl=None, pnl_yuzde=None,
                komisyon=None, funding_maliyet=None):
    """Trade'i kapat.

    v56: `pnl` / `pnl_yuzde` parametreleri EKLENDİ.
    Çağıran taraf komisyon/slippage düşülmüş NET PnL'i biliyorsa onu geçmeli.
    Aksi halde burada BRÜT PnL hesaplanıyordu ve `toplam_pnl()` ile
    PaperTrader.bakiye birbirinden sapıyordu (bakiye net, DB brüt tutuyordu).
    Geçilmezse eski davranış korunur (geriye dönük uyumlu).
    """
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM trades WHERE id=?", (trade_id,))
        trade = c.fetchone()
        if not trade:
            return
        giris    = trade["giris_fiyat"]
        miktar   = trade["miktar"]
        yon      = trade["yon"]
        if pnl is None:
            pnl = (cikis_fiyat - giris) * miktar if yon == "LONG" else (giris - cikis_fiyat) * miktar
        if pnl_yuzde is None:
            pnl_yuzde = (pnl / (giris * miktar)) * 100 if (giris > 0 and miktar > 0) else 0
        # v58 (K-42): komisyon da saklanıyor. Geçilmezse NULL kalır —
        # eski kayıtlarla ayırt edilebilir olsun diye 0 yazılmıyor.
        c.execute("""
            UPDATE trades SET ts_kapat=?,cikis_fiyat=?,pnl=?,pnl_yuzde=?,
                              durum=?,komisyon=?,funding_maliyet=?
            WHERE id=?
        """, (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), cikis_fiyat,
              round(pnl, 4), round(pnl_yuzde, 4), durum,
              round(komisyon, 6) if komisyon is not None else None,
              # v58 (K-87): fonlama maliyeti de saklanır — komisyon gibi
              # (K-42). Saklanmazsa "ne kadar fonlama ödedim" sorusunun
              # geriye dönük cevabı olmaz.
              round(funding_maliyet, 6) if funding_maliyet is not None else None,
              trade_id))
        conn.commit()
        log.info(f"[TRADE KAPANDI] #{trade_id} PnL:{pnl:.4f} ({pnl_yuzde:.2f}%) → {durum}")


def performans_kaydet(sembol, model_adi, dogruluk,
                      toplam_sinyal=0, dogru_sinyal=0,
                      win_rate=0, toplam_pnl=0,
                      sharpe=0, max_drawdown=0):
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO performance
                (ts,sembol,model_adi,dogruluk,toplam_sinyal,
                 dogru_sinyal,win_rate,toplam_pnl,sharpe,max_drawdown)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), sembol, model_adi, dogruluk,
              toplam_sinyal, dogru_sinyal, win_rate, toplam_pnl, sharpe, max_drawdown))
        conn.commit()


def backtest_kaydet(sembol, baslangic, bitis, toplam_islem,
                    kazanan, kaybeden, win_rate, toplam_getiri,
                    max_drawdown, sharpe, params=None):
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO backtest
                (ts,sembol,baslangic,bitis,toplam_islem,kazanan,
                 kaybeden,win_rate,toplam_getiri,max_drawdown,sharpe,params)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), sembol, baslangic, bitis,
              toplam_islem, kazanan, kaybeden, win_rate, toplam_getiri,
              max_drawdown, sharpe, json.dumps(params) if params else None))
        conn.commit()


def son_sinyaller(sembol=None, limit=20) -> list:
    with baglanti() as conn:
        c = conn.cursor()
        if sembol:
            c.execute("SELECT * FROM signals WHERE sembol=? ORDER BY id DESC LIMIT ?", (sembol, limit))
        else:
            c.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in c.fetchall()]
        return rows


def acik_tradeler(mod="PAPER") -> list:
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM trades WHERE durum='ACIK' AND mod=?", (mod,))
        rows = [dict(r) for r in c.fetchall()]
        return rows


def son_kapanis_yasi_sn(sembol: str, mod="PAPER"):
    """Bu sembolde en son kapanan işlemin üstünden kaç saniye geçti?

    v58 (K-C): yeniden giriş bekleme süresi için. Hiç kapanmış işlem
    yoksa None döner (= bekleme kısıtı yok).

    DB'den okunur, bellekten DEĞİL: bot yeniden başladığında bellekteki
    sayaç sıfırlanır ve bekleme sessizce devre dışı kalırdı. Bot ~12
    saatte bir ölüp watchdog ile geri geliyor (§7.9), yani bu gerçek bir
    senaryo.

    ⚠️ fail-open DEĞİL (§5.1): sorgu çökerse "bekleme yok" demez,
    çağıran tarafın karar vermesi için istisnayı yükseltir.
    """
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("SELECT MAX(ts_kapat) FROM trades "
                  "WHERE sembol=? AND mod=? AND durum!='ACIK' AND ts_kapat IS NOT NULL",
                  (sembol, mod))
        ts = c.fetchone()[0]
    if not ts:
        return None
    # ⚠️ ts_kapat NAIVE UTC yazılıyor (trade_kapat: datetime.now(timezone.utc)
    #    .replace(tzinfo=None)). Burada datetime.now() (yerel) kullanılırsa
    #    bu makinede yaş 3 saat şişer, bekleme kapısı HİÇ tetiklenmez ve
    #    hata sessiz kalır. Karşılaştırma aynı ölçekte olmalı.
    return (datetime.now(timezone.utc).replace(tzinfo=None)
            - datetime.fromisoformat(ts)).total_seconds()


def toplam_pnl(mod="PAPER") -> float:
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("SELECT SUM(pnl) FROM trades WHERE durum != 'ACIK' AND mod=?", (mod,))
        sonuc = c.fetchone()[0]
        return round(sonuc or 0, 4)


def win_rate_hesapla(mod="PAPER") -> dict:
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) as toplam,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as kazanan,
                   SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as kaybeden,
                   AVG(pnl) as ort_pnl
            FROM trades WHERE durum != 'ACIK' AND mod=?
        """, (mod,))
        row = dict(c.fetchone())
        toplam = row["toplam"] or 1
        row["win_rate"] = round((row["kazanan"] or 0) / toplam * 100, 2)
        return row


def model_gecmisi(sembol, limit=10) -> list:
    with baglanti() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM performance WHERE sembol=? ORDER BY id DESC LIMIT ?", (sembol, limit))
        rows = [dict(r) for r in c.fetchall()]
        return rows


# ── Otomatik tablo oluşturma (import sırasında) ───────────
try:
    tablolari_olustur()
except Exception:
    pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tablolari_olustur()
    print("✅ Veritabanı hazır:", DB_PATH)
