"""Fase 3 — análise da busca de variações (r11): robustez DEV→OOS, efeito de cada dimensão,
seletor walk-forward (escolhe pelo passado, roda o trimestre seguinte) e ensembles."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from engine.core import ROOT
from research.r11_variants import stats, DEV, OOS

pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
T = pd.read_csv(ROOT / "results/r11_variants.csv")
R = pd.read_parquet(ROOT / "results/r11_returns.parquet").astype(np.float64)
R = R[R.index >= pd.Timestamp("2020-07-01", tz="UTC")]
print(f"variantes: {len(T)}")
print("correlação (Spearman) Sharpe DEV x OOS:", round(T.DEV_sharpe.corr(T.OOS_sharpe, method="spearman"), 3))
T["dec"] = pd.qcut(T.DEV_sharpe.rank(method="first"), 10, labels=False)
print("\nOOS por decil de Sharpe no DEV (9 = melhores):")
print(T.groupby("dec")[["DEV_sharpe", "DEV_cagr", "OOS_sharpe", "OOS_cagr", "OOS_dd"]].median().round(2).to_string())

print("\nEfeito marginal de cada dimensão (mediana DEV/OOS Sharpe e CAGR OOS):")
dims = ["look", "kind", "top", "N", "regime", "coin_ma", "rebal", "buffer", "short_w", "wmode", "vt", "min_age", "maxvol", "dstop"]
for d in dims:
    g = T.groupby(d)[["DEV_sharpe", "OOS_sharpe", "OOS_cagr", "OOS_dd"]].median().round(2)
    print(f"\n[{d}]\n" + g.sort_values("DEV_sharpe", ascending=False).to_string())

# ---------------- seletor walk-forward
def wf_select(R, lookback=365, k=1, metric="sharpe", start="2021-07-01"):
    out = pd.Series(0.0, R.index)
    picks = []
    for q in pd.date_range(pd.Timestamp(start, tz="UTC"), R.index[-1], freq="QS"):
        hist = R[(R.index < q) & (R.index >= q - pd.Timedelta(days=lookback))]
        if metric == "sharpe":
            sc = hist.mean() / hist.std()
        else:
            sc = np.log1p(hist.clip(lower=-0.99)).sum()
        best = sc.nlargest(k).index
        nxt = (R.index >= q) & (R.index < q + pd.offsets.QuarterBegin(1, startingMonth=1))
        out[nxt] = R.loc[nxt, best].mean(axis=1)
        picks.append((q.date(), list(best[:3])))
    return out[out.index >= pd.Timestamp(start, tz="UTC")], picks

rows = []
def add(name, r):
    for lab, per in (("2021H2-2023", ("2021-07-01", DEV[1])), ("OOS 2024-26", OOS), ("2021H2-2026", ("2021-07-01", OOS[1]))):
        c, s, d = stats(r, *per)
        rows.append({"estratégia": name, "período": lab, "CAGR %": c * 100, "mês %": ((1 + c) ** (1 / 12) - 1) * 100,
                     "Sharpe": s, "MaxDD %": d * 100})

for lb in (180, 365, 730):
    for k in (1, 5, 20):
        for met in ("sharpe", "ret"):
            r, picks = wf_select(R, lb, k, met)
            add(f"WF_lb{lb}_k{k}_{met}", r)
# ensembles fixos escolhidos no DEV (válidos só no OOS)
top_dev = T.nlargest(20, "DEV_sharpe").name.tolist()
add("ENS_top20_DEV", R[top_dev].mean(axis=1))
add("TOP1_DEV", R[top_dev[0]])
base = T.iloc[0].name if "name" in T else None
add("BASE_rot5_fase1", R[T.name.iloc[0]])
add("ROT3_short_fase2", R[T.name.iloc[1]])
W = pd.DataFrame(rows)
W.to_csv(ROOT / "results/r14_walkforward.csv", index=False)
print("\n" + W.pivot_table(index="estratégia", columns="período", values=["CAGR %", "Sharpe", "MaxDD %"]).round(2).to_string())
print("\nmelhor variante DEV:", top_dev[0])
