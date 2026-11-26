"""FastAPI entry point for the local ShelfClaim app.

Input: HTTP requests and static files under `web/`. Output: health status and
the browser app. Implements `docs/05_DATA_SCHEMA.md` §6 and Phase 0.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.capture.faces import YuNetDetectorCache
from app.capture.storage import create_sweep
from app.live.client import GeminiFlashClient, LlmClient
from app.live.rate_limit import ModelRateLimiter
from app.live.session import LiveSessionRegistry
from app.server.ws_capture import capture_socket
from app.server.ws_live import live_socket
from app.settings import Settings, load_settings
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class CreateSweepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: str = Field(min_length=1, max_length=512)


def create_app(
    settings: Settings | None = None,
    llm_client_factory: Callable[[Settings, ModelRateLimiter], LlmClient] | None = None,
) -> FastAPI:
    """Build an app instance; settings injection keeps tests isolated."""
    app = FastAPI(title="ShelfClaim", version="0.1.0")
    app.state.settings = settings or load_settings()
    app.state.live_sessions = LiveSessionRegistry()
    app.state.face_detector_cache = YuNetDetectorCache()
    app.state.model_limiter = ModelRateLimiter(app.state.settings.config.llm)
    app.state.llm_client_factory = llm_client_factory or GeminiFlashClient

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/sweeps", tags=["capture"])
    async def create_sweep_route(payload: CreateSweepRequest) -> dict[str, object]:
        sweep = create_sweep(app.state.settings.sweeps_dir, payload.device, app.state.settings)
        app.state.live_sessions.create(
            sweep.id,
            app.state.settings.sweeps_dir / sweep.id,
            app.state.settings.config.agent.echo_window_s,
            app.state.settings.config.agent.echo_match_ratio,
        )
        return {
            "sweep_id": sweep.id,
            "ws_path": "/ws/capture",
            "hires_fps": app.state.settings.hires_fps,
            "capture": app.state.settings.config.capture.model_dump(),
            "live_frame_max_side": app.state.settings.config.agent.live_frame_max_side,
            "live_frame_quality": app.state.settings.config.agent.live_frame_quality,
            "live_ws_path": f"/ws/live/{sweep.id}",
        }

    app.websocket("/ws/capture")(capture_socket)
    app.websocket("/ws/live/{sweep_id}")(live_socket)

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
