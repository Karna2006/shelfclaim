# ShelfClaim plan check

Source of truth: `docs/09_PLAN.md`, `BUILD_PROMPTS.md`, and the repo map in
`AGENTS.md`. This plan maps the supplied prompts to the intended paths and
public APIs. No application code is included here. Phase 4 incorporates the
owner's within-frame duplicate-box rule recorded in `docs/04_ARCHITECTURE.md`
and `docs/05_DATA_SCHEMA.md`.

## Cross-phase notes

- Follow the exact prompt order. A phase starts with its PLAN, waits for review
  and GO, then implements and runs its stated checks. Do not commit; `AGENTS.md`
  reserves commits for the owner.
- Keep the website vanilla HTML/ES modules/CSS. `docs/07_UI_UX.md` is the UI
  specification. The extra `docs/notes/PRODUCT_DIRECTION.md` is Codex-authored
  landscape research, not a kit or owner-authored addendum, and must not
  override `docs/07_UI_UX.md`, integrity rules, or pass bars.
- Existing files to preserve in Phase 0: `config/locales/IN.yaml`,
  `config/locales/GB.yaml`, `config/pricing_rates.yaml`, and the five
  `app/prompts/*.md` files. Add missing config keys only; do not invent rates.
- All `app/`, `web/`, and `tests/` source paths below are created in the phase
  first listing them unless the row explicitly says “extend” or “preserve”.
  `app/cli.py`, `app/settings.py`, `app/server/main.py`,
  `app/pipeline/artifacts.py`, and `app/packet/models.py` are then extended by
  later phases as documented. The prompt files and supplied locale/rate files
  are preserved.
- Phase 6 needs the shared HTTP client/cache for catalogue lookups, while the
  supplied Phase 7 prompt also says to create them. Recommended resolution:
  create `app/net/http.py` and `app/net/cache.py` in Phase 6 as the shared
  foundation, then extend them for price snapshots and provider caching in
  Phase 7. This preserves the architecture rule that all HTTP uses the shared
  client.
- Phase 4 NMS thresholds are configuration, not code constants:
  `dedup.within_frame_iou`, `dedup.within_frame_containment`,
  `dedup.within_frame_center_factor`, and
  `dedup.within_frame_review_iou_min`. These are added to the existing Phase 0
  `config/settings.yaml` contract from `docs/05_DATA_SCHEMA.md`.
- The Gemini API key is reported by the owner as configured in `.env`. Never
  read, print, log, or commit `.env`. The Live-model access check remains a
  manual prerequisite to the real-device check in Phase 2; fake-session tests
  do not require credentials.

## Phase 0 — Skeleton, contract, totals

