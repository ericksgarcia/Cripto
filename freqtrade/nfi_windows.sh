#!/bin/bash
# NFI X7 com config recomendado (grinding, 6 posições) e 25 pares point-in-time por janela de 4 meses.
cd "$(dirname "$0")"
for tr in $(/home/user/ftenv/bin/python -c "import json; print(' '.join(json.load(open('nfi_pairlists.json'))))"); do
  [ -f logs/NFI25_$tr.done ] && continue
  pairs=$(/home/user/ftenv/bin/python -c "import json; print(' '.join(json.load(open('nfi_pairlists.json'))['$tr']))")
  /home/user/ftenv/bin/python ft.py backtesting -c config_nfi.json --strategy NostalgiaForInfinityX7 --timerange $tr \
     --pairs $pairs --cache none --export trades --backtest-directory user_data/backtest_results_nfi > logs/NFI25_$tr.log 2>&1
  ok=$(grep -c 'STRATEGY SUMMARY' logs/NFI25_$tr.log); echo "done $tr $ok"; [ "$ok" = "1" ] && touch logs/NFI25_$tr.done
done
