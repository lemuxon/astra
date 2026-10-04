# =========================================================
# ASTRA v30.0 — MODEL REGISTRY (Versiyonlama)
# MLflow benzeri ama bağımsız — ek servis gerektirmez.
# Her model eğitiminde:
#   - Parametreler, accuracy, eğitim koşulları kaydedilir
#   - Model versiyonu artırılır
#   - "En iyi" model takip edilir, gerilerse rollback yapılır
#   - SQLite + JSON metadata
#
# Neden?
#   Şu an .pkl dosyaları üzerine yazılıyor — "hangi model daha iyiydi?"
#   sorusu cevaplanamıyordu. Versiyonlama ile her eğitim kayıtlı.
# =========================================================
import logging, json, os, shutil, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List

log = logging.getLogger("ASTRA.MODEL_REGISTRY")

# v57: Yol sabitleri env ile yonlendirilebilir. Sabit kodlu olduklari surece
# test kosulari URETIM registry'sine yaziyordu (kosu basina +2 versiyon).
REGISTRY_DB    = os.getenv("MODEL_REGISTRY_DB",  "data/model_registry.db")
VERSIONS_DIR   = os.getenv("MODEL_VERSIONS_DIR", "saved_models/versions")
Path(VERSIONS_DIR).mkdir(parents=True, exist_ok=True)


