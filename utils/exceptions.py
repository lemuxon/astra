# =========================================================
# ASTRA v30.0 — HATA TAKSONOMİSİ
# Production'da tüm exception'lar bu hiyerarşiye göre
# sınıflandırılır. "except Exception" yerine
# spesifik tip kullanılır.
# =========================================================

# ── Temel ─────────────────────────────────────────────────

class AstraError(Exception):
    """Tüm ASTRA hatalarının tabanı."""
    def __init__(self, mesaj: str, kaynak: str = "", retryable: bool = False):
        self.kaynak    = kaynak
        self.retryable = retryable
        super().__init__(mesaj)

# ── Ağ / Bağlantı ─────────────────────────────────────────

class NetworkError(AstraError):
    """Geçici ağ hatası — retry yapılabilir."""
    def __init__(self, mesaj: str, kaynak: str = ""):
        super().__init__(mesaj, kaynak, retryable=True)

# v55 UYARI — İSİM GÖLGELEME:
# Aşağıdaki iki sınıf Python'un yerleşik (builtin) TimeoutError ve
# ConnectionError isimlerini GÖLGELER. Bu modülden `TimeoutError` /
# `ConnectionError` import eden bir dosyada `except ConnectionError:`
# yazmak, socket/requests/urllib3'ün fırlattığı GERÇEK istisnaları
# YAKALAMAZ (requests.exceptions.ConnectionError ayrı bir sınıftır).
#
# Tercih edilen isimler: AstraTimeoutError / AstraConnectionError.
# Kısa isimler yalnızca geriye dönük uyumluluk için korunuyor.
class AstraTimeoutError(NetworkError):
    """İstek zaman aşımına uğradı."""
    pass

class AstraConnectionError(NetworkError):
    """Sunucuya bağlanılamadı."""
    pass

# Geriye dönük uyumluluk takma adları (yeni kodda KULLANMAYIN)
TimeoutError    = AstraTimeoutError      # noqa: A001 — builtin gölgeler
ConnectionError = AstraConnectionError   # noqa: A001 — builtin gölgeler

class RateLimitError(NetworkError):
    """Rate limit aşıldı — bekle, retry yap.

    v55 DÜZELTME (YENİ BULGU): __init__ `super().__init__(mesaj, retryable=True)`
    çağırıyordu, ancak NetworkError.__init__ imzası (mesaj, kaynak) —
    `retryable` parametresi KABUL ETMİYOR. Yani bu sınıf ÖRNEKLENEMİYORDU:
    her denemede `TypeError: NetworkError.__init__() got an unexpected
    keyword argument 'retryable'`.
    Sınıf hiç kullanılmadığı (http_hata_siniflandir hiç çağrılmıyordu) için
    fark edilmemişti. NetworkError zaten retryable=True set ediyor.
    """
    def __init__(self, mesaj: str, bekleme_suresi: float = 60, kaynak: str = ""):
        super().__init__(mesaj, kaynak)
        self.bekleme_suresi = bekleme_suresi

# ── Borsa API ─────────────────────────────────────────────

class ExchangeError(AstraError):
    """Borsa API hatalarının tabanı."""
    def __init__(self, kod: int, mesaj: str, path: str = "", retryable: bool = False):
        self.kod  = kod
        self.path = path
        super().__init__(f"[{kod}] {mesaj} (path={path})", "Exchange", retryable)

class FatalExchangeError(ExchangeError):
    """
    Retry yapılmaması gereken borsa hatası.
    Örnek: -2010 (yetersiz bakiye), -1121 (geçersiz sembol)
    """
    FATAL_CODES = {
        -2010: "Yetersiz bakiye",
        -2011: "Bilinmeyen emir",
        -1121: "Geçersiz sembol",
        -4003: "Geçersiz kaldıraç",
        -4061: "Geçersiz marjin tipi",
        -4046: "Zaten ayarlı",
        -1100: "Geçersiz parametre",
        -1102: "Zorunlu parametre eksik",
    }

    def __init__(self, kod: int, mesaj: str, path: str = ""):
        super().__init__(kod, mesaj, path, retryable=False)

