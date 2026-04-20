"""Camera performance and blocking-regression tests."""

from __future__ import annotations

import time


def test_camera_frame_is_bounded_and_returns_tuple() -> None:
    """get_camera_frame should finish within bounded time and return (data_url, timestamp_ms).

    This test targets the regression where stream iteration could block indefinitely.
    Uses simulation mode so no real hardware is required.
    """
    from app.plugins.loader import load_plugin  # noqa: PLC0415  (deferred import)

    plugin = load_plugin("mock")

    durations: list[float] = []
    for _ in range(8):
        start = time.perf_counter()
        result = plugin.get_camera_frame("test_camera")
        durations.append(time.perf_counter() - start)
        assert result is not None, "simulation must never return None"
        data_url, ts_ms = result
        assert data_url.startswith("data:"), "data_url must be a data URI"
        assert isinstance(ts_ms, float), "timestamp_ms must be a float"

    max_s = max(durations)
    avg_s = sum(durations) / len(durations)
    fps_estimate = 1.0 / avg_s if avg_s > 0 else 0.0

    # Simulation frames should be essentially instantaneous (<100 ms each).
    assert max_s < 0.1

    print(
        {
            "camera_call_max_ms": round(max_s * 1000.0, 2),
            "camera_call_avg_ms": round(avg_s * 1000.0, 2),
            "camera_estimated_fps": round(fps_estimate, 2),
        }
    )