| File | Planned public API |
|---|---|
| `pyproject.toml` | Project metadata, Python 3.12 dependency set from `docs/03_TECH_STACK.md`, dev/GPU extras, pytest and Ruff config. |
| `Makefile` | `dev`, `test`, `lint`, `fmt`, `check`, `replay`, `eval`, `reprice`, `markers`, `modal-deploy` targets from `AGENTS.md`. |
| `.gitignore` | Ignore `.env`, sweeps except the future demo, cache, `*.npz`, generated `markers.pdf`, and standard Python artifacts. |
| `.env.example` | Documented variables from `docs/03_TECH_STACK.md` §7; no secrets; includes `USED_PROVIDER=serpapi_ebay`. |
| `config/settings.yaml` | Capture, cue, keyframe, dedup, identify, measure, room and model thresholds; no room facts. |
| `config/taxonomy.yaml` | Fixed item categories and range-query templates from `docs/04_ARCHITECTURE.md` S8. |
| `app/settings.py` | `class Settings(BaseSettings)`, `load_settings(path: Path | None = None) -> Settings`; load environment and YAML without reading `.env` into logs. |
| `app/packet/models.py` | Pydantic v2 contract: `Sweep`, `Room`, `ScaleAnchor`, `FxInfo`, `ReplacementCost`, `UsedValue`, `BBox`, `Book`, `ItemReplacementCost`, `Dimensions`, `Item`, `Totals`, `ReviewEntry`, `UserStatement`, `Meta`, `ClaimPacket`; validators enforce `docs/05_DATA_SCHEMA.md` §1.1. |
| `app/packet/totals.py` | `compute_totals(books: Sequence[Book], items: Sequence[Item], currency: str) -> Totals`. |
| `app/pipeline/context.py` | `@dataclass class StageContext`: `sweep_dir: Path`, `settings: Settings`, `ledger: Ledger`, plus injected client interfaces. |
| `app/pipeline/artifacts.py` | Pydantic artifact models for `KeyframeSets`, `DetectionsDoc`, `GeometryDoc`, `BookClustersDoc`, `MeasurementsDoc`, `TranscriptionsDoc`, `IdentificationDoc`, `BookPricesDoc`, `ItemsDoc`, `RoomDoc`, and `TelemetryDoc`. |
| `app/telemetry/ledger.py` | `class Ledger`; `stage(name: str) -> ContextManager[None]`, `cost(provider: str, units: float, unit_price_key: str) -> None`, `to_dict() -> dict[str, object]`. |
| `app/telemetry/events.py` | `write_event(sweep_dir: Path, event: Event) -> None`; `iter_events(path: Path) -> Iterator[Event]`. |
| `app/cli.py` | Typer commands `serve()`, `replay(sweep: Path, ...)`, `stage(name: str, sweep: Path)`, `reprice(...)`, `evaluate(...)`, `calibrate(...)`, `ingest_video(path: Path, ...)`, `make_markers(ids: list[int], size_mm: float, out: Path)`. Only `serve` and `make_markers` are implemented in Phase 0. |
| `app/server/main.py` | `create_app(settings: Settings | None = None) -> FastAPI`; `GET /healthz`, static web mount and app entry point. |
| `app/prompts/loader.py` | `load_prompt(name: str) -> str`; read the existing prompt files without changing their content. |
| `tests/unit/test_models.py` | Validator tests: amount without URL/snapshot, converted without FX, unidentified with title, appraisal with amount. |
| `tests/unit/test_totals.py` | Totals cases: null price, appraisal, excluded, converted values, item low/high. |

**External accounts/keys:** none. The existing locale/rate and prompt files are
preserved. `make check` and marker-print verification are Phase 0 exit checks.

## Phase 1 — Capture channel

| File | Planned public API |
|---|---|
| `web/index.html` | Capture screen DOM and accessible controls from `docs/07_UI_UX.md` Screen 1. |
| `web/styles.css` | Responsive capture-screen styles, high-contrast status states, safe areas and touch targets. |
| `web/js/main.js` | `async function startApp(): Promise<void>`; compose capture modules and render application state. |
| `web/js/camera.js` | `async function openCamera(video: HTMLVideoElement): Promise<MediaStream>`; `captureFrame(video: HTMLVideoElement, options: CaptureOptions): Promise<Blob>`. |
| `web/js/motion.js` | `requestMotionPermission(): Promise<boolean>`; `startMotion(onSample: (sample: MotionSample) => void): () => void`. |
| `web/js/ws.js` | `class CaptureSocket`; `connect(sweepId: string): Promise<void>`, `sendFrame(frame: Blob, header: FrameHeader): void`, `close(): void`; max 3 unacked and bounded reconnect buffer. |
| `web/js/ui.js` | `renderQc(state: QcState): void`; `renderCoverage(state: CoverageState): void`; `renderInventory(state: ProvisionalInventory): void`. |
| `app/server/ws_capture.py` | `parse_frame_message(data: bytes) -> tuple[FrameHeader, bytes]`; `capture_websocket(websocket: WebSocket, sweep_id: str) -> None`. |
| `app/capture/storage.py` | `class CaptureStorage`; `async save_frame(header: FrameHeader, jpeg: bytes) -> FrameRecord`. |
| `app/capture/faces.py` | `blur_faces(image: NDArray[np.uint8]) -> tuple[NDArray[np.uint8], int]`. |
| `app/capture/quality.py` | `score_frame(image: NDArray[np.uint8], config: CaptureSettings) -> QualityMetrics`. |
| `app/capture/markers.py` | `detect_markers(image: NDArray[np.uint8], dictionary: str) -> list[MarkerDetection]`. |
| `app/server/main.py` | Add `POST /api/sweeps` creating `sweep.json` with client device metadata. |
| `tests/unit/test_capture_quality.py` | Sharp/checkerboard vs blur, glare patch and exposure metric cases. |
| `tests/unit/test_capture_markers.py` | Generated ArUco marker detection and corners. |
| `tests/unit/test_ws_capture.py` | Binary header parsing, invalid/truncated message handling. |
| `tests/unit/test_capture_storage.py` | JPEG path and JSONL record creation. |

