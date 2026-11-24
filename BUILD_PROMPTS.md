# 10 — Codex Prompt Playbook (copy-paste, in order)

## How to run Codex for this project

- Start Codex **in the repo root** so it picks up `AGENTS.md`. Use the strongest coding model available to you with **high reasoning effort** for Phases 2, 5, 6, 8 (the hard ones). Medium is fine elsewhere.
- Approval mode: let it edit files inside the workspace, but keep command approval on for anything that installs packages or touches the network outside tests.
- **One phase per Codex session.** Start a fresh session per phase (context stays clean). Every prompt below re-points it at the docs.
- Pattern for every phase: paste the **PLAN prompt**, read its plan, fix anything wrong, then send **GO**. After it finishes, paste the **REVIEW prompt**, then read the diff yourself and commit.
- Copy `prompts/*.md` from this kit into `app/prompts/` in Phase 0. Codex must use them as-is, not rewrite them.
- If Codex goes off the rails: use the **RESET** prompt (§R1), `git restore .`, and retry with a narrower scope.

### The two universal follow-ups

**GO**
```
Go. Implement exactly the approved plan. Follow AGENTS.md integrity rules and coding standards. When done: run `make check`, fix failures, then give me (1) files changed, (2) how to verify manually, (3) any deviation from the docs and why, (4) which AGENTS.md integrity rules applied and how you respected them.
```

**REVIEW** (paste after every phase)
```
Review your own work for this phase as a strict senior reviewer, before I commit:
1. Check every AGENTS.md integrity rule against the diff. Quote any line that could let a model produce a number, a price without url/snapshot, a guessed title, or a hardcoded room fact.
2. List any file over 300 lines, any function over 50 lines, any magic number not in config/settings.yaml.
3. List untested branches in the new code and add tests for the top 3.
4. List anything I'd struggle to explain in a code review and add a short "why" comment there.
Don't add features. Fix only what this review finds, then run `make check`.
```

---

## Prompt 0: Orientation + clarifying questions (session 1)
```
You're joining a take-home project. Read these files fully before replying: AGENTS.md, docs/01_PROBLEM_BREAKDOWN.md, docs/02_PRD.md, docs/03_TECH_STACK.md, docs/04_ARCHITECTURE.md, docs/05_DATA_SCHEMA.md, docs/06_USER_FLOWS.md, docs/07_UI_UX.md, docs/09_PLAN.md.

Then:
1. Summarise in 8 bullets what we're building and the 6 integrity rules that matter most.
2. Ask me exactly 5 clarifying questions about edge cases, contradictions between docs, or missing details that would block implementation. Prioritise questions about geometry/scale, dedup, pricing sources and the live session.
3. List the top 5 technical risks you see in docs/04_ARCHITECTURE.md and how you'd de-risk each in the first phase it appears.
Don't write any code yet.
```
*(Answer its questions. If an answer changes a doc, ask it for a doc patch and apply it yourself.)*

## Prompt 1: Plan check
```
Using docs/09_PLAN.md as the source of truth, produce PLAN_CHECK.md at the repo root with, for each phase 0–11:
- the exact files to be created (paths per AGENTS.md §5 repo map),
- the public functions/classes per file with signatures,
- the tests per phase,
- external accounts/keys needed before that phase.
Flag any phase whose scope is too big for one session and propose a split. Don't change docs/09_PLAN.md. Don't write application code.
```
Then: `git add PLAN_CHECK.md && git commit -m "docs: plan check"`

---

## Phase 0: Skeleton, contract, totals

