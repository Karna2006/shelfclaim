# Failure log

Observed failures and fixes for the current build. Missing measurements remain explicit TODOs.

## Three largest errors

| Area | Symptom and evidence | Root cause | Fix and measured result |
|---|---|---|---|
| Voice turns | Phone notes: 3 of 4 user turns became forced finals after 8 s; replies took 21–78 s. | Speaker TTS was heard by recognition, keeping interim speech active and mixing or delaying the next user turn; cues could pre-empt replies. | Promote stable interim text after 1.2 s, strip recent spoken phrases, prioritize user turns over cues, route common intents deterministically, and use earphones mode. `agent-soak` returned replies for 20/20 scripted turns. `PROGRESS.md` records 0 fallback, p50 39 ms, and interpolated p95 1,339 ms for its 21 replies including greeting. |
| Gemini quota and availability | Gemini calls returned 500/503/429 errors; fallback paths ran and Gemini transcription could be empty. | Transient service errors and exhausted free-tier quota. | Agent calls retry and move through the configured model chain. Local RapidOCR with ONNX Runtime is the default spine reader, so OCR no longer depends on Gemini quota. Before/after transcription accuracy: **TODO: fill from final run**. |
| Identification | Before: 0 of 11 books identified. Adjacent spine text was merged, and Open Library could not connect from this network. | S6 scored merged text as one title; neighboring author text diluted the title match. The catalogue request also failed before scoring. | OCR lines are assigned to boxes by position; S6 queries each line and adjacent pair, with strict title/author rules. Google Books is now the primary metadata/ISBN catalogue, with Open Library as an enabled fallback. After S06–S10 replay: 4 of 11 identified; no title-accuracy result without ground truth. |

## Cost and stage latency

Cost per sweep: **TODO: fill from telemetry after pricing rates are set**. The S06–S10 replay recorded S06 65.652798 s, S07 30.327691 s, S08 0.024337 s, S09 0.003086 s, and S10 0.091901 s; S01–S05 and full capture-to-packet latency remain **TODO: fill from a full-run telemetry record**. Provider rates in `config/pricing_rates.yaml` are TODO; do not estimate a cost from model or search counts.

## With two more weeks

- Add MapAnything 3D reconstruction for room area and stronger spatial deduplication.
- Evaluate a dedicated spine detector; fine-tune only if measured split/merge errors justify it.
- Add Gemini Live or native audio only with a funded billing path.
- Wire `end_sweep` to finalization and spoken packet summary.
- Add a checker agent and evaluate against 60+ books with complete ground truth.
