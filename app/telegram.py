"""Telegram bot: notifications + interactive inline-keyboard commands.

Sends session notifications and responds to button presses ("Live Stats",
"Today", "7-Day Report") via long-polling getUpdates.
"""

import time
import logging
import httpx

from .config import config
from . import db

logger = logging.getLogger("analytics.telegram")

_BASE = "https://api.telegram.org/bot{token}/{method}"

# Cooldown state for "new session" notifications
_last_notify_ts: float = 0.0
_pending_sessions: int = 0


def _url(method: str) -> str:
    return _BASE.format(token=config.TELEGRAM_BOT_TOKEN, method=method)


# Public dashboard URL (rich time-series charts live here now).
_DASHBOARD_URL = "https://analytics.patentechi.it/"


# Minimal inline keyboard: a live snapshot + a link to the full dashboard.
def _main_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Live", "callback_data": "stats"},
                {"text": "📈 Dashboard", "url": _DASHBOARD_URL},
            ],
        ]
    }


async def send_message(text: str, with_keyboard: bool = False) -> None:
    if not config.telegram_enabled:
        logger.debug("Telegram disabled; skipping: %s", text)
        return
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if with_keyboard:
        payload["reply_markup"] = _main_keyboard()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_url("sendMessage"), json=payload)
            if resp.status_code != 200:
                logger.warning(
                    "Telegram send failed: %s %s", resp.status_code, resp.text
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram send error: %s", exc)


async def _answer_callback(callback_id: str) -> None:
    """Acknowledge a button press so the loading spinner stops."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                _url("answerCallbackQuery"),
                json={"callback_query_id": callback_id},
            )
    except Exception:  # noqa: BLE001
        pass


# ---------- Message builders ----------


def _stats_text(stats: dict) -> str:
    return (
        f"📊 <b>Live</b>\n\n"
        f"👥 Active now: <b>{stats['active_users']}</b> users "
        f"({stats['active_sessions']} sessions)\n"
        f"📅 Today: {stats['sessions_today']} sessions · {stats['devices_today']} users\n\n"
        f"📈 Full charts: {_DASHBOARD_URL}"
    )


# ---------- Notifications ----------


async def notify_session_start(
    stats: dict, is_new_device: bool, country: str | None
) -> None:
    global _last_notify_ts, _pending_sessions

    cooldown = config.NOTIFY_COOLDOWN_SECONDS
    _pending_sessions += 1

    now = time.time()
    if cooldown > 0 and (now - _last_notify_ts) < cooldown:
        return

    count = _pending_sessions
    _pending_sessions = 0
    _last_notify_ts = now

    new_badge = " 🆕" if is_new_device else ""
    header = f"🟢 New session{new_badge}" if count == 1 else f"🟢 {count} new sessions"
    text = (
        f"{header} · "
        f"👥 {stats['active_users']} active ({stats['active_sessions']} sess)"
    )
    # Quiet ping: no keyboard. Tap /stats or the menu when you want detail.
    await send_message(text, with_keyboard=False)


async def notify_session_end(stats: dict) -> None:
    if not config.NOTIFY_ON_SESSION_END:
        return
    await send_message(
        f"🔴 Session ended\n"
        f"👥 Active now: <b>{stats['active_users']}</b> users "
        f"({stats['active_sessions']} sessions)"
    )


# ---------- Button / command handling (long-polling) ----------


async def _handle_callback(data: str) -> None:
    ts = db.now()
    stats = db.get_stats(config.SESSION_TIMEOUT_SECONDS, ts)
    if data == "stats":
        await send_message(_stats_text(stats), with_keyboard=True)


async def _handle_command(text: str) -> None:
    ts = db.now()
    stats = db.get_stats(config.SESSION_TIMEOUT_SECONDS, ts)
    cmd = text.strip().lower().lstrip("/")
    if cmd in ("start", "menu", "help"):
        await send_message(
            "👋 <b>Patente Analytics</b>\nTap a button for live data:",
            with_keyboard=True,
        )
    elif cmd == "stats":
        await send_message(_stats_text(stats), with_keyboard=True)
    else:
        await send_message("Tap a button below for data.", with_keyboard=True)


async def poll_updates_loop() -> None:
    """Long-poll Telegram for button presses and commands."""
    if not config.telegram_enabled:
        logger.info("Telegram disabled — not polling for commands.")
        return

    offset = 0
    logger.info("Telegram command polling started.")
    while True:
        try:
            async with httpx.AsyncClient(timeout=40) as client:
                resp = await client.get(
                    _url("getUpdates"),
                    params={"offset": offset, "timeout": 30},
                )
                if resp.status_code != 200:
                    await _sleep(5)
                    continue
                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    # Only respond to the configured chat
                    if "callback_query" in update:
                        cq = update["callback_query"]
                        chat_id = str(cq.get("message", {}).get("chat", {}).get("id"))
                        if chat_id == str(config.TELEGRAM_CHAT_ID):
                            await _answer_callback(cq["id"])
                            await _handle_callback(cq.get("data", ""))
                    elif "message" in update:
                        msg = update["message"]
                        chat_id = str(msg.get("chat", {}).get("id"))
                        text = msg.get("text", "")
                        if chat_id == str(config.TELEGRAM_CHAT_ID) and text:
                            await _handle_command(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Poll error: %s", exc)
            await _sleep(5)


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
