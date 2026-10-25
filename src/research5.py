"""#3 StatArb / pairs trading em perps (diário). Seleção de pares walk-forward (formação 365d), z-score de spread, custos+funding."""
import numpy as np, pandas as pd, itertools, sys
from statsmodels.tsa.stattools import adfuller
import research2 as R

FEE = 0.0010          # por perna e por lado (taxa + slippage)
FORM, K = 365, 10
ENTRY, EXIT, STOP, ZWIN, MAXHOLD = 2.0, 0.5, 4.0, 60, 30
spot, perp, fund = R.load()
L = np.log(perp)
RET = L.diff(); FUND = fund.reindex(perp.index).fillna(0)
rebal = pd.date_range("2021-01-01", "2026-09-30", freq="QS")

def half_life(s):
    ds, lag = s.diff().dropna(), s.shift(1).dropna()
    b = np.polyfit(lag.loc[ds.index], ds, 1)[0]
    return -np.log(2) / np.log(1 + b) if -1 < b < 0 else np.inf

def pick(t, rng=None, placebo=False):
    win = L[(L.index < t) & (L.index >= t - pd.Timedelta(days=FORM))]
    cols = [c for c in win.columns if win[c].notna().all()]
    cands = []
    pairs = list(itertools.combinations(cols, 2))
    if placebo:
        idx = rng.choice(len(pairs), min(K, len(pairs)), replace=False)
        sel = [pairs[i] for i in idx]
        out = []
        for a, b in sel:
            x, y = win[a], win[b]; beta = np.polyfit(y, x, 1)[0]; out.append((a, b, beta))
        return out
    for a, b in pairs:
        x, y = win[a], win[b]
        beta = np.polyfit(y, x, 1)[0]
        if not (0.2 < beta < 5): continue
        s = x - beta * y
        try: p = adfuller(s, maxlag=1, regression="c", autolag=None)[1]
        except Exception: continue
        hl = half_life(s)
        if 2 <= hl <= 30: cands.append((p, a, b, beta))
    cands.sort()
    return [(a, b, beta) for _, a, b, beta in cands[:K]]

def trade(selection_fn):
    pnl = pd.Series(0.0, index=perp.index); cnt = pd.Series(0.0, index=perp.index); turn_total = 0
    for i, t in enumerate(rebal):
        t_end = rebal[i + 1] if i + 1 < len(rebal) else perp.index[-1] + pd.Timedelta(days=1)
        sel = selection_fn(t)
        if not sel: continue
        for a, b, beta in sel:
            s = L[a] - beta * L[b]
            z = (s - s.rolling(ZWIN).mean()) / s.rolling(ZWIN).std()
            idx = perp.index[(perp.index >= t) & (perp.index < t_end)]
            pos, held, prev = 0, 0, 0
            scale = 1 / (1 + abs(beta)) / len(sel)
            for k, d in enumerate(idx[:-1]):
                zz = z.loc[d]
                if np.isnan(zz): pos = 0
                elif pos == 0:
                    pos = -1 if zz > ENTRY else (1 if zz < -ENTRY else 0); held = 0
                else:
                    held += 1
                    if abs(zz) < EXIT or abs(zz) > STOP or held >= MAXHOLD: pos = 0
                nd = idx[k + 1]                       # posição decidida no fechamento de d rende em nd
                wa, wb = pos * scale, -pos * beta * scale
                g = wa * RET.loc[nd, a] + wb * RET.loc[nd, b]
                f = -(wa * FUND.loc[nd, a] + wb * FUND.loc[nd, b])     # long paga funding, short recebe
                c = FEE * (abs(wa - prev * scale) + abs(wb + prev * beta * scale))
                pnl.loc[nd] += (0 if np.isnan(g) else g) + f - c
                cnt.loc[nd] += abs(pos) != 0
                prev = pos
    return pnl["2021-01-01":]

def summ(r, name):
    r = r.dropna(); eq = (1 + r).cumprod()
    return dict(strategy=name, cagr=eq.iloc[-1] ** (365 / len(r)) - 1, vol=r.std() * np.sqrt(365),
                sharpe=r.mean() / (r.std() + 1e-12) * np.sqrt(365), maxdd=(eq / eq.cummax() - 1).min())

if __name__ == "__main__":
    pd.set_option("display.width", 200); pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
    real = trade(pick)
    rows = [summ(real, "StatArb (ADF top-10, z>2) completo")]
    for k, v in {"2021-22": real[:"2022-12-31"], "2023-26": real["2023-01-01":]}.items(): rows.append(summ(v, f"  {k}"))
    rows.append(summ(real * 1, "") | {"strategy": "  (sem custos: ver abaixo)"})
    # sem custos
    FEE0 = FEE; globals()["FEE"] = 0.0
    nocost = trade(pick); globals()["FEE"] = FEE0
    rows[-1] = summ(nocost, "  mesmo, SEM custos")
    # placebo: pares aleatórios, 10 sementes
    pls = []
    for sd in range(8):
        rng = np.random.default_rng(sd)
        pls.append(trade(lambda t: pick(t, rng, placebo=True)))
    ps = pd.DataFrame({i: summ(p, "")  for i, p in enumerate(pls)}).T
    print(pd.DataFrame(rows).set_index("strategy").to_string())
    print("\nPlacebo (pares aleatórios, mesmas regras, 8 sementes) — médias:")
    print(ps[["cagr", "vol", "sharpe", "maxdd"]].astype(float).describe().loc[["mean", "min", "max"]])
    print("\nRetorno por ano (real):", {int(k): round(v, 4) for k, v in real.groupby(real.index.year).apply(lambda x: (1 + x).prod() - 1).items()})
    real.to_frame("statarb").to_parquet(R.RES / "statarb.parquet")
