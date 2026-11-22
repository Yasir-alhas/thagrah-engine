"""Score the engine against an expert's list of weak points (the poster's Phase 1 targets).

Usage:
  python -m eval.score --scene scenes/office.json --expert eval/example_expert_office.json [--runs 3]

Expert file: a JSON list in the app's shape, at least {"title", "x", "y", "severity"}
(severity: حرج / عالٍ / متوسط). Real plans stay on your machine; nothing is uploaded.

A finding matches an expert point if it is within --radius px (default 80 on the 800x500 grid)
AND is the same kind of weak point (route, fence, glare, entrance...); --loose drops the second condition.
Each expert point can be matched once (greedy, nearest first).
Reports:
- recall: expert points found (poster target >= 93%)
- severity agreement on matched points (poster target >= 88%)
- extra findings: engine findings that matched no expert point (to be reviewed, not errors by default)
- consistency: identical output across --runs runs
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from thagrah_engine.engine import analyze
from thagrah_engine.scene import load_scene


# expert-title keyword -> engine rules that count as the same kind of weak point
TOPICS = [
    (("مسار", "طريق", "وصول"), {"ROUTE"}),
    (("سياج", "سور", "محيط", "تسلق", "تسلّق"), {"PERIM"}),
    (("وهج", "شمس", "شروق", "غروب"), {"GLARE"}),
    (("إضاءة", "اضاءة", "ليل"), {"LIGHT", "GLARE"}),
    (("عمياء", "حجب", "محجوب"), {"BLIND", "OBSTRUCT"}),
    (("طوارئ",), {"A2", "GATE"}),
    (("بوابة", "مدخل", "باب", "مداخل"), {"A2", "GATE", "ROUTE"}),
    (("كاميرا واحدة",), {"SPOF"}),
    (("دورة مياه", "خصوصية", "تبديل"), {"A6"}),
]


def topic_ok(expert_title: str, rule: str) -> bool:
    for words, rules in TOPICS:
        if any(w in expert_title for w in words):
            return rule in rules
    return True  # no recognised topic: place decides


def match(findings: list[dict], expert: list[dict], radius: float, strict: bool = True) -> list[tuple[int, int, float]]:
    pairs = sorted(((math.dist((e["x"], e["y"]), (f["x"], f["y"])), i, j)
                    for i, e in enumerate(expert) for j, f in enumerate(findings)
                    if not strict or topic_ok(e.get("title", ""), f["rule_id"])))
    used_e, used_f, out = set(), set(), []
    for d, i, j in pairs:
        if d > radius:
            break
        if i in used_e or j in used_f:
            continue
        used_e.add(i)
        used_f.add(j)
        out.append((i, j, d))
    return out


def score(scene_path: str, expert_path: str, radius: float = 80, runs: int = 3, strict: bool = True) -> dict:
    scene = load_scene(scene_path)
    expert = json.loads(Path(expert_path).read_text(encoding="utf-8"))
    results = [analyze(scene) for _ in range(max(runs, 1))]
    findings = results[0]["findings"]
    consistent = all(json.dumps(r["findings"], ensure_ascii=False) == json.dumps(findings, ensure_ascii=False)
                     for r in results)
    m = match(findings, expert, radius, strict)
    sev_ok = sum(expert[i]["severity"] == findings[j]["severity"] for i, j, _ in m)
    found = {i for i, _, _ in m}
    return {
        "scene": scene.meta.id,
        "expert_points": len(expert),
        "found": len(m),
        "recall": round(len(m) / len(expert), 3) if expert else None,
        "severity_agreement": round(sev_ok / len(m), 3) if m else None,
        "extra_findings": len(findings) - len(m),
        "consistent_across_runs": consistent,
        "runs": runs,
        "matching": ("same place AND same kind of weak point" if strict else "same place only"),
        "targets": {"recall": 0.93, "severity_agreement": 0.88},
        "missed": [expert[i].get("title") for i in range(len(expert)) if i not in found],
        "matches": [{"expert": expert[i].get("title"), "engine": findings[j]["title"], "distance_px": round(d),
                     "expert_severity": expert[i]["severity"], "engine_severity": findings[j]["severity"]}
                    for i, j, d in m],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--expert", required=True)
    ap.add_argument("--radius", type=float, default=80)
    ap.add_argument("--loose", action="store_true", help="match by place only")
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    print(json.dumps(score(a.scene, a.expert, a.radius, a.runs, not a.loose), ensure_ascii=False, indent=1))
