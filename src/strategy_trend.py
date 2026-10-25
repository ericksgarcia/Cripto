"""Estratégia candidata: tendência long/flat em BTC+ETH (ensemble SMA 50/100/200) com vol target.
Entrada: closes diários spot (colunas BTCUSDT, ETHUSDT). Saída: peso-alvo por ativo para o PRÓXIMO dia
(fração do capital; resto em caixa/carry). Rebalancear 1x/dia após o fechamento UTC."""
import numpy as np, pandas as pd

CFG = dict(assets=["BTCUSDT", "ETHUSDT"], lookbacks=(50, 100, 200), vol_target=0.40, vol_win=30, max_lev=1.0)


def target_weights(close: pd.DataFrame, cfg=CFG) -> pd.DataFrame:
    close = close[cfg["assets"]]
    vol = close.pct_change().rolling(cfg["vol_win"]).std() * np.sqrt(365)
    scale = (cfg["vol_target"] / vol).clip(upper=cfg["max_lev"])
    sig = sum((close > close.rolling(L).mean()).astype(float) for L in cfg["lookbacks"]) / len(cfg["lookbacks"])
    return (sig * scale / len(cfg["assets"])).fillna(0)   # peso do dia t é aplicado ao retorno de t+1


if __name__ == "__main__":
    from pathlib import Path
    D = Path(__file__).resolve().parent.parent / "data" / "processed2"
    close = pd.DataFrame({a: pd.read_parquet(D / f"{a}_spot_1d.parquet")["close"] for a in CFG["assets"]})
    print(target_weights(close).tail(5).round(3))
