"""Baixa klines 1d de TODOS os pares spot USDT que já existiram na Binance (inclui deslistados)."""
import io, re, sys, zipfile, concurrent.futures as cf
from pathlib import Path
import pandas as pd, requests
sys.path.insert(0, str(Path(__file__).parent))
from download_binance import LIST, BASE, fetch, list_keys

OUT = Path(__file__).resolve().parents[1] / "data" / "spot_all"
(OUT / "1d").mkdir(parents=True, exist_ok=True); (OUT / "funding").mkdir(parents=True, exist_ok=True)


def list_prefixes(prefix):
    out, marker = [], ""
    while True:
        r = requests.get(LIST, params={"prefix": prefix, "delimiter": "/", "marker": marker}, timeout=60).text
        ps = re.findall(r"<Prefix>([^<]*)</Prefix>", r)[1:] if not marker else re.findall(r"<Prefix>([^<]*)</Prefix>", r)
        ps = [p for p in ps if p != prefix]
        out += ps
        if "<IsTruncated>true" not in r or not ps:
            return out
        marker = re.findall(r"<NextMarker>([^<]*)</NextMarker>", r)[0] if "<NextMarker>" in r else ps[-1]


def get(sym):
    try:
        if (OUT / "1d" / f"{sym}.parquet").exists():
            return sym, "cache"
        keys = list_keys(f"data/spot/monthly/klines/{sym}/1d/")
        if not keys:
            return sym, 0
        df = pd.concat([fetch(k) for k in keys])
        t = df.open_time.astype("int64"); t = t.where(t < 1e14, t // 1000)
        df.index = pd.to_datetime(t, unit="ms", utc=True)
        df = df.drop(columns="open_time").sort_index()
        df[~df.index.duplicated()].to_parquet(OUT / "1d" / f"{sym}.parquet")
        fk = []
        fs = []
        for k in fk:
            z = zipfile.ZipFile(io.BytesIO(requests.get(f"{BASE}/{k}", timeout=120).content))
            fs.append(pd.read_csv(z.open(z.namelist()[0])))
        if fs:
            f = pd.concat(fs)
            f.index = pd.to_datetime(f.iloc[:, 0].astype("int64"), unit="ms", utc=True)
            f.iloc[:, [-1]].set_axis(["rate"], axis=1).astype(float).sort_index().to_parquet(OUT / "funding" / f"{sym}.parquet")
        return sym, len(df)
    except Exception as e:
        return sym, repr(e)[:60]


if __name__ == "__main__":
    pre = list_prefixes("data/spot/monthly/klines/")
    syms = sorted({p.rstrip("/").split("/")[-1] for p in pre})
    syms = [s for s in syms if s.endswith("USDT") and "_" not in s]
    print("símbolos:", len(syms), flush=True)
    with cf.ThreadPoolExecutor(40) as ex:
        for s, n in ex.map(get, syms):
            print(s, n, flush=True)
