"""Fase 7 — avaliação do motor de confluência: poder preditivo (IC), retorno por faixa de confiança e carteira.

Carteira: a cada hora, entra nas moedas cujo placar previsto está acima do quantil q dos placares das 30 dias
anteriores (só passado). Segura H horas, no máx. `slots` posições de 1/slots do patrimônio (sem alavancagem),
1 posição por moeda. Custos: taker 0,14% ida+volta (0,05%+0,02% por lado) ou maker 0,04% (ordens limitadas).
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import numpy as np, pandas as pd
from engine.core import ROOT

H = int(sys.argv[1]) if len(sys.argv) > 1 else 4
OUT = ROOT / "results/r28"
P = pd.read_parquet(OUT / f"preds_H{H}.parquet").dropna(subset=["fwd"])
P = P.sort_values("t")
pd.set_option("display.width", 250)

# 1) IC
ic = P.groupby("t").apply(lambda g: g.pred.corr(g.fwd, method="spearman") if len(g) > 5 else np.nan).dropna()
print("IC médio por ano:", ic.groupby(ic.index.year).mean().round(3).to_dict(), " t:", round(ic.mean() / ic.std() * np.sqrt(len(ic) / H), 1))

# 2) retorno médio por faixa de confiança (percentil do placar contra os 30 dias anteriores, todas as moedas)
roll = P.set_index("t").pred
thr = {}
for q in (0.95, 0.98, 0.99, 0.995, 0.999):
    thr[q] = roll.rolling("30D").quantile(q).groupby(level=0).last().shift(1)  # só placares anteriores
P = P.set_index("t")
for q, s in thr.items():
    P[f"q{q}"] = s.reindex(P.index)
P = P.reset_index()
rows = []
for q in thr:
    sel = P[P.pred > P[f"q{q}"]]
    for yr, g in sel.groupby(sel.t.dt.year):
        rows.append({"faixa": f"top {round((1-q)*100,1)}%", "ano": yr, "n": len(g), "fwd_bruto_%": g.fwd.mean() * 100,
                     "acerto_%": (g.fwd > 0.0014).mean() * 100})
T = pd.DataFrame(rows).pivot(index="faixa", columns="ano", values="fwd_bruto_%").round(3)
print(f"\nretorno bruto médio por operação (%) em {H}h, por faixa de confiança e ano:\n", T.to_string())
allp = P.groupby(P.t.dt.year).fwd.mean() * 100
print("média de todas as moedas/horas (referência):", allp.round(3).to_dict())


# 3) carteira
def portfolio(sel, slots, cost):
    sel = sel.sort_values(["t", "pred"], ascending=[True, False])
    eq = 1.0; open_ = []; curve = []; busy = {}
    for t, sym, fwd in zip(sel.t.values, sel.sym.values, sel.fwd.values):
        t_out = t + np.timedelta64(H + 1, "h")
        still = []
        for (to, notional, r, s) in open_:
            if to <= t:
                eq += notional * (r - cost); curve.append((to, eq)); busy.pop(s, None)
            else:
                still.append((to, notional, r, s))
        open_ = still
        if len(open_) < slots and sym not in busy:
            open_.append((t_out, eq / slots, fwd, sym)); busy[sym] = t_out
    for (to, notional, r, s) in sorted(open_):
        eq += notional * (r - cost); curve.append((to, eq))
    return pd.Series(dict(curve)).sort_index()


out = []
curves = {}
for q in thr:
    sel = P[P.pred > P[f"q{q}"]]
    for slots in (3, 5, 10):
        for cname, cost in (("taker", 0.0014), ("maker", 0.0004)):
            c = portfolio(sel, slots, cost)
            if len(c) < 10:
                continue
            d = c.resample("1D").last().ffill()
            d.index = d.index.tz_localize("UTC") if d.index.tz is None else d.index
            for lab, a in (("2022H2-26", "2022-07-01"), ("2024-26", "2024-01-01")):
                x = d[d.index >= a]
                x = pd.concat([pd.Series([d[d.index < a].iloc[-1] if (d.index < a).any() else 1.0], [pd.Timestamp(a, tz="UTC")]), x])
                yrs = (x.index[-1] - x.index[0]).days / 365.25
                cg = (x.iloc[-1] / x.iloc[0]) ** (1 / yrs) - 1
                mo = x.resample("ME").last().pct_change().dropna()
                out.append({"faixa": f"top {round((1-q)*100,1)}%", "slots": slots, "custo": cname, "período": lab,
                            "ops": len(sel), "CAGR_%": cg * 100, "mês_%": ((1 + cg) ** (1 / 12) - 1) * 100,
                            "mediana_mês_%": mo.median() * 100, "meses≥5%": f"{(mo >= .05).sum()}/{len(mo)}",
                            "DD_%": (x / x.cummax() - 1).min() * 100})
            curves[f"{q}|{slots}|{cname}"] = d
R = pd.DataFrame(out).round(2)
R.to_csv(OUT / f"portfolio_H{H}.csv", index=False)
print("\n", R.sort_values(["custo", "período", "CAGR_%"], ascending=[False, True, False]).to_string(index=False))
pd.DataFrame(curves).to_parquet(OUT / f"curves_H{H}.parquet")