**PLAN**
```
Phase 0 per docs/09_PLAN.md. Read AGENTS.md, docs/03_TECH_STACK.md §2 and §7, docs/05_DATA_SCHEMA.md (all), docs/09_PLAN.md Phase 0.
Plan the implementation of:
- pyproject.toml (uv, Python 3.12, deps exactly from docs/03 §2), Makefile with the targets in AGENTS.md §4, ruff config, .gitignore (sweeps/, cache/, .env, *.npz, markers.pdf), .env.example from docs/03 §7.
- config/settings.yaml and config/taxonomy.yaml (new, per docs/05 §4). config/locales/IN.yaml, GB.yaml and config/pricing_rates.yaml ALREADY EXIST from the kit: keep their values, only add missing keys. Never invent prices.
- app/settings.py (pydantic-settings, loads .env + YAML).
- app/packet/models.py: the FULL contract + additions from docs/05 §1 with every validator from §1.1.
- app/packet/totals.py: pure compute_totals(books, items, currency) per docs/04 S10 step 3 and docs/05 Totals.
- app/pipeline/context.py (StageContext), app/pipeline/artifacts.py (stub models for s00–s10 docs per docs/05 §2), app/telemetry/ledger.py and events.py.
- app/cli.py (Typer) with commands serve, replay, stage, reprice, evaluate, calibrate, ingest-video, make-markers. Only make-markers and serve are implemented now; others print "not implemented in phase 0".
- make-markers: OpenCV ArUco DICT_4X4_50, one marker per A4 page with the ID and intended size printed under it, plus a 10 cm ruler line for print-scale checking; output a PDF.
- app/server/main.py: FastAPI app, /healthz, static web/ at /.
- app/prompts/*.md already exist (agent_system, detect, transcribe, items, rerank). Add app/prompts/loader.py to read them. Don't rewrite their content.
Tests: test_models.py (validators: price without url fails; converted without fx fails; unidentified with title fails; needs_appraisal with amount fails), test_totals.py (nulls, appraisal, excluded, converted, items low/high).
Output the plan only.
```
→ **GO** → **REVIEW** → verify: `make check`, `make markers`, print it, measure it with a ruler, set `MARKER_SIZE_MM`.

---

## Phase 1: Capture channel

**PLAN**
```
Phase 1 per docs/09_PLAN.md. Read AGENTS.md, docs/04_ARCHITECTURE.md §3 and §4.1, docs/05_DATA_SCHEMA.md §2 (frames.jsonl) and §3, docs/06_USER_FLOWS.md §5.2, docs/07_UI_UX.md §1 Screen 1 and §3.
Plan:
- web/index.html, web/styles.css, web/js/main.js, camera.js (getUserMedia env camera ideal 1920x1080, fallback 1280x720; grab frames via canvas at HIRES_FPS; JPEG q0.85), motion.js (DeviceMotion/Orientation, iOS requestPermission on the Start tap, gyro magnitude in deg/s, gravity vector), ws.js (capture socket, binary frame format from docs/06 §5.2, back-pressure max 3 un-acked, reconnect with backoff and buffer ≤20), ui.js (QC pill, speed bar, cards seen). Screen wake lock.
- POST /api/sweeps creates sweeps/<id>/sweep.json with device string from the client (UA + resolution).
- app/server/ws_capture.py: parse header+JPEG, hand to app/capture/storage.py, which runs faces.py (blur faces; use OpenCV YuNet if available in opencv-contrib, else Haar cascade), quality.py (blur = Laplacian variance on 960px-wide gray; glare = fraction V>250 in central 80%; exposure = mean luma), markers.py (ArUco detect → ids + corners), writes the JPEG to frames/f_<seq:06d>_<t_ms:07d>.jpg and appends to frames.jsonl. Returns qc + ack.
- Quality thresholds from config/settings.yaml capture.*.
Tests: quality metrics on synthetic images (sharp checkerboard vs gaussian-blurred; white patch glare), marker detection on a generated marker image, header parsing, storage writes the expected files.
Output the plan only.
```
→ **GO** → **REVIEW** → verify on your phone over HTTPS: frames saved, QC pill reacts, face blur works.

---

## Phase 2: Live agent bridge

