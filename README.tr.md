# ASTRA

Binance USDⓈ-M futures için kaldıraçlı, otomatik işlem botu. Sinyal üretir,
çok katmanlı bir veto zincirinden geçirir, borsada emir açar ve koruma
emirlerini (SL/TP/trailing) borsada tutar.

Python 3.10 · ~42.000 satır · 560 test / 54 dosya

🇬🇧 [English README](README.md) — ana belge

---

## ⚠️ ÖNCE BUNU OKU — DÜRÜST DURUM

**Bu bot henüz kâr ettiğini kanıtlamadı.**

| | |
|---|---|
| Çalışma modu | Binance **testnet** (test parası) |
| Kapanmış paper işlem | 0 / 100 (hüküm için 100 gerekiyor) |
| Ölçülen hipotez | **9 denendi, 9'u reddedildi** |
| Edge (istatistiksel üstünlük) | **henüz bulunamadı** |

Boru hattı uçtan uca çalışıyor — sinyal → veto zinciri → borsada emir →
SL/TP yerleşti. Bu doğrulandı. **Kârlılık doğrulanmadı.**

`karar_kurali.py` 100 kapanmış işlem, beklenti > %0.10 ve t > 2.0 istiyor.
Bu eşikler veri görülmeden yazıldı ve **değiştirilmez** — sonuca bakıp eşik
oynatmak hükmü geçersiz kılar.

> **Gerçek parayla kullanma.** Ne bu kod ne de buradaki hiçbir şey yatırım
> tavsiyesi değildir. Kaldıraçlı işlem sermayenin tamamını kaybettirebilir.

---

## Hızlı başlangıç

```bash
pip install -r requirements.txt
cp .env.example .env     # kendi anahtarlarını gir (dosya git'e girmez)
python testleri_calistir.py   # 560 test geçmeli
python main.py bot            # trading döngüsü + Telegram
```

Panel: `http://127.0.0.1:8080` (yalnızca localhost)

### `.env` — zorunlu alanlar

| değişken | ne işe yarar |
|---|---|
| `BINANCE_API_KEY` / `_SECRET` | borsa erişimi |
| `FUTURES_BASE_URL` | **testnet** için `https://testnet.binancefuture.com` |
| `LIVE_TRADING` | `false` = paper (yerel simülasyon), `true` = gerçek emir |
| `BOT_TOKEN` / `CHAT_ID` | Telegram bildirimleri (opsiyonel) |

⚠️ `LIVE_TRADING=true` + production URL = **gerçek para**. Testnet'te
kalmak için URL'leri `testnet.*` bırak.

---

## Nasıl çalışıyor

```
4h bar kapanır
      ↓
coin_analiz()  ──  34 feature · ML modelleri · rejim tespiti (HMM)
      ↓
sinyal (ai_score, confidence, karar)
      ↓
┌─ VETO ZİNCİRİ ────────────────────────────────┐
│  sinyal kalitesi (AI skor + güven, rejime göre)│
│  kill switch · circuit breaker                 │
│  çoklu borsa fiyat doğrulama                   │
│  MTF cascade  (4h ↔ 1d çelişkisi)              │
│  MTF hizalama (kaç zaman dilimi hemfikir)      │
│  EdgeEngine                                     │
│  strateji motoru (trend follow / mean revert)  │
│  minimum R/R · geç giriş · yeniden giriş       │
└────────────────────────────────────────────────┘
      ↓
emir  ──  market giriş + STOP_MARKET + TAKE_PROFIT_MARKET (Algo API)
      ↓
izleme  ──  SL/TP → tasfiye → zaman stop (24s = modelin etiket ufku)
```

### Dizinler

| dizin | içerik |
|---|---|
| `engines/` | işlem motoru, paper trading, veto zinciri, risk, model |
| `core/` | göstergeler, sinyal skoru, rejim tespiti |
| `data/` | Binance istemcileri, veritabanı, çoklu borsa |
| `execution/` | emir yürütme, akıllı emir yönlendirme |
| `strategy/` | strateji motoru, edge engine, rejim adaptörü |
| `api/` | panel (tek endpoint, salt-okunur) |
| `tests/` | 54 dosya, her biri bir kök nedeni koruyor |
| `sunucu/` | VPS kurulum notları |

