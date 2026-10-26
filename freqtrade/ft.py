"""Wrapper do freqtrade que injeta mercados sintéticos da Binance (api.binance.com bloqueada por geo-IP)."""
import sys
import ccxt, ccxt.async_support as ccxta
from freqtrade.main import main

import json, os
BASES = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "LTC", "LINK", "AVAX"]
_pl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nfi_pairlists.json")
if os.path.exists(_pl):
    BASES = sorted(set(BASES) | {p.split("/")[0] for v in json.load(open(_pl)).values() for p in v})

def markets():
    m = {}
    for b in BASES:
        m[f"{b}/USDT"] = {
            "id": f"{b}USDT", "symbol": f"{b}/USDT", "base": b, "quote": "USDT", "settle": None,
            "baseId": b, "quoteId": "USDT", "settleId": None, "type": "spot", "spot": True,
            "margin": False, "swap": False, "future": False, "option": False, "active": True,
            "contract": False, "linear": None, "inverse": None, "contractSize": None,
            "taker": 0.001, "maker": 0.001, "expiry": None, "expiryDatetime": None, "strike": None,
            "optionType": None, "precision": {"amount": 1e-8, "price": 1e-8},
            "limits": {"amount": {"min": 1e-8, "max": 1e9}, "price": {"min": 1e-8, "max": 1e9},
                       "cost": {"min": 5.0, "max": None}, "leverage": {"min": None, "max": None}},
            "info": {}, "created": None,
        }
    return m

def sync_load(self, reload=False, params={}):
    if not self.markets:
        self.set_markets(markets())
    return self.markets

async def async_load(self, reload=False, params={}):
    return sync_load(self)

ccxt.binance.load_markets = sync_load
ccxta.binance.load_markets = async_load
ccxt.binance.fetch_markets = lambda self, params={}: list(markets().values())

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
