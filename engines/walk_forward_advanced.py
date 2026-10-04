# =========================================================
# ASTRA v30.0 — GELİŞMİŞ WALK-FORWARD VALIDATION
# Purged K-Fold, Embargo, Combinatorial Purged CV
# =========================================================
import logging, numpy as np, pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import KFold
import sys; sys.path.append("..")
from config import WALK_FORWARD_SPLITS

log = logging.getLogger("ASTRA.WALK_FORWARD")

def purged_kfold_cv(X: pd.DataFrame, y: pd.Series,
                     model_cls, model_params: dict,
                     n_splits: int = None,
                     embargo_pct: float = 0.01) -> dict:
    """
    Purged K-Fold Cross Validation.
    Finansal zaman serisi için veri sızıntısını önler:
    - Purging: test periyoduna yakın train örnekleri çıkar
    - Embargo: test sonrasında belirli periyot train'e girmez

    Lopez de Prado'nun "Advances in Financial Machine Learning" kitabından.
    """
    n_splits = n_splits or WALK_FORWARD_SPLITS
    n        = len(X)
    embargo  = int(n * embargo_pct)
    kf       = KFold(n_splits=n_splits, shuffle=False)
    sonuclar = []

    for fold_idx, (train_idx, test_idx) in enumerate(kf.split(X)):
        # Purging: test'e zaman olarak yakın train örneklerini çıkar
        test_start = test_idx[0]
        test_end   = test_idx[-1]

        purge_start = max(0, test_start - embargo)
        purge_end   = min(n-1, test_end + embargo)

        # Train'den purge edilen örnekleri çıkar
        train_clean = [i for i in train_idx
                       if not (purge_start <= i <= purge_end)]

        if len(train_clean) < 20 or len(test_idx) < 5:
            continue

        X_tr = X.iloc[train_clean]
        y_tr = y.iloc[train_clean]
        X_te = X.iloc[test_idx]
        y_te = y.iloc[test_idx]

        try:
            model = model_cls(**model_params)
            model.fit(X_tr, y_tr)
            tahmin = model.predict(X_te)
            acc    = accuracy_score(y_te, tahmin)
            f1     = f1_score(y_te, tahmin, average="weighted", zero_division=0)
            try:
                proba = model.predict_proba(X_te)[:, 1]
                auc   = roc_auc_score(y_te, proba)
            except (ValueError, AttributeError, TypeError):
                auc = 0.5
            sonuclar.append({"fold": fold_idx, "acc": acc, "f1": f1, "auc": auc,
                              "train_size": len(train_clean), "test_size": len(test_idx)})
            log.debug(f"[WF] Fold {fold_idx}: acc={acc:.3f} f1={f1:.3f} auc={auc:.3f}")
        except Exception as e:
            log.warning(f"[WF] Fold {fold_idx} hatası: {e}")

    if not sonuclar:
        return {"ortalama": 0, "std": 0, "min": 0, "max": 0,
                "f1_ort": 0, "auc_ort": 0, "detay": []}

    acc_list = [s["acc"] for s in sonuclar]
    f1_list  = [s["f1"]  for s in sonuclar]
    auc_list = [s["auc"] for s in sonuclar]

    return {
        "splits":    n_splits,
        "ortalama":  round(float(np.mean(acc_list)), 4),
        "std":       round(float(np.std(acc_list)), 4),
        "min":       round(float(np.min(acc_list)), 4),
        "max":       round(float(np.max(acc_list)), 4),
        "f1_ort":    round(float(np.mean(f1_list)), 4),
        "auc_ort":   round(float(np.mean(auc_list)), 4),
        "embargo":   embargo_pct,
        "detay":     sonuclar,
    }


def expanding_window_cv(X: pd.DataFrame, y: pd.Series,
                         model_cls, model_params: dict,
                         min_train: int = 100,
                         test_size: int = 50) -> dict:
    """
    Expanding window: her fold'da train penceresi büyür.
    En gerçekçi canlı ortam simülasyonu.
    """
    n       = len(X)
    sonuclar= []
    start   = min_train

    while start + test_size <= n:
        X_tr = X.iloc[:start]
        y_tr = y.iloc[:start]
        X_te = X.iloc[start:start+test_size]
        y_te = y.iloc[start:start+test_size]

        try:
            model = model_cls(**model_params)
            model.fit(X_tr, y_tr)
            tahmin = model.predict(X_te)
            acc    = accuracy_score(y_te, tahmin)
            sonuclar.append({"train_size": start, "acc": acc})
        except Exception as e:
            log.warning(f"[EW] {start} train hatası: {e}")

        start += test_size

    if not sonuclar:
        return {"ortalama": 0, "std": 0, "trend": "VERİ YOK"}

    acc_list = [s["acc"] for s in sonuclar]
    # Trend: son yarısı ilk yarısından iyi mi?
    orta = len(acc_list) // 2
    ilk_ort  = np.mean(acc_list[:orta]) if orta > 0 else 0
    son_ort  = np.mean(acc_list[orta:]) if orta < len(acc_list) else 0
    trend    = "ARTIYOR" if son_ort > ilk_ort else ("DÜŞÜYOR" if son_ort < ilk_ort else "STABIL")

    log.info(f"[EW] {len(sonuclar)} pencere | ort={np.mean(acc_list):.3f} | trend={trend}")
    return {
        "pencere_sayisi": len(sonuclar),
        "ortalama":  round(float(np.mean(acc_list)), 4),
        "std":       round(float(np.std(acc_list)), 4),
        "trend":     trend,
        "ilk_ort":   round(float(ilk_ort), 4),
        "son_ort":   round(float(son_ort), 4),
        "detay":     sonuclar,
    }


def overfitting_skoru(train_acc: float, test_acc: float,
                       walk_forward_std: float) -> dict:
    # v39: Tek kaynak — backtest_engine'deki kanonik versiyona yönlendir.
    # (Eskiden burada farklı eşikler vardı; tutarsızlık giderildi.)
    try:
        from engines.backtest_engine import overfitting_skoru as _kanonik
        sonuc = _kanonik(train_acc, test_acc, walk_forward_std)
        # Geriye dönük uyumluluk için ek alanları doldur
        sonuc.setdefault("train_acc", round(train_acc, 4))
        sonuc.setdefault("test_acc", round(test_acc, 4))
        return sonuc
    except ImportError:
        # Fallback (import döngüsü olursa)
        fark = train_acc - test_acc
        risk = "DÜŞÜK"
        if fark > 0.15 or walk_forward_std > 0.08: risk = "YÜKSEK"
        elif fark > 0.08 or walk_forward_std > 0.05: risk = "ORTA"
        return {"train_acc": round(train_acc, 4), "test_acc": round(test_acc, 4),
                "fark": round(fark, 4), "wf_std": round(walk_forward_std, 4), "risk": risk}
