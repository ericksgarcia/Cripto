"""Engenharia de features (sem lookahead: tudo usa só informação até o fechamento da barra t)."""
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
HORIZON = 24  # horas à frente que o modelo tenta prever
STEP = 4      # rebalanceamento a cada 4h


def load(symbol):
    df = pd.read_parquet(DATA / f"{symbol}_1h.parquet")
    f = pd.read_parquet(DATA / f"{symbol}_funding.parquet")["last_funding_rate"]
    # funding conhecido só após a liquidação: reindex com ffill (causal)
    df["funding"] = f.reindex(df.index.union(f.index)).ffill().reindex(df.index)
    return df


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / (dn + 1e-12))


def make_features(df, btc_ret=None):
    c, v = df["close"], df["volume"]
    r = np.log(c).diff()
    X = pd.DataFrame(index=df.index)
    for h in (1, 4, 12, 24, 72, 168, 336, 720):
        X[f"ret_{h}"] = np.log(c).diff(h)
    for w in (24, 72, 168, 720):
        X[f"vol_{w}"] = r.rolling(w).std()
    X["vol_ratio"] = X["vol_24"] / (X["vol_720"] + 1e-12)
    for n in (14, 72):
        X[f"rsi_{n}"] = rsi(c, n)
    for w in (24, 168):
        ma, sd = c.rolling(w).mean(), c.rolling(w).std()
        X[f"bb_z_{w}"] = (c - ma) / (sd + 1e-12)
    X["ema_gap_24_168"] = c.ewm(span=24).mean() / c.ewm(span=168).mean() - 1
    X["hl_range_24"] = (df["high"].rolling(24).max() - df["low"].rolling(24).min()) / c
    X["dd_720"] = c / c.rolling(720).max() - 1
    X["vol_z_168"] = (v - v.rolling(168).mean()) / (v.rolling(168).std() + 1e-12)
    X["taker_ratio"] = (df["taker_buy_base"] / (v + 1e-12)).rolling(6).mean()
    X["trades_z"] = (df["trades"] - df["trades"].rolling(168).mean()) / (df["trades"].rolling(168).std() + 1e-12)
    X["funding"] = df["funding"] * 1e4
    X["funding_ma_72"] = df["funding"].rolling(72).mean() * 1e4
    hr = df.index.hour
    X["hr_sin"], X["hr_cos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    if btc_ret is not None:  # fator de mercado
        for h in (24, 168):
            X[f"btc_ret_{h}"] = btc_ret[h].reindex(df.index)
        X["beta_btc_168"] = r.rolling(168).cov(btc_ret[1].reindex(df.index)) / (btc_ret[1].reindex(df.index).rolling(168).var() + 1e-12)
    return X


def build_panel():
    raw = {s: load(s) for s in SYMBOLS}
    lb = np.log(raw["BTCUSDT"]["close"])
    btc = {h: lb.diff(h) for h in (1, 24, 168)}
    frames = []
    for s, df in raw.items():
        X = make_features(df, btc)
        X["fwd"] = np.log(df["close"]).shift(-HORIZON) - np.log(df["close"])  # alvo (futuro!)
        X["fwd1"] = np.log(df["close"]).shift(-1) - np.log(df["close"])       # retorno da próxima barra (P&L)
        X["fwd4"] = np.log(df["close"]).shift(-STEP) - np.log(df["close"])    # retorno realizado entre rebalanceamentos
        X["symbol"] = s
        frames.append(X)
    P = pd.concat(frames).reset_index().rename(columns={"index": "open_time", "open_time": "open_time"})
    P = P.sort_values(["open_time", "symbol"]).reset_index(drop=True)
    return P


FEATURES = None
def feature_cols(P):
    return [c for c in P.columns if c not in ("open_time", "fwd", "fwd1", "fwd4", "symbol", "y", "ycs")]


if __name__ == "__main__":
    P = build_panel()
    P.to_parquet(DATA / "panel.parquet")
    print(P.shape, len(feature_cols(P)), "features")
    print(P.groupby("symbol").size())
