"""Storyboard review gate — a 5-lens panel that reviews a week's storyboard BEFORE generation.

Mirrors `verify_scene`, one tier up:  author beats → REVIEW → revise → pass → generate.
Four mechanical lenses (continuity / narrative-logic / realism+privacy / density+variety)
carry a prescribed checklist as a FLOOR *plus* explicit agency; a fifth "naive learner" lens has
NO checklist — it catches what a checklist can't (pacing, monotony, flat mood). The text verifier
checks the generated Danish; this checks the *design*, before any Danish exists.

The DENSITY lens (added 2026-06-27) is the root-cause catch: week 4 ("moving into a flat") passed
this gate clean, then the whole-week text gate forced two scene cuts because the week was one thin
event (a move-in) micro-sliced 14 ways — static room-description scenes, three evening reflections,
a smile/glad flood. All of that is visible in the BEATS. The standard is Anna's-week density: each
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

from tandem.gen import (
    DEFAULT_MODEL,
    make_client,
    parse_storyboard,
    parse_storyboard_header,
)

COMMON = """This is a Danish-for-English-speakers graded AUDIO course (interleaved English→Danish, beginner→up).
A "week" is a STORYBOARD: a set of scene "beats" (one-paragraph summaries). From each beat a model later
generates a short scene of Danish sentences + English glosses, then text-to-speech. You are reviewing the
STORYBOARD (the beats), BEFORE any Danish is generated, to catch design problems while a fix is cheap
(edit a beat, not regenerate + re-verify + re-render).

CONVENTION (do NOT flag): beats are written as 3rd-person summaries ("Maya sits...", "She says...").
The generator converts them to Maya's 1st-person voice ("Jeg sidder...") — this is enforced in the
generation prompt and proven across weeks 1–2. So 3rd-person phrasing in the beats is EXPECTED and
correct; never report it as an issue.

GROUND TRUTH:
--- story_bible.md (established story facts + cross-cutting rules) ---
{bible}
--- end bible ---

--- this week's curriculum row (level / grammar focus / theme) ---
{curric}
(Scene count: right-size to the TOPIC — there is NO minimum. A small topic at 4–5 scenes is fine; a
rich one runs longer. Length comes from how much genuinely happens, not a quota; if a week feels short,
a second activity/topic is added rather than padding one topic. Do NOT flag a week merely for a low
scene count.)
--- end curriculum ---

STORYBOARD UNDER REVIEW — {header}:
{beats}
"""

_FLOOR_AGENCY = """
[Floor — check these at minimum:]
{floor}

[Agency & severity:] The floor is a MINIMUM — also flag anything else off through your lens. Rate each
finding: Med = a problem worth fixing; Low = minor; High = a genuinely blocking problem — content
unusable or wrong as-is that must be fixed before shipping (e.g. a contradiction, a spec/level breach,
a safety/privacy breach, a structural defect; judge by that bar, not only these examples)."""

LENSES = [
    {
        "key": "continuity",
        "title": "Spec & continuity",
        "lens": "consistency with established story facts, and conformance to the week's curriculum spec",
        "floor": (
            "(a) Does any beat CONTRADICT a story_bible fact, or RE-INTRODUCE as new something Maya\n"
            "    already has/knows/is (housing, address, phone, CPR, job, relationships)?\n"
            "(b) Does the week hit its curriculum grammar focus and its theme?\n"
            "(c) Does the scene count COVER the week's grammar without padding? Flag only padding or\n"
            "    genuine grammar under-coverage.\n"
            "(d) Level-appropriate (no out-of-scope grammar,\n"
            "    e.g. ordinals/past-tense before they are introduced)?\n"
            "(e) Character facts consistent (recurring cast, Maya's age/origin)?"
        ),
    },
    {
        "key": "logic",
        "title": "Narrative logic & coherence",
        "lens": "internal logic, ordering, redundancy, and dramatic sense within the week",
        "floor": (
            "(a) Redundancy / over-repetition — the same information, fact, number, phrase, or\n"
            "    scene-shape delivered more than once (e.g. a plan stated, then restated).\n"
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
            "(d) Translation/gloss hazards — beats likely to produce constructions awkward to render in\n"
            "    English / another L1 (written-out abbreviations, lexically ambiguous words, inaccurate\n"
            "    inline glosses of culture-specific terms)."
        ),
    },
    {
        "key": "density",
        "title": "Density, activity & variety",
        "lens": "whether each scene is a real activity that moves and the week is varied, not one thin situation micro-sliced to fill a scene count",
        "floor": (
            "STANDARD (the bar for each scene): a complete mini-vignette that MOVES — like a market\n"
            "visit (several stalls, a small exchange at each). NOT a static description of a place, an\n"
            "inventory of objects, or a mood with no action.\n"
            "(a) ACTIVITY per scene — is each scene a real activity that moves, with a small\n"
            "    beginning→middle→end? Or is it static description (what a room looks like, where\n"
            "    objects are, a feeling restated)? FLAG every description-only scene. A smooth, ordinary\n"
            "    task done well IS the standard.\n"
            "(b) WEEK variety — does the week span several DISTINCT situations (different places, people,\n"
            "    tasks), or micro-slice ONE event (a single move-in, a single tour) across many scenes?\n"
            "    FLAG a week that is one thin situation stretched to length. Also FLAG the SAME kind of\n"
            "    beat repeated (e.g. several 'she meets an unfamiliar thing' scenes) — vary the shape.\n"
            "    (Few scenes is not itself a fault — see the scene-count note above.) The fix for a thin\n"
            "    week is a second activity/topic, never padding one topic to fill a count.\n"
            "(c) CONCRETE texture — does each scene bring its OWN concrete detail — nouns, actions, the\n"
            "    odd sensory note (a smell, warmth, a taste, a small pleasure) — or lean on generic\n"
            "    filler (small, nice, happy, good, lovely, smiles)? FLAG generic/interchangeable scenes.\n"
            "(d) CUT/MERGE — could thin scenes be cut or merged with no loss? Name which.\n"
            "(e) COMMON VOCABULARY — keep the beats in common, everyday words. The axis is common-vs-\n"
            "    technical, NOT specific-vs-generic: SPECIFIC-and-common is ideal and memorable\n"
            "    (strawberries, rye bread, a heavy box, a lost key); SPECIFIC-and-technical is what costs\n"
            "    (a thermostat, a valve, induction controls, a tax appeal). FLAG any beat that drags in\n"
            "    technical/rare nouns when a common-vocab beat of the same shape would do."
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
never resolves, a narrow emotional palette, the same beat or device repeated until it grates)?
Trust your gut; report whatever strikes you, however small or subjective.
Rate each by gut-strength: High = strong reaction, Med = notable, Low = minor."""

