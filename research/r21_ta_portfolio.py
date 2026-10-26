"""Fase 4 — carteiras spot SEM alavancagem a partir dos sinais de análise técnica com vantagem estatística.

Até `slots` posições de 1/slots do patrimônio; sinais disputando vaga entram por ordem cronológica.
Filtro opcional de regime (BTC > SMA100 no dia anterior). Custo 0,12% por lado.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from numba import njit
from engine.core import ROOT
from research.r11_variants import load_spot
from research.r20_ta_exits import gather

COST = 0.0012


@njit(cache=True)
def trade_ix(o, h, l, c, A, t0, stop0, tp_r, trail, max_bars, min_r, max_r):
    n = len(c); e = t0 + 1
    if e >= n or np.isnan(o[e]) or np.isnan(A[t0]):
        return np.nan, -1
    entry = o[e]; at = A[t0]
    risk = entry - stop0
    if np.isnan(risk) or risk < min_r * at:
        risk = min_r * at
    if risk > max_r * at:
        risk = max_r * at
    stop = entry - risk
    tp = entry + tp_r * risk if tp_r > 0 else 1e18
    hc = entry
    for i in range(e, min(n, e + max_bars)):
        if l[i] <= stop:
            return min(o[i], stop) / entry - 1, i
        if h[i] >= tp:
            return (max(o[i], tp) if i > e else tp) / entry - 1, i
        hc = max(hc, c[i])
        if trail > 0 and not np.isnan(A[i]):
            stop = max(stop, hc - trail * A[i])
    last = min(n, e + max_bars) - 1
    return c[last] / entry - 1, last


def run(data, pats, exit_cfg, slots, regime, reg_series):
    tp_r, trail, mb = exit_cfg
    trades = []
    for coin, idx, (o, h, l, c, v), A, S, ST, el in data:
        sig = np.zeros(len(c), np.bool_); stp = np.full(len(c), np.nan)
        for pi in pats:
            m = S[pi] & np.isnan(stp)
            stp[m] = ST[pi][m]; sig |= S[pi]
        sig &= el
        if regime:
            sig &= reg_series.reindex(idx.normalize()).fillna(False).values.astype(bool)
        for t in np.where(sig)[0]:
            r, ex = trade_ix(o, h, l, c, A, t, stp[t], tp_r, trail, mb, 0.5, 3.0)
            if ex > 0:
                trades.append((idx[t], idx[ex], coin, r - 2 * COST))
    trades.sort()
    eq = 1.0; open_ = []; curve = []; held = set()
    for t_in, t_out, coin, r in trades:
        still = []
        for (to, notional, rr, cn) in open_:
            if to <= t_in:
                eq += notional * rr; curve.append((to, eq)); held.discard(cn)
            else:
                still.append((to, notional, rr, cn))
        open_ = still
        if len(open_) < slots and coin not in held:
            open_.append((t_out, eq / slots, r, coin)); held.add(coin)
    for (to, notional, rr, cn) in sorted(open_):
        eq += notional * rr; curve.append((to, eq))
    return pd.Series(dict(curve)).sort_index(), len(trades)


def perf(c, a, b):
    d = c.resample("1D").last().ffill()
    d = d[(d.index >= a) & (d.index <= b)]
    base = c[c.index < a]
    d = pd.concat([pd.Series([base.iloc[-1] if len(base) else 1.0], [pd.Timestamp(a, tz="UTC")]), d])
    yrs = (pd.Timestamp(b, tz="UTC") - pd.Timestamp(a, tz="UTC")).days / 365.25
    cagr = (d.iloc[-1] / d.iloc[0]) ** (1 / yrs) - 1
    m = d.resample("ME").last().pct_change().dropna()
    return cagr * 100, (d / d.cummax() - 1).min() * 100, ((1 + cagr) ** (1 / 12) - 1) * 100


if __name__ == "__main__":
    D = load_spot(); btc = D["C"]["BTC"]
    reg = (btc > btc.rolling(100).mean()).shift(1)
    rows = []
    for tf in ("4h", "1d"):
        data = gather(tf)
        P = {"spring": [2], "div_RSI": [12], "HA": [16], "spring+div+HA": [2, 12, 16],
             "breakouts(BOS+Donchian+triang)": [0, 10, 6]}
        ex = {"4h": [(0.0, 0.0, 48), (0.0, 3.0, 48), (1.0, 0.0, 24), (2.0, 0.0, 24)],
              "1d": [(0.0, 3.0, 20), (0.0, 0.0, 20), (0.0, 0.0, 3), (2.0, 0.0, 10)]}[tf]
        for name, pats in P.items():
            for e in ex:
                for regime in (False, True):
                    for slots in (5, 10):
                        c, n = run(data, pats, e, slots, regime, reg)
                        if len(c) < 10:
                            continue
                        d = perf(c, "2018-03-01", "2023-12-31"); o = perf(c, "2024-01-01", "2026-10-24")
                        a = perf(c, "2022-01-01", "2026-10-24")
                        rows.append({"tf": tf, "sinais": name, "saida(tpR,trail,barras)": str(e), "regime": regime,
                                     "slots": slots, "ops": n, "DEV_cagr": d[0], "DEV_dd": d[1], "OOS_cagr": o[0],
                                     "OOS_dd": o[1], "OOS_mes_%": o[2], "2022-26_cagr": a[0], "2022-26_dd": a[1]})
            print(tf, name, flush=True)
    T = pd.DataFrame(rows).round(1)
    T.to_csv(ROOT / "results/r21_ta_portfolio.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
    print(T.sort_values("DEV_cagr", ascending=False).head(30).to_string(index=False))
    print("\nmelhor por grupo de sinais (pelo DEV):")
    print(T.loc[T.groupby(["tf", "sinais"]).DEV_cagr.idxmax()].to_string(index=False))