class RetryableExchangeError(ExchangeError):
    """
    Retry yapılabilir borsa hatası.
    Örnek: Geçici sunucu hatası, 5xx
    """
    def __init__(self, kod: int, mesaj: str, path: str = ""):
        super().__init__(kod, mesaj, path, retryable=True)

class InsufficientBalanceError(FatalExchangeError):
    """Yetersiz bakiye — retry yapma, kullanıcıyı uyar."""
    pass

class InvalidOrderError(FatalExchangeError):
    """Geçersiz emir parametresi — retry yapma."""
    pass

class OrderNotFoundError(FatalExchangeError):
    """Emir bulunamadı."""
    pass

# ── Execution ─────────────────────────────────────────────

class ExecutionError(AstraError):
    """Emir execution katmanı hatası."""
    pass

class FillTimeoutError(ExecutionError):
    """Emir dolum zaman aşımı."""
    def __init__(self, order_id: int, sembol: str, sure: float):
        self.order_id = order_id
        self.sembol   = sembol
        super().__init__(f"#{order_id} {sembol} fill timeout ({sure}s)", retryable=False)

class SlippageExceededError(ExecutionError):
    """Kabul edilemez slippage."""
    def __init__(self, sembol: str, beklenen: float, gercek: float, pct: float):
        self.sembol   = sembol
        self.beklenen = beklenen
        self.gercek   = gercek
        self.pct      = pct
        super().__init__(
            f"{sembol} slippage aşıldı: beklenen={beklenen:.4f} "
            f"gerçek={gercek:.4f} (%{pct:.3f})",
            retryable=False
        )

class StopLossFailedError(ExecutionError):
    """SL koyulamadı — kritik, pozisyon kapatılmalı."""
    def __init__(self, sembol: str, sl_fiyat: float):
        self.sembol   = sembol
        self.sl_fiyat = sl_fiyat
        super().__init__(
            f"{sembol} SL @ {sl_fiyat} koyulamadı — KRİTİK",
            retryable=False
        )

class DuplicateOrderError(ExecutionError):
    """Duplicate emir engellendi."""
    pass

# ── Risk ──────────────────────────────────────────────────

class RiskError(AstraError):
    """Risk kontrol ihlali — işlemi durdur."""
    pass

class DailyLossLimitError(RiskError):
    """Günlük kayıp limiti aşıldı."""
    pass

class LiquidationRiskError(RiskError):
    """Likidasyon riski tespit edildi."""
    def __init__(self, sembol: str, uzaklik_pct: float):
        self.sembol      = sembol
        self.uzaklik_pct = uzaklik_pct
        super().__init__(
            f"{sembol} likidasyon riski: %{uzaklik_pct:.1f} uzaklık",
            retryable=False
        )

class MarginExceededError(RiskError):
    """Marjin limiti aşıldı."""
    pass

class CorrelationLimitError(RiskError):
    """Portföy korelasyon limiti — yeni pozisyon açılamaz."""
    pass

# ── Model / Strateji ──────────────────────────────────────

class ModelError(AstraError):
    """Model eğitim veya tahmin hatası."""
    pass

class InsufficientDataError(ModelError):
    """Yetersiz veri — model eğitilemez."""
    pass

class ModelDegradedError(ModelError):
    """Model doğruluğu kabul sınırının altına düştü."""
    def __init__(self, sembol: str, accuracy: float, esik: float):
        self.sembol   = sembol
        self.accuracy = accuracy
        super().__init__(
            f"{sembol} model bozundu: acc={accuracy:.3f} < esik={esik}",
            retryable=False
        )

# ── Veritabanı ────────────────────────────────────────────

class DatabaseError(AstraError):
    """DB yazma/okuma hatası."""
    def __init__(self, mesaj: str, retryable: bool = True):
        super().__init__(mesaj, "Database", retryable)

class ConnectionPoolExhaustedError(DatabaseError):
    """Bağlantı havuzu tükendi."""
    pass

# ── Sistem ────────────────────────────────────────────────

class ConfigError(AstraError):
    """Yapılandırma hatası — başlatma sırasında."""
    pass

class StateCorruptedError(AstraError):
    """Pozisyon state bozuk."""
    pass


# ── Yardımcılar ───────────────────────────────────────────

