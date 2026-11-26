# 04 — Architecture: how every number is produced

> Core principle: **models perceive, code decides.** Vision models return boxes and verbatim text. Geometry models return depth and poses. Everything that becomes a number in the packet (count, cm, m², price, total, confidence) is computed by deterministic Python that you can unit-test and explain line by line.

## 1. System diagram

```mermaid
flowchart LR
  subgraph Phone["Phone browser (web/)"]
    STT[Browser Web Speech to final text]
    CAMLO[Camera → 768px JPEG @1fps]
    CAMHI[Camera → 1080p JPEG @2–3fps]
    IMU[DeviceMotion: gyro + gravity]
    UI[Live inventory UI + QC meter]
  end

  subgraph Server["FastAPI server (app/)"]
    WSL[/ws/live/{sweep_id}/]
    WSC[/ws/capture/]
    LIVE[AgentLoop\nFlash function calling + history]
    MON[Capture monitor\nblur·glare·speed·coverage]
    STORE[(sweeps/<id>/frames + events.jsonl)]
    KF[Keyframe selector]
    subgraph Pipeline["Stage pipeline (asyncio DAG, each stage → JSON)"]
      S1[S1 detect\nspines·shelves·items]
      S2[S2 geometry\nreconstruction + scale fusion]
      S3[S3 lift + dedup + count]
      S4[S4 measure spines]
      S5[S5 transcribe spines]
      S6[S6 identify\ncatalogue match]
      S7[S7 price books]
      S8[S8 items: dedup·describe·price]
      S9[S9 room geometry]
      S10[S10 assemble packet\ntotals·review queue·report]
    end
  end

  subgraph External["External services"]
    GF[(Gemini Flash agent)]
    GV[(Gemini Flash vision)]
    GPU[(Modal GPU\nMapAnything / VGGT)]
    OL[(Open Library)]
    GB[(Google Books)]
    SERP[(SerpApi Google Shopping)]
    EBAY[(eBay Browse)]
    FX[(Frankfurter FX)]
  end

  STT --> WSL --> LIVE <--> GF
  CAMLO --> WSL
  CAMHI --> WSC --> STORE
  IMU --> WSC
  WSC --> MON --> LIVE
  STORE --> KF --> S1 --> S3
  KF --> S2 --> S3 --> S4 --> S10
  S3 --> S5 --> S6 --> S7 --> S10
  S1 --> S8 --> S10
  S2 --> S9 --> S10
  S1 -.provisional.-> UI
  S1 & S5 --> GV
  S2 --> GPU
  S6 --> OL & GB
  S7 & S8 --> SERP & EBAY & FX
  S10 -->|summary| LIVE
  LIVE -->|text replies, tools, transcript| STORE
```

## 2. Runtime components

| Component | Module | Responsibility |
|---|---|---|
| Web client | `web/` | Video-only camera capture, browser speech input/output, motion sampling, live UI, QC meter |
| Agent loop | `app/live/agent.py`, `client.py` | Gemini Flash function calls, bounded history, optional latest frame, explicit tool results, and safe timeout fallback |
| Live tools | `app/live/tools.py` | Tool declarations + handlers (locale, user statements, status, end sweep) |
| Agent prompt | `app/prompts/agent_system.md` | Reviewed instruction, integrity rules, and sweep guidance |
| Capture server | `app/server/ws_capture.py` | Receives hi-res frames + motion, saves to disk, timestamps, face-blur on save |
| Capture monitor | `app/capture/monitor.py`, `quality.py`, `coverage.py` | Per-frame quality, rolling windows, coverage map, cue generation with rate limits |
| Keyframe selector | `app/capture/keyframes.py` | Chooses frames for detection (dense) and reconstruction (sparse, pose-diverse) |
| Pipeline orchestrator | `app/pipeline/orchestrator.py` | Runs stages S1–S10 as an asyncio DAG, streaming S1/S5 during the sweep, timing + cost ledger |
| Stages | `app/pipeline/stages/s01_detect.py` … `s10_assemble.py` | One file per stage: `async def run(ctx: StageContext) -> Path` writing `stages/sNN_*.json` |
| Providers | `app/vision/`, `app/geometry/`, `app/identify/`, `app/pricing/providers/` | Thin, mockable API clients with caching |
| Packet | `app/packet/` | Pydantic contract models, totals, review queue, report rendering |
| CLI | `app/cli.py` | `serve`, `check-llm`, `inspect-sweep`, `inspect-faces`, `download-yunet`, and pipeline commands |