**PLAN**
```
Phase 2 per docs/09_PLAN.md. Read AGENTS.md, docs/04_ARCHITECTURE.md §5, docs/06_USER_FLOWS.md §2, §3 and §5.1, app/prompts/agent_system.md.
Important facts to design around:
- Gemini Live audio+video sessions terminate after ~2 minutes WITHOUT context window compression. Enable context_window_compression with a sliding window. Enable session resumption: keep the latest resumption handle from session_resumption_update messages; on GoAway or connection drop, reconnect with the handle. The capture websocket must be unaffected by live reconnects.
- Connection lifetime is limited (~10 min) — handle GoAway gracefully.
- Use the google-genai SDK Live API (client.aio.live.connect). Model ID from LIVE_MODEL env. Check the installed SDK's type names (LiveConnectConfig, ContextWindowCompressionConfig, SlidingWindow, SessionResumptionConfig, RealtimeInputConfig/ActivityHandling, FunctionDeclaration with behavior NON_BLOCKING, FunctionResponse scheduling) by inspecting the installed package. Do not guess names; print them if unsure.
Plan:
- app/live/bridge.py: LiveBridge class (connect, send_audio, send_frame, send_text, inject_cue, run receive loop, handle tool calls in background tasks, transcripts, resumption, reconnect, close).
- app/live/tools.py: declarations + handlers for set_locale, start_sweep, end_sweep, get_sweep_status, record_user_statement, mark_landmark, get_packet_summary (docs/04 §5 table). Handlers write to sweep.json / user_statements.jsonl / events.jsonl. get_sweep_status and get_packet_summary return stub data marked "stub" for now. set_locale validates against config/locales/*.yaml.
- app/server/ws_live.py: protocol per docs/06 §5.1 (binary audio in, JSON frames; agent audio out as binary).
- web/js/audio.js + web/audio-worklet.js: mic → PCM16 16 kHz mono chunks (resample in the worklet), playback queue at 24 kHz with flush on interruption, agent_state handling; live low-res frames 768px q0.6 at 1 fps; captions UI.
- transcript.jsonl writing; tool_event messages to the client.
Tests: tool handlers (locale validation, statement logging with frame seq lookup), the reconnect logic with a fake session that raises GoAway, the protocol parser. Mock the Gemini client completely.
Output the plan only.
```
→ **GO** → **REVIEW** → verify: a 4-minute call with the camera on doesn't drop; corrections are logged.

---

## Phase 3: Capture monitor → spoken direction

**PLAN**
```
Phase 3 per docs/09_PLAN.md. Read AGENTS.md, docs/04_ARCHITECTURE.md §4 (all), docs/06_USER_FLOWS.md §2 rows 6–8 and 13.
Plan:
- app/capture/monitor.py: CaptureMonitor fed by every frame record + motion_only samples; rolling 2 s windows; cue candidates TOO_FAST, BLURRY, GLARE, TOO_DARK, TOO_FAR (hook only, data later), ROW_MISSED (hook), ART_QUESTION (hook), NEED_CEILING, NEED_CORNERS, CARD_NOT_SEEN, PROGRESS with the priority order and rate limits in docs/04 §4.3; never emit while the user is speaking (bridge exposes user_speaking state from input transcription activity).
- app/live/cues.py: turn a cue + metric facts into the "[CAPTURE MONITOR] …" text and inject via the bridge; log cue_sent with metrics to events.jsonl.
- app/capture/coverage.py: cards seen, landmarks (from mark_landmark + later detections), rows (placeholder structure for Phase 4).
- Replace the get_sweep_status stub with real coverage + gaps + provisional counts placeholder.
- Thresholds all from config/settings.yaml.
Tests: synthetic metric streams → expected cues; rate limiting (min gap, same-type gap); suppression while speaking; the gaps list when the ceiling isn't seen.
Output the plan only.
```
→ **GO** → **REVIEW** → verify live: fast pan → "slow down"; "I'm done" without ceiling → the agent asks for the ceiling.

---

## Phase 4: Detection + streaming orchestrator

