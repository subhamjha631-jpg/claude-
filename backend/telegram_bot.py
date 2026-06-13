"""
Telegram alert bot for prediction-market arbitrage.

Runs forever. Every SCAN_INTERVAL seconds it scans Polymarket + Kalshi, finds
YES+NO < $1 mispricings (after fees), and pushes a dead-simple, do-exactly-this
instruction to your Telegram chat. You just follow the steps and place the bets.

Each alert tells you, in plain words:
  - the event, and its title on BOTH platforms
  - which platform to use for each leg (by name)
  - whether to buy YES or NO, and at what price
  - the fees, the net profit, and the net ROI after fees
High-profit alerts (>=5% / >=10% net ROI) are repeated 2-3 times so you don't
miss them. Lower-profit alerts are sent once.

Setup (one time, free) -- see README "Simple Telegram setup" for the walkthrough:
  1. Telegram -> message @BotFather -> /newbot -> get your TOKEN.
  2. Send "hi" to your new bot.
  3. python telegram_bot.py --get-chat-id   (with TELEGRAM_BOT_TOKEN set)
  4. export TELEGRAM_BOT_TOKEN=... ; export TELEGRAM_CHAT_ID=... ; python telegram_bot.py

Tuning via environment variables (all optional):
  SCAN_INTERVAL        seconds between scans                  (default 120)
  MIN_SCORE            0..1 event-match confidence            (default 0.5)
  MIN_PROFIT           min NET $ profit per $1 pair to alert  (default 0.01)
  POLYMARKET_FEE_RATE  Polymarket fee as fraction of notional (default 0.0)
  HIGH_ROI_PCT         net ROI for "high profit" repeats      (default 5)
  VERY_HIGH_ROI_PCT    net ROI for max repeats                (default 10)
  REPEAT_GAP           seconds between repeat pings           (default 20)
  REALERT_AFTER        re-send a still-live opp after N sec   (default 3600)

If TELEGRAM_BOT_TOKEN is not set, the bot runs in DRY-RUN mode and prints the
alerts to the console instead of sending them.
"""

from __future__ import annotations

import logging
import os
import sys
import time

import httpx

import demo_data
import sources
from arbitrage import find_opportunities, Opportunity

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", "120"))
MIN_SCORE = float(os.environ.get("MIN_SCORE", "0.5"))
MIN_PROFIT = float(os.environ.get("MIN_PROFIT", "0.01"))
MIN_VOLUME = float(os.environ.get("MIN_VOLUME", "5000"))
POLYMARKET_FEE_RATE = float(os.environ.get("POLYMARKET_FEE_RATE", "0.0"))
HIGH_ROI_PCT = float(os.environ.get("HIGH_ROI_PCT", "5"))
VERY_HIGH_ROI_PCT = float(os.environ.get("VERY_HIGH_ROI_PCT", "10"))
REPEAT_GAP = int(os.environ.get("REPEAT_GAP", "20"))
REALERT_AFTER = int(os.environ.get("REALERT_AFTER", "3600"))

API = f"https://api.telegram.org/bot{TOKEN}"


