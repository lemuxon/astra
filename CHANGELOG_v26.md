# ASTRA v26.0 — ÇOKLU BORSA FİYAT DOĞRULAMA + ARBİTRAJ SİNYALİ

## Tarih: 2026-05-29 | Temel: v25.0

Bu sürüm botun "tek borsaya körü körüne güvenme" zaafını kapatır.
Artık her işlem öncesi Binance fiyatı, Bybit ve OKX ile çapraz
doğrulanır. İki işlevi var: **güvenlik** (manipülasyon/hatalı fiyat
vetosu) ve **fırsat** (arbitraj yön sinyali).

Not: Mevcut `exchange_failover` yalnızca Binance'in kendi yedek
URL'leri arasında geçiş yapıyordu — gerçek çoklu-borsa değildi.
v26 gerçek bağımsız borsa karşılaştırması ekler.

---

## 🌐 Yeni Modül: `data/multi_exchange.py`

Bybit ve OKX'in **public ticker** API'lerinden fiyat çeker
(API anahtarı gerekmez, harici kütüphane yok — sadece `requests`).

### 1. Fiyat Doğrulama (güvenlik) 🛡️
Binance fiyatı, üç borsanın medyanından `MULTIEX_MAX_SAPMA_PCT`
(varsayılan %1) fazla saparsa → **işlem VETO edilir.**

Bu şunlara karşı korur:
- Tek borsada anlık fiyat manipülasyonu / wick
- Hatalı/gecikmiş veri akışı
- Likidite boşluğunda oluşan sahte fiyatlar

**Güvenli davranış:** Diğer borsalar erişilemezse (tek kaynak),
veto YAPILMAZ — bot durmaz, sadece doğrulama atlanır.

### 2. Arbitraj Yön Sinyali (fırsat) 📈
Diğer borsalar Binance'ten `MULTIEX_ARBITRAJ_ESIK_PCT` (varsayılan
%0.15) fazla saparsa, bu kısa vadeli yön sinyali olarak kullanılır.
Mantık: bir borsada fiyat önce hareket eder, diğerleri takip eder.

**Doğrudan arbitraj DEĞİL** — momentum öncülü olarak pozisyon
boyutunu ayarlar:
- Arbitraj yönü işlem yönüyle **çelişiyorsa** → pozisyon %40 küçülür
- Arbitraj yönü işlem yönünü **teyit ediyorsa** → pozisyon max %15 artar

---

## 🔌 Entegrasyon (main.py)

- **`_execution_isle`**: `yon` belirlendikten hemen sonra çoklu borsa
  doğrulaması çalışır. Güvenilmezse `return` (pozisyon açılmaz).
- Arbitraj çelişki/teyit bilgisi pozisyon boyutu hesabına girer.
- Cache (varsayılan 3sn): Paralel coin analizinde her coin için
  saniyede bir kez gerçek API çağrısı (gereksiz tekrar yok).

---

## 📱 Yeni: `/multiex [coin]` Telegram Komutu
- Veto / arbitraj istatistikleri + Bybit/OKX erişim başarı oranı.
- İstenen coin için canlı 3-borsa fiyat karşılaştırması ve sapma.

## 📊 Dashboard'a Eklendi (v25 üzerine)
- "Execution & Model" paneline çoklu borsa bölümü: veto sayısı +
  arbitraj LONG/SHORT sayıları.

---

## ⚙️ Yeni config Anahtarları (.env)
```
MULTIEX_ENABLED=true              # Çoklu borsa doğrulama aç/kapa
MULTIEX_MAX_SAPMA_PCT=1.0         # Bu %'den fazla sapma → veto
MULTIEX_ARBITRAJ_ESIK_PCT=0.15    # Bu %'den fazla fark → arbitraj sinyali
MULTIEX_CACHE_TTL=3.0             # Fiyat cache süresi (saniye)
```

---

## 🧪 Test Sonuçları (fonksiyonel doğrulama)
| Senaryo | Beklenen | Sonuç |
|---------|----------|-------|
| Uyumlu fiyatlar | güvenilir | ✅ |
| Binance %2.3 sapma | VETO | ✅ 🛡️ |
| Diğer borsalar yukarı | LONG arbitraj | ✅ 📈 |
| Tek kaynak (diğerleri yok) | veto yok | ✅ |

---

## Davranış Notu
- İnternet erişimi gerektirir (Bybit/OKX public API'leri). Erişim
  yoksa bot çalışmaya devam eder, doğrulama sessizce atlanır.
- Bu modül **salt fiyat okuma** yapar — Bybit/OKX'te işlem AÇMAZ.
  İşlemler hâlâ yalnızca Binance Futures'ta gerçekleşir.
- Coğrafi kısıtlama: Bazı bölgelerde OKX/Bybit API'leri engelli
  olabilir; o durumda o borsa otomatik atlanır, kalan borsalarla devam.
