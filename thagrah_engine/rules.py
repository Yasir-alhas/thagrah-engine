"""Saudi-grounded weak-point rules. Each rule is plain code: same plan in, same findings out.

Sources (verified 22 Nov 2026, see docs/SAUDI_SOURCES.md):
- Implementing Regulation of the Surveillance Cameras Law (MOI Decision 22688, 1444-11-20 /
  9 Jun 2023), Art. 2(1) items أ..ع: the 16 location types cameras must cover.
- Law on the Use of Security Surveillance Cameras, Art. 2 (who it applies to) and Art. 6
  (rooms where cameras are banned).
- Saudi Building Code SBC 201 Ch. 10 (means of egress) and SBC 801: an exit must stay
  openable, so a fix never locks an emergency exit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from .geometry import camera_params, covered_by, nominal_sector, visibility_polygon, wall_segments
from .graph import room_at, route_to
from .scene import Scene

SEV_RANK = {"حرجة": 0, "عالية": 1, "متوسطة": 2, "منخفضة": 3}
RULE_ORDER = ["ROUTE", "A2", "A6", "BLIND", "ADJ", "MULTI", "GATE", "PERIM", "SPOF", "OBSTRUCT", "GLARE", "LIGHT"]

REG = "اللائحة التنفيذية لنظام استخدام كاميرات المراقبة الأمنية، المادة 2 (1-{l})"
LAW6 = "نظام استخدام كاميرات المراقبة الأمنية، المادة 6"
SBC_EGRESS = "كود البناء السعودي SBC 201 الفصل 10 (وسائل الخروج) · SBC 801"

# Reg. Art. 2(1): letter -> (text, severity, sheet id)
LAW_ITEMS: dict[str, tuple[str, str, str]] = {
    "أ": ("مداخل المنشأة في مدى رؤية التعرّف على الهوية", "عالية", "WP-01"),
    "ب": ("المخازن والمستودعات", "متوسطة", "WP-23"),
    "ج": ("البهو الرئيسي والممرات في كافة الطوابق", "متوسطة", "WP-18"),
    "د": ("مكاتب الاستقبال في مدى رؤية التعرّف على الهوية", "منخفضة", "WP-08"),
    "هـ": ("أجهزة الصراف الآلي", "متوسطة", "WP-28"),
    "و": ("أبواب مخارج الطوارئ ونقاط التجمع وأماكن أجهزة الحريق", "حرجة", "WP-33"),
    "ز": ("مداخل ومخارج مواقف السيارات بمدى قراءة اللوحات", "متوسطة", "WP-06"),
    "ح": ("مداخل غرف الاتصالات والشبكات وغرف الكهرباء", "حرجة", "WP-14"),
    "ط": ("منطقة نزول وصعود الزوار بمدى قراءة اللوحات", "منخفضة", "WP-07"),
    "ي": ("مناطق تفريغ البضائع وتحميلها ومناطق الخدمات", "عالية", "WP-22"),
    "ك": ("مجمع أو غرفة أسطوانات الغاز والمنطقة المحيطة", "عالية", "WP-24"),
    "ل": ("مجمع أو غرفة الكهرباء والمنطقة المحيطة", "عالية", "WP-15"),
    "م": ("مجمع أو غرفة خزان المياه والمنطقة المحيطة", "عالية", "WP-25"),
    "ن": ("مجمع غرفة التكييف المركزي والمنطقة المحيطة", "متوسطة", "WP-26"),
    "س": ("محطات الوقود: المضخات والخزانات وما حولها", "عالية", "WP-27"),
    "ع": ("السلالم والسلالم الكهربائية", "متوسطة", "WP-19"),
}
AREA_LAW = {"storage": "ب", "corridor": "ج", "lobby": "ج", "reception": "د", "atm": "هـ",
            "assembly": "و", "fire_equipment": "و", "dropoff": "ط", "loading": "ي", "service": "ي",
            "gas": "ك", "electrical": "ل", "water_tank": "م", "hvac": "ن", "fuel": "س", "stairs": "ع"}
ENTRANCE_DOORS = {"main", "secondary", "gate", "vehicle_gate"}
ENTRY_ROOMS_LAW_H = {"server", "telecom", "electrical"}
BANNED_ROOMS = {"toilet": "دورة المياه", "changing_room": "غرفة تبديل الملابس", "medical_exam": "غرفة الكشف الطبي",
                "physio": "غرفة العلاج الطبيعي", "operating_room": "غرفة العمليات الطبية"}
LOCK_WORDS = ("قفل", "إقفال", "اقفال", "يُقفل", "يقفل")


@dataclass
class Finding:
    rule: str
    wp: str
    title: str
    x: float
    y: float
    severity_level: str
    zone: str
    category: str
    confidence: str
    regulation_ref: str
    reason: str
    scenario: str
    action: str
    evidence: dict[str, Any] = field(default_factory=dict)
    monitor: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.rule}:{self.wp}:{round(self.x)}:{round(self.y)}"


# ---------------------------------------------------------------- helpers
def _pts(geom) -> list[list[int]]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [[round(x), round(y)] for x, y in geom.exterior.coords]
    if geom.geom_type in ("LineString",):
        return [[round(x), round(y)] for x, y in geom.coords]
    return []


def _largest(geom):
    if geom.is_empty:
        return geom
    parts = getattr(geom, "geoms", [geom])
    polys = [g for g in parts if g.geom_type == "Polygon"]
    return max(polys, key=lambda g: g.area) if polys else geom


class Ctx:
    """Everything the rules share: scene, camera views, units."""

    def __init__(self, scene: Scene, cov: dict[str, Polygon]):
        self.s = scene
        self.cov = cov
        self.cams = {c.id: c for c in scene.cameras}
        self.m = scene.meta.px_per_m
        self.union = unary_union(list(cov.values())) if cov else Polygon()
        self.assumed_cams = "camera_assumption" in scene.notes
        self.free_union = None

    def cam_name(self, cid: str) -> str:
        c = self.cams[cid]
        return f"{cid} ({c.name})" if c.name else cid

    def door_seen_by(self, at, max_m: Optional[float] = None) -> list[str]:
        """Cameras that see someone passing a door: any sample within 5 m of it."""
        r = 5 * self.m
        samples = [Point(at)] + [Point(at[0] + r * math.cos(k * math.pi / 4) * f, at[1] + r * math.sin(k * math.pi / 4) * f)
                                 for k in range(8) for f in (0.5, 1.0)]
        out: list[str] = []
        for p in samples:
            for cid in covered_by(p, self.cov, max_dist=None if max_m is None else max_m * self.m, cams=self.cams):
                if cid not in out and self.faces(cid, at):
                    out.append(cid)
        return sorted(out)

    def faces(self, cid: str, at) -> bool:
        """The camera points toward the door (so it sees faces, not backs)."""
        cam = self.cams[cid]
        if math.dist((cam.x, cam.y), at) < 1:
            return True
        fov, _, _ = camera_params(cam, self.s)
        bearing = math.degrees(math.atan2(at[1] - cam.y, at[0] - cam.x))
        return abs((bearing - cam.angle + 180) % 360 - 180) <= fov / 2 + 15

    def conf(self, assumed: bool = False) -> str:
        return "متوسطة" if (assumed or self.assumed_cams) else "عالية"

    def monitor(self, x, y, seen: list[str], zone_type: str, room_id: Optional[str] = None) -> dict:
        zone = Point(x, y).buffer(2 * self.m)
        out = {"zone_type": zone_type, "polygon": _pts(zone.simplify(1)), "camera_id": seen[0] if seen else None}
        if not seen:
            # propose a camera 4 m from the weak point, toward the middle of the room/yard it sits in
            rid = room_id or room_at(self.s, x, y)
            if rid:
                c = Polygon(self.s.room(rid).polygon).centroid
                dx, dy = c.x - x, c.y - y
                n = math.hypot(dx, dy) or 1.0
                px, py = x + dx / n * 4 * self.m, y + dy / n * 4 * self.m
                out["proposed_camera"] = {"x": round(px), "y": round(py),
                                          "angle": round(math.degrees(math.atan2(y - py, x - px)))}
        return out


# ---------------------------------------------------------------- rules
def rule_law_coverage(c: Ctx) -> list[Finding]:
    """A2: the 16 location types of Reg. Art. 2(1), checked against camera views."""
    if not c.s.meta.law_scope:
        return []
    out: list[Finding] = []
    idr = c.s.meta.defaults.id_range_m
    for d in c.s.doors:
        letter = None
        if d.type == "emergency_exit":
            letter = "و"
        elif d.type == "parking_entrance":
            letter = "ز"
        elif d.type in ENTRANCE_DOORS and ("outside" in d.connects or any(
                c.s.room(e).type == "yard" for e in d.connects if e != "outside")):
            letter = "أ"
        elif any(e != "outside" and c.s.room(e).type in ENTRY_ROOMS_LAW_H for e in d.connects):
            letter = "ح"
        if not letter:
            continue
        seen = c.door_seen_by(d.at, max_m=idr if letter in ("أ", "ح", "ز") else None)
        if seen:
            continue
        text, sev, wp = LAW_ITEMS[letter]
        ref = REG.format(l=letter) + (" · " + SBC_EGRESS if letter == "و" else "")
        if letter == "و":
            title = f"مخرج طوارئ بلا كاميرا: {d.name}"
            scenario = f"استخدام {d.name} للدخول من الخارج أو لإخراج مواد دون أن تلتقطه أي كاميرا."
            action = (f"تركيب كاميرا وحساس فتح مع إنذار على {d.name}، ويبقى الباب قابلاً للفتح من الداخل "
                      f"دون عائق لأن كود البناء يشترط ذلك.")
        else:
            title = f"{d.name} خارج تغطية الكاميرات"
            scenario = f"دخول شخص أو مركبة من {d.name} دون تسجيل بمدى يسمح بالتعرّف على الهوية."
            action = f"تركيب كاميرا ثابتة على {d.name} بمدى التعرّف على الهوية" + (
                " وقراءة اللوحات." if letter == "ز" else ".")
        reason = f"{d.name} من الأماكن التي تشترط اللائحة تغطيتها ({text})، ولا تراه أي كاميرا في المخطط."
        out.append(Finding("A2", wp, title, d.at[0], d.at[1], sev, d.name, "الامتثال لنظام الكاميرات",
                           c.conf(not d.drawn), ref, reason, scenario, action,
                           evidence={"kind": "uncovered_point", "point": [round(d.at[0]), round(d.at[1])]},
                           monitor=c.monitor(d.at[0], d.at[1], [], "line_crossing"),
                           facts={"place": d.name, "law_item": letter, "door_id": d.id}))
    for r in c.s.rooms:
        letter = AREA_LAW.get(r.type)
        if not letter:
            continue
        poly = Polygon(r.polygon)
        frac = c.union.intersection(poly).area / poly.area if poly.area else 0
        need = 0.3 if letter == "د" else 0.5
        if frac >= need:
            continue
        text, sev, wp = LAW_ITEMS[letter]
        miss = _largest(poly.difference(c.union))
        pt = miss.representative_point() if not miss.is_empty else poly.representative_point()
        out.append(Finding(
            "A2", wp, f"{r.name} بلا تغطية كافية", pt.x, pt.y, sev, r.name, "الامتثال لنظام الكاميرات",
            c.conf(), REG.format(l=letter),
            f"{r.name} من الأماكن التي تشترط اللائحة تغطيتها ({text})، والكاميرات ترى {round(frac * 100)}% منه فقط.",
            f"حركة داخل {r.name} لا تظهر في أي كاميرا، فلا يمكن رصدها أو الرجوع لها بعد الحادث.",
            f"إضافة كاميرا تغطي {r.name}" + (" ومداخله." if r.indoor else " والمنطقة المحيطة."),
            evidence={"kind": "uncovered_area", "polygon": _pts(miss.simplify(1)) if miss.geom_type == "Polygon" else []},
            monitor=c.monitor(pt.x, pt.y, [], "restricted_area", r.id),
            facts={"place": r.name, "law_item": letter, "covered_pct": round(frac * 100)}))
    return out


def rule_banned_rooms(c: Ctx) -> list[Finding]:
    """A6: a camera must not see inside rooms the Law bans (Art. 6)."""
    out = []
    for r in c.s.rooms:
        if r.type not in BANNED_ROOMS:
            continue
        poly = Polygon(r.polygon)
        for cid, vis in c.cov.items():
            if vis.intersection(poly).area > 0.01 * poly.area:
                pt = vis.intersection(poly).representative_point()
                out.append(Finding(
                    "A6", "—", f"كاميرا ترى داخل مكان يحظر النظام تصويره: {r.name}", pt.x, pt.y, "عالية", r.name,
                    "الامتثال لنظام الكاميرات", "عالية", LAW6,
                    f"الكاميرا {c.cam_name(cid)} ترى داخل {r.name}، والنظام يحظر تركيب الكاميرات داخل {BANNED_ROOMS[r.type]}.",
                    "مخالفة نظامية وانتهاك للخصوصية قد يوقف ترخيص المنشأة.",
                    f"تغيير زاوية الكاميرا {cid} أو موقعها، أو تفعيل غطاء الخصوصية على {r.name}.",
                    evidence={"kind": "camera_view", "camera": cid, "polygon": _pts(vis.intersection(poly).simplify(1))},
                    monitor={"zone_type": "none", "camera_id": None, "polygon": []},
                    facts={"place": r.name, "camera": cid}))
    return out


def _targets(c: Ctx):
    for r in c.s.rooms:
        if r.sensitive:
            ct = Polygon(r.polygon).centroid
            yield ("room", r.id, r.name, r.id, (ct.x, ct.y), Polygon(r.polygon))
    for a in c.s.assets:
        if a.sensitive:
            poly = Polygon(a.polygon)
            ct = poly.centroid
            yield ("asset", a.id, a.name, room_at(c.s, ct.x, ct.y), (ct.x, ct.y), poly)


def rule_routes(c: Ctx) -> list[Finding]:
    """ROUTE: a way from outside to a sensitive room/object with no access-controlled door."""
    groups: dict[str, dict] = {}
    dmap = {d.id: d for d in c.s.doors}
    for kind, tid, name, room_id, tp, _ in _targets(c):
        if room_id is None:
            continue
        r = route_to(c.s, room_id, tp)
        if r is None or r.controlled > 0:
            continue
        # entry = the first door that leads into a building (or the only door)
        entry = next((dmap[i] for i in r.doors if any(
            e != "outside" and c.s.room(e).indoor for e in dmap[i].connects)), dmap[r.doors[-1]])
        g = groups.setdefault(entry.id, {"entry": entry, "targets": [], "kinds": set(), "route": r, "assumed": False})
        g["targets"].append(name)
        g["kinds"].add(kind)
        g["assumed"] |= any(not dmap[i].drawn for i in r.doors)
        if r.length_px < g["route"].length_px:
            g["route"] = r
    out = []
    for g in groups.values():
        e, r = g["entry"], g["route"]
        targets = " و".join(g["targets"])
        first = dmap[r.doors[0]].name
        path_names = " ← ".join(dmap[i].name for i in r.doors)
        sev = "حرجة" if "room" in g["kinds"] else "عالية"
        n = len(r.doors)
        out.append(Finding(
            "ROUTE", "WP-11", f"مسار مباشر إلى {targets} دون نقطة تحقق", e.at[0], e.at[1], sev, e.name,
            "مسارات الوصول", c.conf(g["assumed"]),
            "مبدأ الحماية بالطبقات (Garcia 2008) · ورقة الثغرات WP-11",
            f"أقصر مسار من الخارج إلى {targets} يمر عبر {n} {'باب' if n == 1 else 'أبواب'} ولا يوجد على أيّ منها تحكم بالدخول.",
            f"شخص يدخل من {first} ويصل إلى {targets} دون أن يوقفه باب مقيّد.",
            f"إضافة تحكم بالدخول عند {e.name} وكاميرا موجهة نحوه، لتصبح الحماية بطبقتين على الأقل.",
            evidence={"kind": "route", "path": [[round(x), round(y)] for x, y in r.points], "doors": r.doors,
                      "path_text": path_names},
            monitor=c.monitor(e.at[0], e.at[1], c.door_seen_by(e.at), "line_crossing"),
            facts={"targets": targets, "entry": e.name, "path": path_names}))
    return out


def rule_blind(c: Ctx) -> list[Finding]:
    """BLIND: an area next to a sensitive room door or object that no camera sees."""
    out = []
    blockers = [a for a in c.s.assets if a.blocks_view]
    solid = unary_union([Polygon(a.polygon) for a in blockers]) if blockers else Polygon()
    for kind, tid, name, room_id, tp, poly in _targets(c):
        if kind == "asset":
            walk = Polygon(c.s.room(room_id).polygon) if room_id else poly.buffer(1 * c.m)
            zone = poly.buffer(1 * c.m).intersection(walk).difference(solid)
        else:
            parts = []
            for d in c.s.doors:
                if tid in d.connects:
                    other = [e for e in d.connects if e != tid][0]
                    walk = Polygon(c.s.room(other).polygon) if other != "outside" else Point(d.at).buffer(3 * c.m)
                    parts.append(Point(d.at).buffer(2 * c.m).intersection(walk))
            zone = unary_union(parts).difference(solid) if parts else Polygon()
        if zone.is_empty or zone.area == 0:
            continue
        miss = zone.difference(c.union)
        frac = miss.area / zone.area
        if frac < 0.15:
            continue
        pieces = sorted([g for g in getattr(miss, "geoms", [miss]) if g.geom_type == "Polygon"
                         and g.area >= 0.25 * c.m * c.m], key=lambda g: -g.area)[:2]
        for piece in pieces:
            out.append(_blind_finding(c, kind, tid, name, room_id, poly, piece, frac, blockers))
    return out


def _blind_finding(c, kind, tid, name, room_id, poly, piece, frac, blockers) -> Finding:
    pt = piece.representative_point()
    # Would a camera see this piece if no objects were in the way? Then an object is the cause.
    if c.free_union is None:
        walls = wall_segments(c.s)
        c.free_union = unary_union([visibility_polygon(cam, c.s, walls) for cam in c.s.cameras])             if c.s.cameras else Polygon()
    shadowed = c.free_union.intersection(piece).area >= 0.5 * piece.area
    blocker = ""
    if shadowed and blockers:
        b = min(blockers, key=lambda a: Polygon(a.polygon).distance(piece))
        blocker = b.name
        cause = (f"لأن {name} نفسه يحجب رؤية الكاميرا خلفه" if b.id == tid
                 else f"لأن {b.name} يحجب رؤية الكاميرا")
    else:
        cause = "لأنها خارج زاوية الكاميرات"
    if True:
        sev = "حرجة" if (blocker and kind == "asset") or frac >= 0.5 else "عالية"
        area_m2 = piece.area / (c.m * c.m)
        return (Finding(
            "BLIND", "WP-17", f"نقطة عمياء بجوار {name}", pt.x, pt.y, sev,
            f"محيط {name}", "النقاط العمياء", c.conf(),
            "ورقة الثغرات WP-17 · اللائحة التنفيذية لنظام الكاميرات م2 (1-ج)",
            f"منطقة مساحتها نحو {area_m2:.1f} م² بجوار {name} لا تراها أي كاميرا، {cause}.",
            f"الاقتراب من {name} عبر هذه المنطقة دون ظهور في البث المباشر.",
            ("نقل الكاميرا أو إضافة كاميرا ثانية بزاوية تكشف المنطقة" + (f"، أو إزاحة {blocker}." if blocker and blocker != name else ".")),
            evidence={"kind": "uncovered_area", "polygon": _pts(piece.simplify(1))},
            monitor=c.monitor(pt.x, pt.y, [], "restricted_area", room_id),
            facts={"target": name, "area_m2": round(area_m2, 1), "blocker": blocker}))


def rule_adjacent(c: Ctx) -> list[Finding]:
    """ADJ: sensitive room sharing a wall with a loading/service area (Reg. Art. 2(1-ح)(1-ي))."""
    out = []
    for r in c.s.rooms:
        if not r.sensitive:
            continue
        rp = Polygon(r.polygon)
        for o in c.s.rooms:
            if o.type in ("loading", "service") and o.id != r.id:
                shared = rp.boundary.intersection(Polygon(o.polygon).boundary)
                if shared.length >= 2 * c.m:
                    mid = shared.interpolate(0.5, normalized=True)
                    out.append(Finding(
                        "ADJ", "WP-12", f"{r.name} ملاصقة لـ{o.name}", mid.x, mid.y, "حرجة", r.name,
                        "المناطق الحساسة", c.conf(), "ورقة الثغرات WP-12 · اللائحة م2 (1-ح)(1-ي)",
                        f"{r.name} تشترك في جدار طوله نحو {shared.length / c.m:.0f} م مع {o.name}.",
                        f"اختراق الجدار المشترك من {o.name} والوصول إلى {r.name} مباشرة.",
                        f"تقوية الجدار الفاصل وإضافة كاميرا على {o.name} بجانب الجدار.",
                        evidence={"kind": "shared_wall", "path": _pts(shared) if shared.geom_type == "LineString" else []},
                        monitor=c.monitor(mid.x, mid.y, [], "restricted_area", o.id),
                        facts={"target": r.name, "other": o.name}))
    return out


def rule_multi_entry(c: Ctx) -> list[Finding]:
    out = []
    for r in c.s.rooms:
        if not r.sensitive:
            continue
        doors = [d for d in c.s.doors if r.id in d.connects]
        if len(doors) > 1:
            ct = Polygon(r.polygon).centroid
            out.append(Finding(
                "MULTI", "WP-13", f"{r.name} لها أكثر من مدخل", ct.x, ct.y, "عالية", r.name, "المناطق الحساسة",
                c.conf(any(not d.drawn for d in doors)), "ورقة الثغرات WP-13",
                f"{r.name} لها {len(doors)} مداخل، وكل مدخل إضافي نقطة اختراق محتملة.",
                f"الدخول إلى {r.name} من المدخل الأقل مراقبة.",
                "مدخل واحد بتحكم دخول، والباقي مخارج طوارئ مراقبة بحساس وإنذار دون منع الخروج.",
                evidence={"kind": "doors", "doors": [d.id for d in doors]},
                monitor=c.monitor(ct.x, ct.y, [], "restricted_area", r.id),
                facts={"target": r.name}))
    return out


def rule_gates(c: Ctx) -> list[Finding]:
    """GATE: an outside door/gate no camera sees (used when the camera law does not apply)."""
    if c.s.meta.law_scope:
        return []
    out = []
    for d in c.s.doors:
        if "outside" in d.connects and d.type in ENTRANCE_DOORS | {"emergency_exit"} and not c.door_seen_by(d.at):
            out.append(Finding(
                "GATE", "WP-02", f"{d.name} بلا كاميرا", d.at[0], d.at[1], "عالية", d.name, "البوابات والمداخل",
                c.conf(not d.drawn), "ورقة الثغرات WP-02/WP-05",
                f"{d.name} يؤدي إلى الداخل ولا تراه أي كاميرا.",
                f"دخول من {d.name} دون أي تسجيل.", f"إضافة كاميرا موجهة نحو {d.name}.",
                evidence={"kind": "uncovered_point", "point": [round(d.at[0]), round(d.at[1])]},
                monitor=c.monitor(d.at[0], d.at[1], [], "line_crossing"), facts={"place": d.name, "door_id": d.id}))
    return out


def rule_perimeter(c: Ctx) -> list[Finding]:
    """PERIM: for each side of the fence, the longest stretch no camera sees (>= 20 m)."""
    if not c.s.fence or len(c.s.fence) < 3:
        return []
    fence = list(c.s.fence)
    if fence[0] != fence[-1]:
        fence.append(fence[0])
    poly = Polygon(fence)
    inner = poly.buffer(-0.5 * c.m)
    cx, cy = poly.centroid.x, poly.centroid.y
    step = 2 * c.m
    total = covered_total = 0
    sides = []
    for a, b in zip(fence, fence[1:]):
        edge = LineString([a, b])
        n = max(int(edge.length // step), 1)
        pts = [edge.interpolate(i * step) for i in range(n)]
        seen = []
        for p in pts:
            q = inner.exterior.interpolate(inner.exterior.project(p)) if not inner.is_empty else p
            seen.append(bool(covered_by(Point(q.x, q.y), c.cov)))
        total += n
        covered_total += sum(seen)
        best, run, run_start, best_start = 0, 0, 0, 0
        for i, v in enumerate(seen):
            if not v:
                if run == 0:
                    run_start = i
                run += 1
                if run > best:
                    best, best_start = run, run_start
            else:
                run = 0
        if best:
            mid = edge.interpolate(0.5, normalized=True)
            dx, dy = mid.x - cx, mid.y - cy
            side = ("الشرقي" if dx > 0 else "الغربي") if abs(dx) / max(poly.bounds[2] - poly.bounds[0], 1) >                 abs(dy) / max(poly.bounds[3] - poly.bounds[1], 1) else ("الجنوبي" if dy > 0 else "الشمالي")
            sides.append((best * 2, side, pts[best_start:best_start + best]))
    pct = round(100 * (total - covered_total) / max(total, 1))
    out = []
    for length_m, side, run_pts in sorted(sides, key=lambda t: -t[0]):
        if length_m < 20:
            continue
        mid = run_pts[len(run_pts) // 2]
        out.append(Finding(
            "PERIM", "WP-03", f"السياج {side} خارج التغطية (نحو {length_m} م)", mid.x, mid.y, "عالية",
            f"السياج {side}", "السياج والمحيط", "عالية", "ورقة الثغرات WP-03 (حماية المحيط)",
            f"مقطع من السياج {side} طوله نحو {length_m} م لا تراه أي كاميرا ({pct}% من السياج كله مكشوف). "
            f"ارتفاع السياج غير موضح في المخطط.",
            "تسلّق السياج في المقطع المكشوف والتحرك داخل الموقع دون رصد.",
            "كاميرات متداخلة على طول السياج دون فراغات، أو حساس سياج على المقطع المكشوف.",
            evidence={"kind": "fence_gap", "path": [[round(p.x), round(p.y)] for p in run_pts]},
            monitor=c.monitor(mid.x, mid.y, [], "line_crossing", "site" if any(r.id == "site" for r in c.s.rooms) else None),
            facts={"pct": pct, "length_m": length_m, "side": side}))
    return out


def rule_single_camera(c: Ctx) -> list[Finding]:
    """SPOF: a sensitive door/object seen by exactly one camera."""
    out = []
    for kind, tid, name, room_id, tp, poly in _targets(c):
        if kind == "room":
            doors = [d for d in c.s.doors if tid in d.connects]
            if not doors:
                continue
            seen = sorted({cid for d in doors for cid in c.door_seen_by(d.at)})
            x, y = doors[0].at
        else:
            seen = sorted(cid for cid, v in c.cov.items() if v.intersects(poly.buffer(0.2 * c.m)))
            x, y = poly.centroid.x, poly.centroid.y
        if len(seen) == 1:
            out.append(Finding(
                "SPOF", "—", f"{name}: كاميرا واحدة فقط", x, y, "متوسطة", name, "نقطة الفشل الوحيدة",
                c.conf(), "مبدأ التغطية المتداخلة (Garcia 2008)",
                f"{name} لا تراه إلا الكاميرا {c.cam_name(seen[0])}؛ تعطّلها أو حجبها يكشفه بالكامل.",
                f"تغطية الكاميرا {seen[0]} أو تعطيلها ثم الوصول إلى {name} دون رصد.",
                f"إضافة كاميرا ثانية بزاوية مختلفة على {name}.",
                evidence={"kind": "camera_view", "camera": seen[0]},
                monitor=c.monitor(x, y, seen, "restricted_area"), facts={"target": name, "camera": seen[0]}))
    return out


def rule_obstruction(c: Ctx) -> list[Finding]:
    """OBSTRUCT: objects cut a large share of a camera's view (walls are expected; objects are not)."""
    blockers = [a for a in c.s.assets if a.blocks_view]
    if not blockers:
        return []
    walls = wall_segments(c.s)
    out = []
    for cam in c.s.scene_cameras() if hasattr(c.s, "scene_cameras") else c.s.cameras:
        free = visibility_polygon(cam, c.s, walls)
        if free.area == 0:
            continue
        lost = free.difference(c.cov[cam.id])
        pct = lost.area / free.area
        if pct < 0.15:
            continue
        b = min(blockers, key=lambda a: Polygon(a.polygon).distance(Point(cam.x, cam.y)))
        out.append(Finding(
            "OBSTRUCT", "WP-30", f"{b.name} يحجب رؤية الكاميرا {cam.id}", cam.x, cam.y, "متوسطة",
            c.cam_name(cam.id), "حجب الرؤية", c.conf(), "ورقة الثغرات WP-30 · IEC 62676-4",
            f"{b.name} يحجب نحو {round(pct * 100)}% من مجال الكاميرا {c.cam_name(cam.id)}.",
            f"الاختباء خلف {b.name} في المنطقة التي لا تراها الكاميرا.",
            f"تغيير موقع الكاميرا {cam.id} أو زاويتها، أو إزاحة {b.name}.",
            evidence={"kind": "shadow", "polygon": _pts(_largest(lost).simplify(1))},
            monitor={"zone_type": "none", "camera_id": cam.id, "polygon": []},
            facts={"camera": cam.id, "blocker": b.name, "pct": round(pct * 100)}))
    return out


