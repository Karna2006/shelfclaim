"""Serve the laptop viewer stream for one saved sweep.

Input is a sweep ID and viewer WebSocket; output is cached state followed by
capture, caption, inventory and pipeline events for docs/06's live protocol.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

_SWEEP_ID = re.compile(r"sw_\d{8}_\d{6}_[0-9a-f]{4}")


async def viewer_socket(websocket: WebSocket, sweep_id: str) -> None:
    settings = websocket.app.state.settings
    sweep_dir = settings.sweeps_dir / sweep_id
    if not _SWEEP_ID.fullmatch(sweep_id) or not (sweep_dir / "sweep.json").is_file():
        await websocket.close(code=1008, reason="Unknown sweep")
        return

    hub = websocket.app.state.viewer_hub
    await websocket.accept()
    queue, snapshot = hub.attach(sweep_id)
    await websocket.send_json(snapshot)
    sender = asyncio.create_task(_send_queue(websocket, queue))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass
        hub.detach(sweep_id, queue)


async def _send_queue(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        await websocket.send_json(await queue.get())
