# ASTRA v50.0 — DENETİM BULGULARININ KAPATILMASI

## Tarih: 2026-08-11 | Temel: v49.0
v49 denetim raporundaki kalan yüksek/orta öncelikli bulgular kapatıldı.

## 🔒 [H-2] Panel Kimlik Doğrulaması EKLENDİ
### Sorun (denetim bulgusu)
Dashboard 0.0.0.0:8080'de auth'suz dinliyordu — IP'yi bilen herkes
bakiye, pozisyon, strateji ve performans verisini görebiliyordu.
Ayrıca `Access-Control-Allow-Origin: *` ile herhangi bir web sitesi
tarayıcı üzerinden panel verisini okuyabiliyordu.

### Çözüm
- **Basic Auth**: `PANEL_USER` + `PANEL_PASS` .env'de doluysa panel
  kimlik doğrulaması ister. Şifre karşılaştırması `hmac.compare_digest`
  ile sabit süreli (zamanlama saldırısına dayanıklı).
- **CORS kısıtlandı**: `*` kaldırıldı. `PANEL_CORS_ORIGIN` boşsa header
  hiç gönderilmez (en güvenli varsayılan).
- **Geriye dönük uyumlu**: Ayarlar boşsa panel eskisi gibi açılır —
  mevcut kurulumlar kırılmaz.

### Canlı test sonuçları
| Senaryo | Sonuç |
|---|---|
| Kimliksiz istek | 401 REDDEDİLDİ |
| Yanlış şifre | 401 REDDEDİLDİ |
| Doğru kimlik | 200 ERİŞİM |
| CORS header | Gönderilmiyor |
| Ayar boşken | 200 (geriye uyumlu) |

## 🧪 [H-3] Execution Testleri EKLENDİ — 30 → 42 test
`tests/test_execution.py` (12 yeni test). Denetimde en kritik açık
buydu: gerçek emir gönderen kod hiç test edilmiyordu.

### En değerli test: test_paper_modda_gercek_emir_gitmez
Borsa fonksiyonunu izleyip, LIVE_TRADING=false iken HİÇ çağrılmadığını
kanıtlıyor. Bu test bozulursa, test modunda sanılan bir bot gerçek para
harcayabilir — regresyonu anında yakalar.

### Diğer testler
- Paper sonuç bütünlüğü (miktar/fiyat 0)
- İstatistik sayaçları, telegram raporu
- Hata dayanıklılığı: geçersiz sembol / negatif tutar → çökmeden güvenli başarısızlık
- **http_guard**: global timeout uygulanıyor + kullanıcı timeout'u ezilmiyor
- **watchdog**: heartbeat + thread dump teşhisi çökmüyor
- **DB sızıntı**: 40 işlemde tanıtıcı artışı yok + exception'da bağlantı kapanıyor

## 📄 [M-5] Log Rotasyonu EKLENDİ
`baslat.sh` artık 50MB'ı aşan logu arşivliyor, en fazla 5 arşiv tutuyor.
Disk dolması riski giderildi.

## Etkilenen Dosyalar
- `api/dashboard.py` — Basic Auth + CORS kısıtlaması
- `config.py` — PANEL_USER / PANEL_PASS / PANEL_CORS_ORIGIN + v50.0
- `.env.example` — panel güvenlik ayarları belgelendi
- `tests/test_execution.py` (YENİ) — 12 test
- `testleri_calistir.py` — yeni test paketi eklendi
- `baslat.sh` — log rotasyonu

## Doğrulama
- 80 dosya syntax temiz
- **42/42 test geçiyor** (24 çekirdek + 12 execution + 6 validator)
- main.py tam import OK
- Basic Auth canlı HTTP testinden geçti
- Geriye dönük uyumluluk doğrulandı

## Denetim Bulguları Durumu
| Bulgu | Durum |
|---|---|
| [C-1] .env sızıntısı | ✅ v49'da kapatıldı |
| [C-2] Docker secret | ✅ v49'da kapatıldı |
| [H-1] DB bağlantı sızıntısı | ✅ v49'da kapatıldı |
| [H-2] Panel auth | ✅ **v50'de kapatıldı** |
| [H-3] Test kapsamı | ✅ **v50'de iyileştirildi (%28→~%45)** |
| [M-1] Yinelenen ağ çağrısı | ✅ v49'da kapatıldı |
| [M-5] Log rotasyonu | ✅ **v50'de kapatıldı** |
| [M-2] DB modül ikiliği | ⏳ Bilinçli ertelendi (yüksek regresyon riski) |
| [M-3] Sessiz exception | ⏳ Kısmi (kritik olanlar düzeltildi) |
| [M-4] DB havuzu | ⏳ Mevcut ölçekte gerekli değil |

## KULLANICI AKSİYONU
Panel korumasını açmak için .env'e ekleyin:
```
PANEL_USER=admin
PANEL_PASS=guclu-bir-sifre-secin
```
Ayrıca firewall kısıtlaması hâlâ önerilir:
```
ufw allow from SENIN_IP to any port 8080 && ufw deny 8080
```
