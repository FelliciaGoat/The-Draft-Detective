"""Occupancy engine tests: classification, smoothing, persistence and hysteresis."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.enums import RoomState
from app.services.occupancy import (
    OccupancyConfig,
    OccupancyFeatures,
    OccupancyModel,
    RuleBasedOccupancyModel,
)

T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)


def feed(model: OccupancyModel, level: float, seconds: int, start: datetime = T0, interval: int = 10):
    """Feed a constant acoustic level for `seconds`; return (predictions, next_start_time)."""
    predictions = []
    for i in range(seconds // interval):
        ts = start + timedelta(seconds=i * interval)
        predictions.append(model.predict(OccupancyFeatures(timestamp=ts, acoustic_level=level)))
    return predictions, start + timedelta(seconds=seconds)


def test_starts_uncertain_because_nothing_is_known():
    model = RuleBasedOccupancyModel()
    prediction = model.predict(OccupancyFeatures(timestamp=T0, acoustic_level=0.6))
    assert prediction.state == RoomState.UNCERTAIN


def test_sustained_high_activity_becomes_occupied_only_after_persistence():
    model = RuleBasedOccupancyModel()
    predictions, _ = feed(model, 0.6, 120)
    assert predictions[1].state == RoomState.UNCERTAIN  # 10 s of evidence is not enough (needs 30 s)
    assert predictions[-1].state == RoomState.OCCUPIED
    assert predictions[-1].occupancy_confidence > 0.7


def test_sustained_silence_becomes_vacant_only_after_the_long_persistence_period():
    model = RuleBasedOccupancyModel()
    predictions, _ = feed(model, 0.02, 290)
    assert predictions[-1].state == RoomState.UNCERTAIN  # 290 s < 300 s
    predictions, _ = feed(model, 0.02, 60, start=T0 + timedelta(seconds=290))
    assert predictions[-1].state == RoomState.VACANT
    assert 0.05 <= predictions[-1].occupancy_confidence <= 0.2


def test_single_loud_spike_in_a_quiet_room_does_not_flip_the_state():
    model = RuleBasedOccupancyModel()
    _, t = feed(model, 0.02, 400)  # vacant
    spike = model.predict(OccupancyFeatures(timestamp=t, acoustic_level=1.0))
    after, _ = feed(model, 0.02, 100, start=t + timedelta(seconds=10))
    assert spike.state == RoomState.VACANT
    assert after[-1].state == RoomState.VACANT


def test_hysteresis_keeps_occupied_while_activity_stays_between_the_thresholds():
    """Once occupied, activity must fall below the OFF threshold (0.15), not just below ON (0.30)."""
    model = RuleBasedOccupancyModel()
    _, t = feed(model, 0.6, 120)  # occupied
    band, t = feed(model, 0.22, 500, start=t)  # between OFF and ON, shorter than the 600 s ambiguity limit
    assert band[-1].evidence == "ambiguous"
    assert band[-1].state == RoomState.OCCUPIED  # a plain "sound > 0.30" rule would already say vacant
    quiet_short, t = feed(model, 0.02, 250, start=t)
    assert quiet_short[-1].state == RoomState.OCCUPIED  # still holding: vacancy needs 300 s of low evidence
    quiet_long, _ = feed(model, 0.02, 600, start=t)
    assert quiet_long[-1].state == RoomState.VACANT


def test_ambiguous_signal_stays_uncertain_with_middling_confidence():
    model = RuleBasedOccupancyModel()
    predictions, _ = feed(model, 0.22, 700)
    assert all(p.state == RoomState.UNCERTAIN for p in predictions)
    assert 0.35 <= predictions[-1].occupancy_confidence <= 0.65


def test_long_ambiguity_after_occupied_degrades_to_uncertain():
    model = RuleBasedOccupancyModel()
    _, t = feed(model, 0.6, 120)
    predictions, _ = feed(model, 0.22, 800, start=t)
    assert predictions[-1].state == RoomState.UNCERTAIN


def test_confidence_never_reaches_certainty_from_sound_alone():
    model = RuleBasedOccupancyModel()
    loud, t = feed(model, 1.0, 600)
    quiet, _ = feed(model, 0.0, 900, start=t)
    assert max(p.occupancy_confidence for p in loud) <= 0.95
    assert min(p.occupancy_confidence for p in quiet) >= 0.05


def test_confidence_is_consistent_with_the_state():
    model = RuleBasedOccupancyModel()
    occupied, t = feed(model, 0.6, 200)
    assert occupied[-1].state == RoomState.OCCUPIED and occupied[-1].occupancy_confidence >= 0.5
    quiet, _ = feed(model, 0.0, 1000, start=t)
    assert quiet[-1].state == RoomState.VACANT and quiet[-1].occupancy_confidence <= 0.5


def test_works_with_slow_sampling_intervals():
    model = RuleBasedOccupancyModel()
    predictions, _ = feed(model, 0.6, 600, interval=60)
    assert predictions[-1].state == RoomState.OCCUPIED


def test_out_of_order_timestamps_do_not_crash_or_rewind_time():
    model = RuleBasedOccupancyModel()
    model.predict(OccupancyFeatures(timestamp=T0 + timedelta(seconds=100), acoustic_level=0.5))
    prediction = model.predict(OccupancyFeatures(timestamp=T0, acoustic_level=0.5))
    assert prediction.state in RoomState


def test_thresholds_are_configurable():
    config = OccupancyConfig(on_threshold=0.6, off_threshold=0.1, saturation_level=0.9)
    model = RuleBasedOccupancyModel(config)
    predictions, _ = feed(model, 0.4, 300)  # would be "occupied" with the defaults
    assert predictions[-1].state != RoomState.OCCUPIED


def test_reset_forgets_everything():
    model = RuleBasedOccupancyModel()
    feed(model, 0.6, 200)
    model.reset()
    prediction = model.predict(OccupancyFeatures(timestamp=T0, acoustic_level=0.6))
    assert prediction.state == RoomState.UNCERTAIN


@pytest.mark.parametrize(
    "kwargs",
    [
        {"on_threshold": 0.1, "off_threshold": 0.2},
        {"on_threshold": 0.3, "off_threshold": 0.15, "saturation_level": 0.2},
        {"max_confidence": 0.4},
        {"window_seconds": 0},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        OccupancyConfig(**kwargs)


def test_prediction_exposes_model_name_for_future_ml_replacement():
    model = RuleBasedOccupancyModel()
    prediction = model.predict(OccupancyFeatures(timestamp=T0, acoustic_level=0.3))
    assert prediction.model_name == "rule_based_v1"
    assert isinstance(model, OccupancyModel)
