"""Call the configured Gemini vision model behind a small typed interface.

Input: saved JPEG bytes and the detector prompt. Output: validated JSON boxes;
network access uses google-genai and is isolated for fixture-backed tests.
"""

from __future__ import annotations

from typing import Protocol

from app.prompts.loader import load_prompt
from app.settings import Settings
from app.vision.schema import FrameVisionResponse, VisionResponse
from google import genai
from google.genai import types


class VisionDetector(Protocol):
    async def detect(self, image_bytes: bytes, model: str) -> VisionResponse: ...


class GeminiVisionDetector:
    """Use JSON structured output without exposing the API key to logs."""

    def __init__(self, settings: Settings) -> None:
        if settings.google_api_key is None:
            raise ValueError("GOOGLE_API_KEY is required for vision detection")
        self._client = genai.Client(
            api_key=settings.google_api_key.get_secret_value(),
            http_options=types.HttpOptions(
                timeout=90_000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )

    async def detect(self, image_bytes: bytes, model: str) -> VisionResponse:
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=[
                types.Part.from_text(text=load_prompt("detect")),
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FrameVisionResponse,
                temperature=0,
            ),
        )
        if not response.text:
            raise ValueError("Vision model returned no JSON")
        return VisionResponse.model_validate_json(response.text)

    async def detect_still(self, image_bytes: bytes, model: str) -> FrameVisionResponse:
        """Use a compact schema for an interactive single-image inspection."""
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=[
                types.Part.from_text(text=load_prompt("detect")),
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FrameVisionResponse,
                temperature=0,
            ),
        )
        if not response.text:
            raise ValueError("Vision model returned no JSON")
        return FrameVisionResponse.model_validate_json(response.text)

    async def close(self) -> None:
        await self._client.aio.aclose()
