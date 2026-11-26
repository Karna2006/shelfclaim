# 06 — User Flows, Agent Behaviour & Message Protocol

## 1. Setup flow (before the sweep, one-time per room)

1. Laptop: `uv run python -m app.cli serve` (port 8000) + `tailscale serve --bg 8000` (or a cloudflared tunnel).
2. Place **scale cards**: one ArUco card per shelving unit, at roughly eye level on the shelf face (leaning against books or taped to the upright), plus optionally one on the floor near the centre. Placing cards is setup, not a measuring pass (stated assumption).
3. Keep people and personal documents out of the room.
4. Phone: open the HTTPS URL, then tap **Start**. This user gesture is needed for mic, camera, motion permission and audio playback.

## 2. The sweep flow (the happy path, what the demo video shows)

| # | User | Agent / System | Screen |
|---|---|---|---|
| 1 | Taps **Start** | Camera and motion permissions requested; speech recognition starts from the same tap. `POST /api/sweeps` → sweep_id. Capture and live text WebSockets open for the same sweep ID | Camera preview, "Connecting…" |
| 2 | — | Agent: "Hi, I'll help you document your library for the claim. You're in India and want values in rupees, right?" | Caption of agent speech |
| 3 | "Yes" | Agent calls `set_locale(IN, INR)`. "Great. Walk the room once, slowly, shelf by shelf, then the walls and furniture. I'll tell you if I can't read something. Are the scale cards on the shelves?" | Locale chip "IN · INR" |
| 4 | "Yes, go" | `start_sweep()`: timer starts, GPU warmed, stage workers start. Agent: "Start at the left shelf, top row." | Timer 00:00, QC meter live |
| 5 | Pans shelf A | Capture monitor scores frames. S1 detections stream in. Provisional inventory: "Shelf A: ~23 books" | Inventory list fills in. QC meter green |
| 6 | Pans too fast | Monitor: `TOO_FAST` (gyro 85°/s, 70% blurred). Cue injected → Agent: "Slow down a bit, those were blurry." | QC meter turns red, then green |
| 7 | Holds far from the top shelf | Monitor: `TOO_FAR` (text 11 px) → Agent: "Step closer to the top shelf, I can't read those spines." | "Row A-1: not readable yet" chip |
| 8 | Steps closer | Row A-1 marked covered | Chip turns green |
| 9 | Passes a framed portrait | S1 detects `portrait` → `ART_QUESTION` cue → Agent: "Is that portrait an original or a print?" | Item appears: "Portrait — needs appraisal" |
| 10 | "It's a print" | `record_user_statement(kind=print, target_hint="portrait", text="It's a print")` | Item status → "Print — will price as range" |
| 11 | "Skip the bottom shelf on the right, those are my roommate's" | `record_user_statement(kind=not_mine / exclude_region, target_hint="bottom shelf on the right")`. Agent: "Okay, I'll mark the bottom right shelf as not yours." | Row chip "B-5: excluded" |
| 12 | Continues: walls, desk, lamp, rug, coffee machine | Items detected and deduped. Agent occasionally: "Logged a desk lamp and a rug." (PROGRESS, low priority) | Items list grows |
| 13 | Says "I'm done" | Agent calls `get_sweep_status` → gaps: `ceiling_seen=false`, `corners_seen=2/4`. Agent: "Almost. Tilt up to show the ceiling line, then the two corners behind you." | Coverage checklist highlights the gaps |
| 14 | Shows ceiling + corners | Coverage complete. Agent: "Perfect, that's everything." Calls `end_sweep()` | Timer stops (e.g. 02:51) |
| 15 | — | Finalize: S2 (GPU) ∥ remaining S1/S5 → S3…S10. Agent: "Give me about two minutes to finish identifying and pricing." | Progress bar per stage |
| 16 | — | S10 done → `get_packet_summary` result pushed (`INTERRUPT` scheduling). Agent reads back: "Done. I found 74 books, 55 identified, with a replacement total of about twenty-one thousand rupees. There are 9 other items, and the room is about 13.8 square metres. 23 lines need a human reviewer, including the portrait and two possibly collectible books." | "Packet ready" → buttons: **Open report**, **Download JSON** |
| 17 | Opens report | `report.html`: totals, room, books table with crops, prices with links, review queue | Adjuster view |

