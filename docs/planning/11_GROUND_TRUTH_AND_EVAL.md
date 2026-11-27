# 11 — Ground Truth & Evaluation (honest numbers or nothing)

Measured accuracy is 30% of the score, and it's only credible if your ground truth (GT) was collected **before tuning** and covers **every shelf**. Do part 1 on Day 1 while Codex builds Phases 0–3.

## 1. Choosing the space (brief minimums + our safety margin)

| Brief minimum | Aim for |
|---|---|
| ≥ 60 books | 70–120 books (statistics get noisy below 60; above 150 the sweep gets long) |
| ≥ 2 shelving units | 2–3 units, ideally different heights or brands |
| ≥ 8 non-book items | 10–14 items across categories, including ≥ 1 framed art/portrait, 1 lamp, 1 rug, 1 electronics item, 1 appliance (coffee machine/kettle) |
| 1 enclosed room | A room with 4 walls you can tape-measure. Avoid open-plan if you can |

Include some realistic difficulty on purpose: a few books lying flat or stacked, a couple of thin books, at least one shelf a bit high. Don't stage an artificially easy room. They'll test on a messy one.

**Privacy:** no people, no documents with personal data, no family photos with faces visible (turn them around or count them as framed art with the face side away). Permission is needed for any space that isn't yours.

## 2. Collection protocol (part 1: Day 1, ≈ 2 hours)

Tools: tape measure (5 m), a ruler or calliper for spines, phone camera, a spreadsheet, masking tape + marker pen.

1. **Label units and rows** physically with small masking-tape tags: units `A`, `B`, `C` left to right as you enter; rows `1` from the top. (Remove the tags before the demo sweep, or keep them small. Either way, the system never reads them as instructions.)
2. **Count truth (`count_gt.csv`):** count every book per row twice, recounting if the two counts differ. Include flat or stacked books in the row they sit on.
3. **Titles (`books_gt.csv`):** for every book, left to right per row, record position, title/author/publisher **as printed on the spine** (that defines "human-legible"). Mark `legible=y` only if a person standing at a normal sweep distance (≈ 1 m) could read the title from the spine without touching the book. If you had to lean in or tilt your head a lot, mark `n`. Be strict and honest. This set is the denominator for the 70% bar.
4. **Spine dimensions:** choose 20 books **before** looking at any system output: every 4th book or so, spanning units, rows and sizes, including ≥ 3 thin and ≥ 2 large. Measure height and thickness of the spine with a ruler to 1 mm. Mark `measured=y`.
5. **Room (`room_gt.csv`):** length and width at floor level (wall to wall, twice, average), ceiling height (twice, in different spots), every wall segment for non-rectangular rooms, door and window widths/heights (optional, for net wall area). Compute floor area and gross wall area (perimeter × height) in the sheet. Measure each shelving unit (W × H × D) to compute shelved wall area = Σ W × H of units against walls.
6. **Items (`items_gt.csv`):** every non-book object you'd claim: category (from the taxonomy), description, approximate W×H×D, brand/model if visible.
7. **Photos:** photograph each row straight-on as your own reference. Store them in `eval/ground_truth/photos/` (not used by the system).

## 3. Collection protocol (part 2: after Phase 7 works, ≈ 1 hour)

8. **Prices (`prices_gt.csv`):** choose 15 identified books **before looking at the system's prices**: a spread of popular and niche, paperback and hardcover. For each, search the **same source types** the system uses:
   - New: Google Shopping in your country (google.co.in → Shopping tab), searching `"<title>" <author> book`. Take the median of the first few matching physical-book offers, as the system does. Record merchant, URL, price, date.
   - Used: eBay (the marketplace the system uses for your locale), filter Used, books category, the median of the first ~10 matching listings. Record the URL of the search, the price, the date.
   The brief says "same source type": your hand check uses the same kind of source, but checked by a human. Write down the procedure in the sheet header.

