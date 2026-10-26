#!/bin/bash
# NostalgiaForInfinityX7 (estratégia mais popular da comunidade freqtrade) — 2024-01 a 2026-10 por custo computacional
cd "$(dirname "$0")"
while pgrep -f retry2.sh >/dev/null; do sleep 30; done
/home/user/ftenv/bin/python ft.py backtesting -c config.json --strategy NostalgiaForInfinityX7 --timerange 20240101-20261025 --cache none --export trades > logs/NostalgiaForInfinityX7.log 2>&1
echo "done NFI $(grep -c 'STRATEGY SUMMARY' logs/NostalgiaForInfinityX7.log)"
