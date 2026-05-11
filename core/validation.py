import logging
from typing import Any

from core.config import (
    ALLOW_NO_AUTH,
    API_SECRET_TOKEN,
    ASSET_ALLOCATION,
    ATR_DESV_LIMIT,
    ATR_PERIOD,
    CANDLE_TIMEFRAME,
    KRAKEN_API_KEY,
    KRAKEN_API_SECRET,
    PAIRS,
    PARAM_SESSIONS,
    SLEEPING_INTERVAL,
    STOP_PCT_DEFAULT,
    STOP_PERCENTILES,
    TELEGRAM_ENABLED,
    TELEGRAM_POLL_INTERVAL,
    TELEGRAM_TOKEN,
    TELEGRAM_USER_ID,
    TRADING_PARAMS,
    VOLATILITY_LEVELS,
)
from exchange.kraken import build_pairs_map


def validate_common_params(errors: list[str]) -> None:
    # Kraken API credentials
    if not KRAKEN_API_KEY:
        errors.append("KRAKEN_API_KEY is missing")
    if not KRAKEN_API_SECRET:
        errors.append("KRAKEN_API_SECRET is missing")

    # Telegram Bot configuration (only when Telegram is enabled)
    if TELEGRAM_ENABLED:
        if not TELEGRAM_TOKEN:
            errors.append("TELEGRAM_TOKEN is missing")
        if not TELEGRAM_USER_ID or not TELEGRAM_USER_ID.isdigit() or int(TELEGRAM_USER_ID) <= 0:
            errors.append("TELEGRAM_USER_ID must be a positive integer")
        if TELEGRAM_POLL_INTERVAL < 0:
            errors.append("TELEGRAM_POLL_INTERVAL must be a non-negative integer")

    # API auth: refuse to start with no token unless explicit opt-in.
    if not API_SECRET_TOKEN and not ALLOW_NO_AUTH:
        errors.append(
            "API_SECRET_TOKEN is missing. Set it, or set ALLOW_NO_AUTH=true "
            "to explicitly run the API without authentication."
        )

    # Bot settings
    if SLEEPING_INTERVAL <= 0:
        errors.append("SLEEPING_INTERVAL must be a positive integer")
    if PARAM_SESSIONS <= 0:
        errors.append("PARAM_SESSIONS must be a positive integer")
    if CANDLE_TIMEFRAME <= 0:
        errors.append("CANDLE_TIMEFRAME must be a positive integer")
    if ATR_PERIOD <= 0:
        errors.append("ATR_PERIOD must be a positive integer")
    if ATR_DESV_LIMIT < 0:
        errors.append("ATR_DESV_LIMIT must be a non-negative float")

    # Pairs configuration
    if not PAIRS or not any(PAIRS.keys()):
        errors.append("PAIRS is missing or empty")


