"""Validate the constrained output returned by the vision detector.

Input: Gemini JSON object. Output: bounded normalized detections, with text
fields limited to class labels and item categories; implements architecture §1.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VisionObject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cls: str = Field(min_length=1, max_length=40)
    box_2d: list[int] = Field(min_length=4, max_length=4)
    angle_deg: float = Field(default=90, ge=-180, le=360)
    item_category: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=40)


class VisionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    image_quality: str = "unknown"
    objects: list[VisionObject] = Field(default_factory=list, max_length=2000)


class SpineLine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(max_length=300)
    kind_guess: str = Field(default="other", max_length=20)


class SpineTranscription(BaseModel):
    model_config = ConfigDict(extra="ignore")

    crop_id: str = Field(min_length=1, max_length=80)
    readable: bool = False
    orientation: str = Field(default="upright", max_length=20)
    lines: list[SpineLine] = Field(default_factory=list, max_length=30)
    legibility: float = Field(default=0, ge=0, le=1)


class SpineTranscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[SpineTranscription] = Field(default_factory=list, max_length=12)
