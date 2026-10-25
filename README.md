# Cripto — pesquisa de estratégias quantitativas

Pipeline: dados Binance (data.binance.vision) → features → LightGBM + GRU em walk-forward → backtest com custos.

```
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cd src
python download.py        # klines 1h + funding (6 pares, 2020→2026-09) em data/processed
python features.py        # painel de features (30)
python walkforward.py     # 10 folds semestrais 2022→2026, embargo 24h, preds em results/preds.parquet
python backtest.py        # baselines + modelos, custos 10 bps/turnover
```

## Resultados (out-of-sample, 2022-01 → 2026-09)
Ver `results/backtest_summary.csv` e `results/grid_smooth_fee.csv`.

- IC médio dos modelos ≈ 0,01–0,03 (sinal muito fraco; negativo em 2026).
- Com custo de 10 bps/turnover e rebalanceamento a cada 4h: **todas as estratégias de ML perdem dinheiro**
  (Sharpe -0,1 a -1,5). O Sharpe bruto do GRU long/short (1,28) é consumido pelo giro (~1,4x/dia).
- Suavizando o sinal e reduzindo custo, o melhor caso foi Sharpe ≈ 0,78 (GRU L/S, suavização 72 barras, **2 bps**) —
  escolhido entre 48 configurações, positivo em só 4 de 5 anos, com fee irreal para varejo. **Não é evidência de edge.**
- Baselines (tendência EMA, momentum 7d) também não se sustentam fora da amostra.

## Conclusão
Não há estratégia pronta para execução. Não colocar capital real com base nestes resultados.

## Próximos passos sugeridos
1. Dados mais ricos (order book/aggTrades, open interest, liquidações, basis spot-futuros) — o preço OHLCV puro de 1h é muito eficiente.
2. Estratégias de carry/funding (delta-neutro spot vs perp) — edge estrutural, menos dependente de previsão.
3. Horizontes maiores (1d–1w) com menos giro; controle de custo no objetivo (no-trade band).
4. Paper trading antes de qualquer capital real.

## Execução
`api.binance.com` retorna 451 (geo-bloqueio) a partir deste ambiente cloud; execução ao vivo precisa rodar
em máquina/VPS de região permitida, via testnet primeiro.

---
# Fase 2 — pesquisa ampliada (base `data/processed2`, 25 pares, spot+perp+funding, 2019-09→2026-09)
Scripts: `download2.py`, `research2.py`, `research3.py`, `strategy_trend.py`. Resultados: `results/research2_summary.csv`, `curves2/3.parquet`.

Literatura/projetos consultados: Han-Kang-Ryu (momentum cripto com custos reais: série temporal forte, cross-section fraca),
Freqtrade/FreqAI, Hummingbot, Jesse, NautilusTrader, repositórios de funding-rate arbitrage.

| Estratégia (2020-04→2026-09, custos incluídos) | CAGR | Vol | Sharpe | MaxDD |
|---|---|---|---|---|
| Buy&hold BTC+ETH | 57% | 64% | 1,03 | -76% |
| **Tendência ensemble BTC+ETH (SMA 50/100/200, vol target 40%)** | 41% | 27% | **1,38** | **-34%** |
| Carry spot+perp (25 pares, sem alavancagem) | 5% | 1% | 5,7 | -2% |
| Tendência + carry no caixa ocioso | 43% | 27% | 1,45 | -36% |

Robustez: tendência positiva nas duas metades (Sharpe 1,49 em 2020-22; 1,30 em 2023-26), Sharpe 1,20 mesmo com 50 bps de custo,
estável entre vol targets. **Ressalvas:** bootstrap 30d → Sharpe 1,38 com IC95% [0,52; 2,24] e diferença vs B&H com IC [-0,17; 0,89]
(P(dif>0)=0,90 — *não* estatisticamente significativa); a vantagem principal é cortar o drawdown pela metade, não aumentar o retorno.
Só 2 ativos e ~6,5 anos dominados por bull markets. Carry rende só ~2,4% a.a. em 2023-26 (funding comprimido) e ignora riscos
de contraparte/margem/basis intradiário. Tendência em 25 altcoins foi pior (viés de sobrevivência + Sharpe 0,6-1,1).
ML (LightGBM/GRU) em 1h: sem edge líquido (fase 1).

## Antes de operar de verdade
Paper trading ≥ 3 meses na testnet; execução a partir de região permitida (api.binance.com dá 451 aqui); limites de risco/kill-switch.
