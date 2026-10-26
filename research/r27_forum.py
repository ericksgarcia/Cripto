"""Fase 6 — estratégias populares de fóruns/YouTube/TradingView, testadas com as regras como publicadas.

Ativos: BTC e ETH (onde as promessas costumam ser feitas). Spot, sem alavancagem, custo 0,12% por lado, sinal no
fechamento e execução na abertura seguinte. Períodos: completo 2018-01 → 2026-10, DEV 2018-2023, OOS 2024-2026.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from engine.core import ROOT, AGG, sim_target
from research.r21_ta_portfolio import trade_ix
from research.ta.patterns import atr as atr_nb

COST = 0.0012
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)


def bars(sym, rule):
    d = pd.read_parquet(ROOT / "data/1m" / f"{sym}USDT.parquet").loc["2017-09-01":"2026-10-24"]
    return d.resample(rule).agg(AGG).dropna()


def ema(x, n): return x.ewm(span=n, adjust=False).mean()
def sma(x, n): return x.rolling(n).mean()


def rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def stochrsi(c, n=14, k=3, d=3):
    r = rsi(c, n); st = (r - r.rolling(n).min()) / (r.rolling(n).max() - r.rolling(n).min()) * 100
    K = st.rolling(k).mean(); return K, K.rolling(d).mean()


def atr(df, n=14):
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def state(entry, exit_):
    """Posição 0/1 a partir de sinais de entrada/saída (saída tem prioridade)."""
    pos = np.zeros(len(entry)); p = 0
    e, x = entry.fillna(False).values, exit_.fillna(False).values
    for i in range(len(e)):
        if p == 1 and x[i]:
            p = 0
        elif p == 0 and e[i]:
            p = 1
        pos[i] = p
    return pd.Series(pos, entry.index)


# ---------------------------------------------------------------- estratégias por posição
def s_rsi5(df):                     # 1: r/algotrading — compra RSI5>70, sai RSI5<70
    r = rsi(df.close, 5); return (r > 70).astype(float)


def s_zema65(df, thr=0.0):          # 2: r/algotrading — z-score do preço vs EMA65
    dev = df.close - ema(df.close, 65); z = dev / dev.rolling(65).std()
    return state(z > thr, z < 0)


def s_utbot(df, a=1.0, n=10):       # 4: UT Bot Alerts (stop móvel ATR), só compras
    c = df.close.values; xa = a * atr(df, n).values; ts = np.zeros(len(c)); pos = np.zeros(len(c)); p = 0
    for i in range(1, len(c)):
        pv = ts[i - 1]
        if c[i] > pv and c[i - 1] > pv:
            ts[i] = max(pv, c[i] - xa[i])
        elif c[i] < pv and c[i - 1] < pv:
            ts[i] = min(pv, c[i] + xa[i])
        elif c[i] > pv:
            ts[i] = c[i] - xa[i]
        else:
            ts[i] = c[i] + xa[i]
        if c[i] > ts[i] and c[i - 1] <= pv:
            p = 1
        elif c[i] < ts[i] and c[i - 1] >= pv:
            p = 0
        pos[i] = p
    return pd.Series(pos, df.index)


def gaussian(x, period=144, poles=4):
    beta = (1 - np.cos(2 * np.pi / period)) / (1.414 ** (2 / poles) - 1)
    alpha = -beta + np.sqrt(beta ** 2 + 2 * beta)
    y = x.values.astype(float).copy(); out = np.full(len(y), np.nan)
    f = np.nan_to_num(y.copy())
    for _ in range(poles):  # cascata de filtros EMA de 1 polo equivale ao filtro gaussiano de N polos
        g = np.zeros(len(f)); g[0] = f[0]
        for i in range(1, len(f)):
            g[i] = alpha * f[i] + (1 - alpha) * g[i - 1]
        f = g
    return pd.Series(f, x.index)


def s_gaussian(df, sma_gate=True):  # 5: Gaussian Channel (DonovanWall) + gate SMA200
    hlc3 = (df.high + df.low + df.close) / 3
    filt = gaussian(hlc3); tr = gaussian(atr(df, 1)); up = filt + 1.414 * tr
    entry = (df.close > up) & (filt > filt.shift(1))
    if sma_gate:
        entry &= df.close > sma(df.close, 200)
    return state(entry, df.close < up)


def s_squeeze(df):                  # 6: Squeeze Momentum (LazyBear)
    c = df.close; bb_m = sma(c, 20); bb_s = c.rolling(20).std() * 2
    kc_r = sma((df.high - df.low), 20) * 1.5
    sq_on = (bb_m - bb_s > bb_m - kc_r) & (bb_m + bb_s < bb_m + kc_r)
    mid = ((df.high.rolling(20).max() + df.low.rolling(20).min()) / 2 + sma(c, 20)) / 2
    val = (c - mid).rolling(20).apply(lambda y: np.polyfit(np.arange(20), y, 1)[0] * 19 + np.polyfit(np.arange(20), y, 1)[1], raw=True)
    entry = (~sq_on) & sq_on.shift(1).fillna(False) & (val > 0)
    return state(entry, val < val.shift(1))


def s_rsi2(df):                     # 9: Larry Connors RSI(2)
    return state((rsi(df.close, 2) < 10) & (df.close > sma(df.close, 200)), df.close > sma(df.close, 5))


def s_golden(df):                   # 10: cruz dourada
    return (sma(df.close, 50) > sma(df.close, 200)).astype(float)


def s_bmsb(df):                     # 11: Bull Market Support Band (semanal: SMA20 e EMA21)
    w = df.resample("W-SUN").agg(AGG).dropna()
    s20, e21 = sma(w.close, 20), ema(w.close, 21)
    pos = state(w.close > np.maximum(s20, e21), w.close < np.minimum(s20, e21))
    return pos.reindex(df.index, method="ffill").shift(1).fillna(0)  # decisão no fechamento semanal


def s_supertrend_ema(df, n=10, m=3.0):  # 12: Supertrend + EMA200
    a = atr(df, n); hl2 = (df.high + df.low) / 2; up = hl2 - m * a; dn = hl2 + m * a
    c = df.close.values; U = up.values.copy(); Dn = dn.values.copy(); d = np.ones(len(c))
    for i in range(1, len(c)):
        U[i] = max(U[i], U[i - 1]) if c[i - 1] > U[i - 1] else U[i]
        Dn[i] = min(Dn[i], Dn[i - 1]) if c[i - 1] < Dn[i - 1] else Dn[i]
        d[i] = 1 if c[i] > Dn[i - 1] else (-1 if c[i] < U[i - 1] else d[i - 1])
    return ((pd.Series(d, df.index) > 0) & (df.close > ema(df.close, 200))).astype(float)


def s_dow(df):                      # 13: comprar só segunda e sábado (Santiment)
    nxt = df.index + pd.Timedelta("1D")  # posição decidida em t vale para o dia t+1
    return pd.Series(np.isin(nxt.dayofweek, [0, 5]).astype(float), df.index)


HALVINGS = [pd.Timestamp(x, tz="UTC") for x in ("2016-07-09", "2020-05-11", "2024-04-19", "2028-04-15")]


def s_halving(df):                  # 14: ciclo do halving — compra 365d antes, vende 518d depois
    pos = pd.Series(0.0, df.index)
    for h in HALVINGS:
        pos[(df.index >= h - pd.Timedelta(days=365)) & (df.index < h + pd.Timedelta(days=518))] = 1.0
    return pos


def s_mayer(df):                    # 15: múltiplo de Mayer
    mm = df.close / sma(df.close, 200); return state(mm < 1.0, mm > 2.4)


def s_200w_pi(df):                  # 16: compra perto da média de 200 semanas, vende no Pi Cycle Top
    wma200 = sma(df.close, 1400); pi = sma(df.close, 111) > 2 * sma(df.close, 350)
    return state(df.close < 1.3 * wma200, pi & ~pi.shift(1).fillna(False))


def s_fear(df):                     # 17: "compre no medo extremo, venda na ganância" (substituto: queda+RSI)
    dd = df.close / df.close.rolling(90).max() - 1; r = rsi(df.close, 14)
    return state((dd < -0.30) & (r < 30), r > 75)


def s_rsi_bh(df):                   # referência
    return pd.Series(1.0, df.index)


# ---------------------------------------------------------------- estratégias por operação (stop/alvo)
def t_macd_ema(df):                 # 3: MACD + EMA200 (Trading Rush): stop na EMA200/fundo de 10 barras, alvo 1,5R
    c = df.close; macd = ema(c, 12) - ema(c, 26); sig = ema(macd, 9); e200 = ema(c, 200)
    entry = (macd > sig) & (macd.shift(1) <= sig.shift(1)) & (macd < 0) & (c > e200)
    stop = np.minimum(e200, df.low.rolling(10).min())
    return entry, stop, 1.5


def t_3esra(df):                    # 7: 3 EMAs (8/14/50) + StochRSI + ATR: stop 1 ATR, alvo 4 ATR
    c = df.close; e8, e14, e50 = ema(c, 8), ema(c, 14), ema(c, 50); K, D = stochrsi(c)
    entry = (e8 > e14) & (e14 > e50) & (c > e8) & (K > D) & (K.shift(1) <= D.shift(1))
    return entry, c - 1.0 * atr(df), 4.0


def t_ema_stoch_dip(df):            # 8: EMA50>EMA200 + StochRSI sai de <20: stop 1,5 ATR, alvo 2R
    c = df.close; K, D = stochrsi(c)
    entry = (ema(c, 50) > ema(c, 200)) & (K > 20) & (K.shift(1) <= 20)
    return entry, c - 1.5 * atr(df), 2.0


def t_scalp(df):                    # 18: scalping 5m EMA9/21 + RSI (alvo 1,5R, stop 1 ATR)
    c = df.close; r = rsi(c, 14)
    entry = (ema(c, 9) > ema(c, 21)) & (ema(c, 9).shift(1) <= ema(c, 21).shift(1)) & (r > 50) & (r < 75)
    return entry, c - 1.0 * atr(df), 1.5


def run_pos(df, pos):
    eq = sim_target(df.open.values.astype(float), pos.values.astype(float), COST)
    return pd.Series(eq, df.index), int((pos.diff().abs() > 0).sum() // 2)


def run_trades(df, fn):
    entry, stop, tp = fn(df)
    o, h, l, c = (df[x].values.astype(float) for x in ("open", "high", "low", "close"))
    A = atr_nb(h, l, c, 14)
    r = pd.Series(0.0, df.index); t = 0; n = 0; wins = 0; e = entry.fillna(False).values; s = stop.values
    while t < len(c) - 1:
        if e[t]:
            rr, ex = trade_ix(o, h, l, c, A, t, s[t], tp, 0.0, 100000, 0.1, 50.0)
            if ex > 0:
                net = rr - 2 * COST
                r.iloc[ex] += net; n += 1; wins += net > 0; t = ex; continue
        t += 1
    return (1 + r).cumprod(), n, wins / max(n, 1)


def perf(eq, a, b):
    x = eq[(eq.index >= a) & (eq.index <= b)]
    if len(x) < 10:
        return np.nan, np.nan
    d = x.resample("1D").last().ffill()
    yrs = (d.index[-1] - d.index[0]).days / 365.25
    return ((d.iloc[-1] / d.iloc[0]) ** (1 / yrs) - 1) * 100, (d / d.cummax() - 1).min() * 100


POS = {"1 RSI5>70 momentum (r/algotrading)": (s_rsi5, "1D"), "2 Z-score EMA65 (r/algotrading: 65,9%/ano)": (s_zema65, "1D"),
       "4 UT Bot (TradingView) 4h": (s_utbot, "4h"), "4 UT Bot (TradingView) 1d": (s_utbot, "1D"),
       "5 Gaussian Channel + SMA200 (TradingView)": (s_gaussian, "1D"), "6 Squeeze Momentum LazyBear 4h": (s_squeeze, "4h"),
       "6 Squeeze Momentum LazyBear 1d": (s_squeeze, "1D"), "9 RSI(2) Larry Connors": (s_rsi2, "1D"),
       "10 Cruz dourada 50/200": (s_golden, "1D"), "11 Bull Market Support Band": (s_bmsb, "1D"),
       "12 Supertrend + EMA200 4h": (s_supertrend_ema, "4h"), "13 Só segunda e sábado (Santiment)": (s_dow, "1D"),
       "14 Ciclo do halving": (s_halving, "1D"), "15 Múltiplo de Mayer": (s_mayer, "1D"),
       "16 200 semanas + Pi Cycle": (s_200w_pi, "1D"), "17 Medo/ganância (substituto de preço)": (s_fear, "1D"),
       "0 Comprar e segurar": (s_rsi_bh, "1D")}
TRD = {"3 MACD+EMA200 (Trading Rush) 15m": (t_macd_ema, "15min"), "3 MACD+EMA200 (Trading Rush) 1h": (t_macd_ema, "1h"),
       "3 MACD+EMA200 (Trading Rush) 4h": (t_macd_ema, "4h"), "7 3EMA+StochRSI+ATR 1h": (t_3esra, "1h"),
       "7 3EMA+StochRSI+ATR 4h": (t_3esra, "4h"), "8 EMA50/200+StochRSI fundo 1h": (t_ema_stoch_dip, "1h"),
       "8 EMA50/200+StochRSI fundo 4h": (t_ema_stoch_dip, "4h"), "18 Scalping 5m EMA9/21+RSI": (t_scalp, "5min")}

if __name__ == "__main__":
    cache = {}
    rows = []
    for sym in ("BTC", "ETH"):
        for name, (fn, rule) in {**POS, **TRD}.items():
            if fn in (s_halving, s_200w_pi) and sym == "ETH":
                continue
            key = (sym, rule)
            if key not in cache:
                cache[key] = bars(sym, rule)
            df = cache[key]
            if name in POS:
                eq, n = run_pos(df, fn(df)); win = np.nan
            else:
                eq, n, win = run_trades(df, fn)
            full, dev, oos = perf(eq, "2018-01-01", "2026-10-24"), perf(eq, "2018-01-01", "2023-12-31"), perf(eq, "2024-01-01", "2026-10-24")
            rows.append({"estratégia": name, "ativo": sym, "ops": n, "acerto_%": win * 100 if win == win else np.nan,
                         "CAGR_2018-26": full[0], "DD_2018-26": full[1], "CAGR_DEV": dev[0], "CAGR_OOS": oos[0], "DD_OOS": oos[1]})
            print(sym, name, flush=True)
    T = pd.DataFrame(rows).round(1)
    T.to_csv(ROOT / "results/r27_forum.csv", index=False)