## 3. Capture: two channels, on purpose

| Channel | Payload | Rate | Consumer | Why separate |
|---|---|---|---|---|
| `/ws/live/{sweep_id}` | Final transcript JSON and selected 768px JPEG (q 0.6) | final text turns; frames about 1 fps | AgentLoop | No raw microphone audio reaches the server. Frames attach for configured visible references or every third turn |
| `/ws/capture` | 1920×1080 JPEG (q 0.85, ~300–500 KB) + motion sample `{t, gyro_dps, gravity_xyz, orientation}` | 2–3 fps (adaptive) | Disk + monitor + pipeline | Spines need pixels. Frames are evidence (`frame_ref`). Voice must never wait on uploads |

Client-side gating: send a hi-res frame only if (a) ≥ 300 ms since the last one, and (b) the gyro rate is < 120 °/s (a frame mid-whip is useless). The server still scores what it gets.

Every saved frame: `sweeps/<id>/frames/f_<seq:06d>_<ms_since_start:07d>.jpg` plus a row in `frames.jsonl` `{seq, t_ms, w, h, blur, glare, exposure, gyro_dps, gravity, face_boxes}`. YuNet detections at score ≥ 0.85 are blurred before writing. If the ONNX model is absent, the bundled Haar cascade is used with at least 8 neighbours and a minimum face size of 10% of the frame's short side. The detected boxes and YuNet scores are retained for audit; Haar scores are null. The original is never stored.

## 4. Capture monitor (the thing that makes the agent "direct" the sweep)

### 4.1 Per-frame metrics (deterministic, < 60 ms on CPU)

| Metric | Computation | Initial threshold (tune on your capture) |
|---|---|---|
| `blur` | Variance of Laplacian on grayscale, downscaled to 960 px wide | blurred if < 200 (Galaxy S24 FE field test, 2026-11-26) |
| `glare` | Fraction of pixels with V > 250 in HSV, in the central 80% | glare if > 6% |
| `exposure` | Mean luminance | dark if < 50, bright if > 210 |
| `speed` | Gyro magnitude (°/s) from DeviceMotion | too fast if > 35 °/s sustained 1 s (Galaxy S24 FE field test, 2026-11-26) |
| `text_px` (legibility proxy) | Median spine-text height in px from the most recent S1 detections on this region: spine box short side × 0.5. Updated asynchronously | too far if < 18 px |

When `blur < blur_min`, `gyro_dps < speed_max_dps`, and exposure is below the configurable `low_light_exposure_max` (default 85), the frame verdict is `low_light_blur`. This routes low-light softness to `TOO_DARK` rather than a camera-motion cue. Sustained fast motion keeps priority.

### 4.2 Coverage map
Built from S1 detections streamed during the sweep:
- **Shelf units** (A, B, C…, by appearance order) with **rows** (from shelf-board detections). A row counts as covered when at least one frame shows it with `blur ≥ threshold` and `text_px ≥ 18`.
- **Room landmarks** for geometry: `corners_seen` (wall–wall–floor junctions detected), `ceiling_seen` (ceiling-line detection), `floor_seen`. The live model can also report these via a tool.
- **Scale cards seen**: marker IDs detected (cheap ArUco detection on every hi-res frame).

