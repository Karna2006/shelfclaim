# 05 — Data Schema, Artifacts & Folder Layout

Everything here is implemented as **Pydantic v2 models** in `app/packet/models.py` (packet contract) and `app/pipeline/artifacts.py` (stage artifacts). JSON on disk is always produced with `model_dump(mode="json")`. Validation happens on write **and** on read.

Conventions:
- IDs: `sweep_id` = `sw_<YYYYMMDD>_<HHMMSS>_<4 hex>`. Book `b_0001`… in shelf order. Item `i_001`… Frame seq integers.
- Units: metres for the room, centimetres for spines and items, money in **major units** as `float` rounded to 2 dp in output (computed as `Decimal` internally), ISO-4217 currency, ISO-3166-1 alpha-2 country.
- Timestamps: ISO-8601 with timezone (`2026-11-25T14:03:22+05:30`).
- **Unknown = `null` (or empty string where the contract shows `""`).** Never 0 as a placeholder for "unknown". Where the contract shows `0` as the example type, `null` is still used for unknown, and README states this. *(The brief says "An empty field is correct when the system does not know".)*

---

## 1. The claim packet contract (mandatory fields + our additions)

Mandatory fields from the brief are marked **(req)**. Additions are marked **(add)**. You may add fields but never drop any.

```python
# app/packet/models.py  (sketch — Codex writes the real file)
from typing import Literal
from pydantic import BaseModel, Field

class Sweep(BaseModel):
    id: str                                  # (req)
    captured_at: str                         # (req) ISO-8601 start time
    device: str                              # (req) e.g. "Pixel 8 / Chrome 131 / 1920x1080"
    duration_s: float                        # (req)
    country: str                             # (req) ISO-2, e.g. "IN"
    currency: str                            # (req) ISO-4217, e.g. "INR"
    locale_config: str | None = None         # (add) "config/locales/IN.yaml"
    app_version: str | None = None           # (add) git short sha

class Room(BaseModel):
    length_m: float | None                   # (req)
    width_m: float | None                    # (req)
    height_m: float | None                   # (req)
    floor_area_m2: float | None              # (req)
    wall_area_m2: float | None               # (req) gross
    shelved_wall_area_m2: float | None       # (req)
    scale_method: str                        # (req) human-readable, lists anchors + disagreement
    confidence: float                        # (req) 0..1
    floor_area_ft2: float | None = None      # (add)
    wall_area_ft2: float | None = None       # (add)
    shelved_wall_area_ft2: float | None = None  # (add)
    shape: str | None = None                 # (add) "rectangle" | "polygon(n=6)"
    polygon_m: list[tuple[float, float]] | None = None  # (add) floor polygon vertices
    coverage_pct: float | None = None        # (add) perimeter supported by observed walls
    scale_anchors: list["ScaleAnchor"] = []  # (add)
    scale_disagreement_pct: float | None = None  # (add)
    method_notes: str | None = None          # (add) e.g. "ceiling from RANSAC plane, 4 corners observed"

class ScaleAnchor(BaseModel):               # (add)
    kind: Literal["aruco", "model_metric", "user_stated", "book_format_check"]
    detail: str                              # "marker id 7, 100.0 mm, frame f_000231"
    scale_factor: float | None
    weight: float
    frame_ref: str | None = None

class FxInfo(BaseModel):                     # (add)
    from_currency: str
    to_currency: str
    rate: float
    rate_date: str
    source: str                              # "Frankfurter (ECB reference rates)"
    url: str

class ReplacementCost(BaseModel):            # books
    amount: float | None                     # (req)
    source: str                              # (req) "Amazon.in via Google Shopping"
    url: str                                 # (req)
    retrieved_at: str                        # (req)
    converted: bool = False                  # (req)
    currency: str | None = None              # (add) currency of `amount` (always the locale currency)
    original_amount: float | None = None     # (add) before conversion
    original_currency: str | None = None     # (add)
    fx: FxInfo | None = None                 # (add)
    n_offers: int | None = None              # (add) offers used for the median
    snapshot_path: str | None = None         # (add) evidence/prices/b_0001_new.json
    price_status: Literal["priced", "not_found", "skipped_appraisal", "excluded"] = "priced"  # (add)

class UsedValue(BaseModel):
    amount: float | None                     # (req)
    source: str                              # (req)
    url: str                                 # (req)
    retrieved_at: str                        # (req)
    condition_assumed: str                   # (req) "Used – Good"
    converted: bool = False                  # (add) — contract lacks it; we add it
    currency: str | None = None              # (add)
    original_amount: float | None = None     # (add)
    original_currency: str | None = None     # (add)
    fx: FxInfo | None = None                 # (add)
    n_offers: int | None = None              # (add)
    snapshot_path: str | None = None         # (add)
    price_status: Literal["priced", "not_found", "skipped_appraisal", "excluded"] = "priced"

class BBox(BaseModel):                       # (add)
    x: int; y: int; w: int; h: int; angle_deg: float = 0.0

class Book(BaseModel):
    id: str                                  # (req)
    shelf: str                               # (req) "A-2" = unit A, row 2 from top
    position: int                            # (req) 1-based, left→right along the row
    frame_ref: str                           # (req) "frames/f_000231_0045210.jpg"
    status: Literal["identified", "unidentified", "needs_appraisal"]  # (req)
    title: str                               # (req) "" when unknown
    author: str                              # (req)
    edition: str                             # (req) "" unless evidence supports
    isbn: str                                # (req) "" unless edition resolved
    spine_height_cm: float | None            # (req)
    spine_thickness_cm: float | None         # (req)
    id_confidence: float                     # (req) 0..1 (0 when unidentified)
    replacement_cost: ReplacementCost        # (req)
    used_value: UsedValue                    # (req)
    # --- additions ---
    frame_bbox: BBox | None = None
    frame_time_s: float | None = None
    alt_frame_refs: list[str] = []
    crop_ref: str | None = None              # "crops/b_0001.jpg"
    spine_text_raw: str = ""                 # verbatim transcription (evidence, not identity)
    legibility: float | None = None
    orientation: Literal["upright", "flat", "unknown"] = "unknown"
    dim_method: Literal["marker_plane", "recon_depth", "none"] = "none"
    dim_alt: dict | None = None              # the other method's values if both exist
    catalogue_ref: str | None = None         # "openlibrary:/works/OL12345W"
    candidates_ref: str | None = None        # stages/s06_identification.json#b_0001
    appraisal_reasons: list[str] = []
    user_statements: list[str] = []          # statement ids
    excluded_reason: str | None = None       # "not_mine (user statement us_004)"

class ItemReplacementCost(BaseModel):
    low: float | None                        # (req)
    high: float | None                       # (req)
    source: str                              # (req)
    url: str                                 # (req)
    retrieved_at: str                        # (req)
    currency: str | None = None              # (add)
    converted: bool = False                  # (add)
    fx: FxInfo | None = None                 # (add)
    n_offers: int | None = None              # (add)
    query: str | None = None                 # (add) the comparable query used for ranges
    snapshot_path: str | None = None         # (add)

class Dimensions(BaseModel):
    w: float | None; h: float | None; d: float | None   # (req) cm

class Item(BaseModel):
    id: str                                  # (req)
    category: str                            # (req) from taxonomy
    description: str                         # (req) "Wooden 5-shelf bookcase, white laminate"
    brand_model: str                         # (req) "" unless legible
    frame_ref: str                           # (req)
    dimensions_cm: Dimensions                # (req)
    status: Literal["priced", "range", "needs_appraisal"]  # (req)
    replacement_cost: ItemReplacementCost    # (req)
    confidence: float                        # (req) category/detection confidence 0..1
    # --- additions ---
    material: str | None = None
    frame_bbox: BBox | None = None
    crop_ref: str | None = None
    dims_method: Literal["recon_points", "marker_plane", "none"] = "none"
    dims_confidence: float | None = None
    is_artwork: bool = False
    print_confirmed_by: str | None = None    # user statement id; required to price artwork
    user_statements: list[str] = []
    excluded_reason: str | None = None

class Totals(BaseModel):
    book_count: int                          # (req)
    books_identified: int                    # (req)
    books_unidentified: int                  # (req)
    shelf_run_m: float | None                # (req)
    books_replacement_cost: float            # (req) Σ non-null, not appraisal, not excluded
    books_used_value: float                  # (req)
    items_replacement_cost_low: float        # (req)
    items_replacement_cost_high: float       # (req)
    books_priced_replacement_count: int      # included books with a replacement amount
    books_priced_used_count: int              # included books with a used amount
    items_priced_count: int                   # included items with a complete price or range
    excluded_from_totals: int                # (req) count of lines excluded (see assumptions)
    # additions
    books_needs_appraisal: int = 0
    items_needs_appraisal: int = 0
    excluded_line_ids: list[str] = []
    books_priced_converted: int = 0
    sum_thickness_m: float | None = None
    currency: str = ""

class ReviewEntry(BaseModel):
    ref_id: str                              # (req) "b_0012" | "i_004" | "room" | "us_003"
    reason: str                              # (req) human-readable
    code: str | None = None                  # (add) machine code, e.g. "low_id_confidence"
    severity: Literal["info", "warn", "block"] = "warn"  # (add)
    evidence: str | None = None              # (add) frame/url/statement pointer

class UserStatement(BaseModel):              # (add) top-level list
    id: str                                  # "us_001"
    kind: str
    text: str                                # verbatim from transcript
    target_hint: str
    t_s: float                               # seconds since sweep start
    frame_ref: str | None
    frame_seq: int | None = None              # latest saved capture frame at statement time
    value: str | None = None
    resolved_to: list[str] = []              # ["i_003"] or ["shelf:B-*"]
    applied_effect: str | None = None        # "status→needs_appraisal" | "excluded"

class Meta(BaseModel):                       # (add)
    pipeline_version: str
    models: dict[str, str]                   # {"agent": "...", "vision": "...", "recon": "mapanything"}
    telemetry: dict                          # latency per stage, cost per provider, total cost
    assumptions: list[str]
    validation: dict                         # results of the validation gate

class ClaimPacket(BaseModel):
    sweep: Sweep                             # (req)
    room: Room                               # (req)
    books: list[Book]                        # (req)
    items: list[Item]                        # (req)
    totals: Totals                           # (req)
    review_queue: list[ReviewEntry]          # (req)
    user_statements: list[UserStatement] = []   # (add)
    meta: Meta | None = None                 # (add)
```

