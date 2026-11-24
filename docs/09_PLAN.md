# 09 — Build Plan (PLAN.md)

Twelve phases (0–11). Each phase is a short Codex session: **plan → approve → implement → tests → you review the diff → you commit**. Every phase has a "done when" you verify yourself.

**Tiering** (if time runs short, cut from the bottom of each phase, never the integrity rules):
- **Tier A** = required to pass the brief.
- **Tier B** = stand-out work. Do it only after Tier A of that phase passes.

Parallel human track (not Codex): ground truth collection (`11`), accounts/keys, printing cards, test recordings.

---

## Phase 0 — Skeleton, contract, totals (≈1 h)
**Tier A**
- `pyproject.toml` (uv), `Makefile`, `.env.example`, `.gitignore`, `ruff` config, `app/settings.py` (env + `config/settings.yaml`), `config/` files from `05` §4.
- `app/packet/models.py`: the full contract + additions (Pydantic) with validators from `05` §1.1.
- `app/packet/totals.py` + `tests/unit/test_totals.py` (hand-built fixture packet, edge cases: nulls, appraisal, excluded, converted).
- `app/pipeline/context.py` (`StageContext`: sweep dir, settings, ledger, clients), `artifacts.py` (stage doc models, minimal now).
- `app/telemetry/ledger.py` + `events.py`.
- `app/cli.py` with Typer stubs; `make-markers` implemented (OpenCV ArUco `DICT_4X4_50`, A4 PDF via Pillow, size printed on the card).
- FastAPI app with `/healthz` and static serving of `web/`.

**Done when:** `make check` is green. `make markers` creates a PDF, and the printed marker measures the stated size (±1 mm). `uv run python -c "from app.packet.models import ClaimPacket"` works.

---

## Phase 1 — Capture channel (phone → disk) (≈2 h)
**Tier A**
- `web/index.html`, `styles.css`, `js/camera.js` (getUserMedia 1920×1080 env camera, fallback 1280×720), `js/ws.js` (capture socket with back-pressure ≤ 3 in flight), `js/motion.js` (DeviceMotion; iOS permission on tap), wake lock.
- Binary frame protocol (`06` §5.2), `app/server/ws_capture.py`, `app/capture/storage.py` (write JPEG + `frames.jsonl`), `faces.py` (blur faces on save), `markers.py` (ArUco detect per frame), `quality.py` (blur/glare/exposure).
- `POST /api/sweeps`, `sweep.json` creation, device string.
- `qc` messages back to the client, plus the QC pill and speed bar UI.

**Tier B:** client-side gating by gyro rate. Adaptive JPEG quality on slow links.

**Done when:** on your phone over HTTPS, a 60 s capture saves ≥ 100 frames at 1080p with correct `frames.jsonl`. The QC pill reacts when you shake the phone or point at a lamp. Markers are detected when a card is in view. Faces are blurred (test with a photo of a face on a screen).

---

## Phase 2 — Live agent bridge (≈2.5 h)
**Tier A**
- `app/live/bridge.py`: Gemini Live connect with `LIVE_MODEL`, audio in/out, input/output transcription, barge-in, **context window compression (sliding window)**, **session resumption** (store the handle; reconnect on GoAway/drop), low-res frame forwarding at 1 fps.
- `web/js/audio.js` + `audio-worklet.js`: mic → PCM16 16 kHz; playback of 24 kHz agent audio with interruption flush.
- `app/server/ws_live.py` and the protocol in `06` §5.1.
- `app/live/tools.py`: `set_locale`, `start_sweep`, `end_sweep`, `get_sweep_status` (returns stub data for now), `record_user_statement`, `mark_landmark`, `get_packet_summary` (stub). All `NON_BLOCKING`. Scheduling rules from `04` §5.
- `app/prompts/agent_system.md`: full system instruction per `04` §5 and `06` §7.
- Transcript to `transcript.jsonl`; tool calls to `events.jsonl`.

**Done when:** you can hold a 4-minute conversation with the camera on and it doesn't drop (proves compression). Saying "I'm in India" triggers `set_locale(IN, INR)`. Saying "that's a print" logs a user statement with a frame seq. Killing Wi-Fi for 5 s recovers.

---

## Phase 3 — Capture monitor → spoken direction (≈1.5 h)
**Tier A**
- `app/capture/monitor.py`: rolling 2 s windows over QC metrics + motion. Cue candidates with priorities and rate limits (`04` §4.3). Never while the user is speaking.
- `app/live/cues.py`: format cue facts → inject into the live session. Log `cue_sent` with metrics.
- `app/capture/coverage.py`: cards seen, ceiling/corner flags (from `mark_landmark` for now; rows come in Phase 4).
- `get_sweep_status` returns real coverage + gaps.
- Unit tests: synthetic metric streams produce the right cues and respect rate limits.

