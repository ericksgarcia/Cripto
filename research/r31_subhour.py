"""Fase 7b — motor de confluência em candles MENORES que 1h (15m e 5m).

Mesmas famílias de sinais do motor de 1h (r28), agora em 4 tempos gráficos: base (15m ou 5m), 1h, 4h e 1d
(tempos maiores só com barras já fechadas) + posicionamento (métricas horárias, só após a hora fechar),
contexto do BTC, força relativa entre moedas, horário (inclui minuto). Alvo: retorno a frente de 4h e 12h.
LightGBM walk-forward TRIMESTRAL (só passado, embargo do horizonte). Execução realista com ordem limitada
(válida por 1h, exige "trade-through") e custos de taker/maker.

Uso: python -m research.r31_subhour build 15min | train 15min 48 | eval 15min 48
"""
import warnings; warnings.filterwarnings("ignore")
import sys, time, gc
import numpy as np, pandas as pd, lightgbm as lgb
from pathlib import Path
from engine.core import ROOT, AGG
from research.r28_confluence import tf_block

TF = sys.argv[2] if len(sys.argv) > 2 else "15min"
BAR = pd.Timedelta(TF)
BPH = int(pd.Timedelta("1h") / BAR)  # barras por hora
OUT = ROOT / "results/r31" / TF
OUT.mkdir(parents=True, exist_ok=True)
ALL = [p.stem for p in (ROOT / "data/metrics_1h").glob("*.parquet") if p.stem != "HYPE"]
BIG10 = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "LTC", "LINK", "AVAX"]
COINS = ALL if TF == "15min" else BIG10
HZ = (4 * BPH, 12 * BPH)  # 4h e 12h em barras


def load_base(sym):
    base = sym[4:] if sym.startswith("1000") else sym
    f = ROOT / "freqtrade/user_data/data_nfi/binance" / f"{base}_USDT-5m.feather"
    if f.exists():
        d = pd.read_feather(f).set_index("date")
    else:
        d = pd.read_parquet(ROOT / "data/1m" / f"{base}USDT.parquet")
    d.index = pd.to_datetime(d.index, utc=True)
    d = d.loc["2021-08-01":"2026-10-24"]
    return d.resample(TF).agg(AGG).dropna()


def coin_features(sym):
    px = load_base(sym)
    F = tf_block(px, "b")
    for tag, rule in (("h1", "1h"), ("h4", "4h"), ("d1", "1D")):
        d = px.resample(rule).agg(AGG).dropna()
        B = tf_block(d, tag)
        B.index = B.index + pd.Timedelta(rule)
        F = F.join(B.reindex(F.index + BAR, method="ffill").set_axis(F.index))
    F["npat_total"] = F.b_npat_bull + F.h1_npat_bull + F.h4_npat_bull + F.d1_npat_bull
    c = px.close; lr = np.log(c).diff()
    for hrs in (0.25, 0.5, 1, 2, 4, 12, 24, 72):
        n = max(1, int(hrs * BPH))
        F[f"ret_{hrs}h"] = c.pct_change(n)
    F["vol1d"] = lr.rolling(24 * BPH).std(); F["vol7d"] = lr.rolling(168 * BPH).std(); F["volratio"] = F.vol1d / F.vol7d
    F["sret_24h"] = F["ret_24h"] / (F.vol7d * np.sqrt(24 * BPH))
    m = pd.read_parquet(ROOT / "data/metrics_1h" / f"{sym}.parquet")
    m.index = m.index + pd.Timedelta("1h")  # valor da hora h só está disponível no fim da hora
    m = m.reindex(F.index + BAR, method="ffill").set_axis(F.index)
    z = lambda x, n=24 * 30 * BPH: (x - x.rolling(n, min_periods=24 * 7 * BPH).mean()) / x.rolling(n, min_periods=24 * 7 * BPH).std()
    F["z_retail"] = z(m.count_long_short_ratio); F["z_toppos"] = z(m.sum_toptrader_long_short_ratio)
    F["smart_div"] = F.z_toppos - F.z_retail
    oi = m.sum_open_interest_value
    for hrs in (1, 4, 24):
        F[f"oi_chg{hrs}h"] = oi.pct_change(hrs * BPH)
    F["z_taker"] = z(m.sum_taker_long_short_vol_ratio)
    fp = ROOT / "data/perps_all/funding" / f"{sym}USDT.parquet"
    if fp.exists():
        fr = pd.read_parquet(fp)["rate"]; fr = fr[~fr.index.duplicated()]
        F["funding"] = fr.reindex(F.index, method="ffill"); F["z_funding"] = z(F.funding)
    F["hour"] = F.index.hour; F["minute"] = F.index.minute; F["dow"] = F.index.dayofweek
    F["h_to_funding"] = (8 - (F.index.hour % 8)) % 8 - F.index.minute / 60
    for hb in HZ:
        F[f"fwd{hb}"] = px.open.shift(-1 - hb) / px.open.shift(-1) - 1
    F = F.loc["2021-12-01":]
    return F.astype(np.float32), px.loc["2021-12-01":]


