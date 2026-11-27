# ShelfClaim — implemented architecture

## 1. Purpose and core principle

ShelfClaim turns a phone video sweep of shelves into an evidence-linked book claim packet and HTML report; **models perceive, code decides**.

## 2. Components

| Component | File(s) | Responsibility | Runs where |
|---|---|---|---|
| Phone capture and UI | `web/index.html`, `web/js/camera.js`, `web/js/main.js`, `web/js/live.js`, `web/js/ui.js` | Requests camera/mic access, sends high-resolution video frames and speech text, displays QC and agent status, and speaks replies/cues. | Phone browser |
| Browser speech input/output | `web/js/speech.js` | Web Speech API recognition and browser `speechSynthesis`; interim stabilization, sentence playback, cue queue, and barge-in behavior. | Phone browser; optionally laptop viewer for mirrored speech |
| HTTP app and pages | `app/server/main.py`, `app/server/pages.py` | Creates sweeps; serves the app, viewer, report files, sweep list, and architecture page. | Laptop/local server |
| Capture WebSocket | `app/server/ws_capture.py`, `app/capture/storage.py`, `app/capture/quality.py` | Receives binary JPEG frames plus JSON headers/motion samples, scores and saves frames, records face boxes and markers, and acknowledges saved frames. | Laptop/local server; OpenCV runs locally |
| Capture cue monitor | `app/capture/monitor.py`, `app/server/live_output.py` | Evaluates rolling frame metrics, rate-limits cues, logs evidence, and sends cue text without an LLM call. | Laptop/local server |
| Live agent and tools | `app/server/ws_live.py`, `app/live/agent.py`, `app/live/intents.py`, `app/live/tools.py`, `app/live/client.py` | Receives final text and selected low-resolution frames, routes common intents, invokes deterministic tools, and calls Gemini for other turns. | Laptop/local server plus Google API |
| Live viewer and broadcast hub | `app/server/ws_viewer.py`, `app/server/viewer.py`, `web/viewer.html`, `web/js/viewer.js` | Shows saved/downscaled frames, QC, captions, inventory, pipeline progress, and report link. | Laptop browser and local server |
| OCR detection/transcription | `app/vision/local_ocr.py`, `app/vision/ocr_detection.py`, `app/vision/ocr_books.py`, `app/pipeline/stages/s01_detect.py`, `s05_transcribe.py` | Runs RapidOCR on CPU, clusters text into book-spine detections, reuses the OCR lines for transcription. | Laptop/local server |
| Pipeline and artifacts | `app/pipeline/orchestrator.py`, `app/pipeline/stages/` | Runs S01–S10 sequentially after capture ends and writes JSON artifacts, packet, report, and telemetry. | Laptop/local server; selected external APIs are called from here |
| Catalogue and pricing clients | `app/identify/catalogue.py`, `app/pricing/providers/serpapi.py`, `app/net/http.py` | Fetches/cache catalogue and offer evidence; converts used GBP prices to INR with Frankfurter when applicable. | Laptop/local server plus provider APIs |
| Packet, totals, validation, report | `app/packet/totals.py`, `app/packet/validate.py`, `app/packet/report.py`, `app/pipeline/stages/s10_assemble.py` | Constructs the typed packet, computes totals, checks evidence paths and price snapshots, and renders `report.html`. | Laptop/local server |

## 3. End-to-end flow

