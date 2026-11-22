from pathlib import Path

from shapely.geometry import Point

from thagrah_engine.geometry import coverage, covered_by, visibility_polygon, wall_segments
from thagrah_engine.scene import load_scene

SCENES = Path(__file__).resolve().parents[1] / "scenes"


def booth():
    return load_scene(SCENES / "booth.json")


def office():
    return load_scene(SCENES / "office.json")


def test_booth_camera_cannot_see_corridor_behind_prize_box():
    s = booth()
    vis = visibility_polygon(s.cameras[0], s)
    assert not vis.contains(Point(260, 300))  # 50 cm corridor, shadowed by the box
    assert vis.contains(Point(480, 330))      # open floor to the side of the box


def test_moving_camera_reveals_corridor():
    s = booth().with_cameras([{"id": "C1", "x": 240, "y": 100, "angle": 90}])
    assert visibility_polygon(s.cameras[0], s).contains(Point(260, 300))


def test_camera_on_wall_line_sees_into_room():
    s = booth().with_cameras([{"id": "C1", "x": 400, "y": 75, "angle": 90}])
    assert visibility_polygon(s.cameras[0], s).area > 10_000


def test_walls_have_gaps_at_doors():
    s = office()
    segs = wall_segments(s)
    # the server-room door at (512,190) must be an opening
    from shapely.geometry import LineString
    door_probe = LineString([(512, 185), (512, 195)])
    assert not any(LineString(seg).intersects(door_probe) for seg in segs)


def test_office_server_door_seen_by_c3_only():
    s = office()
    cov = coverage(s)
    assert covered_by(Point(512, 191), cov) == ["C3"]
