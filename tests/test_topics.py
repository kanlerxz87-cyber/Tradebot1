from kalshi_trader import topics
from tests.fixtures import (
    CRYPTO_SERIES,
    CULTURE_SERIES,
    ELECTION_SERIES,
    GAS_SERIES,
    GOLF_SERIES,
)


def test_gas_series_known_ticker():
    assert topics.topic_for_series(GAS_SERIES) == "gas"


def test_golf_tag_wins_over_sports_category():
    assert topics.topic_for_series(GOLF_SERIES) == "golf"


def test_category_mapping():
    assert topics.topic_for_series(CRYPTO_SERIES) == "crypto"
    assert topics.topic_for_series(ELECTION_SERIES) == "elections"
    assert topics.topic_for_series(CULTURE_SERIES) == "culture"


def test_unrelated_series_not_classified():
    sports = {"ticker": "KXNFLGAME", "title": "NFL game", "category": "Sports", "categories": ["Sports"], "tags": ["Football"]}
    assert topics.topic_for_series(sports) is None


def test_gas_keyword_fallback_for_unknown_series():
    series = {"ticker": "SOMEGAS", "title": "Average gas price in California", "category": "Economics", "categories": ["Economics"], "tags": []}
    assert topics.topic_for_series(series) == "gas"


def test_market_classification_uses_series_meta():
    meta = {"KXAAAGASM": topics.compact_series(GAS_SERIES, "gas")}
    market = {"title": "Will average gas prices be above $3.45?"}
    assert topics.topic_for_market(market, meta, "KXAAAGASM") == "gas"


def test_no_culture_category_exists_officially():
    # The taxonomy has no "Culture" category; the mapping must not invent one.
    labels = {c for topic in topics.TOPICS for c in topic.categories}
    assert "Culture" not in labels
    assert "Entertainment" in labels
