# START HERE — Library Contents Claim Agent (Cozmo AI take-home)

This folder is your full pre-code kit. Read it in order once, then copy it into your repo and start Codex.

## What's in here

| # | File | What it is | When you use it |
|---|------|-----------|-----------------|
| 00 | `00_START_HERE.md` | This index + the exact setup sequence | First |
| 01 | `01_PROBLEM_BREAKDOWN.md` | The brief in plain words: what's graded, the traps, the approach, what to read first, how to stand out, the 48h timeline, risks | Before anything else. Re-read before the review call |
| 02 | `02_PRD.md` | Product Requirements Document: one-liner, user, MVP features, non-goals, acceptance criteria | Feed to Codex first |
| 03 | `03_TECH_STACK.md` | Exact frameworks, models, APIs, keys, costs, constraints, env vars | Feed to Codex with the PRD |
| 04 | `04_ARCHITECTURE.md` | The pipeline stage by stage: how scale, counting, ID, pricing and room geometry actually work. Also the draft of your 1-page Architecture Note deliverable | Codex reads this before every phase |
| 05 | `05_DATA_SCHEMA.md` | Every data model, including the mandatory `claim_packet.json` contract, internal stage artifacts, folder layout, config files | Codex reads before writing any model |
| 06 | `06_USER_FLOWS.md` | Step-by-step sweep flow, live agent behaviour, voice tools, WebSocket events, the finalize flow | Codex reads before the live agent and UI phases |
| 07 | `07_UI_UX.md` | Layout, screens, components, visual rules | Codex reads before the UI phases |
| 08 | `08_AGENTS.md` | The rulebook. Copy to repo root as **both** `AGENTS.md` (Codex reads this) and `CLAUDE.md` (Claude Code reads this) | Repo root, before the first prompt |
| 09 | `09_PLAN.md` | Build plan: 11 phases, each with deliverables, tests and a "done when" | Phase-by-phase while building |
| 10 | `10_CODEX_PROMPTS.md` | Every prompt to paste into Codex, in order, plus recovery and debugging prompts | While building |
| 11 | `11_GROUND_TRUTH_AND_EVAL.md` | How to collect ground truth, the sheet layout, how each pass bar is computed honestly | Day 1, before tuning anything |
| 12 | `12_DELIVERABLES_AND_REVIEW.md` | README outline, Architecture Note, Failure Log template, demo video script, submission email, review-call prep | Final 8 hours |
| — | `prompts/` | Ready-to-use model prompts: `agent_system.md` (live agent), `detect.md`, `transcribe.md`, `items.md`, `rerank.md` | Copied to `app/prompts/` in Phase 0. Codex uses them as-is |
| — | `templates/` | `.env.example`, `.gitignore`, ground-truth CSV templates, locale configs (`IN.yaml`, `GB.yaml`), `pricing_rates.yaml` | Copied into the repo in Phase 0 |

## The setup sequence (do it exactly in this order)

1. **Read `01_PROBLEM_BREAKDOWN.md` fully** (25 min). Don't skip the traps section.
2. **Run the reference app** (60–90 min, mandatory per the brief). The steps are in `01` §6. Write 5 bullet notes on what you'd keep, change and throw away. These go into your README.
3. **Order your accounts and keys now.** Some take time (eBay developer keyset approval, Modal signup). See `03_TECH_STACK.md` §6.
4. **Print the scale cards** (`scripts/make_markers.py` gets generated in Phase 1, or use any ArUco generator). Print 3 at 100% scale and measure the printed marker with a ruler.
5. **Start ground truth collection in parallel** (`11_GROUND_TRUTH_AND_EVAL.md`). Count books, tape-measure the room, photograph shelves by hand. Do this on Day 1. You can't tune without it.
6. Create the repo:
   ```bash
   mkdir library-claim-agent && cd library-claim-agent
   git init
   KIT=/path/to/library-claim-agent-docs
   mkdir -p docs/planning/prompts app/prompts config/locales eval/ground_truth
   cp $KIT/*.md docs/ && cp $KIT/prompts/*.md docs/planning/prompts/ && cp $KIT/prompts/*.md app/prompts/
   cp docs/planning/08_AGENTS.md AGENTS.md && cp docs/planning/08_AGENTS.md CLAUDE.md
   cp $KIT/templates/.env.example .env.example && cp $KIT/templates/.gitignore .gitignore
   cp -r $KIT/templates/config/* config/ && cp $KIT/templates/ground_truth/*.csv eval/ground_truth/
   git add . && git commit -m "Planning docs: PRD, stack, architecture, schema, flows, plan"
   ```
7. Open Codex in the repo root and paste **Prompt 0** from `10_CODEX_PROMPTS.md` (clarifying questions), then **Prompt 1** (plan check), then build phase by phase.
8. Commit after every phase that passes its tests. Commits are authored by you only, with no AI co-author lines.

## The 6 rules that decide your score

1. **Models perceive, code decides.** A model may read pixels and text. Code computes every count, dimension, area, price and total.
2. **No number without evidence.** Every value points to a saved frame (plus bounding box) or a saved API response (URL, date, raw snapshot).
3. **Blank beats wrong.** Unreadable spine → `unidentified` plus dimensions. Unknown price → empty and excluded. Art or rare → `needs_appraisal`.
4. **The agent must direct the sweep live.** Blur, glare, speed and missed shelves get called out while the user is standing there, driven by measured signals.
5. **Measure honestly on everything.** Report all shelves, including the bad ones, against your own ground truth. Show one measured fix in the failure log.
6. **Don't tune to your room.** They'll test on a room you've never seen. No hardcoded dimensions, catalogues or prices.
