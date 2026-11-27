# 02 — Product Requirements Document (PRD)

Product name: **ShelfClaim** (working name, change freely)
Repo: `library-claim-agent`
Version: v1 (take-home submission)
Owner: Arun Kaarthikeyan

---

## 1. One-liner

A live voice-and-camera agent that guides a policyholder through one walk of their home library and returns an evidence-backed, locally priced contents claim packet covering every book, every other item, and the room's surface area.

## 2. Target users and the problem

| User | Problem today | What they get from v1 |
|---|---|---|
| **Policyholder** (primary, on a phone) | Listing hundreds of books and items by hand for a contents claim takes days and is usually incomplete or undervalued | One guided walk of under 3 minutes. The agent tells them what to fix while they're standing there. A packet in under 5 minutes |
| **Claims adjuster** (secondary, on a laptop) | Can't trust self-reported inventories or prices. Has to re-verify everything | Every line traceable to a frame and a dated price source. A review queue of exactly the lines that need human eyes. Totals that add up in code |
| **Cozmo reviewers** (the actual audience for this build) | Need to see real measurement, pricing integrity, honesty | Pass-bar results vs ground truth, an architecture note, a failure log, a reproducible repo |

## 3. Success metrics (mirror the brief's pass bars)

| Metric | Target |
|---|---|
| Book count error | ≤ 5% |
| Title ID on human-legible spines | ≥ 70% correct, ≤ 3% confidently wrong |
| Spine height and thickness error (20-sample) | ≤ 15% |
| Book price error vs hand check, same source type (15-sample) | ≤ 25% |
| Non-book items found with correct category | ≥ 80% |
| Floor area error | ≤ 10% |
| Wall area error | ≤ 15% |
| Time from "sweep done" to packet | < 5 min (internal target **< 2 min** so the demo video fits in 6 minutes) |
| Sweep duration | < 3 min for one room |
| Fabricated prices (no retrievable source) | **0** |
| LLM-written totals | **0** (enforced by design and a unit test) |

## 4. MVP feature list (strictly 5)

