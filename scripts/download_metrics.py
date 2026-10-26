"""Baixa métricas de posicionamento dos perpétuos (data.binance.vision, futures/um/daily/metrics): open interest,
long/short de contas (varejo) e de top traders, razão de volume agressor. Agrega para 1h."""
import io, sys, time, zipfile, concurrent.futures as cf
from pathlib import Path
import pandas as pd, requests
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from download_binance import list_keys, BASE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/metrics_1h"; OUT.mkdir(parents=True, exist_ok=True)
S = requests.Session()


def one(key):
    for _ in range(5):
        try:
            z = zipfile.ZipFile(io.BytesIO(S.get(f"{BASE}/{key}", timeout=60).content))
            return pd.read_csv(z.open(z.namelist()[0]))
        except Exception:
            time.sleep(1)
    return None


def get(sym):
    if (OUT / f"{sym}.parquet").exists():
        return sym, "cache"
    for _ in range(5):
        try:
            keys = list_keys(f"data/futures/um/daily/metrics/{sym}USDT/"); break
        except Exception:
            time.sleep(2)
    with cf.ThreadPoolExecutor(24) as ex:
        dfs = [d for d in ex.map(one, keys) if d is not None and len(d)]
    if not dfs:
        return sym, 0
    d = pd.concat(dfs)
    d.index = pd.to_datetime(d.create_time, utc=True)
    d = d.drop(columns=["create_time", "symbol"]).apply(pd.to_numeric, errors="coerce").sort_index()
    d = d[~d.index.duplicated()].resample("1h").last()
    d.to_parquet(OUT / f"{sym}.parquet")
    return sym, f"{len(keys)} dias"


if __name__ == "__main__":
    from research.r11_variants import load_perps
    D = load_perps()
    V = D["V"].rolling(30, min_periods=10).mean()
    cnt = {}
    for _, row in V.resample("MS").first().loc["2020-09-01":].iterrows():
        for s in row.dropna().nlargest(12).index:
            cnt[s] = cnt.get(s, 0) + 1
    syms = [s for s, _ in sorted(cnt.items(), key=lambda x: -x[1])][:32]
    print("moedas:", syms, flush=True)
    for s in syms:
        print(*get(s), flush=True)
