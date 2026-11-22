"""AI blueprint reader: a local vision model (Qwen3-VL instruct via Ollama) drafts a scene from an image.

Step 1 (model): find every labelled room/area, door or gate bar, and the site fence, as boxes
         in Qwen's native 0-1000 grid.
Step 2 (code):  turn the Arabic labels into room types, mark sensitive rooms, connect doors to
         the rooms they touch, and add assumed doors from rooms to the corridor (marked
         drawn=false, so findings that rely on them get lower confidence).
A person must confirm the draft before findings are used (the poster's "Expert approval").
"""
from __future__ import annotations

import base64
import io
import json
import os
import re

import httpx
from PIL import Image
from shapely.geometry import Point, Polygon, box

from .scene import Scene

OLLAMA = os.environ.get("THAGRAH_OLLAMA", "http://127.0.0.1:11434")
VLM = os.environ.get("THAGRAH_VLM", "qwen3-vl:8b-instruct")
W, H = 800, 500

PROMPT = """Detect every labeled room or area in this floor plan (the Arabic text labels inside rectangles), every short coloured door/gate bar with its label, and the dashed site fence.
Output a JSON list. Each item: {"label": "<text as written>", "kind": "room"|"door"|"fence", "bbox_2d": [x1, y1, x2, y2]}."""

# Arabic keyword -> (type, sensitive, indoor)
ROOM_WORDS = [
    ("خواد", "server", True, True), ("سيرفر", "server", True, True), ("اتصالات", "telecom", True, True),
    ("شبكات", "telecom", True, True), ("خزنة", "vault", True, True), ("أرشيف", "vault", True, True),
    ("تحكم", "security", True, True), ("مراقبة", "security", False, True), ("أمن", "security", False, True),
    ("حراسة", "security", False, True), ("اجتماع", "meeting", False, True), ("مكتب", "office", False, True),
    ("ممر", "corridor", False, True), ("بهو", "lobby", False, True), ("ردهة", "lobby", False, True),
    ("استقبال", "reception", False, True), ("مستودع", "storage", False, True), ("مخزن", "storage", False, True),
    ("ساحة الشحن", "loading", False, False), ("استلام", "loading", False, True), ("تحميل", "loading", False, True),
    ("مواقف", "parking", False, False), ("سيار", "parking", False, False), ("موقف", "parking", False, False), ("كهرباء", "electrical", True, True), ("غاز", "gas", False, True),
    ("خزان", "water_tank", False, True), ("تكييف", "hvac", False, True), ("وقود", "fuel", False, False),
    ("درج", "stairs", False, True), ("سلالم", "stairs", False, True), ("صراف", "atm", False, True),
    ("دورة مياه", "toilet", False, True), ("حمام", "toilet", False, True), ("تبديل", "changing_room", False, True),
    ("ساحة", "yard", False, False),
]
SKIP_WORDS = ("شمال", "مخطط", "مقياس")


def _image_b64(data: bytes) -> str:
    im = Image.open(io.BytesIO(data)).convert("RGB").resize((W, H))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _scale(b) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = [float(v) for v in b]
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    return x1 * W / 1000, y1 * H / 1000, x2 * W / 1000, y2 * H / 1000


def classify(label: str) -> tuple[str, bool, bool]:
    for word, t, sens, indoor in ROOM_WORDS:
        if word in label:
            return t, sens, indoor
    return "other", False, True