**PLAN**
```
Phase 4 per docs/09_PLAN.md. Read AGENTS.md, docs/04_ARCHITECTURE.md S0, S1 and §7, docs/05_DATA_SCHEMA.md §2 (s00, s01), app/prompts/detect.md.
Plan:
- app/vision/client.py: VisionClient protocol + GeminiVisionClient (VISION_MODEL, JSON schema response, image parts, retries via tenacity, token usage → ledger). A FakeVisionClient for tests.
- app/vision/detect.py: call with the detect.md prompt; convert box_2d (0–1000, [ymin,xmin,ymax,xmax]) to pixel BBox with angle; validate/clip; drop boxes with min side < 6 px.
- app/pipeline/stages/s00_keyframes.py: streaming detection-set selection (blur/glare thresholds + novelty ≥ min_novelty via phase correlation on downscaled gray) and the end-of-sweep reconstruction set (40–80 frames, pose diversity from integrated gyro + sharpness, always include marker frames).
- app/pipeline/stages/s01_detect.py (incremental append-safe writes) and app/pipeline/orchestrator.py (asyncio queue, concurrency 4 during the sweep, the full DAG on end_sweep per docs/04 §7, pipeline events, ledger timings, per-stage failure isolation: a failed stage marks its outputs failed but the DAG continues where possible).
- Provisional inventory builder → inventory WS events (books per unit-row from the best frame, items list), coverage rows from shelf_board detections; feed text_px to the monitor for TOO_FAR; ART_QUESTION when framed_art/portrait is first detected.
- app/cli.py: ingest-video (dev only: ffmpeg/OpenCV sample at 3 fps → a sweep folder with frames.jsonl, motion fields null) and replay --until s01.
Tests: box conversion, keyframe novelty selection, orchestrator ordering with fake stages, failure isolation.
Output the plan only.
```
→ **GO** → **REVIEW** → verify: inventory updates live. `replay` reproduces s01. Eyeball debug boxes on 5 frames.

---

## Phase 5: Geometry (hardest; high reasoning)

**PLAN**
```
Phase 5 per docs/09_PLAN.md. Read AGENTS.md, docs/04_ARCHITECTURE.md S2, S3, S4 carefully, docs/05_DATA_SCHEMA.md §2 (s02–s04).
Before planning, inspect the MapAnything and VGGT repos' README/inference examples (facebookresearch/map-anything, facebookresearch/vggt) to get the exact install steps, model IDs and output formats (extrinsics convention, intrinsics, depth, confidence, metric scale). Write what you found in a short note at the top of the plan, including licence notes for the checkpoints. Don't guess APIs.
Plan:
- gpu/modal_recon.py: Modal app, GPU image with torch + map-anything (+ vggt fallback), weights cached in a Modal Volume, functions warmup() and reconstruct(jpeg_bytes_list, model) returning npz bytes (per-frame K, T_world_cam (OpenCV convention, state it), depth fp16, conf fp16, metric_scale_flag). Resize frames to the model's expected size; return the resize factors.
- app/geometry/recon_client.py: modal | local | off backends behind ReconClient.
- app/geometry/scale.py: anchors — aruco (marker corners from frames.jsonl → map to recon frame pixel coords via resize factors → sample depth (median 5x5) → back-project → edge lengths vs MARKER_SIZE_MM), model_metric, user_stated (from user_statements kind shelf_dimension, after unit matching), book_format_check (check only) → weighted median, disagreement %, scale_method string.
- gravity alignment from frames.jsonl gravity vectors (camera frame → world via T) cross-checked with floor RANSAC.
- app/geometry/lift.py (back-project bbox points with depth; detection-only frames use the nearest recon frame + homography if overlap is sufficient, else skipped and logged), app/geometry/dedup.py (shelf units, rows by board heights, 1-D DBSCAN along the row axis with cannot-link for same-frame detections, best/alt view scoring, best-frame fallback count), app/geometry/homography.py + measure.py (marker_plane → recon_depth → none, depth-offset correction, sanity flags, method disagreement, row spans → shelf_run_m, sum_thickness_m).
- stages s02_geometry.py, s03_dedup.py, s04_measure.py; geometry/pointcloud.ply and per-row debug strip PNGs (numbered books) when DEBUG_GEOMETRY=1.
Tests (no GPU): synthetic pinhole camera + known plane with a marker → scale recovery within 1%; synthetic multi-frame detections of N books with jitter → dedup count == N; a cannot-link case; homography measurement of a synthetic 20×2 cm spine within 2%; the anchor fusion maths.
Output the plan only.
```
→ **GO** → **REVIEW** → verify on the recorded sweep: count within ±10%, 5 spines within ±15%, anchor disagreement < 10%. **Don't move on until this holds.**