1. The user taps **Start** in the phone browser. The browser obtains the camera stream as video-only and requests microphone permission for speech recognition. It posts device metadata to `POST /api/sweeps`; the server creates `sweep.json`, initializes the live session, and returns the sweep ID and WebSocket paths.
2. The phone opens `/ws/capture` for that sweep. It sends binary packets containing a four-byte big-endian JSON-header length, the frame header (sequence, client time, dimensions, optional motion), and JPEG bytes. Motion-only JSON messages may also be sent. The server stores frames under `frames/`, appends metrics, markers, and `face_boxes` to `frames.jsonl`, then sends QC and acknowledgement messages.
3. The phone opens `/ws/live/{sweep_id}` (the live channel under `/ws/live`). It sends final `user_text` messages, speech-activity/events, and selected low-resolution JPEG frames; **no raw microphone audio is sent**. The server returns agent text, cue, state, accepted-transcript, and stop-capture messages. A scripted opening is sent when the connection starts.
4. The live channel publishes user/agent/cue captions to `/ws/viewer/{sweep_id}`. The capture channel publishes saved frames, QC, and markers to the same viewer hub. The viewer receives a current snapshot and subsequent frame, caption, inventory, and pipeline messages.
5. During capture, `CaptureMonitor` evaluates a rolling window and may send a cue directly to phone TTS. It does not ask the LLM to determine the QC cue. The laptop view at `GET /viewer` follows the latest sweep; `GET /viewer/{sweep_id}` selects a specific saved sweep.
6. When the user confirms completion and `end_sweep` returns `stopped: true`, the server stops capture and starts the same `run_pipeline` function used by CLI replay in an asynchronous task. Progress is sent to the phone and viewer. The pipeline runs S01–S10 in order.
7. S10 writes `claim_packet.json` and `report.html`, including the validation result. After the pipeline completes and `get_packet_summary` confirms that a packet exists, the server broadcasts `packet_ready` with `/sweeps/{sweep_id}/`; the server path does not separately gate that WebSocket message on `validation.passed`. The phone speaks a summary derived from `get_packet_summary`. A finalization exception is logged and produces a short failure message.
8. `GET /sweeps` lists sweep report links. `GET /sweeps/{sweep_id}/` serves `report.html`; `GET /sweeps/{sweep_id}/{asset_path}` serves an asset only when its resolved path remains inside that sweep directory. `GET /architecture` renders `docs/architecture.md` as HTML using CDN-hosted Markdown/Mermaid scripts.

## 4. Live agent and capture cues

### Speech and agent

- **Input:** `SpeechRecognition`/`webkitSpeechRecognition`, `lang="en-IN"`, `continuous=true`, `interimResults=true`. A final result is sent as `user_text`; if Chrome leaves interim text unchanged for the configured **1.2 s**, it is force-finalized. Finals are debounced for **800 ms**. Unsupported speech recognition has a typed-input fallback.
- **Deterministic routing:** `app/prompts/agent_intents.yaml` and `app/live/intents.py` recognize locale confirmation (`set_locale`), ownership/exclusion and edition statements (`print`, `original`, `first_edition`, `signed`, `rare`, `not_mine`, `exclude_region`), completion (`done`), count and missing-row questions (`count`, `missed`), title questions (`title`), and price questions (`price`). The latter two use scripted deflections. Tool-backed status/count/done replies are based on `get_sweep_status`; statements use `record_user_statement`. Unmatched turns go to the LLM.
- **LLM fallback:** `AGENT_MODEL` defaults to `gemini-3.1-flash-lite`; `config/settings.yaml` lists `gemini-3.1-flash-lite`, then `gemini-3.5-flash-lite`. The configured call timeout is **20 s**. Transient 500/503/504/internal/unavailable/deadline failures are retried with **0.5 s** and **1.5 s** backoffs, then the next model is tried; after the chain fails, a request with no image is tried once. The configured limiter allows **15 requests/minute** for each chain model (default **5/minute** for other models); 429 retries are configurable, with default max retries **3** and backoff from **0.5 s** up to **8 s**. On a slow turn, “One moment.” is sent after **2.5 s**. A final fallback is “Sorry, say that again?”. The installed client uses thinking level `minimal`; response diagnostics and attempts are logged.
- **Frame context:** a frame is attached only to a turn containing a configured visible-reference keyword (`this`, `that`, `here`, `painting`, `shelf`, `book`, `what is`) or every third turn. It is limited to **768 px** maximum side and JPEG quality **0.60**. The image is removed from stored conversation history after the turn.
- **Output and echo:** browser `speechSynthesis` selects an `en-IN`, then `en-GB`, then other English voice if available. Replies are split into sentences. A non-echo final transcript with at least two words waits for the current sentence to finish and then stops the rest of that reply; “stop”, “wait”, or “hold on” are explicit overrides after the current sentence. The tap-to-interrupt control cancels immediately. Cues queue behind speech, expire after **4 s**, are rechecked against their condition before playback, and duplicate cue types are not queued twice.
- **Echo cleanup:** output lines spoken in the last **6 s** are matched with RapidFuzz at **85**. Three-word spans matching recent output are stripped before sending; a whole transcript is dropped only if it is at least four words and matches. Short replies such as “yes” and “India” are retained. With `earphones_mode: true` (default), recognition remains active during TTS and server echo filtering is used. When false, the client pauses recognition during speech and requests resume **300 ms** after the queue empties.
- **History and grounding:** the agent keeps up to **8 user turns**, including paired function calls/results. It can retry a reply once if numeric claims are not present in the last ten tool results; if the retry still contains unsupported numbers it uses the fallback line. Agent replies are limited by post-processing to two sentences/30 words.

