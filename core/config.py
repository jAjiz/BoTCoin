import os
from dotenv import load_dotenv

load_dotenv()

# KRAKEN API Credentials
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET")

# Telegram Bot Credentials
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID"))
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", 20))

# Bot Settings
MODE = os.getenv("MODE")  # Options: "onek", "dualk"
SLEEPING_INTERVAL = int(os.getenv("SLEEPING_INTERVAL", 60))  # 1 minute
ATR_DATA_DAYS = int(os.getenv("ATR_DATA_DAYS", 60)) # 60 days

# Pairs names map and info
PAIRS = {pair: {} for pair in os.getenv("PAIRS", "").split(",")}

# Trading params - defaults (can be overridden per pair)
DEFAULT_SELL_K_ACT = float(os.getenv("SELL_K_ACT", -1))
DEFAULT_SELL_K_STOP = float(os.getenv("SELL_K_STOP", -1))
DEFAULT_SELL_MIN_MARGIN = float(os.getenv("SELL_MIN_MARGIN", 0))

DEFAULT_BUY_K_ACT = float(os.getenv("BUY_K_ACT", -1))
DEFAULT_BUY_K_STOP = float(os.getenv("BUY_K_STOP", -1))
DEFAULT_BUY_MIN_MARGIN = float(os.getenv("BUY_MIN_MARGIN", 0))

def _build_trading_params():
    params = {}
    for pair in PAIRS.keys():
        sell_k_act = float(os.getenv(f"{pair}_SELL_K_ACT", DEFAULT_SELL_K_ACT))
        sell_k_stop = float(os.getenv(f"{pair}_SELL_K_STOP", DEFAULT_SELL_K_STOP))
        sell_min_margin = float(os.getenv(f"{pair}_SELL_MIN_MARGIN", DEFAULT_SELL_MIN_MARGIN))
        sell_atr_min = sell_min_margin / (sell_k_act - sell_k_stop) if (sell_k_act - sell_k_stop) > 0 else 0

        buy_k_act = float(os.getenv(f"{pair}_BUY_K_ACT", DEFAULT_BUY_K_ACT))
        buy_k_stop = float(os.getenv(f"{pair}_BUY_K_STOP", DEFAULT_BUY_K_STOP))
        buy_min_margin = float(os.getenv(f"{pair}_BUY_MIN_MARGIN", DEFAULT_BUY_MIN_MARGIN))
        buy_atr_min = buy_min_margin / (buy_k_act - buy_k_stop) if (buy_k_act - buy_k_stop) > 0 else 0

        params[pair] = {
            "sell": {
                "K_ACT": sell_k_act,
                "K_STOP": sell_k_stop,
                "MIN_MARGIN": sell_min_margin,
                "ATR_MIN": sell_atr_min
            },
            "buy": {
                "K_ACT": buy_k_act,
                "K_STOP": buy_k_stop,
                "MIN_MARGIN": buy_min_margin,
                "ATR_MIN": buy_atr_min
            }
        }

    return params

TRADING_PARAMS = _build_trading_params()

# Asset minimum allocation
def _build_asset_min_allocation():
    allocations = {}
    for pair in PAIRS.keys():
        allocations[pair] = float(os.getenv(f"{pair}_MIN_ALLOCATION", 0))
    return allocations

ASSET_MIN_ALLOCATION = _build_asset_min_allocation()