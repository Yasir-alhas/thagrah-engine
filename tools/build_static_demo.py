"""Build demo/static/thagrah-demo.html: one self-contained page (no server needed) with real
engine results precomputed for several camera poses. Run: python -m tools.build_static_demo"""
import base64, io, json
from pathlib import Path

from PIL import Image

from thagrah_engine.engine import analyze
from thagrah_engine.scene import load_scene

ROOT = Path(__file__).resolve().parents[1]


def img(p):
    im = Image.open(p).convert("RGB").resize((1000, 625))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def main(narrate=True):
    out = {}
    s = load_scene(ROOT / "scenes/booth.json")
    poses = []
    for k in range(9):
        x, y = 320 - k * 10, 120 - round(k * 20 / 8)
        cams = [{"id": "C1", "name": "كاميرا السقف", "x": x, "y": y, "angle": 90}]
        poses.append({"label": f"x={x}", "cameras": cams, "result": analyze(s, cameras=cams, narrate=narrate)})
    out["booth"] = {"name": s.meta.name, "image": img(ROOT / "scenes/booth.png"),
                    "control": "موضع كاميرا السقف (يمين ← يسار)", "poses": poses}
    s = load_scene(ROOT / "scenes/office.json")
    base = [c.model_dump() for c in s.cameras]
    poses = []
    for a in [0, -15, -30, -45, -60, -75, -90, 15, 30, 45, 60, 75, 90, 180]:
        cams = [dict(c, angle=a) if c["id"] == "C3" else c for c in base]
        poses.append({"label": f"{a}°", "angle": a, "cameras": cams,
                      "result": analyze(s, cameras=cams, narrate=narrate)})
    poses.sort(key=lambda p: p["angle"] if p["angle"] != 180 else 999)
    out["office"] = {"name": s.meta.name, "image": img(ROOT / "scenes/office.png"),
                     "control": "اتجاه كاميرا ممر الخوادم C3", "poses": poses}
    t = (ROOT / "tools/static_demo_template.html").read_text(encoding="utf-8")
    data = json.dumps(out, ensure_ascii=False).replace("</", "<\/")
    (ROOT / "demo/static/thagrah-demo.html").write_text(t.replace("__DATA__", data), encoding="utf-8")


if __name__ == "__main__":
    main()
