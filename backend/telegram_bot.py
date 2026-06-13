"""
Telegram alert bot for prediction-market arbitrage.

Runs forever. Every SCAN_INTERVAL seconds it scans Polymarket + Kalshi, finds
YES+NO<$1 mispricings, and pushes any *new or improved* opportunity to your
Telegram chat. You then tap the links and place the bets manually.

Setup (one time, free):
  1. In Telegram, message @BotFather, send /newbot, follow prompts. It gives
     you a token like "123456:ABC-DEF...". That is your TELEGRAM_BOT_TOKEN.
  2. Send any message ("hi") to your new bot so it can reply to you.
  3. Find your chat id:  python telegram_bot.py --get-chat-id
     (uses TELEGRAM_BOT_TOKEN; prints the chat id of whoever messaged the bot)
  4. Run the bot:
       export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
       export TELEGRAM_CHAT_ID="<the id from step 3>"
       python telegram_bot.py

Tuning via environment variables (all optional):
  SCAN_INTERVAL  seconds between scans            (default 120)
  MIN_SCORE      0..1 event-match confidence       (default 0.5)
  MIN_PROFIT     min $ profit per $1 pair to alert (default 0.02)
  REALERT_AFTER  re-send a still-live opp after N seconds (default 3600)

If TELEGRAM_BOT_TOKEN is not set, the bot runs in DRY-RUN mode and prints the
alerts to the console instead of sending them — handy for testing.
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
MIN_PROFIT = float(os.environ.get("MIN_PROFIT", "0.02"))
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


def format_alert(o: Opportunity, demo: bool) -> str:
    tag = "🧪 <b>[DEMO DATA]</b>\n" if demo else ""
    return (
        f"{tag}💰 <b>Arbitrage: +${o.profit_per_pair:.2f} per $1 pair "
        f"({o.roi_pct:.1f}% ROI)</b>\n\n"
        f"<b>Event:</b> {o.question_a}\n"
        f"<b>Strategy:</b> {o.strategy}\n"
        f"Total cost ${o.total_cost:.2f} → guaranteed $1.00 payout\n"
        f"Match confidence: {o.match_score:.0%}\n\n"
        f"🔗 <a href=\"{o.url_a}\">{o.platform_a} market</a>\n"
        f"🔗 <a href=\"{o.url_b}\">{o.platform_b} market</a>\n\n"
        f"<i>Verify both markets resolve on the same condition before betting. "
        f"Profit is before fees.</i>"
    )


def scan_once() -> tuple[list[Opportunity], bool]:
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
    opps = find_opportunities(poly, kalshi, min_match_score=MIN_SCORE, min_profit=MIN_PROFIT)
    return opps, demo


def main() -> None:
    mode = "LIVE Telegram" if (TOKEN and CHAT_ID) else "DRY-RUN (console)"
    log.info("Starting arbitrage bot | mode=%s | interval=%ss | min_profit=$%.2f | min_score=%.2f",
             mode, SCAN_INTERVAL, MIN_PROFIT, MIN_SCORE)
    send_message(
        "✅ <b>Arbitrage bot started.</b>\n"
        f"Scanning Polymarket + Kalshi every {SCAN_INTERVAL}s.\n"
        f"Alerting on profit ≥ ${MIN_PROFIT:.2f} per $1 pair, "
        f"match ≥ {MIN_SCORE:.0%}."
    )

    # key -> (last_profit_alerted, last_alert_time)
    alerted: dict[str, tuple[float, float]] = {}

    while True:
        try:
            opps, demo = scan_once()
            now = time.time()
            new_count = 0
            for o in opps:
                key = _opp_key(o)
                prev = alerted.get(key)
                is_new = prev is None
                improved = prev is not None and o.profit_per_pair >= prev[0] + 0.01
                stale = prev is not None and (now - prev[1]) >= REALERT_AFTER
                if is_new or improved or stale:
                    send_message(format_alert(o, demo))
                    alerted[key] = (o.profit_per_pair, now)
                    new_count += 1
            log.info("Scan done: %d opportunities, %d alerts sent%s",
                     len(opps), new_count, " [demo]" if demo else "")
        except Exception as exc:
            log.error("Scan loop error: %s", exc)
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    if "--get-chat-id" in sys.argv:
        get_chat_id()
    else:
        main()
