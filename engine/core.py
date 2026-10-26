"""Motor de backtest comum (numba) usado para portar estratégias de Hummingbot, OctoBot e as estratégias próprias.

Convenções:
- Sinais calculados no fechamento da barra i são executados na abertura da barra i+1 (sem look-ahead).
- Taxa padrão 0,1% por lado + 0,02% de slippage (Binance spot sem desconto BNB).
- Cada par recebe a mesma fração do capital; a curva da carteira é a soma das curvas dos pares.
"""
import os
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

ROOT = Path(__file__).resolve().parents[1]
SYMS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "LTC", "LINK", "AVAX"]
START = "2021-01-01"
END = os.environ.get("CRIPTO_END", "2026-10-25")  # fim fixo dos backtests; o script de sinal usa "2100-01-01"
FEE = 0.001
SLIP = 0.0002
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

_cache = {}


def load(sym, tf, start="2020-06-01", end=END):
    """Carrega candles; '3m' e '2h' etc. são reamostrados a partir de 1m/5m."""
    key = (sym, tf, start, end)
    if key in _cache:
        return _cache[key]
    p = ROOT / "data" / tf / f"{sym}USDT.parquet"
    if p.exists():
        df = pd.read_parquet(p)
    else:
        base = "1m" if tf.endswith("m") else "1h"
        df = pd.read_parquet(ROOT / "data" / base / f"{sym}USDT.parquet")
        rule = tf.replace("m", "min").replace("d", "D")
        df = df.resample(rule).agg(AGG).dropna()
    df = df.loc[start:end].copy()
    df = df[df.index < pd.Timestamp(end, tz="UTC")]
    if tf not in ("1m", "3m"):
        _cache[key] = df
    return df


# --------------------------------------------------------------------------------------------
# 1) Exposição-alvo (estratégias de tendência / momentum / carteira)
# --------------------------------------------------------------------------------------------
@njit(cache=True)
def sim_target(o, w, cost):
    """w[i] = exposição desejada decidida no fechamento da barra i (-1..+1, alavancagem permitida).
    Executa na abertura i+1. Retorna equity marcada na abertura de cada barra (eq[0]=1)."""
    n = len(o)
    eq = np.ones(n)
    pos = 0.0  # exposição corrente (fração do equity) após rebalanceamento
    for i in range(1, n):
        # retorno da barra anterior (open i-1 -> open i) com a posição vigente
        r = o[i] / o[i - 1] - 1.0
        e = eq[i - 1] * (1.0 + pos * r)
        # deriva da exposição após o movimento
        if e > 0:
            pos = pos * (1.0 + r) * eq[i - 1] / e
        tgt = w[i - 1]
        if np.isnan(tgt):
            tgt = 0.0
        d = abs(tgt - pos)
        if d > 1e-9:
            e -= d * e * cost
            pos = tgt
        eq[i] = max(e, 0.0)
    return eq


