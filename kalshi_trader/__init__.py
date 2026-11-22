"""Kalshi Trader — live market dashboard, swing alerts and autonomous paper trading.

Public entry points
-------------------
``kalshi_trader.collector.run_cycle``  collect one snapshot, update alerts/paper book, write JSON.
``kalshi_trader.server``               local live server (REST + WebSocket + static site).
``kalshi_trader.cli``                  command line: ``collect``, ``serve``, ``verify``.
"""

__version__ = "1.0.0"
