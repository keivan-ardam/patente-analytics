"""Pydantic request/response schemas."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class EventIn(BaseModel):
    """An analytics event sent by the browser."""

    type: Literal["session_start", "heartbeat", "session_end"]
    session_id: str = Field(..., min_length=8, max_length=64)
    device_id: str = Field(..., min_length=8, max_length=64)
    # Optional context
    page: Optional[str] = Field(default=None, max_length=200)
    # True when the app runs as an installed PWA (display-mode: standalone).
    pwa: Optional[bool] = Field(default=None)


class StatsOut(BaseModel):
    active_users: int
    active_sessions: int
    total_devices: int
    total_sessions: int
    sessions_today: int
    devices_today: int
