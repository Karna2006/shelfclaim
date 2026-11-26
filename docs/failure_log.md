# Failure log

This run did not produce a packet. The recorded evaluation is `BLOCKED`; the failures below describe observed blockers, not inferred model accuracy.

## Three largest observed blockers

1. **Vision replay unavailable.** The single authorized S1 replay against `sw_20261126_044135_a4bd` returned Google HTTP 503 `UNAVAILABLE` (high demand). Root cause: upstream service availability. Before/after quality is not measurable because no S1 artifact was created. Do not spend another model call until the quota/window allows a retry.
2. **Downstream evidence absent.** Both target sweeps lack `s01_detections.json`; `debug-boxes` stops with “Run replay --until s01 first”, and `reprice --limit 10` stops before the provider call because S6 is missing. Root cause: stages require grounded upstream detections and catalogue matches. Result: zero SerpAPI searches; no counts, titles, dimensions, or prices were fabricated.
3. **Evaluation has no valid comparison set.** The latest sweep has no `claim_packet.json`, and `eval/ground_truth/count_gt.csv` has no measured `true_count` rows. The evaluator reports all accuracy bars as NOT MEASURED rather than treating missing data as a pass or dropping unmatched shelves.

## Measurements and fixes

The offline capture summary provides the only measured comparison in this run:

| Sweep | Frames | Duration | OK | Blurry | Fast | Dark | Glare / bright | Markers |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `sw_20261126_023206_7f03` | 68 | 42.73 s | 83.8% | 16.2% | 0% | 0% | 0% / 0% | none |
| `sw_20261126_044135_a4bd` | 85 | 52.92 s | 0% | 49.4% | 5.9% | 44.7% | 0% / 0% | none |

No before/after model, count, price, or accuracy fix can be measured from these artifacts. The implementation includes test coverage for deterministic keyframe, box, counting, marker-plane, pricing, and packet logic, but that does not substitute for a successful field replay. The latest local check passed 113 tests.

## Cost and latency

Pricing rates in `config/pricing_rates.yaml` are marked TODO, and there is no successful full-run stage telemetry. Cost per sweep and per-stage latency are **not measured**. The model returned an upstream 503; no cost is inferred from that response. The repricing command made zero SerpAPI searches.

## Next two weeks

- Retry one S1 replay when the vision endpoint is available; save raw detections and debug-box previews for both sweeps.
- Wire the async detection queue and provisional inventory into capture, then validate all monitor cues and voice barge-in on a phone.
- Label ground truth by row, books, items, measured dimensions, and checked prices; re-run evaluation without omitting unmatched lines.
- Complete item brand/material extraction and grounded item pricing; verify evidence snapshots and appraisal handling.
- Generate and validate one complete packet, then record actual stage latency and provider costs after pricing rates are filled from their sources.
- Measure room geometry only if the scope changes from geometry-off and a supported reconstruction/scale path is implemented.
