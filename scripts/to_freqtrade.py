"""Converte parquet 1m em arquivos feather no formato do freqtrade."""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "freqtrade/user_data/data/binance"
OUT.mkdir(parents=True, exist_ok=True)
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
for sym in sys.argv[1:]:
    df = pd.read_parquet(ROOT / "data/1m" / f"{sym}.parquet")
    for tf, rule in [("5m", "5min"), ("15m", "15min"), ("30m", "30min"), ("1h", "1h"), ("4h", "4h"),
                     ("12h", "12h"), ("1d", "1D")]:
        d = df.resample(rule).agg(AGG).dropna().rename_axis("date").reset_index()
        d.to_feather(OUT / f"{sym[:-4]}_USDT-{tf}.feather")
    print(sym, flush=True)
