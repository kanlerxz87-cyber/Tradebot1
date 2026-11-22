"""Command line entry points.

    python -m kalshi_trader.cli collect        # one full cycle, writes docs/desk/data/*.json
    python -m kalshi_trader.cli serve          # local live server (API + site + WebSocket)
    python -m kalshi_trader.cli verify         # offline integrity checks of the published data
    python -m kalshi_trader.cli demo-status    # whether demo credentials are configured
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import store
from .collector import run_cycle
from .config import Settings, load_settings
from .kalshi_demo import DemoAccount


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def cmd_collect(args: argparse.Namespace) -> int:
    settings: Settings = load_settings()
    latest = run_cycle(settings, samples=args.samples, write=not args.no_write)
    print(
        json.dumps(
            {
                "generated_at": latest["generated_at"],
                "markets": latest["market_count"],
                "events": latest["event_count"],
                "alerts": len(latest["alerts"]),
                "picks": len(latest["picks"]),
                "equity": latest["paper"]["equity"],
                "errors": latest["errors"],
            },
            indent=2,
        )
    )
    if latest["market_count"] == 0:
        print("WARNING: no markets were collected — check network access and KALSHI_DATA_ENV", file=sys.stderr)
        return 2
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed: pip install -r requirements.txt", file=sys.stderr)
        return 1
    from .server import create_app

    settings = load_settings()
    app = create_app(settings, interval=args.interval, live=not args.no_live)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    settings = load_settings()
    problems = 0
    data_dir = settings.data_dir
    required = ["latest.json", "alerts.json", "history.json", "meta.json", "paper.json", "series.json"]
    for name in required:
        path = data_dir / name
        if not path.exists():
            print(f"MISSING  {path.relative_to(settings.repo_root)}")
            problems += 1
            continue
        payload = store.read_json(path)
        if payload is None:
            print(f"INVALID  {path.relative_to(settings.repo_root)} (not JSON)")
            problems += 1
        else:
            print(f"ok       {path.relative_to(settings.repo_root)}  ({store.human_bytes(path)})")

    latest = store.read_json(data_dir / "latest.json", {}) or {}
    for topic in ("gas", "elections", "culture", "crypto", "golf"):
        block = (latest.get("topics") or {}).get(topic)
        if not block:
            print(f"WARNING  topic '{topic}' missing from latest.json")
            problems += 1
            continue
        for market in block.get("markets", []):
            if not market.get("api_url") or not market.get("series_page_url"):
                print(f"MISSING SOURCE LINK: {market.get('ticker')}")
                problems += 1
    for item in (latest.get("resolved") or [])[:50]:
        if not item.get("source"):
            print(f"MISSING RESOLUTION SOURCE: {item.get('ticker')}")
            problems += 1

    print(f"\n{'OK' if problems == 0 else f'{problems} problem(s)'}")
    return 0 if problems == 0 else 1


def cmd_demo_status(_: argparse.Namespace) -> int:
    settings = load_settings()
    account = DemoAccount(settings)
    print(json.dumps(account.status(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kalshi_trader", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="run one collection cycle")
    collect.add_argument("--samples", type=int, default=None)
    collect.add_argument("--no-write", action="store_true")
    collect.set_defaults(func=cmd_collect)

    serve = sub.add_parser("serve", help="run the local live server")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--interval", type=int, default=30, help="seconds between collection cycles")
    serve.add_argument("--no-live", action="store_true", help="serve the last snapshot without collecting")
    serve.set_defaults(func=cmd_serve)

    verify = sub.add_parser("verify", help="offline integrity checks of published data")
    verify.set_defaults(func=cmd_verify)

    demo = sub.add_parser("demo-status", help="report demo credential status")
    demo.set_defaults(func=cmd_demo_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
