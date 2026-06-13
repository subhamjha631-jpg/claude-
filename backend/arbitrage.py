"""
Match equivalent markets across platforms and compute arbitrage (net of fees).

Matching is the genuinely hard part of cross-platform arbitrage: "Will Trump
win the 2024 election?" on one site and "2024 Presidential Election Winner:
Donald Trump" on another are the same bet phrased differently. We use a
lightweight text-similarity score (shared keywords + sequence ratio) to surface
*candidate* pairs. You should always eyeball a match before trading real money,
because a false match looks like free money but is actually two different bets.

Arbitrage on a binary event:
  Exactly one of YES / NO pays out $1. If you buy a YES share on platform A for
  `a` dollars and a NO share on platform B for `b` dollars, you are guaranteed
  to hold exactly one winning $1 share. If a + b (+ fees) < 1 you locked in the
  difference as profit, regardless of the outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher

from sources import Market
from fees import leg_fee

STOPWORDS = {
    "the", "a", "an", "will", "be", "is", "are", "to", "of", "in", "on", "for",
    "by", "at", "and", "or", "win", "wins", "winner", "market", "yes", "no",
    "this", "that", "before", "after", "during", "than", "with", "as", "it",
    "have", "has", "do", "does", "any", "more", "less", "least", "most",
}

WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    words = WORD_RE.findall(text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def similarity(a: str, b: str) -> float:
    """0..1 similarity blending keyword overlap (Jaccard) and sequence ratio."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    ratio = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return round(0.65 * jaccard + 0.35 * ratio, 4)


@dataclass
class Opportunity:
    # --- the matched event on each platform ---
    question_a: str
    question_b: str
    platform_a: str
    platform_b: str
    url_a: str
    url_b: str
    match_score: float

    # --- explicit, no-thinking-required trade legs ---
    yes_platform: str   # where to BUY the YES share
    yes_price: float
    yes_url: str
    no_platform: str    # where to BUY the NO share
    no_price: float
    no_url: str

    # --- liquidity (so you can actually fill your size) ---
    min_volume: float   # the smaller traded volume of the two legs

    # --- the money math, per $1 guaranteed payout ---
    total_cost: float          # yes_price + no_price
    gross_profit_per_pair: float
    gross_roi_pct: float
    fee_per_pair: float        # estimated fees for both legs
    net_profit_per_pair: float # after fees
    net_roi_pct: float         # after fees, the number that matters

    # legacy/compat aliases used by the web dashboard
    strategy: str
    cost_yes: float
    cost_no: float
    profit_per_pair: float     # == net_profit_per_pair
    roi_pct: float             # == net_roi_pct

    def to_dict(self):
        return asdict(self)


def _best_arb(m1: Market, m2: Market):
    """Best of the two cross-platform YES/NO combinations by *gross* edge."""
    candidates = []
    if m1.yes_ask is not None and m2.no_ask is not None:
        candidates.append((m1.yes_ask, m1, m2.no_ask, m2))  # YES on m1, NO on m2
    if m2.yes_ask is not None and m1.no_ask is not None:
        candidates.append((m2.yes_ask, m2, m1.no_ask, m1))  # YES on m2, NO on m1

    best = None
    for yes_price, yes_mkt, no_price, no_mkt in candidates:
        total = yes_price + no_price
        if best is None or total < best[0]:
            best = (total, yes_price, yes_mkt, no_price, no_mkt)
    return best


def find_opportunities(
    markets_a: list[Market],
    markets_b: list[Market],
    min_match_score: float = 0.45,
    min_profit: float = 0.0,
    polymarket_fee_rate: float = 0.0,
    min_volume: float = 0.0,
) -> list[Opportunity]:
    """Cross-match two platforms and return arbs that are profitable AFTER fees.

    `min_profit` is net dollars per $1 pair. `min_volume` drops pairs where
    either market is too thinly traded to fill (uses each platform's reported
    volume). Results are sorted by net profit, highest first.
    """
    opportunities: list[Opportunity] = []

    for m1 in markets_a:
        if not m1.question:
            continue
        for m2 in markets_b:
            if not m2.question:
                continue
            # Liquidity gate: both legs must clear the volume floor.
            if min_volume > 0 and (m1.volume < min_volume or m2.volume < min_volume):
                continue
            score = similarity(m1.question, m2.question)
            if score < min_match_score:
                continue

            best = _best_arb(m1, m2)
            if best is None:
                continue
            total, yes_price, yes_mkt, no_price, no_mkt = best

            fee_yes = leg_fee(yes_mkt.platform, yes_price, polymarket_fee_rate)
            fee_no = leg_fee(no_mkt.platform, no_price, polymarket_fee_rate)
            fee_total = round(fee_yes + fee_no, 4)

            gross_profit = round(1.0 - total, 4)
            net_profit = round(1.0 - total - fee_total, 4)
            if net_profit <= min_profit:
                continue

            outlay = total + fee_total
            net_roi = round((net_profit / outlay * 100.0), 2) if outlay else 0.0
            gross_roi = round((gross_profit / total * 100.0), 2) if total else 0.0

            opportunities.append(
                Opportunity(
                    question_a=m1.question,
                    question_b=m2.question,
                    platform_a=m1.platform,
                    platform_b=m2.platform,
                    url_a=m1.url,
                    url_b=m2.url,
                    match_score=score,
                    yes_platform=yes_mkt.platform,
                    yes_price=round(yes_price, 4),
                    yes_url=yes_mkt.url,
                    no_platform=no_mkt.platform,
                    no_price=round(no_price, 4),
                    no_url=no_mkt.url,
                    min_volume=round(min(m1.volume, m2.volume), 2),
                    total_cost=round(total, 4),
                    gross_profit_per_pair=gross_profit,
                    gross_roi_pct=gross_roi,
                    fee_per_pair=fee_total,
                    net_profit_per_pair=net_profit,
                    net_roi_pct=net_roi,
                    strategy=(
                        f"BUY YES on {yes_mkt.platform} @ {yes_price:.2f} "
                        f"+ BUY NO on {no_mkt.platform} @ {no_price:.2f}"
                    ),
                    cost_yes=round(yes_price, 4),
                    cost_no=round(no_price, 4),
                    profit_per_pair=net_profit,
                    roi_pct=net_roi,
                )
            )

    opportunities.sort(key=lambda o: o.net_profit_per_pair, reverse=True)
    return opportunities
