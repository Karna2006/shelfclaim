# Autonomous run progress

## Stage A — capture monitor and voice barge-in

**Partial.** Implemented rolling capture-quality cues for TOO_FAST, LOW_LIGHT, BLURRY, and GLARE, with priority, per-type/global cooldowns, metrics logging, and speaking-state suppression. Added configurable voice barge-in; accepted non-echo finals interrupt TTS. Detection-dependent cues (OCCLUDED, TOO_FAR, ROW_MISSED, ART_QUESTION, NEED_CEILING/CORNERS, PROGRESS) and live inventory updates remain unavailable until live S1 detection is wired into capture.

Manual test: on a supported phone, start capture, test dim/fast motion, then speak over TTS and verify a genuine utterance interrupts while an echo is dropped. Known issue: user-speaking state is inferred from interim recognition and currently times out after 1.2 seconds.

## Stage B — detection, provisional inventory, and offline book structure

**Partial / externally blocked.** Added keyframe selection, structured Gemini detection, pixel-box conversion, rotated NMS, best-frame row counts, count-disagreement review, marker-plane measurement, rotated/upscaled transcription crops, catalogue matching, item discovery, and replay/debug-boxes commands. Core behavior has fixture tests. The single allowed live replay attempt against `sw_20261126_044135_a4bd` returned Google HTTP 503 `UNAVAILABLE` (high demand), before creating S1. No per-row counts, book identities, dimensions, or debug-box images are therefore available from either sweep. Detection is post-capture only; the requested concurrent live queue and live inventory push are not wired.

Manual recovery: after the vision service is available, run `.venv\\Scripts\\python.exe -m app.cli replay sweeps/sw_20261126_044135_a4bd --until s06`, then run `debug-boxes` and inspect S3–S6 artifacts. This run did not repeat the model call because the one-call replay allowance was already used.

## Stage C — pricing and item valuation

**Partial / no live pricing run.** Added bounded SerpAPI shopping/eBay/Frankfurter provider plumbing, physical-offer/title filters, outlier handling, snapshots, appraisal paths, second-market currency support, and item pricing rules. No search was made: the latest sweep has no S6 catalogue matches. `reprice --limit 10` stopped before provider construction with “S6 identification artifact is missing”; SerpAPI searches used: 0. Item detections are provisional and still need an end-to-end brand/material identification and pricing stage.

Manual recovery: after S6 exists, run `.venv\\Scripts\\python.exe -m app.cli reprice --sweep <sweep> --country GB --limit 10`. Review `s07_book_prices.json` and `evidence/prices/`.

## Stage D — packet, report, telemetry, and evaluation

**Partial / blocked by missing S1.** Added S8/S9 artifacts, S10 packet assembly and validation, report rendering, tool summaries, and evaluation output. `docs/results.md` was generated from the latest sweep and ground-truth directory. It is marked BLOCKED/NOT MEASURED because `claim_packet.json` is absent and `count_gt.csv` has no measured `true_count` rows. No packet/report was generated from the live sweeps. Room dimensions and areas remain null by design with geometry disabled.

Manual recovery: after a successful S1–S9 replay, run `.venv\\Scripts\\python.exe -m app.cli replay <sweep> --until s10`, then `.venv\\Scripts\\python.exe -m app.cli evaluate --sweep <sweep> --gt eval/ground_truth --out docs/results.md`.

## Stage E — documentation

**Done with measured limits stated.** Added README, architecture note, and failure log. Product reference notes are taken from `docs/notes/PRODUCT_DIRECTION.md`; submission results, costs, and latency are not invented. The vision replay’s 503 and missing downstream evidence are recorded as blockers.

## Latest offline QC observations

- `sw_20261126_023206_7f03`: 68 frames, 42.73 s, 1.57 fps; 83.8% OK, 16.2% blurry, 0% fast/glare/dark/bright; no markers seen.
- `sw_20261126_044135_a4bd`: 85 frames, 52.92 s, 1.59 fps; 0% OK, 49.4% blurry, 5.9% fast, 44.7% dark, 0% glare/bright; no markers seen.
- Both `debug-boxes` commands reported “Run replay --until s01 first”; no debug image paths exist.

