"""Pydantic document models for sweep and stage JSON artifacts.

Input/output: JSON documents under a sweep folder. Fields mirror
`docs/05_DATA_SCHEMA.md` §2; extra fields remain readable for later stages.
"""

from __future__ import annotations

from typing import Any, Literal

from app.packet.models import BBox
from pydantic import BaseModel, ConfigDict, Field


class ArtifactModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class MarkerObservation(ArtifactModel):
    id: int
    corners: list[tuple[float, float]]


class FrameRecord(ArtifactModel):
    seq: int = Field(ge=0)
    t_ms: int = Field(ge=0)
    path: str
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    blur: float | None = None
    glare: float | None = None
    exposure: float | None = None
    gyro_dps: float | None = None
    qc_verdict: (
        Literal["ok", "blurry", "low_light_blur", "glare", "dark", "bright", "fast"] | None
    ) = None
    gravity: tuple[float, float, float] | None = None
    markers: list[MarkerObservation] = Field(default_factory=list)
    face_boxes: list[tuple[int, int, int, int, float | None]] = Field(default_factory=list)
    faces_blurred: int = Field(default=0, ge=0)


class Event(ArtifactModel):
    t_ms: int = Field(ge=0)
    type: Literal[
        "cue_sent",
        "cue_suppressed",
        "echo_dropped",
        "transcript_cleaned",
        "intent_routed",
        "agent_reply",
        "recognition_paused",
        "recognition_resumed",
        "numeric_claim_blocked",
        "agent_fallback",
        "agent_response_diagnostics",
        "agent_request",
        "agent_attempt",
        "reply_truncated",
        "tool_call",
        "tool_result",
        "transcript_user",
        "transcript_agent",
        "speech_event",
        "session_resumed",
        "go_away",
        "stage_started",
        "stage_done",
        "transcription_unavailable",
        "packet_ready",
        "landmark_marked",
        "error",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class KeyframeSets(ArtifactModel):
    detection: list[int] = Field(default_factory=list)
    reconstruction: list[int] = Field(default_factory=list)
    selection_params: dict[str, Any] = Field(default_factory=dict)


class Detection(ArtifactModel):
    det_id: str
    cls: str
    box_px: BBox
    item_category: str | None = None
    score: float | None = None
    merged_from: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class RowCountCheck(ArtifactModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    row_hint: str
    model_count_hint: int = Field(ge=0)
    box_count: int = Field(ge=0)


class DetectionFrameStats(ArtifactModel):
    seq: int = Field(ge=0)
    model: str
    latency_ms: int = Field(ge=0)
    spine_count: int = Field(ge=0)
    shelf_board_count: int = Field(ge=0)
    item_count: int = Field(ge=0)


class DetectionsDoc(ArtifactModel):
    frames: dict[int, list[Detection]] = Field(default_factory=dict)
    row_count_checks: list[RowCountCheck] = Field(default_factory=list)
    keyframe_stats: list[DetectionFrameStats] = Field(default_factory=list)


class GeometryDoc(ArtifactModel):
    backend: str
    model: str | None = None
    frames: list[dict[str, Any]] = Field(default_factory=list)
    gravity: dict[str, Any] = Field(default_factory=dict)
    scale: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    error: str | None = None


class BookClustersDoc(ArtifactModel):
    units: list[dict[str, Any]] = Field(default_factory=list)
    books: list[dict[str, Any]] = Field(default_factory=list)


class MeasurementsDoc(ArtifactModel):
    books: dict[str, dict[str, Any]] = Field(default_factory=dict)
    rows: dict[str, dict[str, Any]] = Field(default_factory=dict)
    shelf_run_m: float | None = None
    sum_thickness_m: float | None = None


class TranscriptionsDoc(ArtifactModel):
    books: dict[str, dict[str, Any]] = Field(default_factory=dict)


class IdentificationDoc(ArtifactModel):
    books: dict[str, dict[str, Any]] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    calibration: dict[str, Any] = Field(default_factory=dict)


class BookPricesDoc(ArtifactModel):
    books: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ItemsDoc(ArtifactModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class RoomDoc(ArtifactModel):
    room: dict[str, Any] = Field(default_factory=dict)
    planes: dict[str, Any] = Field(default_factory=dict)
    point_count: int | None = Field(default=None, ge=0)
    debug_png: str | None = None


class TelemetryDoc(ArtifactModel):
    stages: dict[str, dict[str, Any]] = Field(default_factory=dict)
    costs: list[dict[str, Any]] = Field(default_factory=list)
    total_cost_usd: float | None = None
    time_to_packet_s: float | None = None
