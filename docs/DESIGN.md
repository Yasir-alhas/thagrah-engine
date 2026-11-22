# Thagrah Phase 1 engine: design

Date: 22 Nov 2026 · Final: SAIF 2026, Riyadh, 24–26 Nov

## Intent
Make Phase 1 on the team's poster true and demonstrable. The poster's Phase 1 has four steps:
**Blueprint → AI blueprint reader → Coverage & compliance → Risk & scenario → Expert approval.**

Previously Phase 1 was a single prompt sent to a cloud model. This package replaces it with a pipeline that:
- runs on-premise
- gives the same answer on every run
- cites Saudi regulations for every finding

It is delivered as a GitHub repo, because the team's backend isn't reachable right now. The team's technical member plugs it in, and the package also runs on its own as a booth fallback.

## Goals
1. One HTTP call returns weak points in **the JSON shape the team's app already uses**:
   `title, x, y, severity, zone, category, confidence, reason, scenario, action`
   plus extra fields:
   - `rule_id` and `regulation_ref`
   - `evidence`: the geometry that proves the finding
   - `monitor`: the Phase 2 zone and camera, which is the "one-time calibration" link to Phase 2
2. Check the **16 location types** in the camera regulation (Implementing Regulation, Art. 2(1) أ–ع), the places where the law bans cameras (Law, Art. 6), and physical-security geometry:
   - blind spots
   - routes to sensitive rooms
   - perimeter gaps
   - single points of failure
   - views blocked by obstacles
   - sun glare
3. Every finding names a Saudi rule. SBC 201/801 are used as a safety guardrail: never recommend locking an exit. The fix is monitoring and an alarm.
4. A local AI does all the AI work, with no cloud calls:
   - **ALLaM-7B** (SDAIA/HUMAIN, Apache-2.0) writes the Arabic reason, scenario and fix.
   - **Qwen-VL** (open weights) drafts the plan from an image, and a person confirms it.
5. A demo page shows each camera's view, blind spots, routes and findings. Dragging or rotating a camera updates the findings live.
6. An evaluation script measures the poster's targets: ≥93% of the expert's weak points flagged, ≥88% with the same severity, extras counted, and repeat-run consistency.

## Non-goals
- Training or fine-tuning any model. It goes to Future Work, because 2 labeled plans can't train or validate one.
- Reading CAD or PDF. The poster says "Image today; PDF / CAD next".
- Phase 2: detection on video and YOLO.
- Expert-approval UI. The team's app already has one.

## Anti-goals (a failure even if the code works)
- The AI invents or moves weak points. Only the engine decides findings; the LLM only writes their text.
- Any network call outside the machine.
- Claims the code doesn't support. See "Honest claims" in the README.
- Recommending that an emergency exit be locked.

## Approaches considered
- **A. Train a model** on FloorPlanCAD/CubiCasa and the SBC. Rejected:
  - There are no labels for security weak points.
  - The 2 real plans are also the only test set.
  - It can't be finished or defended by 24 Nov.
- **B. Hybrid (chosen):** reader → deterministic Saudi rules engine → local LLM writes the text → expert. It matches the 4 Phase 1 boxes on the poster and gives the same answer every run.
- **C. One prompt to a big multimodal model** (what the team has today). It gives different output each run and is "ChatGPT with a screenshot". It stays only as the team's own fallback.


## Architecture
```
image ──► reader (Qwen-VL, local) ──► draft scene ──► person confirms ──┐
scene JSON (rooms, doors, walls, fence, cameras, assets) ───────────────┤
                                                                        ▼
            engine: geometry (camera views with wall occlusion, coverage)
                    access graph (rooms = nodes, doors = edges)
                    rules (Saudi camera regulation + physical security + SBC guardrail)
                                                                        ▼
            findings (rule, severity, location, evidence, monitor zone)
                                                                        ▼
            narrator: ALLaM-7B via Ollama (JSON-constrained, seed fixed, temp 0)
                      fallback: Arabic templates · cache per finding
                                                                        ▼
            app JSON (+ extras) ──► expert approves / accepts risk (team app)
```