**Debug prompt for Phase 5** (if numbers are off)
```
The geometry numbers are off: <paste: count true vs ours per row, 5 spine dims true vs ours, scale anchors from s02_geometry.json>. Without changing thresholds yet, write a diagnostic script scripts/diag_geometry.py that, for sweep <id>, prints per-row: detections per frame, cluster sizes, merged/split suspects (clusters whose width > 1.8× median thickness, or pairs closer than 0.3× median), and for the 5 named books: method used, pixel height, depth samples, marker distance. Save the per-row strip PNGs. Then propose the single most likely root cause with evidence from the script output, and the minimal fix. Don't implement the fix until I say go.
```

---

## Phase 6: Transcription + identification (high reasoning)

**PLAN**
```
Phase 6 per docs/09_PLAN.md. Read AGENTS.md (integrity rules 1, 3, 4 especially), docs/04_ARCHITECTURE.md S5 and S6, docs/05_DATA_SCHEMA.md Book fields and s05/s06, app/prompts/transcribe.md and rerank.md.
Plan:
- app/vision/transcribe.py: rotated-box crop with 8% pad, upright rotation(s), upscale to short side ≥ 96 px, batch ≤12 crops per call, schema-validated parsing, guard (reject lines > 80 chars or containing prompt example strings), multi-view consensus (token Jaccard ≥ 0.6) → consensus_text, legibility.
- s05_transcribe.py incremental during the sweep for stable clusters + finalisation.
- app/identify/openlibrary.py (search.json with fields, editions endpoint, User-Agent with OPENLIBRARY_CONTACT, ≤5 req/s), googlebooks.py (volumes q=intitle:+inauthor:, metadata/ISBN only, never prices), both via app/net/http.py with the cache.
- app/identify/match.py: normalisation (case, punctuation, leading articles, subtitles after ':'), features (title_sim token_set_ratio, author surname match, publisher_sim, legibility, margin, n_views_agree), raw score with weights from config, id_confidence (uncalibrated passthrough until Phase 10 calibration exists in config), decision with tau_accept/tau_review.
- app/identify/edition.py: strict edition rule from docs/04 S6 step 7.
- optional rerank via rerank.md only when top-2 within 0.05; may only change which candidate; never the threshold.
- s06_identify.py writing candidates for audit; unidentified → title/author/edition/isbn empty, spine_text_raw kept.
Tests: normalisation cases; author initials ("J. R. R. Tolkien" vs "Tolkien"); partial "…" titles; ties; the unidentified path never sets title; the edition rule positive/negative; a rerank returning an id not in the list is rejected.
Output the plan only.
```
→ **GO** → **REVIEW** → verify: 20 legible spines, ≥ 14 right, ≤ 1 confidently wrong.

---

## Phase 7: Book pricing

