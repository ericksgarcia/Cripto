"""Baixa klines 1m completos da Binance (data.binance.vision) e gera parquet 1m/5m/15m/1h/4h/1d."""
import io, sys, zipfile, re, concurrent.futures as cf
from pathlib import Path
import requests, pandas as pd

BASE = "https://data.binance.vision"
LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
OUT = Path(__file__).resolve().parents[1] / "data"
COLS = ["open_time","open","high","low","close","volume","close_time","qv","trades","tbb","tbq","ign"]

def list_keys(prefix):
    keys, marker = [], ""
    while True:
        r = requests.get(LIST, params={"prefix": prefix, "delimiter": "/", "marker": marker}, timeout=60).text
        ks = re.findall(r"<Key>([^<]*\.zip)</Key>", r)
        keys += ks
        if "<IsTruncated>true" not in r or not ks: return keys
        marker = ks[-1]

def fetch(key):
    for _ in range(5):
        try:
            z = zipfile.ZipFile(io.BytesIO(requests.get(f"{BASE}/{key}", timeout=120).content))
            df = pd.read_csv(z.open(z.namelist()[0]), header=None, names=COLS)
            if not str(df.iloc[0,0]).isdigit():  # cabeçalho presente
                df = df.iloc[1:]
            return df.iloc[:, :6].astype(float)
        except Exception as e:
            err = e
    raise err

def get(sym):
    monthly = list_keys(f"data/spot/monthly/klines/{sym}/1m/")
    last = max(re.search(r"(\d{4}-\d{2})\.zip", k).group(1) for k in monthly)
    daily = [k for k in list_keys(f"data/spot/daily/klines/{sym}/1m/")
             if re.search(r"(\d{4}-\d{2})-\d{2}\.zip", k).group(1) > last]
    with cf.ThreadPoolExecutor(16) as ex:
        dfs = list(ex.map(fetch, monthly + daily))
    df = pd.concat(dfs)
    t = df.open_time.astype("int64")
    t = t.where(t < 1e14, t // 1000)  # 2025+: microssegundos
    df.index = pd.to_datetime(t, unit="ms", utc=True)
    df = df.drop(columns="open_time").sort_index()
    df = df[~df.index.duplicated()]
    for tf, rule in [("1m", None), ("5m", "5min"), ("15m", "15min"), ("1h", "1h"), ("4h", "4h"), ("1d", "1D")]:
        d = df if rule is None else df.resample(rule).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        (OUT / tf).mkdir(parents=True, exist_ok=True)
        d.to_parquet(OUT / tf / f"{sym}.parquet")
    print(sym, len(df), df.index[0], df.index[-1], flush=True)

if __name__ == "__main__":
    for s in sys.argv[1:]:
        get(s)
