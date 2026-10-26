"""Baixa klines 1h (spot) de um universo amplo, incluindo moedas deslistadas/colapsadas (anti viés de sobrevivência)."""
import sys, re, concurrent.futures as cf
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from download_binance import list_keys, fetch

OUT = Path(__file__).resolve().parents[1] / "data" / "universe_1h"
OUT.mkdir(parents=True, exist_ok=True)
UNIV = sys.argv[1:] or ["BTC","ETH","BNB","SOL","XRP","ADA","DOGE","LTC","LINK","AVAX","BCH","EOS","TRX","ETC","XLM","XMR","DASH","ZEC",
        "NEO","IOTA","ONT","QTUM","VET","ICX","WAVES","ATOM","ALGO","MATIC","DOT","UNI","FIL","AAVE","SUSHI","LUNA","FTT",
        "SRM","ICP","AXS","SAND","MANA","NEAR","FTM","CHZ","GALA","APE","OP","ARB","APT","SUI","PEPE","SHIB","TON","INJ",
        "RUNE","EGLD","THETA","HBAR","CRV","SNX","MKR","COMP","YFI","1INCH","KSM","ZIL","BAT","ENJ","CELO","KAVA","GRT"]

def get(sym):
    try:
        keys = list_keys(f"data/spot/monthly/klines/{sym}USDT/1h/")
        if not keys:
            return sym, 0
        last = max(re.search(r"(\d{4}-\d{2})\.zip", k).group(1) for k in keys)
        daily = [k for k in list_keys(f"data/spot/daily/klines/{sym}USDT/1h/")
                 if re.search(r"(\d{4}-\d{2})-\d{2}\.zip", k).group(1) > last]
        dfs = [fetch(k) for k in keys + daily]
        df = pd.concat(dfs)
        t = df.open_time.astype("int64"); t = t.where(t < 1e14, t // 1000)
        df.index = pd.to_datetime(t, unit="ms", utc=True)
        df = df.drop(columns="open_time").sort_index()
        df = df[~df.index.duplicated()]
        df.to_parquet(OUT / f"{sym}.parquet")
        return sym, len(df)
    except Exception as e:
        return sym, repr(e)

with cf.ThreadPoolExecutor(8) as ex:
    for s, n in ex.map(get, UNIV):
        print(s, n, flush=True)