### 1.1 Contract rules encoded as validators
- `frame_ref`, `crop_ref`, `snapshot_path` paths are relative to the sweep folder and **must exist** (checked in the S10 validation gate, not in the model).
- A price `amount` not null ⇒ `url` non-empty, `retrieved_at` set, `snapshot_path` set (model validator).
- `converted == True` ⇔ `fx` is not null (model validator).
- `status == "needs_appraisal"` ⇒ both amounts null, `price_status == "skipped_appraisal"`.
- `status == "unidentified"` ⇒ `title == author == edition == isbn == ""` and `id_confidence == 0` (or the raw score kept under an extra field, never shown as identity).
- Item `status == "range"` ⇒ `low ≤ high`. `priced` ⇒ low/high from matched offers of an exact brand/model query.
- An artwork item may be priced only when `print_confirmed_by` names the user statement confirming it is a print; otherwise it must be `needs_appraisal` with null price bounds.
- `model_count_hint` is diagnostic only. It never supplies packet counts or other packet values; when its relative difference from a non-zero `box_count` exceeds `review.row_count_disagreement_pct`, it may create only a `count_disagreement_row` review entry.
- `Totals` must equal `compute_totals(books, items)`. The validation gate recomputes and compares.

### 1.2 Example (abbreviated)
```json
{
  "sweep": {"id":"sw_20261125_140322_a1f3","captured_at":"2026-11-25T14:03:22+05:30","device":"Pixel 8 / Chrome / 1920x1080","duration_s":171.4,"country":"IN","currency":"INR"},
  "room": {"length_m":4.12,"width_m":3.36,"height_m":2.88,"floor_area_m2":13.84,"wall_area_m2":43.07,"shelved_wall_area_m2":6.21,
           "scale_method":"aruco×6 median ⊕ mapanything metric; disagreement 2.7%","confidence":0.78,
           "floor_area_ft2":148.97,"shape":"rectangle"},
  "books": [{"id":"b_0001","shelf":"A-1","position":1,"frame_ref":"frames/f_000231_0045210.jpg","status":"identified",
             "title":"The God of Small Things","author":"Arundhati Roy","edition":"","isbn":"",
             "spine_height_cm":19.6,"spine_thickness_cm":2.3,"id_confidence":0.91,
             "replacement_cost":{"amount":399.0,"source":"<merchant> via Google Shopping","url":"https://…","retrieved_at":"2026-11-25T14:07:01+05:30","converted":false,"snapshot_path":"evidence/prices/b_0001_new.json","n_offers":5},
             "used_value":{"amount":312.4,"source":"eBay UK (used listings median)","url":"https://…","retrieved_at":"2026-11-25T14:07:03+05:30","condition_assumed":"Used – Good","converted":true,
                           "original_amount":2.85,"original_currency":"GBP","fx":{"from_currency":"GBP","to_currency":"INR","rate":109.6,"rate_date":"2026-11-24","source":"Frankfurter (ECB)","url":"https://api.frankfurter.dev/…"}},
             "dim_method":"marker_plane","spine_text_raw":"THE GOD OF SMALL THINGS | ARUNDHATI ROY | PENGUIN"}],
  "items": [],
  "totals": {"book_count":74,"books_identified":55,"books_unidentified":17,"shelf_run_m":3.9,"books_replacement_cost":21450.0,"books_used_value":13210.5,
             "items_replacement_cost_low":38000.0,"items_replacement_cost_high":61500.0,"books_priced_replacement_count":55,"books_priced_used_count":53,"items_priced_count":6,"excluded_from_totals":23},
  "review_queue": [{"ref_id":"b_0042","reason":"Spine unreadable in 3 views (legibility 0.21); logged as unidentified with dimensions","code":"unidentified_spine"}]
}
```
*(Values here are illustrative only. Every real value comes from the pipeline.)*

