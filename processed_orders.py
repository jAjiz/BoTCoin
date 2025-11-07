import json
import os

PROCESSED_FILE = "processed_orders.json"

def load_processed_orders():
    if not os.path.exists(PROCESSED_FILE):
        return set()
    with open(PROCESSED_FILE, "r") as f:
        return set(json.load(f))

def save_processed_orders(order_ids):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(order_ids), f)

def is_processed(order_id, processed_orders):
    return order_id in processed_orders
