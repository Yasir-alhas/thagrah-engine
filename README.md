# Thagrah (ثغرة) — Phase 1 Engine

**Blueprint security analysis grounded in Saudi regulation.**
Thagrah reads a facility blueprint, finds its security weak points before approval, and hands each one to a security expert to approve or accept as a risk. The approved weak points then become the zones that Phase 2 (live camera monitoring) watches.

This repository contains Phase 1. It runs entirely on the local machine, with no cloud calls.

---

## Overview

| Stage | Component | Description |
|---|---|---|
| Blueprint input | `POST /analyze/image`, `POST /read` | Plan image (PNG/JPG). CAD/PDF input is planned. |
| AI blueprint reader | `thagrah_engine/reader.py` | A local vision-language model (Qwen3-VL) detects rooms, doors, gates and the site fence, and produces a draft scene for a person to confirm. |
| Coverage and compliance | `geometry.py`, `rules.py` | Computes each camera's field of view with wall occlusion, then checks the 16 location types that the Saudi surveillance-camera regulation requires to be covered, and the rooms where cameras are prohibited. |
| Risk and scenario | `graph.py`, `rules.py`, `narrate.py` | Finds the attacker's easiest route to sensitive rooms, assigns severity and a fix, and has ALLaM-7B write the Arabic reason, scenario and action. |
| Expert approval | Thagrah application | Every finding is returned with status `معلّقة` (pending). |
| Link to Phase 2 | `monitor` field | Each finding carries its monitoring zone (line crossing or restricted area) and the camera that sees it, or a proposed camera position. |

---

## Technical contribution

The system is an AI pipeline rather than a single trained model. Its contributions are:

**1. Saudi regulation as machine-checkable knowledge.**
The location requirements of the Implementing Regulation of the Law on the Use of Security Surveillance Cameras (Art. 2(1), 16 location types) and the Law's prohibited locations (Art. 6) are encoded as executable rules. The Saudi Building Code egress requirements (SBC 201 Ch. 10, SBC 801) act as a constraint on recommendations: the engine never proposes locking an emergency exit. Every finding cites the clause it is based on.

**2. Spatial reasoning from the attacker's perspective.**
- Visibility analysis: each camera's view is ray-cast against walls and view-blocking objects, which exposes blind spots precisely.
- Adversarial path search: the facility is modelled as an access graph of rooms and doors, and the engine searches for the route an intruder would take to each sensitive room or asset (fewest access controls first, then shortest distance).

**3. Neuro-symbolic architecture.**
Neural models handle perception and language: a vision-language model reads the plan, and ALLaM writes the Arabic report text. A symbolic rules engine alone decides what counts as a weak point, where it is and how severe it is. The language model cannot add, remove or move findings; its output is validated, and rejected if it introduces numbers not present in the facts or recommends locking an exit. The result is explainable and identical across runs.

**4. Reproducible compliance benchmark.**
A generator produces test plans with known answers for every regulatory clause (compliant placement, missing camera, camera facing away, camera behind a wall, camera out of range), with randomized layouts.

**5. Phase 1 to Phase 2 link.**
Each weak point is emitted with a monitoring zone, so approved findings translate directly into the areas the camera-tracking phase watches.

**6. Sovereign, on-premise operation.**
All models run locally through Ollama. ALLaM is developed by SDAIA (Saudi Data and AI Authority). Plans and results never leave the machine.

---

## Results

**Saudi compliance benchmark** (`python -m benchmark.saudi_benchmark --seeds 10`)

| Metric | Result |
|---|---|
| Generated cases | 880 |
| Violations detected | 100% |
| False alarms on compliant plans | 0% |
| Emergency-exit fixes recommending a lock | 0 of 40 |

Per-clause results are in `benchmark/RESULTS.md`. The benchmark verifies that each regulatory clause is applied correctly; agreement with a human expert on real plans is measured separately with `eval/score.py`.

**Blueprint reader** (demo office plan): 10 of 12 rooms located (IoU ≥ 0.5, mean IoU 0.67). Arabic labels are occasionally misread, so the draft is confirmed by a person before analysis.

**Demo plans:** 22 findings on the administrative complex, 6 on the 3 m × 3 m booth. Analysis takes about 150 ms per plan without narration.

---

## Installation

Requirements: Python 3.11+, Windows/Linux/macOS.

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m uvicorn thagrah_engine.api:app --host 127.0.0.1 --port 8100
```

On Windows, `start.bat` performs these steps and opens the demo.

- Demo: http://127.0.0.1:8100/demo
- API documentation: http://127.0.0.1:8100/docs
- Tests: `.venv/Scripts/python -m pytest`

### Local models (optional)

The engine works without them, using Arabic templates for the report text. Narration for the two demo plans is pre-generated in `cache/narration.json`.

1. Install [Ollama](https://ollama.com) and run `ollama serve`.
2. ALLaM-7B (SDAIA/HUMAIN, Apache-2.0): download `ALLaM-AI_ALLaM-7B-Instruct-preview-Q4_K_M.gguf` from `huggingface.co/bartowski/ALLaM-AI_ALLaM-7B-Instruct-preview-GGUF`, then:
   ```
   echo FROM ./ALLaM-AI_ALLaM-7B-Instruct-preview-Q4_K_M.gguf > Modelfile
   ollama create allam:7b -f Modelfile
   ```
3. Blueprint reader: `ollama pull qwen3-vl:8b-instruct`

| Environment variable | Default |
|---|---|
| `THAGRAH_OLLAMA` | `http://127.0.0.1:11434` |
| `THAGRAH_LLM` | `allam:7b` |
| `THAGRAH_VLM` | `qwen3-vl:8b-instruct` |

