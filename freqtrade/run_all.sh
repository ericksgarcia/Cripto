#!/bin/bash
# Roda backtest de cada estratégia do freqtrade em paralelo (4 processos)
cd "$(dirname "$0")"
TR=${TR:-20210101-20261025}
/home/user/ftenv/bin/python ft.py list-strategies -c config.json -1 2>/dev/null | grep -v NostalgiaForInfinity > logs/strategies.txt
cat logs/strategies.txt | xargs -P4 -I{} sh -c "/home/user/ftenv/bin/python ft.py backtesting -c config.json --strategy {} --timerange $TR --cache none --export trades --backtest-filename user_data/backtest_results/{}.json > logs/{}.log 2>&1; echo done {}"
