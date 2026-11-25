import pytest
from app.packet.review import count_disagreement_entry
from app.pipeline.artifacts import RowCountCheck
from pydantic import ValidationError


def test_count_hint_above_threshold_creates_review_entry_only() -> None:
    check = RowCountCheck(seq=12, row_hint="A-1", model_count_hint=12, box_count=10)

    entry = count_disagreement_entry(check, threshold=0.10)

    assert entry is not None
    assert entry.code == "count_disagreement_row"
    assert entry.ref_id == "row:A-1"
    assert "model_count_hint=12" in (entry.evidence or "")


def test_count_hint_at_threshold_does_not_create_review_entry() -> None:
    check = RowCountCheck(seq=12, row_hint="A-1", model_count_hint=9, box_count=10)

    assert count_disagreement_entry(check, threshold=0.10) is None


def test_zero_box_count_skips_undefined_relative_error() -> None:
    check = RowCountCheck(seq=12, row_hint="A-1", model_count_hint=1, box_count=0)

    assert count_disagreement_entry(check, threshold=0.10) is None


def test_row_count_check_rejects_legacy_model_count_field() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RowCountCheck(
            seq=12,
            row_hint="A-1",
            model_count_hint=10,
            model_count=10,
            box_count=10,
        )
