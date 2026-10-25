"""Futuros trimestrais USDT-M (BTC, ETH) – klines diários por contrato + klines 1h perp (BTC, ETH, SOL) p/ risco intradiário."""
import io, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
from download import BASE, COLS
from download2 import get, ts, kl

OUT = Path(__file__).resolve().parent.parent / "data" / "processed3"; OUT.mkdir(parents=True, exist_ok=True)

def last_friday(y, m):
    d = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
    while d.weekday() != 4: d -= pd.Timedelta(days=1)
    return d

def contract(base, exp):
    sym = f"{base}USDT_{exp.strftime('%y%m%d')}"
    ms = pd.period_range(exp.to_period("M") - 8, exp.to_period("M"), freq="M")
    urls = [f"{BASE}/futures/um/monthly/klines/{sym}/1d/{sym}-1d-{m}.zip" for m in ms]
    with ThreadPoolExecutor(8) as ex: blobs = list(ex.map(get, urls))
    fr = []
    for b in blobs:
        if b:
            d = pd.read_csv(io.BytesIO(b), header=None, names=COLS)
            fr.append(d[pd.to_numeric(d.open_time, errors="coerce").notna()])
    if not fr: return None
    d = pd.concat(fr); d["open_time"] = ts(d["open_time"])
    return d.drop_duplicates("open_time").set_index("open_time").sort_index()[["open", "high", "low", "close", "volume"]].astype(float)

if __name__ == "__main__":
    rows = []
    for base in ("BTC", "ETH"):
        for y in range(2021, 2027):
            for m in (3, 6, 9, 12):
                exp = last_friday(y, m)
                d = contract(base, exp)
                if d is None: print(base, exp.date(), "sem dados"); continue
                d.to_parquet(OUT / f"{base}_{exp.strftime('%y%m%d')}.parquet")
                rows.append((base, exp.date(), len(d), d.index[0].date(), d.index[-1].date()))
    print(pd.DataFrame(rows, columns=["base", "expiry", "n", "first", "last"]).to_string())
    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):   # perp 1h (para basis intradiário vs spot 1h)
        d = kl("futures/um", s, "1h"); d.to_parquet(OUT / f"{s}_perp_1h.parquet"); print(s, "perp 1h", d.shape)
