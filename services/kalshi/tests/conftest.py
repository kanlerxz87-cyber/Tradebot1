"""Every numeric fixture here is synthetic test data, not a Kalshi market observation."""

import pytest

from services.kalshi.kalshi_demo.config import Settings
from services.kalshi.kalshi_demo.domain import normalize_market
from services.kalshi.kalshi_demo.store import Store


@pytest.fixture
def settings():
    return Settings(db_path=":memory:", read_interval_seconds=0)


@pytest.fixture
def store():
    state = Store(":memory:")
    yield state
    state.close()


@pytest.fixture
def raw_market():
    return {
        "ticker": "SYNTHETIC-TEST-MARKET", "event_ticker": "SYNTHETIC-EVENT",
        "title": "Synthetic fixture — not a real market", "market_type": "binary",
        "status": "active", "last_price_dollars": "0.5000",
        "yes_bid_dollars": "0.4800", "yes_ask_dollars": "0.5200",
        "no_bid_dollars": "0.4800", "no_ask_dollars": "0.5200",
        "volume_fp": "1000.00", "volume_24h_fp": "100.00", "open_interest_fp": "250.00",
        "notional_value_dollars": "1.0000", "settlement_bounds_type": "default",
        "price_ranges": [{"start": "0.0100", "end": "0.9900", "step": "0.0100"}],
    }


@pytest.fixture
def market(raw_market):
    return normalize_market(raw_market, "crypto", 1_800_000_000_000)
