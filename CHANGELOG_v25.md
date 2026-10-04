# ASTRA v25.0 — GÖZLEMLENEBİLİRLİK: GELİŞMİŞ CANLI DASHBOARD

## Tarih: 2026-05-29 | Temel: v24.0

Bu sürümün odağı: **tek bir tarayıcı ekranında botun tüm zekasını canlı
görebilmek.** v18-v24 arasında onlarca güçlü motor ekledik (Kelly,
performans metrikleri, CVD, HMM, online learning, MVO portföy, A/B test,
model registry, smart execution, dayanıklılık kapısı) — ama bunların çoğu
yalnızca Telegram komutlarıyla parça parça görülebiliyordu. Artık hepsi
tek dashboard'da, 5 saniyede bir otomatik yenilenerek.

Dashboard zaten vardı (`api/dashboard.py`, http.server tabanlı) ama yalnızca
temel verileri (bakiye, pozisyon, PnL, kill switch) gösteriyordu. Bu sürümde
yeni motorların tamamı eklendi.

---

## 🧠 Yeni: "Sistem Zekası" Paneli (6 kart)

Dashboard'un altına 6 yeni canlı kart eklendi:

### 📊 Performans
Sharpe, Sortino, Calmar, Omega oranları + Max Drawdown.
Risk-adjusted getiriyi tek bakışta gösterir.

### 🛡️ Dayanıklılık Kapısı (v24)
Her coin'in validator kararı: ONAY / RED + 100 üzerinden skor.
RED alan coin'de yeni pozisyon açılmadığını görsel olarak teyit eder.

### ⚖️ Portföy Dağılımı (v20 MVO)
Mean-Variance optimizasyonunun coin başına ağırlıkları, mini bar grafiklerle.
Yöntem (MVO/Risk Parity) ve portföy Sharpe'ı.

### 🧬 Öğrenme & Kelly
Online learning eğitim sayısı + drift uyarıları (v20) ve per-coin
canlı Kelly fraksiyonu + win-rate (v18).

### 🧪 A/B Test (v21)
İki strateji varyantının canlı karşılaştırması: işlem sayısı, win-rate,
ortalama PnL + istatistiksel anlamlılık (Mann-Whitney p-değeri) ve kazanan.

### ⚡ Execution & Model
Smart execution dağılımı (Market/TWAP/VWAP/Iceberg, v22) ve
model registry versiyonları + canlı PnL (v22).

---

## 🔧 Coin Kartlarına Eklenenler
- **🛡️ / ⛔ rozeti**: Coin'in dayanıklılık kapısı durumu (v24).
- **⚠CVD göstergesi**: CVD divergence (sahte kırılım uyarısı, v18) tespit
  edildiğinde kart üzerinde turuncu uyarı.

---

## ⚙️ Teknik Detaylar

### Backend (`main.py`)
- **Yeni: `_gelismis_state_topla()`** — Her panel güncellemesinde tüm yeni
  motorların durumunu toplar. Her motor opsiyonel; yoksa o panel sessizce
  "veri bekleniyor" gösterir, hata vermez.
- Panel güncelleme döngüsünde `state_guncelle(..., **_gelismis)` ile beslenir.

### Frontend (`api/dashboard.py`)
- `_state` sözlüğüne 8 yeni alan eklendi (performans, validator, portfolio,
  online_learning, model_registry, smart_exec, ab_test, kelly).
- Yeni CSS: `.intel-section`, `.intel-card`, `.mini-bar`, `.pill` (responsive).
- Yeni JS: `renderIntel(s)` — 6 paneli her döngüde yeniden çizer.
- Mobil uyumlu: 3 kolon → 2 kolon (tablet) → 1 kolon (telefon).

---

## 🚀 Kullanım
Bot çalışırken tarayıcında aç:
```
http://localhost:8080
```
Port `.env`'den değiştirilebilir: `DASHBOARD_PORT=8080`

Dashboard her 5 saniyede bir otomatik yenilenir. Hiçbir ek kurulum
gerektirmez — Python'un kendi `http.server`'ını kullanır (ek paket yok).

---

## 🐛 Bu turda düzeltilen
- Dashboard başlık/log mesajları v15'ten v25'e güncellendi.
- Önizleme üretimi sırasında `fetch` bypass mekanizması test edildi —
  `dashboard_onizleme.html` ile statik görsel doğrulama yapılabiliyor.

## Davranış Notu
- Yeni paneller veri biriktikçe dolar. İlk çalıştırmada çoğu "veri
  bekleniyor" gösterir; işlemler ve eğitim ilerledikçe canlanır.
- Dashboard salt-okunur bir gözlem aracıdır; işlem kararlarını etkilemez.
