import json
from pathlib import Path

import pytest

from thagrah_engine.graph import route_to
from thagrah_engine.scene import Scene, load_scene

SCENES = Path(__file__).resolve().parents[1] / "scenes"


def test_office_route_to_server_goes_through_loading_gate_with_no_control():
    s = load_scene(SCENES / "office.json")
    r = route_to(s, "server")
    assert r.doors[0] == "g_loading"
    assert "d_recv" in r.doors and r.doors[-1] == "d_server"
    assert r.controlled == 0


def test_controlled_door_breaks_the_open_route():
    data = json.loads((SCENES / "office.json").read_text(encoding="utf-8"))
    for d in data["doors"]:
        if d["id"] == "d_server":
            d["controlled"] = True
    r = route_to(Scene.model_validate(data), "server")
    assert r.controlled == 1


def test_door_to_unknown_room_is_rejected():
    data = json.loads((SCENES / "office.json").read_text(encoding="utf-8"))
    data["doors"][0]["connects"] = ["outside", "nowhere"]
    with pytest.raises(ValueError, match="nowhere"):
        Scene.model_validate(data)
