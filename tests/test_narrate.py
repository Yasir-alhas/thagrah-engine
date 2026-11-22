from pathlib import Path

from thagrah_engine import narrate as nr
from thagrah_engine.geometry import coverage
from thagrah_engine.rules import run_rules
from thagrah_engine.scene import load_scene

SCENES = Path(__file__).resolve().parents[1] / "scenes"


def findings():
    s = load_scene(SCENES / "booth.json")
    return run_rules(s, coverage(s))


def test_unreachable_ollama_falls_back_to_templates(monkeypatch, tmp_path):
    monkeypatch.setattr(nr, "OLLAMA", "http://127.0.0.1:9")
    monkeypatch.setattr(nr, "CACHE", tmp_path / "c.json")
    fs = findings()
    before = [f.reason for f in fs]
    out, mode = nr.narrate(fs)
    assert mode == "template" and [f.reason for f in out] == before


def test_validation_rejects_invented_numbers_and_exit_locks():
    f = findings()[0]
    good = {"reason": "منطقة بجوار الصندوق لا تراها الكاميرا.", "scenario": "الاقتراب دون رصد من الجهة اليسرى.",
            "action": "نقل الكاميرا لتكشف المنطقة كاملة."}
    assert nr.valid(good, f)
    assert not nr.valid({**good, "reason": "المنطقة مساحتها 99 م² ولا تراها الكاميرا."}, f)
    f.title = "مخرج طوارئ بلا كاميرا"
    assert not nr.valid({**good, "action": "قفل مخرج الطوارئ بالسلاسل ليلاً."}, f)
