# 01 — Problem Breakdown: what Cozmo is really asking, and how to win it

## 1. The brief in plain words

A homeowner wants to claim insurance on the contents of their home library. Instead of typing a list, they open your web app on a phone, talk to an AI agent, and walk the room once with the camera on (under 3 minutes). Within 5 minutes of finishing, they get a claim packet that lists:

- **every book**: counted from the spine, with title, author and edition where readable, measured (height and thickness in cm), and priced twice (new replacement cost and used market value) in the local currency, with a source URL and date for every price;
- **every non-book item** (shelves, furniture, lamps, art, rugs, electronics, decor), with category, approximate size, brand or model if legible, and a sourced price or price range;
- **the room itself**: length, width, ceiling height, floor area, wall area, and wall area covered by shelving, in m² and ft²;
- **a review queue** of everything the system isn't sure about, with the reason.

The agent isn't passive. While you walk, it watches the capture quality and tells you to slow down, step closer, fix the glare or go back to a missed shelf. It asks questions the camera can't answer ("Is that portrait an original or a print?"), and it accepts voice corrections ("Skip that shelf, those aren't mine").

## 2. What they are actually testing (the hidden rubric)

The brief says it directly: three things.

| They test | What it means in practice | What fails it |
|---|---|---|
| **Real measurements from messy capture** | Counts, cm, m², and the actual book count, all checked against *your* tape measure and *their* tape measure in the live review | "The model estimated it." Any number with no metric-scale method |
| **Keeping a model from inventing facts when money is attached** | The LLM never outputs a price or a total. Titles only come from text actually read on the spine and confirmed against a catalogue | A plausible price with no URL. A guessed title for a blurry spine. Totals written by an LLM |
| **Honest failure reporting** | Accuracy reported on *all* shelves, misses quantified, three worst errors with root causes, one measured fix | "Could be improved with better models." Accuracy only on the good shelf |

The reference app *describes* what it sees. Yours has to measure, count and price it. That gap is the whole assignment.

## 3. Scoring weights and where the points really are

| Area | Weight | Where you win it |
|---|---|---|
| Measured accuracy | **30%** | Ground truth collected before tuning. Pass bars computed by a script on every shelf. A scale method you can explain. Robustness on an unseen room |
| Pricing integrity | **20%** | Pricing in code only, with every price carrying source, URL, date, condition and raw snapshot. Unknowns blank and excluded. Rare/art flagged. Second country shown |
| Live agent & one-sweep capture | **20%** | The agent catches bad capture *in the moment* from measured signals and recovers in the same pass. Inventory fills in live. Voice corrections work |
| Engineering | **15%** | Separate, testable stages with their own JSON outputs. Offline replay. Runs from the README in under 15 minutes. Cost and latency per stage |
| Failure analysis | **15%** | Named root causes. One before/after fix measured on the same recorded sweep |

So 65% is accuracy, pricing integrity and honesty. Visual polish is explicitly worth 0%.

## 4. Pass bars (memorise these)

