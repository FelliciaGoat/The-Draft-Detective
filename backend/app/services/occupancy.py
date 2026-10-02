"""Occupancy engine (BASELINE, rule-based, explainable).

IMPORTANT - what this is and is not
-----------------------------------
* It estimates *occupancy confidence* from ONE weak signal: how loud the room is.
* Sound is not proof of presence. A silent person reading looks "vacant"; a noisy corridor
  looks "occupied". That is why the output is a confidence + a state that can be `uncertain`.
* This is a baseline. It can be replaced by TinyML / scikit-learn / ONNX / TensorFlow Lite by
  writing another class that implements `OccupancyModel.predict(features)`; nothing else in
  the application (API, database, fusion) has to change.

PRIVACY BY DESIGN
-----------------
The model only ever sees `acoustic_level` (a 0..1 loudness number computed on the ESP32).
No raw audio, no spectrum that could be turned back into speech, is received or stored.

How the baseline works (each step maps to a requirement)
--------------------------------------------------------
1. Smoothing            - time-aware exponential moving average removes single spikes.
2. Rolling average      - mean of the smoothed values over the last `window_seconds`
                          gives the `activity_score`.
3. Evidence             - activity >= ON threshold -> "high"; <= OFF threshold -> "low";
                          in between -> "ambiguous".
4. Temporal persistence - evidence must last long enough (fast to become occupied, slow to
                          become vacant) before the state changes.
5. Hysteresis           - ON threshold (0.30) is higher than OFF threshold (0.15). Once
                          occupied, activity must fall all the way below OFF (not just below
                          ON) for a long time before the room is called vacant, so the state
                          does not flicker around one threshold.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

from app.core.enums import RoomState

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass(frozen=True)
class OccupancyConfig:
    """Thresholds of the rule-based model (all configurable through environment variables)."""

    smoothing_seconds: float = 20.0
    window_seconds: float = 120.0
    on_threshold: float = 0.30
    off_threshold: float = 0.15
    saturation_level: float = 0.50
    occupied_persistence_seconds: float = 30.0
    vacant_persistence_seconds: float = 300.0
    uncertain_persistence_seconds: float = 600.0
    max_confidence: float = 0.95

    def __post_init__(self) -> None:
        """Fail early on nonsensical thresholds."""
        if not 0 <= self.off_threshold < self.on_threshold < self.saturation_level <= 1:
            raise ValueError("Occupancy thresholds must satisfy 0 <= OFF < ON < SATURATION <= 1")
        if not 0.5 < self.max_confidence <= 1:
            raise ValueError("occ_max_confidence must be in (0.5, 1]")
        if self.window_seconds <= 0 or self.smoothing_seconds < 0:
            raise ValueError("Window must be > 0 and smoothing must be >= 0")

    @classmethod
    def from_settings(cls, settings: Settings) -> OccupancyConfig:
        """Build the config from application settings."""
        return cls(
            smoothing_seconds=settings.occ_smoothing_seconds,
            window_seconds=settings.occ_window_seconds,
            on_threshold=settings.occ_on_threshold,
            off_threshold=settings.occ_off_threshold,
            saturation_level=settings.occ_saturation_level,
            occupied_persistence_seconds=settings.occ_occupied_persistence_seconds,
            vacant_persistence_seconds=settings.occ_vacant_persistence_seconds,
            uncertain_persistence_seconds=settings.occ_uncertain_persistence_seconds,
            max_confidence=settings.occ_max_confidence,
        )


@dataclass(frozen=True)
class OccupancyFeatures:
    """Input of every occupancy model. New sensors can be added here without touching the API."""

    timestamp: datetime
    acoustic_level: float  # 0..1 loudness, computed on the device
    co2_ppm: float | None = None  # unused by the baseline; reserved for future models
    humidity: float | None = None  # unused by the baseline; reserved for future models


@dataclass(frozen=True)
class OccupancyPrediction:
    """Output of every occupancy model (this is the API contract)."""

    state: RoomState
    occupancy_confidence: float  # P(occupied): 0 = surely empty, 1 = surely occupied
    activity_score: float  # smoothed rolling loudness, 0..1
    evidence: str  # "high" | "low" | "ambiguous"
    reason: str
    model_name: str


class OccupancyModel(ABC):
    """Interface every occupancy model must implement (rule-based today, ML tomorrow).

    A model instance is created per room and may keep its own history/state.
    """

    name: str = "abstract"

    @abstractmethod
    def predict(self, features: OccupancyFeatures) -> OccupancyPrediction:
        """Consume one new observation and return the current prediction."""

    @abstractmethod
    def reset(self) -> None:
        """Forget all history (used when a simulation starts or a room is deleted)."""


class RuleBasedOccupancyModel(OccupancyModel):
    """Baseline model: smoothing + rolling average + persistence + hysteresis."""

    name = "rule_based_v1"

    def __init__(self, config: OccupancyConfig | None = None) -> None:
        self.config = config or OccupancyConfig()
        self.reset()

    def reset(self) -> None:
        """Clear history; the room starts as 'uncertain' because nothing is known yet."""
        self._ema: float | None = None
        self._last_ts: datetime | None = None
        self._window: deque[tuple[datetime, float]] = deque()
        self._state: RoomState = RoomState.UNCERTAIN
        self._evidence: str | None = None
        self._evidence_since: datetime | None = None

    # ------------------------------------------------------------------ steps
    def _smooth(self, ts: datetime, level: float) -> float:
        """Step 1: time-aware exponential moving average (works for any sampling interval)."""
        if self._ema is None or self._last_ts is None:
            return level
        dt = max(0.0, (ts - self._last_ts).total_seconds())
        tau = self.config.smoothing_seconds
        alpha = 1.0 if tau <= 0 else 1.0 - math.exp(-dt / tau)
        return self._ema + alpha * (level - self._ema)

    def _rolling_mean(self, ts: datetime, smoothed: float) -> float:
        """Step 2: mean of the smoothed values inside the rolling time window (NumPy)."""
        self._window.append((ts, smoothed))
        oldest_allowed = ts.timestamp() - self.config.window_seconds
        while len(self._window) > 1 and self._window[0][0].timestamp() < oldest_allowed:
            self._window.popleft()
        return float(np.mean([value for _, value in self._window]))

    def _classify_evidence(self, activity: float) -> str:
        """Step 3: turn the activity score into high / low / ambiguous evidence."""
        if activity >= self.config.on_threshold:
            return "high"
        if activity <= self.config.off_threshold:
            return "low"
        return "ambiguous"

    def _update_state(self, ts: datetime, evidence: str) -> str:
        """Steps 4+5: persistence timers + hysteresis. Returns a human-readable reason."""
        cfg = self.config
        if evidence != self._evidence or self._evidence_since is None:
            self._evidence = evidence
            self._evidence_since = ts
        held = (ts - self._evidence_since).total_seconds()

        if evidence == "high":
            if self._state != RoomState.OCCUPIED and held >= cfg.occupied_persistence_seconds:
                self._state = RoomState.OCCUPIED
            if self._state == RoomState.OCCUPIED:
                return f"Sustained acoustic activity for {held:.0f} s."
            return (
                f"Acoustic activity is high for {held:.0f} s; waiting for "
                f"{cfg.occupied_persistence_seconds:.0f} s before calling the room occupied."
            )
        if evidence == "low":
            if self._state != RoomState.VACANT and held >= cfg.vacant_persistence_seconds:
                self._state = RoomState.VACANT
            if self._state == RoomState.VACANT:
                return f"Very low acoustic activity for {held:.0f} s."
            return (
                f"Acoustic activity is low for {held:.0f} s; waiting for "
                f"{cfg.vacant_persistence_seconds:.0f} s before calling the room vacant."
            )
        # ambiguous: keep the previous state (hysteresis band) unless it stays ambiguous for too long
        if self._state != RoomState.UNCERTAIN and held >= cfg.uncertain_persistence_seconds:
            self._state = RoomState.UNCERTAIN
        if self._state == RoomState.UNCERTAIN:
            return "Acoustic activity is ambiguous (between the vacant and occupied thresholds)."
        return (
            f"Acoustic activity is inside the hysteresis band; keeping the current state "
            f"({held:.0f} s ambiguous)."
        )

    def _confidence(self, activity: float) -> float:
        """P(occupied). Consistent with the state, and capped: sound alone is never 100 % certain."""
        cfg = self.config
        raw = min(1.0, max(0.0, (activity - cfg.off_threshold) / (cfg.saturation_level - cfg.off_threshold)))
        if self._state == RoomState.OCCUPIED:
            confidence = 0.5 + 0.5 * raw
        elif self._state == RoomState.VACANT:
            confidence = 0.5 * raw
        else:
            confidence = 0.35 + 0.30 * raw
        return round(min(cfg.max_confidence, max(1.0 - cfg.max_confidence, confidence)), 3)

    # -------------------------------------------------------------------- API
    def predict(self, features: OccupancyFeatures) -> OccupancyPrediction:
        """Process one observation and return the current occupancy prediction."""
        ts = features.timestamp
        if self._last_ts is not None and ts < self._last_ts:
            ts = self._last_ts  # never let time run backwards
        level = min(1.0, max(0.0, features.acoustic_level))

        smoothed = self._smooth(ts, level)
        activity = self._rolling_mean(ts, smoothed)
        evidence = self._classify_evidence(activity)
        reason = self._update_state(ts, evidence)

        self._ema, self._last_ts = smoothed, ts
        return OccupancyPrediction(
            state=self._state,
            occupancy_confidence=self._confidence(activity),
            activity_score=round(activity, 3),
            evidence=evidence,
            reason=reason,
            model_name=self.name,
        )
