# Cripto: comparação de bots de trade open-source e uma estratégia própria

Este repositório compara, nas mesmas condições, as estratégias dos principais projetos open-source de trade de cripto no GitHub. Também testa se dá para combiná-las e se uma estratégia própria consegue superar todas elas.

> **Aviso.** Backtest não garante resultado futuro. Os números abaixo usam taxa de 0,1% por lado mais 0,02% de slippage e execução no candle seguinte ao sinal, sem look-ahead. Mesmo assim, ignoram impostos, liquidez extrema, falhas de exchange e o risco de a estratégia parar de funcionar. Nada aqui é recomendação de investimento.

![Curvas](results/equity_drawdown.png)

## 1. Projetos escolhidos

| # | Projeto | Por que entrou | Como foi testado |
|---|---|---|---|
| 1 | **[freqtrade/freqtrade](https://github.com/freqtrade/freqtrade)** (~50k ⭐) | É o bot open-source mais usado | Instalado (v2026.9). As estratégias oficiais de [freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) rodaram no **backtester do próprio freqtrade** |
| 2 | **[iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity)** | É a estratégia comunitária mais famosa do freqtrade | Rodou no freqtrade (X7). Como é muito pesada, o período foi reduzido |
| 3 | **[jesse-ai/jesse](https://github.com/jesse-ai/jesse)** | É o framework de pesquisa e backtest mais citado | Instalado. As estratégias de [example-strategies](https://github.com/jesse-ai/example-strategies) rodaram no **motor do próprio Jesse** (`jesse.research.backtest`) sobre candles de 1m |
| 4 | **[hummingbot/hummingbot](https://github.com/hummingbot/hummingbot)** (~20k ⭐) | É referência em market making e scalping | Os controllers direcionais V2 (`bollinger_v1`, `macd_bb_v1`, `supertrend_v1`) foram portados com os parâmetros padrão: candles de 3m, triple barrier SL 3% / TP 2% / 45 min, cooldown e 2 executores por lado |
| 5 | **[Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot)** (~5k ⭐) | Oferece grid, DCA e "daily trading" prontos | Os perfis padrão (Grid, Trailing Grid, Simple DCA, Smart DCA e Daily Trading com os avaliadores RSI e Double MA) foram portados para o motor comum |

O market making puro do Hummingbot (PMM) e a arbitragem não foram simulados. Eles dependem de livro de ofertas e da fila de ordens, que candles não representam.

## 2. Dados

- Fonte: dados públicos completos da Binance em **data.binance.vision**, com klines spot de 1 minuto desde 2017. A API `api.binance.com` é bloqueada por região neste ambiente, então o freqtrade recebe os mercados por um wrapper offline (`freqtrade/ft.py`).
- São 10 pares USDT: BTC, ETH, BNB, SOL, XRP, ADA, DOGE, LTC, LINK e AVAX. Isso dá cerca de 43 milhões de candles de 1m, reamostrados para 3m, 5m, 15m, 1h, 4h e 1d. Para reproduzir, rode `scripts/download_binance.py`.
- Para checar o **viés de sobrevivência**, há também um universo de 70 moedas em 1h, incluindo as que colapsaram ou foram deslistadas (LUNA, FTT, SRM, WAVES, EOS etc.), com seleção point-in-time pelas top-N em volume (`scripts/download_universe.py`).
- Período comum: **2021-01-01 → 2026-10-25**. A janela **fora da amostra (OOS)** vai de 2024-01 a 2026-10.

## 3. Resultado: qual rende mais

O ranking completo está em [`results/ranking_geral.md`](results/ranking_geral.md). A tabela abaixo mostra a melhor estratégia de cada projeto. Cada uma começa com o mesmo capital, de 2021-01 a 2026-10:

| Projeto | Melhor estratégia | Retorno total | CAGR | Max DD | Sharpe | CAGR OOS 24-26 | DD OOS |
|---|---|---|---|---|---|---|---|
| Benchmark | Buy & Hold dos 10 pares | +954% | 50% | **-87%** | 0,90 | -1% | -72% |
| Jesse | Donchian (4h) | +1.755% | 65% | -52% | 1,10 | -1% | -52% |
| Freqtrade | **MultiMa** (4h) | +877% | 48% | **-26%** | **1,39** | 12% | -23% |
| OctoBot | Grid | +81% | 11% | -19% | 0,80 | 7% | -19% |
| Hummingbot | (todos perdem: scalping de 3m não sobrevive à taxa de 0,1%) | -91% a -100% | | | | | |
| **Própria** | **Rotação de momentum (top 5)** | **+8.952%** | **117%** | -39% | **1,82** | **40%** | -32% |
| **Própria** | Rotação de momentum (top 3, agressiva) | +19.042% | 147% | -56% | 1,79 | 69% | -33% |
| **Combo** | **Rotação5 + MultiMa (50/50)** | +3.379% | 84% | **-23%** | **2,14** | 27% | **-19%** |

O que os números mostram:

1. **Entre os projetos prontos, o MultiMa do freqtrade é o mais sólido.** É uma tendência com médias TEMA e take-profit escalonado. Teve o menor drawdown entre as estratégias que ganham bem e é o único que bate o buy & hold em risco ajustado nas duas janelas. O Donchian do Jesse ganhou mais em 2021, mas ficou no zero de 2024 a 2026.
2. **Cerca de 70% das estratégias de exemplo perdem dinheiro** depois das taxas. As piores são os scalpers de 1m a 15m e as de reversão à média.
3. **Os controllers do Hummingbot e o DailyTrading do OctoBot, com parâmetros padrão, destroem capital.** Fazem dezenas de milhares de operações com alvo de 2% e pagam 0,24% de custo por ida e volta. O Hummingbot só faz sentido como market maker, com taxa maker ou rebate.
4. **Grid (OctoBot)** dá retorno baixo e estável: 11% ao ano com DD de -19%. Ele fica 100% em USDT quando o preço sai do range para cima e "segura o saco" quando o preço cai abaixo do range.

## 4. As estratégias se complementam?

Sim, mas só as que capturam fenômenos diferentes. Os detalhes estão em `research/r3_combine.py`, com os resultados em `results/r3_*.csv`.

- A correlação diária entre a **Rotação** (própria) e o **MultiMa** é de apenas **0,12**. Já os seguidores de tendência "clássicos" entre si (Donchian, MACD_EMA, SMACrossover, SimpleBollinger) ficam entre 0,5 e 0,7: na prática são a mesma aposta.
- Grid e DCA têm correlação de 0,7 a 0,97 com o buy & hold, então não diversificam nada em queda.
- **A melhor complementação foi Rotação5 + MultiMa, 50/50 com rebalanceamento semanal.** No período inteiro, o Sharpe sobe para **2,14**, o maior de todos, e o Calmar para 3,7. O drawdown fora da amostra cai de -32% para **-19%**, mantendo ~27% ao ano. Somando o Grid do OctoBot (1/3 cada), o DD OOS fica em -18%.
- **Cuidado com combinar só pelo histórico.** Escolhendo de forma gulosa apenas entre as estratégias externas, pelo Sharpe de 2021-2023, saiu MultiMa + AwesomeMacd + Donchian (Sharpe 2,4 no período de seleção). Fora da amostra, esse combo deu **-1% ao ano com DD de -52%**. Combinar estratégias que só pareceram boas no passado é overfitting disfarçado.

## 5. Uma estratégia melhor que todas

**Rotação de momentum entre moedas com filtros de regime** (`engine/mine.py: s_rotation`, `research/r4_final.py`):

1. Todo dia (fechamento UTC), calcula para cada moeda o **momentum = retorno de 14 dias ÷ volatilidade de 14 dias**.
2. Compra as **5 melhores** em pesos iguais (20% cada), desde que o momentum seja > 0 e o preço esteja acima da própria SMA de 50 dias.
3. Só fica exposta se o **BTC estiver acima da SMA de 100 dias**. Fora disso, fica 100% em USDT. Esse filtro é o que evitou o -82% de 2022.
4. Executa na abertura seguinte, com banda de rebalanceamento de 10% para reduzir giro. São ~52 voltas de carteira por ano.

Por que ela funciona: momentum cross-sectional e tendência são os efeitos mais documentados em cripto. O filtro de regime corta a maior parte das quedas longas, e a seleção relativa captura as "altseasons" (SOL em 2021, DOGE e BNB, AVAX etc.).

### Como evitei me enganar

- Os parâmetros foram **escolhidos só com 2018-2023**, numa varredura de 432 combinações (`research/r1_rotation.py`). A escolha foi a de maior Sharpe no desenvolvimento. O período **2024-2026 ficou intocado** e é reportado como está. O "platô" é largo: as medianas de Sharpe no desenvolvimento variam de 1,5 a 1,9 em todos os parâmetros, então não é um pico isolado.
- **Viés de sobrevivência:** num universo de 70 moedas com LUNA, FTT etc., escolhendo as top 20/30 por volume na época, o resultado se mantém. O CAGR de 2021-2026 fica em 152-155% e o Sharpe em 1,7. O drawdown, porém, fica pior: entre -50% e -55%.
- **Custos:** com o triplo de taxa (0,3% por lado), ainda dá 98% ao ano. Com **1 dia de atraso** na execução, dá 108% ao ano.
- **Stops intradiários (ATR em 4h)** foram testados e **pioraram** o resultado. Execução em 4h em vez de diária também piorou.

### "Estratégia avançada com candles": modelo de ML

O `research/r2_ml_candles.py` treina um **LightGBM cross-sectional com 129 features**:

- anatomia dos candles: corpo, pavios e CLV;
- 16 padrões de candlestick do TA-Lib (engolfo, martelo, estrelas etc.) e Heikin-Ashi;
- estrutura intradiária em 4h, volume, RSI, distância de médias e contexto do BTC;
- ranks cross-sectionais.

O treino é walk-forward trimestral com embargo, no universo de 30 moedas sem viés de sobrevivência.

- O modelo **tem poder preditivo real**: IC de Spearman entre 0,10 e 0,14 em todos os anos de 2020 a 2026.
- Mesmo assim, **como carteira perde para a rotação simples**: 72-76% ao ano contra 147-155% no mesmo universo.
- **As features de padrão de candle praticamente não aparecem entre as importantes.** As 20 principais são todas de tendência, momentum e volatilidade (`dma200`, `ret90`, `dhigh60`, `atrp`...). O modelo "redescobre" o momentum com mais ruído.

Conclusão honesta: padrões clássicos de candle não trouxeram vantagem mensurável em cripto diária. A regra simples e robusta venceu o modelo complexo.

## 6. Como reproduzir

```bash
python3 -m venv ~/ftenv && ~/ftenv/bin/pip install freqtrade numba lightgbm tabulate
python3 -m venv ~/jenv  && ~/jenv/bin/pip install jesse            # (ambiente separado: conflito de numpy)

~/ftenv/bin/python scripts/download_binance.py BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT ADAUSDT DOGEUSDT LTCUSDT LINKUSDT AVAXUSDT
~/ftenv/bin/python scripts/to_freqtrade.py   BTCUSDT ETHUSDT ...        # feather p/ freqtrade
~/ftenv/bin/python scripts/download_universe.py                        # universo de 70 moedas (1h)

freqtrade/run_all.sh                                   # freqtrade (1 processo por vez se tiver < 16 GB de RAM)
~/jenv/bin/python jesse_bt/run_jesse.py                # Jesse
~/ftenv/bin/python -m engine.run_ports                 # Hummingbot / OctoBot + buy & hold
~/ftenv/bin/python -m engine.parse_freqtrade && ~/ftenv/bin/python -m engine.parse_jesse

~/ftenv/bin/python -m research.r1_rotation 10          # varredura da rotação (DEV/OOS)
~/ftenv/bin/python -m research.r2_ml_candles 30        # modelo de ML com candles
~/ftenv/bin/python -m research.r3_combine              # complementaridade e combos
~/ftenv/bin/python -m research.r4_final                # estratégia final + robustez
~/ftenv/bin/python -m research.r6_table && ~/ftenv/bin/python -m research.r5_charts

~/ftenv/bin/python -m scripts.sinal_rotacao 5          # carteira-alvo de hoje
```

## 7. Estrutura

```
engine/core.py        motor comum (numba): exposição-alvo, triple barrier, grid, carteira multiativo, métricas
engine/ports.py       ports Hummingbot (3 controllers) e OctoBot (5 perfis)
engine/mine.py        blocos de sinal e estratégias próprias (rotação, TSMOM, turtle, overlay de stop)
freqtrade/            config, wrapper offline de mercados, estratégias oficiais + NFI
jesse_bt/             runner do Jesse + estratégias de exemplo (patch mínimo de compatibilidade no KDJ)
research/             r1 varredura · r2 ML com candles · r3 combinações · r4 final/robustez · r5 gráficos · r6 tabela
results/              CSVs, curvas diárias (parquet) e gráfico
```

## 8. Limitações conhecidas

- Os 10 pares são as moedas grandes de hoje, o que favorece qualquer estratégia comprada (inclusive o buy & hold). O teste no universo de 70 moedas mitiga isso.
- Hummingbot e OctoBot foram **portados**, não rodados nos motores originais (os backtesters deles exigem infraestrutura de exchange e banco). A lógica e os parâmetros padrão foram copiados dos repositórios. Os avaliadores do OctoBot foram simplificados: a parte "chances to be max" do DoubleMA ficou de fora.
- No Jesse, o `TurtleRules` estoura a margem mesmo com 3x, pelo sizing piramidal, e o `IFR2` não gera sinais nesses pares. No freqtrade, `FixedRiskRewardLoss` é incompatível com o pandas atual e as estratégias short (`AlmgrenChriss`, `TWAP`) não rodam em spot. As estratégias de 1m rodaram só de 2025 a 2026, por limite de memória.
- A rotação concentra em poucas moedas: espere quedas de 30 a 55% e longos períodos parados em USDT (ela não opera em boa parte de 2022).
