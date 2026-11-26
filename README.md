# ShelfClaim

ShelfClaim guides a policyholder through a phone-camera walk of a home library and builds an evidence-backed contents-claim packet.

**Trust model:** models perceive and transcribe; code decides. Packet counts, dimensions, prices, and totals come from detections, marker geometry, provider responses, and deterministic rules. Each price has a source and saved response; unknown values stay blank for review.

## Quickstart (under 15 minutes)

You need Python 3.12, `uv`, an Android phone, and network access.

1. Install the app and development tools:

   ```powershell
   uv sync --extra dev
   Copy-Item .env.example .env
   ```

2. Set these keys in `.env` for the full identification and pricing path: `GOOGLE_API_KEY`, `GOOGLE_BOOKS_API_KEY`, and `SERPAPI_API_KEY`. `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` are optional and unused by the configured SerpApi eBay provider. Keep `.env` private.
3. Download the face detector:

   ```powershell
   uv run python -m app.cli download-yunet
   ```

4. Create scale cards, print at actual size, measure a printed marker with a ruler, then set `MARKER_SIZE_MM` in `.env` to the measured size:

   ```powershell
   uv run python -m app.cli make-markers --ids 0 1 2 --size-mm 100 --out markers.pdf
   ```

5. Set `GEOMETRY_BACKEND=off` for this build, then start the server:

   ```powershell
   .\tasks.ps1 dev
   ```

6. In another terminal, expose port 8000 to your phone:

   ```powershell
   tailscale serve --bg 8000
   ```

   Open the provided HTTPS address in Android Chrome, allow camera and microphone access, and tap **Start**. Place the scale cards on the shelves you want measured. With geometry disabled, room area stays unmeasured.

## Common commands

```powershell
# Replay saved frames beginning at identification and continue through the packet
uv run python -m app.cli replay sweeps/<sweep-id> --from-stage s06 --until s10 --limit 10

# Evaluate against labelled ground truth
uv run python -m app.cli evaluate --sweep sweeps/<sweep-id> --gt eval/ground_truth --out docs/results.md

# Search up to 10 price queries for a locale
uv run python -m app.cli reprice --sweep sweeps/<sweep-id> --country GB --limit 10

# Test the conversational agent in a terminal
uv run python -m app.cli agent-chat

# Exercise the real agent loop with saved frames
uv run python -m app.cli agent-soak --turns 20 --with-frames sweeps/sw_20261126_023206_7f03
```

Replay can call configured model and pricing providers. Use saved fixtures for routine development and keep live calls within the available quota. See [evaluation results](docs/results.md) before interpreting performance.

## Reference app: kept, changed, removed

- **Kept:** the voice-and-camera intake pattern, browser-to-server WebSocket shape, non-blocking tool calls, the “say only what you see” honesty rule, and mocked-model tests.
- **Changed:** added a separate 1080p capture channel because the reference’s 512 px, 1 fps stream cannot resolve spine text; changed the agent into a sweep director that speaks measured QC cues; replaced the ADK graph with a staged, file-based pipeline.
- **Removed:** policy lookup, incident sketches, avatar, and notebook-style packet.

## Design decisions

- **Free cascaded voice:** Chrome Web Speech recognition sends text to Gemini Flash-Lite and deterministic intent handlers; browser speech synthesis speaks replies. This replaces Gemini Live because it requires billing. Raw microphone audio does not go to the server.
- **Direct capture cues:** blur, speed, exposure, and glare rules trigger short browser-spoken cues from measured frame data without an LLM call.
- **Local spine reading:** RapidOCR with ONNX Runtime is the default because the Gemini free quota was exhausted; local OCR does not consume model quota.
- **Catalogue order:** Google Books is primary for metadata and ISBNs because Open Library was unreachable from this network. Open Library remains an enabled fallback. Google Books `saleInfo` is not price evidence.
- **Prices:** SerpApi Google Shopping supplies new offers; the SerpApi eBay engine supplies used offers; Frankfurter supplies FX conversion. The environment template and settings mention optional eBay Browse credentials/provider selection, but this repository has no Browse provider implementation; this run used SerpApi eBay.

## Models, services, and tools

| Role | Model or service |
|---|---|
| Agent conversation | `AGENT_MODEL`, default `gemini-3.1-flash-lite`, through `google-genai` |
| Vision detections | `VISION_MODEL`, default `gemini-3.5-flash-lite` |
| Spine transcription | RapidOCR + ONNX Runtime on CPU |
| Face detection | OpenCV YuNet; strict Haar fallback when the model is absent |
| Catalogue | Google Books API first; Open Library fallback |
| Price evidence | SerpApi Google Shopping and SerpApi eBay; Frankfurter FX |
| Application | Python, FastAPI, Pydantic, Typer, httpx; browser Web Speech API and `speechSynthesis` |

AI coding tools: Codex implemented the application; Claude helped with planning documents and debugging guidance.

## Assumptions

These follow [docs/01_PROBLEM_BREAKDOWN.md §9](docs/01_PROBLEM_BREAKDOWN.md) and [docs/DECISIONS.md](docs/DECISIONS.md): India/INR is primary and UK/GBP is the second locale; up to three printed A4 ArUco cards are allowed setup. Replacement value is the median of matched new physical offers, not necessarily the same edition unless edition evidence exists. Used value is the median of matched used offers and assumes “Used – Good”; without a local market, the nearest market is converted with sourced FX. `excluded_from_totals` counts lines. Wall area is defined as gross perimeter × height; doors and windows are not subtracted unless measured. Appraisal rules include used value above ₹5,000/£50, more than 1.5× replacement, pre-1950 publication, signed/first-edition claims, or visual leather/gilt cues. Art and portraits default to appraisal unless the user confirms a print. Scale cards are the intended metric anchors; with `GEOMETRY_BACKEND=off`, room dimensions and area remain null and book dimensions require a same-plane marker.

## Results, cost, and latency

| Measure | Current evidence |
|---|---|
| S06–S10 packet validation | PASS |
| Book rows / identified | 11 / 4; not an accuracy score |
| Used prices | 4 converted eBay UK offers; 8 SerpApi searches |
| Accuracy | NOT MEASURED; labelled ground truth is incomplete |
| S06–S10 time to packet | 96.118319 s; excludes capture and S01–S05 |
| Cost per sweep | TODO: provider rates and cost telemetry are not available |

The 11 rows came from the three reviewed shelf frames only, not a full-sweep coverage count. See [docs/results.md](docs/results.md) for stage durations, evaluation bars, and evidence limits. Provider rates in `config/pricing_rates.yaml` are still TODO.

## Limitations

- The current shelf run contains about 30 books, below the brief’s 60-book minimum.
- Room area is not measured; 3D reconstruction is out of scope for this build.
- In this build, `end_sweep` does not automatically launch finalization; use CLI replay to process saved capture artifacts.
- Spine boxes can overlap, affecting line assignment and identity matching.
- Capture metrics cannot answer visibility questions such as whether an artwork is an original or print.
- Earphones are recommended so phone TTS is less likely to contaminate speech recognition.
- Live detection-driven inventory and coverage cues remain incomplete; only deterministic image-quality cues are supported during capture.
