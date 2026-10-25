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
