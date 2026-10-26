"""Estratégias próprias (pesquisa). Desenvolvimento: 2018-01 → 2023-12. Validação fora da amostra: 2024-01 → 2026-10.

Todas são long-only spot (sem alavancagem, sem short), executadas na abertura seguinte ao sinal.
"""
import numpy as np
import pandas as pd
from .core import SYMS, FEE, SLIP, panel, sim_multi, metrics

COST = FEE + SLIP
DEV = ("2018-01-01", "2023-12-31")
OOS = ("2024-01-01", "2026-10-25")
CMP = ("2021-01-01", "2026-10-25")
BARS_PER_DAY = {"1d": 1, "4h": 6, "1h": 24}


def data(tf):
    C = panel(tf); O = panel(tf, field="open"); H = panel(tf, field="high"); L = panel(tf, field="low")
    V = panel(tf, field="volume")
    idx = C.index
    return {k: x.reindex(idx) for k, x in dict(C=C, O=O, H=H, L=L, V=V).items()}


def run(W, D, period, band=0.1):
    """Simula pesos W (decididos no fechamento) no período, retornando curva diária normalizada."""
    a, b = period
    sl = (D["O"].index >= pd.Timestamp(a, tz="UTC")) & (D["O"].index <= pd.Timestamp(b, tz="UTC") + pd.Timedelta("1D"))
    O = D["O"][sl]
    Wp = W.reindex(O.index).fillna(0.0)
    eq, turn = sim_multi(O.values, Wp.values, COST, band)
    s = pd.Series(eq, O.index)
    return s, turn


def evaluate(W, D, band=0.1, label=""):
    out = {}
    for name, per in (("DEV", DEV), ("OOS", OOS), ("CMP", CMP)):
        s, turn = run(W, D, per, band)
        m = metrics_period(s, per)
        m["turnover/yr"] = turn / max((s.index[-1] - s.index[0]).days / 365.25, 1e-9)
        out[name] = m
    return out


def metrics_period(s, per):
    import engine.core as core
    old = core.START
    core.START = per[0]
    try:
        return metrics(s)
    finally:
        core.START = old


def summarize(res):
    rows = []
    for k, v in res.items():
        r = {"strategy": k}
        for p in ("DEV", "OOS", "CMP"):
            r[f"{p}_cagr"] = v[p]["cagr_%"]; r[f"{p}_dd"] = v[p]["maxdd_%"]; r[f"{p}_sharpe"] = v[p]["sharpe"]
        r["CMP_total"] = v["CMP"]["total_%"]; r["turn/yr"] = v["CMP"]["turnover/yr"]
        rows.append(r)
    return pd.DataFrame(rows).set_index("strategy").round(2)