# --------------------------------------------------------------------------------------------
# 2) Triple barrier (Hummingbot V2 directional controllers: SL / TP / time limit / cooldown)
# --------------------------------------------------------------------------------------------
@njit(cache=True)
def sim_triple_barrier(o, h, l, c, sig, sl, tp, tlim, max_per_side, cooldown, cost, size):
    """sig[i] in {-1,0,1} no fechamento da barra i -> abre executor na abertura i+1.
    size = fração do equity por executor. SL tem prioridade se SL e TP tocam na mesma barra."""
    n = len(o)
    eq = np.ones(n)
    cash = 1.0
    M = 64
    act = np.zeros(M, np.bool_)
    side = np.zeros(M)
    entry = np.zeros(M)
    t0 = np.zeros(M, np.int64)
    notional = np.zeros(M)
    last_open = np.full(2, -10**9)
    ntr = 0
    for i in range(1, n):
        s = sig[i - 1]
        if s != 0:
            k = 0 if s > 0 else 1
            cnt = 0
            for j in range(M):
                if act[j] and side[j] == s:
                    cnt += 1
            if cnt < max_per_side and i - last_open[k] > cooldown:
                for j in range(M):
                    if not act[j]:
                        # equity atual estimado para dimensionar
                        e = cash
                        for q in range(M):
                            if act[q]:
                                e += notional[q] * side[q] * (o[i] / entry[q] - 1.0)
                        act[j] = True; side[j] = s; entry[j] = o[i]; t0[j] = i
                        notional[j] = e * size
                        cash -= notional[j] * cost
                        last_open[k] = i
                        ntr += 1
                        break
        # checa barreiras nesta barra
        for j in range(M):
            if not act[j]:
                continue
            ex = -1.0
            if side[j] > 0:
                if l[i] <= entry[j] * (1 - sl):
                    ex = entry[j] * (1 - sl)
                elif h[i] >= entry[j] * (1 + tp):
                    ex = entry[j] * (1 + tp)
            else:
                if h[i] >= entry[j] * (1 + sl):
                    ex = entry[j] * (1 + sl)
                elif l[i] <= entry[j] * (1 - tp):
                    ex = entry[j] * (1 - tp)
            if ex < 0 and i - t0[j] + 1 >= tlim:
                ex = c[i]
            if ex > 0:
                cash += notional[j] * side[j] * (ex / entry[j] - 1.0) - notional[j] * cost
                act[j] = False
        e = cash
        for q in range(M):
            if act[q]:
                e += notional[q] * side[q] * (c[i] / entry[q] - 1.0)
        eq[i] = max(e, 0.0)
    return eq, ntr


# --------------------------------------------------------------------------------------------
# 3) Grid (OctoBot GridTradingMode, versão percentual) com trailing up opcional
# --------------------------------------------------------------------------------------------
@njit(cache=True)
def _grid_build(p, quote, base, price, qty, alive, n_orders, inc, spread, fee):
    """Rebalanceia para 50/50 e cria n ordens de compra abaixo e n de venda acima de p."""
    val = quote + base * p
    tgt_base = val * 0.5 / p
    d = tgt_base - base
    if d > 0:
        quote -= d * p * (1 + fee)
    else:
        quote += -d * p * (1 - fee)
    base = tgt_base
    alive[:] = False
    for k in range(n_orders):
        price[k] = p * (1 - spread / 2) * (1 - inc) ** k
        qty[k] = quote / n_orders
        alive[k] = True
        price[n_orders + k] = p * (1 + spread / 2) * (1 + inc) ** k
        qty[n_orders + k] = -base / n_orders
        alive[n_orders + k] = True
    return quote, base


@njit(cache=True)
def sim_grid(o, h, l, c, n_orders, inc, spread, trailing_up, fee):
    n = len(o)
    eq = np.ones(n)
    N = 2 * n_orders + 4
    price = np.zeros(N)
    qty = np.zeros(N)        # >0 compra (em quote), <0 venda (em base)
    alive = np.zeros(N, np.bool_)
    quote = 1.0
    base = 0.0
    nfills = 0

    quote, base = _grid_build(o[0], quote, base, price, qty, alive, n_orders, inc, spread, fee)
    md = spread - inc  # distância do espelho (flat_spread - flat_increment)
    for i in range(n):
        new_p = np.zeros(N); new_q = np.zeros(N); nn = 0
        for k in range(N):
            if not alive[k]:
                continue
            if qty[k] > 0 and l[i] <= price[k]:
                b = qty[k] / price[k] * (1 - fee)
                quote -= qty[k]; base += b
                alive[k] = False; nfills += 1
                new_p[nn] = price[k] * (1 + md); new_q[nn] = -b; nn += 1
            elif qty[k] < 0 and h[i] >= price[k]:
                q = -qty[k] * price[k] * (1 - fee)
                base += qty[k]; quote += q
                alive[k] = False; nfills += 1
                new_p[nn] = price[k] * (1 - md); new_q[nn] = q; nn += 1
        # ordens espelho entram ativas a partir da próxima barra
        for m in range(nn):
            for k in range(N):
                if not alive[k]:
                    price[k] = new_p[m]; qty[k] = new_q[m]; alive[k] = True
                    break
        if base < 0:
            base = 0.0
        if trailing_up:
            any_sell = False
            hi = 0.0
            for k in range(N):
                if alive[k] and qty[k] < 0:
                    any_sell = True
            if not any_sell:
                for k in range(N):
                    if alive[k] and price[k] > hi:
                        hi = price[k]
                if c[i] > hi * (1 + spread):
                    quote, base = _grid_build(c[i], quote, base, price, qty, alive, n_orders, inc, spread, fee)
        eq[i] = quote + base * c[i]
    return eq, nfills