### 4.3 Cue generation → voice
Rolling 2-second windows produce candidate cues. Priority order:
`TOO_FAST` > `TOO_DARK` (includes `low_light_blur`; say "turn on a light") > `BLURRY` > `GLARE` > `TOO_FAR` (text too small) > `ROW_MISSED` > `ART_QUESTION` > `NEED_CEILING` > `NEED_CORNERS` > `CARD_NOT_SEEN` > `PROGRESS` (positive feedback: "logged 12 books on shelf A").

Rate limits: <= 1 cue per 12 s overall, the same cue type <= once per 30 s. `LOW_LIGHT` and `BLURRY` require a sustained condition for 3 s. Never send a cue while the user is speaking, for 8 s after speech, or while an agent reply is pending. A cue that arrives during agent speech waits in the browser queue until the current sentence ends; it is dropped if it is more than 4 s old or its QC condition has cleared. Duplicate cue types are not queued. `PROGRESS` only when nothing else is pending.

Injection: the monitor sends `{type:"cue", text, priority, kind}` for direct TTS and appends the cue to agent history. Every cue is logged to `events.jsonl` with its type and triggering metrics. Current deterministic monitor supports TOO_FAST, TOO_DARK/LOW_LIGHT, BLURRY, and GLARE; detection-dependent coverage and occlusion cues remain pending S1.

## 5. Live agent (browser speech cascade)

The browser uses Web Speech recognition in continuous/interim mode with `en-IN`, but sends only final transcripts as `{type:"user_text", text, t_ms}`. Interim results never reach the LLM. The browser speaks agent replies and cues with `speechSynthesis`, preferring an `en-IN` or `en-GB` voice. Unsupported recognition shows a typed-input fallback. Camera capture is video-only (`audio:false`).

The `AgentLoop` uses `AGENT_MODEL` (default `gemini-3.1-flash-lite`) through `google-genai` `generate_content`, with low thinking, a 20-second deadline, and the reviewed system prompt in `app/prompts/agent_system.md`. It keeps the last eight user turns and complete function-call/result pairs. A frame is attached only to its current user turn; stored history keeps a `[frame f_<seq>]` marker. Transient 500/503/internal/unavailable/deadline failures retry after 0.5 s and 1.5 s, then move through `agent.model_chain`; after all configured models fail, the chain is retried once without the current image. Every attempt records its model, latency, request shape, error, and token usage when the provider returns it. The browser speaks "One moment." after 2.5 s if a turn is still running. `VISION_MODEL` stays reserved for offline vision.

Attach a maximum 768 px JPEG at q 0.6 only when text contains a configured visible-reference keyword, or every configured third turn. One Start tap opens capture and live sockets with the same sweep ID. Final transcripts arriving within 800 ms are merged into one turn. When recognition never finalizes, the browser promotes interim text after it stays unchanged for 1.2 s. Recognition start/end/restart/error, pause/resume, and TTS state events are written to `events.jsonl`. `agent.earphones_mode` defaults on: recognition remains active during TTS; an echo-cleaned final or stable forced-final with at least two words lets the current sentence finish before queued reply sentences are dropped. "Stop", "wait", and "hold on" are explicit barge-in commands. Interim results, noise, and single words do not interrupt. With earphones mode off, recognition pauses during TTS and cues are capped at the configured short length. Before a transcript reaches the agent, the server strips recent spoken phrases by comparing three-word windows with rapidfuzz partial ratio >= 85 over six seconds. A whole transcript is dropped as echo only when it has at least four words and matches at that threshold. The "Tap to interrupt" button cancels immediately.

### Tools

| Tool | Args | Effect |
|---|---|---|
| `set_locale` | `country` (ISO-2), `currency` (ISO-4217) | Validates against `config/locales/*.yaml` and writes `sweep.json` |
| `start_sweep` | none | Records capture stage start |
| `get_sweep_status` | none | Returns current frame sequence and capture state; coverage is a stub |
| `record_user_statement` | `kind`, `target_hint`, verbatim `text`, optional `value` | Appends to `user_statements.jsonl` with latest capture frame sequence and reference |
| `mark_landmark` | `kind` | Returns a landmark hint associated with the latest frame sequence |
| `end_sweep` | none | Stops capture and stores elapsed duration |
| `get_packet_summary` | none | Returns a not-ready stub until a packet exists |

