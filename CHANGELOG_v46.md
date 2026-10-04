# ASTRA v46.0 — DONMANIN GERÇEK KÖK NEDENİ: TELEGRAM + WS TIMEOUT

## Tarih: 2026-06-24 | Temel: v45.0

## Kullanıcı Gözlemleri ve Yanıtları

### 🔴 Sorun: Watchdog bazen 2051s (34 dk!) donuyor
v44'te global timeout ekledik AMA o sadece `requests` kütüphanesini
kapsıyordu. KEŞİF: İki ağ katmanı global timeout'tan ETKİLENMİYORDU:
1. **Telegram (run_polling)** → `requests` değil, `httpx` kullanıyor
2. **WebSocket** → kendi socket katmanını kullanıyor

Application.builder().token().build() HİÇ timeout içermiyordu. Ağ
yavaşken/koparsa getUpdates/sendMessage sonsuza kadar asılı kalıp ana
thread'i kilitliyordu → 34 dakikalık donmalar. /btc takılmasının da
asıl sebebi buydu.

### Düzeltme: Telegram + WebSocket Timeout
- **Telegram**: builder'a açık timeout'lar eklendi:
  connect=15s, read=20s, write=20s, pool=5s, get_updates_read=30s.
  Artık hiçbir Telegram ağ çağrısı sonsuza kadar beklemez.
  (python-telegram-bot 22.8'de doğrulandı, tüm metotlar mevcut)
- **WebSocket**: run_forever'a reconnect=5 eklendi (bağlantı kurma
  takılmasını önler). Eski sürümlerde yoksa güvenli fallback var.

Bu, "neden hep takılıyor" sorununun GERÇEK kök nedeniydi. v44 global
timeout requests'i çözmüştü ama Telegram/WS açıkta kalmıştı.

### ✅ "Bot kusursuz yeniden başlıyor" — bu NORMAL ve İYİ
v44'teki auto-restart çalışıyor. Donma olunca watchdog tetikleniyor,
bot yeniden başlıyor. Bu güvenlik ağı doğru çalışıyor. v46 ile artık
donma OLMAMASI beklenir (timeout'lar kapatıldı), yani restart da
azalacak.

### 📊 AI Memory Raporu Açıklaması (sorun DEĞİL)
Kullanıcı raporu:
- Sinyal Doğruluğu: 42 sinyal, 22 doğru (%52.4)
- Model Acc: %51.8, Trend DÜŞÜYOR
- Paper: 0 işlem

Bunlar BEKLENEN değerler:
- %52 doğruluk: v33 sızıntı düzeltmesi sonrası DÜRÜST değer. Eskiden
  sahte %85+ görüyorduk. Gerçek piyasa tahmininde %52-55 normaldir
  (rastgeleden iyi ama sihir değil). Bu, modelin dürüst olduğunu gösterir.
- "Trend DÜŞÜYOR": %52.6 → %51.8, çok küçük dalgalanma. Model sürekli
  yeniden eğitiliyor; kısa vadeli iniş-çıkış normaldir. Panik değil.
- Paper 0 işlem: Sinyaller üretiliyor ama paper trader'a işlem olarak
  geçmiyor olabilir — bu araştırılmalı (gerçek olası iyileştirme).

## Etkilenen Dosyalar
- `main.py` — Telegram builder timeout'ları
- `engines/websocket_manager.py` — WS reconnect timeout
- `config.py` — v46.0

## Test
- 79 dosya syntax temiz ✅
- 30/30 test geçti ✅
- Telegram builder timeout'ları doğrulandı (ptb 22.8) ✅
- WS reconnect güvenli fallback ile ✅

## Beklenti
v46 ile uzun donmalar (Telegram/WS kaynaklı) bitmeli. Watchdog
alarmları çok azalmalı. /btc artık en geç ~30s'de cevap vermeli
(ya sonuç ya "ağ yavaş" mesajı). Paper 0 işlem konusu bir sonraki
turda incelenebilir.
