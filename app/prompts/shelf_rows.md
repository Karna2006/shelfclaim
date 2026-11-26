Find only horizontal book rows in this bookshelf photo. A row is a contiguous band
of books resting on the same shelf, including books leaning at either end.
Return one box per visible book row, not boxes for the shelf unit, shelf boards,
items, or individual books. Keep each box tight around the row's books.
Use cls "shelf_row" and box_2d [ymin,xmin,ymax,xmax] normalized from 0 to 1000.
Do not read or report text. Return JSON matching the provided schema.