**External accounts/keys:** none. A phone HTTPS tunnel is needed for the manual
camera test; no API key is required.

## Phase 2 — Live agent bridge

| File | Planned public API |
|---|---|
| `app/live/bridge.py` | `class LiveBridge`; `connect() -> None`, `send_audio(pcm: bytes) -> None`, `send_frame(jpeg: bytes, t_ms: int) -> None`, `send_text(text: str) -> None`, `inject_cue(text: str) -> None`, `run() -> None`, `close() -> None`; injected Live session factory. |
| `app/live/tools.py` | `build_tool_declarations() -> list[FunctionDeclaration]`; async handlers `set_locale(...)`, `start_sweep(...)`, `end_sweep(...)`, `get_sweep_status(...)`, `record_user_statement(...)`, `mark_landmark(...)`, `get_packet_summary(...)`. |
| `app/server/ws_live.py` | `parse_live_message(data: str | bytes) -> LiveInput`; `live_websocket(websocket: WebSocket, sweep_id: str) -> None`. |
| `web/js/audio.js` | `class AudioController`; `start(): Promise<void>`, `sendMicChunk(pcm16: Int16Array): void`, `playAgentChunk(pcm16: Int16Array): void`, `flushPlayback(): void`, `stop(): Promise<void>`. |
| `web/audio-worklet.js` | `class PcmProcessor extends AudioWorkletProcessor`; resample mic input to 16 kHz PCM16 and emit playback-ready audio messages. |
| `app/prompts/agent_system.md` | Preserve the kit prompt content as-is; load and apply it, do not rewrite. |
| `tests/unit/test_live_tools.py` | Locale allowlist and user statement log/frame-sequence association. |
| `tests/unit/test_live_bridge.py` | `FakeLiveSession`; GoAway/drop/resumption, interruption and capture independence. |
| `tests/unit/test_ws_live.py` | Audio binary and JSON-frame protocol parsing. |

**External accounts/keys:** `GOOGLE_API_KEY` and a Live model available to
`LIVE_MODEL` for end-to-end testing. Offline bridge tests use `FakeLiveSession`
and need no key. Tailscale or a Cloudflare tunnel is needed for the phone test.

## Phase 3 — Capture monitor and spoken direction

| File | Planned public API |
|---|---|
| `app/capture/monitor.py` | `class CaptureMonitor`; `add_frame(record: FrameRecord) -> list[Cue]`, `add_motion(sample: MotionSample) -> list[Cue]`, `set_user_speaking(value: bool) -> None`. |
| `app/live/cues.py` | `format_cue(cue: Cue) -> str`; `send_cue(bridge: LiveBridge, cue: Cue, events_path: Path) -> None`. |
| `app/capture/coverage.py` | `class CoverageTracker`; `add_frame(record: FrameRecord) -> CoverageState`, `mark_landmark(kind: LandmarkKind) -> None`, `gaps() -> list[CoverageGap]`. |
| `app/live/tools.py` | Replace `get_sweep_status` stub with computed coverage, gaps and provisional placeholders. |
| `tests/unit/test_capture_monitor.py` | Synthetic metrics, cue priority, global and same-type rate limits, speaking suppression. |
| `tests/unit/test_capture_coverage.py` | Missing ceiling/corners/cards and covered-row states. |

**External accounts/keys:** none beyond Phase 2's Live credentials for spoken
cue integration; monitor logic tests are local.

## Phase 4 — Detection and streaming orchestrator

