"""Storyboard review gate — a 4-lens panel that reviews a week's storyboard BEFORE generation.

Mirrors `verify_scene`, one tier up:  author beats → REVIEW → revise → pass → generate.
Three mechanical lenses (continuity / narrative-logic / realism+privacy) carry a prescribed
checklist as a FLOOR *plus* explicit agency; a fourth "naive learner" lens has NO checklist —
it catches what a checklist can't (pacing, monotony, flat mood). The text verifier checks the
generated Danish; this checks the *design*, before any Danish exists.

Why a panel, why agency: a reviewer's errors are asymmetric — a false alarm costs seconds to
dismiss, a miss costs a bad week (×50 at scale). So each lens is told its checklist is a MINIMUM,
not a maximum, and to err toward surfacing.

Validated 2026-06-27 on the pre-fix week-2 storyboard (commit d04b950): the panel independently
caught all 5 issues we'd found by hand (CPR-read-aloud, texts-before-having-number, already-has-
address, bus#4/4-stops, plan-duplication) plus real residual ones (out-of-scope ordinal, the
12/14 recap, the "writes it down" refrain, no-friction flatness).

GROW THE CHECKLIST: when a lens keeps surfacing the same new kind of issue, fold it into that
lens's `floor` below (discovery via agency → codify into the floor). The bible (story_bible.md)
is the continuity ground-truth and is updated as each week locks.

Run:  set -a; . ./.env; set +a;  .venv/bin/python review_storyboard.py year1/week03/storyboard.md
"""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import os
import re
from pathlib import Path

from tandem.gen import (
    DEFAULT_MODEL,
    _json_call,
    make_client,
    parse_storyboard,
    parse_storyboard_header,
)

COMMON = """This is a Danish-for-English-speakers graded AUDIO course (interleaved English→Danish, beginner→up).
A "week" is a STORYBOARD: ~14 scene "beats" (one-paragraph summaries). From each beat a model later
generates ~14 short Danish sentences + English glosses, then text-to-speech. You are reviewing the
STORYBOARD (the beats), BEFORE any Danish is generated, to catch design problems while a fix is cheap
(edit a beat, not regenerate + re-verify + re-render).

GROUND TRUTH:
--- story_bible.md (established story facts + cross-cutting rules) ---
{bible}
--- end bible ---

--- this week's curriculum row (level / grammar focus / theme) ---
{curric}
(Scene-count guide: A1 ramps ~12→28 scenes; A2 ~26; B1 ~18; B2 ~12 — all ≈ a level-appropriate length.)
--- end curriculum ---

STORYBOARD UNDER REVIEW — {header}:
{beats}
"""

_FLOOR_AGENCY = """
[Floor — check these at minimum:]
{floor}

[Agency:] This list is a MINIMUM, not a maximum. Use your judgment — flag anything else off through
your lens even if it is not listed. A false alarm costs us seconds to dismiss; a miss costs a bad
lesson. Err toward surfacing."""

LENSES = [
    {
        "key": "continuity",
        "title": "Spec & continuity",
        "lens": "consistency with established story facts, and conformance to the week's curriculum spec",
        "floor": (
            "(a) Does any beat CONTRADICT a story_bible fact, or RE-INTRODUCE as new something Maya\n"
            "    already has/knows/is (housing, address, phone, CPR, job, relationships)?\n"
            "(b) Does the week hit its curriculum grammar focus and its theme?\n"
            "(c) Scene count vs the ramp guidance? (d) Level-appropriate (no out-of-scope grammar,\n"
            "    e.g. ordinals/past-tense before they are introduced)?\n"
            "(e) Character facts consistent (recurring cast, Maya's age/origin)?"
        ),
    },
    {
        "key": "logic",
        "title": "Narrative logic & coherence",
        "lens": "internal logic, ordering, redundancy, and dramatic sense within the week",
        "floor": (
            "(a) Redundancy — is the same information delivered twice (a plan stated, then restated)?\n"
            "(b) Logic gaps — does any action presuppose something not yet true (contacting someone\n"
            "    before you could have their contact details)?\n"
            "(c) Ordering / cause-effect plausibility across scenes.\n"
            "(d) Over-repetition — a fact, number, phrase, or scene-shape repeated more than it should.\n"
            "(e) Does each scene earn its place / advance something?"
        ),
    },
    {
        "key": "realism",
        "title": "Danish realism, privacy & translation-robustness",
        "lens": "real-world plausibility in a Danish setting, data privacy/safety, and clean glossing",
        "floor": (
            "(a) Are Danish procedures realistic (offices, IDs, the order of steps)?\n"
            "(b) Privacy/safety — is any sensitive datum (esp. a CPR number) mishandled (read aloud /\n"
            "    repeated digit-by-digit)? Are numbers obviously FICTIONAL, not plausibly-real?\n"
            "(c) Dialogue attribution — would each speaker say things appropriate to their role (a clerk\n"
            "    speaking TO Maya, not in Maya's own voice)?\n"
            "(d) Translation/gloss hazards — beats likely to produce constructions awkward to render in\n"
            "    English / another L1 (written-out abbreviations, lexically ambiguous words, inaccurate\n"
            "    inline glosses of culture-specific terms)."
        ),
    },
    {
        "key": "learner",
        "title": "Naive first-time learner (no checklist)",
        "lens": None,  # open — deliberately no floor
        "floor": None,
    },
]

