# =========================================================
# ASTRA v58 — DENETİM DÜZELTMELERİ (K-45..K-49)
# Çalıştırma: python tests/test_denetim_duzeltmeleri.py
#
# Kullanıcı "kodda ve ölçümlerde mantık hataları var mı, AB testine /
# öğrenmeye / Kelly'ye / Monte Carlo'ya / panel göstergelerine bak"
# dedi. Beş gerçek hata çıktı; bu dosya beşini de kilitliyor.
#
#  K-45  Online learner HER ÇAĞRIDA çöküyordu (river API değişikliği:
#        AdaptiveRandomForestClassifier → river.forest.ARFClassifier).
#        İstisna `log.debug` ile yutuluyordu → aylarca çalışmadı,
#        panelde `online_learning: {}` "veri yok" sanılıyordu.
#  K-46  Monte Carlo SAATLİK getiriyi "1 GÜNLÜK VaR" diye raporluyordu.
#        Ölçüm: aynı çağrı 4h getiriyle 157.86, günlükle 377.63 USDT
#        (2.38×; saatlikte ~√24≈4.9×). Risk seviyesi eşiği (var_pct>3)
#        günlük için kalibre olduğundan PRATİKTE HEP "DÜŞÜK" çıkıyordu.
#        Düzeltmeden sonra gerçek değer: %3.87 → "YÜKSEK".
#  K-47  A/B Sharpe `* sqrt(252)` ile yıllıklandırılıyordu — kayıtlar
#        İŞLEM BAŞINA PnL, günlük değil. Panelde `sharpe: -28.356`.
#  K-48  `_gelismis_state_topla` içindeki 11 blok `except Exception: pass`
#        ile sarılıydı → "veri yok" ile "çöktü" ayırt edilemiyordu.
#  K-49  `ab_test.json` sıfırlamadan sağ çıkıyordu (27 Ağustos verisi
#        4h+K-37 sonrası panelde güncel gibi görünüyordu).
#
# §4.1: Muhafızların yanına KONTROL testleri var.
# =========================================================
import sys, os, ast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.izolasyon import izole_et; izole_et()
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("BOT_TOKEN", "")

import numpy as np

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _kaynak(rel):
    with open(os.path.join(KOK, rel), encoding="utf-8") as fh:
        return fh.read()