| File | Planned public API |
|---|---|
| `app/vision/client.py` | `class VisionClient(Protocol)` with `async generate_json(prompt: str, images: Sequence[bytes], schema: type[BaseModel]) -> VisionResult`; `GeminiVisionClient`; `FakeVisionClient`. |
| `app/vision/detect.py` | `parse_detections(result: VisionResult, image_size: tuple[int, int]) -> list[Detection]`; pixel conversion, clipping, rotated boxes and min side validation. |
| `app/capture/keyframes.py` | `select_detection_frame(record: FrameRecord, previous: Sequence[FrameRecord], settings: Settings) -> bool`; `select_reconstruction_frames(records: Sequence[FrameRecord], minimum: int, maximum: int) -> list[int]`. |
| `app/pipeline/stages/s00_keyframes.py` | `async run(ctx: StageContext) -> Path`; persist detection/reconstruction frame sets. |
| `app/pipeline/stages/s01_detect.py` | `async run(ctx: StageContext) -> Path`; append-safe S1 output and within-frame NMS. |
| `app/pipeline/orchestrator.py` | `class PipelineOrchestrator`; `start_sweep() -> None`, `enqueue_frame(record: FrameRecord) -> None`, `finalize() -> None`, `status() -> PipelineStatus`. |
| `app/cli.py` | Implement `ingest_video(path: Path, ...)` and `replay(..., until: str = "s01")`. |
| `docs/04_ARCHITECTURE.md` | S1 within-frame NMS; S3 cannot-link applies only after NMS. |
| `docs/05_DATA_SCHEMA.md` | S1 fields `merged_from` and `possible_duplicate_box`, plus NMS config keys. |
| `tests/unit/test_detect.py` | Normalized box conversion, clipping, small and rotated box validation. |
| `tests/unit/test_keyframes.py` | Novelty selection and marker-frame inclusion. |
| `tests/unit/test_detection_nms.py` | IoU and containment merges, winner/merged IDs, borderline flags, same-class constraint, retained distinct neighbors. |
| `tests/unit/test_orchestrator.py` | Fake stages verify DAG ordering and failure isolation. |

**External accounts/keys:** `GOOGLE_API_KEY` for actual Gemini vision calls;
unit tests use `FakeVisionClient`. FFmpeg/OpenCV video ingestion is local.

## Phase 5 — Geometry, scale, deduplication, measurement

| File | Planned public API |
|---|---|
| `gpu/modal_recon.py` | Modal `warmup() -> str`; `reconstruct(jpeg_bytes_list: list[bytes], model: str) -> bytes` (NPZ bytes with documented OpenCV camera convention and resize factors). |
| `app/geometry/recon_client.py` | `class ReconClient(Protocol)` with `async reconstruct(frames: Sequence[bytes]) -> Reconstruction`; Modal/local/off adapters. |
| `app/geometry/scale.py` | `estimate_scale(reconstruction: Reconstruction, markers: Sequence[MarkerObservation], statements: Sequence[UserStatement], settings: Settings) -> ScaleEstimate`; weighted median and disagreement. |
| `app/geometry/lift.py` | `lift_detection(detection: Detection, frame: ReconFrame, scale: ScaleEstimate) -> LiftedDetection | None`. |
| `app/geometry/dedup.py` | `deduplicate_books(detections: Sequence[LiftedDetection], settings: Settings) -> BookClustersDoc`; same-frame post-NMS cannot-link. |
| `app/geometry/homography.py` | `measure_on_marker_plane(box: BBox, marker: MarkerObservation, marker_size_mm: float) -> DimensionsCm | None`. |
| `app/geometry/measure.py` | `measure_spine(book: BookCluster, geometry: GeometryDoc, settings: Settings) -> SpineMeasurement`. |
| `app/pipeline/stages/s02_geometry.py` | `async run(ctx: StageContext) -> Path`. |
| `app/pipeline/stages/s03_dedup.py` | `async run(ctx: StageContext) -> Path`. |
| `app/pipeline/stages/s04_measure.py` | `async run(ctx: StageContext) -> Path`. |
| `tests/unit/test_scale.py` | Pinhole/marker scale recovery, weighted anchor fusion, absent-marker fallback and disagreement. |
| `tests/unit/test_geometry_lift.py` | Back-projection and resize-factor mapping. |
| `tests/unit/test_geometry_dedup.py` | Jittered multi-view books count correctly, including same-frame cannot-link. |
| `tests/unit/test_measure.py` | Synthetic marker-plane 20×2 cm spine within 2%, sanity flags, fallback method. |

