"""Estudo de evento dos padrões de análise técnica (research/ta/patterns.py).

Universo: moedas que estavam no top-30 spot por volume no dia do sinal (point-in-time, inclui mortas).
Timeframes: 4h e 1d (a partir de candles de 1h). Custo: 0,12% por lado (spot, sem alavancagem).
Para cada sinal: operação com gestão padronizada (stop técnico limitado a 1-4 ATR, depois stop móvel 3 ATR,
prazo máximo). Controle: entrada "cega" na MESMA moeda e MESMA barra com stop 2 ATR e mesma gestão.
Excesso = retorno do padrão - retorno do controle (isola o mérito do padrão do movimento do mercado).
Significância: t-stat por semana (agrupa operações da mesma semana, que são correlacionadas).
Filtros de contexto: tendência no diário (MTF) e regime BTC>SMA100.
"""
import warnings; warnings.filterwarnings("ignore")
import sys
from pathlib import Path
import numpy as np, pandas as pd
from numba import njit
from engine.core import ROOT, AGG
from research.r11_variants import load_spot
from research.ta.patterns import detect_all, manage, atr, ema, sma, NAMES

COST = 0.0012
TF = {"4h": dict(rule="4h", k=3, max_bars=60), "1d": dict(rule="1D", k=3, max_bars=30)}


@njit(cache=True)
def run_trades(o, h, l, c, A, S, ST, max_bars):
    P, n = S.shape
    R = np.full((P, n), np.nan); B = np.full(n, np.nan)
    for t in range(n - 1):
        if np.isnan(A[t]) or np.isnan(c[t]):
            continue
        r, _ = manage(o, h, l, c, A, t, c[t] - 2 * A[t], 3.0, max_bars, 1.0, 4.0)
        B[t] = r
        for p in range(P):
            if S[p, t]:
                rr, _ = manage(o, h, l, c, A, t, ST[p, t], 3.0, max_bars, 1.0, 4.0)
                R[p, t] = rr
    return R, B


def main(tf):
    cfg = TF[tf]
    Dspot = load_spot()
    V = Dspot["V"].rolling(30, min_periods=20).mean().where(Dspot["C"].notna().cumsum() >= 60)
    elig_d = V.rank(axis=1, ascending=False) <= 30
    btc = Dspot["C"]["BTC"]; reg = (btc > btc.rolling(100).mean()).shift(1)  # regime conhecido no início do dia
    rows = []
    for p in sorted((ROOT / "data/ta_1h").glob("*.parquet")):
        coin = p.stem
        if coin not in elig_d.columns:
            continue
        d = pd.read_parquet(p)
        d = d.resample(cfg["rule"]).agg(AGG).dropna()
        if len(d) < 400:
            continue
        o, h, l, c, v = (d[x].values.astype(np.float64) for x in ("open", "high", "low", "close", "volume"))
        S, ST = detect_all(o, h, l, c, v, cfg["k"])
        A = atr(h, l, c, 14)
        R, B = run_trades(o, h, l, c, A, S, ST, cfg["max_bars"])
        # contexto: elegibilidade e regime do dia (conhecidos no dia), tendência diária do próprio ativo (dia anterior)
        day = d.index.normalize()
        el = elig_d[coin].reindex(day).fillna(False).values
        rg = reg.reindex(day).fillna(False).values.astype(bool)
        dd = d["close"].resample("1D").last().dropna()
        e20d, e50d = dd.ewm(span=20).mean(), dd.ewm(span=50).mean()
        mtf = ((dd > e50d) & (e20d > e50d)).shift(1).reindex(day).fillna(False).values.astype(bool)
        if tf == "1d":
            mtf = np.ones(len(d), bool)
        for pi in range(S.shape[0]):
            ix = np.where(S[pi] & el & ~np.isnan(R[pi]) & ~np.isnan(B))[0]
            for t in ix:
                rows.append((NAMES[pi], coin, d.index[t], R[pi, t] - 2 * COST, B[t] - 2 * COST, mtf[t], rg[t]))
        # controle geral (todas as barras elegíveis) para referência
        ixb = np.where(el & ~np.isnan(B))[0]
        for t in ixb[::5]:
            rows.append(("_CONTROLE_todas_barras", coin, d.index[t], B[t] - 2 * COST, B[t] - 2 * COST, mtf[t], rg[t]))
    E = pd.DataFrame(rows, columns=["padrao", "moeda", "t", "ret", "ctrl", "mtf", "regime"])
    E["exc"] = E.ret - E.ctrl
    E.to_parquet(ROOT / f"results/r19_events_{tf}.parquet")
    return E


def stats(g):
    w = g.groupby(g.t.dt.to_period("W")).exc.mean()
    tstat = w.mean() / w.std() * np.sqrt(len(w)) if len(w) > 2 and w.std() > 0 else np.nan
    return pd.Series({"n": len(g), "ret_%": g.ret.mean() * 100, "acerto_%": (g.ret > 0).mean() * 100,
                      "excesso_%": g.exc.mean() * 100, "t_semanal": tstat})


def report(E, tf):
    E = E.copy()
    E["per"] = np.where(E.t < pd.Timestamp("2024-01-01", tz="UTC"), "DEV", "OOS")
    out = []
    for flt, mask in (("todos", E.padrao.notna()), ("MTF+regime", E.mtf & E.regime)):
        x = E[mask]
        for per in ("DEV", "OOS"):
            s = x[x.per == per].groupby("padrao").apply(stats)
            s.columns = [f"{per}_{c}" for c in s.columns]
            s["filtro"] = flt
            out.append(s)
    T = pd.concat([pd.concat(out[:2], axis=1), pd.concat(out[2:], axis=1)])
    T = T.loc[:, ~T.columns.duplicated()]
    T.to_csv(ROOT / f"results/r19_ta_{tf}.csv")
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    cols = ["filtro", "DEV_n", "DEV_ret_%", "DEV_acerto_%", "DEV_excesso_%", "DEV_t_semanal",
            "OOS_n", "OOS_ret_%", "OOS_acerto_%", "OOS_excesso_%", "OOS_t_semanal"]
    print(f"\n===== timeframe {tf} =====")
    print(T[cols].round(2).sort_values(["filtro", "DEV_excesso_%"], ascending=[False, False]).to_string())


if __name__ == "__main__":
    for tf in sys.argv[1:] or ["4h", "1d"]:
        E = main(tf)
        report(E, tf)
