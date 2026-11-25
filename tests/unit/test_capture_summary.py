from __future__ import annotations

from app.capture.summary import summarize_frames
from app.pipeline.artifacts import FrameRecord, MarkerObservation
from app.settings import Settings


def test_summary_reports_duration_fps_categories_and_unique_markers() -> None:
    records = [
        FrameRecord(
            seq=0,
            t_ms=1000,
            path="frames/0.jpg",
            w=100,
            h=80,
            qc_verdict="ok",
            markers=[MarkerObservation(id=2, corners=[])],
        ),
        FrameRecord(
            seq=1,
            t_ms=2000,
            path="frames/1.jpg",
            w=100,
            h=80,
            qc_verdict="low_light_blur",
            markers=[MarkerObservation(id=7, corners=[])],
        ),
        FrameRecord(
            seq=2,
            t_ms=3000,
            path="frames/2.jpg",
            w=100,
            h=80,
            qc_verdict="blurry",
            markers=[MarkerObservation(id=2, corners=[])],
        ),
        FrameRecord(
            seq=3,
            t_ms=4000,
            path="frames/3.jpg",
            w=100,
            h=80,
            qc_verdict="fast",
        ),
    ]

    summary = summarize_frames(records, Settings(_env_file=None).config.capture)

    assert summary.frame_count == 4
    assert summary.duration_s == 3
    assert summary.fps == 1
    assert summary.percentages == {
        "ok": 25,
        "blurry": 25,
        "fast": 25,
        "glare": 0,
        "dark": 25,
        "bright": 0,
    }
    assert summary.markers_seen == (2, 7)


def test_summary_infers_legacy_manifest_low_light_as_dark() -> None:
    record = FrameRecord(
        seq=0,
        t_ms=0,
        path="frames/0.jpg",
        w=100,
        h=80,
        blur=20,
        exposure=75,
        gyro_dps=8,
    )

    summary = summarize_frames([record], Settings(_env_file=None).config.capture)

    assert summary.percentages["dark"] == 100
    assert summary.fps == 0


def test_legacy_summary_requires_a_sustained_fast_window() -> None:
    records = [
        FrameRecord(
            seq=seq,
            t_ms=timestamp,
            path=f"frames/{seq}.jpg",
            w=100,
            h=80,
            blur=250,
            exposure=100,
            gyro_dps=40,
        )
        for seq, timestamp in enumerate((0, 500, 1000))
    ]

    summary = summarize_frames(records, Settings(_env_file=None).config.capture)

    assert summary.percentages["fast"] == 100 / 3
    assert summary.percentages["ok"] == 200 / 3
