"""Fase 2 — candidatas finais e distribuição de retornos MENSAIS (2022-01 → 2026-10, janela com NFI)."""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from engine.core import ROOT

def load(p, col="PORTFOLIO"):
    s = pd.read_parquet(p)[col].dropna(); s.index = s.index.normalize(); return s[~s.index.duplicated(keep="last")]

C = pd.read_parquet(ROOT / "results/r9_curves.parquet")
C.index = C.index.normalize()
S = pd.DataFrame({
    "Rot5 spot (fase 1)": load(ROOT / "results/curves/CLAUDE_Rotation5.parquet"),
    "Rot top3 + short piores (perp, U10)": C["ROT_both_U10_t3"],
    "Rot top3 perp U10": C["ROT_long_U10_t3"],
    "NFI X7": load(ROOT / "results/curves/FT_NostalgiaForInfinityX7_2022.parquet"),
}).ffill()
S = S[S.index >= "2022-01-01"].dropna()
R = S.pct_change().fillna(0)
R["Rot5 + NFI"] = 0.5 * R["Rot5 spot (fase 1)"] + 0.5 * R["NFI X7"]
R["RotLS + NFI"] = 0.5 * R["Rot top3 + short piores (perp, U10)"] + 0.5 * R["NFI X7"]
for L in (2, 3):
    fund = (L - 1) * 0.11 / 365
    R[f"RotLS + NFI  {L}x"] = L * R["RotLS + NFI"] - fund * 0.6
rows = []
for c in R:
    eq = (1 + R[c].clip(lower=-1)).cumprod()
    mo = eq.resample("ME").last().pct_change(); mo.iloc[0] = eq.resample("ME").last().iloc[0] - 1
    yrs = len(eq) / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    rows.append({"estratégia": c, "CAGR %": cagr * 100, "média geom. mês %": ((1 + cagr) ** (1 / 12) - 1) * 100,
                 "mediana mês %": mo.median() * 100, "melhor mês %": mo.max() * 100, "pior mês %": mo.min() * 100,
                 "meses ≥ 20%": f"{(mo >= .2).sum()}/{len(mo)}", "meses < 0": f"{(mo < 0).sum()}/{len(mo)}",
                 "Max DD %": (eq / eq.cummax() - 1).min() * 100})
T = pd.DataFrame(rows).round(1)
T.to_csv(ROOT / "results/r10_mensal.csv", index=False)
pd.set_option("display.width", 250)
print(T.to_string(index=False))
