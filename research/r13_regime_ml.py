"""Fase 3 — regime de mercado por ML (substituto do filtro BTC > SMA100).

Alvo: retorno do BTC nos próximos H dias > 0. Features só com dados até o fechamento de t: tendência multi-horizonte,
distância de médias, volatilidade, drawdown do topo, amplitude (breadth) do universo, funding médio, volume.
Walk-forward trimestral com janela expansiva e embargo de H dias. Saída: probabilidade diária (results/ml_regime.parquet).
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
from engine.core import ROOT
from engine.mine import data_universe

H = 14
U = data_universe("1d", start="2017-08-01")
C = U["C"]; V = U["V"]
btc = C["BTC"]
lr = np.log(btc).diff()
f = pd.DataFrame(index=C.index)
for n in (3, 7, 14, 30, 60, 90, 180, 365):
    f[f"ret{n}"] = btc.pct_change(n)
for n in (20, 50, 100, 200):
    f[f"dma{n}"] = btc / btc.rolling(n).mean() - 1
f["vol14"] = lr.rolling(14).std(); f["vol60"] = lr.rolling(60).std(); f["volratio"] = f.vol14 / f.vol60
f["dd_ath"] = btc / btc.cummax() - 1
f["dd_365"] = btc / btc.rolling(365).max() - 1
for n in (20, 50, 200):
    f[f"breadth{n}"] = (C > C.rolling(n).mean()).astype(float).where(C.notna()).mean(axis=1)
f["alt_rel30"] = (C.pct_change(30).median(axis=1) - btc.pct_change(30))
lv = np.log(V["BTC"] + 1); f["vz"] = (lv - lv.rolling(30).mean()) / lv.rolling(30).std()
fund = []
for p in (ROOT / "data/futures/funding").glob("*.parquet"):
    fund.append(pd.read_parquet(p)["rate"].resample("1D").sum().rename(p.stem))
Fd = pd.concat(fund, axis=1).reindex(C.index)
f["fund_btc7"] = Fd["BTC"].rolling(7).mean() if "BTC" in Fd else np.nan
f["fund_med7"] = Fd.median(axis=1).rolling(7).mean()
f["fund_med30"] = Fd.median(axis=1).rolling(30).mean()
f["dow"] = f.index.dayofweek
f = f.astype(float)
y = (btc.shift(-H) / btc - 1 > 0).astype(float).where(btc.shift(-H).notna())

preds = []
qs = pd.date_range(pd.Timestamp("2020-07-01", tz="UTC"), C.index[-1], freq="QS")
for q in qs:
    tr = f.index < q - pd.Timedelta(days=H + 1)
    tr &= f.index >= pd.Timestamp("2018-06-01", tz="UTC")
    te = (f.index >= q) & (f.index < q + pd.offsets.QuarterBegin(1, startingMonth=1))
    if te.sum() == 0:
        continue
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.02, num_leaves=7, min_child_samples=60,
                           subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5, verbose=-1)
    m.fit(f[tr & y.notna()], y[tr & y.notna()])
    preds.append(pd.Series(m.predict_proba(f[te])[:, 1], f.index[te]))
P = pd.concat(preds).rename("p_up")
P.to_frame().to_parquet(ROOT / "results/ml_regime.parquet")
imp = pd.Series(m.feature_importances_, f.columns).sort_values(ascending=False)
ok = y.reindex(P.index).notna()
print("AUC walk-forward:", round(roc_auc_score(y.reindex(P.index)[ok], P[ok]), 3))
for a, b in (("2020-07-01", "2023-12-31"), ("2024-01-01", "2026-10-25")):
    s = (P.index >= a) & (P.index <= b) & ok.values
    print(f"AUC {a[:4]}-{b[:4]}:", round(roc_auc_score(y.reindex(P.index)[s], P[s]), 3))
sma = (btc > btc.rolling(100).mean()).astype(float).reindex(P.index)
print("AUC do filtro SMA100 (binário):", round(roc_auc_score(y.reindex(P.index)[ok], sma[ok]), 3))
print("top features:", imp.head(10).to_dict())
