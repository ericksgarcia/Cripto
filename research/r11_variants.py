"""Fase 3 — busca em larga escala de variações da Rotação por Momentum em perpétuos USDT-M.

Universo: TODOS os perpétuos que já existiram na Binance (inclui deslistados), elegibilidade point-in-time pelos
top-N em volume (US$) de 30 dias. Custos: 0,05% taker + 0,02% slippage por lado; funding real cobrado/recebido.

Validação anti-overfitting:
  - DEV 2020-07 → 2023-12 (escolha), OOS 2024-01 → 2026-10 (só relatório).
  - Mede quanto do desempenho DEV "sobrevive" no OOS (top-decil vs. mediana), importância de cada dimensão.
  - Seletor walk-forward: a cada trimestre escolhe a melhor variante pelos 365 dias anteriores e roda o trimestre
    seguinte — avalia o PROCESSO de escolha inteiro sem olhar o futuro.
"""
import warnings; warnings.filterwarnings("ignore")
import sys, json, itertools, time
import numpy as np, pandas as pd
from numba import njit
from engine.core import ROOT, AGG
from engine.tradfi import TRADFI

COST = 0.0005 + 0.0002
DEV = ("2020-07-01", "2023-12-31")
OOS = ("2024-01-01", "2026-10-25")
STABLE_IDX = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "USDE", "DEFI", "BLUEBIRD", "FOOTBALL", "BTCDOM", "ALL"}


LEVERAGED = ("UP", "DOWN", "BULL", "BEAR")
FIAT_STABLE = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "PAX", "DAI", "EUR", "GBP", "AUD", "USDS", "USDSB", "SUSD",
               "UST", "USTC", "AEUR", "EURI", "XUSD", "USD1", "RLUSD", "BFUSD", "TRY", "BRL", "PAXG", "WBTC", "WBETH",
               "BETH", "BNSOL", "USDE", "U"}


def load_spot(min_days=60):
    """Todos os pares spot USDT da Binance (inclui deslistados), sem tokens alavancados, stables, fiat e wrapped."""
    C, O, H, L, V = {}, {}, {}, {}, {}
    for p in sorted((ROOT / "data/spot_all/1d").glob("*.parquet")):
        base = p.stem[:-4]
        if not p.stem.isascii() or base in FIAT_STABLE or base in TRADFI or \
                (base.endswith(LEVERAGED) and len(base) > 4 and base not in ("JUP", "SUP")):
            continue
        d = pd.read_parquet(p).loc[:"2026-10-25"]
        g = d.index.to_series().diff()
        cut = g[g > pd.Timedelta("3D")]
        if len(cut):
            d = d[d.index < cut.index[0]]
        if len(d) < min_days:
            continue
        C[base], O[base], H[base], L[base] = d.close, d.open, d.high, d.low
        V[base] = d.volume * d.close
    D = {k: pd.DataFrame(v) for k, v in dict(C=C, O=O, H=H, L=L, V=V).items()}
    idx = pd.date_range("2017-08-17", "2026-10-25", freq="1D", tz="UTC")
    D = {k: v.reindex(idx) for k, v in D.items()}
    D["F"] = pd.DataFrame(0.0, idx, D["C"].columns)
    return D


def load_perps(min_days=60):
    C, O, H, L, V, F = {}, {}, {}, {}, {}, {}
    for p in sorted((ROOT / "data/perps_all/1d").glob("*.parquet")):
        s = p.stem
        base = s[:-4]
        if base in STABLE_IDX or base.endswith("DOM") or not s.isascii() or base in TRADFI:
            continue
        d = pd.read_parquet(p).loc[:"2026-10-25"]
        g = d.index.to_series().diff()
        cut = g[g > pd.Timedelta("3D")]
        if len(cut):
            d = d[d.index < cut.index[0]]
        if len(d) < min_days:
            continue
        k = s[:-4]
        C[k], O[k], H[k], L[k] = d.close, d.open, d.high, d.low
        V[k] = d.volume * d.close
        fp = ROOT / "data/perps_all/funding" / f"{s}.parquet"
        if fp.exists():
            F[k] = pd.read_parquet(fp)["rate"].resample("1D").sum()
    D = {k: pd.DataFrame(v) for k, v in dict(C=C, O=O, H=H, L=L, V=V).items()}
    idx = pd.date_range("2019-09-08", "2026-10-25", freq="1D", tz="UTC")
    D = {k: v.reindex(idx) for k, v in D.items()}
    D["F"] = pd.DataFrame(F).reindex(idx).reindex(columns=D["C"].columns).fillna(0.0)
    return D


