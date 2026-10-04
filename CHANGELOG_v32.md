# ASTRA v32.0 — İŞLEM TEŞHİSİ: "NEDEN AÇILMIYOR?" SORUSUNA CEVAP

## Tarih: 2026-05-30 | Temel: v31.0

### Verinin işaret ettiği sorun
AI Memory raporlarında: win-rate %50, PnL pozitif (+0.94) ama
**işlem sayısı durmuş** — sinyal 62'de sabit, paper işlem 13→14
(sadece +1). Bot bu dönemde neredeyse hiç yeni işlem açmamış.

Sorun: 9 ayrı veto katmanı var (slippage, kill switch, circuit,
çoklu borsa, validator, korelasyon, MTF cascade, MTF hizalama,
EdgeEngine) ama hepsi SESSİZCE işlem reddediyordu. Hangisinin kaç
işlemi engellediği bilinmiyordu — kör nokta.

## 🔬 Yeni: Veto Sayacı + /neden Komutu

Artık her işlem reddi, NEDENİYLE birlikte sayılıyor. `/neden`
komutu işlemlerin tam olarak nerede engellendiğini gösterir:

```
📊 İŞLEM TEŞHİSİ — neden açılmıyor?
✅ Açılan işlem : 2
⛔ Reddedilen   : 8
📈 Açılma oranı : %20

Red nedenleri (en çok → en az):
  📊 MTF hizalama yok: 3 (%38)
  🔬 EdgeEngine veto: 2 (%25)
  ⏱️ Geç giriş (slippage): 1 (%13)
  ...
```

**Bu, "işlem neden durdu" sorusunu TAHMİNLE değil VERİYLE yanıtlar.**
En çok reddeden katman, işlem sayısını en çok kısıtlayandır — ve
onu .env'den hedefli şekilde gevşetebilirsin.

## Sayılan 9 Veto Katmanı
| Katman | Sayaç adı |
|--------|-----------|
| Geç giriş (slippage guard) | slippage_gec_giris |
| Kill switch | kill_switch |
| Circuit breaker | circuit_breaker |
| Çoklu borsa veto | coklu_borsa |
| Dayanıklılık reddi (validator) | validator_dayaniklilik |
| Korelasyon limiti | korelasyon |
| MTF cascade blok | mtf_cascade |
| MTF hizalama yok | mtf_hizalama_yok |
| EdgeEngine veto | edge_engine |
| Strateji reddi | strateji_red |
| Sinyal filtresi | sinyal_filtresi |

Ayrıca başarılı açılışlar da sayılıyor → açılma oranı (%) hesaplanıyor.

## Dashboard
"veto" alanı dashboard state'ine eklendi (gelecekte panel olarak
gösterilebilir).

## Etkilenen Dosyalar
- `main.py`: veto sayacı altyapısı + 9 veto noktasına sayaç +
  /neden komutu + dashboard entegrasyonu
- `config.py`: v32.0

## Test Sonuçları
- 37 komut kayıtlı, hepsi tanımlı ✅
- Veto sayacı: 10 işlemli senaryoda doğru dağılım + açılma oranı ✅
- 74 dosya syntax temiz ✅

## Sonraki Adım (öneri)
Botu bir süre çalıştırıp `/neden` raporuna bak. Eğer örneğin
"MTF hizalama yok" veya "EdgeEngine veto" işlemlerin çoğunu
reddediyorsa, o katman fazla katı demektir — hedefli gevşetebiliriz.
Ama önce VERİ topla; hangi katmanın gerçekten darboğaz olduğunu
görmeden ayar yapma.

## Dürüst Not
İşlem sayısının düşük olması her zaman KÖTÜ değildir — bot sadece
yüksek kaliteli setup'ları bekliyor olabilir (ki win-rate %50 +
pozitif PnL bunu destekliyor). /neden raporu, "az işlem" bir sorun
mu yoksa sağlıklı seçicilik mi olduğunu ayırt etmene yarar.
