"""Sensor fusion tests (pure functions, no database)."""

from app.core.enums import RecommendedAction, RoomState
from app.services.occupancy import OccupancyPrediction
from app.services.sensor_fusion import FusionConfig, FusionInput, fuse
from app.services.thermal import ThermalResult


def occ(state: RoomState, confidence: float = 0.8) -> OccupancyPrediction:
    return OccupancyPrediction(
        state=state,
        occupancy_confidence=confidence,
        activity_score=0.4,
        evidence="high",
        reason="test",
        model_name="test",
    )


def thermal(leak: bool = False, has_data: bool = True, score: float = 0.1) -> ThermalResult:
    if not has_data:
        return ThermalResult.no_data()
    return ThermalResult(
        has_data=True,
        delta_temperature=1.0,
        thermal_anomaly_score=score,
        leak_candidate=leak,
        elevated_seconds=0.0,
        explanation="test",
    )


def test_no_data_at_all_is_insufficient_and_uncertain():
    result = fuse(FusionInput(thermal=thermal(has_data=False), occupancy=None))
    assert result.room_state == RoomState.UNCERTAIN
    assert result.recommended_action == RecommendedAction.INSUFFICIENT_DATA


def test_occupied_room_means_normal_operation():
    result = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.OCCUPIED, 0.86)))
    assert result.room_state == RoomState.OCCUPIED
    assert result.recommended_action == RecommendedAction.NORMAL_OPERATION
    assert result.occupancy_confidence == 0.86


def test_vacant_with_hvac_running_recommends_energy_saving():
    result = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.VACANT, 0.05), hvac_on=True))
    assert result.room_state == RoomState.VACANT
    assert result.recommended_action == RecommendedAction.ENERGY_SAVING_MODE


def test_vacant_with_hvac_off_has_nothing_to_save():
    result = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.VACANT, 0.05), hvac_on=False))
    assert result.recommended_action == RecommendedAction.NORMAL_OPERATION


def test_vacant_with_unknown_hvac_assumes_it_may_be_running_by_default():
    result = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.VACANT, 0.05), hvac_on=None))
    assert result.recommended_action == RecommendedAction.ENERGY_SAVING_MODE
    assert any("HVAC" in note for note in result.notes)


def test_vacant_with_unknown_hvac_can_be_configured_to_be_cautious():
    config = FusionConfig(assume_hvac_on_when_unknown=False)
    result = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.VACANT, 0.05)), config)
    assert result.recommended_action == RecommendedAction.NORMAL_OPERATION


def test_uncertain_occupancy_maintains_a_safe_state():
    result = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.UNCERTAIN, 0.5), hvac_on=True))
    assert result.room_state == RoomState.UNCERTAIN
    assert result.recommended_action == RecommendedAction.MAINTAIN_SAFE_STATE


def test_leak_candidate_while_occupied_recommends_inspection():
    result = fuse(FusionInput(thermal=thermal(leak=True, score=0.76), occupancy=occ(RoomState.OCCUPIED, 0.86)))
    assert result.room_state == RoomState.OCCUPIED
    assert result.leak_candidate is True
    assert result.recommended_action == RecommendedAction.INSPECT_ENVELOPE
    assert result.thermal_anomaly_score == 0.76


def test_leak_candidate_while_vacant_recommends_inspection_not_energy_saving():
    """The demo scenario: vacant room, HVAC on, then the wall temperature climbs."""
    result = fuse(FusionInput(thermal=thermal(leak=True), occupancy=occ(RoomState.VACANT, 0.05), hvac_on=True))
    assert result.room_state == RoomState.VACANT
    assert result.recommended_action == RecommendedAction.INSPECT_ENVELOPE


def test_temperatures_without_acoustics_cannot_estimate_occupancy():
    result = fuse(FusionInput(thermal=thermal(), occupancy=None))
    assert result.room_state == RoomState.UNCERTAIN
    assert result.recommended_action == RecommendedAction.INSUFFICIENT_DATA


def test_leak_candidate_without_acoustics_still_recommends_inspection_with_uncertain_state():
    result = fuse(FusionInput(thermal=thermal(leak=True), occupancy=None))
    assert result.room_state == RoomState.UNCERTAIN
    assert result.recommended_action == RecommendedAction.INSPECT_ENVELOPE


def test_acoustics_only_without_temperatures_still_works():
    result = fuse(FusionInput(thermal=thermal(has_data=False), occupancy=occ(RoomState.OCCUPIED)))
    assert result.room_state == RoomState.OCCUPIED
    assert result.thermal_anomaly_score is None


def test_contradiction_vacant_but_high_co2_falls_back_to_safe_state():
    result = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.VACANT, 0.05), hvac_on=True, co2_ppm=1400))
    assert result.room_state == RoomState.UNCERTAIN
    assert result.recommended_action == RecommendedAction.MAINTAIN_SAFE_STATE


def test_high_co2_supports_occupied_state():
    base = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.OCCUPIED, 0.7)))
    boosted = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.OCCUPIED, 0.7), co2_ppm=1300))
    assert boosted.occupancy_confidence > base.occupancy_confidence


def test_humidity_note_only_appears_with_a_leak_candidate():
    calm = fuse(FusionInput(thermal=thermal(), occupancy=occ(RoomState.OCCUPIED), humidity=85))
    leaky = fuse(FusionInput(thermal=thermal(leak=True), occupancy=occ(RoomState.OCCUPIED), humidity=85))
    assert not any("humidity" in n.lower() for n in calm.notes)
    assert any("humidity" in n.lower() for n in leaky.notes)
