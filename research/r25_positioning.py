"""Fase 5 — posicionamento da multidão (métricas de futuros da Binance) como sinal contrário (ou não).

Features diárias (só dados até o fechamento de t), z-score em janela móvel de 90 dias:
  retail   = long/short de CONTAS (todos os usuários)          -> "varejo"
  top_pos  = long/short de POSIÇÕES dos top traders            -> "dinheiro grande"
  smart_div= z(top_pos) - z(retail)                             -> grandes mais comprados que o varejo
  oi_chg   = variação de 3 dias do open interest (US$)
  taker    = razão volume comprador/vendedor agressor (média do dia)
  funding  = soma diária do funding
Mede o retorno a frente (1, 3, 7 dias) de BTC/ETH (série temporal) e o IC cross-sectional nas alts.
DEV = até 2023-12, OOS = 2024-01 em diante.
"""
import warnings; warnings.filterwarnings("ignore")
import sys
import numpy as np, pandas as pd
from engine.core import ROOT

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
COST = 0.0024


def daily_feats(sym):
    m = pd.read_parquet(ROOT / "data/metrics_1h" / f"{sym}.parquet")
    d = pd.DataFrame({
        "retail": m.count_long_short_ratio.resample("1D").mean(),
        "top_pos": m.sum_toptrader_long_short_ratio.resample("1D").mean(),
        "top_acc": m.count_toptrader_long_short_ratio.resample("1D").mean(),
        "oi": m.sum_open_interest_value.resample("1D").last(),
        "taker": m.sum_taker_long_short_vol_ratio.resample("1D").mean(),
    })
    fp = ROOT / "data/perps_all/funding" / f"{sym}USDT.parquet"
    if fp.exists():
        d["funding"] = pd.read_parquet(fp)["rate"].resample("1D").sum().reindex(d.index)
    px = pd.read_parquet(ROOT / "data/perps_all/1d" / f"{sym}USDT.parquet")
    d["open"] = px.open.reindex(d.index); d["close"] = px.close.reindex(d.index)
    z = lambda x: (x - x.rolling(90, min_periods=30).mean()) / x.rolling(90, min_periods=30).std()
    F = pd.DataFrame(index=d.index)
    F["z_retail"] = z(d.retail); F["z_top_pos"] = z(d.top_pos); F["z_top_acc"] = z(d.top_acc)
    F["smart_div"] = F.z_top_pos - F.z_retail
    F["oi_chg3"] = d.oi.pct_change(3); F["z_oi_chg3"] = z(F.oi_chg3)
    F["ret3"] = d.close.pct_change(3)
    F["z_taker"] = z(d.taker)
    if "funding" in d:
        F["z_funding"] = z(d.funding)
    for H in (1, 3, 7):
        F[f"f{H}"] = d.open.shift(-1 - H) / d.open.shift(-1) - 1
    F["sym"] = sym
    return F


def ts_study(syms):
    rows = []
    for sym in syms:
        F = daily_feats(sym)
        F["per"] = np.where(F.index < pd.Timestamp("2024-01-01", tz="UTC"), "DEV", "OOS")
        base = {H: F.groupby("per")[f"f{H}"].transform("mean") for H in (1, 3, 7)}
        conds = {
            "varejo MUITO comprado (z>2)": F.z_retail > 2, "varejo MUITO vendido (z<-2)": F.z_retail < -2,
            "top traders MUITO comprados (z>2)": F.z_top_pos > 2, "top traders MUITO vendidos (z<-2)": F.z_top_pos < -2,
            "grandes comprados x varejo vendido (div>2)": F.smart_div > 2,
            "grandes vendidos x varejo comprado (div<-2)": F.smart_div < -2,
            "OI sobe forte + preço sobe (alavancados entram)": (F.z_oi_chg3 > 1.5) & (F.ret3 > 0),
            "OI sobe forte + preço cai (vendidos entram)": (F.z_oi_chg3 > 1.5) & (F.ret3 < 0),
            "OI cai forte + preço cai (liquidação de longs)": (F.z_oi_chg3 < -1.5) & (F.ret3 < 0),
            "OI cai forte + preço sobe (short squeeze)": (F.z_oi_chg3 < -1.5) & (F.ret3 > 0),
            "compra agressiva extrema (taker z>2)": F.z_taker > 2, "venda agressiva extrema (taker z<-2)": F.z_taker < -2,
        }
        if "z_funding" in F:
            conds["funding extremo positivo (z>2)"] = F.z_funding > 2
            conds["funding extremo negativo (z<-2)"] = F.z_funding < -2
        for name, cnd in conds.items():
            for t in F.index[cnd.fillna(False)]:
                rows.append({"evento": name, "sym": sym, "t": t, "per": F.per[t],
                             **{f"x{H}": F[f"f{H}"][t] - base[H][t] for H in (1, 3, 7)}})
    X = pd.DataFrame(rows).dropna(subset=["x3"])
    T = X.groupby(["evento", "per"]).agg(n=("x3", "size"), x1=("x1", "mean"), x3=("x3", "mean"), x7=("x7", "mean")).unstack()
    T.columns = [f"{b}_{a}" for a, b in T.columns]
    for c in T.columns:
        if c.startswith(("DEV_x", "OOS_x")):
            T[c] *= 100
    return T[["DEV_n", "OOS_n", "DEV_x1", "OOS_x1", "DEV_x3", "OOS_x3", "DEV_x7", "OOS_x7"]].sort_values("DEV_x3")


def xs_study(syms):
    """Cross-section nas alts: correlação de rank (IC) diária entre cada feature e o retorno a frente."""
    P = pd.concat([daily_feats(s) for s in syms])
    P = P.reset_index().rename(columns={"index": "t", "create_time": "t"})
    P = P.rename(columns={P.columns[0]: "t"})
    out = []
    for f in ["z_retail", "z_top_pos", "smart_div", "z_oi_chg3", "z_taker", "z_funding", "ret3"]:
        for H in (1, 3, 7):
            ic = P.groupby("t").apply(lambda g: g[f].corr(g[f"f{H}"], method="spearman") if g[f].notna().sum() > 5 else np.nan).dropna()
            for per, a, b in (("DEV", None, "2023-12-31"), ("OOS", "2024-01-01", None)):
                x = ic.loc[a:b]
                out.append({"feature": f, "H": H, "per": per, "IC_medio": x.mean(), "t": x.mean() / x.std() * np.sqrt(len(x) / H)})
    T = pd.DataFrame(out).pivot_table(index=["feature", "H"], columns="per", values=["IC_medio", "t"])
    return T


if __name__ == "__main__":
    avail = sorted(p.stem for p in (ROOT / "data/metrics_1h").glob("*.parquet"))
    print("moedas com métricas:", avail)
    print("\n=== BTC + ETH: excesso de retorno a frente (%) após cada condição de posicionamento ===")
    print(ts_study([s for s in ("BTC", "ETH") if s in avail]).round(2).to_string())
    alts = [s for s in avail if s not in ("BTC", "ETH")]
    if len(alts) >= 8:
        print("\n=== ALTS: excesso (%) por condição ===")
        print(ts_study(alts).round(2).to_string())
        print("\n=== ALTS cross-section: IC de rank (feature vs retorno a frente) ===")
        print(xs_study(alts).round(3).to_string())
