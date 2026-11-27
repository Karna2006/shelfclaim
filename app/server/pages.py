"""Build small HTML responses for the live viewer and saved sweep reports.

Inputs are local web/docs files and a validated sweeps directory. Outputs are
HTML pages or path-checked files; report-relative assets stay inside a sweep.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

_SWEEP_ID = re.compile(r"sw_\d{8}_\d{6}_[0-9a-f]{4}")


def viewer_page(web_dir: Path, sweep_id: str | None) -> HTMLResponse:
    page = web_dir / "viewer.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Viewer page not found")
    source = page.read_text(encoding="utf-8")
    return HTMLResponse(source.replace("__SWEEP_ID__", html.escape(sweep_id or "", quote=True)))


def architecture_page(markdown_path: Path) -> HTMLResponse:
    if not markdown_path.is_file():
        raise HTTPException(status_code=404, detail="Architecture document not found")
    source = html.escape(markdown_path.read_text(encoding="utf-8"), quote=False)
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>ShelfClaim architecture</title><style>"
        "body{margin:0;background:#0b0b0c;color:#e4e4e7;font:16px/1.6 system-ui}"
        "main{max-width:1180px;margin:auto;padding:2rem 1.25rem}"
        "a{color:#86efac}h1,h2,h3{line-height:1.2}"
        "table{width:100%;border-collapse:collapse;display:block;overflow:auto}"
        "th,td{border:1px solid #3f3f46;padding:.55rem;text-align:left}"
        "th{background:#18181b}pre{overflow:auto;background:#18181b;padding:1rem;border-radius:.5rem}"
        ".mermaid{background:#111113;padding:1rem;border-radius:.5rem;overflow:auto}"
        "</style><main id='content'></main><textarea id='source' hidden>"
        f"{source}</textarea>"
        "<script src='https://cdn.jsdelivr.net/npm/marked/marked.min.js'></script>"
        "<script src='https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js'></script>"
        "<script>const source=document.querySelector('#source').value;"
        "document.querySelector('#content').innerHTML=marked.parse(source);"
        "document.querySelectorAll('pre code.language-mermaid').forEach(code=>{"
        "const node=document.createElement('div');node.className='mermaid';"
        "node.textContent=code.textContent;code.parentElement.replaceWith(node)});"
        "mermaid.initialize({startOnLoad:false,theme:'dark'});mermaid.run();</script></main></html>"
    )


def sweep_list_page(sweeps_dir: Path) -> HTMLResponse:
    rows = []
    for sweep_id in _sweep_ids(sweeps_dir):
        report = (sweeps_dir / sweep_id / "report.html").is_file()
        suffix = " · report ready" if report else " · report pending"
        rows.append(
            f"<li><a href='/sweeps/{sweep_id}/'>{sweep_id}</a>"
            f"<span>{suffix}</span> · <a href='/viewer/{sweep_id}'>Live view</a></li>"
        )
    content = "".join(rows) or "<li>No saved sweeps yet.</li>"
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>ShelfClaim reports</title><style>body{font:16px system-ui;background:#0b0b0c;"
        "color:#f5f5f5;max-width:900px;margin:2rem auto;padding:0 1rem}a{color:#86efac}"
        "li{margin:1rem 0}span{color:#a1a1aa}</style><h1>ShelfClaim sweeps</h1>"
        f"<ul>{content}</ul></html>"
    )


def report_path(sweeps_dir: Path, sweep_id: str, asset_path: str = "report.html") -> Path:
    if not _SWEEP_ID.fullmatch(sweep_id) or not asset_path:
        raise HTTPException(status_code=404, detail="Sweep file not found")
    root = (sweeps_dir / sweep_id).resolve()
    target = (root / asset_path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Sweep file not found")
    return target


def latest_sweep_id(sweeps_dir: Path) -> str | None:
    return next(iter(_sweep_ids(sweeps_dir)), None)


def _sweep_ids(sweeps_dir: Path) -> list[str]:
    if not sweeps_dir.is_dir():
        return []
    return sorted(
        (
            path.name
            for path in sweeps_dir.iterdir()
            if path.is_dir() and _SWEEP_ID.fullmatch(path.name) and (path / "sweep.json").is_file()
        ),
        reverse=True,
    )
