"""Thermal anomaly engine.

What this does
--------------
It compares the room air temperature with the temperature measured at the building envelope
(window or exterior wall):  delta_T = |room - edge|.

What this does NOT do
---------------------
A large delta_T is NOT proof of a leak. Sun on a window, a cold night, a heater under the
window or an open door all create large differences. The engine therefore reports a
*thermal anomaly score* and only raises a *leak candidate* flag when the anomaly has
persisted for a while. A candidate means "worth inspecting", never "confirmed leak".

Steps
-----
1. instantaneous score = linear ramp between `delta_low_c` (score 0) and `delta_high_c` (score 1)
2. time-aware smoothing of that score
3. persistence: smoothed score must stay >= flag threshold for `persistence_seconds`
4. hysteresis: once flagged it only clears when the score falls below the (lower) clear threshold
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass(frozen=True)
class ThermalConfig:
    """Thresholds of the thermal engine (configurable through environment variables)."""

    delta_low_c: float = 2.0
    delta_high_c: float = 8.0
    smoothing_seconds: float = 60.0
    flag_threshold: float = 0.5
    clear_threshold: float = 0.35
    persistence_seconds: float = 300.0

    def __post_init__(self) -> None:
        """Fail early on nonsensical thresholds."""
        if not 0 <= self.delta_low_c < self.delta_high_c:
            raise ValueError("Thermal thresholds must satisfy 0 <= delta_low < delta_high")
        if not 0 < self.clear_threshold <= self.flag_threshold <= 1:
            raise ValueError("Thermal thresholds must satisfy 0 < clear <= flag <= 1")

    @classmethod
    def from_settings(cls, settings: Settings) -> ThermalConfig:
        """Build the config from application settings."""
        return cls(
            delta_low_c=settings.thermal_delta_low_c,
            delta_high_c=settings.thermal_delta_high_c,
            smoothing_seconds=settings.thermal_smoothing_seconds,
            flag_threshold=settings.thermal_flag_threshold,
            clear_threshold=settings.thermal_clear_threshold,
            persistence_seconds=settings.thermal_persistence_seconds,
        )


@dataclass(frozen=True)
class ThermalResult:
    """Output of the thermal engine."""

    has_data: bool
    delta_temperature: float | None
    thermal_anomaly_score: float | None
    leak_candidate: bool
    elevated_seconds: float
    explanation: str

    @classmethod
    def no_data(cls) -> ThermalResult:
        """Result used when a temperature is missing."""
        return cls(
            has_data=False,
            delta_temperature=None,
            thermal_anomaly_score=None,
            leak_candidate=False,
            elevated_seconds=0.0,
            explanation="Both room and edge temperature are required for thermal analysis.",
        )


def compute_delta_temperature(room_temperature: float, edge_temperature: float) -> float:
    """delta_T = |room - edge| in degrees C."""
    return abs(room_temperature - edge_temperature)


def instantaneous_score(delta_t: float, config: ThermalConfig) -> float:
    """Map delta_T linearly to 0..1: <= low -> 0, >= high -> 1."""
    span = config.delta_high_c - config.delta_low_c
    return min(1.0, max(0.0, (delta_t - config.delta_low_c) / span))


class ThermalAnalyzer:
    """Stateful analyzer (one per room) that remembers how long the anomaly has lasted."""

    def __init__(self, config: ThermalConfig | None = None) -> None:
        self.config = config or ThermalConfig()
        self.reset()

    def reset(self) -> None:
        """Forget all history."""
        self._score: float | None = None
        self._last_ts: datetime | None = None
        self._elevated_since: datetime | None = None

    def update(self, timestamp: datetime, room_temperature: float, edge_temperature: float) -> ThermalResult:
        """Process one pair of temperatures and return the current thermal assessment."""
        cfg = self.config
        ts = timestamp
        if self._last_ts is not None and ts < self._last_ts:
            ts = self._last_ts

        delta_t = compute_delta_temperature(room_temperature, edge_temperature)
        instant = instantaneous_score(delta_t, cfg)

        # 2. smoothing (time-aware exponential moving average)
        if self._score is None or self._last_ts is None:
            score = instant
        else:
            dt = max(0.0, (ts - self._last_ts).total_seconds())
            alpha = 1.0 if cfg.smoothing_seconds <= 0 else 1.0 - math.exp(-dt / cfg.smoothing_seconds)
            score = self._score + alpha * (instant - self._score)

        # 3 + 4. persistence with hysteresis
        if self._elevated_since is None:
            if score >= cfg.flag_threshold:
                self._elevated_since = ts
        elif score < cfg.clear_threshold:
            self._elevated_since = None

        elevated_seconds = 0.0 if self._elevated_since is None else (ts - self._elevated_since).total_seconds()
        leak_candidate = self._elevated_since is not None and elevated_seconds >= cfg.persistence_seconds

        self._score, self._last_ts = score, ts
        return ThermalResult(
            has_data=True,
            delta_temperature=round(delta_t, 2),
            thermal_anomaly_score=round(score, 3),
            leak_candidate=leak_candidate,
            elevated_seconds=round(elevated_seconds, 1),
            explanation=self._explain(delta_t, score, elevated_seconds, leak_candidate),
        )

    def _explain(self, delta_t: float, score: float, elevated_seconds: float, leak_candidate: bool) -> str:
        """Human-readable explanation that never states a leak as a fact."""
        if leak_candidate:
            return (
                f"Persistent temperature differential detected near the building envelope "
                f"(delta {delta_t:.1f} C for {elevated_seconds:.0f} s). This is a leak CANDIDATE, "
                f"not a confirmed leak: inspect the window / wall seals."
            )
        if self._elevated_since is not None:
            return (
                f"Elevated temperature differential (delta {delta_t:.1f} C) for {elevated_seconds:.0f} s; "
                f"waiting for it to persist {self.config.persistence_seconds:.0f} s before flagging a candidate."
            )
        if score > 0:
            return f"Small temperature differential (delta {delta_t:.1f} C); within the normal range."
        return f"Temperature differential is normal (delta {delta_t:.1f} C)."
