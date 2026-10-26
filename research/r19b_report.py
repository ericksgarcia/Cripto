"""Relatório corrigido do estudo de evento: excesso = retorno do padrão - média das entradas aleatórias (controle)
de TODAS as moedas elegíveis na mesma semana (remove o movimento do mercado, preserva o timing do padrão)."""
import warnings; warnings.filterwarnings("ignore")
import sys
import numpy as np, pandas as pd
from engine.core import ROOT

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)


def stats(g):
    w = g.groupby("wk").exc.mean()
    tstat = w.mean() / w.std() * np.sqrt(len(w)) if len(w) > 2 and w.std() > 0 else np.nan
    yrs = g.groupby(g.t.dt.year).exc.mean()
    return pd.Series({"n": len(g), "ret_%": g.ret.mean() * 100, "acerto_%": (g.ret > 0).mean() * 100,
                      "excesso_%": g.exc.mean() * 100, "t": tstat, "anos+": f"{(yrs > 0).sum()}/{len(yrs)}"})


for tf in sys.argv[1:] or ["4h", "1d"]:
    E = pd.read_parquet(ROOT / f"results/r19_events_{tf}.parquet")
    E["wk"] = E.t.dt.to_period("W")
    ctrl = E[E.padrao == "_CONTROLE_todas_barras"]
    for key, mask in (("all", None), ("mr", True)):
        pass
    bench_all = ctrl.groupby("wk").ret.mean()
    bench_mr = ctrl[ctrl.mtf & ctrl.regime].groupby("wk").ret.mean()
    E = E[E.padrao != "_CONTROLE_todas_barras"].copy()
    E["per"] = np.where(E.t < pd.Timestamp("2024-01-01", tz="UTC"), "DEV", "OOS")
    out = []
    for flt, mask, bench in (("todos", E.padrao.notna(), bench_all), ("MTF+regime", E.mtf & E.regime, bench_all)):
        x = E[mask].copy()
        x["exc"] = x.ret - x.wk.map(bench).fillna(0)
        parts = []
        for per in ("DEV", "OOS"):
            s = x[x.per == per].groupby("padrao").apply(stats)
            s.columns = [f"{per}_{c}" for c in s.columns]
            parts.append(s)
        s = pd.concat(parts, axis=1); s.insert(0, "filtro", flt)
        out.append(s)
    T = pd.concat(out)
    T.to_csv(ROOT / f"results/r19_ta_{tf}.csv")
    print(f"\n===== {tf}: excesso vs. entradas aleatórias da mesma semana (custos incluídos) =====")
    print(T.round(2).sort_values(["filtro", "DEV_excesso_%"], ascending=[False, False]).to_string())
