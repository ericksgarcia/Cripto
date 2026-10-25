"""Robustez: ensemble de tendência (SMA 50/100/200) em BTC+ETH, custos, anos, bootstrap, combinação com carry."""
import numpy as np, pandas as pd
import research2 as R

spot, perp, fund = R.load()
sub = spot[["BTCUSDT", "ETHUSDT"]]
pd.set_option("display.width", 200); pd.set_option("display.float_format", lambda x: f"{x:,.3f}")

def ens_trend(sub, fee=0.0010, vt=0.40, maxlev=1.0, Ls=(50, 100, 200)):
    ws, gross = [], 0
    r = sub.pct_change()
    for L in Ls:
        _, w = R.trend(sub, L, vt=vt, maxlev=maxlev, fee=fee); ws.append(w)
    w = sum(ws) / len(ws)
    g = (w * r.fillna(0)).sum(axis=1)
    return g - w.diff().abs().sum(axis=1).fillna(0) * fee, w

def sharpe(r): r = r.dropna(); return r.mean() / (r.std() + 1e-12) * np.sqrt(365)

t, w = ens_trend(sub)
t = t["2020-04-01":]   # após warm-up da SMA200
c, cw = R.carry(spot, perp, fund, always=True)
c = c.reindex(t.index).fillna(0)
bh = sub.pct_change().mean(axis=1).reindex(t.index)

rows = []
def add(name, r):
    for k, v in {"full": r, "2020-22": r[:"2022-12-31"], "2023-26": r["2023-01-01":]}.items():
        rows.append(R.stats(v, f"{name} | {k}"))
add("B&H BTC+ETH 50/50", bh)
add("Tendência ensemble BTC+ETH", t)
idle = (1 - w.sum(axis=1)).clip(lower=0).reindex(t.index).shift(0)
combo = t + idle * c
add("Tendência + carry no caixa ocioso", combo)
add("Carry sempre-ligado (universo)", c)
print(pd.DataFrame(rows).set_index("strategy").to_string())

print("\nSharpe por ano:")
yr = pd.DataFrame({n: s.groupby(s.index.year).apply(sharpe) for n, s in
                   {"B&H": bh, "Trend": t, "Combo": combo, "Carry": c}.items()})
ret = pd.DataFrame({n: s.groupby(s.index.year).apply(lambda x: (1 + x).prod() - 1) for n, s in
                    {"B&H": bh, "Trend": t, "Combo": combo, "Carry": c}.items()})
print(yr.join(ret, lsuffix="_sharpe", rsuffix="_ret"))

print("\nSensibilidade a custo (tendência ensemble, ida+volta por turnover):")
for fee in (0.0005, 0.0010, 0.0025, 0.0050):
    x, _ = ens_trend(sub, fee=fee); x = x["2020-04-01":]
    print(f"  fee {fee*1e4:>4.0f} bps: Sharpe {sharpe(x):.2f}  CAGR {(1+x).prod()**(365/len(x))-1:.3f}")
print("Sensibilidade a vol target:")
for vt in (0.25, 0.40, 0.60):
    x, _ = ens_trend(sub, vt=vt); x = x["2020-04-01":]
    print(f"  vt {vt:.2f}: Sharpe {sharpe(x):.2f}  CAGR {(1+x).prod()**(365/len(x))-1:.3f}  maxDD {((1+x).cumprod()/(1+x).cumprod().cummax()-1).min():.3f}")

# bootstrap em blocos (30d): Sharpe da tendência e da diferença vs B&H
rng = np.random.default_rng(0); B = 2000; blk = 30; n = len(t)
tt, bb = t.values, bh.values
def boot(a, b):
    out = []
    for _ in range(B):
        idx = np.concatenate([np.arange(s, s + blk) % n for s in rng.integers(0, n, n // blk + 1)])[:n]
        x, y = a[idx], b[idx]
        out.append((x.mean() / x.std() * np.sqrt(365), x.mean() / x.std() * np.sqrt(365) - y.mean() / y.std() * np.sqrt(365)))
    return np.array(out)
o = boot(tt, bb)
print(f"\nBootstrap blocos 30d: Sharpe trend IC95% [{np.percentile(o[:,0],2.5):.2f}, {np.percentile(o[:,0],97.5):.2f}]; "
      f"Sharpe(trend)-Sharpe(B&H) IC95% [{np.percentile(o[:,1],2.5):.2f}, {np.percentile(o[:,1],97.5):.2f}], P(dif>0)={np.mean(o[:,1]>0):.2f}")
pd.DataFrame({"trend": t, "carry": c, "combo": combo, "bh": bh}).to_parquet(R.RES / "curves3.parquet")
