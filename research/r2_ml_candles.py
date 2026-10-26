"""Modelo LightGBM cross-sectional com features de candles (anatomia, padrões TA-Lib, intradiário 4h, volume).

Walk-forward trimestral com janela expansiva e embargo do horizonte do alvo — o modelo só vê o passado.
Alvo: retorno dos próximos H dias relativo à média do universo (rank). Carteira: top-k previsto + filtro de regime BTC.
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import numpy as np, pandas as pd, talib, lightgbm as lgb
from engine.mine import data, data_universe, eligible, evaluate, summarize, regime_btc, s_rotation

H = 7
PATTERNS = ["CDLENGULFING", "CDLHAMMER", "CDLSHOOTINGSTAR", "CDLDOJI", "CDLMORNINGSTAR", "CDLEVENINGSTAR",
            "CDL3WHITESOLDIERS", "CDL3BLACKCROWS", "CDLHARAMI", "CDLMARUBOZU", "CDLPIERCING", "CDLDARKCLOUDCOVER",
            "CDLINVERTEDHAMMER", "CDLHANGINGMAN", "CDLSPINNINGTOP", "CDLKICKING"]


def coin_features(d, d4):
    o, h, l, c, v = (d[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    f = {}
    cs = pd.Series(c, d.index)
    lr = np.log(cs).diff()
    for n in (1, 3, 7, 14, 30, 60, 90):
        f[f"ret{n}"] = cs.pct_change(n)
    vol30 = lr.rolling(30).std()
    f["vol30"] = vol30; f["vol7"] = lr.rolling(7).std(); f["volratio"] = f["vol7"] / vol30
    for n in (7, 30, 90):
        f[f"sret{n}"] = f[f"ret{n}"] / (vol30 * np.sqrt(n))
    rng = (h - l); rng[rng == 0] = np.nan
    body = (c - o) / rng; up = (h - np.maximum(o, c)) / rng; lo = (np.minimum(o, c) - l) / rng
    clv = ((c - l) - (h - c)) / rng
    atr = talib.ATR(h, l, c, 14)
    for name, x in (("body", body), ("upwick", up), ("lowwick", lo), ("clv", clv)):
        s = pd.Series(x, d.index)
        f[f"{name}1"] = s; f[f"{name}3"] = s.rolling(3).mean(); f[f"{name}7"] = s.rolling(7).mean()
    f["range_atr"] = pd.Series(rng / atr, d.index)
    f["atrp"] = pd.Series(atr / c, d.index)
    f["rsi14"] = pd.Series(talib.RSI(c, 14), d.index); f["rsi3"] = pd.Series(talib.RSI(c, 3), d.index)
    for n in (20, 50, 200):
        f[f"dma{n}"] = cs / cs.rolling(n).mean() - 1
    f["dhigh60"] = cs / pd.Series(h, d.index).rolling(60).max() - 1
    f["dlow60"] = cs / pd.Series(l, d.index).rolling(60).min() - 1
    lv = np.log(pd.Series(v * c, d.index) + 1)
    f["vz"] = (lv - lv.rolling(30).mean()) / lv.rolling(30).std()
    f["vtrend"] = lv.rolling(7).mean() - lv.rolling(30).mean()
    # Heikin-Ashi: sequência de candles HA de alta
    hac = (o + h + l + c) / 4
    hao = np.zeros_like(c); hao[0] = o[0]
    for i in range(1, len(c)):
        hao[i] = (hao[i - 1] + hac[i - 1]) / 2
    f["ha_up7"] = pd.Series((hac > hao).astype(float), d.index).rolling(7).mean()
    # padrões de candle (TA-Lib): soma sinalizada dos últimos 3 dias
    pat = np.zeros(len(c))
    for p in PATTERNS:
        x = getattr(talib, p)(o, h, l, c) / 100.0
        f[f"p_{p[3:].lower()}"] = pd.Series(x, d.index).rolling(3).sum()
        pat += x
    f["pat_sum3"] = pd.Series(pat, d.index).rolling(3).sum()
    # intradiário (4h): retornos dos últimos candles, fração de candles de alta, maior queda intradiária
    c4 = d4.close
    r4 = c4.pct_change()
    g = pd.DataFrame({"r4_last": r4, "r4_up": (r4 > 0).astype(float), "r4_min": r4, "r4_max": r4,
                      "body4": (d4.close - d4.open) / (d4.high - d4.low).replace(0, np.nan)})
    agg = g.resample("1D").agg({"r4_last": "last", "r4_up": "mean", "r4_min": "min", "r4_max": "max", "body4": "mean"})
    for k in agg:
        f[k] = agg[k].reindex(d.index)
    f["r4_up3"] = f["r4_up"].rolling(3).mean()
    return pd.DataFrame(f)


def build(U, D4, elig):
    rows = []
    for s in U["C"].columns:
        d = pd.DataFrame({k: U[x][s] for k, x in (("open", "O"), ("high", "H"), ("low", "L"), ("close", "C"), ("volume", "V"))}).dropna()
        d["volume"] = d["volume"] / d["close"]
        if len(d) < 120:
            continue
        d4 = pd.DataFrame({k: D4[x][s] for k, x in (("open", "O"), ("high", "H"), ("low", "L"), ("close", "C"))}).dropna()
        F = coin_features(d, d4)
        F["coin"] = s
        fwd = U["O"][s].shift(-1 - H) / U["O"][s].shift(-1) - 1  # entra na abertura seguinte, segura H dias
        F["fwd"] = fwd.reindex(F.index)
        rows.append(F)
    X = pd.concat(rows).reset_index().rename(columns={"index": "date"})
    X = X.rename(columns={X.columns[0]: "date"})
    el = elig.stack(); el.index.names = ["date", "coin"]; el = el.rename("elig").reset_index()
    X = X.merge(el, on=["date", "coin"], how="left")
    X = X[X.elig.fillna(False)]
    # contexto de mercado
    btc = U["C"]["BTC"]
    mk = pd.DataFrame({"btc_ret7": btc.pct_change(7), "btc_ret30": btc.pct_change(30),
                       "btc_dma100": btc / btc.rolling(100).mean() - 1,
                       "btc_vol30": np.log(btc).diff().rolling(30).std()})
    X = X.merge(mk, left_on="date", right_index=True, how="left")
    feats = [c for c in X.columns if c not in ("date", "coin", "fwd", "elig")]
    # ranks cross-sectionais
    for c in [c for c in feats if not c.startswith("btc_")]:
        X[c + "_cs"] = X.groupby("date")[c].rank(pct=True)
    X["y"] = X.groupby("date")["fwd"].rank(pct=True)
    return X


def walk_forward(X, start="2020-01-01"):
    feats = [c for c in X.columns if c not in ("date", "coin", "fwd", "elig", "y")]
    months = pd.date_range(pd.Timestamp(start, tz="UTC"), X.date.max(), freq="QS")  # retreino trimestral
    preds = []
    params = dict(n_estimators=200, n_jobs=4, learning_rate=0.03, num_leaves=15, min_child_samples=200, subsample=0.7,
                  subsample_freq=1, colsample_bytree=0.6, reg_lambda=5.0, verbose=-1)
    for m in months:
        end_train = m - pd.Timedelta(days=H + 1)  # embargo
        tr = X[(X.date < end_train) & X.y.notna()]
        te = X[(X.date >= m) & (X.date < m + pd.offsets.QuarterBegin(1, startingMonth=1))]
        if len(te) == 0 or len(tr) < 5000:
            continue
        mdl = lgb.LGBMRegressor(**params).fit(tr[feats], tr.y)
        p = te[["date", "coin"]].copy(); p["pred"] = mdl.predict(te[feats])
        preds.append(p)
    imp = pd.Series(mdl.feature_importances_, feats).sort_values(ascending=False)
    return pd.concat(preds), imp


def weights_from_pred(P, C, top=5, smooth=3, regime=100):
    S = P.pivot(index="date", columns="coin", values="pred").reindex(C.index)
    S = S.rolling(smooth, min_periods=1).mean()
    rk = S.rank(axis=1, ascending=False)
    w = (rk <= top).astype(float) / top
    if regime:
        w = w.mul(regime_btc(C, regime, 1), axis=0)
    return w.reindex(columns=C.columns).fillna(0.0)


if __name__ == "__main__":
    univ = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    U = data_universe("1d", start="2017-08-01"); D4 = data_universe("4h", start="2017-08-01")
    el = eligible(U, 1, univ)
    X = build(U, D4, el)
    print("amostras", len(X), "features", X.shape[1])
    P, imp = walk_forward(X)
    P.to_parquet(f"results/ml_preds_U{univ}.parquet")
    print("top features:", imp.head(20).to_dict())
    # IC (correlação de Spearman previsão x retorno futuro) por ano
    Z = P.merge(X[["date", "coin", "fwd"]], on=["date", "coin"])
    ic = Z.groupby("date").apply(lambda g: g.pred.corr(g.fwd, method="spearman"))
    print("IC médio por ano:", ic.groupby(ic.index.year).mean().round(3).to_dict())
    res = {}
    for top in (3, 5):
        for sm in (1, 3, 7):
            res[f"ML_U{univ}_t{top}_sm{sm}"] = evaluate(weights_from_pred(P, U["C"], top, sm), U)
    for top in (3, 5):
        res[f"ROT_U{univ}_l14_t{top}"] = evaluate(s_rotation(U, 1, 14, top, el, "btc", 100, 50), U)
    pd.set_option("display.width", 250)
    print(summarize(res).to_string())