Agent readback numbers come **only** from the tool result (code-computed). The prompt forbids paraphrasing them into different numbers. "About" plus rounding is allowed.

## 3. Alternate and edge flows

| Situation | Behaviour |
|---|---|
| User doesn't confirm a country / names an unsupported country | Agent asks once more. If unsupported: "I can price in India or the UK right now. Which should I use?" `set_locale` returns `supported:false` for others |
| No scale cards placed | Agent: "No problem, I'll estimate scale from the room. Dimensions will be marked lower confidence." `scale_method` reflects this. Room confidence ≤ 0.5. Review entry |
| Glare on glossy spines | `GLARE` cue: "There's glare. Tilt the phone slightly down." |
| Too dark or blur under dim light while steady | `TOO_DARK`: "It's a bit dark. Can you turn on a light?" The `low_light_blur` QC verdict is used when blur is below threshold, gyro is below `speed_max_dps`, and exposure is below `low_light_exposure_max`. |
| User walks past a shelf unit without covering all rows | `ROW_MISSED` cue when they move to the next unit: "Go back to the shelf on your left, the bottom row was skipped." (re-capture within the same pass is allowed) |
| User interrupts the agent mid-sentence | Barge-in (`START_OF_ACTIVITY_INTERRUPTS`). The agent stops and listens |
| "That's a first edition" while pointing at a book | `record_user_statement(kind=first_edition, target_hint="this book", …)` resolved via the frame at that time → the book becomes `needs_appraisal` |
| "Those aren't mine" (a region) | `exclude_region` → lines kept in the packet with `excluded_reason`, removed from totals |
| User asks "how much is my library worth?" during the sweep | Agent: "I'll have sourced prices when we finish. I don't guess values." |
| Live session GoAway / drop | Server reconnects with the resumption handle. The capture WebSocket continues. If resume fails: a new session with a summary of the state so far ("We're 1:40 into the sweep, shelves A–B done") as the first client content. Logged as `session_resumed` |
| Capture WebSocket drops | Client reconnects with exponential backoff and buffers ≤ 20 frames. The agent is told "camera link dropped" via a cue |
| Phone camera at 720p only | `device` records it. The monitor's text-px threshold makes the agent ask the user to stand closer more often |
| Pipeline stage fails (API down) | Stage marks affected lines blank + review entries. The packet still builds. The agent says how many lines need review |
| Finalize exceeds 4 min | The agent says it's still working. The packet builds with whatever is done. Unfinished lines go to review |
| Person walks into frame | Faces are blurred on save. Agent: "Someone's in view, I'll avoid recording them." (prompt rule) |

## 4. Adjuster / reviewer flow

1. Open `/sweeps/<id>` → report.
2. Scan the totals and review queue count.
3. Click any book: the crop opens with the bbox drawn on the full frame, the transcription, catalogue link, dims + method, and price links + raw snapshot JSON.
4. Work the review queue: each entry links to its evidence.
5. Download `claim_packet.json`.

## 5. WebSocket message protocol

### 5.1 `/ws/live/{sweep_id}` (JSON text frames)

Client to server:
| type | fields | notes |
|---|---|---|
| `user_text` | `{type, text, t_ms}` | Final Web Speech result or typed fallback only; server merges finals within 800 ms |
| `live_frame` | `{type, data: base64 jpeg, t_ms}` | Low-resolution JPEG, 768 px maximum long edge and q 0.6 |
| `speech_activity` | `{type, speaking}` | Interim recognition activity used only to suppress spoken cues |
| `speech_event` | `{type, name, detail, t_ms}` | Recognition start/end/restart/error and forced-final diagnostics; no interim transcript text |
| `control` | `{type, action:"stop"}` | Close the live session |

