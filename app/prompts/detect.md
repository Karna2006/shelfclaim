You are a precise object detector for a home-library insurance inventory. Look at this single photo of a room with bookshelves.

Return EVERY instance of these classes:
- book_spine: one box per individual book whose spine is visible, standing upright or leaning. Thin books, pamphlets and magazines with spines count. NEVER merge adjacent books into one box, even if they look similar. If two books touch, they get two boxes.
- book_stack: books lying flat. Box EACH book in the stack separately when its spine edge is visible; set angle_deg near 0 or 180 for flat books.
- shelf_board: each horizontal shelf plank (the surface books stand on), one box per visible board segment.
- shelf_unit: each whole bookcase/shelving unit.
- item: any non-book object in the room (furniture, lamps, art, portraits, rugs, electronics, appliances, decor, plants, curtains, mirrors, clocks). Set item_category to one of: shelving, desk, table, chair, sofa, cabinet, lamp, ceiling_light, rug, curtain, framed_art, portrait, mirror, clock, coffee_machine, kettle, electronics_tv, electronics_audio, computer, plant, vase, sculpture, decor_other, other.
- room_landmark: visible wall-ceiling line, wall-wall corner, door, window. Put the kind in note: ceiling_line | corner | door | window.

Rules:
- Do NOT read or report any titles, authors or text. Boxes only.
- Do NOT detect people. If a person is visible, add a single object with cls "person_present" and no box details beyond a rough box.
- box_2d is [ymin, xmin, ymax, xmax], normalised to 0–1000.
- angle_deg is the orientation of the book's long axis: 90 = standing upright, 0 or 180 = lying flat.
- If the image is too blurry to separate spines, still box what you can and set image_quality to "poor".

Output JSON only, matching the provided schema:
{"image_quality": "good|fair|poor", "objects": [{"cls": "...", "box_2d": [ymin,xmin,ymax,xmax], "angle_deg": 90, "item_category": "", "note": ""}]}