## Coordinates and conventions (same as the team's app)
- The image is 800×500 and north is up.
- Camera angle: 0 = east, 90 = south, −90 = north, 180 = west.
- Each scene has a scale in px per metre, used for camera range and "identification range".
- Camera defaults: 90° field of view. Range is 25 m outdoors and 15 m indoors; a scene can override both.

## Rules (first release)
| id | what | source |
|---|---|---|
| A2 | Each of the 16 required location types present in the plan is covered by a camera: a door point within identification range, or ≥60% of an area | Implementing Regulation of the Surveillance Cameras Law, Art. 2(1) أ–ع (applies when the facility type is in the Law's scope, Art. 2) |
| A6 | No camera view covers a banned room: toilets, changing rooms, medical examination, physiotherapy, operating rooms | Law, Art. 6 |
| ROUTE | A route from outside to a sensitive room or asset passes no access-controlled door | layered protection (Garcia 2008); sheet WP-11 |
| MULTI | A sensitive room has more than one door | WP-13 |
| ADJ | A sensitive room shares a wall with a loading or service area | WP-12; Reg. Art. 2(ح)(ي) |
| BLIND | An uncovered area on the approach to a sensitive room or asset (corridors, gaps) | WP-17; Reg. Art. 2(ج) |
| PERIM | The longest stretch of fence that no camera covers | WP-03 |
| GATE | An outside gate or door that no camera covers (when the law doesn't apply) | WP-02/05 |
| SPOF | A sensitive door or room is seen by only one camera | single point of failure |
| OBSTRUCT | Walls or obstacles cut more than 40% of a camera's nominal view | WP-30 (IEC 62676-4 practice) |
| GLARE | An outdoor camera faces the sunrise or sunset band for Riyadh (±26° of east or west) | computed from latitude 24.7° N |
| LIGHT | The plan notes variable or poor lighting | plan note; field check |
| EXIT-GUARD | The fix for an emergency exit never says "lock"; it says a camera, a door contact and an alarm | SBC 201 Ch. 10 (means of egress), SBC 801 |

Severity uses 4 internal levels (حرجة / عالية / متوسطة / منخفضة). They map to the app's 3 levels: حرج / عالٍ / متوسط, with منخفضة shown as متوسط and the original kept in `severity_level`. Confidence is set like this:
- **عالية:** pure geometry on elements drawn in the plan
- **متوسطة:** depends on an assumed door or an assumed camera field of view
- **تحتاج تحقق ميداني:** depends on something the plan can't show, such as fence height or lighting

## Deliverables
- `thagrah_engine/`: the library (`analyze(scene, cameras=None, narrate=False)`) and a FastAPI app with these endpoints:
  - `/health`
  - `/scenes`
  - `/analyze` (JSON scene)
  - `/analyze/image` (image and cameras: the same call shape the team's app uses today)
  - `/read` (draft a scene from an image)
  - `/demo` (the viewer)
- `scenes/`: the demo office complex and the 3×3 m booth, drawn from the team's sample blueprints.
- `rules/catalog.json`: all 35 WP rules from the team's sheet, plus the regulation's 16 location types and their verified citations.
- `docs/SAUDI_SOURCES.md`: what was verified, quoted from the primary text, and what wasn't.
- `eval/`: a scoring script and how to run it on the 2 real plans.
- `tests/`: pytest for geometry, rules, the API and determinism.
- A README in Arabic and English: run, integrate, the poster → code map, and honest claims.

## Left to the team
- Calling `/analyze` (or `/analyze/image`) from their backend and showing the extra fields.
- Running `eval/` on the 2 real plans. They are private and not in this repo.
- Choosing the booth machine. Without a GPU, use the template text or cached ALLaM text.