_CONTRACT = """

Return ONLY a JSON object of this exact shape:
{"findings": [{"scene": "<scene number, or 'week'>", "issue": "<one line>",
               "severity": "High" | "Med" | "Low", "why": "<1-2 sentences>"}]}
Use an empty list if you find nothing. Do not summarize the content back."""


def curriculum_row(curriculum_path: str | Path, week: int | None) -> str:
    """Pull the week's table row (+ its section header and the table's own column header) from the curriculum, for context."""
    if not curriculum_path or week is None:
        return "(curriculum not provided)"
    text = Path(curriculum_path).read_text(encoding="utf-8")
    section = ""
    header = ""                                     # the table's column-header row, read from the file
    for line in text.splitlines():
        if line.startswith("## "):
            section = line.lstrip("# ").strip()
            header = ""                             # each section has its own table; don't carry one over
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= {"-", ":"} for c in cells):   # |---|:--:| separator row — skip
            continue
        if cells and cells[0].isdigit():               # a data row (first cell is the week number)
            if int(cells[0]) == week:
                head = f"{header}\n" if header else ""
                return f"[{section}]\n{head}{stripped}"
            continue
        header = stripped                              # non-separator, non-data |-row = the column header
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


def _call_findings(client, model: str, prompt: str) -> list[dict]:
    """Call the judge for a JSON {findings:[...]} and return the list, robust to truncation.

    A reasoning model can run long and get its JSON cut off mid-array. Rather than crash the whole
    panel on one flaky lens, we salvage every COMPLETE finding object and drop the truncated tail.
    Only a total parse failure raises — so main() can mark that lens incomplete (never a silent pass).
    """
    from google.genai import types

    resp = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           max_output_tokens=8192),
    )
    text = (resp.text or "").strip()
    try:
        return json.loads(text).get("findings", []) or []
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
    return objs


def run_lens(client, model: str, lens: dict, prompt: str) -> list[dict]:
    raw = _call_findings(client, model, prompt)
    out = []
    for f in raw:
        out.append({
            "lens": lens["title"],
            "scene": str(f.get("scene", "?")),
            "issue": (f.get("issue") or f.get("reaction") or "").strip(),
            "severity": (f.get("severity") or "Med").strip().capitalize(),
            "why": (f.get("why") or "").strip(),
            "advisory": lens.get("floor") is None,   # the open naive lens is a human signal, never blocks
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
    highs = [f for f in findings if f["severity"] == "High" and not f["advisory"]]
    adv_high = sum(1 for f in findings if f["severity"] == "High" and f["advisory"])

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
