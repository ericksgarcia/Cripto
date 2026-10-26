#!/bin/bash
# NostalgiaForInfinityX7 em janelas anuais (10 pares x 5m x vários anos não cabe em 15 GB de RAM)
cd "$(dirname "$0")"
for tr in 20220101-20230101 20230101-20240101 20240101-20250101 20250101-20261025; do
  /home/user/ftenv/bin/python ft.py backtesting -c config.json --strategy NostalgiaForInfinityX7 --timerange $tr --cache none --export trades > logs/NFI_$tr.log 2>&1
  echo "done $tr $(grep -c 'STRATEGY SUMMARY' logs/NFI_$tr.log)"
done
