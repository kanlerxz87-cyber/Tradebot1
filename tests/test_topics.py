"""Topic mapping against Kalshi's published categories and tags.

The category list and the Sports/Golf tag are taken from the live public
endpoint, verified 2026-11-22:
https://external-api.kalshi.com/trade-api/v2/search/tags_by_categories

There is no "Gas" or "Culture" category in that payload, which is why those two
topics are built from tags/keywords and say so in their `basis` string.
"""

from app.topics import TOPIC_META, TOPIC_ORDER, match_topic


def test_only_the_five_required_topics_are_tracked():
    assert TOPIC_ORDER == ("gas", "elections", "culture", "crypto", "golf")
    assert set(TOPIC_META) == set(TOPIC_ORDER)


def test_elections_category_maps_directly():
    m = match_topic(category="Elections", title="Who will be the next Secretary General of NATO?")
    assert m.topic == "elections" and m.confidence == "category"


def test_crypto_category_maps_directly():
    m = match_topic(category="Crypto", title="What will BTC's price be end of Q2 2026?")
    assert m.topic == "crypto" and m.confidence == "category"


def test_golf_needs_sports_plus_the_golf_tag():
    m = match_topic(category="Sports", tags=["Golf"], title="Travelers Championship Winner")
    assert m.topic == "golf" and m.confidence == "tag"


def test_golf_series_ticker_is_recognised():
    m = match_topic(category="Sports", series_ticker="KXPGATOUR",
                    title="PGA Championship Winner")
    assert m.topic == "golf"


def test_other_sports_are_not_golf():
    m = match_topic(category="Sports", tags=["Basketball"], title="NBA Championship Winner")
    assert m.topic == "other"


def test_culture_uses_entertainment_and_mentions_categories():
    assert match_topic(category="Entertainment", title="Oscars Best Picture").topic == "culture"
    assert match_topic(category="Mentions", title="How many times will X be mentioned").topic == "culture"


def test_gas_uses_the_official_oil_and_gas_tag():
    m = match_topic(category="Commodities", tags=["Oil & Gas"], title="WTI crude settlement")
    assert m.topic == "gas" and m.confidence == "tag"


def test_gas_series_ticker_and_keywords():
    assert match_topic(category="Commodities", series_ticker="KXAAAGASM",
                        title="National average gas price").topic == "gas"
    assert match_topic(category="Economics", title="Will the national average gas price exceed $4?").topic == "gas"


def test_golf_keyword_does_not_capture_unrelated_titles():
    m = match_topic(category="Financials", title="Mastercard earnings beat")
    assert m.topic == "other"


def test_unmatched_market_is_reported_not_guessed():
    m = match_topic(category="Politics", title="Will Congress pass the budget?")
    assert m.topic == "other"
    assert m.confidence == "none"
    assert not m.matched
