"""Fase 4 — sistema de rompimento/tendência só em BTC e ETH (4h), spot, sem alavancagem.
Sinais: VCP (contração + rompimento c/ volume), Donchian 55 c/ volume, Squeeze TTM, BOS. Uma posição por moeda
(50% do capital cada). Saída: stop técnico (1-4 ATR) + stop móvel k ATR. Escolha da saída/sinais só no DEV (2018-23)."""
import warnings; warnings.filterwarnings("ignore")
import itertools
import numpy as np, pandas as pd
from engine.core import ROOT, AGG
from research.ta.patterns import detect_all, atr
from research.r21_ta_portfolio import trade_ix, perf

COST = 0.0012
SETS = {"VCP+Donch+Squeeze+BOS": [8, 10, 9, 0], "VCP+Donch+Squeeze": [8, 10, 9], "Donchian": [10], "VCP": [8],
        "todos_rompimentos(+triang,bandeira,ichimoku)": [8, 10, 9, 0, 6, 7, 11]}
data = {}
for s in ("BTC", "ETH"):
    d = pd.read_parquet(ROOT / "data/ta_1h" / f"{s}.parquet").resample("4h").agg(AGG).dropna()
    arr = tuple(d[x].values.astype(np.float64) for x in ("open", "high", "low", "close", "volume"))
    S, ST = detect_all(*arr, 3)
    data[s] = (d.index, arr, atr(arr[1], arr[2], arr[3], 14), S, ST, d)
rows, curves = [], {}
for (nm, pats), trail, mb, regf in itertools.product(SETS.items(), (2.0, 3.0, 4.0, 6.0), (60, 120, 240), (False, True)):
    eq_parts = []
    for s, (idx, (o, h, l, c, v), A, S, ST, d) in data.items():
        sig = np.zeros(len(c), bool); stp = np.full(len(c), np.nan)
        for pi in pats:
            m = S[pi] & np.isnan(stp); stp[m] = ST[pi][m]; sig |= S[pi]
        if regf:  # tendência do próprio ativo no diário (fechamento anterior acima da EMA50 diária)
            dd = d.close.resample("1D").last(); ok = (dd > dd.ewm(span=50).mean()).shift(1)
            sig &= ok.reindex(idx.normalize()).fillna(False).values.astype(bool)
        # simulação sequencial: 1 posição por vez nesta moeda, 50% do capital (curva própria somada depois)
        r_series = pd.Series(0.0, idx)
        t = 0; ntr = 0
        while t < len(c) - 1:
            if sig[t]:
                r, ex = trade_ix(o, h, l, c, A, t, stp[t], 0.0, trail, mb, 1.0, 4.0)
                if ex > 0:
                    r_series.iloc[ex] += r - 2 * COST; ntr += 1; t = ex; continue
            t += 1
        eq_parts.append(0.5 * r_series)
    port = (1 + sum(eq_parts)).cumprod()   # aproximação: rebalanceia 50/50 a cada fechamento de operação
    key = f"{nm}|trail{trail}|max{mb}|mtf{regf}"
    dv, oo, a = perf(port, "2018-03-01", "2023-12-31"), perf(port, "2024-01-01", "2026-10-24"), perf(port, "2022-01-01", "2026-10-24")
    rows.append({"config": key, "DEV_cagr": dv[0], "DEV_dd": dv[1], "OOS_cagr": oo[0], "OOS_dd": oo[1], "OOS_mes_%": oo[2],
                 "2022-26_cagr": a[0], "2022-26_dd": a[1]})
    curves[key] = port
T = pd.DataFrame(rows).round(1).sort_values("DEV_cagr", ascending=False)
T.to_csv(ROOT / "results/r22_majors.csv", index=False)
bh = pd.concat([data[s][5].close for s in data], axis=1).pct_change().mean(axis=1)
bh = (1 + bh.fillna(0)).cumprod()
print("buy&hold 50/50 BTC+ETH:", [round(x, 1) for x in perf(bh, "2018-03-01", "2023-12-31")[:2]], [round(x, 1) for x in perf(bh, "2024-01-01", "2026-10-24")[:2]])
pd.set_option("display.width", 250)
print(T.head(15).to_string(index=False))
print("\nmediana OOS por conjunto:\n", T.assign(s=T.config.str.split("|").str[0]).groupby("s")[["DEV_cagr", "OOS_cagr", "OOS_dd"]].median().to_string())
