#!/bin/bash
# Fila sequencial (1 backtest por vez: cada um usa até ~8 GB de RAM com 6 anos de candles 5m)
cd "$(dirname "$0")"
while pgrep -f "strategy FixedRiskRewardLoss" >/dev/null; do sleep 20; done
for s in $(cat logs/retry2.txt); do
  /home/user/ftenv/bin/python ft.py backtesting -c config.json --strategy $s --timerange 20210101-20261025 --cache none --export trades > logs/$s.log 2>&1
  echo "done $s $(grep -c 'STRATEGY SUMMARY' logs/$s.log)"
done
# estratégias de 1m: período reduzido (2025-01 a 2026-10) por limite de memória
for s in $(cat logs/retry_1m.txt); do
  /home/user/ftenv/bin/python ft.py backtesting -c config.json --strategy $s --timerange 20250101-20261025 --cache none --export trades > logs/$s.log 2>&1
  echo "done1m $s $(grep -c 'STRATEGY SUMMARY' logs/$s.log)"
done
