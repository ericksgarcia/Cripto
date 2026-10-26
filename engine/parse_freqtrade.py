"""Lê os resultados (zip) do freqtrade e gera curvas diárias + estatísticas resumidas."""
import io, json, zipfile
import pandas as pd
from engine.core import ROOT, metrics

RES = ROOT / "freqtrade/user_data/backtest_results"
OUT = ROOT / "results" / "curves"
OUT.mkdir(parents=True, exist_ok=True)

rows = []
for f in sorted(RES.glob("*.zip")):
    z = zipfile.ZipFile(f)
    main = [x for x in z.namelist() if x.endswith(".json") and not x.endswith("_config.json")][0]
    d = json.load(z.open(main))
    for name, s in d["strategy"].items():
        if not s["timerange"].endswith("20261025"):
            continue  # execuções de teste
        tag = "" if s["timerange"].startswith("20210101") else "_" + s["timerange"][:4]  # período reduzido
        w = [x for x in z.namelist() if x.endswith(f"{name}_wallet.feather")]
        if not w:
            continue
        wd = pd.read_feather(io.BytesIO(z.read(w[0])))
        eq = wd.groupby("date").total_quote.sum()
        eq = eq.resample("1D").last().ffill()
        eq = eq / s["starting_balance"]
        pd.DataFrame({"PORTFOLIO": eq}).to_parquet(OUT / f"FT_{name}{tag}.parquet")
        import engine.core as core
        core.START = s["backtest_start"][:10] if tag else "2021-01-01"
        m = metrics(eq)
        core.START = "2021-01-01"
        rows.append({"strategy": "FT_" + name + tag, "tf": s["timeframe"], "trades": s["total_trades"],
                     "winrate": s["winrate"], "profit_factor": s["profit_factor"], **m})
df = pd.DataFrame(rows).sort_values("cagr_%", ascending=False)
df.to_csv(ROOT / "results" / "freqtrade_summary.csv", index=False)
print(df.round(2).to_string(index=False))
