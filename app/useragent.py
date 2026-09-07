"""Minimal, dependency-free User-Agent classification.

Turns a raw UA string into coarse buckets: device type, OS, browser, and a
bot flag. Intentionally simple — good enough for anonymous usage analytics,
no external UA-parsing library needed.
"""

from __future__ import annotations

_BOT_MARKERS = (
    "bot",
    "crawler",
    "spider",
    "crawl",
    "slurp",
    "hubspot",
    "shap-user",
    "headless",
    "python-requests",
    "curl/",
    "wget",
    "monitor",
    "preview",
    "facebookexternalhit",
    "embedly",
)


def is_bot(ua: str | None) -> bool:
    if not ua:
        return False
    low = ua.lower()
    return any(m in low for m in _BOT_MARKERS)


def classify(ua: str | None) -> dict:
    """Return {device, os, browser, is_bot} for a UA string."""
    if not ua:
        return {"device": "unknown", "os": "unknown", "browser": "unknown", "is_bot": False}

    low = ua.lower()
    bot = is_bot(ua)

    # --- OS ---
    if "iphone" in low or "ipod" in low:
        os_name = "iOS"
    elif "ipad" in low:
        os_name = "iPadOS"
    elif "android" in low:
        os_name = "Android"
    elif "mac os x" in low or "macintosh" in low:
        os_name = "macOS"
    elif "windows" in low:
        os_name = "Windows"
    elif "cros" in low:
        os_name = "ChromeOS"
    elif "linux" in low:
        os_name = "Linux"
    else:
        os_name = "other"

    # --- Device type ---
    if bot:
        device = "bot"
    elif "ipad" in low or ("tablet" in low) or ("android" in low and "mobile" not in low):
        device = "tablet"
    elif "iphone" in low or "ipod" in low or "mobile" in low or "android" in low:
        device = "phone"
    else:
        device = "desktop"

    # --- Browser (order matters: Edge/Chrome/Safari overlap) ---
    if "edg/" in low or "edga/" in low or "edgios/" in low:
        browser = "Edge"
    elif "opr/" in low or "opera" in low:
        browser = "Opera"
    elif "firefox/" in low or "fxios/" in low:
        browser = "Firefox"
    elif "samsungbrowser" in low:
        browser = "Samsung"
    elif "chrome/" in low or "crios/" in low:
        browser = "Chrome"
    elif "safari/" in low and ("version/" in low or "iphone" in low or "ipad" in low):
        browser = "Safari"
    else:
        browser = "other"

    return {"device": device, "os": os_name, "browser": browser, "is_bot": bot}
