"""Baixa klines 1h de futuros perpétuos USDT-M e histórico de funding (data.binance.vision)."""
import sys, re, io, zipfile, concurrent.futures as cf
from pathlib import Path
import pandas as pd, requests
sys.path.insert(0, str(Path(__file__).parent))
from download_binance import list_keys, fetch, BASE

OUT = Path(__file__).resolve().parents[1] / "data" / "futures"
(OUT / "1h").mkdir(parents=True, exist_ok=True); (OUT / "funding").mkdir(parents=True, exist_ok=True)

def funding(sym):
    keys = list_keys(f"data/futures/um/monthly/fundingRate/{sym}USDT/")
    dfs = []
    for k in keys:
        z = zipfile.ZipFile(io.BytesIO(requests.get(f"{BASE}/{k}", timeout=120).content))
        d = pd.read_csv(z.open(z.namelist()[0]))
        dfs.append(d)
    if not dfs:
        return 0
    d = pd.concat(dfs)
    d.index = pd.to_datetime(d.iloc[:, 0].astype("int64"), unit="ms", utc=True)
    d = d.iloc[:, [-1]].rename(columns={d.columns[-1]: "rate"}).astype(float).sort_index()
    d.to_parquet(OUT / "funding" / f"{sym}.parquet")
    return len(d)

def get(sym):
    try:
        keys = list_keys(f"data/futures/um/monthly/klines/{sym}USDT/1h/")
        if not keys:
            return sym, 0, 0
        df = pd.concat([fetch(k) for k in keys])
        t = df.open_time.astype("int64"); t = t.where(t < 1e14, t // 1000)
        df.index = pd.to_datetime(t, unit="ms", utc=True)
        df = df.drop(columns="open_time").sort_index()
        df = df[~df.index.duplicated()]
        df.to_parquet(OUT / "1h" / f"{sym}.parquet")
        return sym, len(df), funding(sym)
    except Exception as e:
        return sym, repr(e)[:80], 0

if __name__ == "__main__":
    syms = sys.argv[1:] or sorted(p.stem for p in (OUT.parents[0] / "universe_1h").glob("*.parquet"))
    with cf.ThreadPoolExecutor(8) as ex:
        for r in ex.map(get, syms):
            print(*r, flush=True)
