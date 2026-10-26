"""Roda os ports Hummingbot/OctoBot + benchmarks em todos os pares e salva curvas diárias."""
import os, sys, time
from multiprocessing import Pool
import numpy as np, pandas as pd
from engine.core import SYMS, START, ROOT, load, metrics, portfolio
from engine.ports import STRATEGIES

OUT = ROOT / "results" / "curves"
OUT.mkdir(parents=True, exist_ok=True)


def bench(sym):
    d = load(sym, "1d", start=START)
    return d.close / d.close.iloc[0], 1


def job(args):
    name, sym = args
    t = time.time()
    f = bench if name == "BuyHold" else STRATEGIES[name]
    eq, n = f(sym)
    eq = eq[eq.index >= pd.Timestamp(START, tz="UTC")]
    eq = eq / eq.iloc[0]
    return name, sym, eq.resample("1D").last(), n, time.time() - t


if __name__ == "__main__":
    names = sys.argv[1:] or ["BuyHold"] + list(STRATEGIES)
    jobs = [(n, s) for n in names for s in SYMS]
    res = {}
    with Pool(int(os.environ.get("NP", 1))) as p:
        for name, sym, eq, n, dt in p.imap_unordered(job, jobs):
            res.setdefault(name, {})[sym] = eq
            print(f"{name:20s} {sym:5s} trades={n:6d} final={eq.iloc[-1]:.3f} {dt:.0f}s", flush=True)
    for name, curves in res.items():
        df = pd.DataFrame(curves)
        df["PORTFOLIO"] = portfolio(curves)
        df.to_parquet(OUT / f"{name}.parquet")
        print(name, {k: round(float(v), 2) for k, v in metrics(df.PORTFOLIO).items()})