### QC and cues

Capture settings are in `config/settings.yaml`: blur score threshold **200**; low-light exposure threshold **85**; gyro speed threshold **35 dps** (with **1 s** sustained motion for `fast`); glare fraction **0.06**; dark mean **50**; bright mean **210**. Blur is Laplacian variance after resizing to 960 px wide; exposure is grayscale mean; glare is the fraction of central 80% pixels with HSV value above 250. `low_light_blur` takes precedence when blur is below 200, gyro below 35 dps, and exposure below 85.

The monitor uses a **2 s** rolling window and a configured threshold of **40%** of its frames for TOO_FAST, LOW_LIGHT, BLURRY, or GLARE. LOW_LIGHT and BLURRY must persist for **3 s**. At most one cue is emitted per **12 s**, and a cue type repeats no more than once per **30 s**. Cues are suppressed while the user is speaking, for **8 s** after user speech, and while an agent turn is pending. Current cue types and text are: “Move the phone more slowly” (TOO_FAST), “It's dark, can you turn on a light?” (LOW_LIGHT), “Hold the phone steadier for a moment” (BLURRY), and “Tilt the phone slightly to reduce glare” (GLARE). OCCLUDED, TOO_FAR, ROW_MISSED, ART_QUESTION, NEED_CEILING, NEED_CORNERS, and PROGRESS are **not implemented by the current capture monitor**.

## 5. Pipeline stages S0–S10

The replay orchestrator runs `s01` through `s10`; S0 is keyframe selection performed inside S1, and there is no separate S0 artifact. The configured pipeline forces `geometry_backend="off"` for replay/finalization.

