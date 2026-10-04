#!/usr/bin/env python3
# =========================================================
# ASTRA — TELEGRAM CHAT_ID BULUCU
# =========================================================
# Kullanım:
#   1) .env dosyasına BOT_TOKEN'ı gir (@BotFather'dan alınır)
#   2) Telegram'da botuna herhangi bir mesaj yaz (örn. "merhaba")
#   3) python telegram_chat_id_bul.py
#
# Script CHAT_ID'ni bulur ve .env'e nasıl ekleyeceğini söyler.
# Hiçbir şeyi otomatik yazmaz — kararı sen verirsin.
# =========================================================
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
except ImportError:
    print("❌ requests kurulu değil: pip install requests")
    sys.exit(1)

try:
    from config import BOT_TOKEN, CHAT_ID
except Exception as e:
    print(f"❌ config.py okunamadı: {e}")
    sys.exit(1)


def main():
    print("=" * 58)
    print("  TELEGRAM CHAT_ID BULUCU")
    print("=" * 58)

    if not BOT_TOKEN:
        print("\n❌ BOT_TOKEN boş.\n")
        print("   1) Telegram'da @BotFather'a yaz")
        print("   2) /newbot  → bot adı ve kullanıcı adı ver")
        print("   3) Verdiği token'ı .env dosyasındaki BOT_TOKEN= satırına yapıştır")
        print("   4) Bu scripti tekrar çalıştır\n")
        sys.exit(1)

    print(f"\n  BOT_TOKEN : tanımlı ({len(BOT_TOKEN)} karakter)")
    print(f"  CHAT_ID   : {CHAT_ID or '(boş — bulunacak)'}")

    # 1) Token geçerli mi?
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10)
        d = r.json()
    except Exception as e:
        print(f"\n❌ Telegram'a bağlanılamadı: {type(e).__name__}: {e}")
        sys.exit(1)

    if not d.get("ok"):
        print(f"\n❌ TOKEN GEÇERSİZ: {d.get('description')}")
        print("   @BotFather'dan /mybots → token'ı kontrol et veya /revoke ile yenile.")
        sys.exit(1)

    bot = d["result"]
    print(f"\n  ✅ Bot doğrulandı: @{bot.get('username')} ({bot.get('first_name')})")

    # 2) Gelen mesajlardan chat_id çıkar
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                         timeout=10)
        upd = r.json()
    except Exception as e:
        print(f"\n❌ getUpdates başarısız: {e}")
        sys.exit(1)

    sonuclar = upd.get("result", []) if upd.get("ok") else []
    bulunanlar = {}
    for u in sonuclar:
        msg = (u.get("message") or u.get("edited_message")
               or u.get("channel_post") or {})
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        ad = (chat.get("username") or chat.get("title")
              or f"{chat.get('first_name','')} {chat.get('last_name','')}".strip())
        bulunanlar[cid] = (chat.get("type", "?"), ad or "(isimsiz)")

    if not bulunanlar:
        print("\n  ⚠️  Hiç mesaj bulunamadı.\n")
        print(f"   YAP: Telegram'da @{bot.get('username')} botunu aç,")
        print("        /start yaz veya herhangi bir mesaj gönder,")
        print("        sonra bu scripti TEKRAR çalıştır.\n")
        print("   NOT: Bot daha önce çalışıyorduysa mesajları o tüketmiş")
        print("        olabilir. Botu durdur, mesaj at, scripti çalıştır.")
        sys.exit(1)

    print(f"\n  Bulunan sohbet(ler):")
    for cid, (tip, ad) in bulunanlar.items():
        print(f"     CHAT_ID = {cid}   [{tip}]  {ad}")

    if len(bulunanlar) == 1:
        cid = list(bulunanlar)[0]
        print("\n" + "=" * 58)
        if str(CHAT_ID) == str(cid):
            print("  ✅ .env'deki CHAT_ID zaten DOĞRU — değişiklik gerekmiyor.")
        else:
            print("  YAPILACAK: .env dosyasında şu satırı güncelle:\n")
            print(f"      CHAT_ID={cid}\n")
            print("  Sonra botu yeniden başlat.")
        print("=" * 58)
    else:
        print("\n  Birden fazla sohbet var. Kendi kişisel sohbetini seç")
        print("  ([private] tipinde olan) ve .env'e onu yaz.")

    # 3) Yetkilendirme uyarısı
    if not CHAT_ID:
        print("\n  🚨 UYARI: CHAT_ID şu an BOŞ.")
        print("     Bu haldeyken komut yetkilendirmesi ÇALIŞMAZ —")
        print("     token'ı bilen herkes /fkapat gibi komutları kullanabilir.")
        print("     Gerçek para ile çalışmadan önce MUTLAKA doldur.")


if __name__ == "__main__":
    main()
