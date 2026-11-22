#!/usr/bin/env python3
"""
Writes the initial, intentionally-empty data files shipped in the PR, before
the first scheduled GitHub Actions collection run has happened. Run once at
repo-build time (not on a schedule). See docs/EXECUTIVE_SUMMARY.md section 3
and docs/FLAGGED_FOR_REVIEW.md item 1 for why these start empty instead of
containing placeholder/sample numbers.
"""
import os
from . import config
from .io_utils import write_json, utcnow_iso, ensure_dir


def main():
    ensure_dir(config.DATA_DIR)
    ensure_dir(config.HISTORY_DIR)

    now = utcnow_iso()
    status = "awaiting_first_collection_run"

    for topic_key, cfg in config.TOPICS.items():
        write_json(os.path.join(config.DATA_DIR, f"markets_{topic_key}.json"), {
            "topic": topic_key,
            "label": cfg["label"],
            "generated_at": now,
            "status": status,
            "source_endpoint": f"{config.REST_BASE_PRIMARY}/markets",
            "markets": [],
        })
        write_json(os.path.join(config.HISTORY_DIR, f"{topic_key}.json"), {
            "topic": topic_key, "generated_at": now, "series": {},
        })

    write_json(os.path.join(config.DATA_DIR, "alerts_all.json"), {
        "generated_at": now, "status": status,
        "threshold_usd": config.PRICE_SWING_ALERT_THRESHOLD_DOLLARS, "alerts": [],
    })
    write_json(os.path.join(config.DATA_DIR, "alerts_highroi.json"), {
        "generated_at": now, "status": status, "min_score": None,
        "scoring_method": "abs(delta) * log10(1+volume) * (0.5 + distance_from_50c*2)",
        "alerts": [],
    })
    write_json(os.path.join(config.DATA_DIR, "resolved.json"), {
        "generated_at": now, "status": status, "resolved": [],
    })
    write_json(os.path.join(config.DATA_DIR, "simulated_trades.json"), {
        "generated_at": now, "status": status, "trades": [],
    })
    write_json(os.path.join(config.DATA_DIR, "uncategorized.json"), {
        "generated_at": now, "status": status, "note": "No data yet.", "markets": [],
    })

    from . import portfolio as pf_mod
    p = pf_mod.new_portfolio()
    p["generated_at"] = now
    p["status"] = status
    write_json(os.path.join(config.DATA_DIR, "portfolio.json"), p)
    write_json(os.path.join(config.DATA_DIR, "portfolio_history.json"), {
        "generated_at": now, "status": status, "points": [],
    })

    write_json(os.path.join(config.DATA_DIR, "meta.json"), {
        "last_run": None,
        "status": status,
        "topics": list(config.TOPICS.keys()),
        "markets_fetched": 0,
        "markets_categorized": 0,
        "markets_uncategorized": 0,
        "new_alerts_this_run": 0,
        "errors": [],
        "rest_base_used": config.REST_BASE_PRIMARY,
        "note": "Seeded empty by scripts/seed_empty_data.py at repo build time. Will be overwritten by the first successful run of .github/workflows/collect-kalshi-data.yml.",
    })
    print("Seeded empty data files under", config.DATA_DIR)


if __name__ == "__main__":
    main()
