#!/usr/bin/env python3
"""Week-revise — act on review_week findings the way verify->revise acts on per-scene findings.

This closes the broken symmetry: review_week DIAGNOSES whole-week problems (monotony, repeated
templates, cross-scene clashes) but until now nothing TREATED them — they died as a note. Given a
storyboard + review_week's findings JSON, this:
  1. (re)generates any scene whose .da/.en are MISSING (e.g. dropped by a transient gen error), and
  2. routes each blocking whole-week finding to the scene(s) it implicates and REVISES them with the
     finding as feedback (cross-scene context included), then re-verifies each scene per-scene.
It rewrites the affected scenes in place and prints what it did. build_week.py runs this in a loop
with review_week until the gate clears or rounds run out (residuals then become review notes).

Run:  set -a; . ./.env; set +a;
      .venv/bin/python revise_week.py year1/week07/storyboard.md findings.json --location global
"""
import argparse
import json
import os
import re
from pathlib import Path

import tandem.gen as gen
from tandem.gen import (parse_storyboard, parse_storyboard_header, load_story_bible,
                        generate_scene, revise_scene, verify_scene, format_failures, DEFAULT_MODEL)
from tandem.llm import make_client

HARD_DIMS = tuple(d for d in gen.VERIFY_DIMENSIONS if d not in gen.ADVISORY_DIMS)


def hard_pass(rep: dict) -> bool:
    llm = rep.get("llm", {})
    structural = bool(rep.get("aligned")) and bool(rep.get("one_per_line", True))
    return structural and all((llm.get(d) or {}).get("pass") for d in HARD_DIMS)


def implicated_scenes(finding: dict, n: int) -> set:
    """Scene numbers a finding points at: its own `scene` field, or any 'scene N' refs in its prose."""
    s = str(finding.get("scene", ""))
    if s.isdigit():
        k = int(s)
        return {k} if 1 <= k <= n else set()
    text = (finding.get("issue", "") + " " + finding.get("why", "")).lower()
    if "scene" not in text:                      # a truly week-wide finding with no scene anchor
        return set()
    return {int(x) for x in re.findall(r"\d+", text) if 1 <= int(x) <= n}


def write_scene(wdir: Path, stem: str, res: dict) -> None:
    (wdir / f"{stem}.da").write_text("\n".join(res["da"]) + "\n", encoding="utf-8")
    (wdir / f"{stem}.en").write_text("\n".join(res["en"]) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("storyboard")
    ap.add_argument("findings", help="review_week findings JSON (written by review_week.py --out)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--location", default="global")
    a = ap.parse_args()
    os.environ["GOOGLE_CLOUD_LOCATION"] = a.location

    spec = parse_storyboard_header(a.storyboard)
    arc = parse_storyboard(a.storyboard)
    wdir = Path(a.storyboard).parent
    by_num = {r["num"]: r for r in arc}
    n = len(arc)
    level, grammar, week = spec["level"], spec["grammar"], spec["week"]
    client = make_client()

    findings = json.loads(Path(a.findings).read_text(encoding="utf-8"))
    blocking = [f for f in findings if f.get("severity") == "High" and not f.get("advisory")]

    # 1) Regenerate any MISSING scenes (files absent — usually a dropped transient gen).
    n_regen = 0
    for r in arc:
        if (wdir / f"{r['stem']}.da").exists() and (wdir / f"{r['stem']}.en").exists():
            continue
        print(f"[regen] scene {r['num']} {r['stem']} (missing)", flush=True)
        try:
            res = generate_scene(client, model=a.model, week=week, level=level, scene_title=r["title"],
                                 scene=r["scene"], grammar=grammar, arc=arc,
                                 scene_num=r["num"])
            rep = verify_scene(client, model=a.model, level=level, grammar=grammar,
                               da_lines=res["da"], en_lines=res["en"])
            if not hard_pass(rep):               # one revise pass, then keep best-effort
                res = revise_scene(client, model=a.model, level=level, grammar=grammar, scene=r["scene"],
                                   da_lines=res["da"], en_lines=res["en"], feedback=format_failures(rep))
            write_scene(wdir, r["stem"], res)
            n_regen += 1
        except (Exception, SystemExit) as e:  # noqa: BLE001 — one scene failing shouldn't abort
            print(f"         [warn] regen failed: {type(e).__name__}: {str(e)[:120]}", flush=True)

    # 2) Route blocking quality findings (not the 'missing scene' ones, handled above) to scenes.
    quality = [f for f in blocking if "missing" not in (f.get("issue", "") + f.get("why", "")).lower()]
    targets: dict[int, list] = {}
    for f in quality:
        for k in implicated_scenes(f, n):
            targets.setdefault(k, []).append(f"- [{f.get('lens')}] {f.get('issue')} — {f.get('why')}")

    n_revised = 0
    for k in sorted(targets):
        r = by_num.get(k)
        if r is None or not (wdir / f"{r['stem']}.da").exists():
            continue
        da = (wdir / f"{r['stem']}.da").read_text(encoding="utf-8").splitlines()
        en = (wdir / f"{r['stem']}.en").read_text(encoding="utf-8").splitlines()
        feedback = ("A whole-week review found these CROSS-SCENE problems involving this scene. Revise "
                    "THIS scene to help fix them:\n" + "\n".join(targets[k]))
        print(f"[revise] scene {k} {r['stem']} ({len(targets[k])} finding(s))", flush=True)
        try:
            res = revise_scene(client, model=a.model, level=level, grammar=grammar, scene=r["scene"],
                               da_lines=da, en_lines=en, feedback=feedback)
            rep = verify_scene(client, model=a.model, level=level, grammar=grammar,
                               da_lines=res["da"], en_lines=res["en"])
            write_scene(wdir, r["stem"], res)
            n_revised += 1
            print(f"         per-scene re-verify: {'OK' if hard_pass(rep) else 'still flags (kept best)'}",
                  flush=True)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            print(f"         [warn] revise failed: {type(e).__name__}: {str(e)[:120]}", flush=True)

    print(f"\nrevise_week: regenerated {n_regen} missing scene(s), revised {n_revised} scene(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
