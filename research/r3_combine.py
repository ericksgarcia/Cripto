"""Análise de complementaridade: correlação entre estratégias e carteiras combinadas.

Seleção honesta: as estratégias são escolhidas pelo desempenho em 2021-2023 (SEL) e as combinações
são avaliadas em 2024-2026 (OOS), que não participou da escolha.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from engine.core import ROOT, metrics
import engine.core as core

CURVES = ROOT / "results" / "curves"
SEL = ("2021-01-01", "2023-12-31")
OOS = ("2024-01-01", "2026-10-25")


def load_all():
    eq = {}
    for p in sorted(CURVES.glob("*.parquet")):
        s = pd.read_parquet(p)["PORTFOLIO"].dropna()
        s.index = s.index.normalize()
        s = s[~s.index.duplicated(keep="last")]
        eq[p.stem] = s / s.iloc[0]
    return pd.DataFrame(eq).ffill()


def m(s, per):
    old = core.START; core.START = per[0]
    try:
        x = s[(s.index >= pd.Timestamp(per[0], tz="UTC")) & (s.index <= pd.Timestamp(per[1], tz="UTC"))].dropna()
        return metrics(x / x.iloc[0])
    finally:
        core.START = old


def combo(E, names, rebal="W"):
    """Carteira com pesos iguais entre estratégias, rebalanceada semanalmente (retornos diários)."""
    R = E[names].pct_change().fillna(0.0)
    if rebal is None:
        return (E[names] / E[names].iloc[0]).mean(axis=1)
    w = pd.Series(1 / len(names), names)
    eq, val, cur = [], 1.0, w.copy()
    last = None
    for t, r in R.iterrows():
        key = t.to_period("W")
        if key != last:
            cur = w * val; last = key
        cur = cur * (1 + r)
        val = cur.sum()
        eq.append(val)
    return pd.Series(eq, R.index)


if __name__ == "__main__":
    E = load_all()
    E = E[E.index >= pd.Timestamp("2021-01-01", tz="UTC")]
    rows = []
    for c in E:
        a, b = m(E[c], SEL), m(E[c], OOS)
        rows.append({"strategy": c, "SEL_cagr": a["cagr_%"], "SEL_sharpe": a["sharpe"], "SEL_dd": a["maxdd_%"],
                     "OOS_cagr": b["cagr_%"], "OOS_sharpe": b["sharpe"], "OOS_dd": b["maxdd_%"]})
    T = pd.DataFrame(rows).set_index("strategy").round(2).sort_values("SEL_sharpe", ascending=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    print(T.to_string())
    T.to_csv(ROOT / "results" / "r3_sel_oos.csv")
    # correlação dos retornos diários entre as melhores
    R = E.pct_change()
    good = [c for c in T.index if T.loc[c, "SEL_sharpe"] > 0.5 and c != "BuyHold"]
    C = R[good].corr().round(2)
    C.to_csv(ROOT / "results" / "r3_corr.csv")
    print("\ncorrelação (estratégias com Sharpe SEL > 0.5):\n", C.to_string())
    # combinações escolhidas no SEL
    out = {}
    for k in (2, 3, 4, 5, 8):
        names = list(T.index[:k][~T.index[:k].isin(["BuyHold"])])
        out[f"top{k}_SEL"] = (names, combo(E, names))
    # seleção gulosa por baixa correlação (no SEL): começa pela melhor e adiciona a que mais melhora o Sharpe SEL
    pool = good
    chosen = [pool[0]]
    for _ in range(4):
        best, bs = None, -9
        for c in pool:
            if c in chosen:
                continue
            s = m(combo(E, chosen + [c]), SEL)["sharpe"]
            if s > bs:
                best, bs = c, s
        chosen.append(best)
        out[f"greedy{len(chosen)}"] = (list(chosen), combo(E, chosen))
    rows = []
    for k, (names, s) in out.items():
        a, b = m(s, SEL), m(s, OOS)
        rows.append({"combo": k, "members": "+".join(names), "SEL_cagr": a["cagr_%"], "SEL_sharpe": a["sharpe"],
                     "SEL_dd": a["maxdd_%"], "OOS_cagr": b["cagr_%"], "OOS_sharpe": b["sharpe"], "OOS_dd": b["maxdd_%"]})
        s.rename(k).to_frame("PORTFOLIO").to_parquet(ROOT / "results" / f"combo_{k}.parquet")
    print(pd.DataFrame(rows).round(2).to_string(index=False))
    pd.DataFrame(rows).to_csv(ROOT / "results" / "r3_combos.csv", index=False)
