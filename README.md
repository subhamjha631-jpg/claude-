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

## Option A — Telegram bot (recommended: alerts pushed to your phone)

The bot scans both platforms on a loop and messages you whenever an arbitrage
appears. Every message spells out exactly what to do — no thinking required:

- It names the event and what it's called on **both** platforms.
- It tells you which platform to use for each leg, and whether to **BUY YES** or
  **BUY NO**, and at what price.
- It shows the cost, the **estimated fees**, the **net profit**, and the
  **net ROI after fees**, plus a simple "$100 per side → keep ~$X" example.
- The **biggest profits come first**, and high-profit alerts are repeated so you
  don't miss them: **≥10% net ROI is sent 3 times, ≥5% is sent 2 times**, smaller
  ones once.

### Simple Telegram setup (plain language)

You need two things: a **bot token** and your **chat id**. Here's how, step by step:

1. **Make the bot.** Open Telegram, search for the user **@BotFather** (it has a
   blue checkmark), open it, and tap **Start**. Send the message `/newbot`.
   It will ask for a name (anything, e.g. "My Arb Bot") and a username (must end
   in `bot`, e.g. `my_arb_alert_bot`). When done, it sends you a **token** that
   looks like `123456789:ABCdefGhIJKlmnoPQRstuVWxyz`. Copy it — that's your
   `TELEGRAM_BOT_TOKEN`.
2. **Say hi to your bot.** Tap the link BotFather gives you to open your new bot,
   tap **Start**, and send it any message like `hi`. (This lets the bot message
   you back.)
3. **Get your chat id.** On your computer, run:
   ```bash
   pip install -r requirements.txt
   cd backend
   TELEGRAM_BOT_TOKEN="paste-your-token-here" python telegram_bot.py --get-chat-id
   ```
   It prints a number like `7654321` — that's your `TELEGRAM_CHAT_ID`.
4. **Start the bot.** Run:
   ```bash
   export TELEGRAM_BOT_TOKEN="paste-your-token-here"
   export TELEGRAM_CHAT_ID="paste-your-chat-id-here"
   python telegram_bot.py
   ```
   You'll get a "bot started" message in Telegram, then alerts as they appear.
   Leave this running (your PC, a Raspberry Pi, or any free always-on host like
   a free-tier VM). That's it.

> Tip: run it with **no** token first (just `python telegram_bot.py`) to see the
> alerts printed in your console — a free way to confirm it works before wiring
> up Telegram.

**Tuning** (optional, all set as environment variables before running):

| Variable | Meaning | Default |
|---|---|---|
| `SCAN_INTERVAL` | seconds between scans | 120 |
| `MIN_PROFIT` | minimum **net** profit per $1 pair to alert | 0.01 |
| `MIN_VOLUME` | skip markets with less than this $ traded (liquidity floor) | 5000 |
| `MIN_SCORE` | event-match confidence (0–1) | 0.5 |
| `POLYMARKET_FEE_RATE` | Polymarket fee as a fraction of notional | 0.0 |
| `HIGH_ROI_PCT` / `VERY_HIGH_ROI_PCT` | net ROI % for 2× / 3× repeats | 5 / 10 |
| `REPEAT_GAP` | seconds between repeat pings | 20 |

## Option B — Web dashboard

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