Every model-generated value is subject to the integrity rules: tools cannot create prices, totals, packet counts, dimensions, areas, FX rates, or confidence thresholds. Cue messages are sent without an LLM call, logged to the transcript and events, added as an assistant history note, then spoken immediately by the browser.

## 6. The pipeline, stage by stage

Each stage: input = previous stage JSON files + frames. Output = `sweeps/<id>/stages/sNN_<name>.json` + timing/cost entry. Every stage is runnable alone: `python -m app.cli stage s04 --sweep <id>`.

### S0 — Keyframe selection (`keyframes.py`)
- **Detection set:** every frame with `blur ≥ T_blur` and `glare ≤ T_glare`, de-duplicated so consecutive picks differ by ≥ 15% image content (phase correlation shift or ORB overlap < 0.85). Streaming, typically 60–150 frames per sweep.
- **Reconstruction set:** 40–80 frames spread through the sweep. Greedy selection maximises gyro-integrated yaw/pitch diversity and sharpness. Always include every frame where a scale card was detected.

### S1 — Detection (`vision/detect.py`) *(streams during the sweep)*
- Gemini 3.5 Flash Lite, at most 10 keyframes per sweep, JSON schema output:
  `{"objects":[{"cls":"book_spine|book_stack|shelf_unit|shelf_board|item","box_2d":[ymin,xmin,ymax,xmax],"angle_deg":0-180,"item_category":"…","note":"…"}]}`.
- Boxes are 0–1000 normalised; convert to pixels. For long thin spines, ask for **rotated** boxes via `angle_deg` and validate (clip to the image, min side ≥ 6 px).
- Prompt: "List EVERY book spine individually, including thin ones, books lying flat and books in stacks. Do not read titles. Do not merge adjacent books."
- **Within-frame NMS (before cross-frame dedup):** assign stable `det_id` values to raw detections, then compare boxes only within the same frame and class. Merge a pair when rotated-box IoU ≥ `dedup.within_frame_iou` (default 0.80), or when the smaller rotated box is at least `dedup.within_frame_containment` (default 0.85) contained in the larger and their centres are closer than `dedup.within_frame_center_factor` (default 0.30) × the smaller box's short side. Keep the higher-score box (larger area breaks score ties; use area when scores are absent) and record suppressed IDs in `merged_from`. Pairs with IoU ≥ `dedup.within_frame_review_iou_min` (default 0.50) but below the merge threshold are retained and flagged `possible_duplicate_box`; they still count toward the per-row count cross-check. All thresholds live in `config/settings.yaml`.
- **Second-opinion diagnostic hint (review-only):** when a whole shelf row is visible, the model may return `model_count_hint`. Deterministic `box_count` remains the only count used by the pipeline. If `box_count > 0` and `abs(model_count_hint - box_count) / box_count` is greater than `review.row_count_disagreement_pct` (default 0.10), create a `count_disagreement_row` review entry. The hint never changes detections, book counts, or any other packet value. Skip the ratio when `box_count` is zero because its denominator is undefined.
- Output: `s01_detections.json` = per-frame boxes plus model, request latency, and post-NMS spine/shelf-board/item counts for each keyframe. `replay --until s01 --max-keyframes 40` can cap a diagnostic replay; later replays reuse an existing S1 artifact. Provisional live inventory = running estimate (books per unit row from the best frame of that row).

