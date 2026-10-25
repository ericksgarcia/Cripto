"""#5 Cash-and-carry com futuros trimestrais (hold até vencimento) e #1 funding carry refinado."""
import numpy as np, pandas as pd
from pathlib import Path
import research2 as R

P3 = Path(__file__).resolve().parent.parent / "data" / "processed3"
SPOT_FEE, FUT_FEE, DELIV_FEE = 0.0010, 0.0005, 0.0005
pd.set_option("display.width", 220); pd.set_option("display.float_format", lambda x: f"{x:,.4f}")

def contracts(base):
    out = {}
    for f in sorted(P3.glob(f"{base}_2*.parquet")):
        exp = pd.Timestamp("20" + f.stem.split("_")[1]); d = pd.read_parquet(f)
        if exp <= pd.Timestamp("2026-09-30"): out[exp] = d[d.index <= exp]
    return out

# ---------------- #5 cash & carry ----------------
def cash_carry(base, target_days, min_apr=0.0, margin=0.20):
    spot_d = pd.read_parquet(R.D / f"{base}USDT_spot_1d.parquet")["close"]
    spot_h = pd.read_parquet(Path(R.D).parent / "processed" / f"{base}USDT_1h.parquet")["close"]
    C = contracts(base); exps = sorted(C)
    trades, t = [], pd.Timestamp("2021-03-01")
    while True:
        # contratos ainda abertos em t; escolhe o de vida restante mais próxima de target_days
        cand = [(abs((e - t).days - target_days), e) for e in exps if (e - t).days > 7 and t in C[e].index]
        if not cand: break
        _, e = min(cand)
        fut = C[e]; Fin, Sin = fut.loc[t, "close"], spot_d.loc[t]
        days = (e - t).days; apr = (Fin / Sin - 1) * 365 / days
        if apr < min_apr:                         # basis insuficiente: fica em caixa 7 dias
            t += pd.Timedelta(days=7)
            if t > exps[-1]: break
            continue
        FT = fut["close"].iloc[-1]
        ST = spot_h.loc[e + pd.Timedelta(hours=7)]       # spot na hora anterior à liquidação (08:00 UTC)
        pnl = (Fin - Sin) - (FT - ST)
        cost = Sin * (SPOT_FEE * 2 + FUT_FEE + DELIV_FEE)
        # pior marcação a mercado intra-vida (alargamento do basis contra nós), em % do notional
        basis_path = (fut["close"] - spot_d.reindex(fut.index)) / spot_d.reindex(fut.index)
        mae = (basis_path.loc[t:] - (Fin / Sin - 1)).max()
        trades.append(dict(base=base, entry=t.date(), expiry=e.date(), days=days, basis_ann=apr, conv_gap=(FT - ST) / ST,
                           net_ret=(pnl - cost) / Sin, ret_on_cap=(pnl - cost) / (Sin * (1 + margin)), mae_basis=mae))
        t = e
        if t >= exps[-1] - pd.Timedelta(days=7): break
    d = pd.DataFrame(trades)
    d["ann_ret"] = (1 + d.net_ret) ** (365 / d.days) - 1
    return d

