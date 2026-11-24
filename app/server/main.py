"""FastAPI entry point for the local ShelfClaim app.

Input: HTTP requests and static files under `web/`. Output: health status and
the browser app. Implements `docs/05_DATA_SCHEMA.md` §6 and Phase 0.
"""

from __future__ import annotations

from pathlib import Path

from app.settings import Settings, load_settings
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an app instance; settings injection keeps tests isolated."""
    app = FastAPI(title="ShelfClaim", version="0.1.0")
    app.state.settings = settings or load_settings()

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
