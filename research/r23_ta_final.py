"""Fase 4 — (a) rompimento 4h nas top-K moedas por volume spot (point-in-time), K=2,3,5;
(b) carteira final SEM alavancagem com sistemas de leitura de gráfico: Rompimento grandes (4h), Rotação v2
(força relativa + médias) e NFI (compra de quedas multi-indicador). Pesos iguais, rebalanceamento semanal."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from engine.core import ROOT, AGG
from research.ta.patterns import detect_all, atr
from research.r21_ta_portfolio import trade_ix, perf
from research.r11_variants import load_spot

COST = 0.0012
PATS = [8, 10, 9]  # VCP + Donchian55 c/ volume + Squeeze TTM
TRAIL, MB = 4.0, 120

D = load_spot()
V = D["V"].rolling(30, min_periods=20).mean().where(D["C"].notna().cumsum() >= 60)
rank = V.rank(axis=1, ascending=False)


def system(K):
    elig = (rank <= K)
    coins = sorted(set(elig.columns[elig.any()]) & {p.stem for p in (ROOT / "data/ta_1h").glob("*.parquet")})
    rets = {}
    ntr = 0
    for s in coins:
        d = pd.read_parquet(ROOT / "data/ta_1h" / f"{s}.parquet").resample("4h").agg(AGG).dropna()
        if len(d) < 400:
            continue
        o, h, l, c, v = (d[x].values.astype(np.float64) for x in ("open", "high", "low", "close", "volume"))
        S, ST = detect_all(o, h, l, c, v, 3); A = atr(h, l, c, 14)
        el = elig[s].reindex(d.index.normalize()).fillna(False).values.astype(bool)
        sig = np.zeros(len(c), bool); stp = np.full(len(c), np.nan)
        for pi in PATS:
            m = S[pi] & np.isnan(stp); stp[m] = ST[pi][m]; sig |= S[pi]
        sig &= el
        r = pd.Series(0.0, d.index); t = 0
        while t < len(c) - 1:
            if sig[t]:
                rr, ex = trade_ix(o, h, l, c, A, t, stp[t], 0.0, TRAIL, MB, 1.0, 4.0)
                if ex > 0:
                    r.iloc[ex] += rr - 2 * COST; ntr += 1; t = ex; continue
            t += 1
        rets[s] = r.resample("1D").apply(lambda x: (1 + x).prod() - 1)
    R = pd.DataFrame(rets).fillna(0.0)
    return R.sum(axis=1) / K, ntr  # cada moeda elegível usa 1/K do capital


rows = []
sysr = {}
for K in (2, 3, 5):
    r, n = system(K)
    sysr[K] = r
    eq = (1 + r).cumprod()
    d, o, a = perf(eq, "2018-03-01", "2023-12-31"), perf(eq, "2024-01-01", "2026-10-24"), perf(eq, "2022-01-01", "2026-10-24")
    rows.append({"sistema": f"Rompimento 4h top-{K}", "ops": n, "DEV_cagr": d[0], "DEV_dd": d[1], "OOS_cagr": o[0], "OOS_dd": o[1],
                 "OOS_mes_%": o[2], "2022-26_cagr": a[0], "2022-26_dd": a[1]})
print(pd.DataFrame(rows).round(1).to_string(index=False))

# carteira final
brk = sysr[2]
rot = pd.read_parquet(ROOT / "results/rot_v2_returns.parquet")["ROTv2"]
nfi = pd.read_parquet(ROOT / "results/r18_components.parquet")["NFI25"]
idx = pd.date_range("2022-01-01", "2026-10-24", freq="1D", tz="UTC")
for s in (brk, rot, nfi):
    s.index = s.index.normalize()
C = pd.DataFrame({"Rompimento BTC/ETH": brk.reindex(idx).fillna(0), "Rotação v2": rot.reindex(idx).fillna(0),
                  "NFI": nfi.reindex(idx).fillna(0)})
print("\ncorrelação diária:\n", C.corr().round(2).to_string())
C["Rompimento + Rotação"] = C[["Rompimento BTC/ETH", "Rotação v2"]].mean(axis=1)
C["Rompimento + NFI"] = C[["Rompimento BTC/ETH", "NFI"]].mean(axis=1)
C["Os 3 (1/3 cada)"] = C[["Rompimento BTC/ETH", "Rotação v2", "NFI"]].mean(axis=1)
out = []
for col in C:
    for lab, a in (("2022-26", "2022-01-01"), ("2024-26 OOS", "2024-01-01")):
        x = C.loc[a:, col]; eq = (1 + x).cumprod(); yrs = len(x) / 365.25; cg = eq.iloc[-1] ** (1 / yrs) - 1
        m = eq.resample("ME").last(); mo = m.pct_change(); mo.iloc[0] = m.iloc[0] - 1
        out.append({"carteira": col, "período": lab, "CAGR %": cg * 100, "mês %": ((1 + cg) ** (1 / 12) - 1) * 100,
                    "MaxDD %": (eq / eq.cummax() - 1).min() * 100, "pior mês %": mo.min() * 100,
                    "meses neg": f"{(mo < 0).sum()}/{len(mo)}", "Sharpe": x.mean() / x.std() * np.sqrt(365)})
T = pd.DataFrame(out).round(1)
T.to_csv(ROOT / "results/r23_ta_final.csv", index=False)
pd.set_option("display.width", 250)
print(T.to_string(index=False))
yr = (1 + C).groupby(C.index.year).prod() - 1
print("\npor ano (%):\n", (yr * 100).round(1).to_string())
C.to_parquet(ROOT / "results/r23_components.parquet")