Server to client:
| type | fields |
|---|---|
| `agent_text` | `{type, text, t_ms}` | Browser speech synthesis reads the reply |
| `cue` | `{type, text, priority}` | Direct urgent speech; appended to assistant history and transcript |
| `state` | `{type, state:"listening"}` | Session status |
| `control` | `{type, action:"stop_capture"}` | Agent requested capture stop |
| `error` | `{type, message}` | Invalid or unsupported protocol message |
| `user_text_accepted` / `echo_dropped` | `{type}` | Accepted final speech interrupts TTS; echo leaves it speaking |

The browser does not send audio. With `agent.barge_in_mode: true`, recognition stays active during speech synthesis; accepted non-echo final text cancels speech, while EchoGuard drops matching agent/cue lines at rapidfuzz ratio >= 85 within 10 seconds. The interrupt button cancels speech and listening continues. Interim text does not reach the LLM unless recognition has produced no final for eight seconds, when the latest interim is promoted to a final turn. Recognition lifecycle and error codes are logged as `speech_event` records.

### 5.2 `/ws/capture`

Client → server:
| type | payload |
|---|---|
| hi-res frame | binary: 4-byte unsigned big-endian header length + JSON header `{seq, t_ms, w, h, motion:{gyro_dps, gravity:[x,y,z], alpha,beta,gamma}}` + JPEG bytes |
| `motion_only` | JSON `{type, t_ms, gyro_dps, gravity}` at 10 Hz (for speed even when frames are skipped) |

Server → client:
| type | fields |
|---|---|
| `qc` | `{seq, blur, glare, exposure, speed_dps, verdict:"ok"|"blurry"|"low_light_blur"|"glare"|"dark"|"bright"|"fast", markers:[ids]}` |
| `ack` | `{seq}` (client uses it for back-pressure: ≤ 3 un-acked frames in flight) |

Verdict priority is `fast` > `low_light_blur` > `blurry` > `glare` > `dark` > `bright` > `ok`.
The `fast` verdict requires the configured capture speed threshold to be exceeded
for the configured sustain window. `low_light_blur` requires blur below
`blur_min`, gyro below `speed_max_dps`, and exposure below the configurable
`low_light_exposure_max` (default 85). Brightness uses the configured dark and
bright mean-luminance thresholds.

## 6. Developer flows (CLI)

| Command | What it does |
|---|---|
| `python -m app.cli serve [--port 8000]` | Run the server |
| `python -m app.cli make-markers --ids 0 1 2 --size-mm 100 --out markers.pdf` | Printable scale cards (verify printed size with a ruler, then set `MARKER_SIZE_MM`) |
| `python -m app.cli inspect-sweep sweeps/<id>` | List frame QC and print a summary with count, duration, FPS, verdict percentages, and marker IDs |
| `python -m app.cli replay sweeps/<id> [--from s03] [--no-network]` | Re-run stages on saved frames. `--no-network` uses the cache only |
| `python -m app.cli stage s06 --sweep <id>` | Run one stage |
| `python -m app.cli reprice --sweep <id> --country GB --limit 10 --out docs/second_country.md` | Second-locale proof table |
| `python -m app.cli evaluate --sweep <id> --gt eval/ground_truth --out docs/results.md` | Pass-bar table + per-shelf breakdown + calibration plot |
| `python -m app.cli ingest-video path.mp4` | **Dev only.** Builds a sweep folder from a recorded video for offline pipeline work. Never used for the demo |
| `python -m app.cli calibrate --sweep <id> --gt …` | Fits `id_confidence` calibration and picks `tau_accept` |

## 7. Example agent lines (style guide for the prompt)

- Greeting (≤ 2 sentences): "Hi, I'm your claim assistant. I'll help you document your library in one walk-through."
- Sweep explanation: "Walk slowly past each shelf, top to bottom, then the furniture and walls. I'll tell you if anything needs a closer look."
- Cues: "Slow down a little." / "Step closer, top shelf." / "Tilt down, there's glare." / "Go back, bottom row on the left." / "Show me the ceiling line once."
- Questions: "Is that painting an original or a print?" / "Are all these shelves yours?"
- Never: "That looks like a valuable first edition worth…" / "You have about 80 books" (unless the number came from `get_sweep_status`) / "Can you pull that one out?"