**Tier B:** a `TOO_FAR` cue using the text-px proxy (needs Phase 4 detections, so wire it later).

**Done when:** a deliberately fast pan makes the agent say "slow down" within ~3 s. Pointing at a bright window gets a glare cue. Saying "done" without filming the ceiling makes the agent ask for it.

---

## Phase 4 — Detection + streaming orchestrator (≈2 h)
**Tier A**
- `app/vision/client.py` (Gemini Flash, JSON schema output, retries, cost ledger), `app/prompts/detect.md`, `vision/detect.py` (0–1000 → px, rotated boxes, validation).
- `s00_keyframes.py` (detection set streaming + reconstruction set at end), `s01_detect.py`.
- `pipeline/orchestrator.py`: during the sweep, queue new detection keyframes (concurrency 4). On `end_sweep`, run the DAG from `04` §7. Emit `pipeline` events.
- Provisional inventory (books per unit row from the best frame; items list) → `inventory` WS events → UI bottom sheet.
- Coverage rows from detections (shelf boards). The `TOO_FAR` cue now uses the text-px proxy.
- `cli ingest-video` (dev only) and `cli replay --until s01`.

**Tier B:** per-row "how many spines" second-opinion count.

**Done when:** during a live sweep the inventory sheet updates within ~5 s of new shelves. `replay` on a saved sweep regenerates `s01_detections.json`. Drawing debug boxes on 5 frames shows every spine boxed separately (check thin books).

---

## Phase 5 — Geometry: reconstruction, scale, dedup, measurement (≈3 h, the hardest phase)
**Tier A**
- `gpu/modal_recon.py`: Modal app with GPU image (torch + MapAnything, VGGT fallback), function `reconstruct(frames: list[bytes], model) -> npz` (poses, intrinsics, depth fp16, conf). Warm-up function.
- `geometry/recon_client.py` (modal | local | off), `s02_geometry.py`: gravity alignment, ArUco anchors (corner depth back-projection), model-metric anchor, user-stated anchor, weighted-median fusion, disagreement, `scale_method` string.
- `geometry/lift.py`, `dedup.py` (row structure, DBSCAN with cannot-link), `s03_dedup.py` + the best-frame fallback.
- `geometry/homography.py`, `measure.py`, `s04_measure.py` (marker_plane → recon_depth → none, sanity flags, shelf run).
- Unit tests with synthetic geometry (known planes/points) and a printed-card photo fixture (homography accuracy).

**Tier B:** debug outputs: `geometry/pointcloud.ply`, per-row PNG strips with numbered books (great for the failure log and the review call).

**Done when:** on your recorded sweep: the book count is within ±10% before tuning; 5 hand-measured spines are within ±15%; the marker-derived scale and MapAnything disagree < 10%. If not, stop and debug before moving on (this phase decides 30% of the score).

---

## Phase 6 — Transcription + identification (≈2 h)
**Tier A**
- `prompts/transcribe.md`, `vision/transcribe.py` (upright crops, both rotations, batching, consensus), `s05_transcribe.py` (starts during the sweep for stable clusters).
- `identify/openlibrary.py`, `googlebooks.py`, `match.py` (features, score), `edition.py` (strict rule), `s06_identify.py` with thresholds from config. Unidentified lines keep `spine_text_raw` only.
- Tests: fuzzy match cases (subtitle differences, "The" prefix, author initials), the edition rule, the unidentified path never sets title.

**Tier B:** optional LLM re-rank for ties (ID-only output). `identify/calibrate.py` (fit in Phase 10).

**Done when:** on your sweep, a spot check of 20 legible spines gets ≥ 14 right and ≤ 1 wrong-but-confident. Unreadable spines show as unidentified with dims.

---

## Phase 7 — Book pricing (≈2 h)
**Tier A**
- `net/http.py` + `net/cache.py` (SQLite cache, TTL, snapshot copy into the sweep evidence folder).
- `pricing/providers/serpapi_shopping.py`, `ebay_browse.py` (OAuth client credentials, marketplace header, used filter), `frankfurter.py`.
- `pricing/filters.py` (physical-only, title match, IQR), `appraisal.py` (pre/post rules from locale config), `book_pricer.py`, `s07_price_books.py` (concurrency 6).
- `cli reprice --country GB --limit 10` → markdown table (title | IN new | IN used | GB new | GB used | sources).
- Tests with recorded provider JSON fixtures (`respx`): filtering, median, conversion, not-found path, appraisal paths, "no price without url" validator.

