"""Gráficos do relatório: curva de patrimônio (escala log) e drawdown das melhores de cada projeto."""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from research.r3_combine import load_all
from engine.core import ROOT

SERIES = [  # ordem categórica fixa (paleta de referência)
    ("CLAUDE_Rotation5", "Claude: Rotação momentum (top 5)", "#2a78d6"),
    ("combo_greedy2", "Combo: Rotação5 + MultiMa", "#eb6834"),
    ("FT_MultiMa", "Freqtrade: MultiMa", "#1baf7a"),
    ("JS_Donchian", "Jesse: Donchian", "#eda100"),
    ("OB_grid", "OctoBot: Grid", "#e87ba4"),
    ("BuyHold", "Buy & Hold (10 moedas)", "#52514e"),
]

E = load_all()
c = pd.read_parquet(ROOT / "results" / "combo_greedy2.parquet")["PORTFOLIO"]
c.index = c.index.normalize(); E["combo_greedy2"] = c / c.iloc[0]
E = E[E.index >= pd.Timestamp("2021-01-01", tz="UTC")].ffill()

plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#c3c2b7", "axes.labelcolor": "#52514e", "xtick.color": "#52514e",
                     "ytick.color": "#52514e", "axes.grid": True, "grid.color": "#e8e7e2", "grid.linewidth": 0.6})
fig, ax = plt.subplots(2, 1, figsize=(11, 8), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]}, facecolor="#fcfcfb")
for a in ax:
    a.set_facecolor("#fcfcfb")
for key, label, col in SERIES:
    s = E[key].dropna()
    lw = 2.4 if key.startswith(("CLAUDE", "combo")) else 1.6
    ls = "--" if key == "BuyHold" else "-"
    ax[0].plot(s.index, s.values, color=col, lw=lw, ls=ls, label=label)
    dd = s / s.cummax() - 1
    ax[1].plot(dd.index, dd.values * 100, color=col, lw=1.2 if key != "BuyHold" else 1.0, ls=ls)
import numpy as np
ends = sorted(((E[k].dropna().iloc[-1], E[k].dropna().index[-1]) for k, _, _ in SERIES), key=lambda x: x[0])
placed = []
for v, t in ends:  # rótulos finais sem sobreposição (distância mínima em escala log)
    y = np.log10(v)
    if placed and y - placed[-1] < 0.07:
        y = placed[-1] + 0.07
    placed.append(y)
    ax[0].annotate(f"{v:.1f}x", (t, 10 ** y), xytext=(4, 0), textcoords="offset points", color="#0b0b0b", fontsize=9, va="center")
ax[0].set_yscale("log"); ax[0].set_ylabel("Patrimônio (múltiplo do capital, log)")
ax[0].axvline(pd.Timestamp("2024-01-01", tz="UTC"), color="#9a998f", lw=1, ls=":")
ax[0].text(pd.Timestamp("2024-01-15", tz="UTC"), ax[0].get_ylim()[1] * 0.6, "fora da amostra →", color="#52514e", fontsize=9)
ax[0].legend(loc="upper left", frameon=False, fontsize=9)
ax[0].set_title("Melhor estratégia de cada projeto vs. estratégia própria — 10 pares Binance spot, taxa 0,1% + slippage",
                fontsize=11, loc="left", color="#0b0b0b")
ax[1].set_ylabel("Drawdown (%)")
ax[1].axvline(pd.Timestamp("2024-01-01", tz="UTC"), color="#9a998f", lw=1, ls=":")
fig.tight_layout()
fig.savefig(ROOT / "results" / "equity_drawdown.png", dpi=130)
print("ok")
