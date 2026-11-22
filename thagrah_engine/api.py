"""HTTP API for the team's backend.

Run:  uvicorn thagrah_engine.api:app --host 127.0.0.1 --port 8100
Docs: http://127.0.0.1:8100/docs     Demo: http://127.0.0.1:8100/demo
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from . import narrate as nr
from . import reader
from .engine import ENGINE_VERSION, analyze
from .scene import Scene, load_scene

ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "scenes"
DEMO = ROOT / "demo"

app = FastAPI(title="Thagrah Phase 1 engine", version=ENGINE_VERSION,
              description="Blueprint → Saudi rules engine → ALLaM (local) → weak points JSON for expert approval.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _scene_files() -> dict[str, Path]:
    return {p.stem: p for p in sorted(SCENES.glob("*.json")) if "." not in p.stem}


def _get_scene(scene_id: str) -> Scene:
    p = _scene_files().get(scene_id)
    if not p:
        raise HTTPException(404, f"unknown scene {scene_id!r}")
    return load_scene(p)


class AnalyzeRequest(BaseModel):
    scene_id: Optional[str] = None
    scene: Optional[dict[str, Any]] = None
    cameras: Optional[list[dict[str, Any]]] = None
    narrate: bool = False
    limit: Optional[int] = None


@app.get("/health")
def health():
    return {"engine": ENGINE_VERSION, "llm": nr.MODEL, "llm_ready": nr.available(nr.MODEL),
            "vision": reader.VLM, "vision_ready": nr.available(reader.VLM), "cloud_calls": False}


@app.get("/scenes")
def scenes():
    out = []
    for sid, p in _scene_files().items():
        s = load_scene(p)
        out.append({"id": sid, "name": s.meta.name, "image": f"/scenes/{sid}/image" if s.meta.image else None,
                    "law_scope": s.meta.law_scope})
    return out


@app.get("/scenes/{scene_id}")
def scene(scene_id: str):
    return _get_scene(scene_id).model_dump()


@app.get("/scenes/{scene_id}/image")
def scene_image(scene_id: str):
    s = _get_scene(scene_id)
    if not s.meta.image or not (SCENES / s.meta.image).exists():
        raise HTTPException(404, "no image")
    return FileResponse(SCENES / s.meta.image)


@app.post("/analyze")
def analyze_json(req: AnalyzeRequest):
    """Main call. Send a scene (or a demo scene_id) and, optionally, the app's camera list."""
    if req.scene is not None:
        try:
            s = Scene.model_validate(req.scene)
        except ValueError as e:
            raise HTTPException(422, str(e))
    elif req.scene_id:
        s = _get_scene(req.scene_id)
    else:
        raise HTTPException(422, "send scene or scene_id")
    return analyze(s, cameras=req.cameras, narrate=req.narrate, limit=req.limit)


@app.post("/read")
async def read(image: UploadFile = File(...)):
    """AI blueprint reader: image → draft scene (a person must confirm it)."""
    res = reader.read_plan(await image.read())
    if res["scene"] is None:
        raise HTTPException(503, res["error"])
    return res


@app.post("/analyze/image")
async def analyze_image(image: UploadFile = File(...), cameras: str = Form("[]"), narrate: bool = Form(False),
                        scene_id: Optional[str] = Form(None)):
    """Same call shape as the old prompt: blueprint image + camera list (JSON string).

    If scene_id names a confirmed scene (e.g. a demo plan), that scene is used and the image is not re-read.
    Otherwise the local vision model drafts the scene from the image first.
    """
    try:
        cams = json.loads(cameras) if cameras else None
    except ValueError:
        raise HTTPException(422, "cameras must be a JSON list")
    if scene_id:
        s = _get_scene(scene_id)
        source = "confirmed scene"
    else:
        res = reader.read_plan(await image.read())
        if res["scene"] is None:
            raise HTTPException(503, res["error"])
        s = Scene.model_validate(res["scene"])
        source = "reader draft (needs confirmation)"
    out = analyze(s, cameras=cams or None, narrate=narrate)
    out["meta"]["scene_source"] = source
    return out


@app.get("/")
def root():
    return RedirectResponse("/demo")


@app.get("/demo")
def demo():
    return FileResponse(DEMO / "index.html")
