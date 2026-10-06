# =========================================================
# ASTRA v58 — LOG'DA KİMLİK BİLGİSİ MASKELEME (K-108)
# =========================================================
# NEDEN VAR — ÖLÇÜLEN SIZINTI (2026-10-06 18:44, bot yeniden başlatılırken):
#
#   Telegram token'ı DÜZ METİN olarak 4 log dosyasına yazılmış bulundu
#   (astra.log, astra_onemli.log, bot_autostart.log ×2). İKİ ayrı yoldan:
#
#   1) core/telegram_gonderim.py — `requests` istisnasının metni URL'in
#      TAMAMINI içerir, URL'de de token var:
#        "401 Client Error: Unauthorized for url:
#         https://api.telegram.org/bot<TOKEN>/sendMessage"
#
#   2) main.py:3456 — python-telegram-bot'un `InvalidToken` istisnası
#      token'ı mesajın İÇİNE koyuyor:
#        "InvalidToken: The token `<TOKEN>` was rejected by the server"
#      Üstelik `exc_info=True` ile TRACEBACK da yazılıyor.
#
# ⚠️ SECURITY.md bunu AÇIKÇA güvenlik kusuru sayıyor: "Anything that could
#   leak credentials (.env values, API keys, Telegram tokens) into logs...".
#   Depo herkese açık; biri hata ayıklamak için log parçası paylaşırsa
#   token'ı da paylaşır.
#
# ➜ NEDEN TEK TEK YAMA DEĞİL: iki sızma yolu bulundu, üçüncüsü olmadığını
#   KANITLAYAMAM. Her `log.error(f"...{e}")` çağrısı aday. §5.1 gereği
#   "başka yol bilmiyorum" ≠ "başka yol yok". Bu yüzden maskeleme ÇIKTI
#   ANINDA, formatter seviyesinde yapılıyor: mesaj, argüman veya traceback
#   hangi yolla gelirse gelsin son metinden silinir.
#
# İKİ KATMANLI maskeleme BİLEREK:
#   1) .env'deki değeri doğrudan değiştir (kesin eşleşme)
#   2) Desenleri de yakala — token .env'dekinden FARKLI gelse bile
#      (eski token, kopyala-yapıştır hatası) sızmasın.
# =========================================================
import logging
import re

try:
    from config import BOT_TOKEN
except Exception:          # config yüklenemezse maskeleme yine çalışsın
    BOT_TOKEN = ""

# Telegram bot token'ı: <8-12 hane>:<35 civarı base64'e benzer>
# Hem URL içinde hem çıplak geçebilir, ikisini de yakala.
_DESENLER = (
    # URL biçimi — "bot" önekini koru, teşhis için hangi servis olduğu önemli
    (re.compile(r"(api\.telegram\.org/bot)[0-9]{5,}:[A-Za-z0-9_-]{20,}"),
     r"\1<BOT_TOKEN>"),
    # Çıplak biçim (InvalidToken mesajı gibi)
    (re.compile(r"\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b"),
     "<BOT_TOKEN>"),
)


def token_gizle(metin) -> str:
    """Log'a yazılacak metinden Telegram token'ını siler.

    Exception nesnesi de kabul eder (çağrı yerleri `{e}` biçiminde kullanıyor).
    Teşhis bilgisi (HTTP kodu, hata adı, servis adı) KORUNUR — yalnızca
    gizli değer çıkarılır.
    """
    s = str(metin)
    if BOT_TOKEN:
        s = s.replace(BOT_TOKEN, "<BOT_TOKEN>")
    for desen, yerine in _DESENLER:
        s = desen.sub(yerine, s)
    return s


class GizleyenFormatter(logging.Formatter):
    """Biçimlendirilmiş SON metni maskeler — traceback dahil.

    Filter DEĞİL, Formatter olarak yazıldı: `record.exc_text` filtre
    çalıştığı anda henüz None'dır, traceback formatlama sırasında üretilir.
    Filtreyle yapsaydık traceback içindeki token KAÇARDI.
    """

    def format(self, record):
        return token_gizle(super().format(record))


def kur(kok_logger=None) -> int:
    """Mevcut tüm handler'ların formatter'ını maskeleyen sürümle sarar.

    Geriye sarılan handler sayısını döndürür (0 ise hiçbir şey korunmadı —
    çağıran bunu kontrol edebilir).
    """
    kok = kok_logger if kok_logger is not None else logging.getLogger()
    sarilan = 0
    for h in kok.handlers:
        mevcut = h.formatter
        if isinstance(mevcut, GizleyenFormatter):
            continue                      # iki kez sarmayı önle
        desen = getattr(mevcut, "_fmt", None) or "%(message)s"
        tarih = getattr(mevcut, "datefmt", None)
        h.setFormatter(GizleyenFormatter(desen, tarih))
        sarilan += 1
    return sarilan