## Verification

Latest `.\\tasks.ps1 check`: passed, 121 tests. Local commits for Steps 4–6: `8f98694`, `6dd4491`, `3ac7463`; nothing was pushed. Integrity rules applied: model calls do not create packet counts/prices/dimensions/totals; unknown values remain null/empty; prices require parsed provider evidence and snapshots; identities require catalogue matches; room measurements remain unknown with 3D disabled; frame references are validated.

## Steps 4–8 follow-up

**Steps 4–6 done, source sweep is data-limited.** Replayed `sw_20261126_023206_7f03` through S06/S07/S10. It contains no S3 book rows, so no titles or book prices can be audited. S10 validation passes at `sweeps/sw_20261126_023206_7f03/report.html`; totals contain 0 books, 14 appraisal items excluded from totals, and 15 review entries. Latest time-to-packet was 0.232233 s. Commits are listed above.

**Step 7 blocked pending a new phone sweep.** Available folders end at `sw_20261126_044135_a4bd`; there is no sweep captured after the requested marker-card room setup. The 044135 sweep also has no S1 artifact because its vision call previously returned HTTP 503. Do not claim measured dimensions until a new sweep and marker-bearing frames exist.

**Step 8 partial.** Unit tests verify monitor quality-cue selection/throttling, cue delivery/logging, echo suppression, and reading provisional counts from an existing S03 artifact. Replay through S10 passed. The saved 023206 S1 artifact has no `book_spine`, `shelf_unit`, or `shelf_board` detections and no artwork category. Code inspection found three live gaps: no S1 worker sends `inventory` messages during capture; art detections do not trigger an `ART_QUESTION` cue; `end_sweep` stops capture but does not start finalization or speak `get_packet_summary`. The only verified phone cue path is deterministic quality cues (fast, low light, blur, glare). The packet summary tool returns data when asked, but automatic spoken readback is not wired.

Manual phone verification of the currently wired path: open the served HTTPS app in Chrome, tap Start and allow camera/microphone, pan quickly for over a second to trigger TOO_FAST, then hold steady in dim light to trigger the low-light cue. Speak during a cue to confirm the monitor suppresses speech-overlapping cues. Inventory fill-in, original/print question, and final packet readback cannot pass until the three live gaps above are implemented. After the room is prepared, capture a fresh sweep with marker cards before attempting Step 7 dimensions.

## Phone conversation reliability incident — sw_20261126_212234_8e11

**Diagnosis:** 2 user transcripts arrived; 1 received a normal response and 1 ended in ServerError 500 INTERNAL. echo_dropped events: 0. Missed transcript events: 0 observed; this older sweep predates client speech-event logging, so the server logs cannot prove whether any attempted utterance was lost. Slow replies (>4 s): 2, about 9.5 s and 19.9 s from transcript timestamps. The failed hi request reconstructs to 5 history messages, 2 user turns, 0 image parts / 0 image bytes, 7 declared tools, and no function calls. Gemini counted 1,537 prompt tokens for the reconstructed text-only request; the original error response itself contained no usage metadata.

The four live reproduction variants all succeeded: reconstructed request as-is; without images; with only the current 28,180-byte image (Gemini counted 2,649 prompt tokens); and last-six-turn history (same as-is because only two turns existed). This points to a transient provider 500, not an image or history-size trigger.

**Fixes committed:** 484b3a2 transient model retry/fallback, one-current-turn image and bounded history, deterministic intent routing and request telemetry; a665ffc delayed-turn filler, interim force-finalization and client speech diagnostics; cfadb94 20-turn production AgentLoop soak CLI.

**Verification:** .\\tasks.ps1 check passed, 129 tests. agent-soak --turns 20 --with-frames sweeps/sw_20261126_023206_7f03: 100% successful replies (21 including greeting), 0 fallback, p50 39 ms, interpolated p95 1,339 ms. gemini-3.1-flash-lite served the one model turn; the other turns were handled by the scripted agent or intent router. Source sweep unchanged.
