Non-binding research notes. docs/02–09 and AGENTS.md are the source of truth.

# ShelfClaim product and UI/UX direction

This is the design brief to use when the user authorizes implementation. It
keeps the assignment's core tasks and adds a more deliberate user experience.

## Product promise

Document a home library in one guided walk. Show what the camera captured,
what the system could verify, and what still needs a person to check.

The primary user is a policyholder holding a phone while walking. The secondary
user is an adjuster on a laptop who needs to inspect the evidence behind each
line. The product's job is to make capture feel manageable and the packet feel
auditable.

## Design principles

- **Guide attention, not just record video.** Keep one clear next instruction
  visible and make coverage progress understandable at a glance.
- **Show evidence before confidence.** A user can open a crop/frame and read
  why a line was identified, measured, priced, or sent to review.
- **Never make uncertainty look complete.** Provisional counts, estimates,
  converted prices, and appraisal items have distinct labels.
- **Design for a moving hand.** Camera, mute, and finish controls stay large,
  reachable, and stable while the preview moves.
- **Keep the reviewer oriented.** Selecting a review item opens its evidence
  beside the inventory row and preserves filters and scroll position.
- **Use motion only as feedback.** Animate a completed step or connection
  change; respect reduced-motion settings.

## Proposed visual system

The visual metaphor is a field record made from a library catalogue: ordered,
quiet, and evidence-led. Avoid a generic SaaS dashboard and avoid decorative
book illustrations that compete with the camera or evidence.

| Token | Proposed value | Use |
|---|---|---|
| Deep ink | `#142329` | Capture chrome, headings, high contrast text |
| Paper | `#F5F7F4` | Report background and broad reading surfaces |
| Shelf green | `#286A5B` | Verified/covered states and primary action |
| Brass amber | `#A7651E` | Review-needed and provisional states |
| Signal red | `#A83E3E` | Capture failures and blocking errors |
| Muted slate | `#64747A` | Secondary labels and quiet metadata |

Use a system sans-serif for UI and data tables. Use tabular numerals for
measurements, counts, and prices. If a contrasting display face is used, keep
it to the product title and report section titles, not dense rows. The capture
screen should stay dark around the camera; the report should use a light,
print-friendly surface.

## Primary user journey

```text
Prepare -> Sweep -> Check coverage -> Finish -> Review packet
```

### Prepare

Show three short readiness checks: secure connection and permissions, scale
cards, and a privacy reminder. Provide a direct recovery instruction when a
check fails. Let the user choose country/currency before recording starts.

### Sweep

The camera is the largest visual area. Keep the latest agent instruction,
capture-quality state, and coverage compact but visible. The live inventory is
a bottom sheet that can expand; its counts are explicitly marked provisional.

```text
+----------------------------------+
| India / INR        01:24   Live  |
|                                  |
|          Camera view             |
|  [focus/blur state] [speed]      |
|                                  |
| Next: move closer to top shelf   |
| Shelf rows  4 covered / 1 to see |
| Room       corners 2/4, ceiling  |
|----------------------------------|
| Provisional: 38 books, 4 items   |
| [Mute]                  [Finish] |
+----------------------------------+
```

Show the QC state in both words and iconography. Do not rely on color alone.
Do not cover the object the camera is trying to capture with overlays.

### Finish and processing

After the user ends the sweep, keep them informed with human-readable stages
such as "Checking shelf coverage", "Matching readable spines", "Looking up
local prices", and "Preparing your report". Show a failure as a review item,
not as a fabricated success state. Provide a clear way to open the packet when
ready.

### Review packet

For desktop, use a compact summary header, a review queue, and an evidence
inspector. Keep the currently selected book or item visible while its evidence
is inspected. The report should print cleanly and work at phone widths.

```text
+--------------------+-------------------------------------+
| Review queue       | Selected line                       |
| Needs identity     | Title / category + status            |
| Needs price        | Best crop + full frame + bbox        |
| Appraisal          | Raw text / catalogue candidates      |
| Converted price    | Source link + date + FX evidence     |
|                    | Measurement method + alternate view  |
+--------------------+-------------------------------------+
```

Keep the original assignment's report sections: totals, room geometry, books,
other items, review queue, methods/assumptions, and telemetry. Add an evidence
drawer/expanded row so this hierarchy is usable without flattening everything
into one very wide table.

## Accessibility and privacy

- Minimum 44 px touch targets, visible keyboard focus, semantic headings,
  labels on controls, and keyboard-operable report filters.
- Ensure text and status indicators meet WCAG AA contrast; include text labels
  and icons in addition to color.
- Respect `prefers-reduced-motion`; do not use sound as the only alert.
- Before capture, say what is saved and remind the user to keep people and
  personal documents out of frame. Explain face blurring without implying it
  can identify every face.
- On an unsupported browser or denied permission, show a plain next step and a
  retry action. Do not enter a silent or stuck capture state.

## UI/UX quality gates

1. A first-time phone user can tell whether capture is ready and what to do
   next without reading setup documentation.
2. During a sweep, the last spoken instruction, current capture quality, and
   missing coverage are visible without blocking the camera.
3. Every provisional value is labeled as provisional; final values link to
   their evidence or show why they are blank.
4. An adjuster can reach the evidence for a flagged line directly from the
   review queue and return without losing place.
5. The capture view and report remain legible at narrow widths and in print.

