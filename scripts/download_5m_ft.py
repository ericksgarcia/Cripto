"""Baixa klines spot 5m (data.binance.vision) dos pares das listas da NFI e grava no formato feather do freqtrade
(5m, 15m, 1h, 4h; 1d vem do histórico diário completo em data/spot_all)."""
import json, re, sys, concurrent.futures as cf
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from download_binance import list_keys, fetch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "freqtrade/user_data/data_nfi/binance"
OUT.mkdir(parents=True, exist_ok=True)
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def get(pair):
    base = pair.split("/")[0]; sym = base + "USDT"
    if (OUT / f"{base}_USDT-4h.feather").exists():
        return pair, "cache"
    for _ in range(4):
        try:
            keys = [k for k in list_keys(f"data/spot/monthly/klines/{sym}/5m/") if re.search(r"(\d{4}-\d{2})\.zip", k).group(1) >= "2021-07"]
            last = max(re.search(r"(\d{4}-\d{2})\.zip", k).group(1) for k in keys) if keys else "2021-06"
            daily = [k for k in list_keys(f"data/spot/daily/klines/{sym}/5m/") if re.search(r"(\d{4}-\d{2})-\d{2}\.zip", k).group(1) > last]
            df = pd.concat([fetch(k) for k in keys + daily])
            t = df.open_time.astype("int64"); t = t.where(t < 1e14, t // 1000)
            df.index = pd.to_datetime(t, unit="ms", utc=True)
            df = df.drop(columns="open_time").sort_index(); df = df[~df.index.duplicated()]
            df = df[df.index < pd.Timestamp("2026-10-25", tz="UTC")]
            for tf, rule in (("5m", None), ("15m", "15min"), ("1h", "1h"), ("4h", "4h")):
                d = df if rule is None else df.resample(rule).agg(AGG).dropna()
                d.rename_axis("date").reset_index().to_feather(OUT / f"{base}_USDT-{tf}.feather")
            d1 = pd.read_parquet(ROOT / "data/spot_all/1d" / f"{sym}.parquet")
            d1 = d1[d1.index < pd.Timestamp("2026-10-25", tz="UTC")]
            d1.rename_axis("date").reset_index()[["date", "open", "high", "low", "close", "volume"]].to_feather(OUT / f"{base}_USDT-1d.feather")
            return pair, len(df)
        except Exception as e:
            err = e
    return pair, repr(err)[:70]


if __name__ == "__main__":
    pl = json.load(open(ROOT / "freqtrade/nfi_pairlists.json"))
    pairs = sorted({p for v in pl.values() for p in v} | {"BTC/USDT"})
    with cf.ThreadPoolExecutor(16) as ex:
        for r in ex.map(get, pairs):
            print(*r, flush=True)
