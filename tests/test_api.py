from fastapi.testclient import TestClient

from thagrah_engine.api import app

client = TestClient(app)


def test_analyze_demo_scene_keeps_arabic():
    r = client.post("/analyze", json={"scene_id": "booth"})
    assert r.status_code == 200
    body = r.content.decode("utf-8")
    assert "صندوق الجائزة" in body
    assert r.json()["findings"][0]["severity"] in ("حرج", "عالٍ", "متوسط")


def test_app_cameras_override_scene_cameras():
    r = client.post("/analyze", json={"scene_id": "office", "cameras": []}).json()
    assert r["coverage"] == {}


def test_bad_scene_is_a_clear_422():
    r = client.post("/analyze", json={"scene": {"meta": {"id": "x", "name": "x"},
                                                "doors": [{"id": "d", "name": "d", "at": [1, 1], "connects": ["outside", "nope"]}]}})
    assert r.status_code == 422 and "nope" in r.text


def test_scenes_listed():
    ids = [s["id"] for s in client.get("/scenes").json()]
    assert {"office", "booth"} <= set(ids)
