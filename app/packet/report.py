"""Render the user-facing, self-contained HTML claim summary.

Input: a validated ClaimPacket. Output: a local HTML report; prices, counts and
dimensions are copied from the deterministic packet only.
"""

from __future__ import annotations

import html
from urllib.parse import urlsplit

from app.packet.models import Book, ClaimPacket


def render_report(packet: ClaimPacket) -> str:
    """Render an accessible inventory table and review queue without estimates."""
    rows = [_render_book_row(book, packet.sweep.currency) for book in packet.books]
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
        "border-bottom:1px solid #ccd5d1;text-align:left}th{background:#edf3ef}"
        ".totals{display:flex;gap:1rem;flex-wrap:wrap}.totals div{padding:.75rem;"
        "background:#edf3ef;border-radius:.35rem}</style>"
        f"<h1>Home library claim inventory</h1><p>Sweep {html.escape(packet.sweep.id)} · "
        f"{packet.totals.book_count} books · {html.escape(packet.sweep.currency)}</p>"
        f"{_render_totals(packet)}"
        "<h2>Books</h2><table><thead><tr><th>Shelf</th><th>Title</th><th>Author</th>"
        "<th>Status</th><th>Dimensions</th><th>Frame</th><th>New price</th>"
        "<th>New source</th><th>Used price</th><th>Used source</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<h2>Needs review ({len(packet.review_queue)})</h2><ul>{reviews}</ul>"
        "<footer>Room area was not measured in this build.</footer></html>"
    )


def _render_book_row(book: Book, currency: str) -> str:
    title = book.title or "Unidentified spine"
    dims = (
        f"{book.spine_height_cm:g} × {book.spine_thickness_cm:g} cm"
        if book.spine_height_cm is not None and book.spine_thickness_cm is not None
        else "Not measured"
    )
    new = _format_amount(book.replacement_cost.amount, book.replacement_cost.currency, currency)
    used = _format_amount(book.used_value.amount, book.used_value.currency, currency)
    frame = _file_link("Open frame", book.frame_ref)
    new_source = _external_link(book.replacement_cost.source or "Source", book.replacement_cost.url)
    used_source = _external_link(book.used_value.source or "Source", book.used_value.url)
    return (
        "<tr>"
        f"<td>{html.escape(book.shelf)}-{book.position}</td>"
        f"<td>{_file_link(title, book.crop_ref or book.frame_ref)}</td>"
        f"<td>{html.escape(book.author or '—')}</td>"
        f"<td>{html.escape(book.status)}</td>"
        f"<td>{html.escape(dims)}</td>"
        f"<td>{frame}</td>"
        f"<td>{html.escape(new)}</td>"
        f"<td>{new_source}</td>"
        f"<td>{html.escape(used)}</td>"
        f"<td>{used_source}</td>"
        "</tr>"
    )


def _render_totals(packet: ClaimPacket) -> str:
    totals = packet.totals
    currency = html.escape(packet.sweep.currency)
    return (
        "<section class='totals' aria-label='Claim totals'>"
        f"<div>Books: {totals.book_count}</div>"
        f"<div>Identified: {totals.books_identified}</div>"
        f"<div>Unidentified: {totals.books_unidentified}</div>"
        f"<div>Replacement: {totals.books_replacement_cost:.2f} {currency}</div>"
        f"<div>Used value: {totals.books_used_value:.2f} {currency}</div>"
        f"<div>Items: {totals.items_priced_count} priced; "
        f"{totals.items_replacement_cost_low:.2f}–"
        f"{totals.items_replacement_cost_high:.2f} {currency}</div>"
        "</section>"
    )


def _format_amount(amount: float | None, quote_currency: str | None, fallback: str) -> str:
    return f"{amount:.2f} {quote_currency or fallback}" if amount is not None else "Not priced"


def _file_link(label: str, path: str | None) -> str:
    if not path:
        return "—"
    return f"<a href='{html.escape(path, quote=True)}'>{html.escape(label)}</a>"


def _external_link(label: str, url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "—"
    return (
        f"<a href='{html.escape(url, quote=True)}' target='_blank' "
        f"rel='noopener noreferrer'>{html.escape(label)}</a>"
    )