A GPU with 8–12 GB of memory is recommended for the models. Narration takes roughly 5–8 seconds per finding on first run and is cached afterwards.

---

## Integration

### Image and camera list (drop-in for the previous analysis call)
```
POST /analyze/image        multipart/form-data
  image     plan image
  cameras   JSON list, e.g. [{"name":"Main gate","x":400,"y":455,"angle":-90}]
  narrate   true | false   (ALLaM writes the report text)
  scene_id  optional: use a confirmed scene instead of reading the image
```

### Confirmed scene
```
POST /analyze              application/json
{"scene_id": "booth", "cameras": [...], "narrate": false}
{"scene": { ...full scene... }, "cameras": [...]}
```

### Other endpoints
`GET /health` · `GET /scenes` · `GET /scenes/{id}` · `POST /read` (image → draft scene) · `GET /demo`

### Response
```json
{
  "findings": [{
    "id": "V-01", "title": "...", "x": 590, "y": 267,
    "severity": "حرج", "zone": "...", "category": "مسارات الوصول",
    "confidence": "متوسطة", "reason": "...", "scenario": "...", "action": "...",
    "status": "معلّقة",
    "rule_id": "ROUTE", "regulation_ref": "...", "severity_level": "حرجة",
    "evidence": {"kind": "route", "path": [[770, 330], [740, 300]]},
    "monitor": {"zone_type": "line_crossing", "polygon": [], "camera_id": null,
                "proposed_camera": {"x": 610, "y": 250, "angle": 135}}
  }],
  "coverage": {"C1": [[400, 453], [312, 365]]},
  "meta": {"total_findings": 22, "narration": "allam", "runs_on": "local (no cloud calls)"}
}
```
The first ten fields match the application's existing format; the remaining fields are additions that can be ignored.

**Conventions:** 800 × 500 coordinate space, north up. Camera angle: 0 = east, 90 = south, −90 = north, 180 = west.

### Python
```python
from thagrah_engine.engine import analyze
from thagrah_engine.scene import load_scene

result = analyze(load_scene("scenes/office.json"), cameras=app_cameras, narrate=True)
```

### Demo interface
`/demo` shows the plan, camera coverage and findings. Cameras can be dragged and rotated; findings update immediately. **Upload plan** runs the blueprint reader on a new image; **+ Camera** adds cameras to it. `demo/static/thagrah-demo.html` is a self-contained version with precomputed results that opens without a server (rebuild with `python -m tools.build_static_demo`).

---

## Rules

| Rule | Checks | Basis |
|---|---|---|
| A2 | Coverage of the 16 required location types | Implementing Regulation, Art. 2(1) |
| A6 | Cameras viewing prohibited rooms | Surveillance Cameras Law, Art. 6 |
| ROUTE | Route from outside to a sensitive room or asset with no access control | Layered protection |
| BLIND | Unobserved area beside a sensitive door or asset | Coverage analysis |
| PERIM | Uncovered stretch of fence, per side | Perimeter protection |
| ADJ | Sensitive room sharing a wall with a loading or service area | Regulation Art. 2(1-ح, 1-ي) |
| MULTI | Sensitive room with more than one entrance | Access control |
| GATE | External door or gate with no camera (outside the Law's scope) | Perimeter protection |
| SPOF | Sensitive door or asset seen by only one camera | Redundant coverage |
| OBSTRUCT | Object blocking a large share of a camera's view | IEC 62676-4 practice |
| GLARE | Outdoor camera facing the sunrise or sunset band | Solar geometry for Riyadh (24.7° N) |
| LIGHT | Plan notes variable or poor lighting | Field verification |

The full catalogue of 35 weak-point types and their implementation status is in `rules/catalog.json`. Sources are documented in `docs/SAUDI_SOURCES.md`.

---

## Evaluation against an expert

```bash
python -m eval.score --scene <scene.json> --expert <expert.json> [--runs 3]
```
The expert file is a JSON list with at least `title`, `x`, `y` and `severity`. A finding matches an expert point when it is within 80 px and of the same kind of weak point. The script reports recall (target ≥ 93%), severity agreement (target ≥ 88%), additional findings, and run-to-run consistency. Real plans remain on the local machine.

---

## Limitations

- Image input only; CAD and PDF reading are planned.
- The blueprint reader produces a draft that must be confirmed.
- Fence height, lighting levels and other properties not shown in a plan image cannot be assessed; 9 of the 35 catalogued weak-point types depend on such data.
- No model weights were trained. A planned next step is learning from expert approve/reject decisions, which the application already records.

---

## Repository structure

```
thagrah_engine/      scene, geometry, graph, rules, engine, narrate, reader, api
scenes/              demo plans: administrative complex (office) and 3 m × 3 m booth
rules/catalog.json   regulatory location types, prohibited rooms, 35 weak-point types
benchmark/           Saudi compliance benchmark and results
eval/                scoring against an expert list
cache/               pre-generated ALLaM narration for the demo plans
demo/                interactive demo and self-contained static version
docs/                design, Saudi sources, team research sheet
tools/               database export script, static demo builder
tests/               unit and API tests
```
