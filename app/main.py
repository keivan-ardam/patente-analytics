"""Patente Analytics — FastAPI service.

Receives anonymous session events from the Patente B web app, tracks active
users, and sends Telegram notifications. Designed to run on a Raspberry Pi
behind a Cloudflare Tunnel.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import config
from .models import EventIn, StatsOut
from .tasks import sweep_loop
from . import telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("analytics")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("Database ready at %s", config.DB_PATH)
    logger.info("Telegram enabled: %s", config.telegram_enabled)
    sweep_task = asyncio.create_task(sweep_loop())
    try:
        yield
    finally:
        sweep_task.cancel()


app = FastAPI(title="Patente Analytics", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _country_from_request(request: Request) -> str | None:
    """Cloudflare adds CF-IPCountry with the visitor's country code."""
    return request.headers.get("cf-ipcountry") or None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/event")
async def ingest_event(event: EventIn, request: Request):
    ts = db.now()
    country = _country_from_request(request)
    user_agent = request.headers.get("user-agent")

    if event.type == "session_start":
        is_new_session = db.start_session(
            event.session_id, event.device_id, ts, user_agent, country
        )
        is_new_device = db.upsert_device(
            event.device_id, ts, country, new_session=is_new_session
        )
        if is_new_session:
            stats = db.get_stats(config.SESSION_TIMEOUT_SECONDS, ts)
            # Fire-and-forget notification
            asyncio.create_task(
                telegram.notify_session_start(stats, is_new_device, country)
            )

    elif event.type == "heartbeat":
        db.touch_session(event.session_id, ts)
        db.upsert_device(event.device_id, ts, country, new_session=False)

    elif event.type == "session_end":
        db.end_session(event.session_id, ts)
        if config.NOTIFY_ON_SESSION_END:
            stats = db.get_stats(config.SESSION_TIMEOUT_SECONDS, ts)
            asyncio.create_task(telegram.notify_session_end(stats))

    return {"ok": True}


@app.get("/stats", response_model=StatsOut)
async def stats():
    return db.get_stats(config.SESSION_TIMEOUT_SECONDS, db.now())
