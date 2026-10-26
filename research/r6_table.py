"""Tabela mestre: todas as estratégias no mesmo período (2021-01 → 2026-10) e na janela fora da amostra."""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
from research.r3_combine import load_all, m
from engine.core import ROOT

FULL = ("2021-01-01", "2026-10-25")
OOS = ("2024-01-01", "2026-10-25")
PROJ = {"FT": "Freqtrade", "JS": "Jesse", "HB": "Hummingbot", "OB": "OctoBot", "CLAUDE": "Própria", "BuyHold": "Benchmark",
        "NFI": "NostalgiaForInfinity"}

E = load_all()
E = E[E.index >= pd.Timestamp("2021-01-01", tz="UTC")]
rows = []
for c in E:
    s = E[c].dropna()
    if s.index[0] > pd.Timestamp("2021-02-01", tz="UTC"):
        continue  # curvas de período reduzido ficam fora da tabela principal
    a, b = m(s, FULL), m(s, OOS)
    pre = c.split("_")[0]
    rows.append({"Projeto": PROJ.get(pre, pre), "Estratégia": c.split("_", 1)[-1] if "_" in c else c,
                 "Retorno total %": a["total_%"], "CAGR %": a["cagr_%"], "Max DD %": a["maxdd_%"], "Sharpe": a["sharpe"],
                 "Calmar": a["calmar"], "CAGR OOS %": b["cagr_%"], "DD OOS %": b["maxdd_%"], "Sharpe OOS": b["sharpe"]})
T = pd.DataFrame(rows).sort_values("CAGR %", ascending=False).round(2)
T.to_csv(ROOT / "results" / "ranking_geral.csv", index=False)
with open(ROOT / "results" / "ranking_geral.md", "w") as f:
    f.write(T.to_markdown(index=False, floatfmt=".2f"))
print(T.to_string(index=False))
