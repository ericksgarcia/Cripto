"""Fase 7 — MOTOR DE CONFLUÊNCIA (1h): junta todas as técnicas num único placar por moeda/hora, aprendido por ML.

Por moeda, a cada hora t (fechamento), ~130 features usando só dados até t:
  • 18 padrões gráficos (SMC, Wyckoff, clássicos, Ichimoku, squeeze, divergências...) em 1h, 4h e 1d
    (4h/1d só de candles já FECHADOS) + contagem de padrões coincidentes;
  • tendência multi-timeframe (EMA20/50/200, RSI, distância de topos/fundos) em 1h/4h/1d;
  • posicionamento (varejo L/S, top traders, smart_div, OI 1/4/24h, fluxo agressor, funding);
  • contexto BTC (retornos, regime, vol), retorno residual ao BTC, ranks cross-section entre as moedas;
  • horário (hora UTC, dia da semana, horas até o próximo funding), anatomia de candles, volume.
Alvo: retorno a frente de H horas (entrada na abertura de t+1), normalizado pela vol.
LightGBM walk-forward MENSAL (treina só com o passado, embargo de H horas) -> toda previsão é fora da amostra.
"""
import warnings; warnings.filterwarnings("ignore")
import sys, time
import numpy as np, pandas as pd, lightgbm as lgb
from engine.core import ROOT, AGG
from research.ta.patterns import detect_all, NAMES

H = int(sys.argv[2]) if __name__ == "__main__" and len(sys.argv) > 2 else 4
OUT = ROOT / "results/r28"
OUT.mkdir(exist_ok=True)
COINS = [p.stem for p in (ROOT / "data/metrics_1h").glob("*.parquet") if p.stem != "HYPE"]


def ema(x, n): return x.ewm(span=n, adjust=False).mean()


def rsi(c, n=14):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def tf_block(d, tag):
    """Features de tendência/padrões de um timeframe (índice = início da barra)."""
    o, h, l, c, v = (d[x].values.astype(np.float64) for x in ("open", "high", "low", "close", "volume"))
    S, _ = detect_all(o, h, l, c, v, 3)
    F = pd.DataFrame(index=d.index)
    for i, n in enumerate(NAMES):
        F[f"{tag}_p_{n}"] = S[i].astype(np.float32)
    F[f"{tag}_npat_bull"] = S.sum(axis=0)
    cc = d.close
    for n in (20, 50, 200):
        F[f"{tag}_dema{n}"] = cc / ema(cc, n) - 1
    F[f"{tag}_rsi"] = rsi(cc)
    F[f"{tag}_dhi20"] = cc / d.high.rolling(20).max() - 1
    F[f"{tag}_dlo20"] = cc / d.low.rolling(20).min() - 1
    F[f"{tag}_dhi55"] = cc / d.high.rolling(55).max() - 1
    F[f"{tag}_ret1"] = cc.pct_change(); F[f"{tag}_ret5"] = cc.pct_change(5)
    rng = (d.high - d.low).replace(0, np.nan)
    F[f"{tag}_body"] = (d.close - d.open) / rng; F[f"{tag}_lowwick"] = (np.minimum(d.open, d.close) - d.low) / rng
    F[f"{tag}_upwick"] = (d.high - np.maximum(d.open, d.close)) / rng
    lv = np.log1p(d.volume * d.close); F[f"{tag}_vz"] = (lv - lv.rolling(50).mean()) / lv.rolling(50).std()
    return F