---

## 2. Internal stage artifacts (`sweeps/<id>/stages/`)

| File | Model | Key fields |
|---|---|---|
| `frames.jsonl` (root) | `FrameRecord` | `seq, t_ms, path, w, h, blur, glare, exposure, gyro_dps, qc_verdict, gravity[3], markers:[{id,corners}], face_boxes:[[x,y,w,h,score],...], faces_blurred:int` |
| `events.jsonl` (root) | `Event` | `t_ms, type` ∈ {`cue_sent`, `tool_call`, `tool_result`, `transcript_user`, `transcript_agent`, `session_resumed`, `go_away`, `stage_started`, `stage_done`, `error`}, `payload` |
| `user_statements.jsonl` (root) | `UserStatement` (pre-resolution) | as above, `resolved_to` empty |
| `s00_keyframes.json` | `KeyframeSets` | `detection:[seq]`, `reconstruction:[seq]`, selection params |
| `s01_detections.json` | `DetectionsDoc` | `frames:{seq:[{det_id, cls, box_px:BBox, item_category, score?, merged_from:[det_id], flags:["possible_duplicate_box"]}]}`, `row_count_checks:[{seq,row_hint,model_count_hint,box_count}]`; `model_count_hint` is review-only and never changes a packet count; `merged_from` records suppressed same-frame duplicate IDs; borderline IoU pairs remain separate and carry `possible_duplicate_box` |
| `s02_geometry.json` | `GeometryDoc` | `backend, model, frames:[{seq, K[3x3], T_world_cam[4x4], depth_path, conf_path}]`, `gravity`, `scale:{factor, anchors[], disagreement_pct, method}`, `status`, `error?` |
| `s03_books_raw.json` | `BookClustersDoc` | `units:[{unit:"A", rows:[{row:1, z_min, z_max, axis[3]}]}]`, `books:[{book_id, unit,row,position, member_dets:[det_id], best_view:{seq,bbox}, alt_view?, center_world[3], count_method}]` |
| `s04_measurements.json` | `MeasurementsDoc` | `books:{book_id:{height_cm,thickness_cm,method,alt?,flags[]}}`, `rows:{"A-1":{span_m}}`, `shelf_run_m`, `sum_thickness_m` |
| `s05_transcriptions.json` | `TranscriptionsDoc` | `books:{book_id:{views:[{seq,readable,orientation,lines[],legibility}], consensus_text, legibility}}` |
| `s06_identification.json` | `IdentificationDoc` | `books:{book_id:{status, chosen?:{source,key,title,authors,year}, edition?, isbn?, features{}, raw_score, id_confidence, candidates:[…]}}`, `thresholds:{accept, review}`, `calibration:{a,b,fitted_on}` |
| `s07_book_prices.json` | `BookPricesDoc` | `books:{book_id:{new:PriceQuote, used:PriceQuote, appraisal:{flag, reasons[]}}}` |
| `s08_items.json` | `ItemsDoc` | `items:[{item_id, category, member_dets[], center_world, dims, description, brand_model, material, is_artwork, price:ItemPriceQuote, status}]` |
| `s09_room.json` | `RoomDoc` | everything in `Room` + `planes:{floor, ceiling, walls[]}`, `point_count`, `debug_png` |
| `telemetry.json` | `TelemetryDoc` | `stages:{name:{start,end,duration_s}}`, `costs:[{provider, units, unit, unit_price, cost_usd}]`, `total_cost_usd`, `time_to_packet_s` |

