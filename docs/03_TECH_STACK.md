# 03 — Tech Stack & Constraints

Rule: **boring, explainable, few moving parts.** Every choice below has a one-line reason you can say on the review call.

## 1. Overview

| Layer | Choice | Why |
|---|---|---|
| Client | **Single-page vanilla HTML + JS + CSS** (no build step), served by FastAPI | Nothing to install. Runs in mobile Chrome/Safari. Visual polish isn't scored |
| Server | **Python 3.12, FastAPI + Uvicorn**, WebSockets | Same as the reference, so its bridge pattern is easy to adapt. Async I/O for many API calls |
| Live voice + vision | **Gemini Live** via `google-genai` SDK (`LIVE_MODEL`, default `gemini-3.8-live`) | The brief's reference uses it. Native audio, barge-in, non-blocking function calls |
| Offline vision (detection + spine transcription + item description) | **Gemini Flash** (`VISION_MODEL`, default `gemini-3.8-flash`) with structured JSON output and 0–1000 normalised bounding boxes | Cheap, fast, good OCR on crops. One provider, one key |
| Metric 3D geometry | **MapAnything** (metric multi-view feed-forward reconstruction) on a serverless GPU (**Modal**). Fallback **VGGT-1B** (up-to-scale, scaled by markers) | Camera poses plus dense depth from ~40–80 frames in seconds. Metric output gives a second scale anchor |
| Metric anchor | **OpenCV ArUco** (`cv2.aruco`) printed scale cards. Cross-checks: known shelf model dimensions, book-format priors | Deterministic and explainable. The brief explicitly allows reference objects and known shelf dimensions |
| Classical CV | **OpenCV** (blur, glare, homography, face blur), **NumPy/SciPy**, **scikit-learn** (DBSCAN, RANSAC), **Shapely** (polygon area) | Standard, testable, no GPU |
| Book catalogue | **Open Library** Search + Works + Editions API (no key); **Google Books API** (metadata/ISBN only) | Free, open, and editions carry publishers, ISBNs and physical dimensions |
| New-price source | **SerpApi Google Shopping** (`gl` per country) behind a `ShoppingProvider` interface | Localised merchant prices with links (Amazon.in, Flipkart, Bookswagon… / UK retailers) |
| Used-price source | **eBay Browse API** `item_summary/search`, marketplace per locale, `conditions:{USED}` | Real used listings with URLs. Official API |
| FX | **Frankfurter** (`api.frankfurter.dev`, no key) | Sourced, dated central-bank rates for every conversion |
| Report | **Jinja2 → `report.html`** (self-contained, relative links to frames) | "PDF or HTML" allowed. HTML is faster and clickable |
| Storage | **Files per sweep** (`sweeps/<id>/…` JSON, JSONL, JPEG) + **SQLite** response cache (`cache/http_cache.sqlite`) | Files are the evidence trail. No DB server |
| CLI | **Typer** (`python -m app.cli …`) | replay, reprice, evaluate, make-markers |
| Packaging | **uv** (`pyproject.toml` + `uv.lock`) | `uv sync` in seconds, which makes "stranger running in 15 min" realistic |
| Tests / lint | **pytest**, **pytest-asyncio**, **ruff** | Fast. Models and HTTP mocked in unit tests |
| Phone HTTPS | **Tailscale Serve** (recommended) or **Cloudflare quick tunnel**, or mkcert on LAN | `getUserMedia` requires a secure context |

## 2. Python dependencies (pin in `pyproject.toml`)

```toml
[project]
name = "library-claim-agent"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "google-genai>=1.0",          # use the latest; Live API + structured output
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "httpx>=0.27",
  "tenacity>=8.3",
  "opencv-contrib-python-headless>=4.10",
  "numpy>=1.26",
  "scipy>=1.13",
  "scikit-learn>=1.5",
  "shapely>=2.0",
  "rapidfuzz>=3.9",
  "jinja2>=3.1",
  "pyyaml>=6.0",
  "orjson>=3.10",
  "typer>=0.12",
  "rich>=13.7",
  "pillow>=10.3",
  "python-multipart>=0.0.9",
]
[project.optional-dependencies]
gpu = ["modal>=0.64"]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "ruff>=0.5", "respx>=0.21"]
```