def coin_features(sym):
    base = sym[4:] if sym.startswith("1000") else sym
    px = pd.read_parquet(ROOT / "data/ta_1h" / f"{base}.parquet").loc["2021-06-01":"2026-10-24"]
    px = px.resample("1h").agg(AGG).dropna()
    F = tf_block(px, "h1")
    for tag, rule, delta in (("h4", "4h", "4h"), ("d1", "1D", "1D")):
        d = px.resample(rule).agg(AGG).dropna()
        B = tf_block(d, tag)
        B.index = B.index + pd.Timedelta(delta)  # disponível só quando a barra fecha
        F = F.join(B.reindex(F.index + pd.Timedelta("1h"), method="ffill").set_axis(F.index))
    F["npat_total"] = F.h1_npat_bull + F.h4_npat_bull + F.d1_npat_bull
    c = px.close; lr = np.log(c).diff()
    for n in (2, 4, 8, 24, 72, 168):
        F[f"ret{n}"] = c.pct_change(n)
    F["vol24"] = lr.rolling(24).std(); F["vol168"] = lr.rolling(168).std(); F["volratio"] = F.vol24 / F.vol168
    for n in (24, 168):
        F[f"sret{n}"] = F[f"ret{n}"] / (F.vol168 * np.sqrt(n))
    # posicionamento
    m = pd.read_parquet(ROOT / "data/metrics_1h" / f"{sym}.parquet").reindex(F.index)
    z = lambda x, n=24 * 30: (x - x.rolling(n, min_periods=24 * 7).mean()) / x.rolling(n, min_periods=24 * 7).std()
    F["z_retail"] = z(m.count_long_short_ratio); F["z_toppos"] = z(m.sum_toptrader_long_short_ratio)
    F["z_topacc"] = z(m.count_toptrader_long_short_ratio); F["smart_div"] = F.z_toppos - F.z_retail
    oi = m.sum_open_interest_value
    for n in (1, 4, 24):
        F[f"oi_chg{n}"] = oi.pct_change(n)
    F["z_oi24"] = z(F.oi_chg24); F["z_taker"] = z(m.sum_taker_long_short_vol_ratio.rolling(4).mean())
    fp = ROOT / "data/perps_all/funding" / f"{sym}USDT.parquet"
    if fp.exists():
        fr = pd.read_parquet(fp)["rate"]; fr.index = fr.index.floor("1h")
        fr = fr[~fr.index.duplicated()].reindex(F.index, method="ffill")
        F["funding"] = fr; F["z_funding"] = z(fr)
    F["hour"] = F.index.hour; F["dow"] = F.index.dayofweek; F["h_to_funding"] = (8 - (F.index.hour % 8)) % 8
    F["fwd"] = px.open.shift(-1 - H) / px.open.shift(-1) - 1
    F["sym"] = sym
    return F


def build():
    t = time.time()
    parts = {s: coin_features(s) for s in COINS}
    btc = parts["BTC"]
    ctx = pd.DataFrame({"btc_ret1": btc.h1_ret1, "btc_ret4": btc.ret4, "btc_ret24": btc.ret24, "btc_ret168": btc.ret168,
                        "btc_vol24": btc.vol24, "btc_d1_dema200": btc.d1_dema200, "btc_d1_dema50": btc.d1_dema50})
    X = pd.concat(parts.values())
    X = X.join(ctx, how="left")
    X["resid24"] = X.ret24 - X.btc_ret24; X["resid4"] = X.ret4 - X.btc_ret4
    X = X.reset_index().rename(columns={"index": "t"})
    X = X.rename(columns={X.columns[0]: "t"})
    for f in ("ret4", "ret24", "ret168", "oi_chg24", "smart_div", "z_retail", "resid24", "h1_vz", "z_funding"):
        X[f"cs_{f}"] = X.groupby("t")[f].rank(pct=True)
    X["y"] = X.fwd / (X.vol168 * np.sqrt(H))
    feats = [c for c in X.columns if c not in ("t", "sym", "fwd", "y")]
    X[feats] = X[feats].astype(np.float32)
    X.to_parquet(OUT / f"features_H{H}.parquet")
    print("features:", X.shape, f"{time.time()-t:.0f}s", flush=True)
    return X


def walk_forward(X):
    feats = [c for c in X.columns if c not in ("t", "sym", "fwd", "y")]
    X = X[X.y.notna() & np.isfinite(X.y)]
    X = X.assign(y=X.y.clip(-5, 5))
    months = pd.date_range("2022-07-01", "2026-10-01", freq="MS", tz="UTC")
    preds, imps = [], []
    params = dict(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=500, subsample=0.5,
                  subsample_freq=1, colsample_bytree=0.5, reg_lambda=10, n_jobs=4, verbose=-1)
    for m in months:
        tr = X[X.t < m - pd.Timedelta(hours=H + 1)]
        tr = tr.iloc[::2]  # amostra a cada 2 horas (acelera; reduz redundância)
        te = X[(X.t >= m) & (X.t < m + pd.offsets.MonthBegin(1))]
        if len(te) == 0:
            continue
        mdl = lgb.LGBMRegressor(**params).fit(tr[feats], tr.y)
        p = te[["t", "sym", "fwd"]].copy(); p["pred"] = mdl.predict(te[feats])
        preds.append(p); imps.append(pd.Series(mdl.feature_importances_, feats))
        print(m.date(), len(tr), flush=True)
    P = pd.concat(preds)
    P.to_parquet(OUT / f"preds_H{H}.parquet")
    imp = pd.concat(imps, axis=1).mean(axis=1).sort_values(ascending=False)
    imp.to_csv(OUT / f"importance_H{H}.csv")
    return P, imp


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("build", "all"):
        X = build()
    if step in ("train", "all"):
        X = pd.read_parquet(OUT / f"features_H{H}.parquet")
        P, imp = walk_forward(X)
        print(imp.head(30).to_string())
