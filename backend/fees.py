"""
Trading-fee models for each platform, so the bot can report *net* profit.

Kalshi charges a trading fee per contract, rounded up to the next cent:
    fee = ceil( 0.07 * price * (1 - price) )         (per contract)
It is highest near $0.50 and shrinks toward the extremes. This is the standard
general-markets formula; a few special markets differ, so treat it as a close
estimate, not a guarantee.

Polymarket currently charges no protocol trading fee, but you still pay the
bid/ask spread and (for deposits/withdrawals) some gas. We model it as a
configurable notional rate that defaults to 0.
"""

from __future__ import annotations

import math


def _ceil_to_cent(x: float) -> float:
    return math.ceil(round(x * 100, 6)) / 100.0


def kalshi_fee(price: float, contracts: int = 1) -> float:
    """Kalshi trading fee for `contracts` at `price` (0..1), rounded up to cent."""
    return _ceil_to_cent(0.07 * contracts * price * (1.0 - price))


def polymarket_fee(price: float, contracts: int = 1, rate: float = 0.0) -> float:
    """Polymarket fee estimate: `rate` as a fraction of notional (default 0)."""
    return rate * price * contracts


def leg_fee(platform: str, price: float, polymarket_rate: float = 0.0) -> float:
    """Per-contract fee for one leg of the trade on the given platform."""
    if platform == "Kalshi":
        return kalshi_fee(price)
    if platform == "Polymarket":
        return polymarket_fee(price, rate=polymarket_rate)
    return 0.0
