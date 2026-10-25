"""Base ampliada: klines diários spot + perp (USDT-M) e funding, ~20 pares, desde 2019-09."""
import io, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd, requests
from download import COLS, BASE, months

OUT = Path(__file__).resolve().parent.parent / "data" / "processed2"
UNIVERSE = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "SOL", "TRX", "LINK", "DOT", "LTC", "AVAX", "BCH",
            "ETC", "ATOM", "XLM", "UNI", "FIL", "NEAR", "AAVE", "EOS", "XMR", "ALGO", "VET", "MATIC"]
START, END = "2019-09", "2026-09"


def get(url):
    for _ in range(3):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404: return None
            if r.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(r.content)) as z: return z.read(z.namelist()[0])
        except requests.RequestException: pass
    return None


def ts(s):  # ms ou us
    s = pd.to_numeric(s)
    return pd.to_datetime(s.where(s < 1e14, s // 1000), unit="ms")


def kl(kind, sym, itv):
    urls = [f"{BASE}/{kind}/monthly/klines/{sym}/{itv}/{sym}-{itv}-{m}.zip" for m in months(START, END)]
    with ThreadPoolExecutor(12) as ex: blobs = list(ex.map(get, urls))
    fr = []
    for b in blobs:
        if not b: continue
        d = pd.read_csv(io.BytesIO(b), header=None, names=COLS)
        d = d[pd.to_numeric(d.open_time, errors="coerce").notna()]  # alguns arquivos têm cabeçalho
        fr.append(d)
    if not fr: return None
    d = pd.concat(fr); d["open_time"] = ts(d["open_time"])
    d = d.drop(columns=["close_time", "ignore"]).drop_duplicates("open_time").set_index("open_time").sort_index()
    return d.astype("float64")


def fund(sym):
    urls = [f"{BASE}/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip" for m in months(START, END)]
    with ThreadPoolExecutor(12) as ex: blobs = list(ex.map(get, urls))
    fr = [pd.read_csv(io.BytesIO(b)) for b in blobs if b]
    if not fr: return None
    d = pd.concat(fr); d["time"] = pd.to_datetime(d["calc_time"], unit="ms")
    return d.set_index("time")["last_funding_rate"].sort_index()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for u in UNIVERSE:
        s = u + "USDT"
        sp, pf, fu = kl("spot", s, "1d"), kl("futures/um", s, "1d"), fund(s)
        if sp is not None: sp.to_parquet(OUT / f"{s}_spot_1d.parquet")
        if pf is not None: pf.to_parquet(OUT / f"{s}_perp_1d.parquet")
        if fu is not None: fu.to_frame().to_parquet(OUT / f"{s}_funding.parquet")
        f = lambda d: (len(d), str(d.index[0].date())) if d is not None else None
        print(s, "spot", f(sp), "perp", f(pf), "fund", f(fu), flush=True)
