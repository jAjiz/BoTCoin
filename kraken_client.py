import krakenex
from config import KRAKEN_API_KEY, KRAKEN_API_SECRET

api = krakenex.API()
api.key = KRAKEN_API_KEY
api.secret = KRAKEN_API_SECRET

def get_balance():
    return api.query_private("Balance")

def place_limit_order(pair, type_, price, volume):
    return api.query_private("AddOrder", {
        "pair": pair,
        "type": type_,
        "ordertype": "limit",
        "price": price,
        "volume": volume,
    })

def get_open_orders():
    return api.query_private("OpenOrders")

def get_closed_orders(start=0):
    return api.query_private("ClosedOrders", { "start": start })

if __name__ == "__main__":
    print(get_balance())