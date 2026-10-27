"""Fase 7c — consenso entre motores de vários tempos gráficos (1h, 15m, 5m), horizonte 12h.

Cada modelo dá um placar por moeda; convertemos em percentil contra os 30 dias anteriores do próprio modelo
(só passado). Alinhamento no fechamento da hora: 1h (barra t), 15m (barra t+45min), 5m (barra t+55min).
Regras: (a) média dos percentis acima do limiar; (b) TODOS acima do limiar (coincidência estrita).
Execução realista na grade de 1h (como r30): ordem limitada 0,2% abaixo, válida 1h, trade-through 0,05%.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from engine.core import ROOT, AGG

H = 12
TT = 0.0005
pd.set_option("display.width", 250)


def pct_vs_past(P):
    P = P.sort_values("t")
    r = P.set_index("t").pred
    out = {}
    for q in (0.9, 0.95, 0.98, 0.99):
        out[q] = r.rolling("30D").quantile(q).groupby(level=0).last().shift(1)
    return out


def load(path, shift_min):
    P = pd.read_parquet(path)[["t", "sym", "pred", "fwd"]]
    if shift_min:
        P = P[P.t.dt.minute == shift_min].copy(); P["t"] = P.t - pd.Timedelta(minutes=shift_min)
    return P


M = {"1h": load(ROOT / "results/r28/preds_H12.parquet", 0),
     "15m": load(ROOT / "results/r31/15min/preds_48.parquet", 45),
     "5m": load(ROOT / "results/r31/5min/preds_144.parquet", 55)}
TH = {k: pct_vs_past(v) for k, v in M.items()}

px = {}


def price(s):
    if s not in px:
        base = s[4:] if s.startswith("1000") else s
        px[s] = pd.read_parquet(ROOT / "data/ta_1h" / f"{base}.parquet").loc["2022-01-01":].resample("1h").agg(AGG).dropna()
    return px[s]


def trade_r(t, s, delta=0.002):
    d = price(s)
    k = d.index.searchsorted(t)
    if k >= len(d) or d.index[k] != t or k + H + 2 >= len(d):
        return np.nan
    c = d.close.iat[k]; o1 = d.open.iat[k + 1]; l1 = d.low.iat[k + 1]; ox = d.open.iat[k + 1 + H]
    lim = c * (1 - delta)
    if o1 <= lim:
        return ox / o1 - 1 - 0.0009
    if l1 <= lim * (1 - TT):
        return ox / lim - 1 - 0.0009
    return np.nan


def portfolio(sel, slots):
    sel = sel.dropna(subset=["r"]).sort_values(["t", "score"], ascending=[True, False])
    eq = 1.0; open_ = []; curve = []; busy = set()
    for t, sym, r in zip(sel.t.values, sel.sym.values, sel.r.values):
        still = []
        for (to, n, rr, s) in open_:
            if to <= t:
                eq += n * rr; curve.append((to, eq)); busy.discard(s)
            else:
                still.append((to, n, rr, s))
        open_ = still
        if len(open_) < slots and sym not in busy:
            open_.append((t + np.timedelta64(H + 1, "h"), eq / slots, r, sym)); busy.add(sym)
    for (to, n, rr, s) in sorted(open_):
        eq += n * rr; curve.append((to, eq))
    c = pd.Series(dict(curve)).sort_index(); c.index = pd.to_datetime(c.index, utc=True)
    return c


rows = []
for combo in (("1h",), ("1h", "15m"), ("1h", "15m", "5m"), ("15m", "5m")):
    J = None
    for k in combo:
        x = M[k].rename(columns={"pred": f"p_{k}"})
        for q, th in TH[k].items():
            x[f"ok{q}_{k}"] = x[f"p_{k}"] > x.t.map(th)
        J = x if J is None else J.merge(x.drop(columns="fwd"), on=["t", "sym"])
    for q in (0.9, 0.95, 0.98):
        for rule in ("todos", "maioria"):
            oks = J[[f"ok{q}_{k}" for k in combo]]
            m = oks.all(axis=1) if rule == "todos" else (oks.sum(axis=1) >= (len(combo) // 2 + 1))
            sel = J[m].copy()
            if len(sel) < 50:
                continue
            sel["score"] = sel[[f"p_{k}" for k in combo]].rank(pct=True).mean(axis=1)
            sel["r"] = [trade_r(t, s) for t, s in zip(sel.t, sel.sym)]
            for slots in (5,):
                c = portfolio(sel, slots); d = c.resample("1D").last().ffill()
                for lab, a in (("2022H2-26", "2022-07-01"), ("2024-26", "2024-01-01")):
                    x = d[d.index >= a]; yrs = (x.index[-1] - x.index[0]).days / 365.25
                    cg = (x.iloc[-1] / x.iloc[0]) ** (1 / yrs) - 1
                    mo = x.resample("ME").last().pct_change().dropna()
                    rows.append({"modelos": "+".join(combo), "limiar": f"top {round((1-q)*100)}%", "regra": rule,
                                 "moedas": sel.sym.nunique(), "sinais": len(sel), "ret_op_%": sel.r.mean() * 100,
                                 "período": lab, "CAGR_%": cg * 100, "mês_%": ((1 + cg) ** (1 / 12) - 1) * 100,
                                 "meses<0": f"{(mo < 0).sum()}/{len(mo)}", "DD_%": (x / x.cummax() - 1).min() * 100})
        print(combo, q, flush=True)
T = pd.DataFrame(rows).round(2)
T.to_csv(ROOT / "results/r32_consensus.csv", index=False)
for per in ("2022H2-26", "2024-26"):
    print(f"\n== {per} ==")
    print(T[T.período == per].sort_values("mês_%", ascending=False).head(15).to_string(index=False))
