"""Public entry point: analyze(scene) -> findings in the team's app JSON shape."""
from __future__ import annotations

import time
from typing import Optional

from .geometry import coverage
from .rules import run_rules
from .scene import Scene

ENGINE_VERSION = "1.0.0"
APP_SEVERITY = {"حرجة": "حرج", "عالية": "عالٍ", "متوسطة": "متوسط", "منخفضة": "متوسط"}


def to_app(findings) -> list[dict]:
    out = []
    for i, f in enumerate(findings, 1):
        out.append({
            "id": f"V-{i:02d}",
            "title": f.title,
            "x": int(round(f.x)), "y": int(round(f.y)),
            "severity": APP_SEVERITY[f.severity_level],
            "zone": f.zone,
            "category": f.category,
            "confidence": f.confidence,
            "reason": f.reason,
            "scenario": f.scenario,
            "action": f.action,
            "status": "معلّقة",
            # extras (the app can ignore them)
            "rule_id": f.rule,
            "sheet_id": f.wp,
            "regulation_ref": f.regulation_ref,
            "severity_level": f.severity_level,
            "evidence": f.evidence,
            "monitor": f.monitor,
            "key": f.key,
        })
    return out


def analyze(scene: Scene, cameras: Optional[list[dict]] = None, narrate: bool = False,
            limit: Optional[int] = None, **narrate_kw) -> dict:
    t0 = time.perf_counter()
    scene = scene.with_cameras(cameras)
    cov = coverage(scene)
    findings = run_rules(scene, cov)
    mode = "template"
    if narrate:
        from .narrate import narrate as _narrate
        findings, mode = _narrate(findings, **narrate_kw)
    total = len(findings)
    if limit:
        findings = findings[:limit]
    return {
        "findings": to_app(findings),
        "coverage": {cid: [[round(x), round(y)] for x, y in poly.exterior.coords] for cid, poly in cov.items()
                     if not poly.is_empty},
        "meta": {"engine": "thagrah-engine", "version": ENGINE_VERSION, "scene": scene.meta.id,
                 "law_scope": scene.meta.law_scope, "total_findings": total, "narration": mode,
                 "runs_on": "local (no cloud calls)", "ms": round((time.perf_counter() - t0) * 1000)},
    }