**External accounts/keys:** Modal account/token and available GPU are needed for
the hosted reconstruction run; local CUDA is an alternative. `off` backend and
synthetic geometry tests need no GPU credentials. The chosen checkpoint must
be reviewed separately from its source repository license.

## Phase 6 — Transcription and identification

| File | Planned public API |
|---|---|
| `app/vision/transcribe.py` | `make_spine_crop(frame: NDArray, bbox: BBox) -> list[NDArray]`; `async transcribe_crops(crops: Sequence[SpineCrop], client: VisionClient) -> list[Transcription]`; `consensus(views: Sequence[Transcription]) -> Transcription`. |
| `app/pipeline/stages/s05_transcribe.py` | `async run(ctx: StageContext) -> Path`; streaming/final transcription output. |
| `app/net/http.py` | `class HttpClient`; `async get_json(url: str, params: Mapping[str, str], provider: str) -> HttpResponse`; retries, rate limits, User-Agent and cache integration. |
| `app/net/cache.py` | `class SQLiteCache`; `get(key: CacheKey) -> CachedResponse | None`, `put(key: CacheKey, response: CachedResponse) -> None`. |
| `app/identify/openlibrary.py` | `class OpenLibraryClient`; `async search(title: str, author: str | None) -> list[CatalogueCandidate]`, `async editions(work_key: str) -> list[EditionCandidate]`. |
| `app/identify/googlebooks.py` | `class GoogleBooksClient`; `async search(title: str, author: str | None) -> list[CatalogueCandidate]`. Metadata/ISBN only. |
| `app/identify/match.py` | `normalize_text(text: str) -> str`; `score_candidate(transcription: Transcription, candidate: CatalogueCandidate, weights: MatchWeights) -> MatchScore`; `decide_match(scores: Sequence[MatchScore], thresholds: IdentifyThresholds) -> MatchDecision`. |
| `app/identify/edition.py` | `resolve_edition(candidates: Sequence[EditionCandidate], publisher_text: str, measured_height_cm: float | None) -> EditionCandidate | None`. |
| `app/pipeline/stages/s06_identify.py` | `async run(ctx: StageContext) -> Path`. |
| `tests/unit/test_transcribe.py` | Rotation, crop padding/upscale, guard rejection, multiview consensus. |
| `tests/unit/test_identify_match.py` | Normalization, initials, partial titles, tie, confidence decision, unidentified fields empty, optional rerank ID outside candidate set rejected. |
| `tests/unit/test_identify_edition.py` | Edition acceptance/rejection and publisher/height rule. |

**External accounts/keys:** `GOOGLE_API_KEY` for Gemini Flash transcription;
Open Library requires no key and a configured `OPENLIBRARY_CONTACT`; Google
Books key is optional. Catalogue tests are mocked. Shared HTTP/cache foundation
is created here and extended in Phase 7.

## Phase 7 — Book pricing

