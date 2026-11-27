# Decisions

- Local spine OCR uses RapidAI's maintained `rapidocr` package with CPU `onnxruntime`; the requested legacy `rapidocr-onnxruntime` package is being retired and depends on `opencv-python`, which conflicts with the repository's headless contrib OpenCV package.

- Frame review for the 2026-11-26 shelf detection bake-off uses the existing S1 selection rule: highest blur score per 1.5-second interval, then near-duplicate rejection; sweep `sw_20261126_225839_2007` is the newest capture. Its three sharpest clear shelf views are seq 57 (blur 429.1), 62 (405.0), and 90 (386.6); global sharpness leaders show only a desk and monitors.
- Detection bake-off used Gemini 3.5 Flash Lite as the default because it returned usable annotated detections (24 boxes on each selected frame); visual review showed overlaps. The two-pass version returned 25, 29, and 22 boxes with visibly larger merged boxes, so it was not selected. Gemini 3.8 Flash hit free-tier quota/deadline errors; Roboflow was skipped because `ROBOFLOW_API_KEY` was absent from the process environment.
- The validation replay is restricted to reviewed shelf frames 57, 62, and 90 to keep detection calls bounded and avoid desk-only frames. Packet counts therefore represent those saved views and are not a coverage claim for every frame in this sweep.
- Before the latest catalogue change, a replay produced 11 packet book rows and passed validation. Transcription exhausted the configured Gemini free-tier models, so that run left titles unidentified and made no SerpApi searches. Dimensions stayed null because the reviewed frames had no ArUco markers.

- Stage A emits only quality cues from saved frame metrics until S1 provides row, text-size, occlusion, and item evidence.
- Vision detection is post-capture in this implementation; the live async queue and provisional inventory push are deferred because the authorized model replay returned HTTP 503.
- During earlier pipeline verification, the per-run live vision budget was exhausted by the failed S1 replay; later catalogue and price checks were bounded separately.
- At the earlier pricing check, S6 was missing, so repricing stopped before provider construction and used zero SerpApi searches. The later S06–S10 replay and its search count are recorded below.
- Stages S9 and S10 keep room measurements null and add a room-not-measured review entry while geometry is disabled.
- Deliverable reference notes use the non-binding product direction in docs/planning/notes/PRODUCT_DIRECTION.md and the kept/changed/threw-away outline in docs/planning/12_DELIVERABLES_AND_REVIEW.md; user-supplied replacement notes were not present.
- README and failure-log cost/latency fields remain explicitly unmeasured because pricing rates are TODO and no successful full pipeline telemetry exists.
- Local S5 transcription uses maintained RapidOCR plus ONNX Runtime; its redundant `opencv-python-headless` dependency is excluded so the app retains OpenCV contrib features, and Gemini fallback defaults off while free quota is exhausted.
- Sweep `sw_20261126_225839_2007` replayed from the saved local S5 artifact through S10; merged OCR text was conservatively left unidentified, Google Books returned HTTP 429, and packet validation passed with 11 unidentified books and no prices.
- Open Library was unreachable from this network, so Google Books is the primary identification catalogue; Open Library remains an enabled fallback. Google Books contributes catalogue metadata and ISBNs only: its eBook `saleInfo` is never a physical-book price source.
- Catalogue calls use a 5-second connection timeout and at most one retry. A provider that fails to connect is skipped for the rest of that run to avoid repeating the same network failure for each OCR line.
- After this catalogue change, the S06–S10 replay of `sw_20261126_225839_2007` passed validation with 4 of 11 books identified, 4 converted used offers, and 8 SerpApi searches. Recorded `time_to_packet_s` is 96.118319 for this partial replay; full-run cost remains unavailable.