# --------------------------------------------------------------------------------------------
# Métricas
# --------------------------------------------------------------------------------------------
def metrics(eq: pd.Series):
    eq = eq.dropna()
    eq = eq[eq.index >= pd.Timestamp(START, tz="UTC")]
    eq = eq / eq.iloc[0]
    d = eq.resample("1D").last().dropna()
    yrs = (d.index[-1] - d.index[0]).days / 365.25
    r = d.pct_change().dropna()
    cagr = d.iloc[-1] ** (1 / yrs) - 1 if d.iloc[-1] > 0 else -1
    dd = (d / d.cummax() - 1).min()
    sh = r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else 0
    neg = r[r < 0]
    so = r.mean() / neg.std() * np.sqrt(365) if len(neg) > 1 else 0
    yearly = d.resample("YE").last().pct_change()
    yearly.iloc[0] = d.resample("YE").last().iloc[0] / d.iloc[0] - 1
    return {"total_%": (d.iloc[-1] - 1) * 100, "cagr_%": cagr * 100, "maxdd_%": dd * 100, "sharpe": sh,
            "sortino": so, "calmar": (cagr / -dd) if dd < 0 else np.nan,
            **{f"y{y.year}_%": v * 100 for y, v in yearly.items()}}


def portfolio(curves: dict, weights=None):
    """Soma curvas por par (cada uma começando em 1 na sua data inicial; caixa parado antes de listar)."""
    df = pd.DataFrame(curves)
    idx = pd.date_range(START, END, freq="1D", tz="UTC", inclusive="left")
    df = df.resample("1D").last().reindex(idx).ffill().fillna(1.0)
    w = weights or {k: 1 / len(curves) for k in curves}
    return sum(df[k] * w[k] for k in df)


@njit(cache=True)
def sim_multi(O, W, cost, band):
    """Carteira multiativo com capital compartilhado.
    O[t, k] = abertura; W[t, k] = peso-alvo decidido no fechamento de t (executado na abertura t+1).
    NaN em O => ativo indisponível (peso forçado a 0). band = banda relativa de rebalanceamento (reduz giro)."""
    T, K = O.shape
    eq = np.ones(T)
    pos = np.zeros(K)   # peso corrente
    turn = 0.0
    for t in range(1, T):
        r_port = 0.0
        for k in range(K):
            if pos[k] != 0.0 and not np.isnan(O[t, k]) and not np.isnan(O[t - 1, k]):
                r = O[t, k] / O[t - 1, k] - 1.0
                r_port += pos[k] * r
        e = eq[t - 1] * (1.0 + r_port)
        # deriva
        for k in range(K):
            if pos[k] != 0.0 and not np.isnan(O[t, k]) and not np.isnan(O[t - 1, k]):
                pos[k] = pos[k] * (O[t, k] / O[t - 1, k]) * eq[t - 1] / e
        c = 0.0
        for k in range(K):
            tgt = W[t - 1, k]
            if np.isnan(tgt) or np.isnan(O[t, k]):
                tgt = 0.0
            d = tgt - pos[k]
            if (tgt == 0.0) != (pos[k] == 0.0) or abs(d) > band * abs(tgt):
                c += abs(d)
                pos[k] = tgt
        turn += c
        e -= e * c * cost
        eq[t] = max(e, 0.0)
    return eq, turn


def panel(tf, start="2017-08-01", end=END, field="close"):
    return pd.DataFrame({s: load(s, tf, start=start, end=end)[field] for s in SYMS})
