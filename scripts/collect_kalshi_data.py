#!/usr/bin/env python3
"""
Main collector entry point. Designed to run on a schedule via
.github/workflows/collect-kalshi-data.yml, where GitHub's runners have full
internet access (unlike the coding sandbox that built this — see
docs/EXECUTIVE_SUMMARY.md section 3).

What it does, in order:
  1. Pull open markets from the Kalshi DEMO API (public endpoints only).
  2. Categorize each into one of the five tracked topics (or uncategorized).
  3. Detect >= $0.10 price swings vs. the previous run and log alerts
     (all-events feed + a "high ROI" filtered feed).
  4. Detect newly resolved markets and record their Yes/No outcome.
  5. Run the paper-trading strategy engine and settle any trades whose
     market has resolved.
  6. Recompute the simulated portfolio and append an equity-curve point.
  7. Append a price-history point per tracked ticker for the charts.
  8. Write docs/data/meta.json documenting exactly what happened this run.

Every write is best-effort per topic: a failure fetching one topic does not
block the others, and a total network failure leaves existing committed data
untouched (never overwrites good data with an error).
"""
import sys
import traceback

from . import config
from . import categorize as cat
from . import alerts as alerts_mod
from . import strategies as strat_mod
from . import portfolio as pf_mod
from .io_utils import read_json, write_json, utcnow_iso, ensure_dir
from .kalshi_client import KalshiClient, KalshiAPIError

import os


def market_url(market):
    series = (market.get("event_ticker") or market.get("ticker") or "").split("-")[0]
    return f"https://kalshi.com/markets/{series.lower()}"


def normalize_market(market, topic_key, event_category):
    price = alerts_mod.market_mid_price(market)
    liquidity = None
    volume = market.get("volume")
    return {
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "title": market.get("title") or market.get("yes_sub_title"),
        "topic": topic_key,
        "category_raw": event_category,
        "status": market.get("status"),
        "result": market.get("result") if market.get("result") in ("yes", "no") else None,
        "price": price,
        "yes_bid": market.get("yes_bid_dollars") or market.get("yes_bid"),
        "yes_ask": market.get("yes_ask_dollars") or market.get("yes_ask"),
        "volume": volume,
        "open_interest": market.get("open_interest"),
        "liquidity_contracts": liquidity,
        "close_time": market.get("close_time"),
        "kalshi_url": market_url(market),
        "source_endpoint": f"{config.REST_BASE_PRIMARY}/markets/{market.get('ticker')}",
    }


def fetch_all_open_and_recent_markets(client: KalshiClient):
    """Fetch open markets, plus a page of recently-settled markets so we can
    detect resolutions. Returns list of raw market dicts plus a run-level
    error list (one entry per failed call, run continues regardless)."""
    raw_markets = []
    errors = []
    for status in ("open", "settled"):
        try:
            count = 0
            for m in client.iter_all_markets(status=status, max_pages=10):
                raw_markets.append(m)
                count += 1
                if count >= 2000:
                    break
        except KalshiAPIError as e:
            errors.append({"stage": f"list_markets(status={status})", "error": str(e)})
    return raw_markets, errors


def event_category_lookup(client: KalshiClient, event_tickers):
    """Best-effort: fetch /events for distinct event tickers to get the
    authoritative `category` field. Falls back silently (returns {}) on
    failure; categorize.py then relies on market-level fields/keywords."""
    lookup = {}
    try:
        data, _url = client.list_events(status=None, limit=200)
        for ev in data.get("events", []):
            t = ev.get("event_ticker")
            if t:
                lookup[t] = ev.get("category")
    except KalshiAPIError:
        pass
    return lookup


