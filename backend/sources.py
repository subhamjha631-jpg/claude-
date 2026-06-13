"""
Market data clients for prediction-market platforms.

Each client returns a normalized list of `Market` objects so the rest of the
app does not care which platform a price came from. We always use the *ask*
price (what you actually pay to buy a share), because arbitrage profit has to
be computed on executable prices, not the last-trade or mid price.

Prices are normalized to a 0..1 probability scale where a YES share that costs
$0.65 is represented as 0.65.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = logging.getLogger("sources")

# Public, unauthenticated REST endpoints.
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com/markets"
KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"

HTTP_TIMEOUT = 20.0
USER_AGENT = "arb-scanner/1.0 (+https://example.local)"


@dataclass
class Market:
    """A single binary (YES/NO) market on one platform."""

    platform: str           # "Polymarket" | "Kalshi"
    market_id: str
    question: str           # human-readable title
    yes_ask: Optional[float]  # cost to BUY a YES share, 0..1 (None if no offer)
    no_ask: Optional[float]   # cost to BUY a NO share, 0..1 (None if no offer)
    yes_bid: Optional[float] = None  # what you could SELL a YES share for
    volume: float = 0.0
    url: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def mid(self) -> Optional[float]:
        """Approximate YES probability for display/matching sanity checks."""
        if self.yes_ask is not None and self.yes_bid is not None:
            return round((self.yes_ask + self.yes_bid) / 2, 4)
        return self.yes_ask


def _to_float(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_polymarket(limit: int = 500) -> list[Market]:
    """Pull active, non-closed binary markets from Polymarket's Gamma API."""
    markets: list[Market] = []
    params = {
        "closed": "false",
        "active": "true",
        "limit": str(limit),
        "order": "volume24hr",
        "ascending": "false",
    }
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=HTTP_TIMEOUT, headers=headers) as client:
        resp = client.get(POLYMARKET_GAMMA_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    for m in data:
        # Gamma encodes these list fields as JSON strings.
        try:
            outcomes = json.loads(m.get("outcomes") or "[]")
        except (json.JSONDecodeError, TypeError):
            outcomes = []
        # We only handle plain YES/NO binary markets.
        labels = [str(o).strip().lower() for o in outcomes]
        if sorted(labels) != ["no", "yes"]:
            continue

        best_ask = _to_float(m.get("bestAsk"))   # YES ask
        best_bid = _to_float(m.get("bestBid"))   # YES bid
        if best_ask is None:
            continue

        # NO ask = 1 - (YES bid). Buying NO is equivalent to selling YES; the
        # price you pay for NO is one minus the best price someone will pay for
        # YES. Fall back to 1 - yes_ask if bid is missing (more conservative).
        no_ask = None
        if best_bid is not None:
            no_ask = round(1.0 - best_bid, 4)
        elif best_ask is not None:
            no_ask = round(1.0 - best_ask, 4)

        slug = m.get("slug") or ""
        markets.append(
            Market(
                platform="Polymarket",
                market_id=str(m.get("id") or slug),
                question=(m.get("question") or m.get("title") or "").strip(),
                yes_ask=best_ask,
                no_ask=no_ask,
                yes_bid=best_bid,
                volume=_to_float(m.get("volume")) or 0.0,
                url=f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com",
                raw={},
            )
        )
    log.info("Polymarket: %d binary markets", len(markets))
    return markets


def fetch_kalshi(limit: int = 1000) -> list[Market]:
    """Pull open markets from Kalshi's public elections API.

    Kalshi quotes in integer cents (1..99). yes_ask is the cost to buy YES,
    no_ask the cost to buy NO; we divide by 100 to match the 0..1 scale.
    """
    markets: list[Market] = []
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    cursor = None
    fetched = 0
    with httpx.Client(timeout=HTTP_TIMEOUT, headers=headers) as client:
        while fetched < limit:
            params = {"status": "open", "limit": "100"}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(KALSHI_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
            batch = payload.get("markets", [])
            if not batch:
                break
            for m in batch:
                yes_ask_c = _to_float(m.get("yes_ask"))
                no_ask_c = _to_float(m.get("no_ask"))
                yes_bid_c = _to_float(m.get("yes_bid"))
                # 0 means "no offer on the book" on Kalshi.
                yes_ask = yes_ask_c / 100.0 if yes_ask_c else None
                no_ask = no_ask_c / 100.0 if no_ask_c else None
                yes_bid = yes_bid_c / 100.0 if yes_bid_c else None
                if yes_ask is None and no_ask is None:
                    continue
                title = (m.get("title") or m.get("subtitle") or "").strip()
                ticker = m.get("ticker") or ""
                markets.append(
                    Market(
                        platform="Kalshi",
                        market_id=str(ticker),
                        question=title,
                        yes_ask=yes_ask,
                        no_ask=no_ask,
                        yes_bid=yes_bid,
                        volume=_to_float(m.get("volume")) or 0.0,
                        url=f"https://kalshi.com/markets/{ticker}" if ticker else "https://kalshi.com",
                        raw={},
                    )
                )
            fetched += len(batch)
            cursor = payload.get("cursor")
            if not cursor:
                break
    log.info("Kalshi: %d markets", len(markets))
    return markets
