# =========================================================
# ASTRA v56 — TELEGRAM GÖNDERİM KATMANI
# =========================================================
# main.py modülerleştirmesinin 1. adımı.
#
# Bu modül main.py'dan AYNEN taşındı; davranış değişikliği YOKTUR.
# Buraya taşınma sebebi:
#   • Saf ve kendi kendine yeterli (yalnızca config + requests'e bağlı)
#   • Zaten test edilmişti (mesaj bölme, rate limit)
#   • main.py'ın trading mantığıyla hiç ilgisi yok
#
# main.py bu isimleri import edip yeniden dışa verir; mevcut çağrı
# noktalarının hiçbiri değişmez.
# =========================================================
import os
import time
import logging
import threading
import requests

import sys; sys.path.append("..")
from config import BOT_TOKEN, CHAT_ID

log = logging.getLogger("ASTRA")

TELEGRAM_URL   = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
TELEGRAM_PHOTO = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

# ── Rate limiter durumu ──────────────────────────────────
_tg_lock       = threading.Lock()
_tg_son_mesaj: dict = {}   # {anahtar: son_mesaj_ilk_100_karakter}
_tg_son_zaman: dict = {}   # {anahtar: timestamp}
try:
    from config import TG_MIN_ARALIK_SINYAL as _TG_MIN_ARALIK
except ImportError:
    _TG_MIN_ARALIK = 300   # 5 dakika varsayılan

# ── Uzunluk sınırı ───────────────────────────────────────
TG_MAX_UZUNLUK      = 4096   # Telegram Bot API sert sınırı
_TG_GUVENLI_UZUNLUK = 3900   # HTML etiketleri + emoji payı için tampon


def _tg_parcala(metin: str, limit: int = _TG_GUVENLI_UZUNLUK) -> list:
    """v56: Uzun mesajı Telegram sınırının altında parçalara böler.

    Telegram 4096 karakteri aşan mesajı REDDEDER
    (BadRequest: Message is too long). Kod tabanında 60 gönderim noktasının
    HİÇBİRİ uzunluk kontrolü yapmıyordu; veriye göre büyüyen raporlar
    (/neden, /registry, /journal, /ai_rapor, çok coinli özetler) üretimde
    sessizce başarısız oluyordu — kullanıcı raporu HİÇ alamıyordu.

    Mümkün olduğunca satır sınırından böler ki HTML etiketleri ve tablolar
    ortadan kesilmesin.
    """
    if metin is None:
        return [""]
    metin = str(metin)
    if len(metin) <= limit:
        return [metin]

    parcalar, mevcut = [], ""
    for satir in metin.split("\n"):
        # Tek satır bile limitten uzunsa sert böl
        while len(satir) > limit:
            if mevcut:
                parcalar.append(mevcut); mevcut = ""
            parcalar.append(satir[:limit])
            satir = satir[limit:]
        if len(mevcut) + len(satir) + 1 > limit:
            parcalar.append(mevcut); mevcut = satir
        else:
            mevcut = satir if not mevcut else mevcut + "\n" + satir
    if mevcut:
        parcalar.append(mevcut)
    return parcalar or [""]


async def _yanitla(u, metin: str, **kw):
    """v56: reply_text yerine kullanılan güvenli sarmalayıcı.

    - 4096 sınırını aşan mesajı otomatik parçalar
    - Gönderim hatasında komutu çökertmez, loglar
    """
    try:
        parcalar = _tg_parcala(metin)
        for i, p in enumerate(parcalar):
            if len(parcalar) > 1:
                p = f"{p}\n\n<i>({i+1}/{len(parcalar)})</i>" if kw.get("parse_mode") == "HTML" \
                    else f"{p}\n\n({i+1}/{len(parcalar)})"
            await u.message.reply_text(p, **kw)
    except Exception as e:
        log.error(f"[TG] Yanıt gönderilemedi: {type(e).__name__}: {e}")


