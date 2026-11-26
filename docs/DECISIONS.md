# Decisions

- Local spine OCR uses RapidAI's maintained `rapidocr` package with CPU `onnxruntime`; the requested legacy `rapidocr-onnxruntime` package is being retired and depends on `opencv-python`, which conflicts with the repository's headless contrib OpenCV package.

- Frame review for the 2026-11-26 shelf detection bake-off uses the existing S1 selection rule: highest blur score per 1.5-second interval, then near-duplicate rejection; sweep `sw_20261126_225839_2007` is the newest capture. Its three sharpest clear shelf views are seq 57 (blur 429.1), 62 (405.0), and 90 (386.6); global sharpness leaders show only a desk and monitors.
- Detection bake-off used Gemini 3.5 Flash Lite as the default because it returned usable annotated detections (24 boxes on each selected frame); visual review showed overlaps. The two-pass version returned 25, 29, and 22 boxes with visibly larger merged boxes, so it was not selected. Gemini 3.8 Flash hit free-tier quota/deadline errors; Roboflow was skipped because `ROBOFLOW_API_KEY` was absent from the process environment.
- The validation replay is restricted to reviewed shelf frames 57, 62, and 90 to keep detection calls bounded and avoid desk-only frames. Packet counts therefore represent those saved views and are not a coverage claim for every frame in this sweep.
- The replay produced 11 packet book rows and passed validation. Transcription exhausted the configured Gemini free-tier models, so S5 recorded empty text and S6 left titles unidentified; no SerpAPI searches were made because there were no catalogue-grounded titles. Dimensions stayed null because the reviewed frames had no ArUco markers.

- Stage A emits only quality cues from saved frame metrics until S1 provides row, text-size, occlusion, and item evidence.
- Vision detection is post-capture in this implementation; the live async queue and provisional inventory push are deferred because the authorized model replay returned HTTP 503.
- The per-run live model budget was exhausted by the failed S1 replay, so remaining pipeline verification uses local fixtures and avoids further model calls.
- Stage C makes zero SerpAPI calls when the S6 catalogue artifact is missing; the latest sweep has no S6 artifact, so repricing is intentionally blocked.
- Stages S9 and S10 keep room measurements null and add a room-not-measured review entry while geometry is disabled.
- Deliverable reference notes use the non-binding product direction in docs/notes/PRODUCT_DIRECTION.md and the kept/changed/threw-away outline in docs/12_DELIVERABLES_AND_REVIEW.md; user-supplied replacement notes were not present.
- README and failure-log cost/latency fields remain explicitly unmeasured because pricing rates are TODO and no successful full pipeline telemetry exists.
- Local S5 transcription uses maintained RapidOCR plus ONNX Runtime; its redundant `opencv-python-headless` dependency is excluded so the app retains OpenCV contrib features, and Gemini fallback defaults off while free quota is exhausted.
- Sweep `sw_20261126_225839_2007` replayed from the saved local S5 artifact through S10; merged OCR text was conservatively left unidentified, Google Books returned HTTP 429, and packet validation passed with 11 unidentified books and no prices.
