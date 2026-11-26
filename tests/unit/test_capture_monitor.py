from app.capture.monitor import CaptureMonitor
from app.pipeline.artifacts import FrameRecord
from app.settings import CaptureSettings, CueSettings


def _frame(
    seq: int,
    *,
    verdict: str = "ok",
    gyro: float = 2,
    exposure: float = 100,
    glare: float = 0,
):
    return FrameRecord(
        seq=seq,
        t_ms=seq * 500,
        path=f"frames/{seq}.jpg",
        w=1080,
        h=1920,
        blur=300,
        glare=glare,
        exposure=exposure,
        gyro_dps=gyro,
        qc_verdict=verdict,
    )


def test_monitor_prioritizes_fast_and_throttles_cues() -> None:
    monitor = CaptureMonitor(CaptureSettings(), CueSettings())
    candidate = None
    for seq in range(5):
        candidate = monitor.observe(_frame(seq, verdict="blurry", gyro=50)) or candidate
    assert candidate is not None and candidate.kind == "TOO_FAST"
    assert candidate.metrics["fast_fraction"] == 1
    assert monitor.observe(_frame(12, verdict="blurry", gyro=50)) is None


def test_monitor_low_light_suppressed_while_user_speaks() -> None:
    monitor = CaptureMonitor(CaptureSettings(), CueSettings())
    for seq in range(5):
        result = monitor.observe(
            _frame(seq, verdict="low_light_blur", exposure=60), user_speaking=True
        )
        assert result is None
    result = monitor.observe(_frame(6, verdict="low_light_blur", exposure=60))
    assert result is not None and result.kind == "LOW_LIGHT"
