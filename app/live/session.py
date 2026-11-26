"""Hold per-sweep live-agent context in the FastAPI session registry.

Input is a sweep ID and folder; output is shared latest-frame, transcript,
echo-guard, and WebSocket state for the capture and live channels.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from app.live.echo_guard import EchoGuard

if TYPE_CHECKING:
    from app.live.agent import AgentLoop
    from fastapi import WebSocket


@dataclass
class LiveSessionContext:
    sweep_id: str
    sweep_dir: Path
    started_at: float = field(default_factory=time.monotonic)
    latest_capture_seq: int | None = None
    latest_client_t_ms: int = 0
    latest_user_text: str = ""
    latest_frame_jpeg: bytes | None = None
    locale_confirmed: bool = False
    capture_stop_requested: bool = False
    agent: AgentLoop | None = None
    websocket: WebSocket | None = None
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    echo_guard: EchoGuard = field(default_factory=EchoGuard)


class LiveSessionRegistry:
    """Own the only application-wide mutable session map, keyed by sweep ID."""

    def __init__(self) -> None:
        self._sessions: dict[str, LiveSessionContext] = {}

    def create(
        self, sweep_id: str, sweep_dir: Path, echo_window_s: float, echo_ratio: int
    ) -> LiveSessionContext:
        context = LiveSessionContext(
            sweep_id=sweep_id,
            sweep_dir=sweep_dir,
            echo_guard=EchoGuard(echo_window_s, echo_ratio),
        )
        self._sessions[sweep_id] = context
        return context

    def get(self, sweep_id: str) -> LiveSessionContext | None:
        return self._sessions.get(sweep_id)

    def remove(self, sweep_id: str) -> None:
        self._sessions.pop(sweep_id, None)
