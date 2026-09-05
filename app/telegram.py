"""Telegram bot notifications with a cooldown to avoid spam."""

import time
import logging
import httpx

from .config import config

logger = logging.getLogger("analytics.telegram")

_API = "https://api.telegram.org/bot{token}/sendMessage"

# Timestamp of the last "new session" notification (for cooldown batching).
_last_notify_ts: float = 0.0
# Number of sessions accumulated during the cooldown window.
_pending_sessions: int = 0


async def send_message(text: str) -> None:
    """Send a raw message to the configured chat."""
    if not config.telegram_enabled:
        logger.debug("Telegram disabled (missing token/chat id); skipping: %s", text)
        return
    url = _API.format(token=config.TELEGRAM_BOT_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code != 200:
                logger.warning("Telegram send failed: %s %s", resp.status_code, resp.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram send error: %s", exc)


async def notify_session_start(stats: dict, is_new_device: bool, country: str | None) -> None:
    """Notify about a new session, respecting the cooldown window.

    If NOTIFY_COOLDOWN_SECONDS is 0, notifies immediately every time.
    Otherwise, batches sessions and sends a summary at most once per window.
    """
    global _last_notify_ts, _pending_sessions

    cooldown = config.NOTIFY_COOLDOWN_SECONDS
    _pending_sessions += 1

    now = time.time()
    if cooldown > 0 and (now - _last_notify_ts) < cooldown:
        # Still within cooldown — accumulate silently.
        return

    count = _pending_sessions
    _pending_sessions = 0
    _last_notify_ts = now

    flag = f" {country}" if country else ""
    new_badge = " 🆕" if is_new_device else ""

    if count == 1:
        header = f"🟢 New session{new_badge}{flag}"
    else:
        header = f"🟢 {count} new sessions{flag}"

    text = (
        f"{header}\n"
        f"👥 Active now: <b>{stats['active_users']}</b> users "
        f"({stats['active_sessions']} sessions)\n"
        f"📅 Today: {stats['sessions_today']} sessions, {stats['devices_today']} users\n"
        f"📊 Total: {stats['total_devices']} users, {stats['total_sessions']} sessions"
    )
    await send_message(text)


async def notify_session_end(stats: dict) -> None:
    """Notify about a session ending (only if enabled)."""
    if not config.NOTIFY_ON_SESSION_END:
        return
    text = (
        f"🔴 Session ended\n"
        f"👥 Active now: <b>{stats['active_users']}</b> users "
        f"({stats['active_sessions']} sessions)"
    )
    await send_message(text)
