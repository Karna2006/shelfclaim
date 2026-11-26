from app.live.soak import _CONVERSATION, _percentile


def test_soak_covers_twenty_turns_and_uses_interpolated_percentile() -> None:
    values = list(range(1, 21))

    assert len(_CONVERSATION) == 20
    assert _percentile(values, 0.50) == 10.5
    assert _percentile(values, 0.95) == 19.05
