"""Fase 3 — carteira orientada a eventos de microestrutura (1m), com capital compartilhado e custos realistas.

Sinais (no fechamento do minuto t, entrada na abertura de t+1):
  DIP : retorno de `w_dip` min < -z_dip * sigma  -> compra, segura h_dip minutos
  PUMP: retorno de `w_pump` min > +z_pump * sigma -> compra (continuação), segura h_pump minutos
sigma = desvio dos retornos de 1m nos 3 dias anteriores × sqrt(janela).
Carteira: cada operação usa `slot` do patrimônio (até max_pos simultâneas); custo por lado `cost`
(0,07% base; testa 0,15% e 0,30% para slippage de crash). Patrimônio marcado no fechamento de cada operação.
"""
import warnings; warnings.filterwarnings("ignore")
import sys, itertools
import numpy as np, pandas as pd
from engine.core import ROOT
from research.r15_micro import load1m, events, SYMS

pd.set_option("display.width", 250)


def gen_trades(syms, kind, win, z, hold, cache):
    out = []
    for s in syms:
        key = (s, win)
        if key not in cache:
            d = load1m(s)
            lr = np.log(d.close).diff()
            sd = lr.rolling(1440 * 3, min_periods=1440).std() * np.sqrt(win)
            cache[key] = (d.index, d.open.values, d.close.values, (np.log(d.close / d.close.shift(win)) / sd).values)
        idx, o, c, zz = cache[key]
        if kind == "dip":
            sig = np.where(zz < -z, 1, 0)
        else:
            sig = np.where(zz > z, 1, 0)
        sig = np.where(np.isnan(zz), 0, sig).astype(np.int64)
        ix, r = events(o, c, sig, hold)
        for i, rr in zip(ix, r):
            out.append((idx[i], idx[min(i + hold, len(idx) - 1)], s, kind, rr))
    return out


def portfolio(trades, slot, max_pos, cost):
    """Simula em ordem cronológica: entra se houver vaga; marca patrimônio na saída."""
    tr = sorted(trades, key=lambda x: x[0])
    eq = 1.0
    open_ = []  # (saida, notional, ret)
    curve = []
    taken = 0
    for t_in, t_out, s, k, r in tr:
        # fecha as que terminaram
        still = []
        for (to, notional, rr) in open_:
            if to <= t_in:
                eq += notional * (rr - 2 * cost); curve.append((to, eq))
            else:
                still.append((to, notional, rr))
        open_ = still
        if len(open_) < max_pos and not any(x[3] == s for x in []):
            open_.append((t_out, eq * slot, r)); taken += 1
    for (to, notional, rr) in sorted(open_):
        eq += notional * (rr - 2 * cost); curve.append((to, eq))
    c = pd.Series(dict(curve)).sort_index()
    return c, taken


def perf(c, a, b):
    x = c[(c.index >= a) & (c.index <= b)]
    if len(x) < 5:
        return np.nan, np.nan, np.nan
    d = x.resample("1D").last().ffill()
    base = c[c.index < a].iloc[-1] if (c.index < a).any() else 1.0
    d = pd.concat([pd.Series([base], [pd.Timestamp(a, tz="UTC")]), d])
    yrs = (pd.Timestamp(b, tz="UTC") - pd.Timestamp(a, tz="UTC")).days / 365.25
    cagr = (d.iloc[-1] / d.iloc[0]) ** (1 / yrs) - 1
    dd = (d / d.cummax() - 1).min()
    m = d.resample("ME").last().pct_change().dropna()
    return cagr * 100, dd * 100, (m > 0).mean() * 100


if __name__ == "__main__":
    cache = {}
    rows = []
    configs = []
    for zd, hd, zp, hp, wp in itertools.product((6.0, 8.0), (60, 240), (0.0, 8.0), (60, 240), (5, 15)):
        if zp == 0.0 and (hp != 60 or wp != 5):
            continue
        configs.append((zd, hd, zp, hp, wp))
    for zd, hd, zp, hp, wp in configs:
        trades = gen_trades(SYMS, "dip", 60, zd, hd, cache)
        if zp > 0:
            trades += gen_trades(SYMS, "pump", wp, zp, hp, cache)
        for slot, maxp in ((0.1, 10), (0.25, 4), (0.5, 4)):
            for cost in (0.0007, 0.0015, 0.003):
                c, n = portfolio(trades, slot, maxp, cost)
                d = perf(c, "2018-03-01", "2023-12-31"); o = perf(c, "2024-01-01", "2026-10-25"); a = perf(c, "2018-03-01", "2026-10-25")
                rows.append({"dip": f"z{zd}_h{hd}", "pump": f"z{zp}_w{wp}_h{hp}" if zp else "-", "slot": slot, "max": maxp,
                             "custo": cost, "ops": n, "DEV_cagr": d[0], "DEV_dd": d[1], "OOS_cagr": o[0], "OOS_dd": o[1],
                             "ALL_cagr": a[0], "ALL_dd": a[1], "ALL_mes_%": ((1 + a[0] / 100) ** (1 / 12) - 1) * 100,
                             "meses+_%": a[2]})
        print(zd, hd, zp, hp, wp, flush=True)
    T = pd.DataFrame(rows); T[[c for c in T if c not in ("custo",)]] = T[[c for c in T if c not in ("custo",)]].round(1)
    T.to_csv(ROOT / "results/r16_events.csv", index=False)
    print(T[T.custo == 0.0007].sort_values("DEV_cagr", ascending=False).head(25).to_string(index=False))
    print("\nsensibilidade a custo (melhor DEV de cada custo):")
    print(T.loc[T.groupby("custo").DEV_cagr.idxmax()].to_string(index=False))