GPU-side dependencies (MapAnything / VGGT, torch) live **only** in the Modal image definition in `gpu/modal_recon.py`. They never enter the main environment. That keeps the local install light.

> Version note: use the latest `google-genai`. Model IDs change often, so they are **env vars**, never hardcoded. Before Phase 3, check the current Live and Flash model IDs in Google AI Studio and put them in `.env`.

## 3. Frontend

- `web/index.html`, `web/app.js`, `web/audio-worklet.js`, `web/styles.css`. ES modules. No framework, no bundler.
- APIs used: `getUserMedia` (camera `facingMode: "environment"`, ideal 1920×1080, fallback 1280×720), `AudioWorklet` (mic to PCM16 16 kHz), `AudioContext` playback at 24 kHz, `DeviceMotionEvent` and `DeviceOrientationEvent` (iOS needs `DeviceMotionEvent.requestPermission()` on a tap), `OffscreenCanvas`/`canvas.toBlob` for JPEG encoding, `navigator.wakeLock` (keeps the screen on during the sweep).
- Two WebSockets: `/ws/live` (audio + low-res frames + agent events) and `/ws/capture` (hi-res JPEG binary frames + motion JSON). They're separate so a heavy frame upload never delays voice.

## 4. Models: who does what

| Job | Model | Input | Output | Guardrail |
|---|---|---|---|---|
| Conversation, sweep direction, questions, corrections | `LIVE_MODEL` (Gemini Live) | Mic audio, ~768px frames at 1 fps, monitor cues (text), tool results | Speech, tool calls | Never states counts, prices or IDs it didn't get from a tool result. Context compression on |
| Spine/shelf/item detection | `VISION_MODEL` (Flash) | 1080p keyframe | JSON: boxes (0–1000), class, rotation, shelf-row hints | Boxes only. No titles at this stage |
| Spine transcription | `VISION_MODEL` | Upright spine crops (batch of ≤12 per call) | JSON: verbatim text lines, legibility 0–1, `unreadable` flag | Prompt forbids inference. Output text must be substring-plausible (validated) |
| Candidate re-rank (optional) | `VISION_MODEL` | Transcribed text + ≤8 catalogue candidates (IDs) | Chosen candidate ID or `none` | Can only return an ID from the list. Final accept by numeric threshold in code |
| Item description and brand OCR | `VISION_MODEL` | Item crop | Category (from fixed taxonomy), material, visible brand/model text | Brand only if legible text was transcribed |
| 3D reconstruction | MapAnything (fallback VGGT) on Modal GPU | 40–80 keyframes at reduced resolution (~518 px) | Camera poses, intrinsics, depth maps, metric scale | Scale re-anchored to ArUco. Disagreement reported |
| Independent checker (stretch) | `CHECKER_MODEL` (a different model, for example Gemini Pro or another provider) | Random 15% of spine crops, blind | Transcription | Disagreements go to the review queue |

**What never touches an LLM:** prices, totals, counts, dimensions, areas, FX, appraisal rules, confidence thresholds.

## 5. Data and storage constraints

- One folder per sweep: `sweeps/<sweep_id>/` (layout in `05_DATA_SCHEMA.md`). It's gitignored except the final demo sweep, which you commit (frames compressed) because it's a deliverable.
- HTTP cache: SQLite key = `provider + normalized query + locale`, value = raw JSON + fetched_at. TTL 7 days. Cached snapshots are still written into the sweep's `evidence/prices/` so every packet carries its own evidence.
- No database server. No ORM.

## 6. Accounts and keys (get these on Day 1)

| Service | What you need | Free tier / cost | Notes |
|---|---|---|---|
| Google AI Studio | `GOOGLE_API_KEY` | Free tier exists; paid usage per token | Check Live model availability for your key |
| SerpApi | `SERPAPI_API_KEY` | 250 searches/month free; Starter plan is paid | ~70 searches per uncached sweep. **Cache everything**. Consider one month of Starter if you iterate a lot |
| eBay Developers Program | `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` (production keyset) | Free | Client-credentials OAuth token, scope `https://api.ebay.com/oauth/api_scope`. Keyset activation can take a few hours, so apply first |
| Modal | `modal token new` (stored in `~/.modal.toml`) | Monthly free credits | GPU `L4` or `A10G`. Warm the container at sweep start |
| Google Books | `GOOGLE_BOOKS_API_KEY` (optional) | Free quota | Works keyless at low volume |
| Open Library | none | Free | Send a `User-Agent` with a contact email. Be polite: ≤ 5 req/s |
| Frankfurter | none | Free | |
| Tailscale (or Cloudflare) | Account (Tailscale) / none (Cloudflare quick tunnel) | Free | For HTTPS on the phone |

