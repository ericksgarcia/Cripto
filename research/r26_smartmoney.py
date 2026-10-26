"""Fase 5 — estratégia "contra-ataque": seguir os top traders contra o varejo (métricas de posicionamento Binance).

Sinal diário por moeda (dados até o fechamento de t): smart_div = z(L/S de posições dos top traders) - z(L/S de contas
de todos os usuários), z-score em 90 dias. Compra as moedas com smart_div > thr (ou as top-k), segura `hold` dias
(sai antes se o sinal virar < 0). Opcional: vende (1x, sem alavancagem) as moedas com varejo eufórico.
Execução em perpétuos 1x com funding real e custo 0,07% por lado. DEV = até 2023-12, OOS = 2024-01 em diante.
"""
import warnings; warnings.filterwarnings("ignore")
import itertools
import numpy as np, pandas as pd
from engine.core import ROOT
from research.r11_variants import sim_np, stats
from research.r25_positioning import daily_feats

COST = 0.0007
syms = sorted(p.stem for p in (ROOT / "data/metrics_1h").glob("*.parquet"))
F = {s: daily_feats(s) for s in syms}
idx = pd.date_range("2020-10-01", "2026-10-24", freq="1D", tz="UTC")
get = lambda col: pd.DataFrame({s: F[s][col] for s in syms}).reindex(idx)
DIV, ZR, R3 = get("smart_div"), get("z_retail"), get("ret3")
O, H, L, C, FU = {}, {}, {}, {}, {}
for s in syms:
    px = pd.read_parquet(ROOT / "data/perps_all/1d" / f"{s}USDT.parquet")
    O[s], H[s], L[s], C[s] = px.open, px.high, px.low, px.close
    fp = ROOT / "data/perps_all/funding" / f"{s}USDT.parquet"
    FU[s] = pd.read_parquet(fp)["rate"].resample("1D").sum() if fp.exists() else pd.Series(dtype=float)
O, H, L, C = (pd.DataFrame(x).reindex(idx) for x in (O, H, L, C))
FU = pd.DataFrame(FU).reindex(idx).fillna(0.0)
btc = C["BTC"]; bull = (btc > btc.rolling(100).mean()).astype(float)
mom7 = C / C.shift(7) - 1


def run(W):
    r = pd.Series(sim_np(O.values.astype(float), W.values.astype(float), FU.values.astype(float), COST,
                         H.values.astype(float), L.values.astype(float), C.values.astype(float), 0.0), idx)
    return r


rows, curves = [], {}
alts = [s for s in syms if s not in ("BTC", "ETH")]
for univ, thr, hold, mode, regime in itertools.product(("alts", "todas"), (1.5, 2.0, 2.5), (3, 7, 14),
                                                      ("long", "long+short_varejo"), (False, True)):
    cols = alts if univ == "alts" else syms
    sig = (DIV[cols] > thr)
    held = sig.rolling(hold, min_periods=1).max().astype(bool) & (DIV[cols] > 0)
    n = held.sum(axis=1).clip(lower=1)
    W = held.astype(float).div(np.maximum(n, 5), axis=0)  # no máx. 20% por moeda; sobra fica em caixa
    if regime:
        W = W.mul(bull, axis=0)
    if mode == "long+short_varejo":
        sh = (ZR[cols] > 2) & (DIV[cols] < 0)
        shh = sh.rolling(hold, min_periods=1).max().astype(bool)
        m = shh.sum(axis=1).clip(lower=1)
        W = W * 0.5 - 0.5 * shh.astype(float).div(np.maximum(m, 5), axis=0)
    W = W.reindex(columns=syms).fillna(0.0)
    r = run(W)
    name = f"{univ}|div>{thr}|hold{hold}|{mode}|regime{regime}"
    d, o, a = stats(r, "2021-01-01", "2023-12-31"), stats(r, "2024-01-01", "2026-10-24"), stats(r, "2021-01-01", "2026-10-24")
    rows.append({"config": name, "DEV_cagr": d[0] * 100, "DEV_sharpe": d[1], "DEV_dd": d[2] * 100,
                 "OOS_cagr": o[0] * 100, "OOS_sharpe": o[1], "OOS_dd": o[2] * 100, "exposicao_media": W.abs().sum(axis=1).mean()})
    curves[name] = r
# controle: momentum de 7 dias (top-k) nas mesmas moedas — para ver se o sinal é só momentum disfarçado
for k in (3, 5):
    rk = mom7[alts].rank(axis=1, ascending=False)
    W = ((rk <= k) & (mom7[alts] > 0)).astype(float) / k
    r = run(W.reindex(columns=syms).fillna(0))
    d, o = stats(r, "2021-01-01", "2023-12-31"), stats(r, "2024-01-01", "2026-10-24")
    rows.append({"config": f"CONTROLE momentum7d top{k}", "DEV_cagr": d[0] * 100, "DEV_sharpe": d[1], "DEV_dd": d[2] * 100,
                 "OOS_cagr": o[0] * 100, "OOS_sharpe": o[1], "OOS_dd": o[2] * 100})
ew = run(pd.DataFrame(1.0 / len(alts), idx, alts).where(C[alts].notna(), 0).reindex(columns=syms).fillna(0))
d, o = stats(ew, "2021-01-01", "2023-12-31"), stats(ew, "2024-01-01", "2026-10-24")
rows.append({"config": "CONTROLE comprar todas as alts", "DEV_cagr": d[0] * 100, "DEV_sharpe": d[1], "DEV_dd": d[2] * 100,
             "OOS_cagr": o[0] * 100, "OOS_sharpe": o[1], "OOS_dd": o[2] * 100})
T = pd.DataFrame(rows).round(2)
T.to_csv(ROOT / "results/r26_smartmoney.csv", index=False)
pd.DataFrame(curves).astype("float32").to_parquet(ROOT / "results/r26_returns.parquet")
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
print(T.sort_values("DEV_sharpe", ascending=False).head(20).to_string(index=False))
print(T[T.config.str.startswith("CONTROLE")].to_string(index=False))
print("\nmedianas por dimensão:")
for i, dim in enumerate(["univ", "thr", "hold", "mode", "regime"]):
    k = T[~T.config.str.startswith("CONTROLE")].config.str.split("|").str[i]
    print(dim, T[~T.config.str.startswith("CONTROLE")].groupby(k)[["DEV_cagr", "DEV_sharpe", "OOS_cagr", "OOS_sharpe", "OOS_dd"]].median().round(2).to_dict("index"))
