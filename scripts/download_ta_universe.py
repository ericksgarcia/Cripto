"""Baixa klines spot 1h das moedas que estiveram no top-30 por volume (point-in-time, mensal) em algum momento de
2018-2026 — universo para os estudos de análise técnica (sem viés de sobrevivência)."""
import re, sys, concurrent.futures as cf
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from download_binance import list_keys, fetch
from research.r11_variants import load_spot

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/ta_1h"; OUT.mkdir(parents=True, exist_ok=True)


def get(base):
    sym = base + "USDT"
    if (OUT / f"{base}.parquet").exists():
        return base, "cache"
    for _ in range(4):
        try:
            keys = list_keys(f"data/spot/monthly/klines/{sym}/1h/")
            last = max(re.search(r"(\d{4}-\d{2})\.zip", k).group(1) for k in keys)
            daily = [k for k in list_keys(f"data/spot/daily/klines/{sym}/1h/") if re.search(r"(\d{4}-\d{2})-\d{2}\.zip", k).group(1) > last]
            df = pd.concat([fetch(k) for k in keys + daily])
            t = df.open_time.astype("int64"); t = t.where(t < 1e14, t // 1000)
            df.index = pd.to_datetime(t, unit="ms", utc=True)
            df = df.drop(columns="open_time").sort_index(); df = df[~df.index.duplicated()]
            df[df.index < pd.Timestamp("2026-10-25", tz="UTC")].to_parquet(OUT / f"{base}.parquet")
            return base, len(df)
        except Exception as e:
            err = e
    return base, repr(err)[:60]


if __name__ == "__main__":
    D = load_spot()
    V = D["V"].rolling(30, min_periods=20).mean().where(D["C"].notna().cumsum() >= 30)
    ms = V.resample("MS").first().loc["2018-01-01":]
    top = set()
    for _, row in ms.iterrows():
        top |= set(row.dropna().nlargest(30).index)
    top = sorted(top)
    print("moedas:", len(top), flush=True)
    with cf.ThreadPoolExecutor(32) as ex:
        for r in ex.map(get, top):
            print(*r, flush=True)
