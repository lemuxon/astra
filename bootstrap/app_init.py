# =========================================================
# ASTRA v30.0 — BOOTSTRAP / APP INIT
# Tüm singleton'lar burada başlatılır.
# main.py God Object yerine bu kullanılır.
# =========================================================
import logging, os
log = logging.getLogger("ASTRA.BOOTSTRAP")

def init_core(telegram_fn=None) -> dict:
    """Tüm engine singleton'larını başlatır."""
    import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from config import BALANCE
    from engines.event_bus        import get_bus
    from engines.risk_manager     import RiskManager
    from engines.strategy_engine  import StratejiEngine
    from engines.paper_trading    import PaperTrader
    from engines.kill_switch      import get_kill_switch
    from engines.adaptive_sizing  import get_adaptive_sizing
    from engines.order_reconciler import get_order_reconciler
    from engines.watchdog         import get_watchdog
    from engines.shadow_model     import get_shadow_manager
    from engines.edge_analytics   import get_edge_analytics
    from risk.volatility_circuit_breaker import get_circuit_breaker
    from risk.correlation_engine  import get_correlation_engine
    from engines.position_state   import get_state_manager
    from execution.execution_engine import get_execution_engine
    from engines.order_engine     import get_order_engine
    from engines.exchange_failover import get_failover
    from engines.monte_carlo      import get_mc
    from monitoring.prometheus_metrics import get_metrics
    from analytics.risk_analytics import get_analytics
    from simulation.exchange_simulator import get_simulator
    from execution.state_audit    import get_audit
    from execution.failsafe_liquidation import get_failsafe_guard
    from engines.trade_journal    import get_journal

    c = {}
    c["bus"]             = get_bus()
    c["risk_manager"]    = RiskManager(BALANCE)
    c["strateji_engine"] = StratejiEngine()
    c["paper_trader"]    = PaperTrader(BALANCE)
    c["kill_switch"]     = get_kill_switch(telegram_fn)
    c["circuit_breaker"] = get_circuit_breaker(telegram_fn)
    c["correlation"]     = get_correlation_engine()
    c["adaptive_sizing"] = get_adaptive_sizing()
    c["shadow_manager"]  = get_shadow_manager()
    c["edge_analytics"]  = get_edge_analytics()
    c["state_manager"]   = get_state_manager(auto_sync=False)
    c["order_engine"]    = get_order_engine()
    c["failover"]        = get_failover()
    c["mc_risk"]         = get_mc()
    c["metrics"]         = get_metrics()
    c["analytics"]       = get_analytics()
    c["simulator"]       = get_simulator()
    c["exec_engine"]     = get_execution_engine(c["risk_manager"], c["state_manager"])
    c["state_audit"]     = get_audit()
    c["failsafe"]        = get_failsafe_guard()
    c["journal"]         = get_journal()
    c["order_reconciler"]= get_order_reconciler(c["state_manager"])
    c["watchdog"]        = get_watchdog(telegram_fn)
    log.info(f"[BOOTSTRAP] {len(c)} component başlatıldı")
    return c

def init_dashboard():
    from config import DASHBOARD_ENABLED
    if not DASHBOARD_ENABLED:
        return lambda **kw: None, lambda *a, **kw: None
    try:
        from api.dashboard import dashboard_baslat, state_guncelle, pozisyon_kapandi_bildir
        dashboard_baslat()
        return state_guncelle, pozisyon_kapandi_bildir
    except Exception as e:
        log.warning(f"[BOOTSTRAP] Dashboard: {e}")
        return lambda **kw: None, lambda *a, **kw: None

def init_websocket(coins, disconnect_cb=None):
    from config import WS_ENABLED
    if not WS_ENABLED:
        return None
    try:
        from engines.websocket_manager import ws_baslat, son_fiyat
        ws_baslat(coins, spot=False, disconnect_callback=disconnect_cb)
        return son_fiyat
    except Exception as e:
        log.warning(f"[BOOTSTRAP] WebSocket: {e}")
        return None

def start_background(components: dict):
    try: components["order_reconciler"].start()
    except Exception as e: log.warning(f"[BOOTSTRAP] Reconciler: {e}")
    # v30: audit + failsafe + order_engine + failover artık fabrika otomatik başlatmıyor
    try: components["state_audit"].start()
    except Exception as e: log.warning(f"[BOOTSTRAP] Audit: {e}")
    try: components["failsafe"].start()
    except Exception as e: log.warning(f"[BOOTSTRAP] Failsafe: {e}")
    try: components["order_engine"].start()
    except Exception as e: log.warning(f"[BOOTSTRAP] OrderEngine: {e}")
    try: components["failover"].start()
    except Exception as e: log.warning(f"[BOOTSTRAP] Failover: {e}")
    log.info("[BOOTSTRAP] Arka plan servisleri hazır")
