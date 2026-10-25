"""Candidatas: (A) carry spot+perp delta-neutro, (B) tendência long/flat com vol target, (C) combinação.
Hipóteses fixadas antes de ver resultados. Dados diários, custos explícitos."""
import numpy as np, pandas as pd
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "data" / "processed2"
RES = Path(__file__).resolve().parent.parent / "results"
SYMS = sorted({p.name.split("_")[0] for p in D.glob("*_spot_1d.parquet")})
SPOT_FEE, PERP_FEE = 0.0010, 0.0005  # por perna, incluindo slippage

def load():
    spot, perp, fund = {}, {}, {}
    for s in SYMS:
        spot[s] = pd.read_parquet(D / f"{s}_spot_1d.parquet")["close"]
        if (D / f"{s}_perp_1d.parquet").exists(): perp[s] = pd.read_parquet(D / f"{s}_perp_1d.parquet")["close"]
        if (D / f"{s}_funding.parquet").exists():
            f = pd.read_parquet(D / f"{s}_funding.parquet")["last_funding_rate"]
            fund[s] = f.resample("1D").sum(min_count=1)  # funding acumulado por dia
    return pd.DataFrame(spot), pd.DataFrame(perp), pd.DataFrame(fund)

def stats(r, name):
    r = r.dropna(); r = r[r.index >= r.ne(0).idxmax()] if r.ne(0).any() else r
    eq = (1 + r).cumprod(); dd = (eq / eq.cummax() - 1).min()
    ann = eq.iloc[-1] ** (365 / len(r)) - 1
    return dict(strategy=name, cagr=ann, vol=r.std() * np.sqrt(365), sharpe=r.mean() / (r.std() + 1e-12) * np.sqrt(365), maxdd=dd, start=str(r.index[0].date()))

def split(r):
    return {"2020-22": r[:"2022-12-31"], "2023-26": r["2023-01-01":]}

# ---------------- A. Carry ----------------
def carry(spot, perp, fund, hi=0.15, lo=0.05, win=14, fee_on=True, always=False):
    spot, perp = spot.reindex(perp.index), perp
    r_s, r_p = spot.pct_change(), perp.pct_change()
    apr = fund.reindex(perp.index).rolling(win, min_periods=win).mean() * 365
    sig = pd.DataFrame(False, index=perp.index, columns=perp.columns)
    for c in perp.columns:
        on = False; v = []
        for x in apr[c].shift(1).values:       # decisão com info até o dia anterior
            if always: on = not np.isnan(x)
            elif not on and x > hi: on = True
            elif on and x < lo: on = False
            v.append(on)
        sig[c] = v
    w = sig.astype(float); n = w.sum(axis=1).clip(lower=1)
    w = w.div(n, axis=0)               # capital igual entre ativos ativos (100% do capital alocado)
    leg = (r_s - r_p + fund.reindex(perp.index)).fillna(0)  # retorno por unidade de notional (spot long - perp short + funding)
    gross = (w * leg).sum(axis=1) * 0.5          # notional de cada perna = 50% do capital (sem alavancagem)
    turn = w.diff().abs().sum(axis=1).fillna(0)
    cost = turn * 0.5 * 2 * (SPOT_FEE + PERP_FEE) if fee_on else 0  # ida: abre/fecha as duas pernas
    return gross - cost, w

# ---------------- B. Tendência long/flat ----------------
def trend(spot, L=100, kind="sma", vt=0.40, maxlev=1.0, fee=0.0010):
    r = spot.pct_change()
    sig = (spot > spot.rolling(L).mean()) if kind == "sma" else (spot.pct_change(L) > 0)
    vol = r.rolling(30).std() * np.sqrt(365)
    w = (sig.shift(1).astype(float) * (vt / vol.shift(1)).clip(upper=maxlev)).fillna(0)
    n = spot.notna().sum(axis=1).clip(lower=1)
    w = w.div(n, axis=0)                          # 1/N por ativo disponível
    gross = (w * r.fillna(0)).sum(axis=1)
    cost = w.diff().abs().sum(axis=1).fillna(0) * fee
    return gross - cost, w

if __name__ == "__main__":
    spot, perp, fund = load()
    pd.set_option("display.width", 200); pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
    rows, curves = [], {}
    def add(name, r):
        for k, v in {"full": r, **split(r)}.items():
            d = stats(v, f"{name} | {k}"); rows.append(d)
        curves[name] = r
    # baselines
    r_btc = spot["BTCUSDT"].pct_change(); add("B&H BTC", r_btc)
    r_eqw = spot.pct_change().mean(axis=1); add("B&H igual-peso 25", r_eqw)
    # A. carry
    for tag, kw in {"carry seletivo (15%/5%)": {}, "carry sempre-ligado": dict(always=True),
                    "carry seletivo 15%/5% sem custo": dict(fee_on=False)}.items():
        r, w = carry(spot, perp, fund, **kw); add(tag, r)
    # B. tendência
    sub = spot[["BTCUSDT", "ETHUSDT"]]
    for L in (50, 100, 200):
        r, _ = trend(sub, L); add(f"tendência SMA{L} BTC+ETH", r)
        r, _ = trend(spot, L); add(f"tendência SMA{L} universo", r)
    print(pd.DataFrame(rows).set_index("strategy").to_string())
    pd.DataFrame(curves).to_parquet(RES / "curves2.parquet")
    pd.DataFrame(rows).to_csv(RES / "research2_summary.csv", index=False)
