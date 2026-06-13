# Prediction Market Arbitrage Scanner

Finds the same real-world event priced differently on **Polymarket** and
**Kalshi**, and flags when you can lock in a guaranteed profit by buying YES on
one platform and NO on the other.

## The idea in one paragraph

A binary prediction market has YES and NO shares; exactly one of them pays out
$1 when the event resolves. If "Trump wins" YES costs **$0.62** on Polymarket
and the same event's NO costs **$0.33** on Kalshi, you can buy *both* for
**$0.95** and be guaranteed to hold one $1 winner — a locked-in **$0.05**
profit no matter what happens. The scanner hunts for these `YES + NO < $1`
mispricings across the two platforms.

## What it does

1. Pulls live, open markets from the public Polymarket (Gamma) and Kalshi APIs.
2. Normalizes every market to a YES-ask / NO-ask price on a 0..1 scale.
3. Matches equivalent events across platforms using keyword + text similarity.
4. Computes the best cross-platform YES/NO combination and the profit per pair.
5. Serves a live, auto-refreshing dashboard sorted by profit.

## Run it

```bash
pip install -r requirements.txt
cd backend
uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000**.

- Adjust **Min match score** (how confident the event-matching must be) and
  **Min profit / $1 pair** (raise it to cover fees) from the dashboard.
- If the live APIs are unreachable (corporate network, sandbox, etc.), the app
  falls back to bundled demo data and shows a `DEMO DATA` badge so the UI still
  works — replace with live data by running where the APIs are reachable.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/opportunities?min_score=0.45&min_profit=0.0` | ranked arbitrage list |
| `GET /api/markets` | raw normalized markets from both platforms |
| `GET /` | dashboard |

## Read this before risking money

This tool surfaces **candidates** — it does not place trades, and a flagged
opportunity is not automatically free money:

- **False matches are the #1 risk.** Two markets can sound identical but resolve
  on different dates or rules. Always click both links and confirm the exact
  resolution criteria before trading.
- **Fees and spreads eat thin edges.** Kalshi charges trading fees; Polymarket
  has spread/gas costs. Keep min profit above ~$0.02–0.03 to stay net-positive.
- **Displayed price ≠ fillable size.** The best ask may only cover a few
  contracts. Check order-book depth before sizing up.
- **Capital is locked until resolution**, and you need funded accounts on both
  platforms. Account for that opportunity cost.

## Extending it

- Add more platforms in `backend/sources.py` (return `Market` objects).
- Improve event matching in `backend/arbitrage.py` (the `similarity` function) —
  embeddings or an LLM matcher would cut false positives substantially.
- Add Kalshi/Polymarket fee models to `_best_arb` for true net-of-fee profit.