## 7. Environment variables (`.env.example`, full list in `templates/.env.example`)

| Var | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | — | Gemini (Live + Flash) |
| `GOOGLE_GENAI_USE_VERTEXAI` | `False` | AI Studio mode |
| `LIVE_MODEL` | `gemini-3.8-live` | Live conversation model (verify current ID) |
| `VISION_MODEL` | `gemini-3.8-flash` | Detection, transcription, items (verify current ID) |
| `CHECKER_MODEL` | empty | Stretch: independent checker |
| `LIVE_VOICE` | `Kore` | Voice |
| `SERPAPI_API_KEY` | — | New prices |
| `SHOPPING_PROVIDER` | `serpapi` | Swap point |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | — | Used prices |
| `GOOGLE_BOOKS_API_KEY` | empty | Optional |
| `OPENLIBRARY_CONTACT` | — | Email in User-Agent |
| `GEOMETRY_BACKEND` | `modal` | `modal` \| `local` \| `off` |
| `RECON_MODEL` | `mapanything` | `mapanything` \| `vggt` |
| `DEFAULT_COUNTRY` | `IN` | Locale default (confirmed by voice) |
| `MARKER_DICT` | `DICT_4X4_50` | ArUco dictionary |
| `MARKER_SIZE_MM` | `100.0` | **Measure your printout with a ruler and set this** |
| `HIRES_FPS` | `2` | Capture channel rate |
| `HIRES_WIDTH` | `1920` | Capture resolution target |
| `SWEEPS_DIR` | `./sweeps` | Output |
| `CACHE_DB` | `./cache/http_cache.sqlite` | Response cache |
| `LOG_LEVEL` | `INFO` | |

## 8. Phone connectivity (HTTPS is required for camera and mic)

Pick one and put it in the README.

1. **Tailscale Serve (recommended).** Install Tailscale on the laptop and the phone, then run `tailscale serve --bg 8000` and open `https://<machine>.<tailnet>.ts.net` on the phone. It has a real certificate and usually a direct peer-to-peer path, which means high bandwidth for 1080p frames.
2. **Cloudflare quick tunnel:** `cloudflared tunnel --url http://localhost:8000`, then open the printed `https://….trycloudflare.com`. No account needed. Bandwidth goes through the internet, so drop to `HIRES_FPS=2` and JPEG quality 0.8.
3. **mkcert on LAN:** `mkcert <laptop-ip>`, then `uvicorn … --ssl-keyfile --ssl-certfile`, and install the mkcert root CA on the phone. Fastest, but fiddly on iOS.

## 9. Hard constraints (from the brief, enforced in code review)

- No LLM-produced prices or totals. Prices come only from `pricing/providers/*` parsers.
- No hardcoded catalogue, price list or room dimensions. `config/` holds *rules and locale settings only*.
- No barcode/ISBN typing/one-by-one photo flows.
- No training from scratch.
- Secrets only in `.env` (gitignored). `.env.example` committed.
- Identification, pricing and measurement are separate modules with separate JSON outputs.
- Every frame_ref resolves to a saved file.

## 10. Cost and latency budget (targets, measured in telemetry)

| Stage | Latency target (after sweep end) | Cost driver |
|---|---|---|
| Detection + transcription (mostly *during* the sweep) | ≤ 20 s tail | Flash calls (batch crops) |
| Geometry (Modal, pre-warmed) | ≤ 40 s | GPU seconds |
| Dedup + measurement | ≤ 5 s | CPU |
| Identification (catalogue lookups, concurrent 8) | ≤ 25 s | Free APIs |
| Pricing (concurrent 6, cached) | ≤ 40 s | SerpApi searches, eBay calls |
| Room geometry + assembly + report | ≤ 10 s | CPU |
| **Total** | **≤ 2 min** (hard limit 5) | |

Put model and API unit prices in `config/pricing_rates.yaml`, taken from each provider's pricing page on the day you build (with the URL and date in the file). Telemetry multiplies them by measured usage. Never invent the unit prices.
