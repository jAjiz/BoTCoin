import core.logging as logging
from trading.parameters_manager import get_k_stop
from core.config import ASSET_MIN_ALLOCATION, PAIRS, RECENTER_PARAMS, TRADING_PARAMS

def calculate_activation_price(pair, side, entry_price, atr_val):
    activation_distance = calculate_activation_dist(pair, side, entry_price, atr_val)

    if side == "sell":
        activation_price = entry_price - activation_distance
    else:
        activation_price = entry_price + activation_distance

    return activation_price

def calculate_activation_dist(pair, side, entry_price, atr_val):
    k_act = TRADING_PARAMS[pair][side]["K_ACT"]

    if k_act is not None:
        activation_distance = float(k_act) * atr_val
    else:
        k_stop = get_k_stop(pair, side, atr_val)
        min_margin = float(TRADING_PARAMS[pair][side]["MIN_MARGIN"])
        activation_distance = k_stop * atr_val + min_margin * entry_price

    return activation_distance

def calculate_stop_price(pair, side, trailing_price, atr_val):
    k_stop = get_k_stop(pair, side, atr_val)
    stop_distance = k_stop * atr_val

    if side == "sell":
        stop_price = trailing_price - stop_distance
    else:
        stop_price = trailing_price + stop_distance

    return stop_price

def check_recenter_activation(pair, pos, atr_val, price):
        atr_threshold = float(RECENTER_PARAMS[pair]["ATR_MULT"]) * atr_val
        price_threshold = float(RECENTER_PARAMS[pair]["PRICE_PCT"]) * price
        max_threshold = max(atr_threshold, price_threshold)

        # If both RECENTER_PARAMS are set to 0, skip recentering
        if max_threshold > 0 and abs(pos["activation_price"] - price) > max_threshold:
            return True
        return False

def can_execute_sell(pair, order_id, vol_to_sell, balance, price):
    asset = PAIRS[pair]["base"]
    fiat = PAIRS[pair]["quote"]
    
    asset_after_sell = float(balance.get(asset, 0)) - vol_to_sell
    fiat_after_sell = float(balance.get(fiat, 0)) + (vol_to_sell * price)

    total_value_after = (asset_after_sell * price) + fiat_after_sell
    if total_value_after == 0: return True

    asset_allocation_after = (asset_after_sell * price) / total_value_after
    min_allocation = float(ASSET_MIN_ALLOCATION[pair])
    
    if asset_allocation_after < min_allocation:
        logging.warning(f"🛡️[BLOCKED] Sell {order_id} by inventory ratio: {asset_allocation_after:.2%} < min: {min_allocation:.0%}.",
                        to_telegram=True)
        return False
    
    return True