def run():
    ensure_dir(config.DATA_DIR)
    ensure_dir(config.HISTORY_DIR)
    ensure_dir(config.STATE_DIR)

    run_errors = []
    client = KalshiClient()

    try:
        raw_markets, fetch_errors = fetch_all_open_and_recent_markets(client)
        run_errors.extend(fetch_errors)
    except Exception as e:  # noqa: BLE001 - top-level safety net for a scheduled job
        raw_markets = []
        run_errors.append({"stage": "fetch_all_open_and_recent_markets", "error": repr(e)})

    event_tickers = sorted({m.get("event_ticker") for m in raw_markets if m.get("event_ticker")})
    category_lookup = event_category_lookup(client, event_tickers) if raw_markets else {}

    by_topic = {k: [] for k in config.TOPICS}
    uncategorized = []

    for m in raw_markets:
        ev_cat = category_lookup.get(m.get("event_ticker"))
        topic_key = cat.categorize_market(m, event_category=ev_cat)
        if topic_key is None:
            uncategorized.append({
                "ticker": m.get("ticker"),
                "title": m.get("title"),
                "event_ticker": m.get("event_ticker"),
                "category_raw": ev_cat,
                "kalshi_url": market_url(m),
            })
            continue
        normalized = normalize_market(m, topic_key, ev_cat)
        by_topic[topic_key].append(normalized)

    # Keep only the top-N by volume per topic (our "highest dollar amount"
    # proxy, since Kalshi's public endpoints expose volume/open interest, not
    # a direct notional-dollar-exposure field).
    for topic_key in by_topic:
        def _vol(x):
            try:
                return float(x.get("volume") or 0)
            except (TypeError, ValueError):
                return 0.0
        by_topic[topic_key].sort(key=_vol, reverse=True)
        by_topic[topic_key] = by_topic[topic_key][: config.MARKETS_PER_TOPIC_LIMIT]

    # --- Alerts: compare to previous run's prices ---
    state_path = os.path.join(config.STATE_DIR, "last_prices.json")
    previous_prices = read_json(state_path, {})
    all_alerts_file = os.path.join(config.DATA_DIR, "alerts_all.json")
    highroi_alerts_file = os.path.join(config.DATA_DIR, "alerts_highroi.json")
    existing_all = read_json(all_alerts_file, {"alerts": []}).get("alerts", [])
    existing_highroi = read_json(highroi_alerts_file, {"alerts": []}).get("alerts", [])

    new_prices_state = {}
    market_by_ticker = {}
    all_markets_flat = []
    new_alerts = []

    for topic_key, markets in by_topic.items():
        label = config.TOPICS[topic_key]["label"]
        prev_for_topic = previous_prices.get(topic_key, {})
        topic_alerts, updated_prices = alerts_mod.detect_swings(topic_key, label, markets, prev_for_topic)
        new_prices_state[topic_key] = updated_prices
        new_alerts.extend(topic_alerts)
        for m in markets:
            market_by_ticker[m["ticker"]] = m
            all_markets_flat.append(m)

    combined_all = (new_alerts + existing_all)[: config.MAX_ALERTS_KEPT]
    highroi_new = []
    for a in new_alerts:
        score = alerts_mod.high_roi_score(a, market_by_ticker)
        if score >= alerts_mod.HIGH_ROI_MIN_SCORE:
            a2 = dict(a)
            a2["high_roi_score"] = score
            highroi_new.append(a2)
    combined_highroi = (highroi_new + existing_highroi)[: config.MAX_ALERTS_KEPT]

    write_json(state_path, new_prices_state)
    write_json(all_alerts_file, {"generated_at": utcnow_iso(), "threshold_usd": config.PRICE_SWING_ALERT_THRESHOLD_DOLLARS, "alerts": combined_all})
    write_json(highroi_alerts_file, {
        "generated_at": utcnow_iso(),
        "min_score": alerts_mod.HIGH_ROI_MIN_SCORE,
        "scoring_method": "abs(delta) * log10(1+volume) * (0.5 + distance_from_50c*2)",
        "alerts": combined_highroi,
    })

    # --- Resolved markets ---
    resolved_file = os.path.join(config.DATA_DIR, "resolved.json")
    existing_resolved = read_json(resolved_file, {"resolved": []})
    existing_resolved_tickers = {r["ticker"] for r in existing_resolved["resolved"]}
    newly_resolved = []
    for m in all_markets_flat:
        if m.get("result") in ("yes", "no") and m["ticker"] not in existing_resolved_tickers:
            newly_resolved.append({
                "ticker": m["ticker"],
                "title": m["title"],
                "topic": m["topic"],
                "result": m["result"],
                "resolved_detected_at": utcnow_iso(),
                "close_time": m.get("close_time"),
                "kalshi_url": m["kalshi_url"],
                "source_endpoint": m["source_endpoint"],
            })
    existing_resolved["resolved"] = (newly_resolved + existing_resolved["resolved"])[:2000]
    existing_resolved["generated_at"] = utcnow_iso()
    write_json(resolved_file, existing_resolved)
    resolved_by_ticker = {r["ticker"]: r for r in existing_resolved["resolved"]}

    # --- Paper trading strategies ---
    trades_file = os.path.join(config.DATA_DIR, "simulated_trades.json")
    existing_trades = read_json(trades_file, {"trades": []})["trades"]

    new_trades = []
    new_trades.extend(strat_mod.generate_momentum_trades(new_alerts, market_by_ticker))
    new_trades.extend(strat_mod.generate_mean_reversion_trades(new_alerts, market_by_ticker))
    new_trades.extend(strat_mod.generate_high_liquidity_value_trades(all_markets_flat))

    already_open_tickers_by_strategy = {
        (t["ticker"], t["strategy"]) for t in existing_trades if t["status"] == "open"
    }
    deduped_new_trades = [
        t for t in new_trades if (t["ticker"], t["strategy"]) not in already_open_tickers_by_strategy
    ]

    all_trades = deduped_new_trades + existing_trades
    all_trades = [strat_mod.settle_trade_if_resolved(t, resolved_by_ticker) for t in all_trades]
    all_trades = all_trades[: config.MAX_TRADES_KEPT]
    write_json(trades_file, {"generated_at": utcnow_iso(), "trades": all_trades})

    # --- Portfolio ---
    price_by_ticker = {t: m.get("price") for t, m in market_by_ticker.items()}
    portfolio = pf_mod.recompute_portfolio(all_trades, price_by_ticker)
    write_json(os.path.join(config.DATA_DIR, "portfolio.json"), portfolio)

    history_file = os.path.join(config.DATA_DIR, "portfolio_history.json")
    pf_history = read_json(history_file, {"points": []})
    pf_history["points"].append({"timestamp": utcnow_iso(), "equity_usd": portfolio["equity_usd"]})
    pf_history["points"] = pf_history["points"][-config.MAX_EQUITY_POINTS_KEPT:]
    write_json(history_file, pf_history)

    # --- Per-topic market snapshot + per-ticker price history for charts ---
    for topic_key, markets in by_topic.items():
        write_json(os.path.join(config.DATA_DIR, f"markets_{topic_key}.json"), {
            "topic": topic_key,
            "label": config.TOPICS[topic_key]["label"],
            "generated_at": utcnow_iso(),
            "status": "ok" if not run_errors else "partial_error",
            "source_endpoint": f"{config.REST_BASE_PRIMARY}/markets",
            "markets": markets,
        })

        hist_path = os.path.join(config.HISTORY_DIR, f"{topic_key}.json")
        hist = read_json(hist_path, {"topic": topic_key, "series": {}})
        for m in markets:
            if m.get("price") is None:
                continue
            series = hist["series"].setdefault(m["ticker"], [])
            series.append({"ts": utcnow_iso(), "price": m["price"], "volume": m.get("volume")})
            hist["series"][m["ticker"]] = series[-2000:]
        hist["generated_at"] = utcnow_iso()
        write_json(hist_path, hist)

    write_json(os.path.join(config.DATA_DIR, "uncategorized.json"), {
        "generated_at": utcnow_iso(),
        "note": "Markets the collector could not confidently place into one of the five tracked topics. See docs/FLAGGED_FOR_REVIEW.md item 5.",
        "markets": uncategorized[:500],
    })

    status = "ok" if not run_errors else ("error" if not raw_markets else "partial_error")
    write_json(os.path.join(config.DATA_DIR, "meta.json"), {
        "last_run": utcnow_iso(),
        "status": status,
        "topics": list(config.TOPICS.keys()),
        "markets_fetched": len(raw_markets),
        "markets_categorized": sum(len(v) for v in by_topic.values()),
        "markets_uncategorized": len(uncategorized),
        "new_alerts_this_run": len(new_alerts),
        "errors": run_errors,
        "rest_base_used": config.REST_BASE_PRIMARY,
    })

    if run_errors:
        print("Collector finished with errors:", run_errors, file=sys.stderr)
    print(f"Collector run complete. status={status} markets_fetched={len(raw_markets)}")
    return 0 if status != "error" else 1


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
