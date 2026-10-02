"""Energy estimate tests."""

import pytest

from app.services.energy import energy_for_interval_kwh, estimate_energy_savings


def test_basic_formula_power_times_hours():
    estimate = estimate_energy_savings(hvac_power_kw=1.5, avoided_runtime_hours=4)
    assert estimate.estimated_energy_saved_kwh == pytest.approx(6.0)


def test_daily_monthly_and_annual_projections():
    estimate = estimate_energy_savings(1.5, 4)
    assert estimate.estimated_daily_savings_kwh == pytest.approx(6.0)
    assert estimate.estimated_monthly_savings_kwh == pytest.approx(180.0)
    assert estimate.estimated_annual_savings_kwh == pytest.approx(2190.0)


def test_zero_runtime_or_power_saves_nothing():
    assert estimate_energy_savings(2.0, 0).estimated_energy_saved_kwh == 0
    assert estimate_energy_savings(0, 5).estimated_energy_saved_kwh == 0


def test_result_is_clearly_labelled_as_an_estimate_not_a_measurement():
    estimate = estimate_energy_savings(1.5, 4)
    assert estimate.basis == "estimated"
    assert estimate.is_measured is False
    assert "ESTIMATE" in estimate.disclaimer
    assert "NOT a measured" in estimate.disclaimer


def test_assumptions_are_visible():
    estimate = estimate_energy_savings(1.5, 4, days_per_month=26)
    assert estimate.assumptions["days_per_month"] == 26
    assert estimate.estimated_monthly_savings_kwh == pytest.approx(6.0 * 26)


@pytest.mark.parametrize("power,hours", [(-1, 2), (1, -0.5), (1, 24.5)])
def test_invalid_inputs_are_rejected(power, hours):
    with pytest.raises(ValueError):
        estimate_energy_savings(power, hours)


def test_interval_energy_is_power_times_duration_in_hours():
    assert energy_for_interval_kwh(2.0, 1800) == pytest.approx(1.0)
    assert energy_for_interval_kwh(1.5, 0) == 0


def test_negative_interval_is_rejected():
    with pytest.raises(ValueError):
        energy_for_interval_kwh(1.5, -10)
