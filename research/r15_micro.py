"""Fase 3 — microestrutura em candles de 1 minuto (2018-2026).

A) CASCATA: queda (ou alta) extrema em `win` minutos -> entra a favor da reversão na abertura do minuto seguinte,
   sai após `hold` minutos. Eventos sem sobreposição. Custo por lado: 0,07% (taker 0,05% + slippage 0,02%).
B) LEAD-LAG: BTC sobe/cai > x em 1 minuto -> compra/vende a altcoin no minuto seguinte, segura `hold` minutos.

Mede retorno médio líquido por operação, nº de operações e consistência por ano (DEV 2018-2023 / OOS 2024-2026).
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import numpy as np, pandas as pd
from numba import njit
from engine.core import ROOT

COST = 0.0007
SYMS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "LTC", "LINK", "AVAX"]
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)


def load1m(sym):
    d = pd.read_parquet(ROOT / "data/1m" / f"{sym}USDT.parquet").loc["2018-01-01":]
    d = d.reindex(pd.date_range(d.index[0], d.index[-1], freq="1min"))
    return d


@njit(cache=True)
def events(o, c, sig, hold):
    """sig[t] = +1 (comprar) / -1 (vender) no fechamento de t. Retorna índices de entrada e retornos brutos."""
    n = len(o)
    idx = []; ret = []
    t = 0
    while t < n - hold - 2:
        s = sig[t]
        if s != 0 and not np.isnan(o[t + 1]) and not np.isnan(c[t + hold]):
            r = s * (c[t + hold] / o[t + 1] - 1.0)
            idx.append(t); ret.append(r)
            t += hold + 1
        else:
            t += 1
    return np.array(idx), np.array(ret)


def summarize(name, ts, r):
    if len(r) == 0:
        return None
    s = pd.Series(r - 2 * COST, ts)
    out = {"estratégia": name, "ops": len(s), "bruto_bps": np.mean(r) * 1e4, "líquido_bps": s.mean() * 1e4,
           "acerto_%": (s > 0).mean() * 100}
    for lab, a, b in (("DEV", "2018", "2023-12-31"), ("OOS", "2024", "2026-12-31")):
        x = s[a:b]
        out[f"{lab}_ops"] = len(x); out[f"{lab}_bps"] = x.mean() * 1e4 if len(x) else np.nan
        out[f"{lab}_soma_%/ano"] = x.sum() * 100 / max(1, (pd.Timestamp(b) - pd.Timestamp(a)).days / 365) if len(x) else np.nan
    yr = s.groupby(s.index.year).mean() * 1e4
    out["anos_positivos"] = f"{(yr > 0).sum()}/{len(yr)}"
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "cascade"
    rows = []
    if which == "cascade":
        for sym in SYMS:
            d = load1m(sym)
            o, c = d.open.values, d.close.values
            lr = np.log(d.close).diff()
            for win in (5, 15, 60):
                rw = np.log(d.close / d.close.shift(win))
                sd = lr.rolling(1440 * 3, min_periods=1440).std() * np.sqrt(win)
                z = (rw / sd).values
                for zt in (5.0, 8.0):
                    for hold in (15, 60, 240):
                        for side, sgn in (("dip", 1), ("pump", -1)):
                            sig = np.where(sgn * z < -zt, sgn, 0).astype(np.int64)
                            sig = np.where(np.isnan(z), 0, sig)
                            ix, r = events(o, c, sig, hold)
                            row = summarize(f"{sym}_{side}_w{win}_z{zt}_h{hold}", d.index[ix] if len(ix) else [], r)
                            if row:
                                row.update(sym=sym, side=side, win=win, z=zt, hold=hold); rows.append(row)
            print(sym, flush=True)
    elif which == "leadlag":
        b = load1m("BTC")
        rb = np.log(b.close).diff()
        sdb = rb.rolling(1440 * 3, min_periods=1440).std()
        for sym in SYMS[1:]:
            d = load1m(sym).reindex(b.index)
            o, c = d.open.values, d.close.values
            ra = np.log(d.close).diff()
            for zt in (4.0, 6.0, 10.0):
                for hold in (1, 3, 10, 30):
                    # BTC move forte e a alt ainda NÃO acompanhou (move da alt < metade do do BTC no mesmo minuto)
                    zb = (rb / sdb).values
                    lag = (np.abs(ra.values) < 0.5 * np.abs(rb.values))
                    sig = np.where((zb > zt) & lag, 1, np.where((zb < -zt) & lag, -1, 0)).astype(np.int64)
                    ix, r = events(o, c, sig, hold)
                    row = summarize(f"{sym}_lead_z{zt}_h{hold}", d.index[ix] if len(ix) else [], r)
                    if row:
                        row.update(sym=sym, z=zt, hold=hold); rows.append(row)
            print(sym, flush=True)
    T = pd.DataFrame(rows)
    T.to_csv(ROOT / f"results/r15_{which}.csv", index=False)
    cols = ["estratégia", "ops", "bruto_bps", "líquido_bps", "acerto_%", "DEV_ops", "DEV_bps", "OOS_ops", "OOS_bps",
            "OOS_soma_%/ano", "anos_positivos"]
    print(T.sort_values("líquido_bps", ascending=False)[cols].head(40).round(1).to_string(index=False))
    # agregados robustos (média entre moedas) por configuração
    key = [c for c in ("side", "win", "z", "hold") if c in T]
    print(T.groupby(key)[["bruto_bps", "líquido_bps", "DEV_bps", "OOS_bps", "ops"]].mean().round(1).to_string())
