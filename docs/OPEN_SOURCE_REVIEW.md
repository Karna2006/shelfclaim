# Open-source and product landscape review

Research date: 2026-11-25

This is product and implementation research based on public repository pages,
READMEs, selected source files, and vendor product pages. Projects were not
installed or benchmarked locally. License notes are a screening aid, not legal
advice; check the exact code, model, and dataset terms again before copying or
shipping any dependency.

## What the landscape says

The assignment's exact combination remains unusual in the open-source projects
reviewed: one live voice-directed walk that counts and measures individual book
spines, values contents with retrievable market evidence, estimates room
surfaces, and emits a validated claim packet. There are strong component-level
references. There is also a close commercial comparison: Scanlily markets
video walk-throughs with narration, item extraction, live listing-based
replacement values, and claims reports. So avoid claiming that no product does
video inventory or sourced insurance pricing. ShelfClaim's defensible
assignment-specific distinction is the book-by-book geometry and deduplication,
catalogue-gated identities, explicit scale/measurement evidence, and a
machine-validated packet. This is a positioning hypothesis to demonstrate in
the take-home, not a broad market-exclusivity claim.

## Book capture, reading, and matching

| Reference | What was reviewed | Useful pattern | Boundary / caution |
|---|---|---|---|
| [cv-book-svg](https://github.com/capjamesg/cv-book-svg) | README and `grounded.py`; MIT; repository archived in 2026 | Segment each spine, rotate/crop it, then read visible text. Its README names missed thin books and misidentifications as limitations; its video dedup is explicitly work in progress. | Its path asks a vision model to supply title/author and takes a first catalogue result. Use it as a segmentation/crop baseline, not as ShelfClaim's identity authority. Keep the transcription → catalogue candidates → thresholded acceptance boundary. |
| [open-shelves](https://github.com/capjamesg/open-shelves) | Project README and linked Roboflow dataset | A candidate book-spine dataset/model to compare against general detection. | Dataset page is CC BY-NC-SA 4.0. Do not use its data or weights in a commercial-use path unless the terms are reviewed and permit the intended use. |
| [bookshelf-scanner](https://github.com/suxrobGM/bookshelf-scanner) | README; MIT | YOLO spine segmentation followed by crop/rotation and Moondream2 text reading; useful reference for per-spine image preparation. It also streams results to a frontend. | Its CUDA/model setup may be too heavy for this take-home. Reuse ideas, not its model-dependent identity result. |
| [Library Dataset](https://github.com/llabres/library-dataset) and [paper](https://arxiv.org/abs/2407.19812) | Dataset repo and paper abstract; repo code marked MIT | Evaluation separates catalogue matching from the harder detection-plus-matching problem and uses annotated real library shelves. This is a good way to reason about S6 and evaluation design. | Verify the dataset and annotation terms separately before using the data; an MIT code license does not automatically license all data. |
| [Bookshelf Reader API](https://github.com/LakshyaKhatri/Bookshelf-Reader-API) | Public repository | Historical reference for detecting and reading spines. | Treat older Hough/OCR systems as baselines, not a dependency or expected performance target. |
| [Digital Librarian](https://towardsdatascience.com/digital-librarian-using-computer-vision-to-create-a-book-inventory-8e8d1e1aa1e6/) | Public article | Useful historical perspective on the gap between text extraction and reliable book identification. | Avoid repeating its reported accuracy as a benchmark without checking the source data and evaluation method. |

Another useful code reference is [bennetthellman's bookshelf-scanner](https://github.com/bennetthellman/bookshelf-scanner): multi-scale image processing, rotated OCR, catalogue lookup, validation, and deduplication in a staged pipeline. Read its code for approaches only; model-generated titles still need the stricter catalogue acceptance gate defined by the assignment.

## Live voice, camera, and browser audio

| Reference | What to inspect | Useful pattern | Boundary / caution |
|---|---|---|---|
| [Google Cloud plain-JS/Python Live demo](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api/native-audio-websocket-demo-apps/plain-js-python-sdk-demo-app) | `gemini_live.py`, `main.py`, `media-handler.js`, `pcm-processor.js`; Google Gen AI SDK, FastAPI, vanilla JS | Closest architectural match to the planned stack: a server-side Live API wrapper, concurrent send/receive loops, WebSocket media handling, tool use, and browser audio worklet. | It is a demo. Its auth/project setup and session-lifecycle behavior need adaptation; add the assignment-required context compression, resumption, reconnect isolation, and failure handling explicitly. |
| [Gemini Live API web console](https://github.com/google-gemini/live-api-web-console) | React starter, media/audio modules, unified event log; Apache-2.0 | Inspect its audio streaming queue and playback scheduling for continuity, plus its event log as a debugging UX reference. | It is a React starter and may use an older client API in parts. Verify current SDK signatures before borrowing any implementation. |
| [Pipecat Gemini multimodal live demo](https://github.com/pipecat-ai/gemini-multimodal-live-demo) | Archived demo; BSD-2-Clause | Useful comparison if raw WebSocket audio/video transport proves troublesome; WebRTC can be an alternate transport direction. | Archived October 2025. Do not make it the MVP foundation; it brings another framework and deployment choices. |

### Source-reading notes for the Live bridge

The Google Python/JS demo exposes a `GeminiLive` wrapper around the SDK and
runs send-audio, send-video, and receive-response loops together. Its frontend
has separate media and PCM worklet modules, which is a useful boundary for
ShelfClaim. Treat its implementation as a small reference rather than a
production-ready bridge: the assignment specifically requires sliding context
compression, session resumption handles, graceful GoAway handling, mocked
reconnect tests, and a capture socket that remains independent. The Live API
web console is most useful for browser playback queue patterns and observability;
inspect its current API version before adapting code.

## Geometry and scale

| Reference | What it contributes | ShelfClaim implication |
|---|---|---|
| [MapAnything](https://github.com/facebookresearch/map-anything) | Multi-view metric reconstruction; repository documents code/checkpoint options with different terms. | Inspect its current inference example and output conventions before implementing a backend. Track checkpoint licensing separately from source licensing. |
| [VGGT](https://github.com/facebookresearch/vggt) | Feed-forward camera poses, intrinsics, depth, point maps, and tracks. | Its README says the original checkpoint is non-commercial while `VGGT-1B-Commercial` is available under a separate commercial-use path that requires access approval. Do not infer checkpoint rights from code rights. |
| [MASt3R-SLAM](https://github.com/rmurai0610/MASt3R-SLAM) | Real-time monocular SLAM and dense geometry; CVPR 2025 work. | Interesting longer-term alternative for streaming pose, but local CUDA and integration make it too large a dependency for the short take-home. |
| [DeepPerimeter paper](https://arxiv.org/abs/1904.11595) | Posed monocular video to indoor perimeter from planar floor/ceiling and wall observations. | Conceptual reference for S9. Keep geometry coverage-dependent and report uncertainty; the paper's assumptions do not justify filling unseen room boundaries. |
| [levanta](https://github.com/EazyHood/levanta) | Phone video to floor plans/3D and explicit calibration. | Use trusted anchors and show scale provenance; ordinary walking footage may leave sparse floor evidence. |
| [plan3d](https://github.com/apiel/plan3d) | Browser room scanning, landmark map, and user-entered trusted measurement. | A useful capture UX reference for landmark coverage and an explicit scale anchor. |
| [ScanSpace](https://github.com/aabdlwahab/3d-scanner) | iPhone LiDAR/RoomPlan scanning and measurements. | Keep LiDAR optional; the required baseline is ordinary mobile-browser capture. |

## Inventory and insurance products

| Product | What it covers | Useful product lesson | Boundary / caution |
|---|---|---|---|
| [HomeBox](https://github.com/sysadminsmedia/homebox) | Self-hosted home inventory with categories, locations, tags, photos, documents, and value-related fields. | Cross-check the final inventory fields and make locations/evidence understandable. | AGPL-3.0. Do not copy its code into this project without deliberate license review; product-schema inspiration does not require code reuse. |
| [Hot Stuff](https://github.com/PamCatten/hot-stuff) | Offline-first Android home inventory for proof-of-loss; Apache-2.0; archived May 2025. | Insurance language should feel calm, concrete, and useful after a stressful event; offline/privacy choices matter. | Native Android and single-item workflows are not the ShelfClaim capture path. |
| [Kept](https://github.com/keptinventory/kept) | Open-source home inventory, whole-room capture, human confirmation, insurance reporting. | Confirm AI-suggested fields and make the claim report reviewable. | Keep the assignment's local, file-based architecture; do not inherit accounts/database/deployment scope. |
| [Scanlily insurance adjuster workflow](https://www.scanlily.com/en/industries/insurance_adjusters) | Commercial product markets narrated video walk-throughs, AI item extraction, live listing-based RCV with comparable URLs, and claims reports. | This is a close product benchmark for the end-user promise and evidence-linked pricing. Compare the review flow and adjuster report rather than assuming the category lacks video capture. | It is closed-source, so use public product materials for comparison only. Do not make an unsupported claim that ShelfClaim is the only video-to-insurance-inventory product. |

## Patterns to carry into the product

1. **Separate text from identity.** Read visible spine text, normalize it, retrieve catalogue candidates, and accept a title only above a calibrated threshold. Keep unknown books explicitly unknown.
2. **Make capture and evidence the product.** Preflight secure context/permissions, scale cards, and privacy. During the walk, provide one next action, quality state, and coverage gaps. In review, show crop, full frame, transcript, catalogue evidence, dimension method, and price snapshot.
3. **Keep uncertainty field-specific.** Detection, count, identity, dimensions, and price can each have different states. Provisional inventory must not look final.
4. **Make room metrics coverage-aware.** Store anchors and disagreement; leave unobserved dimensions null and route them for review.
5. **Keep price claims auditable.** Preserve provider response, URL, retrieval time, currency and conversion evidence. Never let an LLM fill a missing market price.
6. **Treat performance and licensing as separate checks.** A repository's code license does not automatically cover its pretrained checkpoint or dataset. Record the exact artifact selected.
7. **Design for a phone in motion and a desktop reviewer.** Camera controls need large touch targets and concise prompts; the final packet needs a narrow-screen layout, direct evidence links, keyboard support, and clean printing.

## PRD and positioning updates

The existing PRD's success bars and integrity rules remain unchanged. These
additions sharpen what the user sees and how the work is presented:

- Add a preflight gate for secure context, permissions, locale, scale cards,
  privacy guidance, and capture connection.
- Label live counts as provisional and expose separate detection, identity,
  dimensions, and valuation states.
- Show shelf/room coverage and one plain-language next instruction; never
  replace missing observations with defaults.
- Make review entries open the exact crop/full frame and the relevant text,
  catalogue, measurement, user-statement, and price evidence.
- Make the report responsive, accessible, readable on mobile, and print-ready.
- Phrase differentiation accurately: the product's assignment-specific focus is
  auditable book-level count/measurement plus sourced pricing and validated
  evidence, within a voice-guided room walk. Do not claim there are no video
  inventory or live-pricing products; Scanlily publicly markets both.
- Add a README “Prior art” section with one-line lessons, attribution, and the
  components ShelfClaim deliberately does differently. Re-check licenses before
  copying code, model weights, or data.

Non-binding visual research is in
[`notes/PRODUCT_DIRECTION.md`](notes/PRODUCT_DIRECTION.md), and phase
checkpoints are in [`PHASE_ROADMAP.md`](PHASE_ROADMAP.md). The assignment's original PRD remains
available in `library-claim-agent-docs/02_PRD.md`.

## Scope guard

The assignment is broad for a short take-home. Preserve the expected end-to-end
story, but make capture/replay work without optional GPU services. Missing
geometry, model, or price-provider evidence should produce explicit review
states rather than a fabricated success. Defer LiDAR, 3D viewer polish,
accounts, cloud deployment, and optional transport changes until a measured
failure justifies them.
