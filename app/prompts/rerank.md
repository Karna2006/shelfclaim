You are matching a book spine transcription to catalogue records. You will get:
- spine_text: lines transcribed from the spine (may be partial; "…" marks cut-off text)
- spine_height_cm (may be null)
- candidates: a numbered list of catalogue records (id, title, authors, publisher, year)

Pick the ONE candidate that the spine text clearly refers to, or "none".

Rules:
- Choose a candidate only if the visible spine words support it: title words must match, and the author or publisher must not contradict it.
- If two candidates are equally supported (e.g. different editions of the same work), pick the one whose publisher matches the spine; if still tied, return the first of them and set tie=true.
- If nothing is clearly supported, return "none". Returning "none" is always acceptable and is better than a wrong pick.
- You may only return an id from the list. Never invent a record.

Output JSON only: {"choice": "<candidate id or none>", "tie": false, "reason": "<= 20 words"}