| File | Planned public API |
|---|---|
| `app/net/http.py` | Extend shared client with provider-aware snapshot writing and retry/cache metadata. |
| `app/net/cache.py` | Extend SQLite cache with TTL and raw JSON/fetched-at persistence. |
| `app/pricing/providers/serpapi_shopping.py` | `class SerpApiShoppingProvider`; `async search(query: str, locale: LocaleConfig) -> list[Offer]`. |
| `app/pricing/providers/serpapi_ebay.py` | `class SerpApiEbayProvider`; `async search(query: str, locale: LocaleConfig) -> list[Offer]`; use SerpApi `engine=ebay`, locale `ebay_domain`, and verified used-condition filter IDs; parse listing title, condition, extracted price, currency and URL. |
| `app/pricing/providers/ebay_browse.py` | `class EbayBrowseProvider`; `async get_token() -> OAuthToken`; `async search(query: str, locale: LocaleConfig) -> list[Offer]`; official Browse backend for when production credentials are approved. |
| `app/pricing/providers/frankfurter.py` | `class FrankfurterFxProvider`; `async rate(source: str, target: str, date: date | None) -> FxRate`. |
| `app/pricing/filters.py` | `filter_offers(offers: Sequence[Offer], work_title: str) -> list[Offer]`; `drop_iqr_outliers(offers: Sequence[Offer]) -> list[Offer]`; `median_offer(offers: Sequence[Offer]) -> Offer | None`. |
| `app/pricing/appraisal.py` | `pre_appraisal(book: Book, locale: LocaleConfig, statements: Sequence[UserStatement]) -> list[str]`; `post_appraisal(used: Decimal | None, replacement: Decimal | None, locale: LocaleConfig) -> list[str]`. |
| `app/pricing/book_pricer.py` | `class UsedMarketProvider(Protocol)` with `async search(query: str, locale: LocaleConfig) -> list[Offer]`; `build_used_market_provider(name: str, settings: Settings) -> UsedMarketProvider`; `async price_book(book: Book, locale: LocaleConfig, providers: PricingProviders, evidence_dir: Path) -> BookPriceResult`. |
| `app/pipeline/stages/s07_price_books.py` | `async run(ctx: StageContext) -> Path`; concurrency 6 and ledger tracking. |
| `.env.example`, `docs/03_TECH_STACK.md` §7 | Confirm `USED_PROVIDER=serpapi_ebay` is documented as the temporary default and `ebay_browse` as the alternate. Never place credentials in `.env.example`. |
| `config/locales/IN.yaml`, `config/locales/GB.yaml` | Preserve current values; add verified `ebay_domain` and condition-filter configuration only if missing. India fallback uses `ebay.co.uk`, with dated Frankfurter conversion to INR. |
| `app/cli.py` | Implement `reprice(sweep: Path, country: str, limit: int = 10, out: Path = ...) -> None`; support limiting books for development runs. |
| `tests/fixtures/pricing/serpapi_shopping.json` | One real or redacted provider response shape; never include keys. |
| `tests/fixtures/pricing/serpapi_ebay.json` | One real or redacted eBay-engine response shape; never include keys. |
| `tests/fixtures/pricing/ebay_browse.json` | One real or redacted Browse `itemSummaries` response shape; never include keys. |
| `tests/fixtures/pricing/frankfurter.json` | Dated FX response. |
| `tests/unit/test_pricing_filters.py` | Median/IQR, title threshold, physical format exclusions and positive price. |
| `tests/unit/test_pricing_book_pricer.py` | Provider-only price, conversion+FX, appraisal pre/post, not-found null/review. |
| `tests/unit/test_pricing_providers.py` | Mocked SerpApi response parsing, Browse OAuth/response parsing, condition filtering, URL/evidence validation and provider selection. |

**External accounts/keys:** `SERPAPI_API_KEY` is sufficient for new Shopping
and the temporary `serpapi_ebay` used backend, so eBay approval does not block
Phase 7. Official Browse additionally needs production
`EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`; Frankfurter has no key. Keep both
backends behind `UsedMarketProvider`. Verify SerpApi's current response fields
and eBay used-condition IDs before parsing. Cache every SerpApi response because
both engines share the same quota. The prompt asks for example response
fixtures; use live results with secrets removed or user-run fetch commands,
never commit credentials.

## Phase 8 — Other items and room geometry

