"""NostalgiaForInfinityX7: encadeia backtests anuais do freqtrade (rodados separadamente por limite de memória)
e compara/combina com as demais estratégias na mesma janela."""
import io, json, zipfile, warnings; warnings.filterwarnings("ignore")
import pandas as pd
from engine.core import ROOT
from research.r3_combine import m, combo

RES = ROOT / "freqtrade/user_data/backtest_results"
parts = {}
for f in sorted(RES.glob("*.zip")):
    z = zipfile.ZipFile(f)
    main = [x for x in z.namelist() if x.endswith(".json") and not x.endswith("_config.json")][0]
    d = json.load(z.open(main))
    s = d["strategy"].get("NostalgiaForInfinityX7")
    if not s:
        continue
    w = [x for x in z.namelist() if x.endswith("NostalgiaForInfinityX7_wallet.feather")][0]
    eq = pd.read_feather(io.BytesIO(z.read(w))).groupby("date").total_quote.sum().resample("1D").last().ffill()
    parts[s["timerange"]] = eq.pct_change().fillna(0.0)
r = pd.concat([parts[k] for k in sorted(parts)]).sort_index()
r = r[~r.index.duplicated(keep="first")]
nfi = (1 + r).cumprod()
nfi.index = nfi.index.normalize()
nfi.to_frame("PORTFOLIO").to_parquet(ROOT / "results/curves" / f"FT_NostalgiaForInfinityX7_{nfi.index[0].year}.parquet")
print("janelas:", sorted(parts), "início", nfi.index[0].date())

E = {}
for n in ["CLAUDE_Rotation5", "CLAUDE_Rotation3", "FT_MultiMa", "JS_Donchian", "OB_grid", "BuyHold"]:
    s = pd.read_parquet(ROOT / "results/curves" / f"{n}.parquet")["PORTFOLIO"].dropna()
    s.index = s.index.normalize(); E[n] = s[~s.index.duplicated(keep="last")]
E["NFI_X7"] = nfi
E = pd.DataFrame(E).ffill()
E = E[E.index >= nfi.index[0]].dropna()
E = E / E.iloc[0]
print("correlação diária com NFI:", E.pct_change().corr()["NFI_X7"].round(2).to_dict())
E["Rot5+NFI"] = combo(E, ["CLAUDE_Rotation5", "NFI_X7"])
E["Rot5+MultiMa+NFI"] = combo(E, ["CLAUDE_Rotation5", "FT_MultiMa", "NFI_X7"])
E["Rot5+MultiMa"] = combo(E, ["CLAUDE_Rotation5", "FT_MultiMa"])
per = (str(E.index[0].date()), "2026-10-25")
rows = []
for c in E:
    a = m(E[c], per)
    rows.append({"estratégia": c, "total_%": a["total_%"], "cagr_%": a["cagr_%"], "maxdd_%": a["maxdd_%"],
                 "sharpe": a["sharpe"], **{k: v for k, v in a.items() if k.startswith("y")}})
T = pd.DataFrame(rows).round(2).sort_values("sharpe", ascending=False)
T.to_csv(ROOT / "results" / "r7_nfi.csv", index=False)
pd.set_option("display.width", 250)
print(f"período {per}\n", T.to_string(index=False))