**PLAN**
```
Phase 7 per docs/09_PLAN.md. Read AGENTS.md (integrity rules 1, 2, 4, 7), docs/04_ARCHITECTURE.md S7, docs/05_DATA_SCHEMA.md ReplacementCost/UsedValue/FxInfo/PriceQuote and config/locales/*.yaml.
Before planning, check the current SerpApi Google Shopping response format (shopping_results fields: title, price/extracted_price, source, link/product_link, second_hand_condition if any), the eBay Browse item_summary/search response (itemSummaries[].price.value/currency, condition, itemWebUrl) and the OAuth client-credentials flow, and the Frankfurter v1/v2 endpoints. Record the exact fields you'll parse in the plan, and save one real example response per provider under tests/fixtures/ (I'll run the fetch if you give me the curl commands; don't commit keys).
Plan:
- app/net/http.py + cache.py (SQLite; key = provider+normalised query+locale; TTL; store raw JSON + fetched_at; copy the snapshot into sweeps/<id>/evidence/prices/<line>_<kind>.json).
- providers: serpapi_shopping.py (ShoppingProvider), ebay_browse.py (UsedMarketProvider; marketplace header; filter conditions:{USED}; books category id from locale config), frankfurter.py (FxProvider with date).
- pricing/filters.py (title fuzzy ≥ 80 vs work title, physical-only exclusion list, price > 0, IQR outlier drop when n ≥ 3), appraisal.py (pre rules: user statements, year < min_year, spine text keywords; post rules: used > threshold, used/new > ratio → null amounts, keep snapshots), book_pricer.py (new + used + conversion + not_found path), s07_price_books.py (concurrency 6, ledger costs per call).
- cli reprice --sweep --country --limit 10 → docs/second_country.md table (title, IN new/used, GB new/used, sources, converted flags).
Tests with fixtures via respx: median/IQR maths, the physical-only filter (Kindle/audiobook rejected), conversion sets converted+fx, not_found → null + review flag, appraisal pre/post, the PriceQuote validator rejects an amount without url/snapshot.
Output the plan only.
```
→ **GO** → **REVIEW** → verify: 15 hand checks, ≥ 12 within 25%. Every price is clickable. The GB table is generated.

---

## Phase 8: Items + room geometry (high reasoning)

**PLAN**
```
Phase 8 per docs/09_PLAN.md. Read AGENTS.md, docs/04_ARCHITECTURE.md S8 and S9, docs/05_DATA_SCHEMA.md Item/Room/s08/s09, app/prompts/items.md, config/taxonomy.yaml.
Plan:
- app/vision/items.py (best-view crop → items.md → schema), item dedup by world centroid + category (eps 0.4 m small / 0.8 m furniture, category groups from the taxonomy), dims via 5–95 percentile extents of back-projected points in the box along PCA axes (cm), dims_confidence.
- app/pricing/item_pricer.py: artwork → needs_appraisal unless a resolved 'print' statement → range query "framed print {w}x{h} cm"; legible brand/model → exact query → priced (low=high=median, or min–max if spread > 15%); else template query from taxonomy → P25–P75 of ≥3 filtered offers → range; <3 offers → min–max + review; none → empty + review. Same evidence/snapshot rules as books.
- s08_items.py.
- app/geometry/room.py: fuse depth points (conf filter, 2 cm voxel), floor RANSAC (lowest band, normal ≈ +Z), ceiling RANSAC (top band) or null, wall band projection → 5 cm occupancy grid → boundary → iterative RANSAC lines (min 300 pts) → Manhattan snap ≤ 8° → order by angle → intersect → polygon; push walls outward to the farthest parallel cluster within 0.6 m (shelves vs wall behind); areas (Shapely), min rotated rectangle for length/width, perimeter × height, shelved wall area from shelving units within 0.3 m of a wall; coverage_pct; confidence per docs/04 S9.6; room_debug.png.
- s09_room.py; null everything + review reason if geometry is off/failed.
Tests: synthetic 4×3×2.7 m box room point cloud with noise and a shelf block against one wall → areas within 2% and the wall pushed behind the shelf; an L-shaped room → polygon area within 3%; no ceiling points → height null; item dedup and percentile dims on synthetic points.
Output the plan only.
```
→ **GO** → **REVIEW** → verify against the tape measure: floor within 15%, wall within 20% before tuning.

---

## Phase 9: Assembly, review queue, report, readback