def detections_to_scene(dets: list[dict], scene_id: str = "draft") -> Scene:
    rooms, doors, fence = [], [], None
    sens_marks = []
    for d in dets:
        try:
            label, kind = str(d.get("label", "")).strip(), d.get("kind")
            x1, y1, x2, y2 = _scale(d["bbox_2d"])
        except (KeyError, TypeError, ValueError):
            continue
        if any(w in label for w in SKIP_WORDS):
            continue
        if kind == "fence" or "سور" in label:
            fence = [[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]]
        elif kind == "door" or "بوابة" in label or "مخرج" in label or "باب" in label:
            doors.append((label, ((x1 + x2) / 2, (y1 + y2) / 2), max(x2 - x1, y2 - y1)))
        elif "حساس" in label and (x2 - x1) * (y2 - y1) < 3000:
            sens_marks.append(((x1 + x2) / 2, (y1 + y2) / 2))
        elif (x2 - x1) > 8 and (y2 - y1) > 8:
            t, s, indoor = classify(label)
            rooms.append({"id": f"r{len(rooms) + 1}", "name": label, "type": t, "sensitive": s, "indoor": indoor,
                          "polygon": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]})
    # small "sensitive area" sub-labels mark the room they sit in
    for (sx, sy) in sens_marks:
        for r in rooms:
            if Polygon(r["polygon"]).contains(Point(sx, sy)):
                r["sensitive"] = True
    out_rooms = list(rooms)
    if fence:
        out_rooms.append({"id": "site", "name": "ساحة الموقع", "type": "yard", "indoor": False,
                          "polygon": fence[:4]})
    scene_doors = []
    fence_ring = Polygon(fence[:4]).exterior if fence else None

    def touching(pt, tol=14):
        p = Point(pt)
        hits = [r for r in rooms if Polygon(r["polygon"]).distance(p) <= tol]
        return sorted(hits, key=lambda r: Polygon(r["polygon"]).area)

    for i, (label, at, size) in enumerate(doors):
        if fence_ring is not None and fence_ring.distance(Point(at)) <= 15:
            ends, dtype = ("outside", "site"), ("vehicle_gate" if "شحن" in label else "gate")
        else:
            hits = touching(at)
            indoor = [r for r in hits if r["indoor"]]
            if not indoor:
                continue
            dtype = "emergency_exit" if "طوارئ" in label else ("main" if "رئيس" in label else "secondary")
            ends = (indoor[0]["id"], "site" if fence else "outside")
        scene_doors.append({"id": f"d{i + 1}", "name": label, "type": dtype, "at": [at[0], at[1]],
                            "width": max(14.0, min(size, 100.0)), "connects": list(ends)})
    # assumed doors: every indoor room that shares an edge with a corridor opens onto it
    corridors = [r for r in rooms if r["type"] in ("corridor", "lobby")]
    k = 0
    for r in rooms:
        if not r["indoor"] or r["type"] in ("corridor", "lobby"):
            continue
        for c in corridors:
            shared = box(*Polygon(r["polygon"]).bounds).buffer(3).intersection(Polygon(c["polygon"]).boundary)
            if shared.length >= 10:
                mid = shared.interpolate(0.5, normalized=True)
                k += 1
                scene_doors.append({"id": f"a{k}", "name": f"باب {r['name']}", "type": "internal", "at": [mid.x, mid.y],
                                    "width": 14, "connects": [c["id"], r["id"]], "drawn": False})
                break
    # outdoor areas inside the site open onto the yard
    if fence:
        for r in rooms:
            if not r["indoor"]:
                c = Polygon(r["polygon"]).centroid
                scene_doors.append({"id": f"o{r['id']}", "name": f"مدخل {r['name']}", "type": "open",
                                    "at": [c.x, c.y], "width": 1, "connects": ["site", r["id"]], "drawn": False})
    return Scene.model_validate({
        "meta": {"id": scene_id, "name": "مخطط مقروء آلياً (مسودة تحتاج تأكيد)", "px_per_m": 5, "law_scope": True},
        "rooms": out_rooms, "doors": scene_doors, "fence": fence, "cameras": [],
        "notes": {"draft": "قرأه نموذج الرؤية المحلي؛ يجب أن يؤكده شخص قبل الاعتماد"}})


def parse_detections(text: str) -> list[dict]:
    """Keep every well-formed {...} item, even if the list around them is broken or cut off."""
    try:
        data = json.loads(re.search(r"\[.*\]", text, re.S).group(0))
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except (ValueError, AttributeError):
        pass
    out = []
    for m in re.finditer(r"\{[^{}]*\}", text):
        try:
            out.append(json.loads(m.group(0)))
        except ValueError:
            continue
    return out


def read_plan(image: bytes, model: str = VLM, timeout: float = 300) -> dict:
    """Returns {'detections': [...], 'scene': dict|None, 'error': str|None}."""
    try:
        r = httpx.post(f"{OLLAMA}/api/chat", timeout=httpx.Timeout(timeout, connect=2), json={
            "model": model, "stream": False, "options": {"temperature": 0, "seed": 7, "num_predict": 4000},
            "messages": [{"role": "user", "content": PROMPT, "images": [_image_b64(image)]}]})
        r.raise_for_status()
        text = r.json()["message"]["content"]
    except (httpx.HTTPError, ValueError, KeyError) as e:
        return {"detections": None, "scene": None, "error": f"reader unavailable: {e.__class__.__name__}"}
    dets = parse_detections(text)
    if not dets:
        return {"detections": [], "scene": None, "error": "reader returned no detections", "raw": text[:2000]}
    try:
        return {"detections": dets, "scene": detections_to_scene(dets).model_dump(), "error": None}
    except ValueError as e:
        return {"detections": dets, "scene": None, "error": str(e)}


def compare_rooms(draft: Scene, truth: Scene) -> dict:
    """How well the reader's rooms match a hand-checked scene: mean IoU and how many were found."""
    found, ious = 0, []
    for t in truth.rooms:
        if t.type == "yard":
            continue
        tp = Polygon(t.polygon)
        best = max((tp.intersection(Polygon(d.polygon)).area / tp.union(Polygon(d.polygon)).area
                    for d in draft.rooms if d.name.strip() == t.name.strip()), default=0.0)
        ious.append(best)
        found += best >= 0.5
    n = len(ious)
    return {"rooms_in_truth": n, "rooms_found_iou50": found, "mean_iou": round(sum(ious) / n, 3) if n else 0}
