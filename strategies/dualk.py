from core.config import TRADING_PARAMS as PARAMS

def process_order(side, entry_price, current_atr, pair):
    if side == "buy":
        new_side = "sell"
        sign = 1
    else:
        new_side = "buy"
        sign = -1

    atr_value = calculate_atr_value(new_side, entry_price, current_atr, pair)
    activation_distance = calculate_activation_dist(new_side, atr_value, pair)
    activation_price = entry_price + sign * activation_distance
    return new_side, atr_value, activation_price

def calculate_atr_value(side, price, current_atr, pair):
    atr_min = PARAMS[pair][side]["ATR_MIN"]

    if current_atr is None:
        # ATR data unavailable, use minimum threshold
        atr_value = price * atr_min
    else:
        atr_pct = current_atr / price
        if atr_pct < atr_min:
            # ATR below minimum threshold, use minimum threshold
            atr_value = price * atr_min
        else:
            atr_value = current_atr

    return atr_value

def calculate_activation_dist(side, atr_value, pair):
    activation_distance = PARAMS[pair][side]["K_ACT"] * atr_value
    return activation_distance

def calculate_stop_price(side, entry_price, trailing_ref_price, atr_val, pair):
    raw_stop = PARAMS[pair][side]["K_STOP"] * atr_val
    min_margin_eur = entry_price * PARAMS[pair][side]["MIN_MARGIN"]
    
    if side == "sell":
        max_space = (trailing_ref_price - entry_price) - min_margin_eur
        stop_distance = min(raw_stop, max(0.0, max_space))
        stop_price = trailing_ref_price - stop_distance
    else:
        max_space = (entry_price - trailing_ref_price) - min_margin_eur
        stop_distance = min(raw_stop, max(0.0, max_space))
        stop_price = trailing_ref_price + stop_distance

    return stop_price