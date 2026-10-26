"""Mostra a carteira-alvo de hoje da estratégia CLAUDE_Rotation (top 5 ou top 3).

Uso: python scripts/download_binance.py BTCUSDT ...   (atualiza os dados)
     python -m scripts.sinal_rotacao [5|3]
Executar logo após o fechamento diário (00:00 UTC) e operar na abertura.
"""
import os, sys
os.environ.setdefault("CRIPTO_END", "2100-01-01")
import warnings; warnings.filterwarnings("ignore")
from engine.mine import data, s_rotation, vol

top = int(sys.argv[1]) if len(sys.argv) > 1 else 5
D = data("1d")
C = D["C"]
W = s_rotation(D, 1, look=14, top=top, regime="btc", reg_n=100, coin_ma=50)
last = W.index[-1]
btc = C["BTC"]
print(f"Último candle diário fechado: {last:%Y-%m-%d}")
print(f"Regime BTC: preço {btc.iloc[-1]:.0f} vs SMA100 {btc.rolling(100).mean().iloc[-1]:.0f} ->",
      "ALTA (pode comprar)" if btc.iloc[-1] > btc.rolling(100).mean().iloc[-1] else "BAIXA (100% USDT)")
mom = (C / C.shift(14) - 1) / vol(C, 14, 1)
print("\nMomentum ajustado (14d) e filtro SMA50:")
for s in mom.iloc[-1].sort_values(ascending=False).index:
    print(f"  {s:5s} mom={mom[s].iloc[-1]:6.2f}  acima SMA50={'sim' if C[s].iloc[-1] > C[s].rolling(50).mean().iloc[-1] else 'não'}"
          f"  peso={W[s].iloc[-1]*100:5.1f}%")
print(f"\nUSDT: {(1 - W.iloc[-1].sum())*100:.1f}%")