def _kod(rel):
    """Kaynağı YORUM ve STRING'lerden arındırılmış hâlde döndür.

    ⚠️ Bu yardımcı sonradan eklendi: ilk sürümde testler ham kaynakta
    metin arıyordu ve DÜZELTMEYİ AÇIKLAYAN YORUMLARI eski kod sanıp
    yanlış alarm veriyordu (10 testin 5'i). Aynı tuzak bu kod tabanında
    zaten belgeli — `test_grafik_thread.py`: "docstring'deki plt.savefig
    açıklamasını gerçek çağrı sanıp yanlış alarm veriyordu".

    tokenize ile yorumlar ve string literalleri atılıyor; dönen metinde
    token'lar boşlukla ayrılır (yani `log.warning` → `log . warning`).
    """
    import io as _io, tokenize
    kaynak = _kaynak(rel)
    parcalar = []
    try:
        for tok in tokenize.generate_tokens(_io.StringIO(kaynak).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            parcalar.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        return kaynak          # ayrıştırılamazsa ham kaynağa düş
    return " ".join(parcalar)


# ─────────────────────────────────────────────
# K-45 — ONLINE LEARNER GERÇEKTEN ÇALIŞIYOR
# ─────────────────────────────────────────────
def test_online_learner_kuruluyor_ve_tahmin_uretiyor():
    """DAVRANIŞSAL: kurulum çökmemeli, tahmin dönmeli.

    Eski kod `river.ensemble.AdaptiveRandomForestClassifier` çağırıyordu;
    river 0.15+ onu `river.forest.ARFClassifier`'a taşıdı →
    AttributeError → learner HİÇ oluşmadı.
    """
    from engines.online_learner import (get_online_learner, _online_learners,
                                        RIVER_AVAILABLE)
    if not RIVER_AVAILABLE:
        return          # river kurulu değilse bu test anlamsız
    ol = get_online_learner("TESTOL")
    assert ol is not None, "Online learner oluşturulamadı"
    assert ol._model is not None, (
        "learner._model None — river sınıfı bulunamamış, sessizce "
        "devre dışı kalmış olabilir")
    r = ol.guncelle_ve_tahmin({"RSI": 50.0, "MACD": 0.1, "ATR_pct": 1.0},
                              None, 100.0)
    assert isinstance(r, dict) and "prob" in r, f"beklenmeyen çıktı: {r}"
    assert "TESTOL" in _online_learners, (
        "learner kayıt sözlüğüne girmedi — panel onu göremez")


def test_online_learner_GERCEKTEN_ogreniyor():
    """DAVRANIŞSAL: ardışık çağrılarda eğitim sayacı ARTMALI.

    ⚠️ K-50: `_scaler.learn_one(x).transform_one(x)` zincirleme çağrısı
    river 0.15+'ta kırık — `learn_one()` artık `self` değil `None`
    döndürüyor. Kurulum testi (K-45) bunu YAKALAMIYORDU çünkü hata
    ancak ölçekleyici kullanıldığında ortaya çıkıyor.

    "Kuruluyor" ile "öğreniyor" AYRI iddialar; ikisi de test edilmeli.
    """
    from engines.online_learner import get_online_learner, RIVER_AVAILABLE
    if not RIVER_AVAILABLE:
        return
    ol = get_online_learner("TESTLEARN")
    r1 = ol.guncelle_ve_tahmin({"RSI": 50.0, "MACD": 0.1, "ATR_pct": 1.0},
                               None, 100.0)
    r2 = ol.guncelle_ve_tahmin({"RSI": 55.0, "MACD": 0.2, "ATR_pct": 1.1},
                               1, 102.0)
    r3 = ol.guncelle_ve_tahmin({"RSI": 45.0, "MACD": -0.1, "ATR_pct": 0.9},
                               0, 99.0)
    for i, r in enumerate((r1, r2, r3), 1):
        assert r.get("aktif") is True, (
            f"{i}. turda learner pasif — bir istisna yutulmuş olabilir: {r}")
    assert r3["egitim_sayisi"] >= 2, (
        f"3 turdan sonra eğitim sayısı {r3['egitim_sayisi']} — model "
        f"öğrenmiyor (ölçekleyici zinciri kırık olabilir)")


def test_online_scaler_zincirleme_cagrilmiyor():
    """Kaynak: `learn_one(...).transform_one(...)` deseni OLMAMALI."""
    k = _kod("engines/online_learner.py")
    assert "learn_one ( x ) . transform_one" not in k, (
        "Ölçekleyicide zincirleme çağrı var — river 0.15+ `learn_one()` "
        "None döndürür, AttributeError atar")


def test_online_learner_import_surumden_bagimsiz():
    """Kaynak: eski sınıf adı DOĞRUDAN çağrılmamalı."""
    k = _kod("engines/online_learner.py")
    assert "ensemble . AdaptiveRandomForestClassifier" not in k, (
        "Eski river API'si doğrudan çağrılıyor — river >= 0.15'te "
        "AttributeError atar ve online öğrenme sessizce ölür")
    assert "forest" in k, "Yeni river yolu (river.forest) yok"


# ─────────────────────────────────────────────
# K-46 — MONTE CARLO BİRİM TUTARLILIĞI
# ─────────────────────────────────────────────
def test_mc_gunluk_veri_kullaniyor():
    """Kaynak: `monte_carlo_raporu` GÜNLÜK bar istemeli.

    Saatlik getiriyi "1G VaR" diye raporlamak riski ~5 kat düşük
    gösteriyordu.
    """
    # Yorumlar ayıklanmış kaynakta ARAMA: düzeltmeyi anlatan yorumda
    # eski `interval="1h"` geçiyor ve ham metin araması onu yakalıyordu.
    k = _kaynak("main.py")
    i = k.index("def monte_carlo_raporu")
    j = k.index("\ndef ", i + 10)
    import ast
    fn = ast.parse(k[i:j].strip()).body[0]
    cagrilar = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    araliklar = []
    for c in cagrilar:
        for kw in c.keywords:
            if kw.arg == "interval" and isinstance(kw.value, ast.Constant):
                araliklar.append(kw.value.value)
    assert "1d" in araliklar, (
        f"monte_carlo_raporu günlük (1d) bar istemiyor (bulunan: "
        f"{araliklar}) — VaR birimi etiketiyle uyuşmaz")
    assert "1h" not in araliklar, (
        f"Saatlik bar geri gelmiş (bulunan: {araliklar}) — çıktı "
        f"1 SAATLİK riski '1G VaR' diye gösterir")


def test_mc_var_olcek_ile_buyur():
    """DAVRANIŞSAL: `gun` arttıkça VaR artmalı (√t ölçeklemesi).

    Sabit dönen bir uygulama da diğer testleri geçerdi.
    """
    from engines.monte_carlo import MonteCarloRisk
    mc = MonteCarloRisk(simulations=20000)
    rng = np.random.default_rng(0)
    g = rng.normal(0.0, 0.02, 500)          # günlük getiri, %2 std
    v1 = mc.var_hesapla(g, 10000.0, gun=1)["var_usdt"]
    v4 = mc.var_hesapla(g, 10000.0, gun=4)["var_usdt"]
    assert v4 > v1 * 1.5, (
        f"4 günlük VaR ({v4:.1f}) 1 günlükten ({v1:.1f}) beklendiği "
        f"kadar büyük değil — ölçekleme çalışmıyor")


def test_kontrol_mc_gercek_risk_uretiyor():
    """AŞIRI DÜZELTME KONTROLÜ: VaR sıfır dönmemeli."""
    from engines.monte_carlo import MonteCarloRisk
    mc = MonteCarloRisk(simulations=20000)
    rng = np.random.default_rng(1)
    g = rng.normal(0.0, 0.03, 400)
    r = mc.var_hesapla(g, 10000.0, gun=1)
    assert r["var_usdt"] > 0, "VaR 0 döndü — hesap devre dışı kalmış olabilir"
    assert r["var_pct"] > 0


# ─────────────────────────────────────────────
# K-47 — A/B SHARPE
# ─────────────────────────────────────────────
def test_ab_sharpe_yillikladirilmiyor():
    """`sqrt(252)` çarpanı KALKMALI — kayıtlar işlem başına PnL."""
    k = _kod("engines/ab_test.py")
    assert "252" not in k, (
        "A/B Sharpe hâlâ sqrt(252) ile yıllıklandırılıyor — kayıtlar "
        "günlük getiri değil, işlem başına PnL")


def test_ab_sharpe_az_ornekte_sifir():
    """n < 30 iken Sharpe raporlanmamalı (gürültü ölçmek olur)."""
    from engines.ab_test import ABVaryant
    v = ABVaryant("Test")
    for x in (1.0, -1.0, 0.5, -0.5, 0.2):        # n=5
        v.islem_ekle(x)
    assert v.sharpe == 0.0, (
        f"n=5'te Sharpe {v.sharpe} raporlandı — eski eşik (5) gürültüyü "
        f"ölçüyordu")


def test_kontrol_ab_sharpe_yeterli_ornekte_calisiyor():
    """AŞIRI DÜZELTME KONTROLÜ: n >= 30'da Sharpe ÜRETİLMELİ."""
    from engines.ab_test import ABVaryant
    rng = np.random.default_rng(3)
    v = ABVaryant("Test")
    for x in rng.normal(0.5, 1.0, 60):
        v.islem_ekle(float(x))
    assert v.sharpe != 0.0, "n=60'ta Sharpe hâlâ 0 — hesap ölmüş"
    # İşlem başına Sharpe makul aralıkta olmalı (yıllıklandırılmamış)
    assert abs(v.sharpe) < 5, (
        f"Sharpe {v.sharpe:.2f} — yıllıklandırma geri gelmiş olabilir")


# ─────────────────────────────────────────────
# K-48 — PANEL METRİKLERİ SESSİZ ÇÖKMEMELİ
# ─────────────────────────────────────────────
def test_panel_metrik_toplayici_sessiz_yutmuyor():
    """`_gelismis_state_topla` içinde `except Exception: pass` OLMAMALI.

    Bu desen yüzünden K-45 aylarca görünmedi: panel `{}` gösteriyordu
    ve "henüz veri yok" sanılıyordu.
    """
    # AST ile: `except Exception:` gövdesi TEK BAŞINA `pass` olan
    # handler var mı? (Ham metin araması, düzeltmeyi anlatan yorumdaki
    # "except Exception: pass" ifadesini eski kod sanıyordu.)
    import ast
    k = _kaynak("main.py")
    i = k.index("def _gelismis_state_topla")
    j = k.index("\ndef ", i + 10)
    fn = ast.parse(k[i:j].strip()).body[0]
    sessiz = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)
              and len(h.body) == 1 and isinstance(h.body[0], ast.Pass)]
    assert not sessiz, (
        f"Panel metrik toplayıcısında {len(sessiz)} sessiz yutma var "
        f"(`except: pass`) — bir metrik çökerse 'veri yok' ile 'çöktü' "
        f"ayırt edilemez")
    logcagri = [n for n in ast.walk(fn) if isinstance(n, ast.Attribute)
                and n.attr in ("warning", "error")]
    assert logcagri, "Hata durumunda uyarı basılmıyor"


