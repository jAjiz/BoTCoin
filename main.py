import time
import logging
from kraken_client import get_closed_orders, place_limit_order
from processed_orders import load_processed_orders, is_processed, save_processed_orders

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("BoTC.log", encoding='utf-8'), logging.StreamHandler()]
)

# Constantes 
ONE_WEEK_AGO = int(time.time()) - (60 * 60 * 24 * 7)
ONE_MINUTE_AGO = int(time.time()) - 60
MARGIN = 0.03 # 3%

def process_order(order_id, order, processed_orders):
    logging.info(f"Processing order [{order_id}]...")
    side = order["descr"]["type"]
    price = float(order["price"])
    volume = float(order["vol_exec"])
    cost_eur = float(order["cost"])
    response = None

    try:
        if side == "buy":
            new_side = "sell"
            new_price = price * (1 + MARGIN)
            response = place_limit_order("XXBTZEUR", new_side, new_price, volume)
            if "error" in response and response["error"]:
                raise Exception(response["error"])
            new_order = response['result']['txid'][0]
            logging.info(f"[{new_side.upper()}] 🟢 Created order {new_order} | {volume:.8f} BTC @ {new_price:,.2f}€")

        elif side == "sell":
            new_side = "buy"
            new_price = price * (1 - MARGIN)
            new_volume = cost_eur / new_price
            response = place_limit_order("XXBTZEUR", new_side, new_price, new_volume)
            if "error" in response and response["error"]:
                raise Exception(response["error"])
            new_order = response['result']['txid'][0]
            logging.info(f"[{new_side.upper()}] 🔵 Created order {new_order} | {new_volume:.8f} BTC @ {new_price:,.2f}€")

        processed_orders.add(order_id)

    except Exception as e:
        logging.error(f"Error creating {new_side.upper()} order: {e}")
    finally:
        if response:
            logging.info(f"API Response: {response}")

def main():
    processed_orders = load_processed_orders()

    try:
        response = get_closed_orders(ONE_WEEK_AGO)
        if "error" in response and response["error"]:
            raise Exception(response["error"])
    except Exception as e:
        logging.error(f"Error fetching closed orders: {e}")
        return
        
    closed_orders = response.get("result", {}).get("closed", {})
    if not closed_orders:
        logging.info(f"No closed orders returned.")
        return
    
    for order_id, order in closed_orders.items():
        if order["status"] != "closed" or is_processed(order_id, processed_orders):
            if is_processed(order_id, processed_orders):
                logging.info(f"Order [{order_id}] already processed. Skipping...")
            continue
        process_order(order_id, order, processed_orders)
    
    save_processed_orders(processed_orders)

if __name__ == "__main__":
    main()
