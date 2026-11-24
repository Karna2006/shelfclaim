# 12 — Deliverables, Demo Script & Review-Call Prep

Six deliverables. A missing one scores **zero** for the rubric part it supports.

| # | Deliverable | Where | Supports |
|---|---|---|---|
| 1 | Private GitHub repo shared with reviewers, README, `.env.example`, no secrets | GitHub | Engineering 15% |
| 2 | Demo video: one unedited take, ≤ 6 min, full sweep with agent voice, inventory filling, final packet | YouTube unlisted / Drive link | Live agent 20% |
| 3 | `claim_packet.json` + `report.html` + referenced frames from the video's sweep | `demo/sweep_<id>/` in the repo (and zipped in the email) | Pricing 20%, Accuracy 30% |
| 4 | Ground truth + results sheet vs every pass bar | `eval/ground_truth/`, `eval/results.xlsx`, `docs/results.md` | Accuracy 30% |
| 5 | Architecture note (1 page) | `docs/architecture.md` (+ PDF) | Engineering |
| 6 | Failure log (1 page) incl. cost per sweep, latency per stage | `docs/failure_log.md` (+ PDF) | Failure analysis 15% |

---

## 1. README outline (≤ 250 lines)

1. **ShelfClaim**: one-liner + a 3-line "what makes it trustworthy" (models perceive, code decides; every number has evidence; blank beats wrong).
2. **Results at a glance**: the pass-bar table from `docs/results.md` (including FAILs, honestly).
3. **Quickstart (< 15 min)**: prerequisites (Python 3.12, uv, a phone, Tailscale or cloudflared); `git clone` → `uv sync` → `cp .env.example .env` (which keys are required vs optional) → `make modal-deploy` *or* `GEOMETRY_BACKEND=off` → `make markers` → print, measure, set `MARKER_SIZE_MM` → `make dev` → `tailscale serve --bg 8000` → open on the phone → Start.
4. **Running a sweep**: placing cards, the walk, what the agent will say, where outputs land.
5. **Replay / evaluate / reprice** commands.
6. **Reference app: kept / changed / threw away.** Draft:
   - *Kept:* the interaction pattern (talk + camera + a file that builds itself), the browser↔server↔Gemini Live WebSocket bridge shape, non-blocking tools with interrupt vs when-idle scheduling, the "say only what you can see" honesty stance, mocked-model unit tests.
   - *Changed:* the camera path (the reference's 512 px @ 1 fps is unreadable for spines → a second 1080p capture channel); the session (context compression + resumption, because audio+video sessions otherwise end at ~2 min); the agent's role from intake interviewer to sweep director driven by measured capture-quality cues; the background work from an ADK graph to a staged, file-based pipeline with per-stage JSON.
   - *Threw away:* policy lookup/mock directory, incident sketches, the avatar, the ADK claim-classification graph, the ZIP-notebook packet format.
   - *Why:* the reference describes; this has to measure, count and price, so the evidence and numbers live in deterministic code.
7. **Architecture summary** (8 lines + link).
8. **Models, services, libraries** (table): Gemini Live, Gemini Flash, MapAnything/VGGT (+ licence of the checkpoint used), OpenCV, Open Library, Google Books, SerpApi, eBay Browse, Frankfurter, Modal.
9. **AI coding tools used**: Codex (primary), Claude (planning docs), and how they were used (plans approved by me, every diff reviewed).
10. **Assumptions** (from `01` §9).
11. **Cost per sweep & latency per stage** (from telemetry).
12. **Known limitations** (honest; e.g. tall ceilings, glass-door cabinets, foreign-script spines, no local Indian used market → converted).
13. **Deliverable links.**

## 2. Architecture note template (one page)

```
# ShelfClaim — Architecture (1 page)

[Mermaid diagram: Phone (voice ch. / capture ch.) → Server (Live bridge, Capture monitor) → Stages S1…S10 → Packet]

Which model does what
| Job | Model | Why it can't invent numbers |
| Conversation & sweep direction | Gemini Live (<id>) | states numbers only from tool results |
| Detection (boxes) | Gemini Flash (<id>) | outputs boxes only |
| Spine transcription | Gemini Flash | copies visible text; identity decided by catalogue match |
| 3D geometry | MapAnything on Modal GPU (VGGT fallback) | depth/poses; scale re-anchored to printed markers |
| Everything numeric | Python (OpenCV/NumPy/Shapely) | deterministic, unit-tested |

Where metric scale comes from
ArUco cards (100.0 mm) → corner depth back-projection → scale per detection; fused by weighted median with the model's metric scale (+ user-stated dims). Demo sweep: <n> marker detections, disagreement <x>%. Spine dims: marker-plane homography when a card shares the shelf, else reconstruction depth.

Where prices come from
New: SerpApi Google Shopping (gl=<cc>), physical-only, title-matched, IQR-trimmed median. Used: eBay Browse (<marketplace>), USED condition, median; converted with Frankfurter (ECB) when cross-market. Raw responses saved per line. Appraisal rules (signed/first/rare/old/above threshold/art) → not priced. Totals summed in code.
```

## 3. Failure log template (one page)

```
# Failure log — sweep <id> (<date>)

| # | Error (symptom, measured) | Root cause (evidence) | Fix / what I'd change |
|---|---|---|---|
| 1 | e.g. Row B-3 counted 31 vs 24 true (+29%) | Glossy paperbacks: detector split spines at glare highlights; dedup eps too small for thin books (s03 cluster widths, frames f_000412–f_000431) | Fix applied: cannot-link + eps tied to the row's median thickness → B-3 now 25 (+4%); overall count error 7.8% → 3.1% (replay of the same sweep) |
| 2 | ... | ... | ... |
| 3 | ... | ... | ... |

Measured fix (before → after on the same recorded sweep)
| Metric | Before | After |

Cost per sweep
| Provider | Units | Cost (USD) |   → Total: $x.xx

Latency per stage (after end_sweep)
| Stage | Seconds |   → Time to packet: xx s

With two more weeks
- Native ARKit/ARCore capture (LiDAR depth + VIO poses) → metric scale without cards
- Spine detector fine-tuned only if per-row split/merge errors stay > 5% (justify with data)
- Local Indian used-book source; edition-level pricing via ISBN when edition evidence exists
- Multi-room merge; condition grading from spine wear feeding used value
```

## 4. Demo video script (≤ 6:00, ONE take, no edits)

Practise twice. Record 2–3 full takes and submit the best *complete* one.

| Time | What happens | What must be visible/audible |
|---|---|---|
| 0:00–0:20 | Phone on the report-free start screen. You: "This is ShelfClaim. One sweep of my library, live." Tap Start | Screen + your voice |
| 0:20–0:45 | Agent greets, confirms India/INR, explains the sweep, asks about cards → `start_sweep` | Agent voice, locale chip, captions |
| 0:45–3:30 | The sweep. **Deliberately trigger 2–3 cues**: pan fast once (→ "slow down"), hold far from the top shelf (→ "step closer"), pass the portrait (→ "original or print?" → you: "it's a print"), say "skip the bottom right shelf, not mine". Then walls, furniture, ceiling, corners | QC pill changing, inventory filling, coverage chips, agent responding in the moment |
| 3:30–3:45 | "I'm done" → agent checks gaps (ideally asks for one) → `end_sweep` | Agent voice |
| 3:45–5:30 | Pipeline progress visible. Agent reads back the summary | Stage list ticking. Summary audio |
| 5:30–6:00 | Open the report on the phone: scroll totals → a book with crop and price links → the review queue | Report |

If processing would push past 6:00, the video fails the brief, so time-to-packet < 2 min matters. If you can't hit it, cut the intro, not the packet.

## 5. Review call prep (60 min: 15 architecture, live test, Q&A)

**15-minute architecture walk-through** (practise with a timer):
1. (1 min) The problem in one sentence, and the three things they test.
2. (3 min) Diagram: two channels → monitor → stages → packet. "Models perceive, code decides."
3. (3 min) Metric scale: cards + reconstruction + fusion + disagreement. Show `s02_geometry.json` from the demo.
4. (3 min) Identification integrity: transcribe ≠ identify, calibration plot, the confidently-wrong rate.
5. (3 min) Pricing integrity: providers, filters, conversion, appraisal rules, a click-through from the report to the snapshot.
6. (2 min) Results honestly, including FAILs, plus the unseen-room column and the measured fix.

**Live test on their room:** bring 3 printed cards + tape, a charged phone, the laptop on stable Wi-Fi, the tunnel already running, a Modal container warm-up command ready, `.env` checked. Have a backup: if the live session fails, the capture channel still records; run `replay` on that sweep and show the packet. Say up front: "Expect lower numbers than on my shelf. Here's what I expect to degrade and why."

**Likely questions (prepare 2-sentence answers):**
- Why will your count hold on our shelf? (3D dedup, cannot-link, per-row cross-check, unseen-room result)
- What happens with no cards? (model-metric scale, capped confidence, flagged)
- How do you know a price isn't hallucinated? (provider parser only, snapshot, validator; show the code path)
- Why is this title "identified" at 0.81? (features, calibration, threshold choice)
- How are totals computed? (open `totals.py`)
- What's the 2-minute Live session issue and how did you handle it?
- What did you keep from the reference and why?
- Where does the ceiling height come from? What if it's not filmed?
- Cost per sweep — what dominates? How would you cut it 5×?
- Walk me through `<random file>` line by line. (Run the explain-the-code prompt on every module beforehand.)

## 6. Submission email (reply to the brief's email)

```
Subject: Re: Take-Home Assignment — Library Contents Claim Agent — Arun Kaarthikeyan

Hi <name>,

Submitting the Library Contents Claim Agent take-home.

- Repo (private, shared with <reviewer GitHub handles>): <url>
- Demo video (one take, <m:ss>): <url>
- Claim packet + report + frames from the video's sweep: <repo path> (also attached as zip)
- Ground truth & results vs pass bars: <repo path to results.md / results.xlsx>
- Architecture note (1 page): <path / attached PDF>
- Failure log (1 page): <path / attached PDF>

Headline results on my room (<n> books, <m> items): count error <x>%, title ID <y>% (confidently wrong <z>%), spine dims <a>/20 within 15%, prices <b>/15 within 25%, items <c>% found, floor <d>%, wall <e>%, packet in <t> s after the sweep. Cost ≈ $<cost> per sweep. <One honest sentence on the weakest area.>

Thanks,
Arun
```

## 7. Final submission checklist

- [ ] Repo private, shared with the reviewers. `git log` authored only by you, no AI co-author lines.
- [ ] `.env.example` complete. `git grep -i "api_key\|secret"` shows nothing sensitive. `.env` is not tracked.
- [ ] Fresh-clone test done in < 15 min (prompt R6).
- [ ] README has: kept/changed/threw away, models + tools used, assumptions, results table, cost + latency, limitations.
- [ ] Demo video: one take, ≤ 6:00, agent voice audible, inventory filling live, packet shown.
- [ ] Demo sweep folder committed: `claim_packet.json`, `report.html`, every frame referenced (run the validation gate once more).
- [ ] `claim_packet.json` contains every mandatory field (run the schema test).
- [ ] Ground truth CSVs + results sheet with all pass bars, all shelves, per-shelf breakdown.
- [ ] Second-country table for the same 10 books (`docs/second_country.md`).
- [ ] Architecture note fits one page. Failure log fits one page and has three errors, root causes, a measured fix, cost per sweep, latency per stage.
- [ ] Integrity audit prompt (R5) run, findings fixed.
- [ ] Explain-the-code prompt run on every module. You can explain each file.
- [ ] No people or personal documents in any committed frame.
- [ ] Submitted within 48 h (note the timestamp).
