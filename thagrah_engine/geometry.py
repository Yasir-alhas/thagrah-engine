"""Camera views with wall occlusion, and coverage queries.

A camera's view is a ray-cast polygon: rays across its field of view, each stopped at the first
wall or view-blocking object. This is what makes blind spots visible and checkable.
"""
from __future__ import annotations

import math
from functools import lru_cache

from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .scene import Camera, Scene

Seg = tuple[tuple[float, float], tuple[float, float]]
N_RAYS = 241


def _iter_lines(geom) -> list[LineString]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, LineString)]


def wall_segments(scene: Scene) -> list[Seg]:
    """Walls as straight segments, with openings cut at every door."""
    if scene.walls is not None:
        lines = [LineString(w) for w in scene.walls]
    else:
        lines = []
        for r in scene.rooms:
            if r.indoor:
                ring = list(r.polygon) + [r.polygon[0]]
                lines += [LineString([ring[i], ring[i + 1]]) for i in range(len(ring) - 1)]
    merged = unary_union(lines)
    gaps = unary_union([Point(d.at).buffer(d.width / 2, cap_style="square") for d in scene.doors]) \
        if scene.doors else None
    if gaps is not None:
        merged = merged.difference(gaps)
    segs: list[Seg] = []
    for ln in _iter_lines(merged):
        c = list(ln.coords)
        segs += [((c[i][0], c[i][1]), (c[i + 1][0], c[i + 1][1])) for i in range(len(c) - 1)]
    return segs


def occluders(scene: Scene) -> list[Seg]:
    segs = list(wall_segments(scene))
    for a in scene.assets:
        if a.blocks_view:
            ring = list(a.polygon) + [a.polygon[0]]
            segs += [(tuple(ring[i]), tuple(ring[i + 1])) for i in range(len(ring) - 1)]
    return segs


def is_indoor(scene: Scene, x: float, y: float) -> bool:
    p = Point(x, y)
    return any(r.indoor and Polygon(r.polygon).buffer(1).contains(p) for r in scene.rooms)


def camera_params(cam: Camera, scene: Scene) -> tuple[float, float, bool]:
    """(fov_deg, range_px, indoor)."""
    d = scene.meta.defaults
    indoor = is_indoor(scene, cam.x, cam.y)
    rng_m = cam.range_m if cam.range_m is not None else (d.range_m_indoor if indoor else d.range_m_outdoor)
    return (cam.fov or d.fov), rng_m * scene.meta.px_per_m, indoor


def _ray_hit(px, py, dx, dy, segs, max_t) -> float:
    best = max_t
    for (x1, y1), (x2, y2) in segs:
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        wx, wy = x1 - px, y1 - py
        t = (wx * ey - wy * ex) / den
        u = (wx * dy - wy * dx) / den
        if 1e-6 < t < best and -1e-9 <= u <= 1 + 1e-9:
            best = t
    return best


def visibility_polygon(cam: Camera, scene: Scene, segs: list[Seg] | None = None) -> Polygon:
    fov, rng, _ = camera_params(cam, scene)
    segs = occluders(scene) if segs is None else segs
    a0 = math.radians(cam.angle)
    # step 2 px along the view direction so a camera mounted on a wall looks into its room
    px, py = cam.x + 2 * math.cos(a0), cam.y + 2 * math.sin(a0)
    pts = [(px, py)]
    half = math.radians(fov) / 2
    for i in range(N_RAYS):
        a = a0 - half + (2 * half) * i / (N_RAYS - 1)
        dx, dy = math.cos(a), math.sin(a)
        t = _ray_hit(px, py, dx, dy, segs, rng)
        pts.append((px + dx * t, py + dy * t))
    poly = Polygon(pts).buffer(0)
    return poly if isinstance(poly, Polygon) else max(poly.geoms, key=lambda g: g.area)


def nominal_sector(cam: Camera, scene: Scene) -> Polygon:
    """The camera's view with no walls or objects (for 'how much is blocked')."""
    return visibility_polygon(cam, scene, segs=[])


def coverage(scene: Scene, segs: list[Seg] | None = None) -> dict[str, Polygon]:
    segs = occluders(scene) if segs is None else segs
    return {c.id: visibility_polygon(c, scene, segs) for c in scene.cameras}


def covered_by(geom: BaseGeometry, cov: dict[str, Polygon], min_frac: float = 0.6,
               max_dist: float | None = None, cams: dict | None = None) -> list[str]:
    """Camera ids that see a point (optionally within max_dist px) or >= min_frac of an area."""
    out = []
    for cid, poly in cov.items():
        if isinstance(geom, Point):
            ok = poly.buffer(0.5).contains(geom)
            if ok and max_dist is not None and cams is not None:
                c = cams[cid]
                ok = math.hypot(c.x - geom.x, c.y - geom.y) <= max_dist
        elif geom.area > 0:
            ok = poly.intersection(geom).area / geom.area >= min_frac
        else:
            ok = poly.buffer(0.5).intersects(geom)
        if ok:
            out.append(cid)
    return out


def covered_fraction(geom: BaseGeometry, cov: dict[str, Polygon]) -> float:
    if geom.area <= 0 or not cov:
        return 0.0
    return unary_union(list(cov.values())).intersection(geom).area / geom.area
