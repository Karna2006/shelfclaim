"""Rebuild and compare the failing phone request without exposing settings.

Input: a sweep transcript and its frame manifest. Output: four real Gemini
request outcomes with local request-shape metadata. Credentials are loaded
through app.settings and are never printed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import cv2
from app.capture.storage import list_frames
from app.live.client import GeminiFlashClient
from app.live.models import AgentMessage
from app.live.rate_limit import ModelRateLimiter
from app.live.resilience import _request_shape
from app.live.tools import TOOL_SCHEMAS
from app.prompts.loader import load_prompt
from app.settings import load_settings


def _history_from_transcript(sweep: Path) -> list[AgentMessage]:
    lines = [
        json.loads(line)
        for line in (sweep / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    history: list[AgentMessage] = []
    for line in lines:
        speaker, text = line.get("speaker"), str(line.get("text", ""))
        if speaker == "user":
            history.append(AgentMessage(role="user", text=text))
        elif speaker == "agent" and text != "Sorry, say that again?":
            history.append(AgentMessage(role="model", text=text))
        elif speaker == "cue":
            history.append(AgentMessage(role="model", text=f"[Capture cue already spoken: {text}]"))
    return history


def _current_frame(sweep: Path) -> tuple[bytes, int] | None:
    records = list_frames(sweep)
    if not records:
        return None
    record = records[-1]
    image = cv2.imread(str(sweep / record.path))
    if image is None:
        return None
    height, width = image.shape[:2]
    scale = min(1.0, 768 / max(width, height))
    if scale < 1:
        image = cv2.resize(image, (round(width * scale), round(height * scale)))
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return (encoded.tobytes(), record.seq) if ok else None


async def _run(sweep: Path) -> None:
    settings = load_settings()
    client = GeminiFlashClient(settings, ModelRateLimiter(settings.config.llm))
    history = _history_from_transcript(sweep)
    frame = _current_frame(sweep)
    variants: list[tuple[str, list[AgentMessage]]] = [
        ("as_is_reconstructed", history),
        ("without_images", [item.model_copy(update={"image_jpeg": None}) for item in history]),
    ]
    if frame is not None:
        current_image, sequence = frame
        with_current = [item.model_copy(deep=True) for item in history]
        last_user = max(
            index for index, message in enumerate(with_current) if message.role == "user"
        )
        with_current[last_user] = with_current[last_user].model_copy(
            update={
                "image_jpeg": current_image,
                "text": f"{with_current[last_user].text or ''}\n[frame f_{sequence:06d}]",
            }
        )
        variants.append(("current_turn_image_only", with_current))
    turns = [
        index
        for index, message in enumerate(history)
        if message.role == "user" and not message.tool_results
    ]
    start = turns[-6] if len(turns) > 6 else 0
    variants.append(("last_six_turns", history[start:]))
    try:
        for name, request_history in variants:
            images = [message for message in request_history if message.image_jpeg is not None]
            shape = {
                **_request_shape(request_history, load_prompt("agent_system"), len(TOOL_SCHEMAS)),
                "history_messages": len(request_history),
                "history_turns": sum(
                    1
                    for message in request_history
                    if message.role == "user" and not message.tool_results
                ),
                "image_parts": len(images),
                "image_bytes": sum(len(message.image_jpeg or b"") for message in images),
                "tool_count": len(TOOL_SCHEMAS),
            }
            try:
                response = await client.generate(
                    model=settings.agent_model,
                    system_prompt=load_prompt("agent_system"),
                    history=request_history,
                    tools=TOOL_SCHEMAS,
                    thinking_level="minimal",
                    timeout_s=settings.config.agent.timeout_s,
                    max_output_tokens=1024,
                )
                print(
                    json.dumps(
                        {
                            "variant": name,
                            **shape,
                            "success": bool(response.text or response.tool_calls),
                            "text": response.text,
                            "diagnostics": response.diagnostics,
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception as exc:
                print(
                    json.dumps(
                        {
                            "variant": name,
                            **shape,
                            "success": False,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    )
                )
    finally:
        await client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("sweep", type=Path)
    asyncio.run(_run(parser.parse_args().sweep))
