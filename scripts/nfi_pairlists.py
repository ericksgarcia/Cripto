"""Listas de pares point-in-time para a NFI: top-25 spot USDT por volume médio de 30 dias no início de cada janela
de 4 meses (2022-01 → 2026-10), usando a blacklist oficial da NFI e excluindo stables/alavancados/fiat."""
import json, re, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.r11_variants import load_spot
from engine.tradfi import TRADFI

ROOT = Path(__file__).resolve().parents[1]
D = load_spot()
V = D["V"].rolling(30, min_periods=20).mean()
age = D["C"].notna().cumsum()
V = V.where(age >= 30)
bl = json.loads(re.sub(r"//.*", "", open(sys.argv[1]).read()))["exchange"]["pair_blacklist"] if len(sys.argv) > 1 else []
bl_re = [re.compile(p) for p in bl]
wins = list(pd.date_range("2022-01-01", "2026-10-01", freq="4MS", tz="UTC")) + [pd.Timestamp("2026-10-25", tz="UTC")]
out = {}
for a, b in zip(wins[:-1], wins[1:]):
    v = V.loc[a - pd.Timedelta(days=1)].dropna().sort_values(ascending=False)
    pairs = []
    for s in v.index:
        p = f"{s}/USDT"
        if any(r.fullmatch(p) for r in bl_re) or (s.endswith("B") and s[:-1] in TRADFI):
            continue
        pairs.append(p)
        if len(pairs) == 25:
            break
    out[f"{a:%Y%m%d}-{b:%Y%m%d}"] = pairs
json.dump(out, open(ROOT / "freqtrade/nfi_pairlists.json", "w"), indent=1)
u = sorted({p for v in out.values() for p in v})
print(len(out), "janelas;", len(u), "pares distintos")
for k, v in out.items():
    print(k, " ".join(x[:-5] for x in v))
