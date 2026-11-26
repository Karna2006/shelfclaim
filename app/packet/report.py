"""Render the user-facing, self-contained HTML claim summary.

Input: a validated ClaimPacket. Output: a local HTML report; prices, counts and
dimensions are copied from the deterministic packet only.
"""

from __future__ import annotations

import html

from app.packet.models import ClaimPacket


def render_report(packet: ClaimPacket) -> str:
    """Render an accessible inventory table and review queue without estimates."""
    rows = []
    for book in packet.books:
        title = book.title or "Unidentified spine"
        amount = book.replacement_cost.amount
        price = f"{amount:.2f} {packet.sweep.currency}" if amount is not None else "Not priced"
        rows.append(
            "<tr>"
            f"<td>{html.escape(book.shelf)}-{book.position}</td>"
            f"<td>{html.escape(title)}</td>"
            f"<td>{html.escape(book.status)}</td>"
            f"<td>{html.escape(price)}</td>"
            "</tr>"
        )
    reviews = "".join(
        f"<li>{html.escape(entry.ref_id)}: {html.escape(entry.reason)}</li>"
        for entry in packet.review_queue
    )
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Claim inventory — {html.escape(packet.sweep.id)}</title>"
        "<style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;"
        "color:#18211f}table{width:100%;border-collapse:collapse}th,td{padding:.65rem;"
        "border-bottom:1px solid #ccd5d1;text-align:left}th{background:#edf3ef}</style>"
        f"<h1>Home library claim inventory</h1><p>Sweep {html.escape(packet.sweep.id)} · "
        f"{packet.totals.book_count} books · {html.escape(packet.sweep.currency)}</p>"
        "<h2>Books</h2><table><thead><tr><th>Shelf</th><th>Title</th><th>Status</th>"
        f"<th>Replacement estimate</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"<h2>Needs review ({len(packet.review_queue)})</h2><ul>{reviews}</ul>"
        "<footer>Room area was not measured in this build.</footer></html>"
    )