def build():
    t = time.time()
    btc, _ = coin_features("BTC")
    ctx = btc[["ret_0.25h", "ret_1h", "ret_4h", "ret_24h", "ret_72h", "vol1d", "d1_dema200", "d1_dema50"]].add_prefix("btc_")
    rank_cols = ["ret_1h", "ret_4h", "ret_24h", "oi_chg4h", "smart_div", "z_retail", "b_vz", "z_funding"]
    ranks = []
    for s in COINS:
        F, px = (btc, None) if s == "BTC" else coin_features(s)
        if px is None:
            px = load_base("BTC").loc["2021-12-01":]
        F = F.join(ctx)
        F["resid_24h"] = F.ret_24h - F.btc_ret_24h; F["resid_4h"] = F.ret_4h - F.btc_ret_4h
        F.to_parquet(OUT / f"F_{s}.parquet")
        px.to_parquet(OUT / f"P_{s}.parquet")
        ranks.append(F[[c for c in rank_cols if c in F]].assign(sym=s))
        print(s, F.shape, f"{time.time()-t:.0f}s", flush=True)
        del F; gc.collect()
    R = pd.concat(ranks).reset_index().rename(columns={"index": "t"})
    R = R.rename(columns={R.columns[0]: "t"})
    for c in rank_cols:
        R[f"cs_{c}"] = R.groupby("t")[c].rank(pct=True).astype(np.float32)
    R[["t", "sym"] + [f"cs_{c}" for c in rank_cols]].to_parquet(OUT / "ranks.parquet")
    print("ok", f"{time.time()-t:.0f}s")


def load_all(sub=1, start=None, end=None):
    R = pd.read_parquet(OUT / "ranks.parquet")
    parts = []
    for s in COINS:
        F = pd.read_parquet(OUT / f"F_{s}.parquet")
        if start is not None:
            F = F[(F.index >= start) & (F.index < end)]
        F = F.iloc[::sub]
        F = F.reset_index().rename(columns={"index": "t"}); F = F.rename(columns={F.columns[0]: "t"}); F["sym"] = s
        parts.append(F)
    X = pd.concat(parts)
    return X.merge(R, on=["t", "sym"], how="left")


