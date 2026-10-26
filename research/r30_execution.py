"""Fase 7 — execução realista para o motor de confluência (seleção adversa de ordens limitadas).

Sinal no fechamento da hora t. Cenários:
  A) a mercado: compra na abertura t+1 e vende na abertura t+1+H; taker 0,07%/lado (0,05% taxa + 0,02% slippage).
  B) limitada na entrada: ordem de compra em close[t]*(1-δ), válida por 1 hora; só executa se a mínima da hora t+1
     tocar o preço (se abrir abaixo, executa na abertura). Saída a mercado. Custo 0,02% + 0,07%.
  C) limitada na entrada e na saída: venda limitada na abertura de t+1+H, válida 1h (executa se a máxima tocar);
     se não executar, sai a mercado na abertura seguinte. Custo 0,02%(+0,02% ou 0,07%).
Ordens não executadas = operação perdida (captura a seleção adversa: as que disparam direto não entram).
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import numpy as np, pandas as pd
from engine.core import ROOT, AGG

H = int(sys.argv[1]) if len(sys.argv) > 1 else 4
TT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0  # "trade-through": preço precisa passar o limite em TT para executar
OUT = ROOT / "results/r28"
P = pd.read_parquet(OUT / f"preds_H{H}.parquet").dropna(subset=["fwd"]).sort_values("t")
pd.set_option("display.width", 250)

px = {}
for s in P.sym.unique():
    base = s[4:] if s.startswith("1000") else s
    d = pd.read_parquet(ROOT / "data/ta_1h" / f"{base}.parquet").loc["2022-01-01":].resample("1h").agg(AGG).dropna()
    px[s] = d

roll = P.set_index("t").pred
thr = {q: roll.rolling("30D").quantile(q).groupby(level=0).last().shift(1) for q in (0.95, 0.98, 0.99, 0.995)}


def trade_returns(sel, mode, delta):
    """Retorno líquido de cada sinal sob o cenário de execução (NaN = não executou)."""
    out = np.full(len(sel), np.nan)
    for i, (t, s) in enumerate(zip(sel.t, sel.sym)):
        d = px[s]
        try:
            k = d.index.get_loc(t)
        except KeyError:
            continue
        if k + H + 2 >= len(d):
            continue
        c_t = d.close.iloc[k]; o1 = d.open.iloc[k + 1]; l1 = d.low.iloc[k + 1]
        ox = d.open.iloc[k + 1 + H]
        if mode == "A":
            out[i] = ox / o1 - 1 - 0.0014
            continue
        lim = c_t * (1 - delta)
        if o1 <= lim:
            entry = o1
        elif l1 <= lim * (1 - TT):
            entry = lim
        else:
            continue  # não executou
        if mode == "B":
            out[i] = ox / entry - 1 - 0.0009
        else:  # C: venda limitada na abertura da hora de saída, válida 1h
            hx = d.high.iloc[k + 1 + H]
            if hx >= ox * 1.0005 * (1 + TT):
                out[i] = ox * 1.0005 / entry - 1 - 0.0004
            else:
                out[i] = d.open.iloc[k + 2 + H] / entry - 1 - 0.0009
    return out


def portfolio(sel, slots):
    sel = sel.dropna(subset=["r"]).sort_values(["t", "pred"], ascending=[True, False])
    eq = 1.0; open_ = []; curve = []; busy = set()
    for t, sym, r in zip(sel.t.values, sel.sym.values, sel.r.values):
        t_out = t + np.timedelta64(H + 1, "h")
        still = []
        for (to, notional, rr, s) in open_:
            if to <= t:
                eq += notional * rr; curve.append((to, eq)); busy.discard(s)
            else:
                still.append((to, notional, rr, s))
        open_ = still
        if len(open_) < slots and sym not in busy:
            open_.append((t_out, eq / slots, r, sym)); busy.add(sym)
    for (to, notional, rr, s) in sorted(open_):
        eq += notional * rr; curve.append((to, eq))
    c = pd.Series(dict(curve)).sort_index()
    c.index = pd.to_datetime(c.index, utc=True)
    return c


rows, curves = [], {}
for q, th in thr.items():
    sel = P.merge(th.rename("thr"), left_on="t", right_index=True)
    sel = sel[sel.pred > sel.thr].copy()
    for mode, delta in (("A", 0), ("B", 0.0), ("B", 0.002), ("C", 0.0), ("C", 0.002)):
        sel["r"] = trade_returns(sel, mode, delta)
        fill = sel.r.notna().mean()
        for slots in (5, 10):
            c = portfolio(sel, slots)
            d = c.resample("1D").last().ffill()
            for lab, a in (("2022H2-26", "2022-07-01"), ("2024-26", "2024-01-01")):
                x = d[d.index >= a]
                yrs = (x.index[-1] - x.index[0]).days / 365.25
                cg = (x.iloc[-1] / x.iloc[0]) ** (1 / yrs) - 1
                mo = x.resample("ME").last().pct_change().dropna()
                rows.append({"faixa": f"top {round((1-q)*100,1)}%", "execução": f"{mode} δ={delta*100:.1f}%", "slots": slots,
                             "período": lab, "executadas_%": fill * 100, "ret_médio_op_%": sel.r.mean() * 100,
                             "CAGR_%": cg * 100, "mês_%": ((1 + cg) ** (1 / 12) - 1) * 100,
                             "meses≥5%": f"{(mo >= .05).sum()}/{len(mo)}", "meses<0": f"{(mo < 0).sum()}/{len(mo)}",
                             "DD_%": (x / x.cummax() - 1).min() * 100})
            curves[f"{q}|{mode}{delta}|{slots}"] = d
        print(q, mode, delta, flush=True)
R = pd.DataFrame(rows).round(2)
R.to_csv(OUT / f"execution_H{H}_tt{TT}.csv", index=False)
pd.DataFrame(curves).to_parquet(OUT / f"exec_curves_H{H}_tt{TT}.parquet")
print(R[R.período == "2024-26"].sort_values("CAGR_%", ascending=False).head(25).to_string(index=False))
print(R[R.período == "2022H2-26"].sort_values("CAGR_%", ascending=False).head(12).to_string(index=False))