`face_boxes` uses pixel `x,y,width,height` coordinates in the original frame. `score` is the YuNet detector confidence; it is `null` for Haar fallback detections, which do not provide a confidence score. `faces_blurred` equals the number of recorded boxes.

`qc_verdict` stores the exclusive capture-time quality reason: `ok`, `blurry`, `low_light_blur`, `glare`, `dark`, `bright`, or `fast`. It is optional when reading older sweep manifests.

`PriceQuote` (shared): `{amount, currency, source, url, retrieved_at, converted, fx?, original_amount?, original_currency?, n_offers, offers_used:[{title,price,merchant,url}], query, provider, snapshot_path, price_status}`.

---

## 3. Sweep folder layout

```
sweeps/<sweep_id>/
├── sweep.json                 # Sweep model + locale + device info (written at start, updated at end)
├── frames/                    # hi-res JPEGs, face-blurred  → frame_ref targets
├── frames.jsonl
├── live_frames/               # (optional) low-res frames sent to the live model
├── audio/                     # (optional) agent+user audio wav for the demo trace
├── events.jsonl
├── transcript.jsonl           # {t_ms, speaker:"user"|"agent"|"cue", text, final}
├── user_statements.jsonl
├── geometry/                  # depth_*.npz, conf_*.npz, pointcloud.ply (debug), room_debug.png
├── stages/                    # s00…s10 JSON + telemetry.json
├── crops/                     # b_0001.jpg, i_001.jpg (best-view crops with bbox drawn)
├── evidence/
│   └── prices/                # raw provider JSON per line: b_0001_new.json, b_0001_used.json, i_003.json, fx_GBP_INR_2026-11-24.json
├── claim_packet.json          # ← deliverable
└── report.html                # ← deliverable (relative links to frames/, crops/, evidence/)
```

