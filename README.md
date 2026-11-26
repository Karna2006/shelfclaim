# ShelfClaim

ShelfClaim guides a policyholder through a camera sweep of a home library and prepares an evidence-backed contents claim packet.

**Trust rules:** models perceive and transcribe; deterministic code counts, measures, prices, and totals. Every asserted price must link to a provider response and saved snapshot. Unknown values stay blank and enter review.

## Results at a glance

The live run did not produce an S1 detection artifact: the single allowed Gemini replay returned HTTP 503 `UNAVAILABLE` (high demand). Accuracy is **not measured**; see [docs/results.md](docs/results.md). Offline QC on the demo sweep (`sw_20261126_023206_7f03`) found 68 frames over 42.73 seconds: 83.8% OK and 16.2% blurry. The latest sweep (`sw_20261126_044135_a4bd`) had 85 frames over 52.92 seconds: 0% OK, 49.4% blurry, 44.7% dark, and 5.9% fast. Neither sweep had markers detected.

| Measure | Result |
|---|---|
| Book count, title, dimensions, price, item accuracy | Not measured; no S1 artifact or packet |
| Room floor/wall area | Not measured; 3D reconstruction is out of scope |
| Time to packet, provider cost | Not measured; full pipeline did not complete and rates are unset |

## Quickstart

Expected setup is under 15 minutes with Python 3.12, `uv`, a phone, and network access.

1. Install dependencies: `uv sync --extra dev`.
2. Copy `.env.example` to `.env` and set `GOOGLE_API_KEY`. Set `SERPAPI_API_KEY` only if you intend to run pricing. Do not commit `.env`.
3. Set `GEOMETRY_BACKEND=off` for this build. Room area remains null; spine dimensions can only be measured when a marker is visible in the selected frame.
4. Start the app: `uv run uvicorn app.server.main:app --host 0.0.0.0 --port 8000`.
5. Expose the local server to your phone with Tailscale Serve or a tunnel, open the URL in Chrome, grant camera and microphone access, then tap Start.
6. After a sweep, use the CLI commands below to process, inspect, evaluate, or price its saved artifacts.

The browser uses Web Speech recognition and speech synthesis for voice. The server sends recognized final text to the agent; it does not receive raw microphone audio. Models default to `AGENT_MODEL=gemini-3.1-flash-lite` and `VISION_MODEL=gemini-3.5-flash-lite`. The agent handles short conversation; the vision model handles detection and transcription. Current detection is a post-capture stage; live detection-driven inventory and cues are not wired yet.

## CLI

```powershell
.venv\Scripts\python.exe -m app.cli inspect-sweep sweeps/<sweep-id>
.venv\Scripts\python.exe -m app.cli detect-frame sweeps/<sweep-id>/frames/frame.jpg --out debug/frame-detections.png
.venv\Scripts\python.exe -m app.cli replay sweeps/<sweep-id> --until s06
.venv\Scripts\python.exe -m app.cli debug-boxes sweeps/<sweep-id>
.venv\Scripts\python.exe -m app.cli reprice --sweep sweeps/<sweep-id> --country GB --limit 10
.venv\Scripts\python.exe -m app.cli replay sweeps/<sweep-id> --until s10
.venv\Scripts\python.exe -m app.cli evaluate --sweep sweeps/<sweep-id> --gt eval/ground_truth --out docs/results.md
.\tasks.ps1 check
```

Replay may call the configured vision service; repricing uses at most `--limit` SerpAPI searches and requires S6 catalogue matches. Do not rerun a live model call when it would exceed the configured budget.

## Reference design decisions

The source notes are in `docs/notes/PRODUCT_DIRECTION.md` and the review outline is in `docs/12_DELIVERABLES_AND_REVIEW.md`.

- **Kept:** one guided camera walk, spoken instructions, an auditable packet, evidence-first review, and explicit uncertainty.
- **Changed:** Gemini Live became a browser speech cascade to avoid its billing path; the pipeline uses saved per-stage JSON; high-resolution frames support spine reading; deterministic capture cues guide the walk.
- **Threw away:** the reference policy lookup and mock directory, incident sketches, avatar, ADK classification graph, and ZIP-notebook packet format because they do not support measured, line-level library inventory evidence.

## Models, tools, and assumptions

- Gemini via `google-genai`: configured agent and vision models above. The one S1 vision replay in this run returned 503. No successful full pipeline call is claimed.
- Browser voice: Web Speech API and `speechSynthesis`; no raw audio upload.
- Catalogue: Open Library and Google Books metadata. Identity requires a catalogue match on transcribed spine text.
- Pricing: SerpAPI Google Shopping and eBay results, with Frankfurter FX for cross-currency quotes. No pricing calls were made in this run.
- Geometry: `GEOMETRY_BACKEND=off`; only marker-plane spine measurements are in scope. Room dimensions and area remain null.
- Coding assistant: Codex. Claude was not used for this run.
- Assumptions: local sweep artifacts are the evidence source; no unobserved shelf, title, price, or room facts are inferred.

## Cost, latency, and limitations

Per-provider rates in `config/pricing_rates.yaml` are still TODO. There is no successful full-run telemetry, so cost per sweep and per-stage latency are **not measured**. The results table is blocked because the replay returned 503 and the ground-truth count file has no measured `true_count` rows.

Known limits: S1 detections are post-capture rather than live; the capture monitor currently emits only image-quality cues; the inventory sheet does not receive a live provisional feed; item brand/material extraction and item price integration need completion; a full pipeline packet has not yet been validated on a field sweep; room area is not measured.
