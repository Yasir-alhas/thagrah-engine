"""Arabic wording by ALLaM-7B (SDAIA/HUMAIN, Apache-2.0), running locally through Ollama.

The rules engine decides every weak point. ALLaM only rewrites three short texts
(reason, scenario, action) from the engine's facts. Its output is rejected, and the
template text kept, if it is empty, not Arabic, adds numbers that are not in the facts,
or suggests locking an emergency exit.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import httpx

from .rules import LOCK_WORDS, Finding

OLLAMA = os.environ.get("THAGRAH_OLLAMA", "http://127.0.0.1:11434")
MODEL = os.environ.get("THAGRAH_LLM", "allam:7b")
CACHE = Path(os.environ.get("THAGRAH_CACHE", Path(__file__).resolve().parents[1] / "cache" / "narration.json"))

SYSTEM = (
    "أنت محرر تقارير في فريق أمن منشآت سعودي. تصلك ثغرة اكتشفها محرك قواعد مع نص مبدئي. "
    "أعد صياغة السبب والسيناريو والإجراء بعربية فصحى واضحة، جملة أو جملتين لكل حقل. "
    "لا تضف أماكن أو أرقاماً أو أنظمة غير موجودة في المعطيات، ولا تقترح أبداً قفل مخرج طوارئ. "
    "أعد JSON فقط بالحقول: reason, scenario, action."
)
SCHEMA = {"type": "object", "properties": {k: {"type": "string"} for k in ("reason", "scenario", "action")},
          "required": ["reason", "scenario", "action"]}
ARABIC = re.compile(r"[؀-ۿ]")
NUM = re.compile(r"\d+(?:\.\d+)?")


def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _cache_key(f: Finding, model: str) -> str:
    raw = json.dumps([model, f.key, f.title, f.reason, f.scenario, f.action], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def valid(out: dict, f: Finding) -> bool:
    allowed = set(NUM.findall(" ".join([f.title, f.zone, f.reason, f.scenario, f.action, f.regulation_ref])))
    for k in ("reason", "scenario", "action"):
        v = out.get(k)
        if not isinstance(v, str) or not (10 <= len(v) <= 400) or not ARABIC.search(v):
            return False
        if not set(NUM.findall(v)) <= allowed:
            return False
    if out["reason"].strip(" .") == f.title.strip(" ."):
        return False
    if ("طوارئ" in f.title or f.facts.get("law_item") == "و") and any(w in out["action"] for w in LOCK_WORDS):
        return False
    return True


def _ask(client: httpx.Client, f: Finding, model: str) -> dict:
    facts = {"العنوان": f.title, "المكان": f.zone, "الفئة": f.category, "المرجع": f.regulation_ref,
             "السبب": f.reason, "السيناريو": f.scenario, "الإجراء": f.action}
    r = client.post(f"{OLLAMA}/api/chat", json={
        "model": model, "stream": False, "format": SCHEMA,
        "options": {"temperature": 0, "seed": 7, "num_predict": 400},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}]})
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def available(model: str = MODEL) -> bool:
    try:
        tags = httpx.get(f"{OLLAMA}/api/tags", timeout=2).json()
        return any(m["name"].split(":")[0] == model.split(":")[0] for m in tags.get("models", []))
    except (httpx.HTTPError, ValueError, KeyError):
        return False


def narrate(findings: list[Finding], model: str = MODEL, use_cache: bool = True) -> tuple[list[Finding], str]:
    """Rewrite texts with ALLaM. Returns (findings, mode) where mode is 'allam', 'partial' or 'template'."""
    if not findings:
        return findings, "template"
    cache = _load_cache() if use_cache else {}
    if not available(model) and not any(_cache_key(f, model) in cache for f in findings):
        return findings, "template"
    done = 0
    with httpx.Client(timeout=httpx.Timeout(60, connect=2)) as client:
        for f in findings:
            k = _cache_key(f, model)
            out = cache.get(k)
            if out is None:
                try:
                    out = _ask(client, f, model)
                except (httpx.HTTPError, ValueError, KeyError):
                    out = None
                if out is not None and valid(out, f):
                    cache[k] = out
                else:
                    out = None
            if out:
                f.reason, f.scenario, f.action = out["reason"], out["scenario"], out["action"]
                done += 1
    if use_cache:
        _save_cache(cache)
    mode = "allam" if done == len(findings) else ("partial" if done else "template")
    return findings, mode