## 4. Config files (`config/`)

`config/settings.yaml`: thresholds, all tunable, none of them facts about your room.
```yaml
capture:
  # Tuned on a Galaxy S24 FE during the 2026-11-26 field test.
  blur_min: 200
  low_light_exposure_max: 85
  glare_max_frac: 0.06
  dark_mean: 50
  bright_mean: 210
  speed_max_dps: 35
  face_score_threshold: 0.85
  haar_min_neighbors: 8
  haar_min_size_fraction: 0.10
  haar_scale_factor: 1.1
  text_px_min: 18
cues:
  min_gap_s: 6
  same_type_gap_s: 15
keyframes:
  min_novelty: 0.15
  recon_min: 40
  recon_max: 80
dedup:
  eps_factor_thickness: 0.5
  within_frame_iou: 0.80
  within_frame_containment: 0.85
  within_frame_center_factor: 0.30
  within_frame_review_iou_min: 0.50
identify:
  tau_accept: 0.80
  tau_review: 0.55
  weights: {title: 0.55, author: 0.25, publisher: 0.10, legibility: 0.10}
measure:
  height_range_cm: [8, 45]
  thickness_range_cm: [0.3, 12]
  methods_disagree_pct: 10
room:
  voxel_m: 0.02
  manhattan_snap_deg: 8
  min_conf_for_no_review: 0.5
```

