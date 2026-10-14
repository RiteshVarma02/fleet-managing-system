"""Mission input validation (Plus-button form and text box)."""

import pytest
from pydantic import ValidationError

from app.schemas.task import MissionStart, TaskRequestCreate, WaypointSend


def test_stops_are_trimmed_and_ordered():
    m = MissionStart(robot_id="r1", stops=[" WP_1 ", "WP_2", "WP_5"], repeats=50, mode="step")
    assert m.stops == ["WP_1", "WP_2", "WP_5"] and m.repeats == 50 and m.mode == "step"


@pytest.mark.parametrize("stops", [[], [""], ["A", "  "]])
def test_empty_stops_rejected(stops):
    with pytest.raises(ValidationError):
        MissionStart(robot_id="r1", stops=stops)


def test_too_many_stops_rejected():
    with pytest.raises(ValidationError):
        MissionStart(robot_id="r1", stops=[f"W{i}" for i in range(51)])


def test_mode_must_be_known():
    with pytest.raises(ValidationError):
        MissionStart(robot_id="r1", stops=["A"], mode="whenever")


def test_defaults_are_continuous_single_run():
    m = MissionStart(robot_id="r1", stops=["A"])
    assert (m.mode, m.repeats) == ("continuous", 1)


def test_waypoint_box_trims_and_rejects_blank():
    assert WaypointSend(robot_id="r1", waypoint="  Dock_A ").waypoint == "Dock_A"
    with pytest.raises(ValidationError):
        WaypointSend(robot_id="r1", waypoint="   ")


def test_scheduled_request_carries_stops_and_mode():
    r = TaskRequestCreate(stops=["A", "B"], mode="step", repeats=3)
    assert r.stops == ["A", "B"] and r.mode == "step"
