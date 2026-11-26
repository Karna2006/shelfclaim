from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.pipeline.context import StageContext
from app.pipeline.stages.s06_identify import identify_spine_lines, run
from app.settings import Settings, YamlSettings
from app.telemetry.ledger import Ledger


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lines", "expected_title", "accepted"),
    [
        (["THE EVERYDAY HERO MANIFESTO", "ROBIN SHARMA"], "Everyday Hero Manifesto", True),
        (["DEEP WORK", "IRFAN ALAM"], "Deep Work", False),
        (["HALFMURDERS", "Cal Newport"], "The Half Murders", False),
        (
            ["THE ALMANACK OF NAVAL RAVIKANT", "GARY KELLER", "WITH JAY PAPASAN"],
            "The Almanack of Naval Ravikant",
            True,
        ),
    ],
)
async def test_four_spines_match_openlibrary_fixtures(
    lines: list[str], expected_title: str, accepted: bool
) -> None:
    fixture_path = Path(__file__).parent.parent / "fixtures" / "openlibrary_identification.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))["responses"]

    class RecordedCatalogue:
        google_calls = 0
        open_library_calls = 0

        async def search(self, title: str, author: str) -> list[dict[str, object]]:
            google_candidates = await self.search_google_books(title, author)
            if google_candidates:
                return google_candidates
            return await self.search_open_library(title, author)

        async def search_open_library(self, title: str, author: str) -> list[dict[str, object]]:
            del author
            self.open_library_calls += 1
            documents = fixture.get(title, {}).get("docs", [])
            return [
                {
                    "source": "openlibrary",
                    "key": document["key"],
                    "title": document["title"],
                    "authors": document.get("author_name", []),
                    "publishers": document.get("publisher", []),
                }
                for document in documents
            ]

        async def search_google_books(self, title: str, author: str) -> list[dict[str, object]]:
            del title, author
            self.google_calls += 1
            return []

    catalogue = RecordedCatalogue()
    result = await identify_spine_lines(
        [{"text": line, "kind_guess": "other"} for line in lines], catalogue
    )
    candidates = [
        row for row in result["candidates"] if row["candidate"].get("title") == expected_title
    ]

    assert candidates
    assert bool(result["chosen"]) is accepted
    assert catalogue.google_calls == len(result["queries"])
    assert catalogue.open_library_calls == len(result["queries"])
    query_texts = [query for query, _ in result["queries"]]
    normalized_lines = [line.casefold().removeprefix("the ") for line in lines]
    assert query_texts[: len(lines)] == normalized_lines
    assert query_texts[len(lines) :] == [
        f"{first.casefold().removeprefix('the ')} {second.casefold().removeprefix('the ')}"
        for first, second in zip(lines, lines[1:], strict=False)
    ]
    if expected_title == "Deep Work":
        assert candidates[0]["title_sim"] == 100
        assert candidates[0]["author_sim"] < 85
        assert candidates[0]["raw_score"] == 1
    if expected_title == "The Half Murders":
        assert candidates[0]["title_sim"] == 100


@pytest.mark.asyncio
async def test_closest_title_line_wins_and_other_title_is_reviewed(tmp_path: Path) -> None:
    candidates = {
        "great alpha book": {
            "source": "openlibrary",
            "key": "/works/alpha",
            "title": "The Great Alpha Book",
            "authors": ["Alpha Writer"],
        },
        "better beta book": {
            "source": "openlibrary",
            "key": "/works/beta",
            "title": "The Better Beta Book",
            "authors": ["Beta Writer"],
        },
    }

    class TwoTitleCatalogue:
        async def search(self, title: str, author: str) -> list[dict[str, object]]:
            google = await self.search_google_books(title, author)
            return google or await self.search_open_library(title, author)

        async def search_open_library(self, title: str, author: str) -> list[dict[str, object]]:
            del author
            candidate = candidates.get(title)
            return [candidate] if candidate else []

        async def search_google_books(self, title: str, author: str) -> list[dict[str, object]]:
            del title, author
            return []

    (tmp_path / "s03_books_raw.json").write_text(
        json.dumps(
            {
                "books": [
                    {
                        "book_id": "b_0001",
                        "best_view": {"bbox": {"x": 0, "y": 0, "w": 100, "h": 100}},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "s05_transcriptions.json").write_text(
        json.dumps(
            {
                "books": {
                    "b_0001": {
                        "spine_text_raw": "THE GREAT ALPHA BOOK | THE BETTER BETA BOOK",
                        "views": [
                            {
                                "lines": [
                                    {
                                        "text": "THE GREAT ALPHA BOOK",
                                        "bbox": {"x": 10, "y": 20, "w": 20, "h": 10},
                                    },
                                    {
                                        "text": "THE BETTER BETA BOOK",
                                        "bbox": {"x": 44, "y": 45, "w": 20, "h": 10},
                                    },
                                ]
                            }
                        ],
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
        {"catalogue": TwoTitleCatalogue()},
    )

    output = await run(context)

    identification = json.loads(output.read_text(encoding="utf-8"))
    assert identification["books"]["b_0001"]["title"] == "The Better Beta Book"
    assert identification["review_queue"] == [
        {
            "ref_id": "b_0001",
            "code": "multiple_titles_in_box",
            "other_titles": ["The Great Alpha Book"],
        }
    ]
