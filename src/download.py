"""Baixa klines mensais de data.binance.vision e consolida em parquet."""
import io, sys, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
import requests

BASE = "https://data.binance.vision/data"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
OUT = Path(__file__).resolve().parent.parent / "data" / "processed"


def months(start="2020-01", end="2026-09"):
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def fetch(url):
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        return z.read(z.namelist()[0])


def klines(symbol, interval, start, end):
    urls = [f"{BASE}/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{m}.zip"
            for m in months(start, end)]
    with ThreadPoolExecutor(8) as ex:
        blobs = list(ex.map(fetch, urls))
    frames = [pd.read_csv(io.BytesIO(b), header=None, names=COLS) for b in blobs if b]
    df = pd.concat(frames, ignore_index=True)
    ts = df["open_time"]
    unit = "us" if ts.iloc[-1] > 1e14 else "ms"  # 2025+ files use microseconds
    df["open_time"] = pd.to_datetime(ts.where(ts < 1e14, ts // 1000), unit="ms")
    df = df.drop(columns=["close_time", "ignore"]).drop_duplicates("open_time")
    return df.set_index("open_time").sort_index().astype("float64")


def funding(symbol, start, end):
    urls = [f"{BASE}/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{m}.zip"
            for m in months(start, end)]
    with ThreadPoolExecutor(8) as ex:
        blobs = list(ex.map(fetch, urls))
    frames = [pd.read_csv(io.BytesIO(b)) for b in blobs if b]
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["calc_time"], unit="ms")
    return df.set_index("time")["last_funding_rate"].sort_index()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = sys.argv[1:] or ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    for s in symbols:
        df = klines(s, "1h", "2020-01", "2026-09")
        df.to_parquet(OUT / f"{s}_1h.parquet")
        print(s, "klines", df.shape, df.index[0], "->", df.index[-1], flush=True)
        f = funding(s, "2020-01", "2026-09")
        if f is not None:
            f.to_frame().to_parquet(OUT / f"{s}_funding.parquet")
            print(s, "funding", len(f), flush=True)
