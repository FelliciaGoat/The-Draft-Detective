"""Energy-saving ESTIMATE engine (deliberately simple and transparent).

    estimated_energy_saved_kwh = hvac_power_kw x avoided_runtime_hours

Everything returned here is an ESTIMATE, labelled `basis="estimated"` and `is_measured=False`.
No savings percentages are invented. "Measured" savings need a power meter and a baseline and
are not implemented in the MVP (the API keeps a separate, always-null field for them).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.analytics import ENERGY_DISCLAIMER


@dataclass(frozen=True)
class EnergyEstimate:
    """Result of an estimate. `avoided_runtime_hours` is interpreted as hours PER DAY."""

    hvac_power_kw: float
    avoided_runtime_hours_per_day: float
    estimated_energy_saved_kwh: float
    estimated_daily_savings_kwh: float
    estimated_monthly_savings_kwh: float
    estimated_annual_savings_kwh: float
    assumptions: dict[str, float] = field(default_factory=dict)
    basis: str = "estimated"
    is_measured: bool = False
    disclaimer: str = ENERGY_DISCLAIMER


def estimate_energy_savings(
    hvac_power_kw: float,
    avoided_runtime_hours: float,
    days_per_month: float = 30.0,
    days_per_year: float = 365.0,
) -> EnergyEstimate:
    """Estimate savings if the HVAC would have run `avoided_runtime_hours` every day in a vacant room.

    Raises ValueError for negative power/hours or more than 24 hours per day.
    """
    if hvac_power_kw < 0:
        raise ValueError("hvac_power_kw must be >= 0")
    if not 0 <= avoided_runtime_hours <= 24:
        raise ValueError("avoided_runtime_hours (per day) must be between 0 and 24")

    kwh = hvac_power_kw * avoided_runtime_hours
    return EnergyEstimate(
        hvac_power_kw=hvac_power_kw,
        avoided_runtime_hours_per_day=avoided_runtime_hours,
        estimated_energy_saved_kwh=round(kwh, 4),
        estimated_daily_savings_kwh=round(kwh, 4),
        estimated_monthly_savings_kwh=round(kwh * days_per_month, 4),
        estimated_annual_savings_kwh=round(kwh * days_per_year, 4),
        assumptions={
            "days_per_month": days_per_month,
            "days_per_year": days_per_year,
            "assumes_same_avoided_runtime_every_day": 1.0,
        },
    )


def energy_for_interval_kwh(hvac_power_kw: float, interval_seconds: float) -> float:
    """ESTIMATED energy for one time slice: power (kW) x duration (hours)."""
    if hvac_power_kw < 0 or interval_seconds < 0:
        raise ValueError("power and interval must be >= 0")
    return hvac_power_kw * interval_seconds / 3600.0
