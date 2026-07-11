"""The model-call layer: build a Gemini client and make a JSON-returning call, with salvage + retry.

Pure infrastructure — no story/course knowledge. gen.py (the da/en core) and translate.py (the ml/ta
track) both sit on top of this, so the JSON-call plumbing lives in one place and neither depends on the
other for it.
"""
from __future__ import annotations
import json
import os
import threading

_TRACE_LOCK = threading.Lock()          # the judge panels call the model from a thread pool


def trace(stage: str, model: str, prompt: str, response) -> None:
    """Append this call's INPUT and OUTPUT to the JSONL at $TANDEM_TRACE (no-op if unset).

    Full provenance for release: every model call in the pipeline funnels through either _json_call
    below (storyboards, scene generate/revise/verify, the ml/ta track) or review_storyboard's
    _call_findings (both judge panels), so tracing those two captures a whole run in call order —
    including subprocesses, which inherit the env var.
    """
    path = os.environ.get("TANDEM_TRACE")
    if not path:
        return
    rec = json.dumps({"stage": stage, "model": model, "prompt": prompt, "response": response},
                     ensure_ascii=False)
    with _TRACE_LOCK, open(path, "a", encoding="utf-8") as f:
        f.write(rec + "\n")


def make_client():
    """Return a google-genai Client, auto-selecting backend from the environment."""
    from google import genai

    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true", "yes"}
    if use_vertex:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        if not project:
            raise SystemExit("Vertex backend: set GOOGLE_CLOUD_PROJECT (and optionally GOOGLE_CLOUD_LOCATION).")
        return genai.Client(vertexai=True, project=project, location=location)

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit(
            "No credentials. Either set GEMINI_API_KEY (AI Studio key — get one at "
            "https://aistudio.google.com/apikey), or use Vertex (GOOGLE_GENAI_USE_VERTEXAI=true + "
            "GOOGLE_CLOUD_PROJECT)."
        )
    return genai.Client(api_key=key)


def _parse_json_object(text: str) -> dict | None:
    """Parse a JSON object from model text, tolerating markdown fences / trailing prose.

    Returns the dict, or None if nothing parseable. Transient malformed responses (fences, a
    stray sentence after the JSON, truncation) used to crash whole scenes; salvage what we can.
    """
    t = (text or "").strip()
    if t.startswith("```"):                      # strip a ```json … ``` fence
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
        t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")                          # scan the first BALANCED {...}; ignore trailing junk
    if start < 0:                                # (handles a stray extra '}' or prose after the object)
        return None
    depth, instr, esc = 0, False, False
    for idx in range(start, len(t)):
        c = t[idx]
        if instr:
            esc = (c == "\\" and not esc)
            if c == '"' and not esc:
                instr = False
        elif c == '"':
            instr = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:idx + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _json_call(client, model: str, prompt: str, *, retries: int = 1, stage: str = "") -> dict:
    """Call the model forcing a JSON object response and parse it (salvage + one retry).

    Temperature is left UNSET so the model's own default applies (1.0 for current Gemini, which
    Google recommends across both 2.x and 3.x). This keeps the pipeline model-agnostic — no temp to
    retune when swapping models — and avoids Gemini 3's looping/degradation risk from sub-1.0 temps.

    A transient malformed/truncated response is no longer fatal: we salvage fenced/­trailing JSON,
    and regenerate once before giving up (this was dropping whole scenes — wk6 sc6, wk7 sc4).
    """
    from google.genai import types

    last = ""
    for _ in range(retries + 1):
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        last = (resp.text or "").strip()
        parsed = _parse_json_object(last)
        if parsed is not None:
            trace(stage, model, prompt, parsed)
            return parsed
    raise SystemExit(f"Model did not return valid JSON after {retries + 1} tries:\n{last[:500]}")