_LEARNER_BODY = """
YOUR ROLE: You are the LEARNER, hearing this week for the FIRST time — a curious adult beginner.
There is deliberately NO checklist. Experience the beats in order and REACT honestly, as a person,
not an inspector. We use you precisely to catch what a checklist would miss.

What's confusing? boring or flat? oddly repetitive? Where does your attention drift? What made you
think "huh, that's weird" or "wait, why would she do that"? Anything emotionally off (a downbeat that
never resolves, a narrow emotional palette, a week where nothing ever goes even slightly wrong)?
Trust your gut; report whatever strikes you, however small or subjective.
Rate each by gut-strength: High = strong reaction, Med = notable, Low = minor."""

_CONTRACT = """

Return ONLY a JSON object of this exact shape:
{"findings": [{"scene": "<scene number, or 'week'>", "issue": "<one line>",
               "severity": "High" | "Med" | "Low", "why": "<1-2 sentences>"}]}
Use an empty list if you find nothing. Do not summarize the storyboard back."""


def curriculum_row(curriculum_path: str | Path, week: int | None) -> str:
    """Pull the week's table row (+ its section header) from the curriculum, for context."""
    if not curriculum_path or week is None:
        return "(curriculum not provided)"
    text = Path(curriculum_path).read_text(encoding="utf-8")
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line.lstrip("# ").strip()
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
        if cells and cells[0].isdigit() and int(cells[0]) == week:
            return f"[{section}]\n| Wk | Lvl | Theme | Grammar focus | Narrative beat |\n{line.strip()}"
    return f"(no row found for week {week})"


def build_prompt(lens: dict, *, header: str, beats: str, bible: str, curric: str) -> str:
    common = COMMON.format(bible=bible, curric=curric, header=header, beats=beats)
    if lens["key"] == "learner":
        return common + _LEARNER_BODY + _CONTRACT
    body = (
        f"\nYOUR LENS: **{lens['title']}** — {lens['lens']}.\n"
        + _FLOOR_AGENCY.format(floor=lens["floor"])
    )
    return common + body + _CONTRACT


def run_lens(client, model: str, lens: dict, prompt: str) -> list[dict]:
    rep = _json_call(client, model, prompt)
    out = []
    for f in rep.get("findings", []) or []:
        out.append({
            "lens": lens["title"],
            "scene": str(f.get("scene", "?")),
            "issue": (f.get("issue") or f.get("reaction") or "").strip(),
            "severity": (f.get("severity") or "Med").strip().capitalize(),
            "why": (f.get("why") or "").strip(),
        })
    return out


_SEV_RANK = {"High": 0, "Med": 1, "Low": 2}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Review a week's storyboard with the 4-lens panel.")
    ap.add_argument("storyboard", help="path to the week's storyboard.md")
    ap.add_argument("--bible", default="story_bible.md")
    ap.add_argument("--curriculum", default="curriculum_da.md")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="judge model (e.g. gemini-3.1-pro-preview — stronger critic than the generator)")
    ap.add_argument("--location", default=None,
                    help="Vertex location override; Gemini-3 preview models need 'global' (not us-central1)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    if args.location:
        os.environ["GOOGLE_CLOUD_LOCATION"] = args.location  # make_client() reads this

    hdr = parse_storyboard_header(args.storyboard)
    rows = parse_storyboard(args.storyboard)
    header_line = f"Week {hdr['week']} · {hdr['level']} · grammar: {hdr['grammar']} · {len(rows)} scenes"
    beats = "\n".join(f"{r['num']} {r['stem']}: {r['beat']}" for r in rows)
    bible = Path(args.bible).read_text(encoding="utf-8") if Path(args.bible).exists() else "(no bible)"
    curric = curriculum_row(args.curriculum, hdr["week"])

    client = make_client()
    prompts = {l["key"]: build_prompt(l, header=header_line, beats=beats, bible=bible, curric=curric)
               for l in LENSES}

    findings: list[dict] = []
    failed: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(run_lens, client, args.model, l, prompts[l["key"]]): l for l in LENSES}
        for fut in concurrent.futures.as_completed(futs):
            lens = futs[fut]
            try:
                findings.extend(fut.result())
            except Exception as exc:  # one lens failing shouldn't sink the review — but it's NOT a pass
                failed.append(lens["title"])
                print(f"  [warn] lens '{lens['title']}' failed: {exc}")

    findings.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 1), f["lens"]))
    highs = [f for f in findings if f["severity"] == "High"]

    print(f"\n=== STORYBOARD REVIEW — {header_line} ===")
    print(f"{len(findings)} findings ({len(highs)} High) across {len(LENSES) - len(failed)}/{len(LENSES)} lenses\n")
    for f in findings:
        print(f"  [{f['severity']:<4}] (scene {f['scene']}; {f['lens']}) {f['issue']}")
        if f["why"]:
            print(f"         ↳ {f['why']}")
    print()
    if failed:
        # A review that didn't fully run is NOT a pass — never let lens errors read as green.
        print(f"GATE: ⚠ INCOMPLETE — {len(failed)} lens(es) errored ({', '.join(failed)}). "
              f"Fix the error and re-run; do not treat as clear.")
        return 2
    if highs:
        print(f"GATE: ✗ {len(highs)} High-severity finding(s) — revise the storyboard before generating.")
        return 1
    print("GATE: ✓ no High-severity findings — clear to generate (review Med/Low first).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