def _parse_float(
    value: Any,
    name: str,
    errors: list[str],
    *,
    min_val: float | None = None,
    max_val: float | None = None,
) -> float | None:
    """Parse value to float. Empty/None returns None."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        errors.append(f"{name} must be a float (got {value!r})")
        return None
    if min_val is not None and f < min_val:
        errors.append(f"{name} must be >= {min_val} (got {f})")
        return None
    if max_val is not None and f > max_val:
        errors.append(f"{name} must be <= {max_val} (got {f})")
        return None
    return f


def validate_pair_params(errors: list[str]) -> None:
    """Validate and normalize per-pair trading parameters.

    Rules:
    - K_ACT: float, or unset/empty (treated as None — fall through to K_STOP+MIN_MARGIN path).
    - MIN_MARGIN: only required (must be float) when K_ACT is None.
    - TARGET_PCT: float in [0, 100]; the sum across pairs must also be <= 100.
    - HODL_PCT: float in [0, 100].
    - STOP_PCT_<level>: float in [0, 1] or unset (default 0.90).

    On success, writes normalized typed values back into TRADING_PARAMS,
    ASSET_ALLOCATION and STOP_PERCENTILES so consumers always see floats/None.
    """
    total_target = 0.0
    for pair in PAIRS:
        for side in ("sell", "buy"):
            side_label = side.upper()

            k_act = _parse_float(
                TRADING_PARAMS[pair][side]["K_ACT"],
                f"{pair}_{side_label}_K_ACT",
                errors,
            )
            TRADING_PARAMS[pair][side]["K_ACT"] = k_act

            min_margin_raw = TRADING_PARAMS[pair][side]["MIN_MARGIN"]
            if k_act is None:
                min_margin = _parse_float(min_margin_raw, f"{pair}_{side_label}_MIN_MARGIN", errors)
                if min_margin is None and min_margin_raw in (None, ""):
                    errors.append(f"{pair}_{side_label}_MIN_MARGIN is required when K_ACT is not set")
                TRADING_PARAMS[pair][side]["MIN_MARGIN"] = min_margin
            else:
                # K_ACT defined — MIN_MARGIN unused. Normalize to a float if parseable, else 0.
                parsed = _parse_float(min_margin_raw, f"{pair}_{side_label}_MIN_MARGIN", [])
                TRADING_PARAMS[pair][side]["MIN_MARGIN"] = parsed if parsed is not None else 0.0

        target_pct = _parse_float(
            ASSET_ALLOCATION[pair]["TARGET_PCT"],
            f"{pair}_TARGET_PCT",
            errors,
            min_val=0,
            max_val=100,
        )
        ASSET_ALLOCATION[pair]["TARGET_PCT"] = target_pct if target_pct is not None else 0.0
        total_target += ASSET_ALLOCATION[pair]["TARGET_PCT"]

        hodl_pct = _parse_float(
            ASSET_ALLOCATION[pair]["HODL_PCT"],
            f"{pair}_HODL_PCT",
            errors,
            min_val=0,
            max_val=100,
        )
        ASSET_ALLOCATION[pair]["HODL_PCT"] = hodl_pct if hodl_pct is not None else 0.0

        for level in VOLATILITY_LEVELS:
            parsed = _parse_float(
                STOP_PERCENTILES[pair][level],
                f"{pair}_STOP_PCT_{level}",
                errors,
                min_val=0,
                max_val=1,
            )
            STOP_PERCENTILES[pair][level] = parsed if parsed is not None else STOP_PCT_DEFAULT

    if total_target > 100:
        errors.append(f"Sum of TARGET_PCT across all pairs must not exceed 100 (got {total_target:g})")


def build_and_validate_pairs(errors: list[str]) -> None:
    try:
        build_pairs_map(PAIRS)
        if not any(PAIRS.values()):
            errors.append("No valid pairs found")
    except Exception as e:
        errors.append(f"Failed to fetch pairs: {e!s}")


def log_configuration_summary() -> None:
    logging.info("=" * 60)
    logging.info("✅ CONFIGURATION VALIDATED SUCCESSFULLY")
    logging.info("=" * 60)
    logging.info(f"Telegram polling interval: {TELEGRAM_POLL_INTERVAL}s")
    logging.info(f"Session interval: {SLEEPING_INTERVAL}s")
    logging.info(f"Parameter calculation sessions: {PARAM_SESSIONS}")
    logging.info(f"Candle timeframe: {CANDLE_TIMEFRAME}min")
    logging.info(f"ATR period: {ATR_PERIOD} candles")
    logging.info(f"Pairs to trade: {', '.join(PAIRS.keys())}")
    logging.info("-" * 60 + "\n")


def validate_config() -> bool:
    errors = []

    # Common validations
    validate_common_params(errors)

    if not errors:
        build_and_validate_pairs(errors)
        validate_pair_params(errors)

    # Log all errors at the end
    if errors:
        logging.error("=" * 60)
        logging.error("❌ CONFIGURATION VALIDATION FAILED")
        logging.error("=" * 60)
        for error in errors:
            logging.error(f"  - {error}")
        logging.error("=" * 60)
        return False

    # If all validations passed, log configuration summary
    log_configuration_summary()
    return True
