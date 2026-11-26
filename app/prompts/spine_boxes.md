Find only individual visible book spines in this cropped horizontal book row.
Return one tall, thin box per book, including leaning books. Never merge touching
books into a wider box. Exclude shelf boards, piles without a visible spine edge,
and every non-book object. Use cls "book_spine" and box_2d
[ymin,xmin,ymax,xmax] normalized from 0 to 1000. Do not read or report text.
Return JSON matching the provided schema.
