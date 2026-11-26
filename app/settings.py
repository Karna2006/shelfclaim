"""Load application secrets from the environment and tunable rules from YAML.

Environment input: `.env`/process variables; YAML input: `config/settings.yaml`.
Output: validated settings passed into request and pipeline boundaries.
Implements `docs/03_TECH_STACK.md` §§2, 7 and `docs/05_DATA_SCHEMA.md` §4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CaptureSettings(BaseModel):
    blur_min: float = 200
    low_light_exposure_max: float = Field(default=85, gt=0, le=255)
    glare_max_frac: float = 0.06
    dark_mean: float = 50
    bright_mean: float = 210
    speed_max_dps: float = 35
    speed_sustain_s: float = Field(default=1, gt=0)
    face_score_threshold: float = Field(default=0.85, ge=0, le=1)
    haar_min_neighbors: int = Field(default=8, ge=8)
    haar_min_size_fraction: float = Field(default=0.10, ge=0.10, le=1)
    haar_scale_factor: float = Field(default=1.1, gt=1)
    text_px_min: float = 18
    frame_min_interval_ms: int = Field(default=300, ge=0)
    frame_gyro_max_dps: float = Field(default=120, ge=0)
    motion_sample_hz: int = Field(default=10, gt=0)
    jpeg_quality: float = Field(default=0.85, ge=0, le=1)
    max_inflight_frames: int = Field(default=3, gt=0)
    max_buffered_frames: int = Field(default=20, gt=0)
    reconnect_initial_ms: int = Field(default=250, gt=0)
    reconnect_max_ms: int = Field(default=8000, gt=0)


class CueSettings(BaseModel):
    window_s: float = 2
    blurred_fraction: float = 0.40
    min_gap_s: float = 6
    same_type_gap_s: float = 15


class KeyframeSettings(BaseModel):
    min_novelty: float = 0.15
    recon_min: int = 40
    recon_max: int = 80


class DedupSettings(BaseModel):
    eps_factor_thickness: float = 0.5
    within_frame_iou: float = 0.80
    within_frame_containment: float = 0.85
    within_frame_center_factor: float = 0.30
    within_frame_review_iou_min: float = 0.50


class IdentifySettings(BaseModel):
    tau_accept: float = 0.80
    tau_review: float = 0.55
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "title": 0.55,
            "author": 0.25,
            "publisher": 0.10,
            "legibility": 0.10,
        }
    )


class MeasureSettings(BaseModel):
    height_range_cm: tuple[float, float] = (8, 45)
    thickness_range_cm: tuple[float, float] = (0.3, 12)
    methods_disagree_pct: float = 10


class RoomSettings(BaseModel):
    voxel_m: float = 0.02
    manhattan_snap_deg: float = 8
    min_conf_for_no_review: float = 0.5


class ReviewSettings(BaseModel):
    row_count_disagreement_pct: float = Field(default=0.10, ge=0, le=1)


class AgentSettings(BaseModel):
    timeout_s: float = Field(default=20, gt=0)
    debounce_ms: int = Field(default=800, gt=0)
    history_turns: int = Field(default=20, gt=0)
    max_tool_rounds: int = Field(default=5, gt=0)
    live_frame_max_side: int = Field(default=768, gt=0)
    live_frame_quality: float = Field(default=0.6, gt=0, le=1)
    frame_attachment_keywords: list[str] = Field(
        default_factory=lambda: ["this", "that", "here", "painting", "shelf", "book", "what is"]
    )
    frame_attachment_every_n_turns: int = Field(default=3, gt=0)
    echo_window_s: float = Field(default=10, gt=0)
    echo_match_ratio: int = Field(default=85, ge=0, le=100)


class ModelRateLimitSettings(BaseModel):
    requests_per_minute: int = Field(default=5, gt=0)
    window_s: float = Field(default=60, gt=0)
    max_retries: int = Field(default=3, ge=0)
    backoff_initial_s: float = Field(default=0.5, gt=0)
    backoff_max_s: float = Field(default=8, gt=0)


class LlmSettings(BaseModel):
    default_rate_limit: ModelRateLimitSettings = Field(default_factory=ModelRateLimitSettings)
    model_rate_limits: dict[str, ModelRateLimitSettings] = Field(default_factory=dict)


class YamlSettings(BaseModel):
    """Thresholds and model rules from config/settings.yaml."""

    model_config = ConfigDict(extra="forbid")

    capture: CaptureSettings = Field(default_factory=CaptureSettings)
    cues: CueSettings = Field(default_factory=CueSettings)
    keyframes: KeyframeSettings = Field(default_factory=KeyframeSettings)
    dedup: DedupSettings = Field(default_factory=DedupSettings)
    identify: IdentifySettings = Field(default_factory=IdentifySettings)
    measure: MeasureSettings = Field(default_factory=MeasureSettings)
    room: RoomSettings = Field(default_factory=RoomSettings)
    review: ReviewSettings = Field(default_factory=ReviewSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)


class Settings(BaseSettings):
    """Environment settings plus the validated YAML rule set."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    config: YamlSettings = Field(default_factory=YamlSettings)
    google_api_key: SecretStr | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    google_genai_use_vertexai: bool = Field(
        default=False, validation_alias="GOOGLE_GENAI_USE_VERTEXAI"
    )
    agent_model: str = Field(default="gemini-3.1-flash-lite", validation_alias="AGENT_MODEL")
    vision_model: str = Field(default="gemini-3.8-flash", validation_alias="VISION_MODEL")
    checker_model: str = Field(default="", validation_alias="CHECKER_MODEL")
    serpapi_api_key: SecretStr | None = Field(default=None, validation_alias="SERPAPI_API_KEY")
    shopping_provider: str = Field(default="serpapi", validation_alias="SHOPPING_PROVIDER")
    used_provider: Literal["serpapi_ebay", "ebay_browse"] = Field(
        default="serpapi_ebay", validation_alias="USED_PROVIDER"
    )
    ebay_client_id: SecretStr | None = Field(default=None, validation_alias="EBAY_CLIENT_ID")
    ebay_client_secret: SecretStr | None = Field(
        default=None, validation_alias="EBAY_CLIENT_SECRET"
    )
    google_books_api_key: SecretStr | None = Field(
        default=None, validation_alias="GOOGLE_BOOKS_API_KEY"
    )
    openlibrary_contact: str = Field(default="", validation_alias="OPENLIBRARY_CONTACT")
    geometry_backend: Literal["modal", "local", "off"] = Field(
        default="modal", validation_alias="GEOMETRY_BACKEND"
    )
    recon_model: Literal["mapanything", "vggt"] = Field(
        default="mapanything", validation_alias="RECON_MODEL"
    )
    debug_geometry: bool = Field(default=False, validation_alias="DEBUG_GEOMETRY")
    marker_dict: str = Field(default="DICT_4X4_50", validation_alias="MARKER_DICT")
    marker_size_mm: float = Field(default=100.0, gt=0, validation_alias="MARKER_SIZE_MM")
    hires_fps: int = Field(default=2, gt=0, validation_alias="HIRES_FPS")
    hires_width: int = Field(default=1920, gt=0, validation_alias="HIRES_WIDTH")
    default_country: str = Field(default="IN", validation_alias="DEFAULT_COUNTRY")
    sweeps_dir: Path = Field(default=Path("./sweeps"), validation_alias="SWEEPS_DIR")
    cache_db: Path = Field(default=Path("./cache/http_cache.sqlite"), validation_alias="CACHE_DB")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")


def load_settings(
    settings_path: Path = Path("config/settings.yaml"),
    env_file: Path | None = Path(".env"),
) -> Settings:
    """Read YAML defaults and let environment values configure secrets/runtime."""
    yaml_values: dict[str, object] = {}
    if settings_path.exists():
        loaded = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Settings YAML must contain a mapping: {settings_path}")
        yaml_values = loaded
    config = YamlSettings.model_validate(yaml_values)
    selected_env = env_file if env_file is not None and env_file.exists() else None
    return Settings(config=config, _env_file=selected_env)
