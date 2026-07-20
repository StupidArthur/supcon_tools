"""Locked control-quality metric vocabulary for stage 6 prospective acceptance.

This is an acceptance probe module, not a business implementation.
Business Agents must implement the real calculator separately (e.g. controlQuality.ts).
"""

from __future__ import annotations

QUALITY_METRIC_IDS: tuple[str, ...] = (
    "error_band",
    "overshoot",
    "steady_state_error",
    "settling_time",
    "mv_saturation_time",
    "level_high_hits",
    "level_low_hits",
    "stable_window_60s",
    "segment_reset_after_param_event",
    "irregular_sample_interval",
    "missing_data",
    "non_finite_data",
)

TREND_AXIS_LEFT: tuple[str, ...] = ("tank_2.level", "pid2.SV")
TREND_AXIS_RIGHT: tuple[str, ...] = ("pid2.MV", "valve_1.current_opening")
PV_BINDING_NOTE = "pid2.PV ← tank_2.level"
TREND_CAPACITY = 1200
STABLE_WINDOW_SECONDS = 60
