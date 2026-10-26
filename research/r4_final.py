"""Estratégia final escolhida no período DEV (2018-2023): rotação por momentum com filtros de regime.

Regras (diárias, no fechamento UTC; execução na abertura seguinte):
  1. Momentum = retorno de 14 dias / volatilidade de 14 dias (anualizada) de cada moeda.
  2. Seleciona as 5 maiores, desde que momentum > 0 e preço > SMA(50) da própria moeda.
  3. Só fica exposto se BTC > SMA(100) (regime de alta); senão 100% USDT.
  4. Pesos iguais (20% cada); banda de rebalanceamento de 10% do peso-alvo para reduzir giro.
Variante agressiva: top 3.
Também testa robustez: universo sem viés de sobrevivência, custos maiores e atraso de execução.
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import engine.mine as mine
from engine.mine import data, data_universe, eligible, s_rotation, evaluate, summarize, run, CMP
from engine.core import ROOT

FINAL = dict(look=14, top=5, regime="btc", reg_n=100, coin_ma=50)
AGGR = dict(look=14, top=3, regime="btc", reg_n=100, coin_ma=50)


def weights(D, el=None, **kw):
    return s_rotation(D, 1, kw["look"], kw["top"], el, kw["regime"], kw["reg_n"], kw["coin_ma"])


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    D = data("1d")
    res = {}
    for name, kw in (("CLAUDE_Rotation5", FINAL), ("CLAUDE_Rotation3", AGGR)):
        W = weights(D, **kw)
        res[name] = evaluate(W, D)
        s, _ = run(W, D, CMP)
        s.resample("1D").last().to_frame("PORTFOLIO").to_parquet(ROOT / "results/curves" / f"{name}.parquet")
        W.to_parquet(ROOT / "results" / f"{name}_weights.parquet")
        # custos maiores
        for c in (0.002, 0.003):
            old = mine.COST; mine.COST = c
            res[f"{name}_custo{c*100:.1f}%"] = evaluate(W, D)
            mine.COST = old
        # atraso de 1 dia na execução
        res[f"{name}_atraso1d"] = evaluate(W.shift(1), D)
    U = data_universe("1d")
    for N in (20, 30):
        el = eligible(U, 1, N)
        res[f"CLAUDE_Rotation5_univ{N}"] = evaluate(weights(U, el, **FINAL), U)
        res[f"CLAUDE_Rotation3_univ{N}"] = evaluate(weights(U, el, **AGGR), U)
    T = summarize(res)
    T.to_csv(ROOT / "results" / "r4_final.csv")
    print(T.to_string())
