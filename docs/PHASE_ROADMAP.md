# ShelfClaim phase roadmap

Implementation follows `BUILD_PROMPTS.md` in its supplied order. Work one
phase at a time. Each phase starts with its PLAN prompt, gets reviewed, then
waits for the user's GO before code changes. After implementation, use its
REVIEW prompt and keep the user responsible for commits.

## Phase order and organization

| Order | Prompt / phase | Main outcome | UI/UX checkpoint |
|---|---|---|---|
| 1 | Prompt 0: orientation | Confirm constraints, answer blocking questions, assess risks | Confirm phone and adjuster audiences, privacy expectations, and visual priorities |
| 2 | Prompt 1: plan check | Map every phase to files, public APIs, tests, keys, and session boundaries | Ensure capture and report work are explicitly represented |
| 3 | Phase 0: skeleton and contract | Runnable project structure, schema, totals, config, CLI, health route | Establish tokens and UI states before screen implementation |
| 4 | Phase 1: capture channel | Mobile readiness, camera capture, evidence storage, QC and coverage UI | Build the camera-first flow and test permission, connection, and empty/error states |
| 5 | Phase 2: live agent | Audio bridge, tools, captions, session resumption | Keep captions and live state visible without covering the camera |
| 6 | Phase 3: capture monitor | Cue generation, rate limits, coverage gaps | Make cue severity and next action legible and accessible |
| 7 | Phase 4: detection and streaming | Stage artifacts, provisional inventory, pipeline orchestration | Label inventory as provisional and show how it changes |
| 8 | Phase 5: geometry | Scale, deduplication, dimensions, room reconstruction | Show method, anchors, disagreement, and missing geometry evidence |
| 9 | Phase 6: identity | Spine transcription and catalogue matching | Separate raw text, identity candidates, accepted identity, and unknown |
| 10 | Phase 7: pricing | New/used sources, conversion, appraisal rules | Display source, date, condition, conversion, and blank-price states clearly |
| 11 | Phase 8: items and room | Non-book inventory and room model | Keep artwork/appraisal distinct; communicate room coverage and uncertainty |
| 12 | Phase 9: packet and report | Validation, review queue, report, readback | Complete the evidence inspector, responsive report, and print layout |
| 13 | Phase 10: evaluation | Ground-truth metrics, calibration, measured fix | Make failures and confidence calibration visible; do not hide weak shelves |
| 14 | Phase 11: deliverables | README, architecture, failure log, demo | One-take demo must show capture cues and packet evidence, not just the happy path |

## Working rules

- Preserve the supplied assignment docs as the requirements baseline. Add
  researched requirements through the PRD and UI/UX addenda rather than
  silently deleting assignment criteria.
- Keep the standalone `PRD.md` and `BUILD_PROMPTS.md` as quick references.
  `docs/02_PRD.md` and `docs/10_CODEX_PROMPTS.md` remain the phase-linked
  copies used by the prompt playbook.
- Keep implementation sequential in one working tree. A second simultaneous
  coding session can overwrite files or produce incompatible assumptions.
- Keep one terminal open if that is convenient, but start a clean Codex
  session for each phase as the playbook requests. A new terminal is not
  needed just to create a fresh session.
- Use multiple sessions at once only for independent read-only research or
  review. Parallel code changes should use separate Git worktrees and be
  merged deliberately; avoid them for this short, tightly coupled project.
- In every phase, keep numeric outputs deterministic, preserve evidence
  provenance, and route missing evidence to review.
- UI/UX is a product quality goal for this project even though the original
  assignment rubric emphasizes measurement and integrity. Improve clarity and
  accessibility without letting visual polish displace capture, measurement,
  pricing integrity, or evaluation.

## Important technical gate before Phase 5 implementation

The geometry prompt requires checking actual reconstruction APIs and checkpoint
licenses. Use a commercially suitable checkpoint only if the assignment's use
case and access terms permit it. Keep code and checkpoint licensing separate
in the architecture note. If model access is unavailable, continue with the
documented fallback and mark geometry unknown or lower confidence rather than
claiming unsupported measurements.

