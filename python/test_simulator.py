"""Unit tests with mocked data (no network). Run: python3 -m pytest python/ -q
or: python3 python/test_simulator.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulator import PaperPortfolio  # noqa: E402


def test_alert_threshold():
    pf = PaperPortfolio()
    assert pf.on_alert("T1", "Crypto", 0.05, 0.50, {"momentum": True}) is None
    pos = pf.on_alert("T1", "Crypto", 0.12, 0.62, {"momentum": True})
    assert pos is not None and pos.side == "yes" and pos.strategy == "momentum"


def test_meanrev_fades():
    pf = PaperPortfolio()
    pos = pf.on_alert("T1", "Golf", 0.15, 0.70, {"meanrev": True})
    assert pos.side == "no" and pos.strategy == "meanrev"


def test_settle_win_loss():
    pf = PaperPortfolio()
    pf.on_alert("T1", "Crypto", 0.12, 0.60, {"momentum": True})
    pf.settle("T1", "yes")
    assert pf.positions[0].pnl > 0
    pf2 = PaperPortfolio()
    pf2.on_alert("T2", "Golf", 0.12, 0.60, {"momentum": True})
    pf2.settle("T2", "no")
    assert pf2.positions[0].pnl < 0


def test_category_pnl():
    pf = PaperPortfolio()
    pf.on_alert("T1", "Crypto", 0.12, 0.60, {"momentum": True})
    pf.settle("T1", "yes")
    cats = pf.category_pnl()
    assert cats["Crypto x momentum"]["n"] == 1


if __name__ == "__main__":
    test_alert_threshold(); test_meanrev_fades(); test_settle_win_loss(); test_category_pnl()
    print("All simulator tests passed.")