# ------------------------------------------------------------------------------ simulação numpy
@njit(cache=True)
def sim_np(O, W, F, cost, H=None, L=None, C=None, dstop=0.0):
    """O,F: T×K; W decidido no fechamento de t (posição de open t+1 a open t+2). Retorna retorno diário líquido.
    dstop > 0: stop intradiário — se a mínima (máxima, p/ short) do dia passar de fechamento_anterior*(1∓dstop),
    sai nesse preço (ou na abertura, se abriu além do stop) e fica fora até a próxima decisão."""
    T, K = O.shape
    out = np.zeros(T)
    prev = np.zeros(K)
    for t in range(1, T - 1):
        g = 0.0; turn = 0.0; fund = 0.0
        for k in range(K):
            w = W[t - 1, k]
            if np.isnan(w) or np.isnan(O[t, k]) or np.isnan(O[t + 1, k]):
                w = 0.0
            if w != 0.0 and dstop > 0.0 and prev[k] == 0.0 and t >= 2 and W[t - 2, k] == w:
                w = 0.0  # stopado ontem e a decisão não mudou: continua fora
            turn += abs(w - prev[k])
            if w != 0.0:
                ex = O[t + 1, k]
                stopped = False
                if dstop > 0.0 and not np.isnan(C[t - 1, k]):
                    if w > 0:
                        lvl = C[t - 1, k] * (1 - dstop)
                        if L[t, k] <= lvl:
                            ex = min(O[t, k], lvl); stopped = True
                    else:
                        lvl = C[t - 1, k] * (1 + dstop)
                        if H[t, k] >= lvl:
                            ex = max(O[t, k], lvl); stopped = True
                g += w * (ex / O[t, k] - 1.0)
                fund += w * F[t, k]
                if stopped:
                    turn += abs(w); w = 0.0
            prev[k] = w
        out[t + 1] = g - turn * cost - fund
    return out


@njit(cache=True)
def build_weights(score, ok_long, ok_short, regime, top, buffer, rebal, short_w, short_k, wmode, ivol):
    """Seleção com histerese (mantém a moeda até sair do top+buffer) e rebalanceamento a cada `rebal` dias.
    wmode: 0 = pesos iguais, 1 = inverso da vol. Short opcional das short_k piores (peso total short_w)."""
    T, K = score.shape
    W = np.zeros((T, K))
    held = np.zeros(K, np.bool_)
    for t in range(T):
        if t % rebal != 0 and t > 0:
            W[t] = W[t - 1]
            continue
        s = score[t]
        # ranking (desc) só entre válidos
        order = np.argsort(-np.where(np.isnan(s), -1e18, s))
        nvalid = 0
        for k in range(K):
            if not np.isnan(s[k]):
                nvalid += 1
        rank = np.full(K, 10 ** 9)
        for r in range(nvalid):
            rank[order[r]] = r
        newheld = np.zeros(K, np.bool_)
        cnt = 0
        if regime[t] > 0:
            # mantém os já possuídos que continuam dentro de top+buffer e válidos
            for k in range(K):
                if held[k] and rank[k] < top + buffer and ok_long[t, k] and s[k] > 0:
                    newheld[k] = True; cnt += 1
            for r in range(nvalid):
                if cnt >= top:
                    break
                k = order[r]
                if not newheld[k] and ok_long[t, k] and s[k] > 0:
                    newheld[k] = True; cnt += 1
        held = newheld
        if cnt > 0:
            tot = 0.0
            for k in range(K):
                if held[k]:
                    W[t, k] = 1.0 if wmode == 0 else ivol[t, k]
                    tot += W[t, k]
            for k in range(K):
                if held[k]:
                    W[t, k] = W[t, k] / tot * min(cnt, top) / top * regime[t]
        if short_w > 0 and short_k > 0:
            c2 = 0
            for r in range(nvalid - 1, -1, -1):
                if c2 >= short_k:
                    break
                k = order[r]
                if ok_short[t, k] and s[k] < 0 and not held[k]:
                    W[t, k] -= short_w / short_k; c2 += 1
    return W


