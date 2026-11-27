"""Broadcast per-sweep capture, conversation, inventory and pipeline events.

Inputs are saved frame paths and JSON events from the phone/server pipeline.
Outputs are bounded WebSocket queues plus a latest-state snapshot for viewers.
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2

_MAX_FRAME_SIDE = 960
_FRAME_INTERVAL_S = 1 / 3
_QUEUE_SIZE = 100


@dataclass
class _SweepView:
    queues: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    latest_frame: dict[str, Any] | None = None
    latest_qc: dict[str, Any] | None = None
    latest_inventory: dict[str, Any] | None = None
    latest_progress: dict[str, Any] | None = None
    report_url: str | None = None
    cards_seen: set[int] = field(default_factory=set)
    captions: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=80))
    last_frame_at: float = 0


class ViewerHub:
    """Keep latest per-sweep state and deliver events without blocking capture."""

    def __init__(self) -> None:
        self._sweeps: dict[str, _SweepView] = {}

    def attach(self, sweep_id: str) -> tuple[asyncio.Queue[dict[str, Any]], dict[str, Any]]:
        state = self._state(sweep_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        state.queues.add(queue)
        return queue, self.snapshot(sweep_id)

    def detach(self, sweep_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._state(sweep_id).queues.discard(queue)

    def snapshot(self, sweep_id: str) -> dict[str, Any]:
        state = self._state(sweep_id)
        return {
            "type": "snapshot",
            "sweep_id": sweep_id,
            "frame": state.latest_frame,
            "qc": state.latest_qc,
            "inventory": state.latest_inventory,
            "captions": list(state.captions),
            "progress": state.latest_progress,
            "report_url": state.report_url,
        }

    async def publish(self, sweep_id: str, message: dict[str, Any]) -> None:
        state = self._state(sweep_id)
        kind = message.get("type")
        if kind == "frame":
            state.latest_frame = message
        elif kind == "qc":
            state.cards_seen.update(
                marker for marker in message.get("markers", []) if isinstance(marker, int)
            )
            state.latest_qc = {**message, "cards_seen": sorted(state.cards_seen)}
        elif kind == "inventory":
            state.latest_inventory = message
        elif kind == "pipeline_progress":
            state.latest_progress = message
        elif kind == "packet_ready":
            state.report_url = str(message.get("report_url", "")) or None
        elif kind == "caption":
            state.captions.append(message)
        for queue in tuple(state.queues):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)

    async def publish_saved_frame(self, sweep_id: str, frame_path: Path, t_ms: int) -> None:
        """Encode a face-redacted saved frame and publish no faster than 3 fps."""
        state = self._state(sweep_id)
        now = time.monotonic()
        if now - state.last_frame_at < _FRAME_INTERVAL_S:
            return
        state.last_frame_at = now
        encoded = await asyncio.to_thread(_encode_viewer_jpeg, frame_path)
        if encoded is None:
            return
        await self.publish(
            sweep_id,
            {"type": "frame", "t_ms": t_ms, "jpeg": base64.b64encode(encoded).decode("ascii")},
        )

    def _state(self, sweep_id: str) -> _SweepView:
        return self._sweeps.setdefault(sweep_id, _SweepView())


def _encode_viewer_jpeg(path: Path) -> bytes | None:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return None
    height, width = image.shape[:2]
    scale = min(1.0, _MAX_FRAME_SIDE / max(width, height))
    if scale < 1:
        image = cv2.resize(
            image,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 78])
    return encoded.tobytes() if ok else None