`config/locales/IN.yaml`
```yaml
country: IN
currency: INR
shopping: {provider: serpapi, gl: in, hl: en, google_domain: google.co.in}
used_market:
  provider: ebay
  marketplace: null            # no eBay India marketplace
  fallback_marketplace: EBAY_GB
  books_category_id: "<verify per marketplace>"
condition_assumed: "Used – Good"
appraisal:
  used_value_threshold: 5000   # INR
  used_over_new_ratio: 1.5
  min_year: 1950
units: {area: [m2, ft2]}
```

`config/locales/GB.yaml`: same shape; `currency: GBP`, `gl: uk`, `google_domain: google.co.uk`, `marketplace: EBAY_GB`, threshold 50.

`config/taxonomy.yaml`: categories plus default query templates for range pricing (e.g. `shelving: "{material} bookcase {shelves} shelves {height_cm} cm"`).

`config/pricing_rates.yaml`: unit costs for telemetry, each with `source_url` and `as_of` date.

## 5. Ground truth files (`eval/ground_truth/`, templates provided)

| File | Columns |
|---|---|
| `books_gt.csv` | `gt_id, unit, row, position, legible(y/n), title, author, publisher, spine_height_cm, spine_thickness_cm, measured(y/n), notes` |
| `prices_gt.csv` | `gt_id, title, country, source_type(new_shopping/used_ebay), source_name, url, price_local, currency, checked_at` |
| `items_gt.csv` | `gt_item_id, category, description, w_cm, h_cm, d_cm, brand_model, notes` |
| `room_gt.csv` | `measure, value, unit, method, notes` (length, width, height, floor_area, wall_area, shelved_wall_area, door/window sizes) |
| `count_gt.csv` | `unit, row, true_count` |

## 6. API surface (server)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Sweep app (phone) |
| GET | `/sweeps/{id}` | Adjuster view (report.html) |
| GET | `/sweeps/{id}/files/{path}` | Serve frames/crops/evidence (path-safe) |
| POST | `/api/sweeps` | Create sweep → `{sweep_id}` |
| GET | `/api/sweeps/{id}/status` | Pipeline progress, provisional inventory |
| GET | `/api/sweeps/{id}/packet` | `claim_packet.json` |
| WS | `/ws/live/{sweep_id}` | Final text + selected low-res frames to agent; agent text, cues, transcript and tool events back |
| WS | `/ws/capture?sweep_id=` | Hi-res frames (binary) + motion (JSON) → `qc` events back |

WebSocket message types are in `06_USER_FLOWS.md` §5.
