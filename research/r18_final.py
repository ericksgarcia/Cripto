"""Fase 3 — carteira final honesta (sem viés de sobrevivência, escolha só com dados até 2023).

Componentes:
  ROTv2 : ensemble de 20 variações da rotação no universo spot COMPLETO (650 moedas, inclui mortas), subfamília
          robusta (top 5-10 mais líquidas, teto de vol, regime BTC>SMA100, sem stop) escolhida pelo DEV 2020-23.
  NFI25 : NostalgiaForInfinity X7, config recomendado (grinding, 6 posições), 25 pares point-in-time por janela de 4 meses.
  DIP   : compra de crash extremo (1m, z>8 em 60 min, segura 4h), 4 vagas de 20%, custo 0,15%/lado.
Combinações: pesos iguais e paridade de risco (vol de 90 dias, sem olhar o futuro), alavancagem 1-4x
(custo de financiamento ~11%/ano sobre a parte alavancada).
"""
import io, json, zipfile, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from engine.core import ROOT
from research.r16_events import gen_trades, portfolio, SYMS

pd.set_option("display.width", 250)


def nfi25():
    parts = {}
    for f in sorted((ROOT / "freqtrade/user_data/backtest_results_nfi").glob("*.zip")):
        z = zipfile.ZipFile(f)
        main = [x for x in z.namelist() if x.endswith(".json") and not x.endswith("_config.json")][0]
        s = json.load(z.open(main))["strategy"].get("NostalgiaForInfinityX7")
        if not s:
            continue
        w = [x for x in z.namelist() if x.endswith("NostalgiaForInfinityX7_wallet.feather")][0]
        eq = pd.read_feather(io.BytesIO(z.read(w))).groupby("date").total_quote.sum().resample("1D").last().ffill()
        parts[s["timerange"]] = (eq.pct_change().fillna(0.0), s["total_trades"], s["profit_total"])
    r = pd.concat([parts[k][0] for k in sorted(parts)]).sort_index()
    r = r[~r.index.duplicated(keep="first")]
    r.index = r.index.normalize()
    info = pd.DataFrame({k: {"trades": v[1], "lucro_%": v[2] * 100} for k, v in sorted(parts.items())}).T
    return r, info


if __name__ == "__main__":
    rot = pd.read_parquet(ROOT / "results/rot_v2_returns.parquet")["ROTv2"]
    nfi, info = nfi25()
    print("NFI25 por janela:\n", info.round(1).to_string())
    c, _ = portfolio(gen_trades(SYMS, "dip", 60, 8.0, 240, {}), 0.2, 4, 0.0015)
    dip = c.resample("1D").last().ffill()
    dip.index = dip.index.normalize()
    idx = pd.date_range("2022-01-01", "2026-10-24", freq="1D", tz="UTC")
    C = pd.DataFrame({"ROTv2": rot.reindex(idx).fillna(0), "NFI25": nfi.reindex(idx).fillna(0),
                      "DIP": dip.reindex(idx).ffill().pct_change().fillna(0)})
    print("\ncorrelação diária:\n", C.corr().round(2).to_string())
    base = ["ROTv2", "NFI25", "DIP"]
    C["Igual (1/3)"] = C[base].mean(axis=1)
    C["ROTv2+NFI25"] = C[["ROTv2", "NFI25"]].mean(axis=1)
    vol = C[base].rolling(90, min_periods=30).std().shift(1)
    w = (1 / vol).div((1 / vol).sum(axis=1), axis=0).fillna(1 / 3)
    C["Paridade de risco"] = (w * C[base]).sum(axis=1)
    for L in (2, 3, 4):
        C[f"ROTv2+NFI25 {L}x"] = L * C["ROTv2+NFI25"] - (L - 1) * 0.11 / 365 * 0.5
        C[f"Paridade de risco {L}x"] = L * C["Paridade de risco"] - (L - 1) * 0.11 / 365 * 0.5
    rows = []
    for col in C:
        for lab, a, b in (("2022-26", "2022-01-01", "2026-10-24"), ("2024-26 OOS", "2024-01-01", "2026-10-24")):
            x = C.loc[a:b, col]
            eq = (1 + x.clip(lower=-1)).cumprod()
            yrs = len(x) / 365.25
            cagr = eq.iloc[-1] ** (1 / yrs) - 1
            m = eq.resample("ME").last()
            mo = m.pct_change(); mo.iloc[0] = m.iloc[0] - 1
            rows.append({"carteira": col, "período": lab, "CAGR %": cagr * 100, "mês médio %": ((1 + cagr) ** (1 / 12) - 1) * 100,
                         "mediana mês %": mo.median() * 100, "pior mês %": mo.min() * 100, "meses ≥10%": int((mo >= .1).sum()),
                         "meses <0": int((mo < 0).sum()), "meses": len(mo), "MaxDD %": (eq / eq.cummax() - 1).min() * 100,
                         "Sharpe": x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0})
    out = pd.DataFrame(rows).round(1)
    out.to_csv(ROOT / "results/r18_final.csv", index=False)
    C.to_parquet(ROOT / "results/r18_components.parquet")
    print(out.to_string(index=False))
    yr = (1 + C).groupby(C.index.year).prod() - 1
    print("\nretorno por ano (%):\n", (yr * 100).round(1)[[*base, "ROTv2+NFI25", "Paridade de risco", "Paridade de risco 3x"]].to_string())