**PLAN**
```
Phase 9 per docs/09_PLAN.md. Read AGENTS.md, docs/04_ARCHITECTURE.md S10, docs/05_DATA_SCHEMA.md §1 (all validators) and §3, docs/07_UI_UX.md §1 Screen 2 and §2, docs/06_USER_FLOWS.md §2 rows 15–17.
Plan:
- app/packet/resolve_statements.py: for each user statement, take its frame seq; match target_hint words (colour, category nouns, left/right/top/bottom/first/second, shelf/row words) against S1 detections and S3 units/rows in that frame; produce resolved_to + applied_effect; unresolved → review.
- app/packet/review.py (all reason codes listed in docs/04 S10.4, severity, evidence pointers).
- app/packet/validate.py (every frame_ref/crop_ref/snapshot_path exists; price evidence; totals recompute equality; contract schema) → meta.validation; raise on failure.
- s10_assemble.py: build ClaimPacket (books ordered by shelf then position; ids b_0001…), write crops/ with the bbox drawn, claim_packet.json, report.html.
- app/packet/report.py + templates/report.html.j2: self-contained HTML (inline CSS, relative links), sections per docs/07 Screen 2, money via locale formatting, filter chips with tiny inline JS, room polygon SVG.
- Real get_packet_summary (totals + review count + top 3 review reasons, from code) and a packet_ready event; the bridge sends the summary as a tool result with INTERRUPT scheduling so the agent reads it back.
- Web: pipeline progress list + packet-ready card.
Tests: the validation gate catches a missing frame, a price without url, and a totals mismatch; the statement resolver on fixture detections (portrait/print, bottom shelf right/exclude); the review queue for each reason code; report renders with an empty items list.
Output the plan only.
```
→ **GO** → **REVIEW** → verify a full live sweep end-to-end: spoken summary plus a report in < 5 min (target < 2).

---

## Phase 10: Evaluation, calibration, the measured fix

**PLAN**
```
Phase 10 per docs/09_PLAN.md. Read AGENTS.md, docs/11_GROUND_TRUTH_AND_EVAL.md (all), docs/05_DATA_SCHEMA.md §5.
Plan:
- app/eval/ (or eval/ helpers) + cli evaluate: load the GT CSVs; match predicted books to GT by (unit,row,position) with ±2 position tolerance and title similarity; compute every metric exactly as defined in docs/11 §4 (count error, ID accuracy on legible, confidently-wrong rate, dims error on the 20 measured, price error on the 15 checked with the same source type, item recall + category accuracy, floor/wall error, time to packet); a per-shelf breakdown; PASS/FAIL per bar; write docs/results.md and docs/results.json; never drop rows that failed to match (count them as misses).
- cli calibrate: logistic regression on the S6 features vs GT correctness for legible spines; choose tau_accept = the smallest threshold with confidently-wrong ≤ 2% (report the 95% Wilson interval); write it to config/settings.yaml with a comment (fitted on sweep id, n, date); save a reliability plot PNG to docs/.
- Telemetry summary into results (latency per stage, time to packet, cost per sweep by provider).
Tests: metric functions on tiny hand-built GT/pred tables, including edge cases (an extra predicted book, a missing book, an unidentified legible spine counts as wrong-but-not-confident).
Output the plan only.
```
→ **GO** → **REVIEW** → run `make eval`. Then use the **measured fix prompt**:

**Measured fix prompt**
```
Here is docs/results.md from sweep <id>: <paste>. Identify the 3 worst errors by impact on the pass bars. For the #1 error: (1) find the root cause using the stage artifacts (cite the exact JSON entries/frames), (2) propose the smallest fix, (3) predict which metric moves and by roughly how much. Don't implement yet.
```
then after **GO**: `make replay SWEEP=…` → `make eval` → record before/after in `docs/failure_log.md`.

---

## Phase 11: Deliverable documents