def sun_band(lat: float) -> float:
    """Half-width (deg) of the sunrise/sunset direction band around due east/west over a year."""
    a = math.degrees(math.acos(math.sin(math.radians(23.44)) / math.cos(math.radians(lat))))
    return 90 - a


def _arc_overlap(center: float, half: float, target: float, band: float) -> bool:
    d = (center - target + 180) % 360 - 180
    return abs(d) <= half + band


def rule_glare(c: Ctx) -> list[Finding]:
    out = []
    band = sun_band(c.s.meta.lat)
    for cam in c.s.cameras:
        fov, _, indoor = camera_params(cam, c.s)
        if indoor:
            continue
        for target, sun in ((0, "الشروق"), (180, "الغروب")):
            if _arc_overlap(cam.angle, fov / 2, target, band):
                out.append(Finding(
                    "GLARE", "—", f"وهج {sun} على الكاميرا {cam.id}", cam.x, cam.y, "متوسطة", c.cam_name(cam.id),
                    "الإضاءة ووهج الشمس", "متوسطة", f"حساب اتجاه الشمس لخط عرض {c.s.meta.lat}° (±{band:.0f}° حول {'الشرق' if target == 0 else 'الغرب'})",
                    f"الكاميرا {c.cam_name(cam.id)} خارجية ومجالها يشمل اتجاه {sun} في الرياض، فيقل وضوح الصورة وقت {sun}.",
                    f"دخول شخص أو مركبة وقت {sun} دون وضوح كافٍ للتعرّف عليه.",
                    f"تعديل زاوية الكاميرا {cam.id} أو استخدام كاميرا بخاصية WDR لمعالجة الإضاءة العالية.",
                    evidence={"kind": "camera_view", "camera": cam.id},
                    monitor={"zone_type": "none", "camera_id": cam.id, "polygon": []},
                    facts={"camera": cam.id, "sun": sun}))
    return out


