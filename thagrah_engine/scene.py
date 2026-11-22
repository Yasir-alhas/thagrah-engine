"""Scene model: a blueprint turned into data (rooms, doors, walls, fence, cameras, assets).

Coordinates follow the team's app: an 800x500 image, north up.
Camera angle: 0 = east, 90 = south, -90 = north, 180 = west.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, model_validator

Point = tuple[float, float]

# Room / area types the engine understands. Types that the Implementing Regulation of the
# Surveillance Cameras Law requires cameras for are mapped in rules.py (LAW_AREA_TYPES).
ROOM_TYPES = {
    "office", "meeting", "server", "telecom", "vault", "corridor", "lobby", "reception",
    "security", "storage", "loading", "service", "parking", "yard", "electrical", "gas",
    "water_tank", "hvac", "fuel", "stairs", "atm", "assembly", "fire_equipment", "dropoff",
    "booth", "toilet", "changing_room", "medical_exam", "physio", "operating_room", "other",
}
DOOR_TYPES = {"main", "secondary", "emergency_exit", "gate", "vehicle_gate", "internal",
              "open", "parking_entrance", "roof_access"}


class Defaults(BaseModel):
    fov: float = 90.0
    range_m_indoor: float = 15.0
    range_m_outdoor: float = 25.0
    id_range_m: float = 12.0  # "identification range" used for entrances (Reg. Art. 2)


class Meta(BaseModel):
    id: str
    name: str
    image: Optional[str] = None
    width: int = 800
    height: int = 500
    px_per_m: float = 5.0
    facility_category: str = ""
    law_scope: bool = True  # is the facility one of the categories in Art. 2 of the Law?
    lat: float = 24.7       # Riyadh, used for sun-glare bands
    defaults: Defaults = Field(default_factory=Defaults)


class Room(BaseModel):
    id: str
    name: str
    type: str = "other"
    polygon: list[Point]
    indoor: bool = True
    sensitive: bool = False


class Door(BaseModel):
    id: str
    name: str
    type: str = "internal"
    at: Point
    width: float = 20.0
    connects: tuple[str, str]
    controlled: bool = False  # access control (card reader, guard, interlock)
    drawn: bool = True        # False = assumed by the person who entered the plan


class Camera(BaseModel):
    id: str
    name: str = ""
    x: float
    y: float
    angle: float
    fov: Optional[float] = None
    range_m: Optional[float] = None


class Asset(BaseModel):
    id: str
    name: str
    polygon: list[Point]
    sensitive: bool = True
    blocks_view: bool = True


class Scene(BaseModel):
    meta: Meta
    rooms: list[Room] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    walls: Optional[list[tuple[Point, Point]]] = None  # if None, derived from indoor rooms
    fence: Optional[list[Point]] = None                 # closed polyline
    cameras: list[Camera] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_refs(self) -> "Scene":
        ids = {r.id for r in self.rooms} | {"outside"}
        for d in self.doors:
            for end in d.connects:
                if end not in ids:
                    raise ValueError(f"door {d.id!r} connects to unknown room {end!r}")
        return self

    def room(self, rid: str) -> Room:
        for r in self.rooms:
            if r.id == rid:
                return r
        raise KeyError(rid)

    def with_cameras(self, cameras: Optional[list[dict]]) -> "Scene":
        """Return a copy whose cameras are replaced by the app's camera list (if given)."""
        if cameras is None:
            return self
        cams = []
        for i, c in enumerate(cameras):
            c = dict(c)
            c.setdefault("id", f"C{i + 1}")
            cams.append(Camera(**c))
        return self.model_copy(update={"cameras": cams})


def load_scene(path: str | Path) -> Scene:
    return Scene.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