**README prompt**
```
Write README.md per docs/12_DELIVERABLES_AND_REVIEW.md §1 outline. Facts only from the repo, config and docs/results.md — no invented numbers. Include: the one-liner, a 90-second architecture summary with a link to docs/architecture.md, Quickstart (< 15 min: uv sync, .env, Modal deploy or GEOMETRY_BACKEND=off, phone HTTPS via Tailscale/cloudflared, print cards and set MARKER_SIZE_MM), how to run a sweep, how to replay/evaluate/reprice, the reference app section (kept/changed/threw away — use my notes: <paste your 5 bullets>), models & services used (table), AI coding tools used (Codex, Claude), the assumptions list (docs/01 §9), the results summary table copied from docs/results.md, cost per sweep and latency per stage, known limitations, and links to all deliverables. Keep it under 250 lines.
```

**Architecture note prompt**
```
Write docs/architecture.md as a ONE-PAGE note per docs/12 §2: a mermaid pipeline diagram (simplified from docs/04 §1), a "which model does what" table, "where metric scale comes from" (anchors, fusion, disagreement on our sweep from s02_geometry.json), and "where prices come from" (providers, filters, conversion, appraisal rules). Use real values from the demo sweep's artifacts. Must fit one printed page (~450 words + diagram).
```

**Failure log prompt**
```
Draft docs/failure_log.md as ONE page per docs/12 §3 from docs/results.md, the stage artifacts and my notes: <paste notes on what broke and what you tried>. Three worst errors: symptom (with numbers), root cause (with artifact evidence), what I changed or would change. Include the measured before/after fix, cost per sweep and latency per stage tables from telemetry, and "what I'd do with two more weeks". No vague lines like "use better models".
```

**Explain-the-code prompt (review-call prep; run per module)**
```
Explain app/<module>.py to me as if I'll be questioned on it line by line in a code review. For each function: purpose, inputs/outputs, the non-obvious lines and why they exist, failure modes, and one question a reviewer might ask with a good answer. Don't change code.
```

---

## Recovery & utility prompts

**R1: Reset when Codex drifts**
```
Stop. You're drifting from the approved plan/docs. List every change you made that isn't in the approved plan. Then revert those changes only, and continue with the approved scope. Re-read AGENTS.md §1 and §3 first.
```

**R2: Failing tests**
```
`make check` fails: <paste output>. Find the root cause (not the symptom). Explain it in 3 lines, then fix it with the smallest change. Don't weaken or delete tests unless a test is wrong, and if so explain why.
```

**R3: Live voice issues**
```
Live voice problem: <describe: e.g. agent audio choppy / session drops at ~2 min / agent ignores monitor cues / talks over user>. Inspect bridge.py, audio.js, audio-worklet.js and events.jsonl from sweep <id>. List the 3 most likely causes ranked with evidence, and how to confirm each with a log line or a tiny test. Don't change code until I pick one.
```

**R4: Cost/latency over budget**
```
time_to_packet is <X> s and cost/sweep is $<Y> (telemetry.json pasted below). Propose up to 3 changes ranked by (seconds saved or $ saved) / effort, e.g. starting a stage earlier during the sweep, batching more crops per call, raising cache hits, reducing reconstruction frames. Each must keep the integrity rules. Don't implement yet.
```

**R5: Integrity audit (run before submission)**
```
Audit the whole repo against AGENTS.md §1. Search for: any code path where a model output can become a numeric field in the packet; any price assignment not originating from providers/*; any title assignment not from identify/match.py's accepted candidate; any constant that encodes my room (dimensions, counts, titles, prices); any prompt that lets the live agent state numbers not from tools. Report file:line for each finding with severity, and propose fixes.
```

**R6: Fresh-clone test**
```
Simulate a stranger: list every step from `git clone` to a running sweep using only README.md. Flag anything missing (a key, a command, a file, a version) or anything that would take > 15 minutes. Then patch README.md and .env.example accordingly.
```

**R7: Commit message (you commit, no AI attribution)**
```
Write a conventional commit message (subject ≤ 72 chars + 3–6 bullet body) for the staged diff. Don't include any Co-Authored-By, AI-tool, or session lines.
```