if __name__ == "__main__":
    print("=" * 30, "#5 CASH & CARRY (hold até vencimento)", "=" * 30)
    for base in ("BTC", "ETH"):
        for tgt in (90, 180):
            d = cash_carry(base, tgt)
            tot = (1 + d.net_ret).prod() - 1; yrs = (pd.Timestamp(d.expiry.iloc[-1]) - pd.Timestamp(d.entry.iloc[0])).days / 365
            print(f"\n{base} entrada ~{tgt}d antes do vencimento | {len(d)} ciclos | CAGR sobre notional {((1+tot)**(1/yrs)-1):.3%} | "
                  f"sobre capital (1,2x) {((1+(d.ret_on_cap).add(1).prod()-1)**(1/yrs)-1):.3%} | pior ciclo {d.ann_ret.min():.2%} a.a. | "
                  f"basis anualizado médio na entrada {d.basis_ann.mean():.2%} | gap de convergência médio {d.conv_gap.abs().mean():.3%} | "
                  f"alargamento máx. do basis {d.mae_basis.max():.2%}")
            if tgt == 90 and base == "BTC": print(d[["entry", "expiry", "days", "basis_ann", "net_ret", "ann_ret", "conv_gap", "mae_basis"]].to_string(index=False))
    d = pd.concat([cash_carry(b, 90) for b in ("BTC", "ETH")])
    d["year"] = pd.to_datetime(d.entry).dt.year
    print("\nPor ano (entrada ~90d, BTC+ETH):"); print(d.groupby("year").agg(ciclos=("net_ret", "size"), basis_ent=("basis_ann", "mean"), ret_ann=("ann_ret", "mean")))

    print("\n" + "=" * 30, "#1 FUNDING CARRY refinado", "=" * 30)
    spot, perp, fund = R.load()
    fa = fund * 365                     # funding diário -> APR
    print("APR médio de funding por ano (perp USDT-M):")
    print(fa[["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT", "BNBUSDT"]].groupby(fa.index.year).mean())
    print("\n% de dias com funding negativo:", (fund[["BTCUSDT", "ETHUSDT"]] < 0).mean().round(3).to_dict())
    for names, label in ((["BTCUSDT", "ETHUSDT"], "BTC+ETH"), (list(perp.columns), "25 pares")):
        r, w = R.carry(spot[names], perp[names], fund[names], always=True)
        r = r["2020-02-01":]
        for capf, cl in ((0.5, "capital 2,0x notional (50/50)"), (1 / 1.2, "capital 1,2x notional (spot cheio+20% margem)")):
            rr = r / 0.5 * capf if True else r      # r já está em base 0.5*notional -> escala p/ outro uso de capital
            eq = (1 + rr).cumprod()
            print(f"{label:9} {cl:48} CAGR {eq.iloc[-1]**(365/len(rr))-1:6.2%} vol {rr.std()*np.sqrt(365):6.2%} maxDD {(eq/eq.cummax()-1).min():7.2%} "
                  f"pior 30d {rr.rolling(30).sum().min():7.2%}")
        yr = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
        print("   retorno por ano (base 50/50):", {int(k): round(v, 4) for k, v in yr.items()})
    # top-N por funding (cross-sectional)
    print("\nTop-N por funding (rebal. semanal, trailing 14d, base 50/50, custos incluídos):")
    r_s, r_p = spot.reindex(perp.index).pct_change(), perp.pct_change()
    leg = (r_s - r_p + fund.reindex(perp.index)).fillna(0)
    apr14 = fund.reindex(perp.index).rolling(14, min_periods=14).mean().shift(1)
    for N in (3, 5, 10):
        w = pd.DataFrame(0.0, index=perp.index, columns=perp.columns); cur = None
        for i, dt in enumerate(perp.index):
            if i % 7 == 0:
                s = apr14.loc[dt].dropna(); s = s[s > 0].nlargest(N)
                cur = pd.Series(1.0 / N, index=s.index) if len(s) else pd.Series(dtype=float)
            if cur is not None and len(cur): w.loc[dt, cur.index] = cur.values
        g = (w * leg).sum(axis=1) * 0.5; c = w.diff().abs().sum(axis=1).fillna(0) * 0.5 * 2 * (R.SPOT_FEE + R.PERP_FEE)
        x = (g - c)["2020-03-01":]; eq = (1 + x).cumprod()
        print(f"  top-{N:<2}: CAGR {eq.iloc[-1]**(365/len(x))-1:6.2%} vol {x.std()*np.sqrt(365):6.2%} maxDD {(eq/eq.cummax()-1).min():7.2%} | 2023-26 CAGR {((1+x['2023-01-01':]).prod())**(365/len(x['2023-01-01':]))-1:6.2%}")

    # risco intradiário: basis spot x perp em 1h
    print("\nRisco de basis intradiário (perp 1h vs spot 1h), % do preço:")
    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        sp = pd.read_parquet(Path(R.D).parent / "processed" / f"{s}_1h.parquet")["close"]
        pf = pd.read_parquet(P3 / f"{s}_perp_1h.parquet")["close"]
        b = ((pf - sp.reindex(pf.index)) / sp.reindex(pf.index)).dropna()
        print(f"  {s}: média {b.mean():.4%}  p1 {b.quantile(.01):.3%}  p99 {b.quantile(.99):.3%}  min {b.min():.3%}  max {b.max():.3%}")