def telegram_gonder(mesaj, chat_id=CHAT_ID, tip="genel", force=False):
    """Rate-limited Telegram mesajı. Aynı 'tip' için _TG_MIN_ARALIK bekler."""
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return False
    with _tg_lock:
        simdi = time.time()
        # Memory leak koruması: eski kayıtları temizle (1 saatlik)
        if len(_tg_son_zaman) > 200:
            eskiler = [k for k, v in _tg_son_zaman.items() if simdi - v > 3600]
            for k in eskiler:
                _tg_son_zaman.pop(k, None); _tg_son_mesaj.pop(k, None)
        anahtar = f"{tip}_{chat_id}"
        gecen = simdi - _tg_son_zaman.get(anahtar, 0)
        if not force and gecen < _TG_MIN_ARALIK:
            log.debug(f"[TG RATE] {tip} atlandı ({gecen:.0f}s < {_TG_MIN_ARALIK}s)")
            return False
        # Birebir aynı mesajı tekrar gönderme
        # v58 (K-44): 4h'de analiz fiyatı barlar ARASINDA aynı kalıyor
        # (aynı kapanmış bar tekrar tekrar değerlendiriliyor), dolayısıyla
        # mesajın ilk 100 karakteri de aynı oluyor ve bu koruma sürekli
        # devreye giriyor. İlk gönderim geçer, sonrakiler bastırılır —
        # istenen davranış bu, ama SESSİZ olmamalı: debug yerine bilgi
        # düzeyinde saymıyoruz (gürültü olur), yalnızca ilk bastırmayı
        # anlaşılır kılıyoruz.
        if not force and _tg_son_mesaj.get(anahtar) == mesaj[:100]:
            log.debug(f"[TG RATE] {tip} duplicate atlandı "
                      f"(4h'de aynı bar → aynı mesaj, beklenen)")
            return False
        _tg_son_zaman[anahtar] = simdi
        _tg_son_mesaj[anahtar] = mesaj[:100]

    # v56: 4096 karakter sınırı. Eskiden uzun mesaj Telegram tarafından
    # REDDEDİLİYOR (400 Bad Request: message is too long) ve
    # raise_for_status() ile hata loglanıp mesaj TAMAMEN kayboluyordu.
    parcalar = _tg_parcala(mesaj)
    tum_basarili = True
    for i, parca in enumerate(parcalar):
        govde = parca if len(parcalar) == 1 else f"{parca}\n\n<i>({i+1}/{len(parcalar)})</i>"
        try:
            r = requests.post(TELEGRAM_URL,
                              data={"chat_id": chat_id, "text": govde,
                                    "parse_mode": "HTML"},
                              timeout=10)
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            log.error(f"Telegram gönderme hatası (parça {i+1}/{len(parcalar)}): {e}")
            tum_basarili = False
    # v58 (K-44): BAŞARILI GÖNDERİM DE LOGLANIR.
    # Öncesinde yalnızca hata ve rate-limit (debug) yazılıyordu; başarı
    # sessizdi. Sonuç: "Telegram'a mesaj gitti mi?" sorusunun logdan
    # cevabı YOKTU — K-40 teşhisinde tam bu duvara çarpıldı.
    # §5.2'nin karşılığı: yapılanı da görünür kıl, yalnızca yapılamayanı değil.
    if tum_basarili:
        log.info(f"[TG] gönderildi: tip={tip} ({len(parcalar)} parça, "
                 f"{len(mesaj)} karakter)")
    return tum_basarili


def telegram_grafik_gonder(yol, baslik="", chat_id=CHAT_ID):
    """Grafik gönderimi — sinyal ile aynı rate limit kullanır."""
    if not BOT_TOKEN or len(BOT_TOKEN) < 20 or not os.path.exists(yol):
        return False
    # Rate limit: grafiği de sinyal tipiyle kontrol et
    sembol = baslik.split(" | ")[0] if " | " in baslik else "grafik"
    with _tg_lock:
        simdi = time.time()
        anahtar = f"grafik_{sembol}_{chat_id}"
        gecen = simdi - _tg_son_zaman.get(anahtar, 0)
        if gecen < _TG_MIN_ARALIK:
            log.debug(f"[TG RATE] Grafik atlandı ({gecen:.0f}s < {_TG_MIN_ARALIK}s)")
            return False
        _tg_son_zaman[anahtar] = simdi
    try:
        with open(yol, "rb") as f:
            r = requests.post(TELEGRAM_PHOTO,
                              data={"chat_id": chat_id, "caption": baslik},
                              files={"photo": f}, timeout=30)
        r.raise_for_status()
        # v58 (K-44): grafik gönderimi de görünür olsun
        log.info(f"[TG] grafik gönderildi: {os.path.basename(yol)} "
                 f"({os.path.getsize(yol)//1024} KB) — {baslik[:60]}")
        return True
    except requests.exceptions.RequestException as e:
        log.error(f"Grafik gönderme hatası: {e}"); return False
