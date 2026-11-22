"""Access graph: how someone gets from outside to a sensitive room or object.

Nodes are doors. Two doors are linked when they open into the same room; the weight is the
walking distance between them. A controlled door (card reader, guard) costs a large penalty,
so the route found is the one an intruder would choose: fewest controls first, then shortest.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx
from shapely.geometry import Point, Polygon

from .scene import Scene

CONTROL_PENALTY = 10_000.0


@dataclass
class Route:
    doors: list[str]
    controlled: int
    length_px: float
    points: list[tuple[float, float]] = field(default_factory=list)


def room_at(scene: Scene, x: float, y: float) -> Optional[str]:
    """Smallest room that contains the point (indoor rooms win over yards)."""
    p = Point(x, y)
    hits = [r for r in scene.rooms if Polygon(r.polygon).buffer(1).contains(p)]
    return min(hits, key=lambda r: Polygon(r.polygon).area).id if hits else None


def _door_graph(scene: Scene) -> nx.Graph:
    g = nx.Graph()
    by_room: dict[str, list] = {}
    for d in scene.doors:
        g.add_node(d.id, door=d)
        for end in d.connects:
            by_room.setdefault(end, []).append(d)
    for room, doors in by_room.items():
        if room == "outside":
            continue
        for i, a in enumerate(doors):
            for b in doors[i + 1:]:
                w = math.dist(a.at, b.at) + CONTROL_PENALTY * (int(a.controlled) + int(b.controlled)) / 2
                if not g.has_edge(a.id, b.id) or g[a.id][b.id]["weight"] > w:
                    g.add_edge(a.id, b.id, weight=w, via=room)
    for d in scene.doors:
        if "outside" in d.connects:
            g.add_edge("OUT", d.id, weight=CONTROL_PENALTY * int(d.controlled) / 2)
    return g


def route_to(scene: Scene, target_room: str, target_point: Optional[tuple[float, float]] = None) -> Optional[Route]:
    g = _door_graph(scene)
    if "OUT" not in g:
        return None
    tp = target_point
    if tp is None:
        c = Polygon(scene.room(target_room).polygon).centroid
        tp = (c.x, c.y)
    for d in scene.doors:
        if target_room in d.connects:
            g.add_edge(d.id, "T", weight=math.dist(d.at, tp) + CONTROL_PENALTY * int(d.controlled) / 2)
    if "T" not in g:
        return None
    try:
        path = nx.shortest_path(g, "OUT", "T", weight="weight")
    except nx.NetworkXNoPath:
        return None
    doors = [n for n in path if n not in ("OUT", "T")]
    dmap = {d.id: d for d in scene.doors}
    pts = [tuple(dmap[i].at) for i in doors] + [tuple(tp)]
    length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return Route(doors=doors, controlled=sum(dmap[i].controlled for i in doors), length_px=length, points=pts)