---

## Değişmez kurallar

Bu kurallar acıyla öğrenildi; ihlal etmek ölçümü geçersiz kılar.

**1. Paper, canlıyı BİREBİR yansıtmalı (§5.3).**
İki yol aynı veto zincirinden, aynı kaldıraçtan, aynı eşiklerden geçer.
Ayrışırsa toplanan 100 işlem canlıyı temsil etmez ve hüküm anlamsızdır.
Parametre değişirse eldeki veri geçersizdir → sayaç sıfırlanır.

**2. "Bilmiyorum" ≠ "sorun yok" (fail-open deseni).**
Bu kod tabanının ana hastalığıydı: `acik_pozisyonlar()` hata alınca `[]`
("pozisyon yok") dönüyordu. Güvenlik-kritik çağrılar `strict=True` kullanır.

**3. Yeşil test kanıt değildir.**
Her veto testinin yanında bir **kontrol testi** olmalı — "hiçbir zaman izin
verme" davranışı da veto testlerini geçer. Yeni muhafız yazınca korumayı
kasten boz ve testin gerçekten kırmızıya döndüğünü gör.

**4. Kaynak metni arayan test, davranışı kilitlemez.**
`"fonksiyon_adi" in kaynak` araması import satırında da eşleşir; çağrıyı
silen mutasyon yakalanmaz. Davranışsal test yaz.

**5. Sürüklenme ≠ edge.**
Boğa piyasasında rastgele giriş bile pozitif beklenti verir. Doğru ölçü
`P(TP) − taban oran`.

---

## Belgeler

| dosya | ne anlatır |
|---|---|
| **`DEVAM_NOTLARI.md`** | **asıl belge** — oturumlar arası tek hafıza, ~100 kök nedenin tespiti ve düzeltmesi, ölçümlerle |
| `CANLI_GECIS_PROTOKOLU.md` | gerçek paraya geçiş koşulları |
| `DENETIM_RAPORU_v55.md` | bağımsız denetim raporu |
| `BINANCE_ALGO_EMIR_SEMASI.md` | koşullu emir API şeması (deneyerek çıkarıldı) |
| `CHANGELOG_v*.md` | sürüm geçmişi |

Yeni bir oturuma başlarken: **`DEVAM_NOTLARI.md` §0'dan oku.** Hangi
hipotezin neden reddedildiği orada yazılı; tekrar denemek zaman kaybı.

---

## Geliştirme

```bash
python testleri_calistir.py   # tüm paket (560 test)
python kontrol_4h.py          # sağlık + tempo
python kontrol_kapanis.py     # kapanış türü · fonlama · kaldıraç bütünlüğü
python karar_kurali.py        # hüküm (100 işlem gerektirir)
```

Yeni test eklerken: dosyayı `testleri_calistir.py` listesine **ekle** —
listede olmayan dosya sessizce atlanır (`tests/test_kosucu_kapsami.py` bunu
koruyor).

---

## Depoya girmeyenler

`.gitignore` şunları dışarıda tutar: `.env` ve tüm sırlar, `data/` ve
`saved_models/` içeriği (~8 GB model + veritabanı), `logs/`, order book
akışı, yedek dizinleri, ve gerçek bakiye/pozisyon içeren çalışma zamanı
durum dosyaları.

Klonlayan biri `.env.example`'ı doldurup kendi verisini sıfırdan toplar.

---

## Durum ve açık soru

Proje 2026-09 itibarıyla **duraklatıldı**. Son ölçümde paper 0 işlem açarken
canlı yol 5 işlem açtı — iki yolun ayrışması ters yöne döndü ve sebebi henüz
bulunmadı. Ayrıntı: `DEVAM_NOTLARI.md` §0.44.

Devam ederken ilk üç adım `DEVAM_NOTLARI.md` §0.46'da yazılı.

---

## Katkı, güvenlik, risk

| belge | içerik |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | katkı kuralları — ölçmeden değiştirme, kontrol testi, paper↔canlı eşitliği |
| [SECURITY.md](SECURITY.md) | güvenlik açığı bildirimi (public issue AÇMA) |
| [DISCLAIMER.md](DISCLAIMER.md) | finansal risk — çalıştırmadan önce oku |
| [LICENSE](LICENSE) | MIT |