## 4. Metric definitions (exactly what `cli evaluate` computes)

Let GT books = G, predicted books = P.

| Metric | Definition | Pass |
|---|---|---|
| **Book count error** | `|#P_counted − #G| / #G`, where P_counted excludes nothing (owned-ness doesn't change the physical count). Also report per row: `Σ_rows |p_r − g_r| / #G` (stricter, shows compensating errors) | ≤ 5% |
| **Title ID accuracy** | Over GT books with `legible=y`: matched P book has `status=identified` and normalised title similarity ≥ 90 to GT title (plus author surname match if GT has an author). `accuracy = correct / #legible` | ≥ 70% |
| **Confidently wrong** | Over all P books with `status=identified` and `id_confidence ≥ tau_accept`: title doesn't match its GT book. `rate = wrong / #legible` (the brief's denominator is legible spines; also report `/ #identified`) | ≤ 3% |
| **Spine dims** | For the 20 measured books: `|pred − true| / true` for height and thickness separately. Report mean, median, and the count within 15%. Pass if **≥ 17 of 20** height errors and **≥ 17 of 20** thickness errors are ≤ 15% (state your interpretation; also show the mean) | within 15% |
| **Book prices** | For the 15 checked: `|pred − gt| / gt` for replacement and used separately. Pass if the median error ≤ 25% and ≥ 12/15 within 25% (state the interpretation) | within 25% |
| **Non-book items** | Recall = matched GT items / #GT items. Category accuracy among matched | ≥ 80% found with correct category |
| **Floor area** | `|pred − true| / true` | ≤ 10% |
| **Wall area** | gross vs gross | ≤ 15% |
| **Time to packet** | `packet_written_at − end_sweep_at` from telemetry | < 5 min (target < 2) |

**Matching books P↔G:** for each GT book, candidates are P books in the same unit-row within ±2 positions. Pick the best by title similarity (if identified), else by position. Unmatched GT = missed; unmatched P = extra (both count against the count and accuracy). Unit/row naming may differ (your A might be the system's B), so build a mapping by majority vote of matched titles, and log it.

**No cherry-picking:** the evaluator runs on *all* rows. The report shows the per-shelf breakdown, including rows where the system did badly, plus a "what went wrong on this row" note for each failing row.

## 5. Calibration (why your confidence numbers mean something)

- Features from S6 plus correctness from GT (legible spines) → logistic regression → `id_confidence`.
- Choose `tau_accept` = the smallest threshold where confidently-wrong ≤ 2% on your data (a 1-point safety margin under the 3% bar), and report the Wilson 95% interval because n is small.
- Plot: x = confidence bin, y = empirical accuracy, plus bar counts. Save it to `docs/calibration.png`. Mention in the README that it was calibrated on your room and *expected to degrade on unseen rooms*, which is why the margin exists.

## 6. The unseen-room rehearsal (do this; it's the review-call simulation)

Before submitting, sweep a space you never tuned on (a friend's shelf, a hostel common room, a bookshop corner with permission). Collect a light GT: count + 30 legible titles + floor tape. Run the system **without changing any threshold**. Add a column "unseen room" to `results.md`. If it collapses, you've found your #1 failure-log item while you still have time to fix it, and you can tell the reviewers you anticipated their test.

## 7. Results sheet layout (deliverable #4)

`eval/results.xlsx` (or `docs/results.md` + CSVs), tabs:
1. `summary`: each pass bar: target, our value, PASS/FAIL, n, notes.
2. `books`: GT rows with matched prediction columns side by side (title GT | title pred | status | conf | correct?).
3. `dims_20`: true vs pred height/thickness, error %, method used.
4. `prices_15`: GT new/used vs pred new/used, error %, both URLs.
5. `items`: GT vs matched pred, category correct?
6. `room`: tape vs system for every measure.
7. `per_shelf`: count and ID accuracy per row.
8. `telemetry`: latency per stage, cost per sweep.
9. `unseen_room` (if done).
