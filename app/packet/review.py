"""Create review-only entries from diagnostic row-count hints.

Input: a row's model hint and deterministic box count. Output: a review entry
or `None`; hints never alter packet counts. Implements `docs/04_ARCHITECTURE.md` S1.
"""

from app.packet.models import ReviewEntry
from app.pipeline.artifacts import RowCountCheck


def count_disagreement_entry(check: RowCountCheck, threshold: float) -> ReviewEntry | None:
    """Return a review entry only when a model hint exceeds the relative threshold."""
    # A zero box count makes the specified relative-error denominator undefined.
    if check.box_count == 0:
        return None

    disagreement = abs(check.model_count_hint - check.box_count) / check.box_count
    if disagreement <= threshold:
        return None

    return ReviewEntry(
        ref_id=f"row:{check.row_hint}",
        reason="Model count hint disagrees with the deterministic box count",
        code="count_disagreement_row",
        evidence=(
            f"model_count_hint={check.model_count_hint}; box_count={check.box_count}; "
            f"relative_difference={disagreement:.3f}"
        ),
    )
