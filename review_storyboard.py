"""Storyboard review gate — a 5-lens panel that reviews a week's storyboard BEFORE generation.

Mirrors `verify_scene`, one tier up:  author scenes → REVIEW → revise → pass → generate.
Four mechanical lenses (continuity / narrative-logic / realism+privacy / density+variety)
carry a prescribed checklist as a FLOOR *plus* explicit agency; a fifth "naive learner" lens has
NO checklist — it catches what a checklist can't (pacing, monotony, flat mood). The text verifier
checks the generated Danish; this checks the *design*, before any Danish exists.

The DENSITY lens (added 2026-06-27) is the root-cause catch: week 4 ("moving into a flat") passed
this gate clean, then the whole-week text gate forced two scene cuts because the week was one thin
event (a move-in) micro-sliced 14 ways — static room-description scenes, three evening reflections,
a smile/glad flood. All of that is visible in the SCENES. The standard is Anna's-week density: each
scene a complete mini-vignette that MOVES (a market visit hitting several stalls), not a furniture
inventory; the week spanning varied situations, not one thin event micro-sliced.

Why a panel, why agency: a reviewer's errors are asymmetric — a false alarm costs seconds to
dismiss, a miss costs a bad week (×50 at scale). So each lens is told its checklist is a MINIMUM,
not a maximum, and to err toward surfacing.

Validated 2026-06-27 on the pre-fix week-2 storyboard (commit d04b950): the panel independently
caught all 5 issues we'd found by hand (CPR-read-aloud, texts-before-having-number, already-has-
address, bus#4/4-stops, plan-duplication) plus real residual ones (out-of-scope ordinal, the
12/14 recap, the "writes it down" refrain, flat-affect monotony).

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

from tandem.llm import make_client, trace, generate_retrying
from tandem.gen import (
    DEFAULT_MODEL,
    parse_storyboard,
    parse_storyboard_header,
)

COMMON = """This is a Danish-for-English-speakers graded AUDIO course (interleaved English→Danish, beginner→up).
A "week" is a STORYBOARD: a set of SCENES (one-paragraph summaries). From each scene a model later
generates a short passage of Danish sentences + English glosses, then text-to-speech. You are reviewing the
STORYBOARD (the scenes), BEFORE any Danish is generated, to catch design problems while a fix is cheap
(edit a scene, not regenerate + re-verify + re-render).

CONVENTION (do NOT flag): scenes are 3rd-person summaries ("Maya sits..."); the generator converts them to Maya's 1st-person Danish. Never flag the 3rd-person phrasing.

GROUND TRUTH:
--- story_bible.md (established story facts + cross-cutting rules) ---
{bible}
--- end bible ---

--- this week's curriculum spec ---
{curric}
--- end curriculum ---

STORYBOARD UNDER REVIEW — {header}:
{scenes}
"""

_FLOOR_AGENCY = """
[Floor — check at least these, and flag anything else off through your lens:]
{floor}

