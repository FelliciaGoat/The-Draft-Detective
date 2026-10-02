"""Application configuration.

Every setting can be overridden with an environment variable (or a `.env` file) using the
UPPER_CASE version of the field name, e.g. `OCC_ON_THRESHOLD=0.35`.

All algorithm thresholds live here so nothing is hard-coded inside the services.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # `MQTT_PASSWORD=` (empty) falls back to the default
    )

    # ---- General -----------------------------------------------------------
    app_name: str = "Acoustic Occupancy & Thermal Leak Dual-Tracker"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    seed_demo_data: bool = False

    # ---- Database ----------------------------------------------------------
    # SQLite for development; use e.g. postgresql+psycopg2://user:pass@host:5432/db in production.
    database_url: str = "sqlite:///./occupancy.db"

    # ---- MQTT --------------------------------------------------------------
    mqtt_enabled: bool = False
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_client_id: str = "occupancy-backend"
    # building/{building_id}/room/{room_id}/sensors  ({room_id} is the database id of the room)
    mqtt_topic: str = "building/+/room/+/sensors"

    # ---- Security / CORS ---------------------------------------------------
    device_api_key: str = ""  # required for POST /readings and simulation; never hard-code it
    cors_origins: str = "http://localhost:3000"  # comma-separated

    # ---- Data freshness / dashboard ---------------------------------------
    data_stale_seconds: float = 300.0  # older than this -> the room is reported as "uncertain"
    dashboard_utc_offset_minutes: int = 0  # defines "today" and "this month" (330 = India)

    # ---- Occupancy engine (baseline, rule-based) ---------------------------
    occ_smoothing_seconds: float = 20.0  # EMA time constant applied to raw acoustic level
    occ_window_seconds: float = 120.0  # rolling-average window over the smoothed level
    occ_on_threshold: float = 0.30  # activity >= this counts as "occupied evidence"
    occ_off_threshold: float = 0.15  # activity <= this counts as "vacant evidence"
    occ_saturation_level: float = 0.50  # activity at which confidence stops growing
    occ_occupied_persistence_seconds: float = 30.0  # evidence must last this long -> occupied
    occ_vacant_persistence_seconds: float = 300.0  # evidence must last this long -> vacant
    occ_uncertain_persistence_seconds: float = 600.0  # ambiguous this long -> uncertain
    occ_max_confidence: float = 0.95  # acoustic-only data never reaches 100 % certainty

    # ---- Thermal anomaly engine -------------------------------------------
    thermal_delta_low_c: float = 2.0  # delta-T at/below this -> score 0
    thermal_delta_high_c: float = 8.0  # delta-T at/above this -> score 1
    thermal_smoothing_seconds: float = 60.0
    thermal_flag_threshold: float = 0.5  # smoothed score >= this starts the persistence timer
    thermal_clear_threshold: float = 0.35  # smoothed score < this clears it (hysteresis)
    thermal_persistence_seconds: float = 300.0  # elevated this long -> leak candidate

    # ---- Sensor fusion -----------------------------------------------------
    co2_occupied_ppm: float = 1000.0  # CO2 at/above this is (weak) evidence of people
    humidity_high_pct: float = 70.0
    assume_hvac_on_when_unknown: bool = True

    # ---- Energy estimate ---------------------------------------------------
    # PLACEHOLDER rating: set the real HVAC power of your room (kW) for meaningful estimates.
    default_hvac_power_kw: float = 1.5
    energy_max_interval_seconds: float = 900.0  # gaps longer than this are not counted as savings

    # ---- Simulation --------------------------------------------------------
    simulation_enabled: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origins as a clean list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object (call `get_settings.cache_clear()` in tests)."""
    return Settings()
