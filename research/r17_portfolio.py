"""Fase 3 — carteira final de componentes + alavancagem + distribuição mensal (honesta).

Componentes (retornos diários):
  ROT  : rotação em perps, subfamília a priori (N<=10 mais líquidas, vol<=100%/ano, regime BTC, sem stop);
         ensemble das 10 melhores dessa subfamília pelo DEV (2020-07..2023-12), sem olhar 2024-26.
  NFI  : NostalgiaForInfinity X7 (freqtrade, 2022+).
  DIP  : compra de crash extremo em 1m (z>8 em 60 min, segura 4h), 4 vagas de 20%.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from engine.core import ROOT
from research.r16_events import gen_trades, portfolio, SYMS

pd.set_option("display.width", 250)
T = pd.read_csv(ROOT / "results/r11_variants.csv")
R = pd.read_parquet(ROOT / "results/r11_returns.parquet").astype(float)
sub = T[T.N.astype(str).isin(["5", "8", "10"]) & (T.maxvol.astype(float) == 1.0) & (T.dstop.astype(float) == 0)
        & T.regime.isin(["btc50", "btc100"])]
top10 = sub.nlargest(10, "DEV_sharpe")
print("subfamília:", len(sub), "variantes; top10 DEV:")
print(top10[["name", "DEV_cagr", "DEV_sharpe", "DEV_dd", "OOS_cagr", "OOS_sharpe", "OOS_dd"]].round(2).to_string(index=False))
rot = R[top10.name].mean(axis=1)
rot1 = R[top10.name.iloc[0]]

# DIP: curva diária
c, n = portfolio(gen_trades(SYMS, "dip", 60, 8.0, 240, {}), 0.2, 4, 0.0015)
dip = c.resample("1D").last().ffill().reindex(rot.index).ffill().fillna(1.0).pct_change().fillna(0)

nfi = pd.read_parquet(ROOT / "results/curves/FT_NostalgiaForInfinityX7_2022.parquet")["PORTFOLIO"]
nfi.index = nfi.index.normalize(); nfi = nfi[~nfi.index.duplicated()].reindex(rot.index).ffill()
nfi_r = nfi.pct_change().fillna(0)

C = pd.DataFrame({"ROT_ens10": rot, "ROT_top1": rot1, "NFI": nfi_r, "DIP": dip})
C = C[C.index >= pd.Timestamp("2022-01-01", tz="UTC")]
print("\ncorrelações diárias 2022-26:\n", C.corr().round(2).to_string())
C["ROT+NFI"] = 0.5 * C.ROT_ens10 + 0.5 * C.NFI
C["ROT+NFI+DIP"] = (C.ROT_ens10 + C.NFI + C.DIP) / 3
C["RiskParity"] = 0
vol = C[["ROT_ens10", "NFI", "DIP"]].rolling(90, min_periods=30).std().shift(1)
w = (1 / vol).div((1 / vol).sum(axis=1), axis=0).fillna(1 / 3)
C["RiskParity"] = (w * C[["ROT_ens10", "NFI", "DIP"]]).sum(axis=1)
for L in (2, 3, 4):
    C[f"RiskParity {L}x"] = L * C.RiskParity - (L - 1) * 0.11 / 365 * 0.5

rows = []
for col in C:
    for lab, a, b in (("2022-26", "2022-01-01", "2026-10-25"), ("2024-26 (OOS)", "2024-01-01", "2026-10-25")):
        x = C.loc[a:b, col]
        eq = (1 + x.clip(lower=-1)).cumprod()
        yrs = len(x) / 365.25
        cagr = eq.iloc[-1] ** (1 / yrs) - 1
        mo = eq.resample("ME").last().pct_change().fillna(eq.resample("ME").last().iloc[0] - 1)
        rows.append({"carteira": col, "período": lab, "CAGR %": cagr * 100, "mês médio %": ((1 + cagr) ** (1 / 12) - 1) * 100,
                     "mediana mês %": mo.median() * 100, "pior mês %": mo.min() * 100, "meses ≥10%": int((mo >= .1).sum()),
                     "meses": len(mo), "MaxDD %": (eq / eq.cummax() - 1).min() * 100,
                     "Sharpe": x.mean() / x.std() * np.sqrt(365)})
out = pd.DataFrame(rows).round(1)
out.to_csv(ROOT / "results/r17_portfolio.csv", index=False)
print(out.to_string(index=False))
C.to_parquet(ROOT / "results/r17_components.parquet")
