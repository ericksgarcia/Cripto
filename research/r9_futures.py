"""Fase 2 com futuros perpétuos (USDT-M): short, long/short, funding carry e combinações.

Simulação diária vetorizada: decisão no fechamento de t, execução na abertura de t+1 (retornos open->open),
custo 0,05% taker + 0,02% slippage por lado em futuros (0,12% em spot), funding real da Binance cobrado/recebido
sobre a posição (long paga funding positivo, short recebe).
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import numpy as np, pandas as pd
from engine.core import ROOT, AGG
from engine.mine import data_universe, eligible, regime_btc, vol, metrics_period, DEV, OOS, CMP

FUT_COST = 0.0005 + 0.0002
SPOT_COST = 0.0012
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)


def fut_panel(start="2019-09-01"):
    out = {k: {} for k in "OHLC"}
    F = {}
    for p in sorted((ROOT / "data/futures/1h").glob("*.parquet")):
        d = pd.read_parquet(p).loc[start:]
        g = d.index.to_series().diff()
        cut = g[g > pd.Timedelta("3D")]
        if len(cut):
            d = d[d.index < cut.index[0]]
        d = d.resample("1D").agg(AGG).dropna()
        if len(d) < 60:
            continue
        for k, c in zip("OHLC", ("open", "high", "low", "close")):
            out[k][p.stem] = d[c]
        fp = ROOT / "data/futures/funding" / f"{p.stem}.parquet"
        if fp.exists():
            F[p.stem] = pd.read_parquet(fp)["rate"].resample("1D").sum()
    D = {k: pd.DataFrame(v) for k, v in out.items()}
    idx = D["C"].index
    D = {k: v.reindex(idx) for k, v in D.items()}
    D["F"] = pd.DataFrame(F).reindex(idx).fillna(0.0)
    return D


def simulate(W, D, cost=FUT_COST, funding=True):
    """W decidido no fechamento de t -> posição durante [open t+1, open t+2). Retorna retorno diário líquido."""
    O = D["O"]
    r = (O.shift(-1) / O - 1)              # retorno open t -> open t+1, atribuído ao dia t
    Wp = W.shift(1).reindex(O.index).fillna(0.0)   # posição vigente no dia t
    gross = (Wp * r).sum(axis=1)
    turn = Wp.diff().abs().sum(axis=1).fillna(Wp.abs().sum(axis=1))
    fund = (Wp * D["F"].reindex(O.index).fillna(0.0)).sum(axis=1) if funding else 0.0
    return (gross - turn * cost - fund).shift(1).fillna(0.0)  # realizado no dia seguinte


def report(r, label):
    eq = (1 + r.clip(lower=-1)).cumprod()
    row = {"strategy": label}
    for name, per in (("DEV", ("2020-06-01", DEV[1])), ("OOS", OOS), ("CMP", CMP)):
        s = eq[(eq.index >= pd.Timestamp(per[0], tz="UTC")) & (eq.index <= pd.Timestamp(per[1], tz="UTC"))]
        m = metrics_period(s / s.iloc[0], per)
        row[f"{name}_cagr"] = m["cagr_%"]; row[f"{name}_dd"] = m["maxdd_%"]; row[f"{name}_sharpe"] = m["sharpe"]
    row["CMP_mes_%"] = ((1 + row["CMP_cagr"] / 100) ** (1 / 12) - 1) * 100
    return row, eq


def mom_score(C, look=14):
    return (C / C.shift(look) - 1) / vol(C, look, 1)


def rotation_ls(D, el, look=14, top=5, bot=5, mode="switch", coin_ma=50, gross=1.0):
    """mode: 'long' (só compra, regime BTC), 'switch' (compra em alta / vende a descoberto as piores em baixa),
    'neutral' (sempre long top + short bottom, market-neutral)."""
    C = D["C"]
    m = mom_score(C, look).where(el)
    rk_top = m.rank(axis=1, ascending=False); rk_bot = m.rank(axis=1, ascending=True)
    ma = C.rolling(coin_ma).mean()
    longs = ((rk_top <= top) & (m > 0) & (C > ma)).astype(float) / top
    shorts = ((rk_bot <= bot) & (m < 0) & (C < ma)).astype(float) / bot
    bull = regime_btc(C, 100, 1)
    if mode == "long":
        W = longs.mul(bull, axis=0)
    elif mode == "switch":
        W = longs.mul(bull, axis=0) - shorts.mul(1 - bull, axis=0)
    elif mode == "neutral":
        W = 0.5 * longs - 0.5 * shorts
    elif mode == "both":   # long em alta + short das piores sempre (meia exposição)
        W = longs.mul(bull, axis=0) - 0.5 * shorts
    return W * gross


def funding_carry(D, el, thr=0.0003, look=3, max_n=5):
    """Cash & carry: compra spot + vende perp nas moedas com funding médio recente alto. Ganha o funding.
    Retorno = funding recebido - custos de 4 pernas na entrada/saída (aproxima basis ~ constante)."""
    Fm = D["F"].rolling(look).mean()
    sel = (Fm > thr) & el
    rk = Fm.where(sel).rank(axis=1, ascending=False)
    W = ((rk <= max_n) & sel).astype(float) / max_n
    Wp = W.shift(1).fillna(0.0)
    inc = (Wp * D["F"]).sum(axis=1)
    turn = Wp.diff().abs().sum(axis=1).fillna(0.0)
    return (inc - turn * (FUT_COST + SPOT_COST)).shift(1).fillna(0.0), W


if __name__ == "__main__":
    D = fut_panel()
    Ud = data_universe("1d")
    rows = []
    curves = {}
    for N in (10, 20, 30):
        # elegibilidade: top-N por volume no spot (point-in-time), restrito a moedas com perp
        el = eligible(Ud, 1, N).reindex(D["C"].index).reindex(columns=D["C"].columns).fillna(False)
        for mode in ("long", "switch", "neutral", "both"):
            for top in (3, 5):
                W = rotation_ls(D, el, 14, top, top, mode)
                row, eq = report(simulate(W, D), f"ROT_{mode}_U{N}_t{top}")
                rows.append(row); curves[row["strategy"]] = eq
        for thr in (0.0001, 0.0003, 0.0006):
            r, _ = funding_carry(D, el, thr)
            row, eq = report(r, f"CARRY_U{N}_thr{thr}")
            rows.append(row); curves[row["strategy"]] = eq
    T = pd.DataFrame(rows).set_index("strategy").round(2).sort_values("DEV_sharpe", ascending=False)
    T.to_csv(ROOT / "results/r9_futures.csv")
    pd.DataFrame(curves).to_parquet(ROOT / "results/r9_curves.parquet")
    print(T.to_string())
