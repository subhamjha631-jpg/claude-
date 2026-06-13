"""
Match equivalent markets across platforms and compute arbitrage.

Matching is the genuinely hard part of cross-platform arbitrage: "Will Trump
win the 2024 election?" on one site and "2024 Presidential Election Winner:
Donald Trump" on another are the same bet phrased differently. We use a
lightweight text-similarity score (shared keywords + sequence ratio) to surface
*candidate* pairs. You should always eyeball a match before trading real money,
because a false match looks like free money but is actually two different bets.

Arbitrage on a binary event:
  Exactly one of YES / NO pays out $1. If you buy a YES share on platform A for
  `a` dollars and a NO share on platform B for `b` dollars, you are guaranteed
  to hold exactly one winning $1 share. If a + b < 1 you locked in (1 - a - b)
  profit per pair, regardless of the outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher

from sources import Market

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
    question_a: str
    question_b: str
    platform_a: str
    platform_b: str
    url_a: str
    url_b: str
    match_score: float
    # The winning strategy:
    strategy: str          # e.g. "Buy YES on Polymarket + Buy NO on Kalshi"
    cost_yes: float        # price paid for the YES leg
    cost_no: float         # price paid for the NO leg
    total_cost: float      # cost_yes + cost_no (per guaranteed $1 payout)
    profit_per_pair: float # 1 - total_cost
    roi_pct: float         # profit / total_cost * 100

    def to_dict(self):
        return asdict(self)


def _best_arb(m1: Market, m2: Market) -> dict | None:
    """Best of the two cross-platform YES/NO combinations, if profitable."""
    candidates = []

    # Combination 1: YES on m1, NO on m2.
    if m1.yes_ask is not None and m2.no_ask is not None:
        candidates.append(
            (m1.yes_ask, m2.no_ask, m1, m2, "YES", "NO")
        )
    # Combination 2: YES on m2, NO on m1.
    if m2.yes_ask is not None and m1.no_ask is not None:
        candidates.append(
            (m2.yes_ask, m1.no_ask, m2, m1, "YES", "NO")
        )

    best = None
    for cost_yes, cost_no, yes_mkt, no_mkt, _, _ in candidates:
        total = cost_yes + cost_no
        profit = 1.0 - total
        if best is None or profit > best["profit_per_pair"]:
            best = {
                "yes_mkt": yes_mkt,
                "no_mkt": no_mkt,
                "cost_yes": round(cost_yes, 4),
                "cost_no": round(cost_no, 4),
                "total_cost": round(total, 4),
                "profit_per_pair": round(profit, 4),
            }
    return best


def find_opportunities(
    markets_a: list[Market],
    markets_b: list[Market],
    min_match_score: float = 0.45,
    min_profit: float = 0.0,
) -> list[Opportunity]:
    """Cross-match two platforms' markets and return profitable arbs.

    `min_profit` is in dollars-per-$1-pair (after no fees). Set it above 0 to
    leave a margin for platform fees and slippage.
    """
    opportunities: list[Opportunity] = []

    for m1 in markets_a:
        if not m1.question:
            continue
        for m2 in markets_b:
            if not m2.question:
                continue
            score = similarity(m1.question, m2.question)
            if score < min_match_score:
                continue

            arb = _best_arb(m1, m2)
            if arb is None:
                continue
            if arb["profit_per_pair"] <= min_profit:
                continue

            yes_mkt = arb["yes_mkt"]
            no_mkt = arb["no_mkt"]
            roi = (arb["profit_per_pair"] / arb["total_cost"] * 100.0) if arb["total_cost"] else 0.0
            opportunities.append(
                Opportunity(
                    question_a=m1.question,
                    question_b=m2.question,
                    platform_a=m1.platform,
                    platform_b=m2.platform,
                    url_a=m1.url,
                    url_b=m2.url,
                    match_score=score,
                    strategy=(
                        f"Buy YES on {yes_mkt.platform} @ {arb['cost_yes']:.2f} "
                        f"+ Buy NO on {no_mkt.platform} @ {arb['cost_no']:.2f}"
                    ),
                    cost_yes=arb["cost_yes"],
                    cost_no=arb["cost_no"],
                    total_cost=arb["total_cost"],
                    profit_per_pair=arb["profit_per_pair"],
                    roi_pct=round(roi, 2),
                )
            )

    opportunities.sort(key=lambda o: o.profit_per_pair, reverse=True)
    return opportunities
