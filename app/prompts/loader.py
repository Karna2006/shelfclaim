"""Load reviewed prompt files by a fixed logical name.

Input: one of the prompt names shipped under `app/prompts/`. Output: UTF-8
prompt text without code-embedded copies. Implements `AGENTS.md` §2.
"""

from __future__ import annotations

from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent
_ALLOWED_PROMPTS = {"agent_system", "detect", "transcribe", "items", "rerank"}


def load_prompt(name: str) -> str:
    """Read a known prompt without allowing path traversal or prompt rewriting."""
    if name not in _ALLOWED_PROMPTS:
        raise ValueError(f"Unknown prompt name: {name}")
    path = _PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file is missing: {path.name}")
    return path.read_text(encoding="utf-8")
