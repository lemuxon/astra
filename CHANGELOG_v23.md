# ASTRA v23.0 — KARARLILIK & HATA DÜZELTME TURU

## Tarih: 2026-05-29 | Temel: v22.0

Bu sürüm yeni özellik eklemez; v18–v22 arasında eklenen modüllerin
birbiriyle ve mevcut sistemle etkileşiminde oluşabilecek **gerçek ve
potansiyel hataları** kapatır. Özellikle v20'de gelen **async paralel
döngü** birçok thread-safety riski doğurmuştu.

---

## 🔴 Eşzamanlılık (Concurrency) — En Kritik Grup

Async paralel döngüde (`asyncio.gather`) tüm coinler aynı anda thread'lerde
analiz ediliyor. Aşağıdakiler ancak bu paralel ortamda ortaya çıkardı:

1. **Keras/TF thread-safe değil**
   TFT ve LSTM inference paralel thread'lerden çağrılıyordu → segfault/bozuk
   tahmin riski. `engines/model_engine.py`'ye global `_tf_lock` eklendi;
   tüm `model.predict` çağrıları serialize edildi.

2. **Korumasız paylaşımlı dict iterasyonu**
   Portfolio getiri güncellemesi `_son_analizler`'ı kilitsiz dolaşıyordu;
   paralel yazım "dictionary changed size during iteration" hatası
   doğurabilirdi. Artık `_son_analizler_lock` altında snapshot alınıyor.

3. **On-chain cache yarışı**
   `data/onchain_data.py` cache'i kilitsizdi → `_cache_lock` eklendi.

4. **Rollback dosya yarışı**
   Model rollback `shutil.copy2` ile canlı dosyanın üzerine yazarken paralel
   `model_yukle` yarı-yazılmış pickle okuyabilirdi. Artık temp dosya + atomik
   `os.replace` kullanılıyor.

---

## 🟠 Mantık / Doğruluk Hataları

5. **A/B testi fiilen çalışmıyordu**
   `dongu if 'dongu' in dir() else 0` ifadesi `coin_analiz` içinde her zaman
   0 dönüyordu → tüm işlemler "A" varyantına yazılıyordu. Global
   `_global_dongu_sayaci` ile düzeltildi (her döngü başında senkronize edilir).

6. **MVO optimizatörüne bozuk veri**
   Getiri serisi log-return tutuyordu ama bir sonraki getiriyi hesaplarken
   son log-return değeri **fiyat sanılıyordu**. Artık son fiyat ayrı
   `_portfolio_son_fiyat` sözlüğünde tutuluyor.

7. **PnL çift sayımı**
   `futures_pozisyon_kapat` hem `pnl_guncelle` çağırıyor hem de
   `POSITION_CLOSED` event'ini yayınlıyordu; event'i dinleyen
   `_on_position_closed` tekrar `pnl_guncelle` çağırıyordu. Engine'deki
   doğrudan çağrı kaldırıldı — güncelleme tek noktadan (event handler).

8. **İnce event payload'u**
   `_on_position_closed` event'te olmayan alanları (`ab_varyant`,
   `risk_usdt`, `model_adi`) okuyordu → Kelly R:R hep 1, A/B hep "A",
   registry hiç güncellenmiyordu. Artık eksik alanlar son analiz cache'inden
   tamamlanıyor; gerçek R:R için giriş anında SL mesafesi cache'e yazılıyor.

9. **Online learner accuracy sızıntısı**
   Accuracy `learn_one`'dan **sonra** ölçülüyordu (model etiketi görmüştü).
   Predict-before-learn sırasına çevrildi. Ayrıca blend artık bayat cache
   yerine güncel bar feature'larını kullanıyor.

---

## 🟡 Kaynak / Çalışma Zamanı