**Done when:** on 15 books, a hand check of the same source type is within 25% for ≥ 12. Every price has a clickable URL and a snapshot file. The GB reprice table is generated.

---

## Phase 8 — Non-book items + room geometry (≈2.5 h)
**Tier A**
- `prompts/items.md`, `vision/items.py`, item dedup by world centroid + category, dims from recon points, `pricing/item_pricer.py` (exact / range / appraisal), `s08_items.py`.
- `geometry/room.py`: point fusion, floor/ceiling RANSAC, wall lines, Manhattan snap, polygon, areas, shelved area, coverage, confidence. `s09_room.py`.
- Tests: a synthetic box room (4×3×2.7 m with noise) → areas within 2%; an L-shaped room polygon; missing ceiling → nulls + review.

**Tier B:** `room_debug.png` (top-down points + fitted polygon). Item dots on the plan.

**Done when:** on your sweep, floor area is within 15% and wall area within 20% before tuning. ≥ 6 of your 8+ items are found with the right category. Art goes to needs_appraisal unless a "print" statement exists.

---

## Phase 9 — Assembly, review queue, report, readback (≈2 h)
**Tier A**
- `packet/resolve_statements.py` (frame + target_hint → lines/regions; exclusions).
- `packet/review.py` (all reason codes from `04` S10), `packet/validate.py` (frame_ref exists, price evidence, totals recompute, schema), `s10_assemble.py`.
- `packet/report.py` + `templates/report.html.j2` per `07` §1 Screen 2 (crops with bbox, links, method badges, review queue, methods, telemetry).
- `get_packet_summary` real implementation, `packet_ready` event, agent readback (INTERRUPT scheduling).
- Tests: validation gate catches a missing frame, a price without url, and a totals mismatch.

**Done when:** a full live sweep ends with a spoken summary and an openable report in < 5 min (target < 2). `claim_packet.json` validates. Clicking any book shows its frame and price sources.

---

## Phase 10 — Evaluation, calibration, tuning, the measured fix (≈3 h)
**Tier A**
- `cli evaluate`: computes every pass bar from `11` (count, ID accuracy + confidently wrong, dims on 20, prices on 15, items recall + category, floor, wall, time to packet). Per-shelf breakdown. Writes `docs/results.md` + `docs/results.json`.
- `cli calibrate`: logistic calibration of `id_confidence`, chooses `tau_accept` for ≤ 2% confidently-wrong, writes to `config/settings.yaml` (with a comment on what it was fitted on), plus a reliability plot PNG.
- Telemetry summary in results (latency per stage, cost per sweep).
- **The measured fix:** pick the worst error from the first eval, fix it, re-run `replay` on the *same* sweep, and record before/after numbers in `docs/failure_log.md`.

**Tier B:** run on a second, unseen space and add an "unseen room" column to the results. Stretch: independent checker agent (`CHECKER_MODEL` re-reads 15% of spines blind → `checker_disagrees` review entries + agreement rate).

**Done when:** `docs/results.md` shows every pass bar with honest numbers, all shelves included, and the failure log has one before/after fix.

---

## Phase 11 — Deliverables & demo (≈3 h, human-heavy)
**Tier A**
- README (outline in `12` §1), architecture note (1 page, `docs/architecture.md`), failure log (1 page), results sheet (xlsx or CSV + md), second-country table, `.env.example` check, fresh-clone test (< 15 min).
- Final sweep for the demo (record 2–3 takes, keep the best *whole* take), commit the demo sweep folder (`claim_packet.json`, `report.html`, referenced frames).
- Private GitHub repo shared with the reviewers. Submission email (`12` §6).

**Done when:** every item in `12_DELIVERABLES_AND_REVIEW.md` §7's checklist is ticked.

---

## Dependency graph

```
P0 → P1 → P2 → P3
          ↘
P1 → P4 → P5 → P6 → P7 → P9 → P10 → P11
          P5 → P8 ↗
```
P2/P3 (voice) and P4/P5 (pipeline) can be developed in either order once P1 exists. If you're blocked on keys for voice, do P4/P5 first with `ingest-video`.

## Commit plan (you author every commit)
`chore: skeleton and packet contract` → `feat(capture): hi-res capture channel` → `feat(live): gemini live bridge with compression` → `feat(monitor): capture cues` → `feat(vision): detection + streaming` → `feat(geometry): recon, scale fusion, dedup, measurement` → `feat(identify): transcription + catalogue match` → `feat(pricing): sourced book prices + fx + appraisal` → `feat(items-room): items and room geometry` → `feat(packet): assembly, review queue, report` → `feat(eval): evaluation + calibration` → `fix: <the measured fix>` → `docs: README, architecture, failure log, results`.
