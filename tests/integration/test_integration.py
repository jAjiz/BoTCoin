import os
import pytest

import core.database as database
from exchange import kraken

# ============================================================================
# Kraken API Integration Tests
# ============================================================================

def _live_integration_enabled() -> bool:
    return os.getenv("RUN_LIVE_INTEGRATION", "false").lower() == "true"


@pytest.fixture(scope="session")
def kraken_live_enabled() -> bool:
    has_credentials = bool(os.getenv("KRAKEN_API_KEY")) and bool(os.getenv("KRAKEN_API_SECRET"))
    return _live_integration_enabled() and has_credentials


@pytest.mark.integration
def test_get_balance_live(kraken_live_enabled: bool) -> None:
    if not kraken_live_enabled:
        pytest.skip("Live integration disabled. Set RUN_LIVE_INTEGRATION=true with Kraken credentials.")

    balance = kraken.get_balance()

    assert balance is not None
    assert isinstance(balance, dict)

# ============================================================================
# Database Integration Tests
# ============================================================================

def _db_integration_enabled() -> bool:
    return os.getenv("RUN_DB_INTEGRATION", "false").lower() == "true"


@pytest.mark.integration
def test_get_bot_paused_returns_not_none() -> None:
    if not _db_integration_enabled():
        pytest.skip("PostgreSQL DAL integration disabled. Set RUN_DB_INTEGRATION=true to run this test.")
    assert database.get_bot_paused() is not None