### F1. Live sweep agent (voice + camera, directs the capture)
- Real-time two-way voice in a mobile browser using Web Speech recognition and browser speech synthesis, with Gemini Flash function calling for conversation. This cascade avoids Gemini Live billing; recognized final text and selected low-resolution frames reach the server, never raw microphone audio.
- Greets the user, confirms country and currency, explains the sweep in 1–2 sentences, asks them to place the scale cards (if not placed).
- **Capture monitor** (deterministic): per-frame blur, glare, exposure and speed scores, plus a coverage map (shelf rows seen, room corners seen, ceiling seen). It pushes cues to the agent, which says them out loud during the pass ("Slow down a little", "Step closer to the top shelf on the left, I can't read those spines", "Tilt up to the ceiling line once").
- Asks questions it can't answer from video ("Is that portrait an original or a print?").
- Accepts barge-in and voice corrections: "that's a first edition", "skip that shelf, those aren't mine", "it's a print". Each correction becomes a logged user statement attached to the affected lines.
- The inventory updates on screen during the sweep (provisional counts and items as they're recognised).
- Survives sweeps longer than 2 minutes (context window compression and session resumption).

### F2. Books from the spine (detect → count → measure → read → identify)
- Detect every spine in keyframes, including books lying flat or stacked (rotated boxes).
- Deduplicate across frames to a single count per physical book, with `shelf` and `position`.
- Measure spine height and thickness in cm with a stated metric method per book. Report total shelf run in metres.
- Transcribe the visible spine text only. Resolve it to a work (and edition only when the evidence supports it) through catalogue lookup. Calibrated `id_confidence`.
- Unreadable or low-confidence → `unidentified`, with dimensions and no title. Never guessed.

### F3. Valuation at local prices (books and items)
- Per book: **replacement cost** (new) and **used value**, in the policyholder's country and currency, each with source, URL, retrieval date, condition assumed, raw response snapshot, and a `converted` flag plus FX source when cross-market.
- No price found → blank and excluded from totals, with a review entry.
- Rare, signed, antiquarian or above-threshold → `needs_appraisal`, never auto-priced.
- Non-book items: priced at local replacement cost with a source if the brand/model is known, or a sourced low–high range from comparable listings otherwise. Art and portraits default to `needs_appraisal` unless the user says it's a print.
- Locale is configuration: a CLI reprices the same 10 books for a second country (GB/GBP).

### F4. Room surface area from the same sweep
- Length, width, ceiling height; floor area and total wall area in m² and ft²; shelved wall area as a separate figure.
- A non-rectangular room becomes a polygon (stated in the packet). The method and confidence are recorded.
- No separate measuring pass. The agent asks for the corner and ceiling views *within* the single sweep.

### F5. Claim packet + review queue + report
- `claim_packet.json` matching the mandatory contract (extra fields allowed, none dropped).
- `report.html` built from the JSON: summary, rooms, books table, items table, totals, review queue, method notes, cost and latency. Each line links to its frame crop and price snapshot.
- Totals computed in code from the lines. A review queue lists every line below confidence thresholds, with reasons.
- Saved frames referenced by `frame_ref` (openable paths).
- Spoken summary read back by the agent when the packet is ready.

## 5. Supporting features (required by deliverables, not "product" features)

- **Offline replay** of a saved sweep through all stages (`app.cli replay`).
- **Evaluation script** that compares the packet with the ground-truth CSVs and writes `results.md` with every pass bar.
- **Telemetry ledger**: latency per stage, cost per sweep (tokens, API calls, GPU seconds).
- **Second-country reprice CLI.**

## 6. Non-goals (do NOT build these in v1)

- ❌ Authentication, user accounts, social login, multi-tenant anything.
- ❌ Deployment to a cloud host. Local server plus HTTPS tunnel is enough.
- ❌ A policy database, policy checks, coverage decisions, claim submission to an insurer.
- ❌ Visual polish, animations, theming, dark/light toggle, avatars, sketches.
- ❌ Native iOS/Android apps. LiDAR/ARKit/ARCore is a "two more weeks" item.
- ❌ Barcode scanning, ISBN typing, any "photograph items one by one" flow (banned by the brief).
- ❌ Training a model from scratch. No fine-tuning unless a measured failure justifies it (it won't in 48h).
- ❌ Multi-room merging, condition grading, smart-glasses support (stretch only, after the core passes).
- ❌ A database server. Files per sweep plus a SQLite cache is enough.
- ❌ Hand-maintained price lists, catalogues, or room dimensions of any kind.
- ❌ PDF generation pipelines. HTML report only (the browser can print to PDF).
- ❌ Internationalised UI. English UI. Currency and locale only affect pricing and units.

## 7. Functional requirements (detailed, testable)

| ID | Requirement | Acceptance test |
|---|---|---|
| FR-1 | Agent greets, confirms country and currency within the first 2 turns, explains the sweep in ≤ 2 sentences | Transcript shows `set_locale` called with country and currency before the sweep starts |
| FR-2 | Capture monitor scores each hi-res frame (blur, glare, exposure, motion) in < 60 ms | Unit test on fixture frames. Timing log |
| FR-3 | Cue to agent when ≥ 40% of the frames in a 2 s window are blurred or speed > threshold. Rate limit: ≤ 1 cue per 6 s, same cue type ≤ once per 15 s | Replay of a deliberately fast sweep produces "slow down" cues in `events.jsonl` |
| FR-4 | Coverage cue when a detected shelf unit has a row never captured sharply, or when no ceiling or corner was seen before the user says done | Replay test |
| FR-5 | Inventory panel updates within 5 s of a new book or item being first detected | Event timestamps |
| FR-6 | Voice corrections map to `user_statements` and are applied to the right lines or regions | Unit test of resolver. Packet shows the statement in `evidence.user_statements` |
| FR-7 | Each unique book appears once, with `shelf`, `position`, `frame_ref` (best view), and bbox | Dedup unit test with synthetic 3D points. Eval count error |
| FR-8 | Every spine dimension carries `dim_method` ∈ {`marker_plane`, `recon_depth`, `none`} | Schema validation |
| FR-9 | Title only set if catalogue match score ≥ τ (calibrated). Otherwise status `unidentified`, title empty, raw spine text kept in `spine_text_raw` | Unit test. Eval confidently-wrong ≤ 3% |
| FR-10 | Prices only from provider responses. Each has `source`, `url`, `retrieved_at`, snapshot path | Test: price objects without url/snapshot fail validation |
| FR-11 | `converted: true` plus `fx` block whenever the currency of the source ≠ the locale currency | Unit test |
| FR-12 | Appraisal rules route to `needs_appraisal` with no price | Unit test per rule |
| FR-13 | Room geometry from reconstruction anchored by marker scale; `scale_method` string lists the anchors and their disagreement % | Replay on the recorded sweep |
| FR-14 | Totals computed by `packet/totals.py` only. A test recomputes them from the lines and asserts equality | Unit test |
| FR-15 | Review queue contains every line with confidence < threshold, status `unidentified`/`needs_appraisal`/`range`, a missing price, a converted price, or a dimension outlier | Unit test |
| FR-16 | Every `frame_ref` resolves to an existing file under the sweep folder | Validation step fails the packet build otherwise |
| FR-17 | Packet produced < 5 min after `end_sweep` (target < 2 min) | Telemetry |
| FR-18 | Reprice CLI produces a side-by-side table for 10 books in a second country | CLI output file |
| FR-19 | `.env.example` present, no secrets in git. README gets a stranger running in < 15 min | Fresh-clone test |

## 8. Non-functional requirements

- **Honesty over coverage:** blank > guessed. Encoded in code paths, not just prompts.
- **Traceability:** every number links to evidence (frame + bbox, or URL + date + snapshot, or user statement + transcript timestamp).
- **Testability:** each stage is a pure-ish function `run(input_json_paths) -> output_json_path`, runnable alone.
- **Reproducibility:** replaying a saved sweep gives the same packet, except for live price refreshes (the cache makes it deterministic).
- **Cost:** target < US$1.00 per sweep excluding GPU, < US$1.50 including GPU. Report the real number.
- **Latency:** live cue reaction < 3 s from a bad frame to speech start. Packet < 2 min after sweep.
- **Privacy:** no people in frames by instruction. Faces blurred in saved frames. No PII in the packet.

## 9. Open questions (answered by assumption; see `01` §9)

Country and currency defaults, the meaning of `excluded_from_totals`, gross vs net wall area, used condition, appraisal threshold, whether scale cards count as an allowed reference object. All decided and documented. Revisit only if a reviewer asks.

## Product research addendum (2026-11-25)

The original assignment requirements and pass bars above remain binding. The owner also wants a stronger, more considered UI/UX, provided it does not displace measurement accuracy, pricing integrity, or failure reporting. The researched additions are:

- Add a preflight state for secure context, camera/microphone permissions, locale, scale cards, and privacy guidance.
- Show live counts as provisional until deduplication finishes. Keep detection, title identity, dimensions, and valuation as separate statuses.
- Show capture coverage and one plain-language next action. Mark missing views instead of filling them with assumed measurements.
- Route each uncertain line to a review entry that opens its crop, full frame, raw transcription, catalogue evidence, and price evidence.
- Keep room geometry tied to observed coverage, scale anchors, and disagreement. Unknown or weakly supported dimensions remain null and enter review.
- Make the phone flow touch-friendly and the report responsive, keyboard-accessible, high-contrast, and printable.
- Preserve the baseline of ordinary mobile-browser capture. LiDAR or other depth-specific capture remains optional.
- Record the exact reconstruction checkpoint and its license separately from the model repository license.

The UI source of truth is `07_UI_UX.md`; non-binding research notes are in `notes/PRODUCT_DIRECTION.md`. Phase checkpoints are in `PHASE_ROADMAP.md`, and prior-art links are in `OPEN_SOURCE_REVIEW.md`.

### Competitive context and positioning

The landscape review found strong open-source components for book-spine
detection, OCR, live voice/video, and room reconstruction, but no reviewed
open-source project that combines the assignment's complete workflow:
voice-directed capture, book-level deduplication and metric measurement,
catalogue-gated identity, sourced valuation, room surfaces, and a validated
claim packet. This is a bounded finding from the repositories reviewed, not a
claim about every product in the market.

Scanlily is a close commercial comparison: it publicly describes narrated
video inventory, item extraction, live listing-based replacement values, and
claims reports. ShelfClaim's assignment-specific focus is auditable book-spine
counting and dimensions, explicit scale and price provenance, catalogue-gated
identification, and deterministic packet validation. Avoid marketing claims
that no video-inventory or live-pricing product exists.

Prior-art sources and license cautions are recorded in
[`OPEN_SOURCE_REVIEW.md`](OPEN_SOURCE_REVIEW.md). Optional Codex-authored UI
research is in [`notes/PRODUCT_DIRECTION.md`](notes/PRODUCT_DIRECTION.md);
`07_UI_UX.md` remains the implementation spec.
