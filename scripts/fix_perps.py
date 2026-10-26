"""Completa os perps: rebaixa os que falharam e acrescenta outubro/2026 (arquivos diários) aos que estão ativos."""
import re, sys, concurrent.futures as cf
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from download_binance import list_keys, fetch
from download_all_perps import get, OUT

log = (OUT.parent / "perps_all_download.log").read_text().splitlines()
failed = [l.split()[0] for l in log if " " in l and not re.search(r" (cache|\d+)$", l) and l.split()[0].endswith("USDT")]
print("refazendo", len(failed), flush=True)
failed = [f for f in failed if not ((OUT / "1d" / f"{f}.parquet").exists() and (OUT / "funding" / f"{f}.parquet").exists())]
with cf.ThreadPoolExecutor(8) as ex:
    for r in ex.map(get, failed):
        print(*r, flush=True)

def add_oct(p):
    for i in range(4):
        try:
            return _add_oct(p)
        except Exception as e:
            err = e
    return p.stem, repr(err)[:60]


def _add_oct(p):
    d = pd.read_parquet(p)
    if d.index[-1] < pd.Timestamp("2026-09-29", tz="UTC"):
        return p.stem, "inativo"
    keys = [k for k in list_keys(f"data/futures/um/daily/klines/{p.stem}/1d/") if "2026-10-" in k]
    if not keys:
        return p.stem, 0
    x = pd.concat([fetch(k) for k in keys])
    t = x.open_time.astype("int64"); t = t.where(t < 1e14, t // 1000)
    x.index = pd.to_datetime(t, unit="ms", utc=True); x = x.drop(columns="open_time")
    d = pd.concat([d, x]).sort_index(); d = d[~d.index.duplicated()]
    d.to_parquet(p)
    return p.stem, len(x)

with cf.ThreadPoolExecutor(12) as ex:
    res = list(ex.map(add_oct, sorted((OUT / "1d").glob("*.parquet"))))
print("outubro adicionado:", sum(1 for _, n in res if isinstance(n, int) and n > 0))
