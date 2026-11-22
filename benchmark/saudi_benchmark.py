"""Saudi compliance benchmark for the Phase 1 engine.

Every case is a small plan built with a KNOWN answer, so the ground truth does not come from
the engine itself:
- compliant: a camera is placed 3-6 m in front of the required location, facing it;
- violation: the camera is missing, faces away, sits behind a wall, or is too far.

Clauses covered:
- Implementing Regulation of the Surveillance Cameras Law, Art. 2(1) items أ..ع (16 location types)
- Law, Art. 6 (cameras banned inside toilets, changing rooms, medical rooms)
- Layered access to a sensitive room (route with / without access control)
- SBC 201 Ch. 10 guardrail: the fix for an emergency exit never locks it

Run:  python -m benchmark.saudi_benchmark --seeds 10
Writes benchmark/results.json and benchmark/RESULTS.md.
What this measures: whether the engine applies each clause correctly on varied layouts.
What it does not measure: agreement with a human expert on real plans (use eval/score.py).
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from thagrah_engine.engine import analyze
from thagrah_engine.rules import LAW_ITEMS, LOCK_WORDS
from thagrah_engine.scene import Scene

OUT = Path(__file__).resolve().parent
M = 5.0  # px per metre

# letter -> (kind, room type, door type, indoor)
ITEMS = {
    "أ": ("door", "lobby_room", "main", True),
    "ب": ("area", "storage", None, True),
    "ج": ("area", "corridor", None, True),
    "د": ("area", "reception", None, True),
    "هـ": ("area", "atm", None, True),
    "و": ("door", "meeting", "emergency_exit", True),
    "ز": ("door", "parking", "parking_entrance", False),
    "ح": ("door", "server", "internal", True),
    "ط": ("area", "dropoff", None, False),
    "ي": ("area", "loading", None, True),
    "ك": ("area", "gas", None, True),
    "ل": ("area", "electrical", None, True),
    "م": ("area", "water_tank", None, True),
    "ن": ("area", "hvac", None, True),
    "س": ("area", "fuel", None, False),
    "ع": ("area", "stairs", None, True),
}
VARIANTS = ["compliant", "missing", "facing_away", "behind_wall", "too_far"]


def rect(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def make_case(letter: str, variant: str, rng: random.Random) -> tuple[Scene, bool]:
    kind, rtype, dtype, indoor = ITEMS[letter]
    w, h = rng.randint(90, 180), rng.randint(70, 130)
    x0, y0 = rng.randint(230, 560 - w), rng.randint(130, 360 - h)
    rooms = [{"id": "R", "name": "المكان المطلوب", "type": "lobby" if rtype == "lobby_room" else rtype,
              "polygon": rect(x0, y0, w, h), "indoor": indoor}]
    doors = []
    if rtype == "lobby_room":
        rooms[0]["type"] = "office"  # an entrance hall that is not itself a law area
    if kind == "door":
        dx = rng.randint(x0 + 20, x0 + w - 20)
        door_at = [dx, y0 + h]
        if letter == "ح":
            rooms.append({"id": "H", "name": "ممر", "type": "office", "polygon": rect(x0 - 40, y0 + h, w + 80, 60)})
            doors.append({"id": "D", "name": "باب غرفة الخوادم", "type": "internal", "at": door_at, "width": 16,
                          "connects": ["H", "R"]})
            doors.append({"id": "E", "name": "مدخل", "type": "secondary", "at": [x0 - 40, y0 + h + 30], "width": 16,
                          "connects": ["outside", "H"]})
            rooms[0]["sensitive"] = False
        else:
            doors.append({"id": "D", "name": "الباب المطلوب", "type": dtype, "at": door_at, "width": 20,
                          "connects": ["outside", "R"]})
        target = door_at
        # camera inside R, 3-6 m in front of the door, facing it
        dist = rng.uniform(3, 6) * M
        cx, cy = dx + rng.uniform(-10, 10), y0 + h - dist
        face = math.degrees(math.atan2(target[1] - cy, target[0] - cx))
    else:
        if letter == "ج":  # corridors are long and narrow
            w, h = rng.randint(200, 320), rng.randint(28, 40)
            x0, y0 = rng.randint(200, 760 - w - 20), rng.randint(150, 330)
            rooms[0]["polygon"] = rect(x0, y0, w, h)
            cx, cy = x0 + 4, y0 + h / 2
            target = [x0 + w, y0 + h / 2]
        else:
            cx, cy = x0 + 4, y0 + 4
            target = [x0 + w / 2, y0 + h / 2]
        doors.append({"id": "D", "name": "باب", "type": "secondary", "at": [x0 + w / 2, y0 + h], "width": 16,
                      "connects": ["outside", "R"]})
        face = math.degrees(math.atan2(target[1] - cy, target[0] - cx)) + rng.uniform(-8, 8)
    cam = {"id": "C1", "name": "كاميرا", "x": round(cx, 1), "y": round(cy, 1), "angle": round(face, 1),
           "range_m": 60 if letter == "ج" else (40 if kind == "area" else None)}
    if cam["range_m"] is None:
        cam.pop("range_m")
    cams = [cam]
    if variant == "missing":
        cams = []
    elif variant == "facing_away":
        cam["angle"] = round(face + 180, 1)
    elif variant == "behind_wall":
        if indoor:
            # same direction, but mounted outside the room's far wall: the wall blocks the view
            cam["x"], cam["y"] = (x0 - 12, cy) if kind == "area" else (cx, y0 - 12)
            cam["angle"] = round(math.degrees(math.atan2(target[1] - cam["y"], target[0] - cam["x"])), 1)
            rooms.append({"id": "B", "name": "غرفة مجاورة", "type": "office",
                          "polygon": rect(x0 - 60, y0 - 60, w + 120, 60) if kind == "door" else rect(x0 - 60, y0, 60, h)})
        else:
            cams = []  # outdoor: no wall to hide behind, treat as missing
    elif variant == "too_far":
        # 40 m away on the line of sight, outside the camera range / identification range
        ang = math.radians(face + 180)
        cam["x"], cam["y"] = target[0] + math.cos(ang) * 40 * M, target[1] + math.sin(ang) * 40 * M
        cam["x"], cam["y"] = round(min(max(cam["x"], 2), 798), 1), round(min(max(cam["y"], 2), 498), 1)
        cam["angle"] = round(math.degrees(math.atan2(target[1] - cam["y"], target[0] - cam["x"])), 1)
        cam.pop("range_m", None)
        if math.dist((cam["x"], cam["y"]), target) < 26 * M:  # clipped by the image edge: not a fair case
            return None, False
    data = {"meta": {"id": f"bench-{letter}-{variant}", "name": "bench", "px_per_m": M, "law_scope": True,
                     "facility_category": "جهة حكومية"},
            "rooms": rooms, "doors": doors, "cameras": cams}
    return Scene.model_validate(data), variant != "compliant"


def flagged(result: dict, letter: str) -> bool:
    return any(f["rule_id"] == "A2" and f"(1-{letter})" in f["regulation_ref"] for f in result["findings"])


def banned_case(violation: bool, rng: random.Random) -> Scene:
    x0, y0 = rng.randint(250, 450), rng.randint(150, 250)
    rooms = [{"id": "W", "name": "دورة مياه", "type": rng.choice(["toilet", "changing_room", "medical_exam"]),
              "polygon": rect(x0, y0, 80, 70)},
             {"id": "H", "name": "ممر", "type": "office", "polygon": rect(x0 - 100, y0 + 70, 280, 60)}]
    doors = [{"id": "D", "name": "باب", "type": "internal", "at": [x0 + 40, y0 + 70], "width": 16, "connects": ["H", "W"]}]
    if violation:
        cam = {"id": "C1", "x": x0 + 40, "y": y0 + 100, "angle": -90}  # in the corridor, looking into the room
    else:
        cam = {"id": "C1", "x": x0 + 40, "y": y0 + 100, "angle": 90}   # same spot, looking away
    return Scene.model_validate({"meta": {"id": "bench-A6", "name": "bench", "px_per_m": M, "law_scope": True},
                                 "rooms": rooms, "doors": doors, "cameras": [cam]})


def route_case(violation: bool, rng: random.Random) -> Scene:
    x0 = rng.randint(220, 400)
    rooms = [{"id": "L", "name": "البهو", "type": "office", "polygon": rect(x0, 300, 200, 80)},
             {"id": "S", "name": "غرفة الخوادم", "type": "server", "sensitive": True, "polygon": rect(x0, 200, 200, 100)}]
    doors = [{"id": "E", "name": "المدخل", "type": "main", "at": [x0 + 100, 380], "width": 20, "connects": ["outside", "L"]},
             {"id": "D", "name": "باب الخوادم", "type": "internal", "at": [x0 + rng.randint(30, 170), 300], "width": 16,
              "connects": ["L", "S"], "controlled": not violation}]
    return Scene.model_validate({"meta": {"id": "bench-route", "name": "bench", "px_per_m": M, "law_scope": True},
                                 "rooms": rooms, "doors": doors, "cameras": []})


def run(seeds: int) -> dict:
    rng = random.Random(2026)
    rows = {}
    exit_fixes, exit_locks = 0, 0
    for letter in ITEMS:
        tp = fn = fp = tn = 0
        for _ in range(seeds):
            for v in VARIANTS:
                scene, is_violation = make_case(letter, v, rng)
                if scene is None:
                    continue
                res = analyze(scene)
                hit = flagged(res, letter)
                if letter == "و" and hit:
                    for f in res["findings"]:
                        if "(1-و)" in f["regulation_ref"]:
                            exit_fixes += 1
                            exit_locks += any(w in f["action"] for w in LOCK_WORDS)
                if is_violation:
                    tp += hit
                    fn += not hit
                else:
                    fp += hit
                    tn += not hit
        rows[f"م2 (1-{letter})"] = {"clause": LAW_ITEMS[letter][0], "tp": tp, "fn": fn, "fp": fp, "tn": tn}
    for name, maker, rule in (("نظام الكاميرات م6 (أماكن محظورة)", banned_case, "A6"),
                              ("الحماية بالطبقات (مسار بلا تحكم دخول)", route_case, "ROUTE")):
        tp = fn = fp = tn = 0
        for _ in range(seeds * 2):
            for violation in (True, False):
                res = analyze(maker(violation, rng))
                hit = any(f["rule_id"] == rule for f in res["findings"])
                if violation:
                    tp += hit
                    fn += not hit
                else:
                    fp += hit
                    tn += not hit
        rows[name] = {"clause": rule, "tp": tp, "fn": fn, "fp": fp, "tn": tn}
    tot = {k: sum(r[k] for r in rows.values()) for k in ("tp", "fn", "fp", "tn")}
    n = sum(tot.values())
    summary = {
        "cases": n,
        "detection_rate": round(tot["tp"] / max(tot["tp"] + tot["fn"], 1), 4),
        "false_alarm_rate": round(tot["fp"] / max(tot["fp"] + tot["tn"], 1), 4),
        "accuracy": round((tot["tp"] + tot["tn"]) / max(n, 1), 4),
        "exit_fixes_checked": exit_fixes, "exit_fixes_that_lock": exit_locks,
    }
    return {"summary": summary, "per_clause": rows, "seeds": seeds}


def write_report(res: dict) -> str:
    s = res["summary"]
    lines = ["# Saudi compliance benchmark", "",
             f"{s['cases']} generated cases ({res['seeds']} random layouts per clause and variant).", "",
             f"- **Detection rate (violations flagged):** {s['detection_rate'] * 100:.1f}%",
             f"- **False-alarm rate (compliant plans flagged):** {s['false_alarm_rate'] * 100:.1f}%",
             f"- **Accuracy:** {s['accuracy'] * 100:.1f}%",
             f"- **Emergency-exit fixes that recommend locking (SBC 201 Ch. 10 guardrail):** "
             f"{s['exit_fixes_that_lock']} of {s['exit_fixes_checked']}", "",
             "| Clause | Requirement | Violations caught | False alarms |", "|---|---|---|---|"]
    for k, r in res["per_clause"].items():
        lines.append(f"| {k} | {r['clause']} | {r['tp']}/{r['tp'] + r['fn']} | {r['fp']}/{r['fp'] + r['tn']} |")
    lines += ["", "What this measures: whether each Saudi clause is applied correctly on varied layouts with a known answer.",
              "It is not agreement with a human expert on real plans; run `eval/score.py` for that."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    a = ap.parse_args()
    res = run(a.seeds)
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "RESULTS.md").write_text(write_report(res), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False))
    for k, r in res["per_clause"].items():
        print(k, r)