def rule_lighting(c: Ctx) -> list[Finding]:
    if c.s.notes.get("lighting") not in ("variable", "poor") or not c.s.cameras:
        return []
    cam = c.s.cameras[0]
    text = c.s.notes.get("lighting_text", "الإضاءة متغيرة")
    return [Finding(
        "LIGHT", "WP-32", "تغيّر الإضاءة يضعف الكشف", cam.x, cam.y, "متوسطة", c.cam_name(cam.id),
        "الإضاءة ووهج الشمس", "تحتاج تحقق ميداني", "ورقة الثغرات WP-32",
        f"المخطط يذكر أن {text}، والكشف بالكاميرا يتأثر بتغيّر الإضاءة.",
        "حركة وقت انخفاض الإضاءة لا يلتقطها الكشف الآلي بثقة.",
        "اختبار الكشف في أوقات الإضاءة المختلفة، وإضافة إضاءة ثابتة على المنطقة الحساسة.",
        evidence={"kind": "note"}, monitor={"zone_type": "none", "camera_id": cam.id, "polygon": []},
        facts={"lighting_text": text})]


RULES = [rule_routes, rule_law_coverage, rule_banned_rooms, rule_blind, rule_adjacent, rule_multi_entry,
         rule_gates, rule_perimeter, rule_single_camera, rule_obstruction, rule_glare, rule_lighting]


