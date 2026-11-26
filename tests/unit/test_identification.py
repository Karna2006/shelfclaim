from __future__ import annotations

import json

import pytest
from app.pipeline.context import StageContext
from app.pipeline.stages.s06_identify import normalize_catalogue_text, run
from app.settings import Settings, YamlSettings
from app.telemetry.ledger import Ledger


class EmptyCatalogue:
    async def search(self, title: str, author: str) -> list[dict[str, object]]:
        assert title == "VISIBLE FRAGMENT"
        return []


def test_catalogue_normalization_folds_accents_and_punctuation() -> None:
    assert normalize_catalogue_text("Le Thé—Book, Vol. 2") == "le the book vol 2"


@pytest.mark.asyncio
async def test_unidentified_book_keeps_identity_fields_empty(tmp_path) -> None:
    (tmp_path / "s03_books_raw.json").write_text(
        json.dumps({"books": [{"book_id": "b_0001"}]}), encoding="utf-8"
    )
    (tmp_path / "s05_transcriptions.json").write_text(
        json.dumps(
            {
                "books": {
                    "b_0001": {
                        "spine_text_raw": "VISIBLE FRAGMENT",
                        "legibility": 0.8,
                        "views": [{"lines": [{"kind_guess": "title", "text": "VISIBLE FRAGMENT"}]}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(config=YamlSettings(), _env_file=None)
    context = StageContext(tmp_path, settings, Ledger(), {"catalogue": EmptyCatalogue()})

    output = await run(context)

    book = json.loads(output.read_text(encoding="utf-8"))["books"]["b_0001"]
    assert book["status"] == "unidentified"
    assert (book["title"], book["authors"], book["edition"], book["isbn"]) == ("", [], "", "")
    assert book["id_confidence"] == 0


@pytest.mark.asyncio
async def test_missing_transcription_is_explicitly_unidentified(tmp_path) -> None:
    (tmp_path / "s03_books_raw.json").write_text(
        json.dumps({"books": [{"book_id": "b_0001"}]}), encoding="utf-8"
    )
    (tmp_path / "s05_transcriptions.json").write_text('{"books": {}}', encoding="utf-8")
    context = StageContext(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        Ledger(),
        {"catalogue": EmptyCatalogue()},
    )

    output = await run(context)

    book = json.loads(output.read_text(encoding="utf-8"))["books"]["b_0001"]
    assert book["status"] == "unidentified"
    assert (book["title"], book["authors"], book["edition"], book["isbn"]) == ("", [], "", "")
    assert book["spine_text_raw"] == ""


@pytest.mark.asyncio
async def test_merged_unclassified_ocr_text_does_not_match_title_subset(tmp_path) -> None:
    class CatalogueWithPartialTitle:
        async def search(self, title: str, author: str) -> list[dict[str, object]]:
            assert "THE ONE THING" in title
            del author
            return [
                {
                    "title": "The One Thing",
                    "authors": ["Gary Keller"],
                    "publishers": [],
                    "source": "openlibrary",
                    "key": "/works/OL123W",
                }
            ]

    (tmp_path / "s03_books_raw.json").write_text(
        json.dumps({"books": [{"book_id": "b_0001"}]}), encoding="utf-8"
    )
    (tmp_path / "s05_transcriptions.json").write_text(
        json.dumps(
            {
                "books": {
                    "b_0001": {
                        "spine_text_raw": "THE ONE THING GARY KELLER DEEP WORK",
                        "legibility": 0.98,
                        "views": [{"lines": [{"kind_guess": "other", "text": "THE ONE THING"}]}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    context = StageContext(
        tmp_path,
        Settings(config=YamlSettings(), _env_file=None),
        Ledger(),
        {"catalogue": CatalogueWithPartialTitle()},
    )

    output = await run(context)

    book = json.loads(output.read_text(encoding="utf-8"))["books"]["b_0001"]
    assert book["status"] == "unidentified"
    assert book["title"] == ""