| Stage | Input → method/tool/model | Output artifact | Failure/fallback behavior |
|---|---|---|---|
| S0 — coverage selection | `frames.jsonl` → divide sweep duration into at most **6** equal segments; choose the sharpest QC-`ok` frame per segment, otherwise the sharpest available frame. | Selection metadata and low-quality-segment review entries inside `s01_detections.json`. | Empty segment is recorded for review; a segment with no QC-ok frame uses its sharpest frame and records a review entry. |
| S1 — detect | Selected frames → RapidOCR on **90°**, **270°**, and **0°** rotations; keep confidence ≥ **0.5**. Cluster text-box centers into y row bands (gap factor **0.6**) and x clusters (epsilon factor **0.6 × median line height**); cap cluster width at **0.45 × row height** and apply configured spine-height/aspect filters. NMS removes within-frame duplicates. Optional Gemini assist adds unmatched spine boxes; current config is `assist: none`. | `s01_detections.json` (selected frames, per-frame detections/stats and review entries). | OCR errors can fail S1. If Gemini assist is enabled, assist failures are recorded and do not block OCR. The optional Gemini backend has configured model `gemini-3.5-flash-lite`; model fallbacks are disabled in current config. |
| S2 — geometry | Stage context → explicit geometry-off status; no reconstruction is run by the orchestrator. | `s02_geometry.json`. | Writes `skipped` and an explanatory error; no depth or room scale is fabricated. |
| S3 — books/rows | S1 detections and frame QC → OCR boxes tracked by row and horizontal overlap, within **18,000 ms** and minimum x-overlap **0.5**. Best readable/sharp view is retained; candidate frame counts are kept. | `s03_books_raw.json`. | Count spread above configured **10%** creates `count_disagreement_row`; missing S1 artifact fails the stage. |
| S4 — measure | S3 best-view book boxes and frame ArUco observations → homography on a marker in the same frame and inside the unit box; scale comes from runtime `MARKER_SIZE_MM` (default **100 mm** in `.env.example`). | `s04_measurements.json`. | Without usable same-frame marker evidence, dimensions and shelf run are null and `missing_scale_marker` is reviewed. Configured sanity ranges are height **8–45 cm** and thickness **0.3–12 cm**. |
| S5 — transcribe | S3 best views → with OCR-spine backend, reuse OCR lines persisted by S1; otherwise configured local OCR runs on crops. Lines are attached by center to a containing spine box, choosing nearest center-x if needed. | `s05_transcriptions.json`. | Empty/failed OCR remains empty text and zero legibility; Gemini fallback is disabled by current `gemini_fallback_if_empty: false`. |
| S6 — identify | S5 text → query every non-empty line and adjacent pair. Current catalogue order is Google Books then Open Library, but `open_library_enabled: false`, so current runs use Google Books only. Normalize punctuation/case/leading THE and compact joined words. | `s06_identification.json` including candidates, query log, scores and review queue. | Google Books uses a 5 s timeout, one retry, cached responses, and a per-run circuit breaker after connection failure. Match title similarity must be ≥ **90** and either another line matches an author at ≥ **85**, or title has ≥ **3 words**. YAML contains `tau_accept: 0.80`, `tau_review: 0.55`, and match weights, but the current S6 decision path does not read those fields; the title/author thresholds above are active. No candidate or low score leaves identity fields empty and creates review evidence; Open Library is not currently enabled. Google Books `saleInfo` is ignored. |
| S7 — book pricing | Identified books and locale → SerpApi Google Shopping for new offers; SerpApi eBay engine for used offers. Filters require title token-set similarity ≥ **80**, a URL, physical book (configured excluded terms include ebook, audiobook, summary, workbook, sets/posters), and matching new/used condition. With at least three offers, IQR outliers are removed; the median is used and the closest offer supplies the source URL. India used offers use eBay UK and Frankfurter GBP→INR conversion. | `s07_book_prices.json`; raw responses are saved under `evidence/prices/`. | Run limit defaults to **10 provider searches** (capped at 40 by the stage); missing offers become null with review. Provider errors produce `price_provider_unavailable`. Locale pre/post appraisal rules can skip pricing and retain a review entry. |
| S8 — non-book items | S1 detections with class `item` → category/frame-proximity dedup; dimensions are null. | `s08_items.json`. | Current OCR-first detector produces book-spine classes only unless Gemini assist/backend is enabled, so current OCR-default runs generally have no detected item rows. Detected rows are marked `needs_appraisal`; there is no item offer-pricing stage in the current S8 implementation. |
| S9 — room | Geometry choice → explicit null room document. | `s09_room.json`. | Room length, width, height, floor/wall/shelved area are null, confidence is 0, and the method records that 3D reconstruction is out of scope. |
| S10 — assemble | S3–S9, sweep metadata, frames, and user statements → Pydantic packet, code-computed totals, review queue, evidence validation, Jinja report. | `claim_packet.json`, `report.html`; pipeline writes `telemetry.json`. | Validation checks frame/crop references, price snapshots when amounts exist, and recomputed totals. The result is written with validation status; S10's `packet_ready` event is emitted only when validation passes. Missing required stage artifacts fail assembly. The live finalization path separately sends its WebSocket `packet_ready` after pipeline completion and summary lookup without checking the validation flag. |