class ModelRegistry:
    """
    Model versiyonlama ve performans takibi.

    Akış:
      1. Yeni model eğitildiğinde register() çağrılır
      2. Versiyon, params, accuracy, market koşulları kaydedilir
      3. En iyi versiyon takip edilir
      4. Performans düşerse rollback() ile eski versiyona dönülür
    """

    def __init__(self):
        self._db_init()

    def _baglanti(self):
        conn = sqlite3.connect(REGISTRY_DB, timeout=10, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        conn.row_factory = sqlite3.Row
        return conn

    def _db_init(self):
        Path("data").mkdir(exist_ok=True)
        conn = self._baglanti(); c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS model_versions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                sembol       TEXT NOT NULL,
                model_tipi   TEXT NOT NULL,
                versiyon     INTEGER NOT NULL,
                accuracy     REAL,
                f1_score     REAL,
                sharpe_canli REAL DEFAULT 0,
                params       TEXT,
                feature_sayisi INTEGER,
                egitim_orneklem INTEGER,
                rejim        TEXT,
                ts           TEXT,
                dosya_yolu   TEXT,
                aktif        INTEGER DEFAULT 0,
                canli_islem  INTEGER DEFAULT 0,
                canli_pnl    REAL DEFAULT 0
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_sembol_tip
            ON model_versions(sembol, model_tipi)
        """)
        conn.commit(); conn.close()

    def _eski_surumleri_buda(self, sembol: str, model_tipi: str) -> int:
        """Eski model .pkl dosyalarını sil — KORUNMASI GEREKENLER hariç.

        ── v58 (K-39): SINIRSIZ BÜYÜME ────────────────────────────
        Arşiv 2026-09-10'da 7174 dosya / 26.3 GB idi ve hiçbir temizlik
        yoktu (5 coinle ~0.7 GB/gün; 50 coinle ~7 GB/gün).

        ⚠️ HEPSİNİ SİLMEK YANLIŞ OLUR: `rollback_yap()` performans
        düşünce eski sürüme geri dönüyor. Bu yüzden üç grup korunur:
          1. Son N sürüm (MODEL_SAKLANAN_SURUM)
          2. `aktif=1` olan
          3. `en_iyi_versiyon()`in işaret ettiği
        Yalnızca DOSYA silinir; DB kaydı (accuracy geçmişi, canlı sonuç)
        DURUR — `gecmis()` ve raporlar bozulmaz.

        Döner: silinen dosya sayısı
        """
        try:
            from config import MODEL_SAKLANAN_SURUM as _N
        except ImportError:
            _N = 20
        silinen = 0
        try:
            conn = self._baglanti(); c = conn.cursor()
            c.execute("""
                SELECT versiyon, dosya_yolu, aktif FROM model_versions
                WHERE sembol=? AND model_tipi=? AND dosya_yolu IS NOT NULL
                  AND dosya_yolu != ''
                ORDER BY versiyon DESC
            """, (sembol, model_tipi))
            satirlar = c.fetchall()
            conn.close()

            if len(satirlar) <= _N:
                return 0

            korunan = set()
            for r in satirlar[:_N]:                  # son N
                korunan.add(r[1])
            for r in satirlar:                       # aktif olan
                if r[2]:
                    korunan.add(r[1])
            en_iyi = self.en_iyi_versiyon(sembol, model_tipi)
            if en_iyi and en_iyi.get("dosya_yolu"):
                korunan.add(en_iyi["dosya_yolu"])

            for _v, yol, _a in satirlar:
                if yol in korunan or not yol:
                    continue
                try:
                    if os.path.exists(yol):
                        os.remove(yol)
                        silinen += 1
                except OSError as e:
                    # §5.2: sessiz yutma yok — silinemeyen dosya birikirse
                    # politika çalışmıyor demektir, görünür olmalı.
                    log.warning(f"[REGISTRY] {os.path.basename(yol)} "
                                f"silinemedi: {e}")
            if silinen:
                log.info(f"[REGISTRY] {sembol}/{model_tipi}: {silinen} eski "
                         f"sürüm dosyası silindi (son {_N} + aktif + en iyi korundu)")
        except Exception as e:
            # Budama başarısız olsa da kayıt geçerlidir — asla register'ı
            # düşürme, yalnızca uyar.
            log.warning(f"[REGISTRY] Budama başarısız ({sembol}/{model_tipi}): {e}")
        return silinen

    def sonraki_versiyon(self, sembol: str, model_tipi: str) -> int:
        conn = self._baglanti(); c = conn.cursor()
        c.execute("""
            SELECT MAX(versiyon) as max_v FROM model_versions
            WHERE sembol=? AND model_tipi=?
        """, (sembol, model_tipi))
        row = c.fetchone(); conn.close()
        return (row["max_v"] or 0) + 1

    def register(self, sembol: str, model_tipi: str,
                 model_dosya: str, accuracy: float,
                 params: dict = None, f1: float = 0,
                 feature_sayisi: int = 0, orneklem: int = 0,
                 rejim: str = "") -> int:
        """
        Yeni model versiyonu kaydet.
        Model dosyasını versiyonlu klasöre kopyalar.
        Returns: versiyon numarası
        """
        try:
            versiyon = self.sonraki_versiyon(sembol, model_tipi)

            # Model dosyasını versiyonlu olarak sakla
            versiyon_yolu = ""
            if os.path.exists(model_dosya):
                ext = os.path.splitext(model_dosya)[1]
                hedef = os.path.join(
                    VERSIONS_DIR,
                    f"{model_tipi}_{sembol.replace('-','_')}_v{versiyon}{ext}"
                )
                shutil.copy2(model_dosya, hedef)
                versiyon_yolu = hedef

            conn = self._baglanti(); c = conn.cursor()
            # Önceki aktif modeli pasifleştir
            c.execute("""
                UPDATE model_versions SET aktif=0
                WHERE sembol=? AND model_tipi=?
            """, (sembol, model_tipi))
            # Yeni versiyonu aktif kaydet
            c.execute("""
                INSERT INTO model_versions
                (sembol, model_tipi, versiyon, accuracy, f1_score, params,
                 feature_sayisi, egitim_orneklem, rejim, ts, dosya_yolu, aktif)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,1)
            """, (
                sembol, model_tipi, versiyon, accuracy, f1,
                json.dumps(params or {}), feature_sayisi, orneklem, rejim,
                datetime.now(timezone.utc).isoformat(), versiyon_yolu
            ))
            conn.commit(); conn.close()

            log.info(f"[REGISTRY] {sembol}/{model_tipi} v{versiyon} kaydedildi "
                     f"acc={accuracy:.3f}")
            # v58 (K-39): her kayıttan sonra eski sürümleri buda.
            self._eski_surumleri_buda(sembol, model_tipi)
            return versiyon

        except Exception as e:
            log.error(f"[REGISTRY] Kayıt hatası: {e}")
            return 0

    def canli_sonuc_guncelle(self, sembol: str, model_tipi: str,
                              pnl_pct: float):
        """Aktif modelin canlı performansını güncelle."""
        try:
            conn = self._baglanti(); c = conn.cursor()
            c.execute("""
                UPDATE model_versions
                SET canli_islem = canli_islem + 1,
                    canli_pnl   = canli_pnl + ?
                WHERE sembol=? AND model_tipi=? AND aktif=1
            """, (pnl_pct, sembol, model_tipi))
            conn.commit(); conn.close()
        except Exception as e:
            log.debug(f"[REGISTRY] Canlı güncelleme: {e}")

    def en_iyi_versiyon(self, sembol: str, model_tipi: str) -> Optional[dict]:
        """En yüksek canlı PnL'e sahip versiyonu döner."""
        try:
            conn = self._baglanti(); c = conn.cursor()
            c.execute("""
                SELECT * FROM model_versions
                WHERE sembol=? AND model_tipi=? AND canli_islem >= 5
                ORDER BY (canli_pnl / canli_islem) DESC
                LIMIT 1
            """, (sembol, model_tipi))
            row = c.fetchone(); conn.close()
            return dict(row) if row else None
        except Exception as e:
            log.debug(f"[REGISTRY] {e}")
            return None

    def rollback_gerekli_mi(self, sembol: str, model_tipi: str,
                             min_islem: int = 10,
                             max_kayip_pct: float = -5.0) -> Optional[dict]:
        """
        Aktif model kötü performans gösteriyorsa, daha iyi eski versiyonu döner.
        Returns: rollback hedefi versiyon dict veya None
        """
        try:
            conn = self._baglanti(); c = conn.cursor()
            # Aktif modelin performansı
            c.execute("""
                SELECT * FROM model_versions
                WHERE sembol=? AND model_tipi=? AND aktif=1
            """, (sembol, model_tipi))
            aktif = c.fetchone()
            if not aktif or aktif["canli_islem"] < min_islem:
                conn.close(); return None

            aktif_ort = aktif["canli_pnl"] / max(aktif["canli_islem"], 1)
            if aktif_ort >= max_kayip_pct:
                conn.close(); return None   # Performans yeterli

            # Daha iyi geçmiş versiyon var mı?
            c.execute("""
                SELECT * FROM model_versions
                WHERE sembol=? AND model_tipi=? AND aktif=0
                  AND canli_islem >= ?
                ORDER BY (canli_pnl / canli_islem) DESC LIMIT 1
            """, (sembol, model_tipi, min_islem))
            aday = c.fetchone(); conn.close()

            if aday:
                aday_ort = aday["canli_pnl"] / max(aday["canli_islem"], 1)
                if aday_ort > aktif_ort:
                    log.warning(f"[REGISTRY] {sembol}/{model_tipi} rollback önerisi: "
                                f"v{aktif['versiyon']}({aktif_ort:.2f}) → "
                                f"v{aday['versiyon']}({aday_ort:.2f})")
                    return dict(aday)
            return None
        except Exception as e:
            log.debug(f"[REGISTRY] Rollback kontrol: {e}")
            return None

    def rollback_yap(self, sembol: str, model_tipi: str,
                      hedef_versiyon: dict, model_dir: str) -> bool:
        """Eski versiyonu aktif modele geri yükle."""
        try:
            kaynak = hedef_versiyon.get("dosya_yolu", "")
            if not kaynak or not os.path.exists(kaynak):
                return False
            ext  = os.path.splitext(kaynak)[1]
            hedef= os.path.join(model_dir,
                                 f"{model_tipi}_{sembol.replace('-','_')}{ext}")
            # v23: Atomik kopya — paralel loop yarı yazılmış dosyayı okumasın
            _tmp = hedef + ".tmp"
            shutil.copy2(kaynak, _tmp)
            os.replace(_tmp, hedef)   # atomic rename (aynı dosya sisteminde)

            conn = self._baglanti(); c = conn.cursor()
            c.execute("""UPDATE model_versions SET aktif=0
                         WHERE sembol=? AND model_tipi=?""", (sembol, model_tipi))
            c.execute("""UPDATE model_versions SET aktif=1
                         WHERE id=?""", (hedef_versiyon["id"],))
            conn.commit(); conn.close()
            log.info(f"[REGISTRY] {sembol}/{model_tipi} "
                     f"v{hedef_versiyon['versiyon']}'e rollback yapıldı")
            return True
        except Exception as e:
            log.error(f"[REGISTRY] Rollback hatası: {e}")
            return False

    def gecmis(self, sembol: str, model_tipi: str = None,
               limit: int = 10) -> List[dict]:
        try:
            conn = self._baglanti(); c = conn.cursor()
            if model_tipi:
                c.execute("""SELECT * FROM model_versions
                             WHERE sembol=? AND model_tipi=?
                             ORDER BY id DESC LIMIT ?""",
                          (sembol, model_tipi, limit))
            else:
                c.execute("""SELECT * FROM model_versions WHERE sembol=?
                             ORDER BY id DESC LIMIT ?""", (sembol, limit))
            rows = [dict(r) for r in c.fetchall()]; conn.close()
            return rows
        except Exception as e:
            log.debug(f"[REGISTRY] {e}")
            return []

    def telegram_raporu(self, sembol: str = None) -> str:
        try:
            from config import COINS
            semboller = [sembol] if sembol else COINS[:3]
            satirlar = ["📦 <b>MODEL REGISTRY v22</b>", "━━━━━━━━━━━━━━━━"]
            for s in semboller:
                gecmis = self.gecmis(s, limit=3)
                if not gecmis:
                    satirlar.append(f"<b>{s}</b>: kayıt yok")
                    continue
                satirlar.append(f"<b>{s}</b>:")
                for g in gecmis:
                    aktif_e = "✅" if g["aktif"] else "  "
                    canli   = (g["canli_pnl"]/g["canli_islem"]) if g["canli_islem"] > 0 else 0
                    satirlar.append(
                        f" {aktif_e} {g['model_tipi']} v{g['versiyon']} "
                        f"acc={g['accuracy']:.2f} canlı={canli:+.2f}%({g['canli_islem']})"
                    )
            return "\n".join(satirlar)
        except Exception as e:
            return f"Registry rapor hatası: {e}"


# ── Singleton ─────────────────────────────────────────────
_registry: Optional[ModelRegistry] = None

_registry_lock = __import__('threading').Lock()   # v55

def get_model_registry() -> ModelRegistry:
    global _registry
    if _registry is None:                      # v55: double-checked locking
        with _registry_lock:
            if _registry is None:
                _registry = ModelRegistry()
    return _registry
