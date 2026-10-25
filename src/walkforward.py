"""Walk-forward: retreina a cada semestre (janela expansiva, embargo 24h) e gera previsões fora da amostra."""
import sys, time
import numpy as np, pandas as pd, lightgbm as lgb, torch, torch.nn as nn
from features import DATA, HORIZON, STEP, feature_cols

torch.set_num_threads(4); torch.manual_seed(0); np.random.seed(0)
SEQ = 48
P = pd.read_parquet(DATA / "panel.parquet")
FC = feature_cols(P)
P["y"] = (P["fwd"] / (P["vol_24"] * np.sqrt(HORIZON) + 1e-9)).clip(-4, 4)  # retorno futuro normalizado por vol

folds = []
for y in range(2022, 2027):
    for m0, m1 in (("01", "07"), ("07", "01")):
        a = pd.Timestamp(f"{y}-{m0}-01"); b = pd.Timestamp(f"{y + (m1 == '01')}-{m1}-01")
        if a < pd.Timestamp("2026-10-01"): folds.append((a, b))


class GRUNet(nn.Module):
    def __init__(s, d, h=64):
        super().__init__()
        s.gru = nn.GRU(d, h, num_layers=2, batch_first=True, dropout=0.2)
        s.head = nn.Sequential(nn.Dropout(0.2), nn.Linear(h, 32), nn.GELU(), nn.Linear(32, 1))
    def forward(s, x):
        o, _ = s.gru(x); return s.head(o[:, -1]).squeeze(-1)


def seq_tensor(df, mu, sd):
    """Retorna X[N,SEQ,d] para as linhas de df (alinhadas por símbolo, janelas causais)."""
    arrs, idx = [], []
    for sym, g in P.groupby("symbol"):
        Z = ((g[FC].values - mu) / sd).clip(-5, 5).astype("float32")
        Z = np.nan_to_num(Z)
        win = np.lib.stride_tricks.sliding_window_view(Z, SEQ, axis=0).transpose(0, 2, 1)  # [T-SEQ+1,SEQ,d]
        pos = np.full(len(g), -1); pos[SEQ - 1:] = np.arange(len(win))
        arrs.append((sym, win, pd.Series(pos, index=g.index)))
    return arrs


def run():
    mu = None
    out = []
    # janelas pré-computadas por símbolo (usa stats globais do treino de cada fold -> recalcula por fold)
    for k, (a, b) in enumerate(folds):
        t0 = time.time()
        tr = P[(P.open_time < a - pd.Timedelta(hours=HORIZON)) & P.y.notna()].dropna(subset=FC)
        te = P[(P.open_time >= a) & (P.open_time < b)].dropna(subset=FC)
        te = te[te.open_time.dt.hour % STEP == 0]
        # ---------- LightGBM ----------
        cut = tr.open_time.quantile(0.9) - pd.Timedelta(hours=HORIZON)
        trn, val = tr[tr.open_time < cut], tr[tr.open_time >= cut + pd.Timedelta(hours=HORIZON)]
        params = dict(objective="huber", alpha=1.5, learning_rate=0.03, num_leaves=15, min_data_in_leaf=500,
                      feature_fraction=0.7, bagging_fraction=0.7, bagging_freq=1, lambda_l2=50, verbose=-1, num_threads=4)
        m = lgb.train(params, lgb.Dataset(trn[FC], trn.y), 1500, valid_sets=[lgb.Dataset(val[FC], val.y)],
                      callbacks=[lgb.early_stopping(100, verbose=False)])
        p_lgb = m.predict(te[FC], num_iteration=m.best_iteration)
        # ---------- GRU ----------
        mu, sd = tr[FC].mean().values, tr[FC].std().values + 1e-9
        wins = {sym: (w, pos) for sym, w, pos in seq_tensor(P, mu, sd)}
        def gather(df):
            X = np.empty((len(df), SEQ, len(FC)), dtype="float32"); ok = np.ones(len(df), bool)
            for sym in df.symbol.unique():
                mk = (df.symbol == sym).values
                pos = wins[sym][1].loc[df.index[mk]].values
                good = pos >= 0
                X[np.where(mk)[0][good]] = wins[sym][0][pos[good]]
                ok[np.where(mk)[0][~good]] = False
            return torch.from_numpy(X), ok
        trs = trn[trn.open_time.dt.hour % 2 == 0]; vas = val[val.open_time.dt.hour % 4 == 0]
        Xtr, ok1 = gather(trs); Xva, ok2 = gather(vas)
        ytr = torch.tensor(trs.y.values[ok1], dtype=torch.float32); yva = torch.tensor(vas.y.values[ok2], dtype=torch.float32)
        Xtr, Xva = Xtr[torch.from_numpy(ok1)], Xva[torch.from_numpy(ok2)]
        net = GRUNet(len(FC)); opt = torch.optim.AdamW(net.parameters(), 2e-3, weight_decay=1e-2)
        best, bad, state = 1e9, 0, None
        for ep in range(12):
            net.train(); perm = torch.randperm(len(Xtr))
            for i in range(0, len(perm), 512):
                j = perm[i:i + 512]
                loss = nn.functional.huber_loss(net(Xtr[j]), ytr[j], delta=1.5)
                opt.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(net.parameters(), 1.0); opt.step()
            net.eval()
            with torch.no_grad(): vl = nn.functional.huber_loss(net(Xva), yva, delta=1.5).item()
            if vl < best - 1e-5: best, bad, state = vl, 0, {k_: v.clone() for k_, v in net.state_dict().items()}
            else:
                bad += 1
                if bad >= 3: break
        net.load_state_dict(state); net.eval()
        Xte, ok3 = gather(te)
        with torch.no_grad(): p_gru = net(Xte).numpy()
        r = te[["open_time", "symbol", "fwd4", "fwd", "y", "fwd1"]].copy()
        r["lgb"], r["gru"] = p_lgb, p_gru
        r = r[ok3]
        out.append(r)
        ic = lambda c: np.corrcoef(r[c], r.y.fillna(0))[0, 1]
        print(f"fold {k} {a.date()}->{b.date()} n_tr={len(trn)} lgb_iter={m.best_iteration} IC lgb={ic('lgb'):.3f} gru={ic('gru'):.3f} ({time.time()-t0:.0f}s)", flush=True)
        pd.concat(out).to_parquet(DATA.parent.parent / "results" / "preds.parquet")
    # modelo final (para produção): treina com tudo e salva
    return pd.concat(out)


if __name__ == "__main__":
    run()
