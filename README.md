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

---
# Fase 3 — teste das 5 estratégias sugeridas
Scripts: `download3.py` (futuros trimestrais BTC/ETH + perp 1h), `research4.py` (cash&carry e funding), `research5.py` (StatArb).

| # | Estratégia | Resultado (líquido de custos) |
|---|---|---|
| 1 | Funding delta-neutro (spot long + perp short) | BTC+ETH: 6,4% a.a. (capital 2x notional) a ~11% (spot cheio + 20% margem); 25 pares: 5,3% / 9,0%. Vol ~1%, maxDD -1,4% a -4%. Decaiu: 2021 +18%, 2023 +4%, 2025 +2,5%, 2026 +0,9% (base 50/50). Top-N por funding piorou (0–4%). |
| 2 | MEV / flash loans | **Não testável** (exige nó on-chain, mempool, builders). Sandwich = front-running de outros usuários; não implementar. |
| 3 | StatArb / pairs (ADF walk-forward, 25 perps) | Sharpe 0,52, CAGR 9,4% (2021-22: 24%; 2023-26: 2,4%, Sharpe 0,28). Placebo de pares aleatórios: Sharpe -0,16 → seleção agrega, mas edge decaiu. |
| 4 | HFT / market making | **Não testável** sem order book L2/fila de ordens e infraestrutura de baixa latência. |
| 5 | Cash & carry (futuros trimestrais, hold até vencimento) | BTC 7,4% a.a. (6,1% sobre capital 1,2x), ETH 6,1%; 23 ciclos, só 2 com retorno ≤0. Basis na entrada: 15% (2021), 2,4% (2022), 8% (2023), 14% (2024), 4,8% (2025), 1,8% (2026). |

Ressalvas: basis pode alargar até ~5-6% intra-vida (risco de margem); basis perp-spot em 1h chegou a ±2,5% (BTC/ETH) e -24% (SOL);
convergência no vencimento medida de forma aproximada (gap médio 0,37%); risco de corretora/contraparte não modelado.
Yields de carry caíram para ~2-5% a.a. em 2025-26.