def send_message(text: str) -> None:
    """Send a Telegram message, or print it if running without a token."""
    if not TOKEN or not CHAT_ID:
        print("\n--- [DRY-RUN ALERT] ---\n" + text + "\n-----------------------")
        return
    try:
        resp = httpx.post(
            f"{API}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        log.error("Failed to send Telegram message: %s", exc)


def get_chat_id() -> None:
    """Print chat ids of recent messages sent to the bot (setup helper)."""
    if not TOKEN:
        print("Set TELEGRAM_BOT_TOKEN first, then message your bot, then re-run.")
        sys.exit(1)
    resp = httpx.get(f"{API}/getUpdates", timeout=20.0)
    resp.raise_for_status()
    updates = resp.json().get("result", [])
    if not updates:
        print("No messages yet. Send a message to your bot in Telegram, then re-run.")
        return
    seen = {}
    for u in updates:
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            seen[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name", "?")
    print("Chat id(s) that messaged your bot:")
    for cid, name in seen.items():
        print(f"  {cid}  ({name})")
    print("\nUse the id above as TELEGRAM_CHAT_ID.")


def _opp_key(o: Opportunity) -> str:
    return f"{o.question_a}|{o.question_b}"


def repeat_count(net_roi_pct: float) -> int:
    """How many times to ping for a given net ROI (priority by profit size)."""
    if net_roi_pct >= VERY_HIGH_ROI_PCT:
        return 3
    if net_roi_pct >= HIGH_ROI_PCT:
        return 2
    return 1


def format_alert(o: Opportunity, demo: bool, idx: int, total: int) -> str:
    """Build the spell-it-out message. idx/total drive the repeat header."""
    # Priority banner.
    if o.net_roi_pct >= VERY_HIGH_ROI_PCT:
        banner = f"🔥🔥 BIG PROFIT {o.net_roi_pct:.1f}% — ACT FAST"
    elif o.net_roi_pct >= HIGH_ROI_PCT:
        banner = f"🔥 HIGH PROFIT {o.net_roi_pct:.1f}% — don't miss it"
    else:
        banner = f"💰 Arbitrage {o.net_roi_pct:.1f}% net"
    if total > 1:
        banner += f"  (reminder {idx}/{total})"

    demo_tag = "🧪 <b>[DEMO DATA — not live prices]</b>\n" if demo else ""

    # Per-$100 example so the size is intuitive.
    profit_100 = o.net_roi_pct  # net profit on $100 ≈ net_roi% dollars

    return (
        f"{demo_tag}<b>{banner}</b>\n\n"
        f"📌 <b>EVENT:</b> {o.question_a}\n"
        f"• On <b>{o.platform_a}</b> it's called: \"{o.question_a}\"\n"
        f"• On <b>{o.platform_b}</b> it's called: \"{o.question_b}\"\n\n"
        f"✅ <b>DO EXACTLY THIS (place two bets):</b>\n"
        f"1️⃣ Go to <b>{o.yes_platform}</b> → <b>BUY \"YES\"</b> at <b>${o.yes_price:.2f}</b>\n"
        f"   👉 <a href=\"{o.yes_url}\">open {o.yes_platform}</a>\n"
        f"2️⃣ Go to <b>{o.no_platform}</b> → <b>BUY \"NO\"</b> at <b>${o.no_price:.2f}</b>\n"
        f"   👉 <a href=\"{o.no_url}\">open {o.no_platform}</a>\n\n"
        f"ℹ️ You are NOT selling anything you don't own. You place these two bets "
        f"on the two sites. One side is guaranteed to win $1.00.\n\n"
        f"💵 <b>THE MATH (per $1 you aim to win):</b>\n"
        f"• You pay:      ${o.total_cost:.2f}\n"
        f"• Est. fees:    ${o.fee_per_pair:.2f}\n"
        f"• You get back: $1.00 (guaranteed)\n"
        f"• <b>NET PROFIT: ${o.net_profit_per_pair:.2f}  ➜  +{o.net_roi_pct:.1f}% after fees</b>\n\n"
        f"📊 <b>Example:</b> put ~$100 on each side → keep roughly "
        f"<b>${profit_100:.0f} profit</b>, guaranteed.\n\n"
        f"💧 Liquidity (smaller side): ~${o.min_volume:,.0f} traded — "
        f"check the order book covers your size.\n"
        f"🧠 Match confidence {o.match_score:.0%}. Open BOTH links and confirm it's "
        f"the same question with the same end date before betting."
    )


def scan_once():
    """Return (opportunities, is_demo)."""
    demo = False
    try:
        poly = sources.fetch_polymarket()
        kalshi = sources.fetch_kalshi()
        if not poly or not kalshi:
            raise RuntimeError("a source returned no markets")
    except Exception as exc:
        log.warning("Live fetch failed (%s); using demo data", exc)
        poly, kalshi = demo_data.load()
        demo = True
    opps = find_opportunities(
        poly, kalshi,
        min_match_score=MIN_SCORE,
        min_profit=MIN_PROFIT,
        polymarket_fee_rate=POLYMARKET_FEE_RATE,
        min_volume=MIN_VOLUME,
    )
    return opps, demo


def send_with_repeats(o: Opportunity, demo: bool) -> int:
    """Send an opportunity, repeating high-profit ones. Returns messages sent."""
    reps = repeat_count(o.net_roi_pct)
    for i in range(reps):
        send_message(format_alert(o, demo, i + 1, reps))
        if i < reps - 1:
            time.sleep(REPEAT_GAP)
    return reps


def main() -> None:
    mode = "LIVE Telegram" if (TOKEN and CHAT_ID) else "DRY-RUN (console)"
    log.info("Starting bot | mode=%s | interval=%ss | min_net_profit=$%.2f | min_score=%.2f",
             mode, SCAN_INTERVAL, MIN_PROFIT, MIN_SCORE)
    send_message(
        "✅ <b>Arbitrage bot started.</b>\n"
        f"Scanning Polymarket + Kalshi every {SCAN_INTERVAL}s.\n"
        f"Alerting on NET profit ≥ ${MIN_PROFIT:.2f} per $1 pair "
        f"(match ≥ {MIN_SCORE:.0%}, volume ≥ ${MIN_VOLUME:,.0f}). "
        f"Best profits come first; high-profit ones are repeated."
    )

    # key -> (last_net_profit_alerted, last_alert_time)
    alerted: dict[str, tuple[float, float]] = {}

    while True:
        try:
            opps, demo = scan_once()  # already sorted best-first
            now = time.time()
            sent = 0
            for o in opps:
                key = _opp_key(o)
                prev = alerted.get(key)
                is_new = prev is None
                improved = prev is not None and o.net_profit_per_pair >= prev[0] + 0.01
                stale = prev is not None and (now - prev[1]) >= REALERT_AFTER
                if is_new or improved or stale:
                    sent += send_with_repeats(o, demo)
                    alerted[key] = (o.net_profit_per_pair, time.time())
            log.info("Scan done: %d opportunities, %d messages sent%s",
                     len(opps), sent, " [demo]" if demo else "")
        except Exception as exc:
            log.error("Scan loop error: %s", exc)
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    if "--get-chat-id" in sys.argv:
        get_chat_id()
    else:
        main()