### S2 — Geometry + metric scale (`geometry/`)
1. **Reconstruction:** send the reconstruction set (resized to ~518 px long side) to Modal `recon.run(frames, model="mapanything")`. It returns per-frame extrinsics, intrinsics, depth (float16), confidence, and the model's own metric scale. Fallback VGGT if MapAnything fails. `GEOMETRY_BACKEND=off` skips this, and room and recon-based dims go to review.
2. **Gravity alignment:** average the phone gravity vectors (camera frame) over the reconstruction frames and rotate the world so +Z is up. Check with RANSAC on the dominant horizontal plane (floor).
3. **Scale anchors** (each yields `s_k = true_length / recon_length`):
   - **ArUco cards** (weight 1.0 each detection): detect the 4 corners in the hi-res frame, sample depth at those pixels in the matching recon frame, back-project, and compare the 3D edge lengths with `MARKER_SIZE_MM`. Use the median across edges and detections.
   - **Model metric scale** (MapAnything; weight 0.3): `s = 1.0` by definition if the output is already metric.
   - **User-stated dimension** (weight 0.7): e.g. "the shelf is two metres tall" → `record_user_statement(kind=shelf_dimension)`. Compare with the measured height of that unit.
   - **Book-format sanity** (weight 0, check only): the distribution of measured spine heights should mostly fall within 15–32 cm. Flag if > 30% fall outside.
4. **Fusion:** `s* = weighted median(s_k)`. `scale_disagreement_pct = max_k |s_k / s* − 1|`. `scale_method` string, e.g. `"aruco×5 (median) ⊕ mapanything metric; disagreement 3.1%"`. If there are no ArUco detections, `s*` comes from the model metric scale and confidence is capped at 0.5 ("model estimate cross-checked with book-format priors"). It's stated honestly.
5. Output `s02_geometry.json`: poses, intrinsics, scale, anchors, gravity, path to `geometry/depth_*.npz`.