def train(hb):
    X = load_all(sub=4 * max(1, BPH // 4))  # treino: 1 amostra por hora (15m) / a cada 20 min (5m)
    fwdc = [c for c in X.columns if c.startswith("fwd")]
    feats = [c for c in X.columns if c not in ["t", "sym"] + fwdc]
    X = X[X[f"fwd{hb}"].notna()]
    X["y"] = (X[f"fwd{hb}"] / (X.vol7d * np.sqrt(hb))).clip(-5, 5)
    X = X[np.isfinite(X.y)]
    params = dict(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=500, subsample=0.5,
                  subsample_freq=1, colsample_bytree=0.5, reg_lambda=10, n_jobs=4, verbose=-1)
    preds, imps = [], []
    for q in pd.date_range("2022-07-01", "2026-10-01", freq="QS", tz="UTC"):
        tr = X[X.t < q - BAR * (hb + 1)]
        mdl = lgb.LGBMRegressor(**params).fit(tr[feats], tr.y)
        te = load_all(1, q, q + pd.offsets.QuarterBegin(1, startingMonth=1))
        p = te[["t", "sym", f"fwd{hb}"]].rename(columns={f"fwd{hb}": "fwd"})
        p["pred"] = mdl.predict(te[feats].astype(np.float32))
        preds.append(p); imps.append(pd.Series(mdl.feature_importances_, feats))
        print(q.date(), len(tr), len(te), flush=True)
        del te; gc.collect()
    P = pd.concat(preds); P.to_parquet(OUT / f"preds_{hb}.parquet")
    imp = pd.concat(imps, axis=1).mean(axis=1).sort_values(ascending=False); imp.to_csv(OUT / f"importance_{hb}.csv")
    print(imp.head(25).to_string())


def evaluate(hb, TT=0.0005):
    P = pd.read_parquet(OUT / f"preds_{hb}.parquet").dropna(subset=["fwd"]).sort_values("t")
    ic = P.groupby("t").apply(lambda g: g.pred.corr(g.fwd, method="spearman") if len(g) > 4 else np.nan).dropna()
    print("IC por ano:", ic.groupby(ic.index.year).mean().round(3).to_dict())
    roll = P.set_index("t").pred
    px = {s: pd.read_parquet(OUT / f"P_{s}.parquet") for s in P.sym.unique()}
    rows, curves = [], {}
    for q in (0.98, 0.99, 0.995, 0.999):
        th = roll.rolling("30D").quantile(q).groupby(level=0).last().shift(1)
        sel = P.merge(th.rename("thr"), left_on="t", right_index=True)
        sel = sel[sel.pred > sel.thr].copy()
        for mode, delta in (("A", 0.0), ("B", 0.0), ("B", 0.002)):
            r = np.full(len(sel), np.nan)
            for i, (t, s) in enumerate(zip(sel.t, sel.sym)):
                d = px[s]
                k = d.index.searchsorted(t)
                if k >= len(d) or d.index[k] != t or k + hb + BPH + 2 >= len(d):
                    continue
                o1 = d.open.iat[k + 1]; ox = d.open.iat[k + 1 + hb]
                if mode == "A":
                    r[i] = ox / o1 - 1 - 0.0014; continue
                lim = d.close.iat[k] * (1 - delta)
                if o1 <= lim:
                    r[i] = ox / o1 - 1 - 0.0009; continue
                lows = d.low.values[k + 1:k + 1 + BPH]
                if lows.min() <= lim * (1 - TT):
                    r[i] = ox / lim - 1 - 0.0009
            sel["r"] = r
            for slots in (5, 10):
                c = _portfolio(sel.dropna(subset=["r"]), slots, hb)
                d = c.resample("1D").last().ffill()
                for lab, a in (("2022H2-26", "2022-07-01"), ("2024-26", "2024-01-01")):
                    x = d[d.index >= a]; yrs = (x.index[-1] - x.index[0]).days / 365.25
                    cg = (x.iloc[-1] / x.iloc[0]) ** (1 / yrs) - 1
                    mo = x.resample("ME").last().pct_change().dropna()
                    rows.append({"faixa": f"top {round((1-q)*100,1)}%", "exec": f"{mode} δ={delta*100:.1f}%", "slots": slots,
                                 "período": lab, "sinais": len(sel), "exec_%": np.isfinite(r).mean() * 100,
                                 "ret_op_%": np.nanmean(r) * 100, "CAGR_%": cg * 100, "mês_%": ((1 + cg) ** (1 / 12) - 1) * 100,
                                 "meses≥5%": f"{(mo >= .05).sum()}/{len(mo)}", "meses<0": f"{(mo < 0).sum()}/{len(mo)}",
                                 "DD_%": (x / x.cummax() - 1).min() * 100})
                curves[f"{q}|{mode}{delta}|{slots}"] = d
            print(q, mode, delta, flush=True)
    T = pd.DataFrame(rows).round(2)
    T.to_csv(OUT / f"eval_{hb}.csv", index=False)
    pd.DataFrame(curves).to_parquet(OUT / f"curves_{hb}.parquet")
    pd.set_option("display.width", 250)
    for per in ("2024-26", "2022H2-26"):
        print(T[T.período == per].sort_values("CAGR_%", ascending=False).head(8).to_string(index=False))


def _portfolio(sel, slots, hb):
    sel = sel.sort_values(["t", "pred"], ascending=[True, False])
    eq = 1.0; open_ = []; curve = []; busy = set()
    dt = (BAR * (hb + 1)).to_timedelta64()
    for t, sym, r in zip(sel.t.values, sel.sym.values, sel.r.values):
        still = []
        for (to, notional, rr, s) in open_:
            if to <= t:
                eq += notional * rr; curve.append((to, eq)); busy.discard(s)
            else:
                still.append((to, notional, rr, s))
        open_ = still
        if len(open_) < slots and sym not in busy:
            open_.append((t + dt, eq / slots, r, sym)); busy.add(sym)
    for (to, notional, rr, s) in sorted(open_):
        eq += notional * rr; curve.append((to, eq))
    c = pd.Series(dict(curve)).sort_index(); c.index = pd.to_datetime(c.index, utc=True)
    return c


if __name__ == "__main__":
    step = sys.argv[1]
    if step == "build":
        build()
    elif step == "train":
        train(int(sys.argv[3]))
    elif step == "eval":
        evaluate(int(sys.argv[3]))
