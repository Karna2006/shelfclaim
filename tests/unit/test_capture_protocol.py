from __future__ import annotations

import json

import pytest
from app.server.ws_capture import _accept_motion_sample, _update_fast_motion, parse_frame_packet


def _packet() -> tuple[bytes, int]:
    header = {
        "seq": 7,
        "t_ms": 1200,
        "w": 1280,
        "h": 720,
        "motion": {"gyro_dps": 12.5, "gravity": [0, 0, 9.8], "alpha": 1, "beta": 2, "gamma": 3},
    }
    header_bytes = json.dumps(header).encode("utf-8")
    return len(header_bytes).to_bytes(
        4, byteorder="big"
    ) + header_bytes + b"\xff\xd8jpeg\xff\xd9", len(header_bytes)


def test_frame_header_length_is_unsigned_big_endian() -> None:
    packet, header_length = _packet()

    assert packet[:4] == header_length.to_bytes(4, byteorder="big", signed=False)
    parsed, jpeg = parse_frame_packet(packet)
    assert parsed.seq == 7
    assert parsed.motion is not None and parsed.motion.gravity == (0.0, 0.0, 9.8)
    assert jpeg == b"\xff\xd8jpeg\xff\xd9"


def test_fast_verdict_requires_a_sustained_motion_window() -> None:
    started = _update_fast_motion(None, 100, 65, 60)
    still_fast = _update_fast_motion(started, 900, 70, 60)
    stable = _update_fast_motion(still_fast, 1100, 20, 60)

    assert started == 100
    assert still_fast == 100
    assert stable is None
    assert _accept_motion_sample('{"type":"motion_only","t_ms":1200,"gyro_dps":66}') == (1200, 66.0)


@pytest.mark.parametrize(
    "packet",
    [b"", b"\x00\x00\x00\x00\xff\xd8", b"\x00\x00\x00\x01x\xff\xd8"],
)
def test_frame_parser_rejects_incomplete_or_invalid_packets(packet: bytes) -> None:
    with pytest.raises(ValueError):
        parse_frame_packet(packet)
