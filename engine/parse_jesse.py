"""Agrega os resultados do Jesse (por par) em curvas de carteira e estatísticas."""
import json
import pandas as pd
from engine.core import ROOT, SYMS, portfolio, metrics

RES = ROOT / "jesse_bt" / "results"
OUT = ROOT / "results" / "curves"
rows = []
strats = sorted({p.stem.rsplit("_", 1)[0] for p in RES.glob("*.json")})
for st in strats:
    curves, ntr, err = {}, 0, None
    for s in SYMS:
        d = json.load(open(RES / f"{st}_{s}.json"))
        if "error" in d:
            err = d["error"][:80]; continue
        if not d.get("equity_curve"):  # nenhuma operação no período -> curva plana
            curves[s] = pd.Series(1.0, pd.date_range("2021-01-01", "2026-10-25", freq="1D", tz="UTC")); continue
        ec = [x for x in d["equity_curve"] if x["name"] == "Portfolio"][0]["data"]
        eq = pd.Series([x["value"] for x in ec], pd.to_datetime([x["time"] for x in ec], unit="s", utc=True))
        curves[s] = (eq / eq.iloc[0]).resample("1D").last().ffill()
        ntr += int(float(d["metrics"].get("total", 0)))
    if not curves:
        print(st, "ERRO", err); continue
    df = pd.DataFrame(curves).resample("1D").last()
    df["PORTFOLIO"] = portfolio(curves)
    df.to_parquet(OUT / f"JS_{st}.parquet")
    rows.append({"strategy": "JS_" + st, "trades": ntr, "pares_ok": len(curves), **metrics(df.PORTFOLIO)})
out = pd.DataFrame(rows).sort_values("cagr_%", ascending=False)
out.to_csv(ROOT / "results" / "jesse_summary.csv", index=False)
print(out.round(2).to_string(index=False))