def exit_guard(f: Finding) -> Finding:
    """SBC 201 Ch. 10 / SBC 801: a fix for an emergency exit must never lock it."""
    if f.facts.get("law_item") == "و" or "طوارئ" in f.title:
        if any(w in f.action for w in LOCK_WORDS) and "دون عائق" not in f.action:
            f.action = "تركيب كاميرا وحساس فتح مع إنذار، ويبقى المخرج قابلاً للفتح من الداخل دون عائق."
    return f


def run_rules(scene: Scene, cov: dict[str, Polygon]) -> list[Finding]:
    c = Ctx(scene, cov)
    found: list[Finding] = []
    for rule in RULES:
        found += rule(c)
    found = [exit_guard(f) for f in found]
    route_doors = {d for f in found if f.rule == "ROUTE" for d in f.evidence.get("doors", [])}
    targets = {d: f.facts["targets"] for f in found if f.rule == "ROUTE" for d in f.evidence.get("doors", [])}
    for f in found:
        did = f.facts.get("door_id")
        if f.rule in ("A2", "GATE") and did in route_doors and f.severity_level != "حرجة":
            f.severity_level = "حرجة"
            f.reason += f" وهو بداية مسار مفتوح إلى {targets[did]}."
    found.sort(key=lambda f: (SEV_RANK[f.severity_level], RULE_ORDER.index(f.rule), round(f.x), round(f.y)))
    return found
