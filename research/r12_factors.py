"""Fase 3 — outras fontes de retorno em perpétuos (universo completo, inclui deslistados).

1. NEW LISTING SHORT: vende a descoberto cada perp recém-listado do dia d0 ao dia d1 após a listagem,
   com stop de squeeze (fecha se subir x% acima da entrada). Funding real pago/recebido.
2. FUNDING FACTOR: cross-section diário; compra as de funding médio mais baixo, vende as de funding mais alto.
3. REVERSÃO DE CURTO PRAZO: compra os maiores perdedores de 1-3 dias e vende os maiores ganhadores (neutro).
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import numpy as np, pandas as pd
from numba import njit
from engine.core import ROOT
from research.r11_variants import load_perps, sim_np, stats, Feats, COST, DEV, OOS

pd.set_option("display.width", 250)


@njit(cache=True)
def listing_short_weights(C, first, d0, d1, slot, stop, max_gross):
    T, K = C.shape
    W = np.zeros((T, K))
    entry = np.zeros(K)
    stopped = np.zeros(K, np.bool_)
    for t in range(T):
        g = 0.0
        for k in range(K):
            age = t - first[k]
            if first[k] < 0 or np.isnan(C[t, k]):
                continue
            if age == d0:
                entry[k] = C[t, k]; stopped[k] = False
            if d0 <= age < d1 and not stopped[k] and entry[k] > 0:
                if C[t, k] > entry[k] * (1 + stop):
                    stopped[k] = True
                    continue
                if g + slot <= max_gross + 1e-9:
                    W[t, k] = -slot; g += slot
    return W


def report(r, label, extra=None):
    d, o, a = stats(r, *DEV), stats(r, *OOS), stats(r, "2020-07-01", "2026-10-25")
    row = {"strategy": label, "DEV_cagr": d[0] * 100, "DEV_sharpe": d[1], "DEV_dd": d[2] * 100,
           "OOS_cagr": o[0] * 100, "OOS_sharpe": o[1], "OOS_dd": o[2] * 100,
           "ALL_cagr": a[0] * 100, "ALL_sharpe": a[1], "ALL_dd": a[2] * 100}
    row["ALL_mes_%"] = ((1 + row["ALL_cagr"] / 100) ** (1 / 12) - 1) * 100
    if extra:
        row.update(extra)
    return row


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    D = load_perps()
    fe = Feats(D)
    C = D["C"]; O = D["O"].values.astype(np.float64); F = D["F"].values.astype(np.float64)
    idx = C.index
    rows, curves = [], {}
    if which in ("all", "listing"):
        first = np.array([np.argmax(C[c].notna().values) if C[c].notna().any() else -1 for c in C])
        # perps que já existiam no início dos dados não são "novas listagens"
        first = np.where(first == 0, -1, first)
        print("novas listagens no período:", int((first > 0).sum()))
        for d0 in (1, 3, 7, 14):
            for d1 in (30, 60, 120):
                for stop in (0.3, 0.6, 1e9):
                    for slot in (0.05, 0.1):
                        W = listing_short_weights(C.values, first, d0, d1, slot, stop, 1.0)
                        r = pd.Series(sim_np(O, W, F, COST, fe.Hv, fe.Lv, fe.Cv, 0.0), idx)
                        name = f"LIST_d{d0}-{d1}_stop{stop if stop < 1e8 else 'none'}_slot{slot}"
                        rows.append(report(r, name, {"posições_médias": float((W != 0).sum(1).mean())}))
                        curves[name] = r
    if which in ("all", "funding", "reversal"):
        for N in (20, 50, 100):
            el = fe.elig(N)
            Fm = {n: D["F"].rolling(n).mean().where(el) for n in (1, 3, 7)}
            for n in (1, 3, 7):
                for k in (3, 5, 10):
                    rk_lo = Fm[n].rank(axis=1, ascending=True); rk_hi = Fm[n].rank(axis=1, ascending=False)
                    for side in ("ls", "short_hi", "long_lo"):
                        W = pd.DataFrame(0.0, idx, C.columns)
                        if side in ("ls", "long_lo"):
                            W += (rk_lo <= k).astype(float) * (0.5 if side == "ls" else 1.0) / k
                        if side in ("ls", "short_hi"):
                            W -= (rk_hi <= k).astype(float) * (0.5 if side == "ls" else 1.0) / k
                        r = pd.Series(sim_np(O, W.values, F, COST, fe.Hv, fe.Lv, fe.Cv, 0.0), idx)
                        name = f"FUND_{side}_U{N}_n{n}_k{k}"
                        rows.append(report(r, name)); curves[name] = r
            for n in (1, 3):
                for k in (3, 5, 10):
                    ret = fe.ret(n).where(el)
                    lo = ret.rank(axis=1, ascending=True) <= k; hi = ret.rank(axis=1, ascending=False) <= k
                    W = (lo.astype(float) * 0.5 / k - hi.astype(float) * 0.5 / k)
                    r = pd.Series(sim_np(O, W.values, F, COST, fe.Hv, fe.Lv, fe.Cv, 0.0), idx)
                    name = f"REV_U{N}_n{n}_k{k}"
                    rows.append(report(r, name)); curves[name] = r
    T = pd.DataFrame(rows).set_index("strategy").round(2).sort_values("DEV_sharpe", ascending=False)
    T.to_csv(ROOT / f"results/r12_{which}.csv")
    pd.DataFrame(curves).astype(np.float32).to_parquet(ROOT / f"results/r12_{which}_returns.parquet")
    print(T.head(40).to_string())
    print("...\npiores:\n", T.tail(5).to_string())
