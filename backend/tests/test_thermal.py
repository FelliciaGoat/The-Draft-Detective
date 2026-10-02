"""Thermal anomaly engine tests."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.thermal import (
    ThermalAnalyzer,
    ThermalConfig,
    ThermalResult,
    compute_delta_temperature,
    instantaneous_score,
)

T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
CFG = ThermalConfig()


def feed(analyzer: ThermalAnalyzer, room: float, edge: float, seconds: int, start: datetime = T0, interval: int = 10):
    """Feed constant temperatures; return (results, next_start_time)."""
    results = [
        analyzer.update(start + timedelta(seconds=i * interval), room, edge) for i in range(seconds // interval)
    ]
    return results, start + timedelta(seconds=seconds)


def test_delta_is_absolute_and_symmetric():
    assert compute_delta_temperature(24.8, 29.6) == pytest.approx(4.8)
    assert compute_delta_temperature(29.6, 24.8) == pytest.approx(4.8)


@pytest.mark.parametrize("delta,expected", [(0.0, 0.0), (2.0, 0.0), (5.0, 0.5), (8.0, 1.0), (15.0, 1.0)])
def test_instantaneous_score_maps_delta_to_zero_one(delta, expected):
    assert instantaneous_score(delta, CFG) == pytest.approx(expected)


def test_small_delta_gives_low_anomaly_and_no_candidate():
    results, _ = feed(ThermalAnalyzer(), 24.0, 25.0, 3600)
    assert results[-1].thermal_anomaly_score == 0.0
    assert results[-1].leak_candidate is False


def test_moderate_persistent_delta_gives_medium_score_but_never_a_candidate():
    results, _ = feed(ThermalAnalyzer(), 24.0, 28.5, 3600)  # delta 4.5 -> score ~0.42, below the 0.5 flag
    assert 0.3 < results[-1].thermal_anomaly_score < 0.5
    assert results[-1].leak_candidate is False


def test_large_delta_is_not_called_a_candidate_until_it_persists():
    analyzer = ThermalAnalyzer()
    results, _ = feed(analyzer, 24.0, 32.0, 400)  # delta 8 from the first reading
    assert results[0].thermal_anomaly_score == 1.0
    assert results[0].leak_candidate is False  # a single abnormal reading is never an alert
    assert results[29].leak_candidate is False  # 290 s
    assert results[30].leak_candidate is True  # 300 s = persistence period reached
    assert results[30].thermal_anomaly_score > 0.9


def test_one_abnormal_reading_among_normal_ones_does_not_trigger():
    analyzer = ThermalAnalyzer()
    _, t = feed(analyzer, 24.0, 25.0, 300)
    spike = analyzer.update(t, 24.0, 40.0)
    after, _ = feed(analyzer, 24.0, 25.0, 600, start=t + timedelta(seconds=10))
    assert spike.leak_candidate is False
    assert not any(r.leak_candidate for r in after)


def test_candidate_clears_after_the_differential_disappears():
    analyzer = ThermalAnalyzer()
    _, t = feed(analyzer, 24.0, 32.0, 400)
    normal, _ = feed(analyzer, 24.0, 25.0, 300, start=t)
    assert normal[-1].leak_candidate is False
    assert normal[-1].elevated_seconds == 0.0


def test_hysteresis_keeps_the_candidate_while_score_is_between_clear_and_flag():
    analyzer = ThermalAnalyzer()
    _, t = feed(analyzer, 24.0, 32.0, 400)  # flagged
    middle, _ = feed(analyzer, 24.0, 28.5, 600, start=t)  # score settles near 0.42: between 0.35 and 0.5
    assert middle[-1].leak_candidate is True


def test_missing_temperature_result():
    result = ThermalResult.no_data()
    assert result.has_data is False
    assert result.thermal_anomaly_score is None and result.leak_candidate is False


def test_explanations_never_claim_a_confirmed_leak():
    analyzer = ThermalAnalyzer()
    results, _ = feed(analyzer, 24.0, 32.0, 400)
    candidate = results[-1].explanation
    assert "candidate" in candidate.lower() and "not a confirmed leak" in candidate.lower()
    for result in results[:29]:
        assert "leak" not in result.explanation.lower()


def test_thresholds_are_configurable():
    strict = ThermalAnalyzer(ThermalConfig(persistence_seconds=60))
    results, _ = feed(strict, 24.0, 32.0, 100)
    assert results[6].leak_candidate is True


@pytest.mark.parametrize(
    "kwargs",
    [{"delta_low_c": 5, "delta_high_c": 3}, {"clear_threshold": 0.9, "flag_threshold": 0.5}, {"flag_threshold": 1.5}],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ThermalConfig(**kwargs)
