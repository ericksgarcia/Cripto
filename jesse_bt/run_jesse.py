"""Roda as estratégias de exemplo oficiais do Jesse (jesse-ai/example-strategies) via jesse.research.backtest."""
import json, os, sys, time, traceback
from pathlib import Path
import numpy as np, pandas as pd
from multiprocessing import Pool

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))
DATA = HERE.parent / "data/1m"
START, END = "2021-01-01", "2026-10-25"
SYMS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "LTC", "LINK", "AVAX"]
TF = {"KDJstrategy": "1D", "MACD_EMA": "1h", "SimpleBollinger": "1h"}
LEV = {"TurtleRules": 3}  # sizing por risco (1%/ATR) com pirâmide de 4 unidades exige margem > 1x
EXTRA = {"DUAL_THRUST": ["1D"]}  # data routes adicionais exigidas pela estratégia
STRATS = ["DUAL_THRUST", "Donchian", "IFR2", "KDJstrategy", "MACD_EMA", "MAGen", "RSI2",
          "SMACrossover", "SimpleBollinger", "TradingView_RSI", "TurtleRules"]
WARM = 240  # candles de aquecimento no timeframe da estratégia

def candles(sym):
    arr = np.load(HERE.parent / "data/npy" / f"{sym}.npy")
    end_ts = pd.Timestamp(END, tz="UTC").value // 10**6
    return None, arr[arr[:, 0] < end_ts]

def run(args):
    strat, sym = args
    import jesse.helpers as jh; jh.is_jesse_project = lambda: False
    from jesse import research
    try:
        df, arr = candles(sym)
        tf = TF.get(strat, "4h")
        mins = {"1h": 60, "4h": 240, "1D": 1440}[tf]
        start_ts = pd.Timestamp(START, tz="UTC").value // 10**6
        i0 = max(np.searchsorted(arr[:, 0], start_ts), WARM * mins)
        i0 -= i0 % mins
        cfg = {"starting_balance": 10_000, "fee": 0.001, "type": "futures", "futures_leverage": LEV.get(strat, 1),
               "futures_leverage_mode": "cross", "exchange": "Binance Perpetual Futures",
               "warm_up_candles": WARM}
        key = f"Binance Perpetual Futures-{sym}-USDT"
        t = time.time()
        r = research.backtest(cfg, [{"exchange": cfg["exchange"], "strategy": strat, "symbol": f"{sym}-USDT", "timeframe": tf}],
                              [{"exchange": cfg["exchange"], "symbol": f"{sym}-USDT", "timeframe": x} for x in EXTRA.get(strat, [])],
                              {key: {"exchange": cfg["exchange"], "symbol": f"{sym}-USDT", "candles": arr[i0:]}},
                              {key: {"exchange": cfg["exchange"], "symbol": f"{sym}-USDT", "candles": arr[i0 - WARM * mins:i0]}},
                              generate_equity_curve=True, fast_mode=True)
        m = r["metrics"]
        eq = r.get("equity_curve")
        return {"strategy": strat, "symbol": sym, "tf": tf, "secs": round(time.time() - t),
                "metrics": {k: (float(v) if isinstance(v, (int, float, np.floating)) else str(v)) for k, v in m.items()},
                "equity_curve": eq}
    except Exception as e:
        return {"strategy": strat, "symbol": sym, "error": repr(e), "tb": traceback.format_exc()[-1500:]}

if __name__ == "__main__":
    jobs = [(s, y) for s in (sys.argv[1:] or STRATS) for y in SYMS]
    out = HERE / "results"; out.mkdir(exist_ok=True)
    with Pool(int(os.environ.get("NP", 2))) as p:
        for r in p.imap_unordered(run, jobs):
            json.dump(r, open(out / f"{r['strategy']}_{r['symbol']}.json", "w"), default=str)
            print(r["strategy"], r["symbol"], r.get("error") or (r["metrics"].get("net_profit_percentage"), r["secs"]), flush=True)
