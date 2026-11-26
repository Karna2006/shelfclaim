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

Latest `.\\tasks.ps1 check`: passed, 113 tests. No git commits or pushes were made. Integrity rules applied: model calls do not create packet counts/prices/dimensions/totals; unknown values remain null/empty; prices require parsed provider evidence and snapshots; identities require catalogue matches; room measurements remain unknown with 3D disabled; frame references are validated.
