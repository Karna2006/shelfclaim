"""Run a scripted conversation through the production AgentLoop.

Input: a real sweep's saved JPEG frames and normal app settings. Output:
per-turn success/model/latency plus aggregate soak statistics in a temporary
sweep directory, without modifying the source sweep.
"""

from __future__ import annotations

import math
import shutil
import tempfile
import time
from pathlib import Path

import cv2
from app.capture.storage import list_frames
from app.live.agent import FALLBACK_LINE, AgentLoop
from app.live.client import GeminiFlashClient
from app.live.rate_limit import ModelRateLimiter
from app.live.session import LiveSessionContext
from app.packet.models import Sweep
from app.settings import Settings

_CONVERSATION = [
    "Yes, India and rupees",
    "Which book is this?",
    "What's it worth?",
    "It's a print",
    "That painting is an original",
    "This is a first edition",
    "This book is signed",
    "That item is rare",
    "That's not mine",
    "Skip that shelf",
    "How many books?",
    "What did I miss?",
    "I'm done",
    "What is this?",
    "Which book is this?",
    "What's it worth?",
    "Please exclude that shelf",
    "It's a print",
    "How many books?",
    "That's all",
]


async def run_agent_soak(settings: Settings, source: Path, turns: int = 20) -> dict[str, object]:
    """Exercise the real loop while borrowing frames from a saved sweep."""
    if turns < 1:
        raise ValueError("turns must be positive")
    source_frames = list_frames(source)
    if not source_frames:
        raise ValueError(f"No saved frames in {source}")
    with tempfile.TemporaryDirectory(prefix="shelfclaim-agent-soak-") as temporary:
        sweep_dir = Path(temporary)
        sweep = Sweep.model_validate_json((source / "sweep.json").read_text(encoding="utf-8"))
        (sweep_dir / "sweep.json").write_text(sweep.model_dump_json(indent=2), encoding="utf-8")
        (sweep_dir / "frames.jsonl").write_text(
            "".join(frame.model_dump_json() + "\n" for frame in source_frames), encoding="utf-8"
        )
        for frame in source_frames:
            target = sweep_dir / frame.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / frame.path, target)
        stage = source / "s03_books_raw.json"
        if stage.is_file():
            shutil.copy2(stage, sweep_dir / stage.name)
        session = LiveSessionContext(sweep.id, sweep_dir)
        client = GeminiFlashClient(settings, ModelRateLimiter(settings.config.llm))
        agent = AgentLoop(settings, session, client)
        latencies: list[float] = []
        successes = fallbacks = 0
        try:
            opening = await agent.greet()
            successes += opening.text != FALLBACK_LINE
            print(f"0\t{agent.last_model_used}\t0\t{opening.text}")
            for index in range(turns):
                frame = source_frames[index % len(source_frames)]
                session.latest_capture_seq = frame.seq
                session.latest_client_t_ms = frame.t_ms
                image = _prepare_frame((source / frame.path).read_bytes())
                utterance = _CONVERSATION[index % len(_CONVERSATION)]
                started = time.perf_counter()
                reply = await agent.handle_user_text(utterance, image)
                elapsed = (time.perf_counter() - started) * 1000
                latencies.append(elapsed)
                success = reply.text != FALLBACK_LINE
                successes += success
                fallbacks += not success
                print(f"{index + 1}\t{agent.last_model_used}\t{elapsed:.0f}\t{reply.text}")
                if reply.start_sweep_after_reply:
                    await agent.complete_reply(reply)
        finally:
            await client.close()
        ordered = sorted(latencies)
        total = turns + 1
        summary: dict[str, object] = {
            "user_turns": turns,
            "replies_including_greeting": total,
            "successes": successes,
            "success_rate_pct": round(successes * 100 / total, 1),
            "fallback_count": fallbacks,
            "p50_latency_ms": round(_percentile(ordered, 0.50)),
            "p95_latency_ms": round(_percentile(ordered, 0.95)),
        }
        print(f"SUMMARY {summary}")
        return summary


def _prepare_frame(data: bytes) -> bytes:
    """Ensure test attachments match the browser's 768 px/q0.6 payload policy."""
    import numpy as np

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode source sweep frame")
    height, width = image.shape[:2]
    ratio = min(1.0, 768 / max(width, height))
    if ratio < 1:
        image = cv2.resize(image, (round(width * ratio), round(height * ratio)))
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 60])
    if not ok:
        raise ValueError("Could not encode low-resolution soak frame")
    return encoded.tobytes()


def _percentile(values: list[float], percentile: float) -> float:
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)
