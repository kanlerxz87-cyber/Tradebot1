"""
Configuration for the Kalshi demo data collector.

Base URLs are copied verbatim from docs.kalshi.com (confirmed in
docs/API_VERIFICATION.md section A). The "recommended" demo host is used by
default; the alternate host is kept here for reference/fallback.
"""
import os

# --- Kalshi demo API (public, unauthenticated market-data endpoints only) ---
REST_BASE_PRIMARY = "https://external-api.demo.kalshi.co/trade-api/v2"
REST_BASE_FALLBACK = "https://demo-api.kalshi.co/trade-api/v2"
WS_BASE_PRIMARY = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
WS_BASE_FALLBACK = "wss://demo-api.kalshi.co/trade-api/ws/v2"

KALSHI_MARKET_URL_TEMPLATE = "https://kalshi.com/markets/{series_ticker_lower}"

# --- Topics the user asked us to track, and how we recognize them ---
# `category_match`: Kalshi's own `category` string on /series and /events
#   (confirmed field exists: docs.kalshi.com quick-start guide). Matched
#   case-insensitively, substring match, since Kalshi has used variants like
#   "Economics", "Climate and Weather", "Entertainment" etc.
# `keyword_fallback`: used only when a market's category is missing/ambiguous,
#   matched against the market/event title and subtitle. Kept intentionally
#   narrow to avoid mis-bucketing unrelated markets.
TOPICS = {
    "gas_prices": {
        "label": "Gas Prices",
        "category_match": ["economics", "commodities", "energy"],
        "keyword_fallback": ["gas price", "gasoline", "aaa national average", "aaagas"],
        "series_hint": ["KXAAAGASM", "KXAAAGASMAX", "KXAAAGASMIN"],
    },
    "elections": {
        "label": "Elections",
        "category_match": ["elections", "politics"],
        "keyword_fallback": ["election", "senate", "governor", "president", "referendum"],
        "series_hint": [],
    },
    "culture": {
        "label": "Culture",
        "category_match": ["entertainment", "culture", "mentions", "social"],
        "keyword_fallback": ["award", "box office", "reality tv", "music", "movie", "celebrity"],
        "series_hint": [],
    },
    "crypto": {
        "label": "Crypto",
        "category_match": ["crypto"],
        "keyword_fallback": ["bitcoin", "ethereum", "btc", "eth", "solana", "xrp"],
        "series_hint": ["KXBTC", "KXETH"],
    },
    "golf": {
        "label": "Golf",
        "category_match": ["sports"],
        "keyword_fallback": ["golf", "pga", "masters", "open championship", "ryder cup"],
        "series_hint": ["KXPGATOUR", "KXMASTERS", "KXPGA", "KXUSOPEN", "KXTHEOPEN"],
    },
}

# A market must mention one of these sport keywords in addition to category
# "Sports" to be bucketed as golf (category alone is too broad for Sports).
SPORTS_CATEGORY_REQUIRES_KEYWORD = {"golf"}

# --- Alerting ---
PRICE_SWING_ALERT_THRESHOLD_DOLLARS = 0.10  # per task spec, >= $0.10 move
MAX_ALERTS_KEPT = 500

# --- Paper trading / portfolio ---
STARTING_PAPER_BALANCE_USD = 10_000.00
PAPER_CONTRACTS_PER_TRADE = 10
MAX_TRADES_KEPT = 1000
MAX_EQUITY_POINTS_KEPT = 2000

# --- Collection scope / politeness ---
MARKETS_PER_TOPIC_LIMIT = 40          # top-N by volume kept per topic per run
HTTP_TIMEOUT_SECONDS = 12
HTTP_MIN_INTERVAL_SECONDS = 1.0       # conservative throttle, see API_VERIFICATION.md E2
MAX_RETRIES = 2

# --- Paths (relative to repo root) ---
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "docs", "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
STATE_DIR = os.path.join(REPO_ROOT, "scripts", "_state")