# ─────────────────────────────────────────────
# K-49 — A/B VERİSİ SIFIRLAMADA SİLİNİYOR
# ─────────────────────────────────────────────
def test_sifirlama_ab_testi_de_temizliyor():
    """`sifirla_k37.py` ab_test.json'u silmeli.

    Yedekleniyor ama silinmiyordu: 27 Ağustos verisi (4h ve K-37
    öncesi) panelde güncel gibi görünüyordu — §5.3 ihlali.
    """
    k = _kaynak("sifirla_k37.py")
    assert "ab_test.json" in k and "os.remove" in k, (
        "Sıfırlama betiği ab_test.json'u silmiyor — farklı "
        "yapılandırmadan kalan A/B verisi taşınır")


# ═════════════════════════════════════════════════════════
if __name__ == "__main__":
    testler = [v for k, v in sorted(globals().items())
               if k.startswith("test_") and callable(v)]
    print(f"\n{'='*56}")
    print(f"  ASTRA DENETİM DÜZELTMELERİ — {len(testler)} test")
    print(f"{'='*56}")
    basari, hata = 0, 0
    for t in testler:
        try:
            t()
            print(f"  [GEÇTİ]  {t.__name__}")
            basari += 1
        except AssertionError as e:
            print(f"  [HATA]   {t.__name__}")
            print(f"           → {str(e)[:95]}")
            hata += 1
        except Exception as e:
            print(f"  [ÇÖKTÜ]  {t.__name__}: {type(e).__name__}: {str(e)[:70]}")
            hata += 1
    print(f"{'='*56}")
    print(f"  SONUÇ: {basari} geçti, {hata} başarısız (toplam {len(testler)})")
    print(f"{'='*56}\n")
    sys.exit(0 if hata == 0 else 1)