# ── Geriye dönük uyumluluk aliasları ──────────────────────
# binance_futures_client ve diğer modüller bu isimleri doğrudan import eder.
FuturesAPIError    = FatalExchangeError   # eski isim → FatalExchangeError
# v55: AstraTimeoutError/AstraConnectionError artık ASIL sınıf adları
# (yukarıda tanımlı). Buradaki ters yönlü atamalar kaldırıldı — aynı
# nesneyi işaret ettikleri için işlevsizdi ve okuyanı yanıltıyordu.


def exchange_hata_siniflandir(kod: int, mesaj: str, path: str = "") -> AstraError:
    """
    Binance hata kodunu doğru exception tipine dönüştürür.

    NOT: Dönüş tipi v55'te ExchangeError'dan AstraError'a genişletildi —
    rate limit durumunda RateLimitError (NetworkError alt sınıfı) döner.
    """
    # v55: Eskiden burada ayrı bir `fatal = {...}` kümesi hardcode edilmişti ve
    # FatalExchangeError.FATAL_CODES hiç kullanılmıyordu. İkisi o an aynıydı
    # ama senkron kalmalarını sağlayan bir şey yoktu — birine kod eklenip
    # diğerine eklenmezse retryable/fatal yanlış sınıflandırılırdı.
    # Artık TEK kaynak: FatalExchangeError.FATAL_CODES
    fatal = set(FatalExchangeError.FATAL_CODES)

    # v55: Binance rate-limit kodu — çağıranın bekleme süresine uyabilmesi için
    # doğru tiple dönmeli (eskiden sıradan RetryableExchangeError oluyordu).
    if kod == -1003:
        return RateLimitError(f"[{kod}] {mesaj} (path={path})", 60)

    if kod in fatal:
        if kod == -2010:
            return InsufficientBalanceError(kod, mesaj, path)
        if kod in (-2011,):
            return OrderNotFoundError(kod, mesaj, path)
        if kod in (-1100, -1102):
            return InvalidOrderError(kod, mesaj, path)
        return FatalExchangeError(kod, mesaj, path)

    return RetryableExchangeError(kod, mesaj, path)


def http_hata_siniflandir(status_code: int, mesaj: str = "") -> AstraError:
    """HTTP status kodunu exception tipine dönüştürür."""
    if status_code == 429:
        return RateLimitError(f"HTTP 429 Rate Limit: {mesaj}", 60)
    if status_code in (400, 403):
        return FatalExchangeError(status_code, mesaj)
    if status_code in (500, 502, 503, 504):
        return RetryableExchangeError(status_code, f"Sunucu hatası {status_code}: {mesaj}")
    if status_code == 401:
        return FatalExchangeError(status_code, "Yetkisiz erişim — API key kontrol et")
    return RetryableExchangeError(status_code, mesaj)

# =========================================================
# v16.0 — Spesifik Exception Sınıfları
# =========================================================

class TradingHaltedError(AstraError):
    """Kill switch veya circuit breaker işlemi durdurdu."""
    pass

# NOT: CorrelationLimitError yukarıda (RiskError alt sınıfı olarak) tanımlıdır.
# v55 denetimi: burada AstraError alt sınıfı olarak ikinci kez tanımlanıyordu;
# ikinci tanım birinciyi gölgeleyip `except RiskError` bloklarının korelasyon
# ihlalini yakalamasını engelliyordu. Yinelenen tanım kaldırıldı.

class SpreadTooWideError(AstraError):
    """Spread çok geniş, işlem reddedildi."""
    pass

class VolatilityCircuitBreakerError(AstraError):
    """Volatilite eşiği aşıldı, işlem duraklatıldı."""
    pass

class ShadowModelNotApprovedError(AstraError):
    """Shadow model henüz onaylanmadı, canlı model güncellenmedi."""
    pass

class StaleMarketDataError(AstraError):
    """Piyasa verisi bayatladı (WebSocket kopmuş olabilir)."""
    pass

class DBWriteError(AstraError):
    """Veritabanı yazma hatası — trade kaydedilemedi."""
    pass

class OrderRejectError(AstraError):
    """Borsadan order reject yanıtı geldi."""
    pass
