#!/bin/bash
cd "$(dirname "$0")"
TR=20210101-20261025
run() { /home/user/ftenv/bin/python ft.py backtesting -c config.json --strategy $1 --timerange $TR --cache none --export trades $2 > logs/$1.log 2>&1; echo "done $1 $(grep -c 'STRATEGY SUMMARY' logs/$1.log)"; }
export -f run; export TR
cat logs/retry.txt | xargs -P1 -I{} bash -c 'if [ {} = FixedRiskRewardLoss ]; then run {} "--timeframe 5m"; else run {}; fi'
cat logs/retry_1m.txt | xargs -P1 -I{} bash -c 'run {}'