### S3 — Lift, dedup, count (`geometry/lift.py`, `geometry/dedup.py`)
1. For each spine detection in a frame that has depth (recon frame, or nearest recon frame mapped via homography if it's a detection-only frame): sample depth inside the central 60% of the rotated box (median), back-project the box centre, top-mid and bottom-mid points to world coordinates (scaled by `s*`).
2. **Shelf structure:** shelf-board detections → world heights → per unit, cluster board heights → rows. Shelf units are separated by DBSCAN on the horizontal position of `shelf_unit` boxes' 3D centres. Name them `A, B, C…` left-to-right in sweep order. Rows are numbered from the top: `A-1`, `A-2`…
3. **Dedup:** within each row, DBSCAN on 1-D position along the row axis (eps = 0.5 × median spine thickness, min_samples = 1) with a **cannot-link constraint on post-NMS detections**: two surviving detections from the same frame never merge (adjacent books in one frame are distinct by definition). Same-frame near-duplicate boxes have already been consolidated by S1; suppressed IDs remain auditable through `merged_from`. Clusters = books.
4. **Fallback without geometry:** per row, count = the max detections in the single best frame that shows the full row (from the coverage map). Flag `count_method="best_frame"`.
5. Each book cluster gets a `best_view` = argmax(sharpness × crop text px × frontalness) plus 1 alternate view. `position` = rank along the row axis. `frame_ref` = best view frame path + bbox.
6. Output `s03_books_raw.json`.

### S4 — Measure spines (`geometry/measure.py`)
Order of methods, first one available wins. All are recorded.
1. **`marker_plane`:** if an ArUco card on the same unit is visible in the best-view frame, compute the homography from the card corners to the card plane (mm). Map the spine box top/bottom/left/right midpoints through it to get height and thickness. Correct for books recessed from the card plane using recon depth if available (scale factor = depth_book / depth_card).
2. **`recon_depth`:** 3D distance between back-projected top-mid and bottom-mid (height) and left-mid and right-mid (thickness), scaled by `s*`.
3. **`none`:** dims null, with a review entry.

Sanity: height outside [8, 45] cm or thickness outside [0.3, 12] cm → keep the value, flag `dim_outlier`. If both methods exist and disagree > 10%, record both, keep the marker value, and flag.

**Shelf run:** per row, the span from the leftmost book edge to the rightmost book edge along the row axis. `shelf_run_m = Σ row spans`. Also report `sum_thickness_m` as a cross-check.

Output `s04_measurements.json`.

### S5 — Transcribe spines (`vision/transcribe.py`) *(starts during the sweep for stable clusters)*
- Use `config/settings.yaml` `transcribe.backend` (`local_ocr` by default, optional `gemini`). Local OCR runs once on each best-view frame at 90° and 270°; frames containing flat spines also run at 0°. Map OCR quadrilaterals back to frame coordinates and keep lines with confidence ≥ 0.5.
- Assign each line by its center to a containing spine box; if boxes overlap, choose the nearest box center-x. Drop lines outside all spine boxes and order each spine's text top-to-bottom. Gemini remains an optional fallback only for books without local OCR text when enabled, keyed, and available.
- Output schema remains `{"crop_id","readable":bool,"orientation":"rotate_0deg|rotate_90deg|rotate_180deg|rotate_270deg","lines":[{"text","kind_guess":"title|author|publisher|other"}],"legibility":0-1}`. Gemini prompts still require visible characters only and prohibit completing titles from memory.
- The configured catalogue thresholds remain unchanged. Merged or weak text stays `unidentified`; no title is inferred from OCR alone.
- **Validation guard:** reject any line > 80 characters, or lines containing text that also appears in your prompt examples (a prompt-leak check).
- Output `s05_transcriptions.json` (keeps raw text = `spine_text_raw`).

### S6 — Identify (`identify/`)
1. **Query build:** search every non-empty OCR line and every adjacent line pair as a title query on Open Library `search.json`. Normalize case, punctuation, whitespace and a leading `THE`; compare compact forms too so joined words such as `HALFMURDERS` can match `Half Murders`. Do not merge non-adjacent lines.
2. **Candidates:** search Open Library first. Use Google Books only if Open Library returns no candidates and neither provider has returned HTTP 429 in the last 60 seconds. Record each request URL and status for diagnostics. Merge duplicate records by source key.
3. **Features per candidate:** report `title_sim`, `author_sim`, `publisher_sim`, `raw_score`, and `id_confidence`. A line that does not match a candidate author is ignored; it never subtracts from title evidence.
4. **Decision:** accept only when `title_sim ≥ 90` and either another OCR line on that spine matches a catalogue author at `author_sim ≥ 85`, or the normalized title has at least three words. Confidence is the accepted title similarity expressed from 0 to 1; rejected candidates have `id_confidence=0`. Otherwise keep title/author/edition/isbn **empty** and preserve the raw spine text.
5. If a box has multiple distinct accepted titles, select the one whose matching OCR line center is closest to the box center and add a `multiple_titles_in_box` review entry listing the other titles. If line geometry is unavailable, use the highest title similarity and author similarity.
6. Edition remains empty unless supported by edition-specific evidence. Output `s06_identification.json` with candidate scores and decisions saved for audit.

### S7 — Price books (`pricing/`)
For each `identified` book not already `needs_appraisal`:
1. **Pre-appraisal rules** (`appraisal_rules.py`): user said signed/first edition/rare, first publish year < 1950 with no modern edition match, or spine text contains "first edition"/"signed"/"limited". → `needs_appraisal`, skip pricing.
2. **Replacement (new):** `ShoppingProvider.search(query, locale)`. Query = ISBN if resolved, else `"<title>" <author> book`. Filter offers: title fuzzy ≥ 80 vs the work title, physical only (exclude: kindle, ebook, e-book, audiobook, audio cd, mp3, summary, study guide, workbook, poster, "set of", "box set" unless the spine says set), condition new, price > 0. If ≥ 3 remain, drop IQR outliers. `amount` = median. `url`/`source` = the offer closest to the median (`"<merchant> via Google Shopping"`). Raw response → `evidence/prices/<book_id>_new.json`.
3. **Used:** `UsedMarketProvider` (eBay Browse) on the locale's marketplace with `filter=conditions:{USED}`, books category, `q` as above, `limit=50`. Same title filter, IQR, median. `condition_assumed = "Used – Good"` (the locale config can change this). If the locale has no eBay marketplace (India), use the configured **fallback market** (e.g. EBAY_GB) and convert.
4. **Conversion:** if the source currency ≠ the locale currency, `FX.rate(from, to, date)` from Frankfurter, and set `converted: true` + `fx: {from, to, rate, date, source:"Frankfurter (ECB)", url}`.
5. **Post-appraisal rules:** used > 1.5 × replacement, or used > the locale threshold → move to `needs_appraisal`, *null the amounts* (the snapshots are kept as evidence), review entry "possible collectible".
6. **No result:** amount null, `price_status = "not_found"`, excluded from totals, review entry.
7. **Never** fill a price from anything other than a parsed provider response. `PriceQuote` validation requires `url`, `retrieved_at`, and `snapshot_path`.

### S8 — Non-book items (`vision/items.py`, `pricing/item_pricer.py`)
1. **Taxonomy** (`config/taxonomy.yaml`): `shelving, desk, table, chair, sofa, cabinet, lamp, ceiling_light, rug, curtain, framed_art, portrait, mirror, clock, coffee_machine, kettle, electronics_tv, electronics_audio, computer, plant, vase, sculpture, decor_other, other`.
2. **Dedup:** world centroid (median of back-projected points in the box) + category. DBSCAN with eps = 0.4 m for small items and 0.8 m for furniture.
3. **Describe:** best-view crop to Flash: category confirm, material, colour, **verbatim brand/model text only if visible**, and `is_artwork` flag.
4. **Dimensions:** robust 5–95 percentile extents of the item's 3D points along its principal axes (PCA in the horizontal plane + Z), in cm. Approximate, with `dims_method="recon_points"` and a confidence based on point count and depth confidence.
5. **Pricing:** art/portrait → `needs_appraisal` unless a `print` user statement is attached; then price as a "framed print W×H" range. Brand/model legible → shopping search, `status=priced`, low = high = median of matched offers (or min–max of matched offers if they differ by > 15%). Otherwise a query from category + material + size bucket (`"wooden bookcase 5 shelves 180 cm"`) → P25–P75 of ≥ 3 filtered offers → `status=range`. Fewer than 3 offers → `range` with min–max and a review entry. None → empty + review.
6. Output `s08_items.json`.

### S9 — Room geometry (`geometry/room.py`)
1. **Point cloud:** fuse recon depth points (confidence-filtered, voxel-downsampled 2 cm) in the gravity-aligned, scaled world.
2. **Floor plane:** RANSAC on points with normal ≈ +Z in the lowest 25% height band. **Ceiling plane:** RANSAC on near-horizontal points in the top band. If the ceiling isn't observed → height = null, plus review entry "ceiling not captured" (the agent should have prevented this via `NEED_CEILING`).
3. **Walls:** points between floor+0.3 m and ceiling−0.3 m → project to XY → occupancy grid (5 cm) → boundary extraction → RANSAC line fitting (iterative, min 300 points per line) → snap near-orthogonal lines to a Manhattan frame if within 8° → order lines by angle around the centroid → intersect consecutive lines → room polygon. Shelves standing against walls are fine because their front faces are parallel to the wall. Push the line outward to the farthest strong parallel cluster (the wall behind the shelves) when ≥ 2 parallel clusters exist within 0.6 m.
4. **Outputs:** `floor_area_m2` = Shapely polygon area. `length_m`, `width_m` = sides of the minimum rotated bounding rectangle. `height_m` = ceiling − floor (median distance). `wall_area_m2` = perimeter × height (gross). `shelved_wall_area_m2` = Σ over shelving units standing against a wall (unit back within 0.3 m of a wall line) of unit width × unit height. ft² = m² × 10.7639.
5. **Shape note:** `room.shape = "rectangle" | "polygon(n=6)"`, `room.polygon_m` = vertex list. `room.coverage_pct` = fraction of the polygon perimeter supported by observed wall points.
6. **Confidence:** `min(1, coverage_pct) × (1 − scale_disagreement) × plane_fit_quality`. Below 0.5 → review entry.
7. If geometry is off or failed: all room numbers null, confidence 0, review entry with the reason. **Never fill from assumptions.**

### S10 — Assemble (`packet/`)
1. **Resolve user statements** to targets: the frame seq at speech time + `target_hint` matched against S1 detections in that frame (category/colour words, left/right/top/bottom). Statements of kind `exclude_region` remove the books/items of that unit/row from totals (kept in the packet with `excluded_reason`). Unresolved statements → review queue.
2. Build the `ClaimPacket` Pydantic model (exact contract + additions, see `05`).
3. **Totals** (`packet/totals.py`, pure function, unit-tested): `book_count` = all book lines not excluded by ownership; `books_identified`/`books_unidentified` by status; `books_replacement_cost`/`books_used_value` = Σ amounts where non-null and status ≠ needs_appraisal; `items_replacement_cost_low/high` = Σ low/high for priced/range items; `excluded_from_totals` = count of lines with no amount or needs_appraisal or not owned; `shelf_run_m` from S4.
4. **Review queue** (`packet/review.py`): one entry per reason per line. Reasons: `low_id_confidence`, `unidentified_spine`, `needs_appraisal:<rule>`, `price_not_found`, `price_converted`, `price_range_few_offers`, `dim_outlier`, `dim_methods_disagree`, `count_disagreement_row`, `room_low_confidence`, `ceiling_not_captured`, `scale_anchors_disagree`, `unresolved_user_statement`, `checker_disagrees` (stretch).
5. **Validation gate:** every `frame_ref` exists, every price has url/date/snapshot, totals recomputed match, JSON validates against the contract schema. The build fails loudly otherwise.
6. **Report:** `report.html` from Jinja2: header (sweep, locale, duration), totals cards, room block with polygon SVG (stretch: items on the plan), books table (thumbnail crop link, status chip, dims + method, both prices with source links, confidence), items table, review queue, methods section (scale method, sources, assumptions), telemetry (latency per stage, cost per sweep).
7. Save `claim_packet.json`, `report.html`, `crops/` thumbnails. Notify the live bridge so the agent reads the summary.

## 7. Streaming plan (how we hit < 2 min after the sweep)

| When | What runs |
|---|---|
| `start_sweep` | Warm the Modal container (no-op call). Open HTTP clients. Start the S1 worker pool (concurrency 4) |
| During the sweep | S1 on each new detection keyframe. S5 on clusters that are stable (provisional per-frame clustering by row). Identification (S6) for the first confidently read spines. Prices warm the cache |
| `end_sweep` | Final keyframe set → S2 (GPU, ~30–40 s) ∥ remaining S1/S5 → S3 → S4 → S6 (remaining) ∥ S8 → S7 (remaining) → S9 → S10 |

## 8. Telemetry

`app/telemetry/ledger.py`: a context manager `with ledger.stage("s07_price"):` records wall time, plus `ledger.cost(provider, units, unit_price_key)`. Unit prices come from `config/pricing_rates.yaml` (taken from provider pricing pages, with URL and date). It's written to `stages/telemetry.json` and copied into `claim_packet.json → meta.telemetry` and the report footer.

## 9. Where things will break (design guards already in place)

| Failure | Guard |
|---|---|
| Adjacent thin books merged into one box | Per-row count cross-check (S1), cannot-link dedup, review entry |
| The same book counted twice across frames | 3D dedup, eps tied to median thickness |
| Hallucinated title from a blurry spine | Transcription-only prompt, catalogue match threshold, consensus across views |
| Wrong edition → wrong price | Edition only with publisher + size evidence. Otherwise price the work's in-print physical copies |
| Ebook/audiobook prices polluting replacement cost | Keyword and format filters, physical-only |
| Room scale off | Multiple anchors, disagreement reported, confidence capped |
| Ceiling never filmed | `NEED_CEILING` cue before end. Null + review if still missing |
| Live session dies at 2 min | Compression + resumption. Capture continues independently |
| An API down mid-run | Tenacity retries (3, exponential). Cached responses. Lines left blank + review, never invented |
