# =========================================================
# ASTRA v58 — PANEL EŞZAMANLILIĞI (K-53)
# Çalıştırma: python tests/test_panel_esszamanlilik.py
#
# NE KORUYOR:
#   Panel periyodik olarak DONUYORDU. Ölçüm (2026-09-06, 25 çift istek):
#
#     /saglik   (kilit ALMAZ, sabit 14 bayt) → 56.4s ve 58.3s
#     /api/state (kilit ALIR, JSON üretir)   → hep milisaniye
#
#   Bu ayrım kritikti: takılma KİLİT ÇEKİŞMESİ ya da handler gövdesi
#   olsaydı `/api/state` yavaşlardı. Yavaşlayan HİÇBİR İŞ YAPMAYAN uç
#   nokta oldu → sorun bağlantı/kuyruk seviyesinde.
#
#   Kök neden: `HTTPServer` aynı anda TEK bağlantı işler. Bir bağlantı
#   takılınca ardındaki her istek bekler (head-of-line blocking).
#   Tarayıcı paneli saniyede bir yokladığı için bu, panelin donması
#   demek.
#
#   Düzeltmeden sonra: 30 çift istekte (60 istek) 0 yavaşlama.
#
# ⚠️ DÜRÜST SINIR: bu düzeltme takılmanın KÖK NEDENİNİ çözmüyor
#   (hangi işlemin ~56s tuttuğu belirlenemedi). Yaptığı şey, tek bir
#   takılmanın DİĞER istekleri kilitlemesini engellemek.
#
# §4.1: Muhafızın yanına KONTROL testi var — "sunucuyu hiç başlatma"
#   davranışı da sınıf kontrolünü geçerdi.
# =========================================================
import sys, os, ast, socketserver, threading, time, json
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sunucu_sinif_adi():
    """AST: `dashboard_baslat` hangi sunucu sınıfını kuruyor?"""
    with open(os.path.join(KOK, "api", "dashboard.py"), encoding="utf-8") as fh:
        agac = ast.parse(fh.read())
    for d in ast.walk(agac):
        if not (isinstance(d, ast.FunctionDef) and d.name == "dashboard_baslat"):
            continue
        for n in ast.walk(d):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id.endswith("HTTPServer")):
                return n.func.id
    return None


# ─────────────────────────────────────────────
# 1. MUHAFIZ
# ─────────────────────────────────────────────
def test_sunucu_es_zamanli_sinif_kullaniyor():
    """Kurulan sınıf ThreadingMixIn içermeli — SEMANTİK kontrol.

    İsim araması zayıf olurdu; sınıfı gerçekten çözüp MRO'suna
    bakıyoruz.
    """
    ad = _sunucu_sinif_adi()
    assert ad is not None, "dashboard_baslat bir *HTTPServer kurmuyor"
    import api.dashboard as dash
    sinif = getattr(dash, ad, None)
    assert sinif is not None, f"'{ad}' api.dashboard'da çözülemedi"
    mro = [c.__name__ for c in sinif.__mro__]
    assert "ThreadingMixIn" in mro, (
        f"Sunucu sınıfı '{ad}' eşzamanlı DEĞİL (MRO: {mro}). Tek iş "
        f"parçacıklı sunucuda bir takılan bağlantı, ardındaki her "
        f"isteği bloke eder — panel donar.")


def test_daemon_threads_acik():
    """Sunucu thread'i ölürse yavrular süreci canlı tutmamalı (§5.2.1)."""
    with open(os.path.join(KOK, "api", "dashboard.py"), encoding="utf-8") as fh:
        kaynak = fh.read()
    assert "daemon_threads = True" in kaynak, (
        "daemon_threads ayarlanmamış — yavru thread'ler süreç çıkışını "
        "engelleyebilir")


def test_es_zamanli_sunucu_bloke_etmiyor():
    """DAVRANIŞSAL: yavaş bir istek, hızlı isteği BEKLETMEMELİ.

    Gerçek kanıt bu. Aynı sunucu sınıfıyla minik bir sunucu kurup
    kasten yavaş bir uç nokta ekliyoruz; ikinci (hızlı) istek yavaşın
    bitmesini BEKLEMEMELİ.
    """
    from http.server import BaseHTTPRequestHandler
    import api.dashboard as dash
    sinif = getattr(dash, _sunucu_sinif_adi())

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/yavas":
                time.sleep(3.0)
            govde = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(govde)))
            self.end_headers()
            self.wfile.write(govde)

        def log_message(self, *a):    # test çıktısını kirletme
            pass

    srv = sinif(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        time.sleep(0.2)
        yavas_bitti = []

        def yavas():
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/yavas", timeout=15).read()
            except Exception:
                pass
            yavas_bitti.append(time.time())

        th = threading.Thread(target=yavas, daemon=True); th.start()
        time.sleep(0.4)                     # yavaş istek başlasın
        t0 = time.time()
        urllib.request.urlopen(f"http://127.0.0.1:{port}/hizli", timeout=15).read()
        gecen = time.time() - t0
        assert gecen < 1.5, (
            f"Hızlı istek {gecen:.2f}s sürdü — yavaş isteğin bitmesini "
            f"BEKLEDİ. Sunucu eşzamanlı değil (head-of-line blocking).")
        th.join(timeout=10)
    finally:
        srv.shutdown(); srv.server_close()


# ─────────────────────────────────────────────
# 2. KONTROL TESTİ (§4.1)
# ─────────────────────────────────────────────
def test_kontrol_tek_isparcacikli_sunucu_GERCEKTEN_bloke_eder():
    """Ölçütün geçerliliği: tek iş parçacıklı sunucu bloke ETMELİ.

    Bu olmadan yukarıdaki test, ölçüt bozuksa da yeşil kalırdı —
    "her şey hızlı" diye yanlış güvence verirdi.
    """
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/yavas":
                time.sleep(3.0)
            govde = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(govde)))
            self.end_headers()
            self.wfile.write(govde)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        time.sleep(0.2)

        def yavas():
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/yavas", timeout=15).read()
            except Exception:
                pass

        th = threading.Thread(target=yavas, daemon=True); th.start()
        time.sleep(0.4)
        t0 = time.time()
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/hizli", timeout=15).read()
        except Exception:
            pass
        gecen = time.time() - t0
        assert gecen > 1.0, (
            f"Tek iş parçacıklı sunucuda hızlı istek {gecen:.2f}s sürdü — "
            f"bloke ETMEDİ. Ölçüt çalışmıyor, asıl test anlamsız.")
        th.join(timeout=10)
    finally:
        srv.shutdown(); srv.server_close()


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA PANEL EŞZAMANLILIĞI — {len(testler)} test")
    print(f"{'='*56}")
    basari, hata = 0, 0
    for t in testler:
        try:
            t()
            print(f"  [GEÇTİ]  {t.__name__}")
            basari += 1
        except AssertionError as e:
            print(f"  [HATA]   {t.__name__}")
            print(f"           → {str(e)[:95]}")
            hata += 1
        except Exception as e:
            print(f"  [ÇÖKTÜ]  {t.__name__}: {type(e).__name__}: {str(e)[:70]}")
            hata += 1
    print(f"{'='*56}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'='*56}\n")
    sys.exit(0 if hata == 0 else 1)
