# Decisions

- Frame review for the 2026-11-26 shelf detection bake-off uses the existing S1 selection rule: highest blur score per 1.5-second interval, then near-duplicate rejection; sweep `sw_20261126_225839_2007` is the newest capture. Its three sharpest clear shelf views are seq 57 (blur 429.1), 62 (405.0), and 90 (386.6); global sharpness leaders show only a desk and monitors.

- Stage A emits only quality cues from saved frame metrics until S1 provides row, text-size, occlusion, and item evidence.
- Vision detection is post-capture in this implementation; the live async queue and provisional inventory push are deferred because the authorized model replay returned HTTP 503.
- The per-run live model budget was exhausted by the failed S1 replay, so remaining pipeline verification uses local fixtures and avoids further model calls.
- Stage C makes zero SerpAPI calls when the S6 catalogue artifact is missing; the latest sweep has no S6 artifact, so repricing is intentionally blocked.
- Stages S9 and S10 keep room measurements null and add a room-not-measured review entry while geometry is disabled.
- Deliverable reference notes use the non-binding product direction in docs/notes/PRODUCT_DIRECTION.md and the kept/changed/threw-away outline in docs/12_DELIVERABLES_AND_REVIEW.md; user-supplied replacement notes were not present.
- README and failure-log cost/latency fields remain explicitly unmeasured because pricing rates are TODO and no successful full pipeline telemetry exists.