# ------------------------------------------------------------------------------ features
class Feats:
    def __init__(self, D):
        self.D = D
        C = D["C"]
        self.C = C
        self.lr = np.log(C).diff()
        self.Hv = D["H"].values.astype(np.float64); self.Lv = D["L"].values.astype(np.float64)
        self.Cv = C.values.astype(np.float64)
        self.cache = {}

    def get(self, key, fn):
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]

    def vol(self, n):
        return self.get(("vol", n), lambda: self.lr.rolling(n, min_periods=max(5, n // 2)).std() * np.sqrt(365))

    def ret(self, n):
        return self.get(("ret", n), lambda: self.C / self.C.shift(n) - 1)

    def sma_ok(self, n):
        return self.get(("sma", n), lambda: (self.C > self.C.rolling(n).mean()) if n else self.C.notna())

    def elig(self, N, min_age=30, maxvol=0.0):
        def f():
            V = self.D["V"].rolling(30, min_periods=10).mean()
            age = self.C.notna().cumsum()
            V = V.where(age >= min_age)
            if maxvol > 0:
                V = V.where(self.vol(30) <= maxvol)
            return V.rank(axis=1, ascending=False) <= N
        return self.get(("elig", N, min_age, maxvol), f)

    def score(self, kind, look):
        def f():
            looks = look if isinstance(look, tuple) else (look,)
            parts = []
            for L in looks:
                if kind == "riskadj":
                    x = self.ret(L) / (self.vol(L) * np.sqrt(L / 365))
                elif kind == "raw":
                    x = self.ret(L)
                elif kind == "resid":  # momentum residual ao BTC (remove o beta)
                    b = self.lr.rolling(60).cov(self.lr["BTC"]).div(self.lr["BTC"].rolling(60).var(), axis=0)
                    rb = self.ret(L)["BTC"]
                    x = (self.ret(L) - b.mul(rb, axis=0)) / (self.vol(L) * np.sqrt(L / 365))
                elif kind == "sharpe_smooth":  # tendência suave: retorno médio / desvio dos retornos diários
                    x = self.lr.rolling(L).mean() / self.lr.rolling(L).std()
                parts.append(x.rank(axis=1, pct=True) - 0.5 if len(looks) > 1 else x)
            s = sum(parts) / len(parts)
            if len(looks) > 1:  # sinal absoluto do ensemble: retorno do menor horizonte
                s = s.where(self.ret(min(looks)) > 0, -s.abs())
            return s
        return self.get(("score", kind, look), f)

    def regime(self, kind):
        C = self.C
        def f():
            btc = C["BTC"]
            br = lambda n: ((C > C.rolling(n).mean()).where(C.notna()).mean(axis=1) > 0.5).astype(float)
            if kind == "none":
                return pd.Series(1.0, C.index)
            if kind == "btc100&breadth50":
                return ((btc > btc.rolling(100).mean()) & (br(50) > 0)).astype(float)
            if kind == "btc100|breadth50":
                return ((btc > btc.rolling(100).mean()) | (br(50) > 0)).astype(float)
            if kind.startswith("btc"):
                n = int(kind[3:])
                return (btc > btc.rolling(n).mean()).astype(float)
            if kind.startswith("breadth"):
                return br(int(kind[7:]))
            if kind == "graded":  # 0, 0.5 ou 1 conforme BTC acima de SMA50 e SMA200
                return ((btc > btc.rolling(50).mean()).astype(float) + (btc > btc.rolling(200).mean()).astype(float)) / 2
        return self.get(("reg", kind), f)


SPACE = dict(
    look=[7, 10, 14, 21, 30, 45, 60, (7, 14, 30), (14, 30, 60), (7, 21)],
    kind=["riskadj", "raw", "resid", "sharpe_smooth"],
    top=[2, 3, 4, 5, 7],
    N=[5, 8, 10, 15, 20, 30, 50],
    regime=["none", "btc50", "btc100", "btc200", "breadth50", "breadth100", "btc100&breadth50", "btc100|breadth50", "graded"],
    coin_ma=[0, 20, 50, 100],
    rebal=[1, 2, 3, 7],
    buffer=[0, 1, 3],
    short_w=[0.0, 0.25, 0.5],
    wmode=[0, 1],
    vt=[0.0, 0.6, 1.0],
    min_age=[30, 180, 365],
    maxvol=[0.0, 1.5, 1.0],
    dstop=[0.0, 0.1, 0.2],
    lev=[1.0],
)


def run_config(fe, cfg, O, F):
    C = fe.C
    el = fe.elig(cfg["N"], cfg.get("min_age", 30), cfg.get("maxvol", 0.0))
    sc = fe.score(cfg["kind"], cfg["look"]).where(el)
    okl = (fe.sma_ok(cfg["coin_ma"]) & el).values
    oks = ((~fe.sma_ok(50)) & el).values
    reg = fe.regime(cfg["regime"]).values
    iv = (1 / fe.vol(30)).fillna(0).values
    W = build_weights(sc.values.astype(np.float64), okl, oks, reg.astype(np.float64), cfg["top"], cfg["buffer"],
                      cfg["rebal"], cfg["short_w"], 5, cfg["wmode"], iv)
    r = sim_np(O, W * cfg["lev"], F, COST, fe.Hv, fe.Lv, fe.Cv, cfg.get("dstop", 0.0))
    r = pd.Series(r, C.index)
    if cfg["vt"] > 0:  # alvo de vol da carteira (escala decidida com dados até t-1, máx 1x)
        pv = r.rolling(30, min_periods=10).std().shift(1) * np.sqrt(365)
        sc_ = (cfg["vt"] / pv).clip(upper=1.0).fillna(1.0)
        r = r * sc_ - (sc_.diff().abs().fillna(0) * 0.3 * COST)
    return r


def stats(r, a, b):
    x = r[(r.index >= pd.Timestamp(a, tz="UTC")) & (r.index <= pd.Timestamp(b, tz="UTC"))]
    eq = (1 + x.clip(lower=-1)).cumprod()
    yrs = len(x) / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1
    sh = x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0
    dd = (eq / eq.cummax() - 1).min()
    return cagr, sh, dd


def cfg_name(c):
    return "|".join(f"{k}={v}" for k, v in c.items())


if __name__ == "__main__":
    n_samples = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    SRC = sys.argv[2] if len(sys.argv) > 2 else "perps"
    t0 = time.time()
    if SRC == "spot":
        COST = 0.0012
        SPACE["short_w"] = [0.0]
        SPACE["vt"] = [0.0, 0.6]
        D = load_spot()
    else:
        D = load_perps()
    print("moedas:", D["C"].shape[1], "dias:", len(D["C"]), f"{time.time()-t0:.0f}s", flush=True)
    fe = Feats(D)
    O = D["O"].values.astype(np.float64); F = D["F"].values.astype(np.float64)
    rng = np.random.default_rng(42)
    keys = list(SPACE)
    seen, rows, rets = set(), [], {}
    base = dict(look=14, kind="riskadj", top=5, N=10, regime="btc100", coin_ma=50, rebal=1, buffer=0,
                short_w=0.0, wmode=0, vt=0.0, min_age=30, maxvol=0.0, dstop=0.0, lev=1.0)
    cfgs = [base, {**base, "top": 3, "short_w": 0.5}]
    while len(cfgs) < n_samples:
        c = {k: SPACE[k][rng.integers(len(SPACE[k]))] for k in keys}
        if cfg_name(c) not in seen:
            seen.add(cfg_name(c)); cfgs.append(c)
    for i, c in enumerate(cfgs):
        r = run_config(fe, c, O, F)
        d, o, full = stats(r, *DEV), stats(r, *OOS), stats(r, "2020-07-01", "2026-10-25")
        name = cfg_name(c)
        rows.append({**{k: str(v) for k, v in c.items()}, "name": name,
                     "DEV_cagr": d[0] * 100, "DEV_sharpe": d[1], "DEV_dd": d[2] * 100,
                     "OOS_cagr": o[0] * 100, "OOS_sharpe": o[1], "OOS_dd": o[2] * 100,
                     "ALL_cagr": full[0] * 100, "ALL_sharpe": full[1], "ALL_dd": full[2] * 100})
        rets[name] = r.astype(np.float32)
        if i % 200 == 0:
            print(i, f"{time.time()-t0:.0f}s", flush=True)
    T = pd.DataFrame(rows)
    suf = "" if SRC == "perps" else "_spot"
    T.to_csv(ROOT / f"results/r11_variants{suf}.csv", index=False)
    pd.DataFrame(rets).to_parquet(ROOT / f"results/r11_returns{suf}.parquet")
    print("ok", len(T), f"{time.time()-t0:.0f}s")