| File | Planned public API |
|---|---|
| `app/vision/items.py` | `async describe_items(crops: Sequence[ItemCrop], client: VisionClient, taxonomy: Taxonomy) -> list[ItemDescription]`. |
| `app/pricing/item_pricer.py` | `async price_item(item: DetectedItem, locale: LocaleConfig, provider: ShoppingProvider, evidence_dir: Path) -> ItemPriceResult`. |
| `app/pipeline/stages/s08_items.py` | `async run(ctx: StageContext) -> Path`. |
| `app/geometry/room.py` | `estimate_room(points: NDArray, shelving: Sequence[ShelvingUnit], settings: Settings) -> RoomEstimate`; floor/ceiling planes, wall polygon, area, coverage and confidence. |
| `app/pipeline/stages/s09_room.py` | `async run(ctx: StageContext) -> Path`; null fields/review reason on geometry failure. |
| `tests/unit/test_item_dedup.py` | Same-category centroid dedup and category boundaries. |
| `tests/unit/test_item_dimensions.py` | PCA 5–95 percentile dimensions on synthetic points. |
| `tests/unit/test_item_pricing.py` | Art appraisal/print statement, exact brand/model, range offer counts and not-found. |
| `tests/unit/test_room_geometry.py` | Noisy 4×3×2.7 m box and shelf push-out, L-shaped area, missing-ceiling null height. |

**External accounts/keys:** `GOOGLE_API_KEY` for vision, pricing-provider
credentials from Phase 7, and Modal/local reconstruction from Phase 5 for a
real sweep. Synthetic tests run locally.

## Phase 9 — Packet, review queue, report, readback

| File | Planned public API |
|---|---|
| `app/packet/resolve_statements.py` | `resolve_statements(statements: Sequence[UserStatement], detections: DetectionsDoc, books: BookClustersDoc) -> list[UserStatement]`. |
| `app/packet/review.py` | `build_review_queue(packet_parts: PacketParts) -> list[ReviewEntry]`. |
| `app/packet/validate.py` | `validate_packet(packet: ClaimPacket, sweep_dir: Path) -> ValidationResult`; `recompute_totals(packet: ClaimPacket) -> Totals`. |
| `app/pipeline/stages/s10_assemble.py` | `async run(ctx: StageContext) -> Path`; build packet, crops, HTML report, packet-ready event. |
| `app/packet/report.py` | `render_report(packet: ClaimPacket, sweep_dir: Path, template_dir: Path) -> str`. |
| `app/packet/templates/report.html.j2` | Responsive, printable report template with evidence links and inline styles/scripts. |
| `app/live/tools.py` | Replace `get_packet_summary` stub with `get_packet_summary(sweep_dir: Path) -> PacketSummary`. |
| `web/js/ui.js` | Add `renderPipeline(progress: PipelineProgress): void` and `renderPacketReady(summary: PacketSummary): void`. |
| `tests/unit/test_packet_validate.py` | Missing frame, price without evidence and totals mismatch are rejected. |
| `tests/unit/test_resolve_statements.py` | Resolve portrait/print and exclude target against fixture detections. |
| `tests/unit/test_packet_review.py` | Every documented reason code and severity/evidence links. |
| `tests/unit/test_report.py` | Empty item list, evidence links, narrow screen/print structure. |

**External accounts/keys:** none for packet/report tests. Live readback uses
Phase 2 credentials; all packet tests are offline.

## Phase 10 — Evaluation, calibration, measured fix

| File | Planned public API |
|---|---|
| `eval/evaluate.py` | `load_ground_truth(path: Path) -> GroundTruth`; `match_books(gt: BooksGT, pred: Books) -> BookMatches`; `compute_metrics(gt: GroundTruth, packet: ClaimPacket) -> EvaluationResults`; `render_results(results: EvaluationResults) -> str`. |
| `app/identify/calibrate.py` | `fit_calibration(features: NDArray, labels: NDArray) -> Calibration`; `choose_accept_threshold(calibration: Calibration, max_wrong_rate: float) -> ThresholdResult`; `wilson_interval(successes: int, trials: int) -> tuple[float, float]`. |
| `app/cli.py` | Implement `evaluate(sweep: Path, gt: Path, out: Path) -> None` and `calibrate(sweep: Path, gt: Path) -> None`. |
| `config/settings.yaml` | Write measured `tau_accept` with sweep id, sample size and date comment; never invent a threshold. |
| `docs/results.md`, `docs/results.json` | Full pass-bar and per-shelf metrics, retaining misses/extras. |
| `docs/calibration.png` | Reliability plot from the calibration data. |
| `tests/unit/test_eval_metrics.py` | Tiny GT/pred tables covering extra/missing books and unidentified legible spine. |
| `tests/unit/test_calibration.py` | Logistic fit, threshold selection, Wilson interval edge cases. |

