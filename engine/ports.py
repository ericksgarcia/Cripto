"""Ports fiéis (com os parâmetros padrão dos repositórios) de estratégias do Hummingbot e do OctoBot.

Hummingbot (hummingbot/controllers/directional_trading/*): bollinger_v1, macd_bb_v1, supertrend_v1
  - candles 3m, triple barrier padrão: SL 3%, TP 2%, time limit 45 min, 2 executores por lado, cooldown 5 min.
  - Rodado com alavancagem 1x (o padrão do repo é 20x, o que liquidaria a conta).
OctoBot (OctoBot-Tentacles + profiles padrão): GridTradingMode, Grid com trailing up, DCA simples,
  Smart DCA e DailyTradingMode com SimpleStrategyEvaluator (DoubleMovingAverage + RSIMomentum em 1h/4h/1d).
"""
import numpy as np
import pandas as pd
import talib
import pandas_ta as pta
from numba import njit

from .core import load, sim_target, sim_triple_barrier, sim_grid, START, FEE, SLIP

COST = FEE + SLIP


# ---------------------------------------------------------------- Hummingbot
def _hb_run(df, sig):
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    sig = np.where(df.index < pd.Timestamp(START, tz="UTC"), 0, sig).astype(np.float64)
    eq, n = sim_triple_barrier(o, h, l, c, sig, 0.03, 0.02, 15, 2, 2, COST, 0.5)
    return pd.Series(eq, df.index), n


def _bbp(c, length=100, std=2.0):
    up, mid, lo = talib.BBANDS(c, length, std, std)
    return (c - lo) / (up - lo)


def hb_bollinger_v1(sym):
    df = load(sym, "3m")
    bbp = _bbp(df.close.values)
    sig = np.where(bbp < 0.0, 1, np.where(bbp > 1.0, -1, 0))
    return _hb_run(df, sig)


def hb_macd_bb_v1(sym):
    df = load(sym, "3m")
    c = df.close.values
    bbp = _bbp(c)
    macd, sigl, hist = talib.MACD(c, 21, 42, 9)
    sig = np.where((bbp < 0) & (hist > 0) & (macd < 0), 1, np.where((bbp > 1) & (hist < 0) & (macd > 0), -1, 0))
    return _hb_run(df, sig)


def hb_supertrend_v1(sym):
    df = load(sym, "3m")
    st = pta.supertrend(df.high, df.low, df.close, length=20, multiplier=4.0)
    line = st.iloc[:, 0].values
    d = st.iloc[:, 1].values
    dist = np.abs(df.close.values - line) / df.close.values
    sig = np.where((d == 1) & (dist < 0.01), 1, np.where((d == -1) & (dist < 0.01), -1, 0))
    return _hb_run(df, sig)


# ---------------------------------------------------------------- OctoBot
def ob_grid(sym):
    """Perfil grid_trading: BTC flat_spread 2000 / increment 1000 (~4% / 2%), 25 ordens por lado."""
    df = load(sym, "5m", start=START)
    eq, n = sim_grid(*(df[k].values for k in ("open", "high", "low", "close")), 25, 0.02, 0.04, False, COST)
    return pd.Series(eq, df.index), n


def ob_trailing_grid(sym):
    """Perfil trailing_grid_trading: spread 1300 / increment 800 (~2,6% / 1,6%), 15 ordens, trailing up."""
    df = load(sym, "5m", start=START)
    eq, n = sim_grid(*(df[k].values for k in ("open", "high", "low", "close")), 15, 0.016, 0.026, True, COST)
    return pd.Series(eq, df.index), n


def ob_simple_dca(sym):
    """Perfil simple_dca: compra 5% do total a cada 7 dias, a mercado, nunca vende."""
    df = load(sym, "1d", start=START)
    c = df.close.values
    quote, base = 1.0, 0.0
    eq = np.zeros(len(c))
    for i in range(len(c)):
        if i % 7 == 0 and quote > 1e-9:
            amt = min(quote, 0.05 * (quote + base * c[i]))
            base += amt / c[i] * (1 - COST); quote -= amt
        eq[i] = quote + base * c[i]
    return pd.Series(eq, df.index), int(np.ceil(len(c) / 7))


# --- avaliadores OctoBot
def _trend(x, avgs):
    inc = round(1 / len(avgs), 2)
    m = [pd.Series(x).rolling(a).mean().values for a in avgs]
    t = np.zeros(len(x))
    for a in range(len(m) - 1):
        t += np.where(m[a] - m[a + 1] > 0, -inc, inc)
    return t


def _rsi_note(c):
    rsi = talib.RSI(c, 14)
    lt = _trend(rsi, [40, 30, 20, 15, 10])
    st = _trend(rsi, [7, 5, 4, 3, 2, 1])
    note = np.where((st > 0) & (lt < 0), -st, np.where((lt > 0) & (st < 0), st, 0.0))
    note = note + np.where(rsi > 50, rsi / 200, (rsi - 100) / 200)
    return np.clip(note, -1, 1)