[Severity:] Med = a problem worth fixing; Low = minor; High = a genuinely blocking problem — content
unusable or wrong as-is that must be fixed before shipping (e.g. a contradiction, a spec/level breach,
a safety/privacy breach, a structural defect; judge by that bar, not only these examples)."""

LENSES = [
    {
        "key": "continuity",
        "title": "Spec & continuity",
        "lens": "consistency with established story facts, and conformance to the week's curriculum spec",
        "floor": (
            "(a) Does any scene CONTRADICT a story_bible fact, or RE-INTRODUCE as new something Maya\n"
            "    already has/knows/is (housing, address, phone, CPR, job, relationships, recurring cast,\n"
            "    her age/origin)?\n"
            "(b) Does the week hit its curriculum grammar focus and its theme?\n"
            "(c) Level-appropriate (no out-of-scope grammar,\n"
            "    e.g. ordinals/past-tense before they are introduced)?"
        ),
    },
    {
        "key": "logic",
        "title": "Narrative logic & coherence",
        "lens": "internal logic, ordering, redundancy, and dramatic sense within the week",
        "floor": (
            "(a) Redundancy / over-repetition — the same information, fact, number, phrase, or\n"
            "    scene-shape delivered more than once.\n"
            "(b) Logic gaps — does any action presuppose something not yet true (contacting someone\n"
            "    before you could have their contact details)?\n"
            "(c) Ordering / cause-effect plausibility across scenes.\n"
            "(d) Does each scene earn its place / advance something?"
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
            "(d) Translation/gloss hazards — scenes likely to produce constructions awkward to render in\n"
            "    English / another L1 (written-out abbreviations, lexically ambiguous words, inaccurate\n"
            "    inline glosses of culture-specific terms)."
        ),
    },
    {
        "key": "density",
        "title": "Density, activity & variety",
        "lens": "whether each scene is a real activity that moves and the week is varied, not one thin situation micro-sliced to fill a scene count",
        "floor": (
            "(a) ACTIVITY per scene — each scene should be a complete mini-vignette that MOVES (a small\n"
            "    beginning→middle→end), not a static description, object inventory, or restated feeling.\n"
            "    FLAG description-only scenes; an ordinary task done well IS the standard.\n"
            "(b) WEEK variety — does the week span several DISTINCT situations (different places, people,\n"
            "    tasks)?\n"
            "    FLAG a week that is one thin situation stretched to length.\n"
            "(c) CONCRETE texture — does each scene bring its OWN concrete detail — nouns, actions, the\n"
            "    odd sensory note (a smell, warmth, a taste, a small pleasure) — or lean on generic\n"
            "    filler (small, nice, happy, good, lovely, smiles)? FLAG generic/interchangeable scenes.\n"
            "(d) COMMON VOCABULARY — keep the scenes in common, everyday words (the axis is common-vs-\n"
            "    technical, not specific-vs-generic: 'rye bread' is great, 'a thermostat' is not). FLAG\n"
            "    any scene that drags in technical/rare nouns when a common one of the same shape would do."
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
There is deliberately NO checklist. Experience the scenes in order and REACT honestly, as a person,
not an inspector. We use you precisely to catch what a checklist would miss.

What's confusing? boring or flat? oddly repetitive? Where does your attention drift? What made you
think "huh, that's weird" or "wait, why would she do that"? Anything emotionally off (a downbeat that
never resolves, a narrow emotional palette, the same scene or device repeated until it grates)?
Trust your gut; report whatever strikes you, however small or subjective.
Rate each by gut-strength: High = strong reaction, Med = notable, Low = minor."""

_CONTRACT = """

Return ONLY a JSON object of this exact shape:
{"findings": [{"scene": "<scene number, or 'week'>", "issue": "<one line>",
               "severity": "High" | "Med" | "Low", "why": "<1-2 sentences>"}]}
Use an empty list if you find nothing. Do not summarize the content back."""


def curriculum_row(curriculum_path: str | Path, week: int | None) -> str:
    """Pull the week's row as LABELED fields (level / grammar / theme / brief), for review context.

    The brief is the week's intended shape — labeling it (rather than leaving it an unlabeled
    trailing cell of the raw markdown row) lets the reviewer weigh it as the design intent.
    """
    if not curriculum_path or week is None:
        return "(curriculum not provided)"
    section = ""
    for line in Path(curriculum_path).read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line.lstrip("# ").strip()
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0].isdigit() and int(cells[0]) == week:
            return (f"[{section}] Week {cells[0]} · Level {cells[1]} · Theme: {cells[2]}\n"
                    f"Grammar focus: {cells[3]}\n"
                    f"Brief (the week's intended shape — the storyboard should realize THIS): {cells[4]}")
    return f"(no row found for week {week})"


def build_prompt(lens: dict, *, header: str, scenes: str, bible: str, curric: str) -> str:
    common = COMMON.format(bible=bible, curric=curric, header=header, scenes=scenes)
    if lens["key"] == "learner":
        return common + _LEARNER_BODY + _CONTRACT
    body = (
        f"\nYOUR LENS: **{lens['title']}** — {lens['lens']}.\n"
        + _FLOOR_AGENCY.format(floor=lens["floor"])
    )
    return common + body + _CONTRACT


