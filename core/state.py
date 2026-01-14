import json
import os

os.makedirs("data", exist_ok=True)
STATE_FILE = "data/trailing_state.json"
CLOSED_FILE = "data/closed_positions.json"

def load_trailing_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_trailing_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_closed_positions():
    if os.path.exists(CLOSED_FILE):
        with open(CLOSED_FILE, "r") as f:
            return json.load(f)
    return {}

def save_closed_position(pair, pos):
    closed_positions = load_closed_positions()
    
    if pair not in closed_positions or closed_positions[pair] is None:
        closed_positions[pair] = []
    
    closed_positions[pair].append(pos)
    
    with open(CLOSED_FILE, "w") as f:
        json.dump(closed_positions, f, indent=2)