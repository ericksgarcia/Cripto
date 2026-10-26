"""Fase 4 — saídas otimizadas para os sinais de reversão que mostraram vantagem (spring, divergência RSI, HA),
e confluências. Escolha da saída só no DEV (2018-2023); OOS 2024-2026 apenas reportado.

Gestão: stop técnico (limitado a [0.5, 3] ATR), alvo em múltiplos do risco (R) ou nenhum, stop móvel opcional,
saída por tempo. Custo 0,12% por lado. Excesso medido contra entradas aleatórias da mesma semana.
"""
import warnings; warnings.filterwarnings("ignore")
import itertools, sys
import numpy as np, pandas as pd
from numba import njit
from engine.core import ROOT, AGG
from research.r11_variants import load_spot
from research.ta.patterns import detect_all, atr, NAMES

COST = 0.0012
SEL = {"Varredura_liquidez_spring": 2, "Divergencia_RSI": 12, "HeikinAshi_reversao": 16, "SMC_varredura+CHoCH": 17,
       "Engolfo_em_suporte": 13}


@njit(cache=True)
def trade(o, h, l, c, A, t0, stop0, tp_r, trail, max_bars, min_r, max_r):
    n = len(c); e = t0 + 1
    if e >= n or np.isnan(o[e]) or np.isnan(A[t0]):
        return np.nan
    entry = o[e]; at = A[t0]
    risk = entry - stop0
    if np.isnan(risk) or risk < min_r * at:
        risk = min_r * at
    if risk > max_r * at:
        risk = max_r * at
    stop = entry - risk
    tp = entry + tp_r * risk if tp_r > 0 else 1e18
    hc = entry
    for i in range(e, min(n, e + max_bars)):
        if l[i] <= stop:
            return min(o[i], stop) / entry - 1
        if h[i] >= tp:
            return max(o[i], tp) / entry - 1 if i > e else tp / entry - 1
        hc = max(hc, c[i])
        if trail > 0 and not np.isnan(A[i]):
            stop = max(stop, hc - trail * A[i])
    last = min(n, e + max_bars) - 1
    return c[last] / entry - 1


def gather(tf, k=3):
    Dspot = load_spot()
    V = Dspot["V"].rolling(30, min_periods=20).mean().where(Dspot["C"].notna().cumsum() >= 60)
    elig_d = V.rank(axis=1, ascending=False) <= 30
    data = []
    for p in sorted((ROOT / "data/ta_1h").glob("*.parquet")):
        coin = p.stem
        if coin not in elig_d.columns:
            continue
        d = pd.read_parquet(p).resample({"4h": "4h", "1d": "1D"}[tf]).agg(AGG).dropna()
        if len(d) < 400:
            continue
        arr = tuple(d[x].values.astype(np.float64) for x in ("open", "high", "low", "close", "volume"))
        S, ST = detect_all(*arr, k)
        el = elig_d[coin].reindex(d.index.normalize()).fillna(False).values
        data.append((coin, d.index, arr, atr(arr[1], arr[2], arr[3], 14), S, ST, el))
    return data


if __name__ == "__main__":
    tf = sys.argv[1] if len(sys.argv) > 1 else "4h"
    data = gather(tf)
    # controle semanal: entradas aleatórias (a cada 5 barras) com a mesma gestão de cada configuração
    exits = list(itertools.product((0.0, 1.0, 1.5, 2.0, 3.0), (0.0, 2.0, 3.0), (6, 12, 24, 48) if tf == "4h" else (3, 5, 10, 20)))
    signals = dict(SEL)
    rows = []
    for tp_r, trail, mb in exits:
        if tp_r == 0 and trail == 0 and mb == (48 if tf == "4h" else 20):
            pass
        ctrl, recs = [], []
        for coin, idx, (o, h, l, c, v), A, S, ST, el in data:
            for t in range(260, len(c) - 1, 5):
                if el[t]:
                    r = trade(o, h, l, c, A, t, c[t] - 1.5 * A[t], tp_r, trail, mb, 0.5, 3.0)
                    if not np.isnan(r):
                        ctrl.append((idx[t], r - 2 * COST))
            for name, pi in signals.items():
                for t in np.where(S[pi] & el)[0]:
                    r = trade(o, h, l, c, A, t, ST[pi, t], tp_r, trail, mb, 0.5, 3.0)
                    if not np.isnan(r):
                        recs.append((name, idx[t], r - 2 * COST))
            # confluência: spring + divergência RSI ou HA nas últimas 3 barras
            spring = S[2]; div = S[12] | S[16]
            conf = np.zeros(len(c), np.bool_)
            for t in np.where(spring & el)[0]:
                if div[max(0, t - 3):t + 1].any():
                    conf[t] = True
            for t in np.where(conf)[0]:
                r = trade(o, h, l, c, A, t, ST[2, t], tp_r, trail, mb, 0.5, 3.0)
                if not np.isnan(r):
                    recs.append(("CONF_spring+div/HA", idx[t], r - 2 * COST))
        C = pd.DataFrame(ctrl, columns=["t", "r"]); C["wk"] = C.t.dt.to_period("W")
        bench = C.groupby("wk").r.mean()
        R = pd.DataFrame(recs, columns=["padrao", "t", "r"]); R["wk"] = R.t.dt.to_period("W")
        R["exc"] = R.r - R.wk.map(bench).fillna(0)
        R["per"] = np.where(R.t < pd.Timestamp("2024-01-01", tz="UTC"), "DEV", "OOS")
        for (pd_, per), g in R.groupby(["padrao", "per"]):
            w = g.groupby("wk").exc.mean()
            rows.append({"padrao": pd_, "per": per, "tp_R": tp_r, "trail": trail, "max_barras": mb, "n": len(g),
                         "ret_%": g.r.mean() * 100, "acerto_%": (g.r > 0).mean() * 100, "excesso_%": g.exc.mean() * 100,
                         "t": w.mean() / w.std() * np.sqrt(len(w)) if len(w) > 2 else np.nan})
        print(tp_r, trail, mb, flush=True)
    T = pd.DataFrame(rows)
    T.to_csv(ROOT / f"results/r20_exits_{tf}.csv", index=False)
    W = T.pivot_table(index=["padrao", "tp_R", "trail", "max_barras"], columns="per", values=["n", "ret_%", "acerto_%", "excesso_%", "t"])
    W.columns = [f"{b}_{a}" for a, b in W.columns]
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
    best = W.reset_index().sort_values("DEV_ret_%", ascending=False).groupby("padrao").head(4)
    print(best.round(2).to_string(index=False))
