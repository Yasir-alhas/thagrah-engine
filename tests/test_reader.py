import json
from pathlib import Path

from thagrah_engine.engine import analyze
from thagrah_engine.reader import compare_rooms, detections_to_scene, parse_detections
from thagrah_engine.scene import load_scene

SCENES = Path(__file__).resolve().parents[1] / "scenes"


def test_recorded_reader_draft_rebuilds_a_usable_scene():
    dets = json.loads((SCENES / "office.reader-draft.json").read_text(encoding="utf-8"))["detections"]
    s = detections_to_scene(dets)
    truth = load_scene(SCENES / "office.json")
    assert compare_rooms(s, truth)["rooms_found_iou50"] >= 9
    assert {r.name for r in s.rooms if r.sensitive} >= {"غرفة الخوادم", "الخزنة"}
    res = analyze(s, cameras=[c.model_dump() for c in truth.cameras])
    assert any(f["rule_id"] == "ROUTE" and "غرفة الخوادم" in f["title"] for f in res["findings"])


def test_parse_survives_a_cut_off_list():
    text = '```json\n[{"label": "مكتب 1", "kind": "room", "bbox_2d": [1, 2, 3, 4]}, {"label": "مك'
    assert parse_detections(text) == [{"label": "مكتب 1", "kind": "room", "bbox_2d": [1, 2, 3, 4]}]
