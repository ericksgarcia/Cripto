"""Backtest vetorizado com custos. Rebalanceia a cada 4h; P&L = peso(t) * retorno 4h seguinte."""
import numpy as np, pandas as pd
from features import DATA, STEP

FEE = 0.0010  # 10 bps por unidade de turnover (taxa taker + slippage)
BARS_YEAR = 365 * 24 / STEP


def stats(r, name):
    r = r.dropna()
    eq = r.cumsum()
    dd = (eq - eq.cummax()).min()
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(BARS_YEAR)
    return dict(strategy=name, ret_ann=r.mean() * BARS_YEAR, vol_ann=r.std() * np.sqrt(BARS_YEAR),
                sharpe=sh, maxdd=dd, calmar=(r.mean() * BARS_YEAR) / (abs(dd) + 1e-12))


def run(P, score_col, mode="ls", smooth=3, vol_target=0.30):
    """score -> pesos. mode 'ls' = neutro ao mercado (long top/short bottom); 'dir' = direcional long/short."""
    S = P.pivot(index="open_time", columns="symbol", values=score_col)
    R = P.pivot(index="open_time", columns="symbol", values="fwd4")
    V = P.pivot(index="open_time", columns="symbol", values="vol")
    S = S.ewm(span=smooth).mean() if smooth > 1 else S
    if mode == "ls":
        Z = S.sub(S.mean(axis=1), axis=0)
        W = Z.div(Z.abs().sum(axis=1) + 1e-12, axis=0)
    else:
        Z = S.clip(-1, 1) / V * V.mean().mean()
        W = Z.div(Z.abs().sum(axis=1).clip(lower=1), axis=0)
    gross = (R * W).sum(axis=1)
    cost = FEE * W.diff().abs().sum(axis=1).fillna(0)
    net = gross - cost
    # alvo de volatilidade, usando só vol passada realizada
    scale = (vol_target / (net.rolling(6 * 60).std().shift(1) * np.sqrt(BARS_YEAR))).clip(0.25, 3).fillna(1)
    return net * scale, gross, W


if __name__ == "__main__":
    pr = pd.read_parquet(DATA.parent.parent / "results" / "preds.parquet")
    Pn = pd.read_parquet(DATA / "panel.parquet")[["open_time", "symbol", "vol_24"]]
    pr = pr.merge(Pn, on=["open_time", "symbol"]).rename(columns={"vol_24": "vol"})
    pr["ens"] = pr.groupby("open_time")[["lgb", "gru"]].transform(lambda x: x).mean(axis=1)
    pr = pr.dropna(subset=["fwd4"])
    rows, curves = [], {}
    # baselines
    R = pr.pivot(index="open_time", columns="symbol", values="fwd4")
    bh = R.mean(axis=1); rows.append(stats(bh, "buy&hold igual-peso (sem vol target)")); curves["B&H"] = bh
    btc = R["BTCUSDT"]; rows.append(stats(btc, "buy&hold BTC")); curves["BTC"] = btc
    Pf = pd.read_parquet(DATA / "panel.parquet")
    for col, label in (("ema_gap_24_168", "tendência EMA24/168"), ("ret_168", "momentum 7d")):
        t = Pf.merge(pr[["open_time", "symbol"]], on=["open_time", "symbol"]).copy()
        t["sc"] = np.sign(t[col]); t = t.merge(pr[["open_time", "symbol", "fwd4", "vol"]], on=["open_time", "symbol"], suffixes=("_x", ""))
        for mode in ("ls", "dir"):
            n, g, _ = run(t, "sc", mode); rows.append(stats(n, f"{label} [{mode}]")); curves[f"{label}[{mode}]"] = n
    for col in ("lgb", "gru", "ens"):
        for mode in ("ls", "dir"):
            n, g, W = run(pr, col, mode)
            rows.append(stats(n, f"{col} [{mode}]")); rows[-1]["turnover_dia"] = W.diff().abs().sum(axis=1).mean() * 24 / STEP
            curves[f"{col}[{mode}]"] = n
    res = pd.DataFrame(rows).set_index("strategy")
    pd.set_option("display.width", 200); pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
    print(res)
    res.to_csv(DATA.parent.parent / "results" / "backtest_summary.csv")
    pd.DataFrame(curves).to_parquet(DATA.parent.parent / "results" / "curves.parquet")
    # por ano
    print("\nSharpe por ano:")
    yr = pd.DataFrame({k: v.groupby(v.index.year).apply(lambda r: r.mean() / (r.std() + 1e-12) * np.sqrt(BARS_YEAR)) for k, v in curves.items()})
    print(yr.T)
