"""Receive capture frames, persist them, then acknowledge saved evidence.

Input is the `/ws/capture` protocol in `docs/06_USER_FLOWS.md` §5.2; output is
QC plus an ack after a redacted JPEG and frame record are written.
"""

from __future__ import annotations

import json
import logging
import math
import re

from app.capture.monitor import CaptureMonitor
from app.capture.storage import FrameHeader, save_frame
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

logger = logging.getLogger(__name__)
_SWEEP_ID = re.compile(r"sw_\d{8}_\d{6}_[0-9a-f]{4}")


def parse_frame_packet(packet: bytes) -> tuple[FrameHeader, bytes]:
    """Parse a four-byte unsigned big-endian JSON length and trailing JPEG."""
    if len(packet) < 5:
        raise ValueError("frame packet must include a header and JPEG payload")
    header_length = int.from_bytes(packet[:4], byteorder="big", signed=False)
    if header_length == 0 or header_length >= len(packet) - 2:
        raise ValueError("frame packet has an invalid header length")
    header_bytes = packet[4 : 4 + header_length]
    jpeg_bytes = packet[4 + header_length :]
    if not jpeg_bytes.startswith(b"\xff\xd8"):
        raise ValueError("frame packet does not contain a JPEG payload")
    try:
        header = FrameHeader.model_validate_json(header_bytes)
    except (ValidationError, ValueError) as exc:
        raise ValueError("frame packet has an invalid JSON header") from exc
    return header, jpeg_bytes


async def capture_socket(websocket: WebSocket, sweep_id: str) -> None:
    """Validate a sweep session and process binary frames and motion samples."""
    settings = websocket.app.state.settings
    sweep_dir = settings.sweeps_dir / sweep_id
    if not _SWEEP_ID.fullmatch(sweep_id) or not (sweep_dir / "sweep.json").is_file():
        await websocket.close(code=1008, reason="Unknown sweep")
        return

    await websocket.accept()
    monitor = CaptureMonitor(settings.config.capture, settings.config.cues)
    fast_motion_since_ms: int | None = None
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                try:
                    header, jpeg_bytes = parse_frame_packet(message["bytes"])
                    if header.motion is not None:
                        fast_motion_since_ms = _update_fast_motion(
                            fast_motion_since_ms,
                            header.t_ms,
                            header.motion.gyro_dps,
                            settings.config.capture.speed_max_dps,
                        )
                    fast_sustained = (
                        fast_motion_since_ms is not None
                        and header.t_ms - fast_motion_since_ms
                        >= settings.config.capture.speed_sustain_s * 1000
                    )
                    result = save_frame(
                        sweep_dir,
                        header,
                        jpeg_bytes,
                        settings,
                        fast_sustained,
                        websocket.app.state.face_detector_cache,
                    )
                except (ValueError, ValidationError) as exc:
                    logger.info("Rejected capture frame: %s", exc)
                    await websocket.send_json(
                        {"type": "error", "message": "Invalid capture frame", "recoverable": True}
                    )
                    continue
                context = websocket.app.state.live_sessions.get(sweep_id)
                if context is not None:
                    context.latest_capture_seq = result.record.seq
                    context.latest_client_t_ms = header.t_ms
                    candidate = monitor.observe(result.record, user_speaking=context.user_speaking)
                    if candidate is not None:
                        from app.server.ws_live import send_cue

                        await send_cue(
                            context,
                            candidate.text,
                            candidate.priority,
                            kind=candidate.kind,
                            metrics=candidate.metrics,
                        )
                await websocket.send_json(result.qc_message())
                await websocket.send_json({"type": "ack", "seq": header.seq})
            elif message.get("text"):
                sample = _accept_motion_sample(message["text"])
                if sample is not None:
                    t_ms, gyro_dps = sample
                    fast_motion_since_ms = _update_fast_motion(
                        fast_motion_since_ms,
                        t_ms,
                        gyro_dps,
                        settings.config.capture.speed_max_dps,
                    )
    except WebSocketDisconnect:
        return


def _accept_motion_sample(text: str) -> tuple[int, float | None] | None:
    """Parse valid motion-only samples and ignore malformed or unrelated messages."""
    try:
        sample = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(sample, dict) or sample.get("type") != "motion_only":
        return None
    t_ms, gyro_dps = sample.get("t_ms"), sample.get("gyro_dps")
    if isinstance(t_ms, bool) or not isinstance(t_ms, int) or t_ms < 0:
        return None
    if gyro_dps is not None and (
        isinstance(gyro_dps, bool)
        or not isinstance(gyro_dps, (int, float))
        or not math.isfinite(gyro_dps)
        or gyro_dps < 0
    ):
        return None
    return t_ms, float(gyro_dps) if gyro_dps is not None else None


def _update_fast_motion(
    started_at_ms: int | None,
    t_ms: int,
    gyro_dps: float | None,
    speed_threshold_dps: float,
) -> int | None:
    """Start a fast-motion window at the first over-threshold sample; clear it when stable."""
    if gyro_dps is None or gyro_dps <= speed_threshold_dps:
        return None
    return t_ms if started_at_ms is None else started_at_ms