def _call_findings(client, model: str, prompt: str, stage: str = "") -> list[dict]:
    """Call the judge for a JSON {findings:[...]} and return the list, robust to truncation.

    No output cap: on a reasoning model the THINKING tokens count against max_output_tokens, so a cap
    big enough for the findings could still be spent thinking and return an EMPTY response (it did, on a
    whole source file). Salvage stays as the safety net: keep every COMPLETE finding object, drop a
    truncated tail. Only a total parse failure raises — so main() can mark that lens incomplete
    (never a silent pass).
    """
    from google.genai import types

    resp = generate_retrying(client, model, prompt,
                             types.GenerateContentConfig(response_mime_type="application/json"))
    text = (resp.text or "").strip()
    try:
        findings = json.loads(text).get("findings", []) or []
        trace(stage, model, prompt, findings)
        return findings
    except json.JSONDecodeError:
        pass
    # Salvage: scan balanced {...} objects inside the findings array; keep the parseable ones.
    objs, depth, start = [], 0, None
    for j in range(max(0, text.find("findings")), len(text)):
        c = text[j]
        if c == "{":
            if depth == 0:
                start = j
            depth += 1
        elif c == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    objs.append(json.loads(text[start:j + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    if not objs:
        raise RuntimeError(f"unparseable JSON from judge ({len(text)} chars)")
    trace(stage, model, prompt, objs)
    return objs


def run_lens(client, model: str, lens: dict, prompt: str) -> list[dict]:
    raw = _call_findings(client, model, prompt, stage=f"storyboard_gate.{lens['key']}")
    out = []
    for f in raw:
        severity = (f.get("severity") or "Med").strip().capitalize()
        out.append({
            "lens": lens["title"],
            "scene": str(f.get("scene", "?")),
            "issue": (f.get("issue") or f.get("reaction") or "").strip(),
            "severity": severity,
            "why": (f.get("why") or "").strip(),
            # The naive-learner lens's reactions count like any other lens: a High (any lens) blocks the
            # gate, and a Med drives a revise round in the loop. Only its Low stays advisory (soft signal).
            "advisory": lens.get("floor") is None and severity == "Low",
        })
    return out


_SEV_RANK = {"High": 0, "Med": 1, "Low": 2}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Review a week's storyboard with the 5-lens panel.")
    ap.add_argument("storyboard", help="path to the week's storyboard.md")
    ap.add_argument("--bible", default="story_bible.md")
    ap.add_argument("--curriculum", default="curriculum_da.md")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="judge model (e.g. gemini-3.1-pro-preview — stronger critic than the generator)")
    ap.add_argument("--location", default="global",
                    help="Vertex location (default 'global' — required for gemini-3 models; not us-central1)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", help="also write the findings list as JSON to this path (for the autonomous loop)")
    ap.add_argument("--show-prompt", action="store_true",
                    help="print each lens's prompt and exit (no API call)")
    args = ap.parse_args(argv)
    if args.location:
        os.environ["GOOGLE_CLOUD_LOCATION"] = args.location  # make_client() reads this

    hdr = parse_storyboard_header(args.storyboard)
    rows = parse_storyboard(args.storyboard)
    header_line = f"Week {hdr['week']} · {hdr['level']} · grammar: {hdr['grammar']} · {len(rows)} scenes"
    scenes = "\n".join(f"{r['num']} {r['stem']}: {r['scene']}" for r in rows)
    bible = Path(args.bible).read_text(encoding="utf-8") if Path(args.bible).exists() else "(no bible)"
    curric = curriculum_row(args.curriculum, hdr["week"])

    if args.show_prompt:
        for l in LENSES:
            print(f"\n{'=' * 70}\nLENS: {l['title']}\n{'=' * 70}\n"
                  + build_prompt(l, header=header_line, scenes=scenes, bible=bible, curric=curric))
        return 0

    client = make_client()
    prompts = {l["key"]: build_prompt(l, header=header_line, scenes=scenes, bible=bible, curric=curric)
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
    highs = [f for f in findings if f["severity"] == "High" and not f["advisory"]]
    adv_high = sum(1 for f in findings if f["severity"] == "High" and f["advisory"])
    if args.out:
        Path(args.out).write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== STORYBOARD REVIEW — {header_line} ===")
    extra = f", {adv_high} advisory High" if adv_high else ""
    print(f"{len(findings)} findings ({len(highs)} blocking High{extra}) across {len(LENSES) - len(failed)}/{len(LENSES)} lenses\n")
    for f in findings:
        adv = "  (advisory — does not block)" if f["advisory"] else ""
        print(f"  [{f['severity']:<4}] (scene {f['scene']}; {f['lens']}) {f['issue']}{adv}")
        if f["why"]:
            print(f"         ↳ {f['why']}")
    print()
    if failed:
        # A review that didn't fully run is NOT a pass — never let lens errors read as green.
        print(f"GATE: ⚠ INCOMPLETE — {len(failed)} lens(es) errored ({', '.join(failed)}). "
              f"Fix the error and re-run; do not treat as clear.")
        return 2
    if highs:
        print(f"GATE: ✗ {len(highs)} blocking High finding(s) — revise the storyboard before generating.")
        return 1
    print("GATE: ✓ no blocking findings — clear to generate (review advisory + Med/Low first).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
