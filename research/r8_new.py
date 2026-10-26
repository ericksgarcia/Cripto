"""Novas estratégias (pesquisa fase 2). Todas long-only spot, custos 0,12% por lado, sem look-ahead.

1. Volatility Breakout (Larry Williams / popular na Coreia): compra quando o preço rompe abertura + k*range de ontem,
   vende na abertura seguinte. Filtro: abertura acima da SMA curta.
2. Compra de capitulação (dip buying intradiário, ideia da NFI): compra após queda extrema em 1h/4h abaixo da banda
   inferior com RSI baixo, vende no repique (alvo) ou por tempo.
3. Sazonalidade intradiária/semanal do BTC.
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import numpy as np, pandas as pd, talib
from numba import njit
from engine.mine import data, data_universe, eligible, COST, DEV, OOS, CMP, metrics_period

pd.set_option("display.width", 250)


def daily_returns_to_metrics(r, label):
    """r = retorno diário da carteira (já líquido). Retorna métricas DEV/OOS/CMP."""
    eq = (1 + r.fillna(0)).cumprod()
    out = {}
    for name, per in (("DEV", DEV), ("OOS", OOS), ("CMP", CMP)):
        s = eq[(eq.index >= pd.Timestamp(per[0], tz="UTC")) & (eq.index <= pd.Timestamp(per[1], tz="UTC"))]
        m = metrics_period(s / s.iloc[0], per)
        out[name] = m
    row = {"strategy": label}
    for p in ("DEV", "OOS", "CMP"):
        row[f"{p}_cagr"] = out[p]["cagr_%"]; row[f"{p}_dd"] = out[p]["maxdd_%"]; row[f"{p}_sharpe"] = out[p]["sharpe"]
    row["CMP_mes_%"] = ((1 + out["CMP"]["cagr_%"] / 100) ** (1 / 12) - 1) * 100
    return row, eq


# ---------------------------------------------------------------- 1. Volatility breakout
def vol_breakout(D, k=0.5, ma=5, elig=None, top=None, vt=None):
    O, H, L, C = D["O"], D["H"], D["L"], D["C"]
    rng = (H - L).shift(1)
    tgt = O + k * rng
    trig = (H >= tgt) & (O > C.rolling(ma).mean().shift(1))
    if elig is not None:
        trig &= elig.shift(1).fillna(False)
    exitp = O.shift(-1)
    entry = np.maximum(tgt, O)  # se abrir acima do alvo, entra na abertura
    r = (exitp / entry - 1 - 2 * COST).where(trig)
    if vt:  # tamanho por volatilidade: alvo vt de risco diário / range% de ontem
        w = (vt / (rng / O)).clip(upper=1.0)
    else:
        w = pd.DataFrame(1.0, index=O.index, columns=O.columns)
    w = w.where(trig)
    n = elig.sum(axis=1) if elig is not None else O.notna().sum(axis=1)
    port = (r * w).sum(axis=1) / n.replace(0, np.nan)
    return port.fillna(0.0)


# ---------------------------------------------------------------- 2. compra de capitulação (barras 1h)
@njit(cache=True)
def _dip_sim(o, h, l, c, sig, tp, sl, tmax, cost):
    """Por moeda: entra na abertura após sinal; sai no alvo tp, stop sl ou após tmax barras. Retorna retorno por barra."""
    n = len(o)
    ret = np.zeros(n)
    inpos = False
    e = 0.0; t0 = 0
    for i in range(1, n):
        if not inpos and sig[i - 1] and not np.isnan(o[i]):
            inpos = True; e = o[i]; t0 = i
            ret[i] -= cost
            prev = e
        if inpos:
            ex = -1.0
            if l[i] <= e * (1 - sl):
                ex = e * (1 - sl)
            elif h[i] >= e * (1 + tp):
                ex = e * (1 + tp)
            elif i - t0 >= tmax:
                ex = c[i]
            if ex > 0:
                ret[i] += ex / prev - 1 - cost
                inpos = False
            else:
                ret[i] += c[i] / prev - 1
                prev = c[i]
    return ret


def dip_buyer(U1h, elig_d, drop_z=3.0, rsi_max=25, tp=0.04, sl=0.10, tmax=48, slot=0.2):
    C, O, H, L = U1h["C"], U1h["O"], U1h["H"], U1h["L"]
    r = np.log(C).diff()
    z = (C / C.shift(4) - 1) / (r.rolling(24 * 14).std() * 2)   # queda de 4h em desvios
    rsi = C.apply(lambda s: pd.Series(talib.RSI(s.values.astype(float), 14), s.index))
    up, mid, lo = {}, {}, {}
    sig = (z < -drop_z) & (rsi < rsi_max)
    el = elig_d.reindex(C.index, method="ffill").fillna(False)
    sig &= el
    R = {}
    for s in C:
        R[s] = _dip_sim(O[s].values, H[s].values, L[s].values, C[s].values, sig[s].fillna(False).values, tp, sl, tmax, COST)
    R = pd.DataFrame(R, index=C.index)
    # cada operação usa uma fatia `slot` do capital (até 1/slot posições simultâneas, aproximação)
    port = (R * slot).sum(axis=1).clip(lower=-0.99)
    return port.resample("1D").apply(lambda x: (1 + x).prod() - 1), int(sig.sum().sum())


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "vb"
    rows = []
    if which == "vb":
        D = data("1d")
        for k in (0.3, 0.5, 0.7):
            for ma in (3, 5, 10):
                for vt in (None, 0.02):
                    row, _ = daily_returns_to_metrics(vol_breakout(D, k, ma, vt=vt), f"VB10_k{k}_ma{ma}_vt{vt}")
                    rows.append(row)
        U = data_universe("1d"); el = eligible(U, 1, 20)
        for k in (0.5, 0.7):
            row, _ = daily_returns_to_metrics(vol_breakout(U, k, 5, el), f"VB_U20_k{k}_ma5")
            rows.append(row)
    elif which == "dip":
        U = data_universe("1h"); Ud = data_universe("1d")
        for N in (10, 20):
            el = eligible(Ud, 1, N)
            for dz in (2.5, 3.5):
                for tp in (0.03, 0.06):
                    for sl in (0.08, 0.2):
                        r, nsig = dip_buyer(U, el, dz, 30, tp, sl, 48)
                        row, _ = daily_returns_to_metrics(r, f"DIP_U{N}_z{dz}_tp{tp}_sl{sl}")
                        row["sinais"] = nsig
                        rows.append(row)
    T = pd.DataFrame(rows).set_index("strategy").round(2).sort_values("DEV_sharpe", ascending=False)
    T.to_csv(f"results/r8_{which}.csv")
    print(T.to_string())
