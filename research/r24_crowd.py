"""Fase 5 — "contra-ataque": eventos em que a multidão (varejo) entra de forma previsível.

Para cada evento (no fechamento do dia t, entrada na abertura de t+1) mede o retorno a frente em H dias, líquido de
custo (0,24% ida e volta), relativo a um controle SEM olhar o futuro: ALTS = média do retorno a frente de todas as
alts elegíveis no MESMO dia (remove o movimento do mercado); MAIORES = média do próprio ativo no período (DEV ou OOS).
Positivo = comprar ganha; negativo = vender/ficar de fora ganha.
Grupos: MAIORES (BTC, ETH) e ALTS (top-30 por volume spot no dia, point-in-time).
DEV = 2018-2023, OOS = 2024-2026. t-stat agrupando por semana.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from engine.core import ROOT
from research.r11_variants import load_spot

COST = 0.0024
HS = (1, 3, 7, 14)


def rsi(c, n=14):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def events_for(o, h, l, c):
    """Retorna dict nome -> série booleana (evento no fechamento de t)."""
    E = {}
    for N in (20, 55):
        hiN = h.rolling(N).max().shift(1); loN = l.rolling(N).min().shift(1)
        bo = (c > hiN) & (c.shift(1) <= hiN.shift(1))
        bd = (c < loN) & (c.shift(1) >= loN.shift(1))
        E[f"rompe_max_{N}d (multidão compra)"] = bo
        E[f"rompe_min_{N}d (multidão vende)"] = bd
        # rompimento que falha em até 3 dias: fecha de volta abaixo do nível rompido
        lvl_bo = hiN.where(bo).ffill(limit=3); lvl_bd = loN.where(bd).ffill(limit=3)
        recent_bo = bo.rolling(3).max().shift(1).fillna(0).astype(bool)
        recent_bd = bd.rolling(3).max().shift(1).fillna(0).astype(bool)
        E[f"armadilha_alta_{N}d (rompe e volta)"] = recent_bo & (c < lvl_bo.shift(1))
        E[f"armadilha_baixa_{N}d (perde e recupera)"] = recent_bd & (c > lvl_bd.shift(1))
        # varredura intradiária: mínima fura o fundo de N dias mas fecha acima (stop hunt no mesmo dia)
        E[f"varredura_min_{N}d (caça de stops)"] = (l < loN) & (c > loN)
        E[f"varredura_max_{N}d (caça de stops vendidos)"] = (h > hiN) & (c < hiN)
    pdl = l.shift(1); pdh = h.shift(1)
    E["varre_minima_dia_anterior e fecha acima"] = (l < pdl) & (c > pdl) & (c > o)
    E["varre_maxima_dia_anterior e fecha abaixo"] = (h > pdh) & (c < pdh) & (c < o)
    r = rsi(c)
    E["RSI cruza acima de 70 (varejo vende)"] = (r > 70) & (r.shift(1) <= 70)
    E["RSI cruza abaixo de 30 (varejo compra)"] = (r < 30) & (r.shift(1) >= 30)
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    E["cruz_dourada 50/200"] = (s50 > s200) & (s50.shift(1) <= s200.shift(1))
    E["cruz_da_morte 50/200"] = (s50 < s200) & (s50.shift(1) >= s200.shift(1))
    m20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    E["fecha abaixo Bollinger inferior (varejo compra)"] = (c < m20 - 2 * sd20) & (c.shift(1) >= (m20 - 2 * sd20).shift(1))
    E["fecha acima Bollinger superior (varejo vende)"] = (c > m20 + 2 * sd20) & (c.shift(1) <= (m20 + 2 * sd20).shift(1))
    ema12, ema26 = c.ewm(span=12).mean(), c.ewm(span=26).mean(); macd = ema12 - ema26; sig = macd.ewm(span=9).mean()
    E["MACD cruza p/ cima abaixo de zero (varejo compra)"] = (macd > sig) & (macd.shift(1) <= sig.shift(1)) & (macd < 0)
    E["MACD cruza p/ baixo acima de zero (varejo vende)"] = (macd < sig) & (macd.shift(1) >= sig.shift(1)) & (macd > 0)
    ret3 = c / c.shift(3) - 1; sd = c.pct_change().rolling(60).std() * np.sqrt(3)
    E["pump 3 dias > 3 desvios (FOMO)"] = ret3 > 3 * sd
    E["queda 3 dias > 3 desvios (pânico)"] = ret3 < -3 * sd
    return E


def fwd(o, H):
    return o.shift(-1 - H) / o.shift(-1) - 1


def study(group):
    D = load_spot()
    V = D["V"].rolling(30, min_periods=20).mean().where(D["C"].notna().cumsum() >= 60)
    if group == "MAIORES":
        coins = ["BTC", "ETH"]
        elig = pd.DataFrame(True, D["C"].index, coins)
    else:
        rk = V.rank(axis=1, ascending=False)
        elig = (rk <= 30) & (rk > 2)  # alts: top-30 menos os 2 maiores
        coins = list(elig.columns[elig.any()])
    Fall = {H: (D["O"].shift(-1 - H) / D["O"].shift(-1) - 1) for H in HS}
    xs = {H: Fall[H].where(elig.reindex(Fall[H].index).fillna(False)).mean(axis=1) for H in HS}
    rows = []
    for s in coins:
        o, h, l, c = D["O"][s], D["H"][s], D["L"][s], D["C"][s]
        if c.notna().sum() < 300:
            continue
        E = events_for(o, h, l, c)
        F = {H: fwd(o, H) for H in HS}
        if group == "MAIORES":
            per = pd.Series(np.where(c.index < pd.Timestamp("2024-01-01", tz="UTC"), "DEV", "OOS"), c.index)
            base = {H: F[H].groupby(per).transform("mean") for H in HS}
        else:
            base = {H: xs[H].reindex(c.index) for H in HS}
        el = elig[s].reindex(c.index).fillna(False)
        for name, ev in E.items():
            ix = ev.fillna(False) & el
            for t in ix[ix].index:
                rec = {"evento": name, "moeda": s, "t": t}
                for H in HS:
                    rec[f"r{H}"] = F[H].get(t, np.nan) - COST
                    rec[f"x{H}"] = F[H].get(t, np.nan) - base[H].get(t, np.nan)
                rows.append(rec)
    X = pd.DataFrame(rows).dropna(subset=["x7"])
    X["per"] = np.where(X.t < pd.Timestamp("2024-01-01", tz="UTC"), "DEV", "OOS")
    X["wk"] = X.t.dt.to_period("W")
    X.to_parquet(ROOT / f"results/r24_events_{group}.parquet")
    out = []
    for (ev, per), g in X.groupby(["evento", "per"]):
        rec = {"evento": ev, "per": per, "n": len(g)}
        for H in HS:
            w = g.groupby("wk")[f"x{H}"].mean()
            rec[f"exc{H}d_%"] = g[f"x{H}"].mean() * 100
            rec[f"t{H}"] = w.mean() / w.std() * np.sqrt(len(w)) if len(w) > 2 and w.std() > 0 else np.nan
        rec["ret7d_liq_%"] = g.r7.mean() * 100
        out.append(rec)
    T = pd.DataFrame(out)
    W = T.pivot(index="evento", columns="per")
    W.columns = [f"{b}_{a}" for a, b in W.columns]
    cols = ["DEV_n", "OOS_n", "DEV_exc3d_%", "OOS_exc3d_%", "DEV_exc7d_%", "DEV_t7", "OOS_exc7d_%", "OOS_t7",
            "DEV_exc14d_%", "OOS_exc14d_%", "OOS_ret7d_liq_%"]
    W = W[cols].sort_values("DEV_exc7d_%")
    W.to_csv(ROOT / f"results/r24_crowd_{group}.csv")
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 100)
    print(f"\n===== {group}: excesso vs. normal da moeda (+ = comprar ganha, - = vender ganha) =====")
    print(W.round(2).to_string())


if __name__ == "__main__":
    for g in ("MAIORES", "ALTS"):
        study(g)