# ------------------------------------------------------------------ blocos de sinal
def vol(C, n_days, bpd):
    r = np.log(C).diff()
    return r.rolling(n_days * bpd, min_periods=n_days * bpd // 2).std() * np.sqrt(365 * bpd)


def tsmom_score(C, lookbacks_days, bpd):
    """Média de sinais de tendência (retorno passado > 0) em vários horizontes: 0..1."""
    s = sum((C / C.shift(L * bpd) - 1 > 0).astype(float) for L in lookbacks_days)
    return s / len(lookbacks_days)


def breakout_state(C, H, L, n_entry, n_exit):
    """Donchian: entra no rompimento da máxima de n_entry barras, sai na mínima de n_exit barras."""
    up = H.rolling(n_entry).max().shift(1)
    dn = L.rolling(n_exit).min().shift(1)
    st = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    st[C > up] = 1.0
    st[C < dn] = 0.0
    return st.ffill().fillna(0.0)


def regime_btc(C, n_days, bpd):
    btc = C["BTC"]
    return (btc > btc.rolling(n_days * bpd).mean()).astype(float)


# ------------------------------------------------------------------ estratégias
def s_tsmom_vt(D, bpd, lbs=(10, 20, 40, 80, 160), tvol=0.6, cap=1.0):
    """Momentum de série temporal multi-horizonte + alvo de volatilidade por moeda."""
    C = D["C"]
    sc = tsmom_score(C, lbs, bpd)
    w = sc * (tvol / vol(C, 30, bpd)).clip(upper=cap)
    w = w.where(C.notna(), 0.0)
    return w.div(len(SYMS))  # 1/N do capital por moeda


def s_xsmom(D, bpd, look=30, top=3, regime=100, skip=0):
    """Rotação: compra as `top` moedas de maior momentum (ajustado por vol) se BTC em regime de alta."""
    C = D["C"]
    mom = (C.shift(skip * bpd) / C.shift((look + skip) * bpd) - 1) / vol(C, look, bpd)
    mom = mom.where(C.notna())
    rk = mom.rank(axis=1, ascending=False)
    w = (rk <= top).astype(float) / top
    w = w.mul((mom > 0).astype(float))
    if regime:
        w = w.mul(regime_btc(C, regime, bpd), axis=0)
    return w


def s_turtle(D, bpd, n_in=20, n_out=10, tvol=0.6):
    C, H, L = D["C"], D["H"], D["L"]
    st = breakout_state(C, H, L, n_in * bpd, n_out * bpd)
    w = st * (tvol / vol(C, 30, bpd)).clip(upper=1.0)
    return w.div(len(SYMS))


# ------------------------------------------------------------------ universo amplo (anti viés de sobrevivência)
def data_universe(tf="1d", start="2018-01-01"):
    from .core import ROOT, AGG, END
    out = {k: {} for k in "COHLV"}
    rule = {"1d": "1D", "4h": "4h", "1h": "1h"}[tf]
    for p in sorted((ROOT / "data" / "universe_1h").glob("*.parquet")):
        d = pd.read_parquet(p).loc[start:END]
        if len(d) < 24 * 60:
            continue
        g = d.index.to_series().diff()
        cut = g[g > pd.Timedelta("3D")]
        if len(cut):  # deslistado/relistado (LUNA->LUNA2, FTT): mantém só o primeiro segmento
            d = d[d.index < cut.index[0]]
        d = d.resample(rule).agg(AGG).dropna()
        s = p.stem
        out["C"][s] = d.close; out["O"][s] = d.open; out["H"][s] = d.high; out["L"][s] = d.low
        out["V"][s] = d.volume * d.close
    D = {k: pd.DataFrame(v) for k, v in out.items()}
    idx = D["C"].index
    return {k: x.reindex(idx) for k, x in D.items()}


def eligible(D, bpd, top_n=20, min_age_days=60, stable_excl=()):
    """Elegível em t: listado há >= min_age_days e entre os top_n por volume médio (US$) de 30 dias — point-in-time."""
    V = D["V"].rolling(30 * bpd, min_periods=10 * bpd).mean()
    age = D["C"].notna().cumsum()
    V = V.where(age >= min_age_days * bpd)
    rk = V.rank(axis=1, ascending=False)
    return (rk <= top_n)


def s_xsmom_u(D, bpd, look=30, top=3, regime=100, elig=None):
    C = D["C"]
    mom = (C / C.shift(look * bpd) - 1) / vol(C, look, bpd)
    if elig is not None:
        mom = mom.where(elig)
    rk = mom.rank(axis=1, ascending=False)
    w = (rk <= top).astype(float) / top
    w = w.mul((mom > 0).astype(float))
    if regime:
        w = w.mul(regime_btc(C, regime, bpd), axis=0)
    return w


def breadth(C, n_days, bpd, elig=None):
    above = (C > C.rolling(n_days * bpd).mean()).astype(float).where(C.notna())
    if elig is not None:
        above = above.where(elig)
    return above.mean(axis=1)


def s_rotation(D, bpd, look=30, top=3, elig=None, regime="btc", reg_n=100, coin_ma=0,
               port_vt=None, vt_win=30, weighting="equal", look2=None):
    """Rotação por momentum generalizada.
    regime: 'btc' (BTC>SMA reg_n), 'breadth' (>50% das moedas acima da SMA reg_n), 'both', None
    coin_ma: exige moeda acima da própria SMA(coin_ma) dias; port_vt: alvo de vol anual da carteira;
    weighting: 'equal' | 'invvol'; look2: segundo horizonte de momentum (média dos z-scores)."""
    C = D["C"]
    v = vol(C, look, bpd)
    mom = (C / C.shift(look * bpd) - 1) / v
    if look2:
        mom = (mom.rank(axis=1, pct=True) + ((C / C.shift(look2 * bpd) - 1) / vol(C, look2, bpd)).rank(axis=1, pct=True)) / 2
        raw = (C / C.shift(look * bpd) - 1)
        pos_ok = raw > 0
    else:
        pos_ok = mom > 0
    if elig is not None:
        mom = mom.where(elig)
    mom = mom.where(C.notna())
    rk = mom.rank(axis=1, ascending=False)
    sel = (rk <= top) & pos_ok
    if coin_ma:
        sel &= C > C.rolling(coin_ma * bpd).mean()
    if weighting == "invvol":
        iv = (1 / v).where(sel)
        w = iv.div(iv.sum(axis=1), axis=0).fillna(0.0) * (sel.sum(axis=1) / top).values[:, None]
    else:
        w = sel.astype(float) / top
    if regime in ("btc", "both"):
        w = w.mul(regime_btc(C, reg_n, bpd), axis=0)
    if regime in ("breadth", "both"):
        w = w.mul((breadth(C, reg_n, bpd, elig) > 0.5).astype(float), axis=0)
    if port_vt:
        r = np.log(C).diff().fillna(0.0)
        pr = (w.shift(1) * r).sum(axis=1)
        pv = pr.rolling(vt_win * bpd, min_periods=10 * bpd).std() * np.sqrt(365 * bpd)
        sc = (port_vt / pv).clip(upper=1.0).fillna(1.0)
        w = w.mul(sc, axis=0)
    return w


from numba import njit as _njit


@_njit(cache=True)
def _atr_stop_overlay(W, C, A, k, cooldown):
    """Aplica stop móvel em barras intradiárias: zera a posição se o fechamento cair abaixo de
    (máxima de fechamento desde a entrada - k*ATR). Só reentra após `cooldown` barras E se o peso-alvo
    continuar > 0 (nova decisão diária)."""
    T, K = W.shape
    out = W.copy()
    for j in range(K):
        hi = 0.0
        stopped_until = -1
        in_pos = False
        for t in range(T):
            if W[t, j] <= 0 or np.isnan(C[t, j]):
                in_pos = False; hi = 0.0
                out[t, j] = 0.0
                continue
            if t < stopped_until:
                out[t, j] = 0.0
                continue
            if not in_pos:
                in_pos = True; hi = C[t, j]
            hi = max(hi, C[t, j])
            if not np.isnan(A[t, j]) and C[t, j] < hi - k * A[t, j]:
                out[t, j] = 0.0
                in_pos = False; hi = 0.0
                stopped_until = t + cooldown
    return out


def with_intraday_stop(Wd, D4, k=4.0, atr_n=14, cooldown_bars=6):
    """Wd = pesos diários; D4 = painel 4h. Retorna pesos 4h com overlay de stop ATR."""
    import talib
    C4 = D4["C"]
    W4 = Wd.reindex(C4.index, method="ffill").fillna(0.0)
    A = pd.DataFrame({s: talib.ATR(D4["H"][s].values, D4["L"][s].values, C4[s].values, atr_n) for s in C4}, index=C4.index)
    out = _atr_stop_overlay(W4.values, C4.values, A.values, k, cooldown_bars)
    return pd.DataFrame(out, C4.index, C4.columns)
