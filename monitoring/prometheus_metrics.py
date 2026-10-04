# =========================================================
# ASTRA v30.0 — PROMETHEUS METRİKLERİ
# Grafana ile görselleştirme için metric export
# Kurulu değilse sessizce devre dışı kalır
# =========================================================
import logging, time
from typing import Optional
import sys; sys.path.append("..")
from config import PROMETHEUS_ENABLED, PROMETHEUS_PORT, PROMETHEUS_ADDR

log = logging.getLogger("ASTRA.PROMETHEUS")

try:
    from prometheus_client import (
        Counter, Gauge, Histogram, Summary,
        start_http_server, REGISTRY
    )
    PROM_AVAILABLE = True
except ImportError:
    PROM_AVAILABLE = False

class AstraMetrics:
    """
    Tüm metrikler burada tanımlanır.
    prometheus_client kurulu değilse no-op objeler döner.
    """

    def __init__(self):
        self._aktif = PROMETHEUS_ENABLED and PROM_AVAILABLE

        if not self._aktif:
            if PROMETHEUS_ENABLED and not PROM_AVAILABLE:
                log.warning("[PROM] prometheus_client kurulu değil: pip install prometheus-client")
            self._noop()
            return

        # ── Sayaçlar (Counter — sadece artar) ────────────
        self.sinyal_sayisi = Counter(
            "astra_signals_total", "Toplam üretilen sinyal",
            ["sembol", "karar", "rejim"]
        )
        self.emir_sayisi = Counter(
            "astra_orders_total", "Toplam emir",
            ["sembol", "yon", "durum"]
        )
        self.hata_sayisi = Counter(
            "astra_errors_total", "Hata sayısı",
            ["kaynak", "tip"]
        )

        # ── Anlık Değerler (Gauge) ────────────────────────
        self.futures_bakiye = Gauge(
            "astra_futures_balance_usdt", "Futures hesap bakiyesi"
        )
        self.acik_pozisyon = Gauge(
            "astra_open_positions", "Açık pozisyon sayısı"
        )
        self.gunluk_pnl = Gauge(
            "astra_daily_pnl_usdt", "Günlük PnL"
        )
        self.ai_score = Gauge(
            "astra_ai_score", "AI skor",
            ["sembol"]
        )
        self.model_accuracy = Gauge(
            "astra_model_accuracy", "Model doğruluğu",
            ["sembol", "model"]
        )
        self.drawdown = Gauge(
            "astra_drawdown_pct", "Mevcut drawdown yüzdesi"
        )
        self.var_usdt = Gauge(
            "astra_var_usdt", "Value at Risk (USDT)"
        )
        self.kuyruk_boyutu = Gauge(
            "astra_order_queue_size", "Order engine kuyruk boyutu"
        )
        self.exchange_saglik = Gauge(
            "astra_exchange_health", "Borsa sağlık durumu (1=OK, 0=DOWN)"
        )
        self.ws_aktif = Gauge(
            "astra_websocket_active", "WebSocket aktif mi (1/0)"
        )

        # ── Histogramlar (dağılım) ────────────────────────
        self.emir_suresi = Histogram(
            "astra_order_duration_seconds", "Emir tamamlanma süresi",
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )
        self.analiz_suresi = Histogram(
            "astra_analysis_duration_seconds", "Coin analiz süresi",
            buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
        )

        # ── Heartbeat ─────────────────────────────────────
        self.son_heartbeat = Gauge(
            "astra_last_heartbeat_timestamp", "Son heartbeat unix timestamp"
        )

        log.info(f"[PROM] Metrikler hazır, port: {PROMETHEUS_PORT}")

    def _noop(self):
        """prometheus_client yoksa hiçbir şey yapmayan objeler."""
        class NoOp:
            def labels(self, **kwargs): return self
            def inc(self, *a, **kw): pass
            def set(self, *a, **kw): pass
            def observe(self, *a, **kw): pass
            def time(self): return self
            def __enter__(self): return self
            def __exit__(self, *a): pass

        noop = NoOp()
        for attr in ["sinyal_sayisi","emir_sayisi","hata_sayisi","futures_bakiye",
                     "acik_pozisyon","gunluk_pnl","ai_score","model_accuracy",
                     "drawdown","var_usdt","kuyruk_boyutu","exchange_saglik",
                     "ws_aktif","emir_suresi","analiz_suresi","son_heartbeat"]:
            setattr(self, attr, noop)

    def baslat(self):
        if self._aktif:
            try:
                # v55 GÜVENLİK: Varsayılan olarak YALNIZCA localhost'a bağlanır.
                # prometheus_client'ın varsayılanı 0.0.0.0'dır ve bu endpoint
                # astra_futures_balance_usdt / astra_daily_pnl_usdt /
                # astra_drawdown_pct gibi hesap finansallarını HİÇ kimlik
                # doğrulaması olmadan yayınlar (dashboard'un aksine Basic Auth
                # seçeneği bile yok). Firewall'suz bir VPS'te bu, bakiyenin
                # herkese açık olması demektir.
                # Dışarıdan erişim gerekiyorsa reverse-proxy + auth kullanın.
                start_http_server(PROMETHEUS_PORT, addr=PROMETHEUS_ADDR)
                log.info(f"[PROM] HTTP server: http://{PROMETHEUS_ADDR}:{PROMETHEUS_PORT}/metrics")
                if PROMETHEUS_ADDR == "0.0.0.0":
                    log.critical(
                        f"[PROM] 🚨 Metrics endpoint TÜM ARAYÜZLERDE ve kimlik "
                        f"doğrulaması YOK (0.0.0.0:{PROMETHEUS_PORT}). Bakiye/PnL/"
                        f"drawdown verisi porta erişen herkese açık — firewall şart."
                    )
            except Exception as e:
                log.warning(f"[PROM] Server başlatılamadı: {e}")

    def heartbeat_guncelle(self):
        self.son_heartbeat.set(time.time())


# Singleton
_metrics_instance: Optional[AstraMetrics] = None

def get_metrics() -> AstraMetrics:
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = AstraMetrics()
        _metrics_instance.baslat()
    return _metrics_instance
