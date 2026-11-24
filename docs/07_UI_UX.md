# 07 — UI/UX & Design Vibe

UI isn't scored. The brief says not to spend time on visual polish. The UI has exactly three jobs: (1) make the live direction **visible** in the demo video, (2) show the inventory **filling in live**, (3) make the packet **auditable** (every number clickable to evidence). Build it plain, legible and fast. Budget: ≤ 2 hours total.

## 1. Screens

### Screen 1: Sweep (phone, portrait, `/`)

```
┌──────────────────────────────┐
│ IN · INR    ● REC 01:42   ⓘ  │  ← top bar: locale chip, timer, connection dot
├──────────────────────────────┤
│                              │
│        CAMERA PREVIEW        │  ← full-width video, 16:9 crop
│  ┌──────────────┐            │
│  │ QC: ● SHARP  │            │  ← QC pill: SHARP / BLURRY / GLARE / DARK / TOO FAST
│  │ speed ▓▓░░░  │            │  ← speed bar (gyro °/s vs limit)
│  └──────────────┘            │
│  [cards: 0 ✓ 1 ✓ 2 –]        │  ← scale cards seen
├──────────────────────────────┤
│ 🗣 "Step closer, top shelf." │  ← latest agent caption (1 line, large)
├──────────────────────────────┤
│ Coverage  A-1✓ A-2✓ A-3⚠ B-1… │  ← row chips (green/amber/grey/struck=excluded)
│           ceiling ✗ corners 2/4│
├──────────────────────────────┤
│ Inventory (live, provisional) │  ← bottom sheet, scrollable
│ 📚 Books ~47   A:23  B:24     │
│ 🪑 Items 6                    │
│  • Bookcase (wood)            │
│  • Portrait – needs appraisal │
│  • Desk lamp                  │
├──────────────────────────────┤
│  [ Mute ]   [ I'm done ]      │  ← big tap targets (Done = same as saying it)
└──────────────────────────────┘
```

After `end_sweep`: the camera area is replaced by **pipeline progress** (one row per stage with spinner/✓ and elapsed seconds). Then a **Packet ready** card with totals and two buttons: *Open report*, *Download JSON*.

### Screen 2: Report / adjuster view (laptop, `/sweeps/<id>` → `report.html`)

Single scrolling page with a sticky left table of contents:
1. **Header:** sweep id, date, device, duration, country/currency, time to packet, cost per sweep.
2. **Totals cards** (4): books (count / identified / unidentified / appraisal), books value (replacement / used), items value (low–high), excluded lines. Each card has "how computed" tooltip text.
3. **Room:** dimensions table (m and ft), floor/wall/shelved areas (m² and ft²), `scale_method`, confidence, polygon SVG (plus item dots as a stretch goal), method notes.
4. **Books table:** columns: thumb crop | ID | shelf-pos | status chip | title / author (or *"spine unreadable"* + raw text in grey) | H × T cm + method badge | replacement (amount, source link, date, converted badge) | used (amount, source link, condition) | confidence. Filter chips: All / Identified / Unidentified / Needs appraisal / In review. Clicking a row expands it: full frame with the bbox drawn, alternate views, transcription, catalogue link, the price offers used, a raw snapshot link.
5. **Items table:** thumb | category | description | brand/model | W×H×D | status | low–high (source link) | confidence.
6. **Review queue:** grouped by reason code, each line linking to its row.
7. **Methods & assumptions:** scale anchors, price sources, appraisal rules, assumptions list.
8. **Telemetry:** latency per stage (bar list), cost per provider, total.

## 2. Visual style

- **Aesthetic:** utilitarian "instrument panel". Minimal and high-contrast, in the spirit of Linear/Vercel dashboards. No gradients, no shadows beyond 1 px borders, no animations except spinners and the QC pill colour change.
- **Sweep screen:** dark (camera UIs read better dark): background `#0B0B0C`, text `#F5F5F5`, borders `#2A2A2E`.
- **Report:** light: background `#FFFFFF`, text `#111111`, muted `#6B7280`, borders `#E5E7EB`. Prints cleanly to PDF.
- **Status colours** (used consistently everywhere): OK/identified `#16A34A`, warn/review `#D97706`, error/blurry `#DC2626`, appraisal `#7C3AED`, neutral/unidentified `#6B7280`, excluded = strikethrough + `#9CA3AF`.
- **Typography:** system UI font stack (`-apple-system, Segoe UI, Roboto, sans-serif`). Numbers in `font-variant-numeric: tabular-nums`. Agent caption 20 px, body 15 px, tables 13 px.
- **Layout:** sweep screen is a single column, max 480 px wide, safe-area insets. Report max width 1200 px.
- **Money formatting:** `Intl.NumberFormat(locale, {style:"currency", currency})`, so INR shows `₹21,450` and GBP shows `£185.40`.
- **Accessibility:** tap targets ≥ 44 px. Colour is never the only signal (chips include icons/text).

## 3. Components (vanilla JS functions, each in `web/app.js` or small modules)

| Component | Renders from | Updates on |
|---|---|---|
| `TopBar` | locale, timer, connection | `tool_event:set_locale`, ticks |
| `QcPill` + `SpeedBar` | latest `qc` message | every `qc` (throttled to 5/s) |
| `CardsSeen` | `qc.markers` cumulative | `qc` |
| `AgentCaption` | latest agent transcript (final or partial) | `transcript` |
| `CoverageChips` | `inventory.coverage` | `inventory` |
| `InventorySheet` | `inventory.books`, `inventory.items` | `inventory` |
| `PipelineProgress` | `pipeline` events | `pipeline` |
| `PacketCard` | `packet_ready.summary` | `packet_ready` |

## 4. Reference screenshots (optional)

If you want visual targets for Codex, screenshot (a) any camera app with an overlay pill (the stock phone camera "too dark" hint works), and (b) a Linear issue table, and paste them with Prompt 9. Not needed; the ASCII above is enough.

## 5. Demo-video considerations

- The QC pill and the speed bar must be visible in the recording. They're your proof that the agent is directing from measurements.
- Agent captions on screen make the voice legible even if the audio is quiet.
- Keep the inventory sheet at least 30% of the screen height so "fills in live" is obvious.
- Record the phone screen with audio (Android: screen recorder with "media + mic"; iOS: Control Centre screen recording with mic on). After the sweep, show the report on the phone or switch to the laptop **without cutting** (one take). Simplest: open the report on the phone itself.