| Measure | Pass bar | The real difficulty | Our lever |
|---|---|---|---|
| Book count | within ±5% of true | The same book appears in 10+ frames (dedup). Flat stacks. Thin pamphlets | 3D dedup through reconstruction plus per-row ordering. Stacks handled as rotated boxes |
| Title ID | ≥70% of human-legible spines correct, **≤3% confidently wrong** | Hallucinated titles. Similar titles. Series volumes | Transcribe, then catalogue match, then a calibrated threshold. Below threshold → unidentified |
| Spine dimensions | within 15% on 20 hand-measured | Metric scale, perspective, books recessed from the shelf edge | Marker plane homography, then reconstruction depth as fallback, format priors as a sanity check |
| Book prices | within 25% of your hand-checked price (same source type) on 15 | Wrong edition, ebook vs print, outlier listings | Same source type as your ground truth. Physical-only filter. Median of matched offers |
| Non-book items | ≥80% found with correct category | Dedup across frames. Small decor. Category taxonomy | Fixed taxonomy. 3D centroid dedup. The agent asks the user to show room corners |
| Floor area | within 10% | Metric scale of the whole room. Non-rectangular rooms | Metric 3D reconstruction anchored by the marker. Wall-line polygon |
| Wall area | within 15% | Ceiling height (users don't film ceilings) | The agent explicitly asks for the ceiling line. Measured height from floor and ceiling planes |
| Time to packet | <5 min after sweep end | Many API calls | Start the pipeline *during* the sweep. Concurrency. Caching. GPU warmed at sweep start |

> The demo video is **one take, ≤ 6 min, including the final packet.** Sweep (~3 min) plus intro (~30 s) leaves you roughly **2 minutes** for processing on camera. **Target time-to-packet: under 2 minutes.**

## 5. The traps (each one can zero a rubric section)

1. **Forking the reference and changing the prompt.** Explicitly banned. Write your own code. You can borrow patterns (WebSocket bridge, NON_BLOCKING tools) and say so in the README.
2. **The LLM produces a price from memory.** Counts as a fabricated price. Pricing is code that parses API responses, and the LLM may at most pick *which* search result matches, by ID.
3. **Guessed titles on unreadable spines.** Penalised harder than blanks.
4. **Totals written by a model.** Totals must be pure Python summing the lines, with a unit test.
5. **Hardcoding** a catalogue, a price list, or your room dimensions. Every number must come from the sweep or a live source.
6. **Asking the user to scan barcodes, type ISBNs, pull books out or photograph items one by one.** Banned interaction.
7. **An edited, sped-up or stitched demo video.** One take.
8. **Accuracy only on the frames that worked.** Report everything.
9. **Auto-pricing art, signed copies or rare editions.** Must be `needs_appraisal`.
10. **Gemini Live audio+video sessions die at about 2 minutes** unless you enable **context window compression** and handle **session resumption / GoAway**. Your sweep is up to 3 minutes. The reference never hits this. You will.
11. **The reference sends 512px JPEGs at 1 fps** to the live model. You cannot read spines at that resolution. You need a **second, high-res capture channel** for the measurement pipeline.
12. **Phone camera access requires HTTPS.** `getUserMedia` won't work on `http://<laptop-ip>`. Plan a tunnel or a local certificate (see `03`).
13. **Google Books `saleInfo` prices are eBook-store prices** (Google Play). They're not physical-book replacement cost. Don't use them as "replacement cost" without labelling them.
14. **Capturing people or personal documents** in the sweep. Not allowed. Keep people out of frame, and blur faces in saved frames as a safety net.
15. **Code you can't explain line by line.** Codex will write a lot. Read every file before committing (see `08_AGENTS.md`, rule "explainability").

## 6. What to read and run before building (in order, ~3 hours total)

### 6.1 The reference app (mandatory, 60–90 min)

Repo: https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/voice_ai_agents/insurance_claim_live_agent_team

Run it:
```bash
git clone --depth 1 https://github.com/Shubhamsaboo/awesome-llm-apps.git
cd awesome-llm-apps/voice_ai_agents/insurance_claim_live_agent_team
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set GOOGLE_API_KEY, GOOGLE_GENAI_USE_VERTEXAI=False
python -m uvicorn live_demo.server:app --reload --host 127.0.0.1 --port 4177
# open http://127.0.0.1:4177 ; Talk → Show camera → try the fictional claim in the README
```

What to read, file by file (and what to note):

| File | Read for | Keep / change / throw away |
|---|---|---|
| `live_demo/live_tools.py` | `SYSTEM_INSTRUCTION` style (honest "say what you see, don't repeat the claimant's word"). Tool declarations with `behavior=NON_BLOCKING`. `FunctionResponseScheduling.INTERRUPT` vs `WHEN_IDLE`. `START_OF_ACTIVITY_INTERRUPTS` for barge-in | **Keep the pattern**: non-blocking tools, interrupt scheduling for urgent capture cues. **Change**: completely new prompt and tools for sweep direction |
| `live_demo/server.py` | WebSocket loop: browser to server to `live_session.send_realtime_input(audio/video)`. Per-kind rate limits (video ≤5/s, ≤512 KB). Frame freshness (`FRAME_MAX_AGE_SECONDS`). Tool launch in background tasks | **Keep** the bridge shape. **Change**: add a separate high-res frame channel, context compression, session resumption, the capture monitor. **Throw away**: policy lookup, sketches, avatar |
| `live_demo/app.js` | Mic capture to PCM16 16 kHz (resampling). Camera at 640×480, 512px JPEG at 1 fps. 24 kHz playback | **Keep** the audio plumbing idea. **Change** camera to 1080p+, dual stream, device-motion sampling |
| `agent.py`, `policies.py`, `schemas.py` | ADK graph doing normalization → classification → validation → packet. Deterministic rules after LLM extraction | **Keep the philosophy** (deterministic rules after model extraction). **Throw away** ADK itself: your background work is a plain asyncio stage pipeline, which is easier to test and explain |
| `tests/` | Mocked model calls, regression tests | **Keep** the testing approach: mock models, test deterministic code |

Write 5 bullets for the README: *kept / changed / threw away / why*. A draft is in `12` §1.

### 6.2 Docs to skim (bookmark these)

- **Gemini Live API session management**: context window compression, session resumption, GoAway. https://ai.google.dev/gemini-api/docs/live-session
- **Gemini Live tool use** (function calling in live sessions, non-blocking behaviour). Linked from the Live API docs at https://ai.google.dev/gemini-api/docs/live
- **Gemini image understanding / object detection with bounding boxes** (boxes come back normalised 0–1000): https://ai.google.dev/gemini-api/docs/image-understanding
- **OpenCV ArUco detection** (your metric anchor): https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html
- **MapAnything** (Meta + CMU, feed-forward *metric* multi-view 3D reconstruction): https://github.com/facebookresearch/map-anything. Check the checkpoint licence (there's a non-commercial and an Apache variant; either is fine for an assignment, but state which you used)
- **VGGT** (fallback reconstruction, up-to-scale): https://github.com/facebookresearch/vggt
- **Open Library APIs** (search, works, editions with publishers, ISBNs, physical dimensions): https://openlibrary.org/developers/api
- **Google Books API volumes** (metadata, ISBNs; `saleInfo` is eBook only): https://developers.google.com/books/docs/v1/reference/volumes
- **SerpApi Google Shopping** (localised new prices via `gl=in` / `gl=uk`): https://serpapi.com/google-shopping-api. The free plan is 250 searches/month, so cache aggressively
- **eBay Browse API** `item_summary/search` with `X-EBAY-C-MARKETPLACE-ID` (EBAY_GB, EBAY_US …) and `filter=conditions:{USED}`: https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
- **Frankfurter** (free FX from ECB and other central banks, no key): https://frankfurter.dev
- **Modal** (serverless GPU for the reconstruction stage): https://modal.com/docs
- **Cloudflare quick tunnels** (HTTPS URL for your phone, no account): https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/

### 6.3 Domain knowledge to have in your head

- **Standard book formats** (sanity priors, *never* the measurement itself). UK A-format paperback ≈ 17.8 × 11.1 cm; B-format ≈ 19.8 × 12.9 cm; Demy ≈ 21.6 × 13.8 cm; Royal ≈ 23.4 × 15.6 cm; US trade paperback ≈ 22.9 × 15.2 cm; US hardcover ≈ 23.5–24.1 cm tall. Indian editions mostly fall in the same B-format/Demy range. Use these only to flag implausible measurements ("a 41 cm novel? → review").
- **Known furniture dimensions as a cross-check.** If the shelf is a legible, known model (for example IKEA BILLY 80×28×202 cm), it's a *second scale anchor*. The brief explicitly allows "known shelf dimensions".
- **Insurance vocabulary.** *Replacement cost* is the cost to buy new or equivalent today. *Used/actual cash value* is depreciated market value. *Adjuster* is the person who verifies the claim. *Contents claim* covers movable items, not the building.

## 7. The approach, in one paragraph

A phone browser streams **two channels** to a FastAPI server: (1) mic audio plus low-res frames to **Gemini Live** for the conversation, and (2) **1080p frames at 2–3 fps plus phone motion data** to a **capture pipeline**. A deterministic **capture monitor** scores every frame for blur, glare, exposure, speed and coverage, and pushes short cues into the live session so the agent says "slow down" or "you missed the bottom shelf" while the user is still there. Keyframes flow into **separate, testable stages**: (a) detection of spines, shelves and items with a vision model; (b) **metric geometry**: ArUco scale cards plus a metric multi-view reconstruction, fused and cross-checked with known shelf sizes; (c) **3D dedup and counting**; (d) **spine transcription** (the model copies visible text only) followed by **catalogue matching** in Open Library and Google Books with a calibrated confidence threshold; (e) **pricing in code** from SerpApi Google Shopping (new) and eBay Browse (used), with FX from Frankfurter when converted, rare and art routed to appraisal; (f) **room geometry** from floor, ceiling and wall planes; (g) **packet assembly** with totals in code, a review queue, and an HTML report where every line links to its frame crop and price snapshot. Identification and detection start *during* the sweep, so the packet lands within about 2 minutes of "done".

## 8. How to stand out (beyond passing)

Ranked by impact per hour:

1. **A measured capture monitor drives the voice.** Blur (Laplacian variance), glare (% saturated pixels), speed (gyro °/s from DeviceMotion plus frame flow), and a coverage map of shelf rows, room corners and ceiling. The agent's "slow down" is triggered by a number, not a vibe. Show the meter on screen in the video.
2. **Scale fusion with reported disagreement.** `scale_method: "aruco(3 detections) + mapanything; cross-check IKEA BILLY height 202 cm → +2.8%"`. Nobody else will report *how much their anchors disagree*.
3. **Transcribe ≠ identify.** The vision model only transcribes spine text, and a catalogue decides identity. This structurally prevents hallucinated titles, and you can explain it in one sentence on the call.
4. **An evidence chain an adjuster can click.** Every report line opens the frame crop with its bounding box drawn, plus the price source URL and the saved raw API JSON.
5. **Calibrated confidence.** Plot accuracy vs `id_confidence` from your ground truth, and pick the threshold that keeps confidently-wrong ≤3%. Put the plot in the results doc.
6. **Offline replay.** `python -m app.cli replay sweeps/<id>` re-runs every stage on the saved frames. This makes the before/after fix in the failure log provable, and lets the reviewers rerun your packet.
7. **A dress rehearsal on an unseen room.** Before submitting, run it on a friend's shelf or a bookshop corner you never tuned on, and report those numbers too. This directly pre-empts their "collapses on our shelf" test.
8. **A cost and latency ledger** per stage in the packet (`meta.telemetry`) and in the report footer.
9. **Locale as config.** `config/locales/IN.yaml`, `GB.yaml`; `python -m app.cli reprice --sweep <id> --country GB --limit 10` produces the second-country table.
10. **Stretch goals, only after the core passes:** an independent checker agent (a second model re-reads a random 15% of spines blind and reports disagreement) and a floor-plan SVG from the room polygon. Both are cheap because you already have the data.

## 9. Assumptions to state in the README (decide well under ambiguity, then move on)

1. Primary locale **India / INR**; second locale **United Kingdom / GBP** (strong used-book market on eBay UK).
2. **Scale cards are allowed setup**: up to three printed A4 ArUco cards placed on shelves before the sweep. They're "reference objects", which the brief allows. Without cards, the system falls back to metric reconstruction plus shelf/format cross-checks at lower confidence, and says so.
3. **Replacement cost** = cheapest *reputable new physical copy* of the same work in the local market today (median of matched new offers). It doesn't need to be the same edition unless an edition was resolved.
4. **Used value** = median of matched *used* listings, assumed condition **"Used – Good"**. If there's no local used market (India has no eBay), use the nearest market converted with a sourced FX rate, labelled `converted: true`.
5. **`excluded_from_totals`** = *number of lines* excluded (unpriced or needs appraisal). The excluded line IDs are listed in an added field.
6. **Wall area** is gross (perimeter × height). Doors and windows are reported separately if detected, not subtracted, unless measured.
7. **Appraisal threshold:** used value > ₹5,000 (or £50 for GB), or used > 1.5 × replacement, or publication year < 1950, or the user says signed or first edition, or visual cues of leather/gilt binding. All of these go to `needs_appraisal` and are not priced.
8. **Art and portraits** default to `needs_appraisal`. They're priced as a print range only if the user says "print".
9. One room per sweep. Multi-room is a stretch goal and out of scope.
10. People and personal documents are kept out of frame. Saved frames get face-blurred as a precaution.

## 10. 48-hour timeline (15–20 hours of real work)

| Block | Hours | What |
|---|---|---|
| H0–H2 | 2 | Read the brief, run the reference, set up keys, print cards |
| H2–H4 | 2 | **Ground truth part 1**: count books, tape the room, hand-read titles, measure 20 spines. Record a test sweep with any camera for offline dev |
| H4–H8 | 4 | Phases 0–3: skeleton, capture app, capture monitor, live agent with tools and compression |
| H8–H12 | 4 | Phases 4–6: detection, geometry and scale, counting/dedup, transcription and identification |
| — | sleep | — |
| H12–H15 | 3 | Phases 7–8: pricing, items, room geometry, packet and report |
| H15–H17 | 2 | **Ground truth part 2** (hand-check 15 prices), eval script, first honest results |
| H17–H20 | 3 | Phase 9: tune with replay, the one measured fix, rehearsal on an unseen space |
| H20–H22 | 2 | Final recorded sweep and demo video (allow 2–3 takes), README, architecture note, failure log |
| buffer | 2–4 | Breakage, stretch goals |

## 11. Risk register (and your fallback for each)

| Risk | Likelihood | Fallback already designed in |
|---|---|---|
| Reconstruction fails (textureless walls, fast motion) | Medium | Room fields left empty, confidence 0, review queue entry. Spine dims still come from the marker plane. The failure is logged honestly |
| No GPU / Modal issues | Medium | `GEOMETRY_BACKEND=local` (CUDA laptop) or `off` (room via review queue, dims via marker plane only) |
| SerpApi quota exhausted | High during dev | SQLite response cache. Dev against cached fixtures. Provider interface lets you swap in Serper or another shopping API |
| eBay key delay | Medium | Used value blank → excluded and queued. That's honest, and pricing integrity holds |
| Live session drops mid-sweep | Medium | Compression plus resumption. The capture channel is independent, so frames keep saving even if the voice blips |
| Spines unreadable at 1080p | High on small type | The agent asks to step closer (driven by text-height estimate). Unreadable → unidentified with dims. Never guess |
| Phone/laptop bandwidth too low for 1080p@3fps | Medium | Drop to 2 fps. Adaptive JPEG quality. Keyframe gating on the client (only send when moved or sharp) |
| Codex writes code you can't explain | High | Rule in AGENTS.md: small files, comments on the "why", and you read every diff before committing |
