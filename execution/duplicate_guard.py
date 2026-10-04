# =========================================================
# ASTRA EXECUTION LAYER — DUPLICATE EXECUTION GUARD
# =========================================================
# Race condition'a dayanıklı duplicate prevention.
# Sorun: Time-window tabanlı kontrol yeterli değil.
#   - Aynı sinyalin iki thread'de aynı anda işlenmesi
#   - Network timeout sonrası retry → çift pozisyon
#   - Sinyal üretimi hız > execution hızı
#
# Çözüm: İşlem başladığında atomik kilit al, bitince bırak.
# Ek olarak: Binance'ten gerçek pozisyon durumunu doğrula.
# =========================================================

import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Set
import sys
sys.path.append("..")

log = logging.getLogger("ASTRA.DUPLICATE_GUARD")


class DuplicateGuard:
    """
    Thread-safe, atomik duplicate execution koruması.

    v9'daki sorun: `_son_emirler` dict'i ve `DUPLICATE_WINDOW_SEC`
    time-window kontrolü race condition'a açık.
    İki thread aynı anda kontrol edip ikisi de "OK" diyebilir.

    Bu sınıf threading.Lock() ile atomik kontrol sağlar.
    """

    def __init__(self):
        self._lock            = threading.Lock()
        self._islem_altinda: Set[str] = set()   # Şu an işlenen semboller
        self._tamamlanan:    dict     = {}       # {key: timestamp}
        self._COOLDOWN        = 300              # 5 dakika cooldown
        self._istatistik      = {
            "engellenen": 0,
            "izin_verilen": 0,
            "kilitli_engel": 0,
        }

    def _anahtar(self, sembol: str, yon: str) -> str:
        return f"{sembol.upper()}_{yon.upper()}"

    @contextmanager
    def isle(self, sembol: str, yon: str):
        """
        Context manager: işlem süresince sembolü kilitler.

        Kullanım:
            guard = DuplicateGuard()
            with guard.isle("BTCUSDT", "LONG") as izin:
                if not izin:
                    return   # duplicate, işleme
                # ... emir gönder ...
        """
        anahtar = self._anahtar(sembol, yon)
        izin    = False

        # ── v55 KRİTİK EŞZAMANLILIK DÜZELTMESİ ──
        # Eskiden Binance pozisyon sorgusu (ağ çağrısı, yavaş ağda 15s'e
        # kadar) LOCK İÇİNDE yapılıyordu. Bu süre boyunca aynı guard'ı
        # kullanan TÜM thread'ler bloklanıyordu → ana döngü tıkanması,
        # watchdog alarmı. Lock içinde ağ çağrısı klasik anti-pattern'dir.
        #
        # Yeni akış: (1) lock al, hızlı kontroller + kilit → lock bırak,
        # (2) ağ sorgusu lock DIŞINDA, (3) sonuca göre kilidi bırak.
        # Atomiklik korunur: adım 1'de kilit alındığı için aynı sembol
        # için başka thread giremez.
        with self._lock:
            # 1) Şu an işlem görüyor mu?
            if anahtar in self._islem_altinda:
                log.warning(f"[DUPLICATE GUARD] {sembol} {yon} zaten işleniyor — engellendi")
                self._istatistik["kilitli_engel"] += 1
                yield False
                return

            # 2) Cooldown kontrolü
            son_zaman = self._tamamlanan.get(anahtar, 0)
            gecen     = time.time() - son_zaman
            if gecen < self._COOLDOWN:
                log.warning(f"[DUPLICATE GUARD] {sembol} {yon} cooldown — "
                             f"{gecen:.0f}s/{self._COOLDOWN}s geçti — engellendi")
                self._istatistik["engellenen"] += 1
                yield False
                return

            # Kilit al (ağ sorgusundan ÖNCE — başka thread giremesin)
            self._islem_altinda.add(anahtar)
            izin = True

        # 3) Binance pozisyon sorgusu — LOCK DIŞINDA (yavaş olabilir)
        sorgu_hatasi = None
        try:
            pozisyon_var = self._binance_pozisyon_var(sembol, yon)
        except Exception as e:
            # Sorgu başarısızsa fail-safe: işleme İZİN VERME
            sorgu_hatasi = e
            log.error(f"[DUPLICATE GUARD] {sembol} pozisyon sorgusu başarısız: {e} "
                      f"→ güvenlik gereği işlem engellendi")
            pozisyon_var = True

        if pozisyon_var:
            if sorgu_hatasi is None:
                log.warning(f"[DUPLICATE GUARD] {sembol} {yon} Binance'te zaten açık — engellendi")
            else:
                log.warning(f"[DUPLICATE GUARD] {sembol} {yon} pozisyon durumu "
                            f"DOĞRULANAMADI — fail-safe engelleme")
            with self._lock:
                self._islem_altinda.discard(anahtar)
                self._istatistik["engellenen"] += 1
            yield False
            return

        with self._lock:
            self._istatistik["izin_verilen"] += 1

        try:
            yield True
        finally:
            with self._lock:
                self._islem_altinda.discard(anahtar)
                if izin:
                    self._tamamlanan[anahtar] = time.time()
                    # Eski kayıtları temizle
                    eski = time.time() - self._COOLDOWN * 2
                    self._tamamlanan = {k: v for k, v in self._tamamlanan.items()
                                        if v > eski}

    def _binance_pozisyon_var(self, sembol: str, yon: str) -> bool:
        """Binance'ten gerçek pozisyon durumunu sorgular.

        v55 DÜZELTME: Bu metot İSTİSNA YAKALAMAZ.
        Eskiden burada `except Exception: return False` vardı; bu, çağırandaki
        fail-closed bloğunu (isle() içinde `pozisyon_var = True`) ULAŞILAMAZ
        ölü koda çeviriyordu. Sonuç: Binance'e erişilemediği anda guard
        "pozisyon yok" deyip işleme İZİN VERİYORDU — yani belgelenen
        fail-safe davranışın tam tersi.
        Hata durumunda ne yapılacağına karar vermek çağıranın işidir.
        """
        from data.binance_futures_client import acik_futures_pozisyonlar
        # strict=True: sorgu başarısızsa boş liste DÖNMEZ, istisna yükselir.
        pozlar = acik_futures_pozisyonlar(strict=True)
        return any(p["sembol"] == sembol.upper() and p["yon"] == yon.upper()
                   for p in pozlar)

    def cooldown_sifirla(self, sembol: str, yon: str):
        """Pozisyon kapandıktan sonra cooldown'ı sıfırla."""
        anahtar = self._anahtar(sembol, yon)
        with self._lock:
            self._tamamlanan.pop(anahtar, None)
            self._islem_altinda.discard(anahtar)
        log.debug(f"[DUPLICATE GUARD] {sembol} {yon} cooldown sıfırlandı")

    def durum(self) -> dict:
        with self._lock:
            return {
                "islem_altinda":    list(self._islem_altinda),
                "cooldown_sayisi":  len(self._tamamlanan),
                **self._istatistik,
            }


# Singleton
_guard_instance: Optional[DuplicateGuard] = None

def get_duplicate_guard() -> DuplicateGuard:
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = DuplicateGuard()
    return _guard_instance
