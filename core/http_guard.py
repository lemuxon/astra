# =========================================================
# ASTRA v44.0 — GLOBAL HTTP TIMEOUT ZORLAMA
# Hiçbir ağ çağrısı sonsuza kadar bekleyemez.
# Bu modül, requests kütüphanesini sistem genelinde patch'ler:
# timeout belirtilmeyen HER istek otomatik bir tavan timeout alır.
#
# Sorun: Bir ağ çağrısı yanıt vermezse ve timeout'u yoksa, sonsuza
# kadar bekler → thread donar → watchdog alarmı → bot çöker.
# Çözüm: Global tavan. Takılan çağrı hangisi olursa olsun kesilir.
# =========================================================
import logging
import requests

log = logging.getLogger("ASTRA.HTTP")

# Tavan timeout (saniye). Hiçbir istek bundan uzun bekleyemez.
# (connect_timeout, read_timeout) — bağlantı 8s, yanıt 15s.
VARSAYILAN_TIMEOUT = (8, 15)

_patch_uygulandi = [False]


def global_timeout_uygula(connect: float = 8, read: float = 15):
    """requests kütüphanesini patch'le: timeout'suz istekleri engelle.
    Uygulama başında BİR KEZ çağrılır. Tüm requests.get/post/vb.
    çağrıları (timeout belirtmeseler bile) bu tavanı alır."""
    if _patch_uygulandi[0]:
        return
    tavan = (connect, read)

    # 1. Session.request'i sarmala (requests.get/post hepsi buradan geçer)
    _orijinal_request = requests.Session.request

    def _timeoutlu_request(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = tavan
        return _orijinal_request(self, method, url, **kwargs)

    requests.Session.request = _timeoutlu_request

    # 2. Modül seviyesi requests.api.request'i de sarmala (requests.get
    #    bazı yollarda doğrudan buraya gidebilir)
    _orijinal_api_request = requests.api.request

    def _timeoutlu_api_request(method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = tavan
        return _orijinal_api_request(method, url, **kwargs)

    requests.api.request = _timeoutlu_api_request

    _patch_uygulandi[0] = True
    log.info(f"[HTTP] Global timeout aktif: connect={connect}s read={read}s "
             f"(timeout'suz hiçbir istek artık sonsuza kadar bekleyemez)")


def patch_durumu() -> bool:
    """Global timeout patch'i uygulandı mı?"""
    return _patch_uygulandi[0]
