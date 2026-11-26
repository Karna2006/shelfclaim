"""Pydantic contract for the final claim packet.

Input/output: packet JSON and its nested evidence records; path existence is
checked by the later packet validation gate. Implements `docs/05_DATA_SCHEMA.md` §1.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sweep(ContractModel):
    id: str
    captured_at: str
    device: str
    duration_s: float = Field(ge=0)
    country: str = Field(min_length=2, max_length=2)
    currency: str = Field(min_length=3, max_length=3)
    locale_config: str | None = None
    app_version: str | None = None


class ScaleAnchor(ContractModel):
    kind: Literal["aruco", "model_metric", "user_stated", "book_format_check"]
    detail: str
    scale_factor: float | None = Field(gt=0)
    weight: float = Field(ge=0)
    frame_ref: str | None = None


class Room(ContractModel):
    length_m: float | None = Field(gt=0)
    width_m: float | None = Field(gt=0)
    height_m: float | None = Field(gt=0)
    floor_area_m2: float | None = Field(gt=0)
    wall_area_m2: float | None = Field(gt=0)
    shelved_wall_area_m2: float | None = Field(gt=0)
    scale_method: str
    confidence: float = Field(ge=0, le=1)
    floor_area_ft2: float | None = Field(default=None, gt=0)
    wall_area_ft2: float | None = Field(default=None, gt=0)
    shelved_wall_area_ft2: float | None = Field(default=None, gt=0)
    shape: str | None = None
    polygon_m: list[tuple[float, float]] | None = None
    coverage_pct: float | None = Field(default=None, ge=0, le=1)
    scale_anchors: list[ScaleAnchor] = Field(default_factory=list)
    scale_disagreement_pct: float | None = Field(default=None, ge=0)
    method_notes: str | None = None


class FxInfo(ContractModel):
    from_currency: str
    to_currency: str
    rate: float = Field(gt=0)
    rate_date: str
    source: str
    url: str


class ReplacementCost(ContractModel):
    amount: float | None = Field(gt=0)
    source: str
    url: str
    retrieved_at: str
    converted: bool = False
    currency: str | None = None
    original_amount: float | None = Field(default=None, gt=0)
    original_currency: str | None = None
    fx: FxInfo | None = None
    n_offers: int | None = Field(default=None, ge=0)
    snapshot_path: str | None = None
    price_status: Literal["priced", "not_found", "skipped_appraisal", "excluded"] = "priced"

    @model_validator(mode="after")
    def validate_evidence_and_fx(self) -> ReplacementCost:
        if (self.price_status == "priced") != (self.amount is not None):
            raise ValueError("priced status must match a present amount")
        if self.amount is not None and not all(
            value and value.strip()
            for value in (self.source, self.url, self.retrieved_at, self.snapshot_path)
        ):
            raise ValueError("a priced amount requires source, url, retrieved_at and snapshot_path")
        if self.converted != (self.fx is not None):
            raise ValueError("converted must be true exactly when FX evidence is present")
        return self


class UsedValue(ContractModel):
    amount: float | None = Field(gt=0)
    source: str
    url: str
    retrieved_at: str
    condition_assumed: str
    converted: bool = False
    currency: str | None = None
    original_amount: float | None = Field(default=None, gt=0)
    original_currency: str | None = None
    fx: FxInfo | None = None
    n_offers: int | None = Field(default=None, ge=0)
    snapshot_path: str | None = None
    price_status: Literal["priced", "not_found", "skipped_appraisal", "excluded"] = "priced"

    @model_validator(mode="after")
    def validate_evidence_and_fx(self) -> UsedValue:
        if (self.price_status == "priced") != (self.amount is not None):
            raise ValueError("priced status must match a present amount")
        if self.amount is not None and not all(
            value and value.strip()
            for value in (self.source, self.url, self.retrieved_at, self.snapshot_path)
        ):
            raise ValueError("a used amount requires source, url, retrieved_at and snapshot_path")
        if self.converted != (self.fx is not None):
            raise ValueError("converted must be true exactly when FX evidence is present")
        return self


class BBox(ContractModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    angle_deg: float = 0.0


class Book(ContractModel):
    id: str
    shelf: str
    position: int = Field(ge=1)
    frame_ref: str
    status: Literal["identified", "unidentified", "needs_appraisal"]
    title: str
    author: str
    edition: str
    isbn: str
    spine_height_cm: float | None = Field(default=None, gt=0)
    spine_thickness_cm: float | None = Field(default=None, gt=0)
    id_confidence: float = Field(ge=0, le=1)
    replacement_cost: ReplacementCost
    used_value: UsedValue
    frame_bbox: BBox | None = None
    frame_time_s: float | None = Field(default=None, ge=0)
    alt_frame_refs: list[str] = Field(default_factory=list)
    crop_ref: str | None = None
    spine_text_raw: str = ""
    legibility: float | None = Field(default=None, ge=0, le=1)
    orientation: Literal["upright", "flat", "unknown"] = "unknown"
    dim_method: Literal["marker_plane", "recon_depth", "none"] = "none"
    dim_alt: dict[str, object] | None = None
    catalogue_ref: str | None = None
    candidates_ref: str | None = None
    appraisal_reasons: list[str] = Field(default_factory=list)
    user_statements: list[str] = Field(default_factory=list)
    excluded_reason: str | None = None

    @model_validator(mode="after")
    def validate_status_integrity(self) -> Book:
        # An accepted title needs a catalogue pointer so the packet cannot carry free-form guesses.
        if self.status == "identified" and (
            not self.title.strip() or not self.catalogue_ref or not self.catalogue_ref.strip()
        ):
            raise ValueError("identified books require a title and catalogue match reference")
        if self.status == "unidentified":
            if any((self.title, self.author, self.edition, self.isbn)) or self.id_confidence != 0:
                raise ValueError(
                    "unidentified books must have empty identity fields and zero confidence"
                )
        if self.status == "needs_appraisal":
            if self.replacement_cost.amount is not None or self.used_value.amount is not None:
                raise ValueError("books needing appraisal cannot carry prices")
            if (
                self.replacement_cost.price_status != "skipped_appraisal"
                or self.used_value.price_status != "skipped_appraisal"
            ):
                raise ValueError("appraisal prices must use skipped_appraisal status")
        return self


class ItemReplacementCost(ContractModel):
    low: float | None = Field(gt=0)
    high: float | None = Field(gt=0)
    source: str
    url: str
    retrieved_at: str
    currency: str | None = None
    converted: bool = False
    fx: FxInfo | None = None
    n_offers: int | None = Field(default=None, ge=0)
    query: str | None = None
    snapshot_path: str | None = None

    @model_validator(mode="after")
    def validate_range_evidence(self) -> ItemReplacementCost:
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("item price range low must be less than or equal to high")
        if (self.low is not None or self.high is not None) and not all(
            value and value.strip()
            for value in (self.source, self.url, self.retrieved_at, self.snapshot_path)
        ):
            raise ValueError("item prices require source, url, retrieved_at and snapshot_path")
        if self.converted != (self.fx is not None):
            raise ValueError("converted must be true exactly when FX evidence is present")
        return self


class Dimensions(ContractModel):
    w: float | None = Field(default=None, gt=0)
    h: float | None = Field(default=None, gt=0)
    d: float | None = Field(default=None, gt=0)


class Item(ContractModel):
    id: str
    category: str
    description: str
    brand_model: str
    frame_ref: str
    dimensions_cm: Dimensions
    status: Literal["priced", "range", "needs_appraisal"]
    replacement_cost: ItemReplacementCost
    confidence: float = Field(ge=0, le=1)
    material: str | None = None
    frame_bbox: BBox | None = None
    crop_ref: str | None = None
    dims_method: Literal["recon_points", "marker_plane", "none"] = "none"
    dims_confidence: float | None = Field(default=None, ge=0, le=1)
    is_artwork: bool = False
    print_confirmed_by: str | None = None
    user_statements: list[str] = Field(default_factory=list)
    excluded_reason: str | None = None

    @model_validator(mode="after")
    def validate_status_integrity(self) -> Item:
        if (
            self.is_artwork
            and self.status != "needs_appraisal"
            and not (self.print_confirmed_by and self.print_confirmed_by.strip())
        ):
            raise ValueError("priced artwork requires a print-confirming user statement")
        if self.status == "needs_appraisal" and any(
            value is not None for value in (self.replacement_cost.low, self.replacement_cost.high)
        ):
            raise ValueError("items needing appraisal cannot carry prices")
        if self.status in {"priced", "range"} and (
            self.replacement_cost.low is None or self.replacement_cost.high is None
        ):
            raise ValueError("priced and range items require both price bounds")
        return self


class Totals(ContractModel):
    book_count: int = Field(ge=0)
    books_identified: int = Field(ge=0)
    books_unidentified: int = Field(ge=0)
    shelf_run_m: float | None = Field(default=None, ge=0)
    books_replacement_cost: float = Field(ge=0)
    books_used_value: float = Field(ge=0)
    items_replacement_cost_low: float = Field(ge=0)
    items_replacement_cost_high: float = Field(ge=0)
    books_priced_replacement_count: int = Field(ge=0)
    books_priced_used_count: int = Field(ge=0)
    items_priced_count: int = Field(ge=0)
    excluded_from_totals: int = Field(ge=0)
    books_needs_appraisal: int = Field(default=0, ge=0)
    items_needs_appraisal: int = Field(default=0, ge=0)
    excluded_line_ids: list[str] = Field(default_factory=list)
    books_priced_converted: int = Field(default=0, ge=0)
    sum_thickness_m: float | None = Field(default=None, ge=0)
    currency: str = ""


class ReviewEntry(ContractModel):
    ref_id: str
    reason: str
    code: str | None = None
    severity: Literal["info", "warn", "block"] = "warn"
    evidence: str | None = None


class UserStatement(ContractModel):
    id: str
    kind: str
    text: str
    target_hint: str
    t_s: float = Field(ge=0)
    frame_ref: str | None = None
    frame_seq: int | None = Field(default=None, ge=0)
    value: str | None = None
    resolved_to: list[str] = Field(default_factory=list)
    applied_effect: str | None = None


class Meta(ContractModel):
    pipeline_version: str
    models: dict[str, str]
    telemetry: dict[str, object]
    assumptions: list[str]
    validation: dict[str, object]


class ClaimPacket(ContractModel):
    sweep: Sweep
    room: Room
    books: list[Book]
    items: list[Item]
    totals: Totals
    review_queue: list[ReviewEntry]
    user_statements: list[UserStatement] = Field(default_factory=list)
    meta: Meta | None = None
