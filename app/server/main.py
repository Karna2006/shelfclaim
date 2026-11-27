"""FastAPI entry point for the local ShelfClaim app.

Input: HTTP requests and static files under `web/`. Output: health status and
the browser app. Implements `docs/05_DATA_SCHEMA.md` §6 and Phase 0.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from app.capture.faces import YuNetDetectorCache
from app.capture.storage import create_sweep
from app.live.client import GeminiFlashClient, LlmClient
from app.live.rate_limit import ModelRateLimiter
from app.live.session import LiveSessionRegistry
from app.server.pages import (
    architecture_page,
    latest_sweep_id,
    report_path,
    sweep_list_page,
    viewer_page,
)
from app.server.viewer import ViewerHub
from app.server.ws_capture import capture_socket
from app.server.ws_live import live_socket
from app.server.ws_viewer import viewer_socket
from app.settings import Settings, load_settings
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
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
    app.state.viewer_hub = ViewerHub()
    app.state.face_detector_cache = YuNetDetectorCache()
    app.state.model_limiter = ModelRateLimiter(app.state.settings.config.llm)
    app.state.llm_client_factory = llm_client_factory or GeminiFlashClient

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/sweeps", tags=["capture"])
    async def create_sweep_route(payload: CreateSweepRequest) -> dict[str, object]:
        sweep = create_sweep(app.state.settings.sweeps_dir, payload.device, app.state.settings)
        context = app.state.live_sessions.create(
            sweep.id,
            app.state.settings.sweeps_dir / sweep.id,
            app.state.settings.config.agent.echo_window_s,
            app.state.settings.config.agent.echo_match_ratio,
            earphones_mode=app.state.settings.config.agent.earphones_mode,
            cue_max_words=app.state.settings.config.agent.cue_max_words,
            cue_suppress_after_user_s=app.state.settings.config.agent.cue_suppress_after_user_s,
        )
        context.viewer_hub = app.state.viewer_hub
        return {
            "sweep_id": sweep.id,
            "ws_path": "/ws/capture",
            "hires_fps": app.state.settings.hires_fps,
            "capture": app.state.settings.config.capture.model_dump(),
            "live_frame_max_side": app.state.settings.config.agent.live_frame_max_side,
            "live_frame_quality": app.state.settings.config.agent.live_frame_quality,
            "earphones_mode": app.state.settings.config.agent.earphones_mode,
            "interim_force_final_ms": round(
                app.state.settings.config.agent.interim_force_final_s * 1000
            ),
            "live_ws_path": f"/ws/live/{sweep.id}",
        }

    @app.get("/api/sweeps/{sweep_id}/report", tags=["capture"])
    async def get_report(sweep_id: str) -> FileResponse:
        if not re.fullmatch(r"sw_\d{8}_\d{6}_[0-9a-f]{4}", sweep_id):
            raise HTTPException(status_code=404, detail="Report not found")
        report = app.state.settings.sweeps_dir / sweep_id / "report.html"
        if not report.is_file():
            raise HTTPException(status_code=404, detail="Report not found")
        return FileResponse(report, media_type="text/html")

    @app.get("/viewer", response_class=HTMLResponse, tags=["viewer"])
    async def viewer_latest() -> HTMLResponse:
        return viewer_page(WEB_DIR, latest_sweep_id(app.state.settings.sweeps_dir))

    @app.get("/viewer/{sweep_id}", response_class=HTMLResponse, tags=["viewer"])
    async def viewer_sweep(sweep_id: str) -> HTMLResponse:
        if not re.fullmatch(r"sw_\d{8}_\d{6}_[0-9a-f]{4}", sweep_id):
            raise HTTPException(status_code=404, detail="Sweep not found")
        sweep_dir = app.state.settings.sweeps_dir / sweep_id
        if not (sweep_dir / "sweep.json").is_file():
            raise HTTPException(status_code=404, detail="Sweep not found")
        return viewer_page(WEB_DIR, sweep_id)

    @app.get("/sweeps", response_class=HTMLResponse, tags=["reports"])
    async def list_sweeps() -> HTMLResponse:
        return sweep_list_page(app.state.settings.sweeps_dir)

    @app.get("/sweeps/{sweep_id}/", tags=["reports"])
    async def sweep_report(sweep_id: str) -> FileResponse:
        return FileResponse(
            report_path(app.state.settings.sweeps_dir, sweep_id), media_type="text/html"
        )

    @app.get("/sweeps/{sweep_id}/{asset_path:path}", tags=["reports"])
    async def sweep_asset(sweep_id: str, asset_path: str) -> FileResponse:
        path = report_path(app.state.settings.sweeps_dir, sweep_id, asset_path)
        return FileResponse(path)

    @app.get("/architecture", response_class=HTMLResponse, tags=["docs"])
    async def architecture() -> HTMLResponse:
        return architecture_page(Path(__file__).resolve().parents[2] / "docs" / "architecture.md")

    app.websocket("/ws/capture")(capture_socket)
    app.websocket("/ws/live/{sweep_id}")(live_socket)
    app.websocket("/ws/viewer/{sweep_id}")(viewer_socket)

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
