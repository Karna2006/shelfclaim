"""Transcribe labelled spine crops without completing text from memory.

Input: at most twelve labelled JPEG crops per call. Output: validated visible
text lines and legibility from the reviewed transcription prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.prompts.loader import load_prompt
from app.settings import Settings
from app.vision.schema import SpineTranscriptionResponse
from google import genai
from google.genai import types


@dataclass(frozen=True)
class CropInput:
    crop_id: str
    image_bytes: bytes


class SpineTranscriber(Protocol):
    async def transcribe(
        self, crops: list[CropInput], model: str
    ) -> SpineTranscriptionResponse: ...


class GeminiSpineTranscriber:
    """Generate structured text-only transcripts from reviewed image crops."""

    def __init__(self, settings: Settings) -> None:
        if settings.google_api_key is None:
            raise ValueError("GOOGLE_API_KEY is required for spine transcription")
        self._client = genai.Client(api_key=settings.google_api_key.get_secret_value())

    async def transcribe(self, crops: list[CropInput], model: str) -> SpineTranscriptionResponse:
        if not 1 <= len(crops) <= 12:
            raise ValueError("transcription requests must contain one to twelve crops")
        parts = [types.Part.from_text(text=load_prompt("transcribe"))]
        for crop in crops:
            parts.append(types.Part.from_text(text=f"crop_id: {crop.crop_id}"))
            parts.append(types.Part.from_bytes(data=crop.image_bytes, mime_type="image/jpeg"))
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SpineTranscriptionResponse,
                temperature=0,
            ),
        )
        if not response.text:
            raise ValueError("Transcription model returned no JSON")
        return SpineTranscriptionResponse.model_validate_json(response.text)

    async def close(self) -> None:
        await self._client.aio.aclose()
