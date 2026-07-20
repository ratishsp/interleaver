"""The model-call layer: build a Gemini client and make a JSON-returning call, with salvage + retry.

Pure infrastructure — no story/course knowledge. gen.py (the da/en core) and translate.py (the ml/ta
track) both sit on top of this, so the JSON-call plumbing lives in one place and neither depends on the
other for it.
"""
from __future__ import annotations
import json
import os
import threading
import time
from datetime import datetime, timezone

_TRACE_LOCK = threading.Lock()          # the judge panels call the model from a thread pool

_THROTTLE_LOCK = threading.Lock()       # serialize call STARTS to smooth traffic (DSQ mitigation)
_next_call_at = [0.0]                    # monotonic time the next call is allowed to start


def throttle() -> None:
    """Space model-call STARTS at least $TANDEM_MIN_INTERVAL seconds apart, process-wide.

    Google's first remedy for dynamic-shared-quota 429s is to smooth traffic and avoid spikes. The
    pipeline fires calls in parallel (5 gate lenses at once, 4 scenes at once), so a per-thread sleep
    would not smooth anything — all threads sleep, then burst. Holding one lock across the wait paces
    every call start evenly, whatever the thread count. Default 0 = off (unchanged behaviour)."""
    delay = float(os.environ.get("TANDEM_MIN_INTERVAL", "0") or 0)
    if delay <= 0:
        return
    with _THROTTLE_LOCK:
        wait = _next_call_at[0] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _next_call_at[0] = time.monotonic() + delay


def trace(stage: str, model: str, prompt: str, response) -> None:
    """Append this call's INPUT and OUTPUT (with a UTC timestamp) to the JSONL at $TANDEM_TRACE (no-op if unset).

    Full provenance for release: every model call in the pipeline funnels through either _json_call
    below (storyboards, scene generate/revise/verify, the ml/ta track) or review_storyboard's
    _call_findings (both judge panels), so tracing those two captures a whole run in call order —
    including subprocesses, which inherit the env var.
    """
    path = os.environ.get("TANDEM_TRACE")
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)   # a brand-new week has no dir yet
    rec = json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "stage": stage, "model": model, "prompt": prompt, "response": response},
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


_TRANSIENT_STATUS = {429, 500, 502, 503, 504}     # capacity + momentary upstream/gateway errors


def _is_transient(exc) -> bool:
    """A retryable server-side blip: 429 (RESOURCE_EXHAUSTED) or a 5xx (502 Bad Gateway etc.).

    These are not our bug and not a permanent state — Google's own remedy is backoff-and-retry.
    They spike on concurrent bursts (the 5 gate lenses, the parallel scenes) and over a proxied
    egress; a single one used to fail a whole gate lens or scene."""
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _TRANSIENT_STATUS:
        return True
    s = str(exc)
    return any(t in s for t in ("RESOURCE_EXHAUSTED", "Bad Gateway", "Service Unavailable",
                                "Internal error", "502", "503", "504"))


def generate_retrying(client, model: str, prompt: str, config, *, tries: int = 5):
    """throttle()d generate_content that backs off and retries transient 429/5xx.

    Distinct from _json_call's parse-retry: this catches the HTTP-level blip BEFORE a response
    exists. Backoff is 1,2,4,8s (capped), which clears the 'try again in 30 seconds' 502s and the
    burst 429s without a human re-running the whole cycle."""
    import time
    last = None
    for attempt in range(tries):
        throttle()
        try:
            return client.models.generate_content(model=model, contents=prompt, config=config)
        except Exception as exc:                       # noqa: BLE001 — re-raised unless transient
            last = exc
            if attempt < tries - 1 and _is_transient(exc):
                time.sleep(min(2 ** attempt, 16))
                continue
            raise
    raise last


def _json_call(client, model: str, prompt: str, *, retries: int = 1, stage: str = "") -> dict:
    """Call the model forcing a JSON object response and parse it (salvage + one retry).

    Temperature is left UNSET so the model's own default applies (1.0 for current Gemini, which
    Google recommends across both 2.x and 3.x). This keeps the pipeline model-agnostic — no temp to
    retune when swapping models — and avoids Gemini 3's looping/degradation risk from sub-1.0 temps.

    A transient malformed/truncated response is no longer fatal: we salvage fenced/­trailing JSON,
    and regenerate once before giving up (this was dropping whole scenes — wk6 sc6, wk7 sc4).
    """
    from google.genai import types

    cfg = types.GenerateContentConfig(response_mime_type="application/json")
    last = ""
    for _ in range(retries + 1):
        resp = generate_retrying(client, model, prompt, cfg)
        last = (resp.text or "").strip()
        parsed = _parse_json_object(last)
        if parsed is not None:
            trace(stage, model, prompt, parsed)
            return parsed
    raise SystemExit(f"Model did not return valid JSON after {retries + 1} tries:\n{last[:500]}")
