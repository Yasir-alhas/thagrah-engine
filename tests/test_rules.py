import json
from pathlib import Path

from thagrah_engine.engine import analyze
from thagrah_engine.scene import Scene, load_scene

SCENES = Path(__file__).resolve().parents[1] / "scenes"


def rules_of(result):
    return [f["rule_id"] for f in result["findings"]]


def test_office_finds_route_to_server_as_critical():
    r = analyze(load_scene(SCENES / "office.json"))
    route = [f for f in r["findings"] if f["rule_id"] == "ROUTE"]
    assert route and route[0]["severity"] == "حرج"
    assert "غرفة الخوادم" in route[0]["title"]
    assert "g_loading" in route[0]["evidence"]["doors"]


def test_office_checks_camera_law_and_perimeter():
    r = analyze(load_scene(SCENES / "office.json"))
    ids = rules_of(r)
    assert "A2" in ids and "PERIM" in ids
    places = [f["zone"] for f in r["findings"] if f["rule_id"] == "A2"]
    assert "بوابة الشحن الخلفية" in places and "مخرج الطوارئ" in places


def test_booth_blind_spot_next_to_prize_and_no_camera_law():
    r = analyze(load_scene(SCENES / "booth.json"))
    ids = rules_of(r)
    assert "A2" not in ids
    assert corridor_hidden(r)  # the 50 cm corridor left of the prize box


def corridor_hidden(result) -> bool:
    from shapely.geometry import Point, Polygon
    return any(f["rule_id"] == "BLIND" and len(f["evidence"]["polygon"]) > 2
               and Polygon(f["evidence"]["polygon"]).buffer(1).contains(Point(260, 300))
               for f in result["findings"])


def test_moving_booth_camera_removes_corridor_blind_spot():
    s = load_scene(SCENES / "booth.json")
    assert corridor_hidden(analyze(s))
    after = analyze(s, cameras=[{"id": "C1", "x": 240, "y": 100, "angle": 90}])
    assert not corridor_hidden(after)


def test_no_cameras_does_not_crash():
    r = analyze(load_scene(SCENES / "office.json"), cameras=[])
    assert len(r["findings"]) > 5


def test_same_input_same_output():
    s = load_scene(SCENES / "office.json")
    assert json.dumps(analyze(s)["findings"], ensure_ascii=False) == json.dumps(analyze(s)["findings"], ensure_ascii=False)


def test_emergency_exit_fix_never_locks():
    r = analyze(load_scene(SCENES / "office.json"))
    for f in r["findings"]:
        if "طوارئ" in f["title"]:
            assert "قفل" not in f["action"]


def test_camera_in_toilet_is_flagged():
    data = json.loads((SCENES / "booth.json").read_text(encoding="utf-8"))
    data["rooms"].append({"id": "wc", "name": "دورة مياه", "type": "toilet",
                          "polygon": [[380, 250], [470, 250], [470, 330], [380, 330]]})
    r = analyze(Scene.model_validate(data))
    assert "A6" in rules_of(r)


def test_app_contract_fields():
    r = analyze(load_scene(SCENES / "office.json"))
    f = r["findings"][0]
    for k in ("id", "title", "x", "y", "severity", "zone", "category", "confidence", "reason",
              "scenario", "action", "status", "rule_id", "regulation_ref", "evidence", "monitor"):
        assert k in f
    assert f["severity"] in ("حرج", "عالٍ", "متوسط")
    assert 0 <= f["x"] <= 800 and 0 <= f["y"] <= 500