def _dma_note(c, win=200):
    sma2 = talib.SMA(c, 2)
    res = []
    for n in (5, 10):
        diff = pd.Series(sma2 - talib.SMA(c, n))
        rmean = diff.rolling(win).mean(); rng = diff.rolling(win).max() - diff.rolling(win).min()
        cur = np.minimum(np.abs((diff - rmean) / rng) * 2, 1).values
        res.append(np.sign(diff.values) * cur)
    return np.nanmean(res, axis=0)


def _tf_note(sym, tf, idx):
    d = load(sym, tf)
    c = d.close.values.astype(float)
    note = (_rsi_note(c) + _dma_note(c)) / 2
    tfdelta = pd.Timedelta(tf.replace("d", "D"))
    s = pd.Series(note, d.index + tfdelta)  # só fica disponível após o candle fechar
    return s.reindex(idx, method="ffill").values


@njit(cache=True)
def _daily_state_machine(ev):
    w = np.zeros(len(ev))
    pos = 0.0
    last = 0
    for i in range(len(ev)):
        e = ev[i]
        if np.isnan(e):
            w[i] = pos
            continue
        st = 2 if e < -0.85 else (1 if e < -0.25 else (0 if e < 0.25 else (-1 if e < 0.85 else -2)))
        if st != last:
            if st == 2:
                pos = 1.0
            elif st == 1:
                pos = pos + (1 - pos) * 0.5
            elif st == -1:
                pos = pos * 0.5
            elif st == -2:
                pos = 0.0
            last = st
        w[i] = pos
    return w


def ob_daily(sym):
    """Perfil daily_trading: SimpleStrategyEvaluator(DoubleMovingAverage + RSIMomentum) em 1h/4h/1d.
    Notas OctoBot: negativo = compra. Limiares: VERY_LONG<-0.85<LONG<-0.25<NEUTRAL<0.25<SHORT<0.85<VERY_SHORT."""
    df = load(sym, "1h")
    ev = np.nanmean([_tf_note(sym, tf, df.index + pd.Timedelta("1h")) for tf in ("1h", "4h", "1d")], axis=0)
    w = _daily_state_machine(ev)
    w[df.index < pd.Timestamp(START, tz="UTC")] = 0
    eq = sim_target(df.open.values, w, COST)
    return pd.Series(eq, df.index), int((np.abs(np.diff(w)) > 0).sum())


def ob_smart_dca(sym):
    """Perfil smart_dca: SimpleStrategyEvaluator 4h; entrada limite -0,2% + 2 secundárias (-0,5%) de 5%t cada,
    take profit +0,35% / +0,5%; no máximo 1 ciclo de compra a cada 7 dias; sem stop loss."""
    d4 = load(sym, "4h")
    note = (_rsi_note(d4.close.values) + _dma_note(d4.close.values)) / 2
    df = load(sym, "1h")
    sig = pd.Series(note, d4.index + pd.Timedelta("4h")).reindex(df.index + pd.Timedelta("1h"), method="ffill").values
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    t0 = np.searchsorted(df.index.values, np.datetime64(pd.Timestamp(START).to_datetime64()))
    eq, n = _smart_dca(o, h, l, c, sig, t0)
    return pd.Series(eq, df.index), n


@njit(cache=True)
def _smart_dca(o, h, l, c, sig, t0):
    n = len(o)
    eq = np.ones(n)
    quote, base, cost_basis = 1.0, 0.0, 0.0
    entries = np.zeros(3)
    filled = np.zeros(3, np.bool_)
    open_cycle = False
    last_buy = -10**9
    ntr = 0
    for i in range(t0, n):
        if (not open_cycle) and sig[i - 1] <= -0.25 and i - last_buy >= 168 and quote > 0.01 * (quote + base * o[i]):
            p0 = o[i]
            entries[0] = p0 * 0.998; entries[1] = p0 * 0.993; entries[2] = p0 * 0.988
            filled[:] = False
            open_cycle = True
            last_buy = i
        if open_cycle:
            tot = quote + base * o[i]
            for k in range(3):
                if not filled[k] and l[i] <= entries[k]:
                    amt = min(quote, 0.05 * tot)
                    if amt > 0:
                        b = amt / entries[k] * (1 - FEE)
                        base += b; quote -= amt; cost_basis += amt; ntr += 1
                    filled[k] = True
            if base > 0:
                avg = cost_basis / base
                tp = avg * 1.0035
                if h[i] >= tp and (filled[0] or filled[1] or filled[2]):
                    quote += base * tp * (1 - FEE)
                    base = 0.0; cost_basis = 0.0; open_cycle = False
            elif i - last_buy > 168:
                open_cycle = False  # ordens não executadas expiram no próximo ciclo
        eq[i] = quote + base * c[i]
    return eq, ntr


STRATEGIES = {
    "HB_bollinger_v1": hb_bollinger_v1,
    "HB_macd_bb_v1": hb_macd_bb_v1,
    "HB_supertrend_v1": hb_supertrend_v1,
    "OB_grid": ob_grid,
    "OB_trailing_grid": ob_trailing_grid,
    "OB_simple_dca": ob_simple_dca,
    "OB_smart_dca": ob_smart_dca,
    "OB_daily_trading": ob_daily,
}