**External accounts/keys:** no new keys. Owner-provided ground-truth CSVs are
required for meaningful evaluation and calibration. Do not state accuracy
claims until this evaluator has run on those files.

## Phase 11 — Deliverables

| File | Planned public API / content |
|---|---|
| `README.md` | Quickstart, architecture, keys, sweep/replay/eval/reprice, reference-app keep/change/drop notes, exact models/services/checkpoints, assumptions, measured results, limitations and deliverable links; facts only from repo/config/results. |
| `docs/architecture.md` | One-page pipeline diagram, model roles, measured scale anchors/disagreement and sourced-price workflow from actual sweep artifacts. |
| `docs/failure_log.md` | Three measured failures, artifact evidence, minimal fixes, before/after metrics, telemetry and future work. |
| `docs/second_country.md` | Generated India/GB price comparison from Phase 7. |
| `docs/results.md` | Final evaluation results from Phase 10; no invented values. |
| `tests/fixtures/demo_sweep/` or `sweeps/<id>/` | Demo sweep artifacts only after a real sweep and user review; keep secrets/PII excluded. |

**External accounts/keys:** no new accounts, but final demo needs the relevant
Gemini, pricing and geometry services, a phone HTTPS route, printed cards and a
real sweep. The user supplies reference-app notes if they differ from the
documented keep/change/drop analysis.

## Scope and session-size flags

| Phase | Size | Suggested split if a single session becomes too large |
|---|---|---|
| 0 | Medium | Keep contract/config separate from CLI/server only if needed; both remain Phase 0 and must pass the same checks. |
| 1 | Medium | Backend capture/storage and browser capture/UI are separable sub-parts; validate protocol end-to-end after both. |
| 2 | Large | Split bridge/tools/reconnect tests, then browser audio/worklet/protocol integration. Do not proceed to Phase 3 until the fake-session reconnect test passes. |
| 3 | Medium | Monitor/rate-limit logic, then coverage/tool integration. |
| 4 | Large | Split S1 detection + within-frame NMS and tests, then keyframe/orchestrator streaming + provisional UI. Preserve the NMS-before-cross-frame contract. |
| 5 | Very large / highest risk | Split reconstruction client + scale/gravity, then lifting/dedup, then measurement/debug. Hold at Phase 5 until its geometry exit checks are met. |
| 6 | Large | Split crop/transcription and catalogue/matching/edition. Keep shared HTTP/cache interface stable before pricing work. |
| 7 | Large | Split provider parsing/auth/cache, then filtering/appraisal/pricer/CLI; real provider fixtures can be added without exposing keys. |
| 8 | Very large | Split item detection/dedup/pricing, then room geometry. Do not let room failure invalidate otherwise valid items/packet lines. |
| 9 | Large | Split statement resolution/validation/review, then report/template/UI, then Live readback integration. |
| 10 | Large | Split evaluator metrics/report, then calibration, then measured fix. Threshold changes must be evaluated on the same sweep. |
| 11 | Medium, human-dependent | Documentation can be drafted in separate passes, but final numbers and claims wait for actual Phase 10 outputs and demo artifacts. |

## Open decisions and dependencies

1. The API key is confirmed present by the owner, but Live-model access must be
   tested in AI Studio or via an authenticated, non-logging SDK check before
   Phase 2's real phone check. Do not ask the owner to paste a key in chat.
2. India's used-price fallback is explicitly EBAY_GB converted with dated
   Frankfurter evidence; if no qualifying used result exists, keep the value
   null and add `price_not_found`. Never infer it from replacement cost.
3. Phase 4 S1 must persist `merged_from` and `possible_duplicate_box` as defined
   in the updated schema and count borderline candidates in the row check.
4. Ground truth is being collected by the owner. Phase 5's recorded-sweep
   acceptance and Phase 10 calibration cannot be claimed complete until that
   data and the required sample measurements exist.