Cross-frame OCR tracking is based on same-row box overlap and time; S6 can then mark repeated identified titles as duplicates when row/time/x-overlap evidence agrees. It is not 3D tracking. Review reasons are assembled from stage outputs and include identification, count disagreement, missing scale, price, item, and room issues as applicable.

## 6. Integrity guards

| Rule | Enforcement in current code |
|---|---|
| LLM numeric claims must be grounded in recent tool results; deterministic packet values are not authored by the LLM. | `app/live/numeric_grounding.py:find_ungrounded_claims`; `app/live/agent.py:AgentLoop._generate` checks the last ten tool results, retries once, then falls back. `app/packet/totals.py:compute_totals` computes claim totals. |
| Prices must come from parsed provider offers and have linked evidence. | `app/pricing/book_pricer.py:parse_serp_offers`, `estimate_book_price`; `app/pipeline/stages/s07_price_books.py` writes raw snapshots and offer URLs; `app/packet/validate.py:validate_packet` checks snapshots for non-null prices. |
| Google Books metadata is not price evidence. | `app/identify/catalogue.py:OpenLibraryGoogleBooks._google_books` maps catalogue metadata and omits `saleInfo`; pricing uses SerpApi responses. |
| Titles require OCR text and a catalogue match; no candidate means empty identity fields. | `app/pipeline/stages/s06_identify.py` query generation, normalization, scoring, and unmatched path. |
| Unknown dimensions and room area remain null without scale evidence/reconstruction. | `app/pipeline/stages/s04_measure.py:measure_books`; `app/pipeline/stages/s09_room.py:run`; `app/pipeline/stages/s10_assemble.py:run`. |
| Art/portrait rows and items without pricing evidence are not automatically priced by S8. | `app/pipeline/stages/s08_items.py:run` marks detected items `needs_appraisal`; locale rules in `app/pipeline/stages/s07_price_books.py` govern book appraisal. |
| Totals are deterministic and recomputed at validation. | `app/packet/totals.py:compute_totals`; `app/packet/validate.py:validate_packet`. |
| Saved frame references must exist under the sweep. | `app/packet/validate.py:validate_packet`; report asset paths are resolved and constrained by `app/server/pages.py:report_path`. |
| Room dimensions are not hardcoded from the test room; they remain null while reconstruction is disabled. | `app/pipeline/stages/s02_geometry.py:run`, `app/pipeline/stages/s09_room.py:run`, and `app/pipeline/stages/s10_assemble.py:run`. |
| Text in camera images is treated as OCR/catalogue data, not instructions. | OCR outputs feed spine matching only; tool schemas/handlers are explicit in `app/live/tools.py`. Prompt wording is in `app/prompts/`. |

## 7. External services and keys

| Service | Used for | Key needed | Free-tier limit/status |
|---|---|---|---|
| Google Gemini API | Live agent via `google-genai`; optional Gemini detection assist/backend or transcription fallback when enabled. | `GOOGLE_API_KEY` required to initialize the live agent; vision calls use the same key. | Numeric account quota is **not verified**; documented free-tier availability can change. Current OCR detection assist and Gemini transcription fallback are disabled. |
| Google Books API | Primary S6 catalogue metadata/ISBN lookup. | `GOOGLE_BOOKS_API_KEY` is optional in current client; requests can be keyless. | Repository docs describe a free quota; current quota and account status are **not verified**. |
| Open Library Search | Configured secondary catalogue. | No API key; contact/User-Agent is configurable. | Current `open_library_enabled` is false. Current service limits are **not verified**; any published request guidance is not enforced as an application quota here. |
| SerpApi Google Shopping | New-book offer search. | `SERPAPI_API_KEY` required when identified books are priced. | `docs/planning/03_TECH_STACK.md` records 250 searches/month for its free plan; current plan/account limit is **not verified**. |
| SerpApi eBay engine | Used-book offers; for India, the implementation queries the UK eBay domain. | Same `SERPAPI_API_KEY`. | Shares the SerpApi account quota; current remaining quota is **not verified**. |
| Frankfurter | Dated GBP→INR conversion for used offers where source currency differs. | No key. | No numeric free-tier limit is recorded in this repository; current service limit is **not verified**. |
| RapidOCR / ONNX Runtime | Local spine OCR for detection/transcription. | No key; runs on CPU. | No hosted free-tier quota applies. |
| eBay Browse API | Optional provider implementation. | `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` when selected. | Current default `USED_PROVIDER` is `serpapi_ebay`; Browse is not used by the current default path. Quota **not verified**. |

