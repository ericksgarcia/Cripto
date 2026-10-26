"""Varredura de rotação por momentum (DEV 2018-2023 para escolha, OOS 2024-2026 só para relatório)."""
import warnings; warnings.filterwarnings("ignore")
import itertools, sys
import pandas as pd
from engine.mine import *

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
univ = sys.argv[1] if len(sys.argv) > 1 else "10"
if univ == "10":
    D = data("1d"); el = None
else:
    D = data_universe("1d"); el = eligible(D, 1, int(univ))
res = {}
for look, top, regime, reg_n, coin_ma, vt, wt in itertools.product(
        [14, 21, 30], [3, 5], ["btc", "breadth", "both"], [50, 100, 200], [0, 50], [None, 0.6], ["equal", "invvol"]):
    w = s_rotation(D, 1, look, top, el, regime, reg_n, coin_ma, vt, 30, wt)
    res[f"l{look}_t{top}_{regime}{reg_n}_ma{coin_ma}_vt{vt}_{wt}"] = evaluate(w, D)
df = summarize(res).sort_values("DEV_sharpe", ascending=False)
df.to_csv(f"results/r1_rotation_U{univ}.csv")
print(df.head(40).to_string())
print("\nmedianas por fator (DEV_sharpe / OOS_sharpe):")
for i, f in enumerate(["look", "top", "regime", "ma", "vt", "wt"]):
    key = df.index.str.split("_").str[i]
    print(f, df.groupby(key)[["DEV_sharpe", "OOS_sharpe", "DEV_dd", "OOS_dd"]].median().round(2).to_dict("index"))
