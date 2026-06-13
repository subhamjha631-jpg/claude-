"""
Arbitrage scanner web server.

Serves:
  GET /api/opportunities  -> JSON list of cross-platform arbitrage opportunities
  GET /api/markets        -> raw normalized markets from both platforms
  GET /                   -> the dashboard (frontend/index.html)

Results are cached for CACHE_TTL seconds so the dashboard auto-refresh does not
hammer the upstream APIs. If the live APIs are unreachable (e.g. blocked egress
in a sandbox), the server transparently falls back to bundled demo data so you
can still see how the tool works, and flags `demo: true` in the response.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import demo_data
import sources
from arbitrage import find_opportunities

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="Prediction Market Arbitrage Scanner")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
CACHE_TTL = 30  # seconds

_cache: dict = {"ts": 0.0, "poly": [], "kalshi": [], "demo": False}


def _refresh(force: bool = False):
    """Refresh the market cache, falling back to demo data on failure."""
    now = time.time()
    if not force and (now - _cache["ts"]) < CACHE_TTL and (_cache["poly"] or _cache["kalshi"]):
        return

    demo = False
    try:
        poly = sources.fetch_polymarket()
        kalshi = sources.fetch_kalshi()
        if not poly or not kalshi:
            raise RuntimeError("one or both sources returned no markets")
    except Exception as exc:  # network blocked, API change, etc.
        log.warning("Live fetch failed (%s); using demo data", exc)
        poly, kalshi = demo_data.load()
        demo = True

    _cache.update(ts=now, poly=poly, kalshi=kalshi, demo=demo)


@app.get("/api/opportunities")
def opportunities(
    min_score: float = Query(0.45, ge=0.0, le=1.0),
    min_profit: float = Query(0.0, ge=-1.0, le=1.0),
    min_volume: float = Query(0.0, ge=0.0),
    force: bool = Query(False),
):
    _refresh(force=force)
    opps = find_opportunities(
        _cache["poly"], _cache["kalshi"],
        min_match_score=min_score, min_profit=min_profit,
        min_volume=min_volume,
    )
    return JSONResponse({
        "demo": _cache["demo"],
        "updated": _cache["ts"],
        "poly_count": len(_cache["poly"]),
        "kalshi_count": len(_cache["kalshi"]),
        "count": len(opps),
        "opportunities": [o.to_dict() for o in opps],
    })


@app.get("/api/markets")
def markets(force: bool = Query(False)):
    _refresh(force=force)
    def dump(ms):
        return [
            {
                "platform": m.platform, "question": m.question,
                "yes_ask": m.yes_ask, "no_ask": m.no_ask,
                "volume": m.volume, "url": m.url,
            } for m in ms
        ]
    return JSONResponse({
        "demo": _cache["demo"],
        "polymarket": dump(_cache["poly"]),
        "kalshi": dump(_cache["kalshi"]),
    })


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
