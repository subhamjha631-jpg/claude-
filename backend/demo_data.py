"""
Bundled demo markets used when the live APIs are unreachable.

These are illustrative numbers, NOT live prices. They include a couple of
deliberately mispriced pairs so you can see the scanner light up an
opportunity. The Trump example from the original request is included:
YES is cheap on one platform and NO is cheap on the other, so buying both
legs costs less than $1.
"""

from __future__ import annotations

from sources import Market


def load() -> tuple[list[Market], list[Market]]:
    poly = [
        Market("Polymarket", "p1", "Will Trump win the 2024 election?",
               yes_ask=0.62, no_ask=0.40, yes_bid=0.60, volume=5_000_000,
               url="https://polymarket.com/event/trump-2024"),
        Market("Polymarket", "p2", "Will the Fed cut rates in September?",
               yes_ask=0.55, no_ask=0.47, yes_bid=0.53, volume=900_000,
               url="https://polymarket.com/event/fed-september"),
        Market("Polymarket", "p3", "Will Bitcoin reach $100,000 in 2024?",
               yes_ask=0.30, no_ask=0.72, yes_bid=0.28, volume=2_000_000,
               url="https://polymarket.com/event/btc-100k-2024"),
        Market("Polymarket", "p4", "Will SpaceX reach Mars by 2030?",
               yes_ask=0.18, no_ask=0.84, yes_bid=0.16, volume=300_000,
               url="https://polymarket.com/event/spacex-mars-2030"),
    ]
    kalshi = [
        # Mispriced vs Polymarket p1: NO is cheap here (0.33). Buy YES on
        # Polymarket @0.62 + NO on Kalshi @0.33 = 0.95 -> 5c locked profit.
        Market("Kalshi", "PRES-24-TRUMP", "Donald Trump wins 2024 presidential election",
               yes_ask=0.68, no_ask=0.33, yes_bid=0.66, volume=4_200_000,
               url="https://kalshi.com/markets/PRES-24-TRUMP"),
        Market("Kalshi", "FED-SEP-CUT", "Fed cuts interest rates at September meeting",
               yes_ask=0.51, no_ask=0.52, yes_bid=0.49, volume=700_000,
               url="https://kalshi.com/markets/FED-SEP-CUT"),
        # Mispriced vs Polymarket p3: YES cheap here (0.26). Buy YES on Kalshi
        # @0.26 + NO on Polymarket @0.72 = 0.98 -> 2c locked profit.
        Market("Kalshi", "BTC-100K-24", "Bitcoin reaches $100,000 during 2024",
               yes_ask=0.26, no_ask=0.77, yes_bid=0.24, volume=1_500_000,
               url="https://kalshi.com/markets/BTC-100K-24"),
        Market("Kalshi", "NBA-CHAMP", "Boston Celtics win the NBA championship",
               yes_ask=0.40, no_ask=0.63, yes_bid=0.38, volume=550_000,
               url="https://kalshi.com/markets/NBA-CHAMP"),
    ]
    return poly, kalshi