The server can be exposed to the phone with a tunnel such as Tailscale, but the app itself does not call a Tailscale API. Runtime environment values other than checked-in defaults are **not verified**.

## 8. Measured results in current packet and telemetry artifacts

Counts and totals below come from each sweep’s `claim_packet.json`; time and cost come from its `meta.telemetry` / `telemetry.json`. “Books” is the packet’s `totals.book_count`; “priced” is `totals.books_priced_used_count + totals.books_priced_replacement_count`. Values describe saved artifacts as inspected, not a guarantee that rerunning the pipeline will reproduce external provider responses.

| Sweep | Books detected | Identified | Priced | Used total (INR) | Review entries | Telemetry `time_to_packet_s` | Cost |
|---|---:|---:|---:|---:|---:|---:|---|
| `sw_20261127_062544_0f69` (newest) | 19 | 7 | 5 | 3,608.76 | 53 | 72.442118 | `total_cost_usd: null`; no cost entries |
| `sw_20261127_044901_65d3` | 11 | 1 | 1 | 493.04 | 33 | 48.199214 | `total_cost_usd: null`; no cost entries |
| `sw_20261126_225839_2007` | 13 | 7 | 5 | 4,950.39 | 36 | 80.104688 | `total_cost_usd: null`; no cost entries |

For `sw_20261127_062544_0f69` and `sw_20261126_225839_2007`, the recorded telemetry lists S06–S10 only, so their elapsed values are **partial-replay durations**, not verified end-to-end capture-to-report durations. `sw_20261127_044901_65d3` telemetry contains S01–S10. Costs are **not verified / unavailable in artifacts**. The historical Gemini-box baseline reported earlier was **4/11** and **1/11** identified; exact sweep IDs and corresponding packet/telemetry artifacts are **not verified** here.

## 9. Limitations and two-week follow-up

### Known limitations

- OCR clustering can split or merge spines; row positions and title matching remain uncertain, and unresolved identity is intentionally left blank.
- Current OCR-first detection does not produce shelf-board, item, ceiling, corner, or art detections. Those cue types and live item detection are not implemented in the active default path.
- Current Open Library fallback is disabled in YAML; catalogue availability depends on Google Books connectivity and quota.
- OCR detection/transcription is local and quota-independent, but live agent replies still depend on Gemini and browser speech recognition/TTS behavior.
- Dimensions require a visible usable ArUco marker in the same frame and plane as the book. Room area and full 3D reconstruction are not measured; replay forces geometry off.
- S8 does not implement item provider pricing. The completed packet may therefore contain no item rows or unresolved item appraisal rows.
- Finalization is sequential after `end_sweep`; it is not the aspirational during-sweep S1–S9 pipeline. Report latency depends on catalogue/pricing network calls and cached responses.
- Current telemetry artifacts have empty cost ledgers and, for two recent sweeps, only partial replay stage timing. A real per-sweep service cost is not verified.
- Current results vary across saved sweeps; they do not establish a 60-book evaluation or validated accuracy rates.

### With two more weeks

1. Build a labeled multi-sweep evaluation set and measure per-row count, OCR, title match, dimensions, and price accuracy before changing thresholds.
2. Improve spine segmentation/overlap handling and evaluate a dedicated spine detector against the same labeled frames.
3. Add item detection and evidence-backed item pricing, while retaining nulls and appraisal review where evidence is insufficient.
4. Add marker-guided 3D/room reconstruction only if the geometry backend can be evaluated against ruler/room ground truth.
5. Instrument actual provider cost and full end-to-end timing, and validate automatic finalization and report delivery on repeated phone runs.