10. **Chandelier state sızıntısı + bayat stop**
    `_chandelier_state` / `_tp1_tamamlandi` pozisyon kapanınca temizlenmiyordu;
    aynı `sembol_yon` ile açılan yeni pozisyon eski trailing stop'u miras
    alıyordu (tehlikeli) ve sözlük sınırsız büyüyordu. `_pozisyon_state_temizle`
    eklenip kapanışta çağrılıyor.

11. **TFT wrapper 200× yavaş**
    `predict_proba` her satır için ayrı `model.predict` çağırıyordu. Batch
    inference'a çevrildi (tek tensör, `batch_size=256`).

12. **TWAP dilimleri duplicate olarak engelleniyordu**
    Her dilim `futures_market_ac` çağırıyor, ikinci dilim "açık pozisyon var"
    / cooldown nedeniyle reddediliyordu. `_ic_slice` parametresi eklendi:
    ilk dilim normal, sonrakiler duplicate kontrolünü atlıyor. Dilim
    `min_notional` altındaysa sessizce atlanıyor.

13. **TWAP sırasında SL gecikmesi**
    Çok-saniyeli execution SL yerleşimini geciktiriyordu. Dilim aralığı
    3.0→1.5sn düşürüldü; `TWAP_MAX_SURE_SN=8.0` toplam süre tavanı eklendi.

14. **Smart-exec emrinde yanlış slippage kapatması**
    TWAP ortalama fiyatı, işlem öncesi anlık fiyatla karşılaştırılıp
    `MAX_SLIPPAGE_PCT` aşılınca doğru dolan pozisyon hemen kapatılıyordu.
    Smart-exec emirleri için bu otomatik kapatma atlanıyor.

15. **RL ortamı hataları**
    `self.T = len(fiyatlar)` → tanımsız isim (`NameError`); düzeltildi.
    Fiyat/feature uzunluk uyumsuzluğu (feature_olustur NaN satır düşürür)
    hizalanıyor; NaN/inf temizliği eklendi.

16. **MVO NaN ağırlık koruması**
    Singular kovaryans matrisi NaN ağırlık üretebiliyordu; sonlu-değer ve
    pozitif-toplam kontrolü eklendi (NaN → Risk Parity fallback).

17. **On-chain gereksiz tekrar API çağrısı**
    Coingecko `/global` tüm coinler için aynı; per-symbol cache 5 özdeş
    çağrı yapıyordu. Tek `netflow_GLOBAL` cache anahtarı kullanılıyor.

18. **Eski yorum bozukluğu (v17'den beri)**
    `_ogrenme_metrikleri` global'inin yorumu bir sed işleminde bozulmuştu;
    temizlendi.

---

## Etkilenen Dosyalar
| Dosya | Düzeltme No |
|-------|-------------|
| `main.py` | 2, 5, 6, 7, 8, 9, 18 |
| `engines/model_engine.py` | 1, 11 |
| `engines/futures_trade_engine.py` | 7, 10 |
| `engines/online_learner.py` | 9 |
| `engines/model_registry.py` | 4 |
| `execution/execution_engine.py` | 14 |
| `execution/smart_execution.py` | 12, 13 |
| `data/binance_futures_client.py` | 12 |
| `data/onchain_data.py` | 3, 17 |
| `analytics/portfolio_optimizer.py` | 16 |
| `simulation/rl_environment.py` | 15 |
| `config.py` | 13 (TWAP_MAX_SURE_SN) |

---

## Davranış Değişiklikleri (Dikkat)
- TWAP dilim aralığı varsayılanı **3.0sn → 1.5sn** (SL gecikmesini azaltmak için).
- A/B testi artık gerçekten iki gruba dağıtım yapıyor — önceki sürümlerde
  toplanan A/B verisi geçersizdi, sıfırdan birikecek.
- Online learner accuracy metriği artık gerçekçi (önceden şişikti).

## Yeni config Anahtarı
```
TWAP_MAX_SURE_SN=8.0   # Smart execution toplam süre tavanı (saniye)
```
