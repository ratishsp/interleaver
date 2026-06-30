"""Week-content review gate — a panel that reads the WHOLE generated week.

Completes the verification matrix:
                 per-scene             whole-week
   design          —                   review_storyboard (beats)
   text            verify_scene        review_week (this)   <-- the gap

`verify_scene` reads one scene in isolation, so it is structurally blind to anything that is a
property of the WHOLE WEEK: repetition/monotony across scenes, the mood arc, cross-scene continuity,
pacing. Those are exactly the issues a human keeps catching by hand (an emotion restated in four
scenes, a week that ends on "alone", a time-zone that flips between scenes). This panel reads every
scene in order and checks them — pushing that human pass into the pipeline so it holds at scale.

Reuses review_storyboard's panel machinery (the robust judge call, severity rank, floor+agency and
output contract). Same gate semantics: High-severity findings block; an incomplete run (a lens errors)
is never a silent pass.

Run:  set -a; . ./.env; set +a; export GOOGLE_CLOUD_LOCATION=global
      .venv/bin/python review_week.py year1/week03/storyboard.md --model gemini-3.1-pro-preview
"""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import os
from pathlib import Path

from tandem.gen import DEFAULT_MODEL, make_client, parse_storyboard, parse_storyboard_header
from review_storyboard import _call_findings, _SEV_RANK, _FLOOR_AGENCY, _CONTRACT, curriculum_row

COMMON = """This is a Danish-for-English-speakers graded AUDIO course (interleaved English→Danish). A
"week" is several short scenes; the learner hears them one after another in a sitting. You are reviewing
the GENERATED TEXT of a FULL WEEK — every scene, in order, as "Danish line  |  English gloss".

A separate PER-SCENE verifier already checked each scene's Danish in isolation (grammar, alignment,
naturalness). Do NOT re-do that. YOUR job is the WHOLE-WEEK view — only what is visible ACROSS scenes:
repetition, the emotional arc, cross-scene consistency, and pacing.

IMPORTANT CALIBRATION — this is a comprehensible-input beginner LANGUAGE course, NOT a novel. MODERATE
repetition of common words and simple phrases is PEDAGOGICALLY GOOD (it reinforces vocabulary) and is
EXPECTED — not a defect. Do NOT flag a word or phrase merely for recurring across scenes (a learner
hearing "varm" or "på skærmen" several times is fine and useful).

GROUND TRUTH:
--- story_bible.md (facts + cross-cutting rules) ---
{bible}
--- this week's curriculum row ---
{curric}
--- end ---

THE FULL WEEK — {header}:
{week_text}
"""

_LISTENER_BODY = """
YOUR ROLE: You are the LEARNER, listening to this ENTIRE week back-to-back for the first time — a
curious adult beginner. There is deliberately NO checklist. Take the scenes in order as one sitting
and REACT honestly, as a person.

Where did your attention drift? What dragged or felt repetitive from scene to scene? Did the week feel
warm and hopeful, or a bit flat / sad? Did a later scene clash with an earlier one? What would make
you stop listening? Trust your gut and report whatever strikes you about the WEEK AS A WHOLE (not
single lines — the per-scene check already covered those). Rate by gut-strength: High / Med / Low."""

LENSES = [
    {
        "key": "repetition",
        "title": "Repetition & monotony",
        "lens": "things over-repeated or too samey across the week",
        "floor": (
            "(a) An emotion or state asserted in scene after scene (e.g. the same feeling restated).\n"
            "(b) Scenes built on an identical shape/template — a 'roll-call' of near-identical beats.\n"
            "(c) A whole scene that recaps another (near-verbatim summary of the same content).\n"
            "(d) A refrain — the same small action or line recurring scene after scene.\n"
            "Reserve High for clear, listener-noticeable monotony."
        ),
    },
    {
        "key": "mood",
        "title": "Mood & emotional arc",
        "lens": "the week's emotional shape as a whole",
        # Mood-resolution rule lives here, not in the bible — this is the only mood gate.
        "floor": (
            "(a) Resolution — never leave a scene, or the week, on despair/loneliness. Flag the week\n"
            "    if its arc doesn't lift by the end, and any individual scene that ends on a down note\n"
            "    with no lift.\n"
            "(b) Cumulative gloom — sadness/loneliness/cold/dark stacked across scenes without warmth.\n"
            "(c) Emotional range — or is the whole week stuck on one narrow note?"
        ),
    },
    {
        "key": "continuity",
        "title": "Cross-scene continuity & consistency",
        "lens": "facts holding consistent from scene to scene across the week",
        "floor": (
            "(a) Time consistency — time of day, and time-zone between places — across scenes.\n"
            "(b) Names / characters / objects consistent; nothing contradicts an earlier scene this week.\n"
            "(c) What the character has / knows / has done stays consistent scene to scene.\n"
            "(d) The sequence of events makes sense from the first scene to the last."
        ),
    },
    {
        "key": "listener",
        "title": "Naive whole-week listener (no checklist)",
        "lens": None,
        "floor": None,
    },
]


def assemble_week(storyboard_path: str | Path) -> str:
    """Read every scene's .da/.en (in storyboard order) into one 'DA | EN' block per scene."""
    rows = parse_storyboard(storyboard_path)
    wdir = Path(storyboard_path).parent
    parts = []
    for r in rows:
        da, en = wdir / f"{r['stem']}.da", wdir / f"{r['stem']}.en"
        if not (da.exists() and en.exists()):
            continue
        dal = da.read_text(encoding="utf-8").splitlines()
        enl = en.read_text(encoding="utf-8").splitlines()
        body = "\n".join(f"  {d}  |  {e}" for d, e in zip(dal, enl))
        parts.append(f"## Scene {r['num']} — {r['stem']}\n{body}")
    return "\n\n".join(parts)


def build_prompt(lens: dict, *, header: str, week_text: str, bible: str, curric: str) -> str:
    common = COMMON.format(bible=bible, curric=curric, header=header, week_text=week_text)
    if lens["key"] == "listener":
        return common + _LISTENER_BODY + _CONTRACT
    body = (f"\nYOUR LENS: **{lens['title']}** — {lens['lens']}.\n"
            + _FLOOR_AGENCY.format(floor=lens["floor"]))
    return common + body + _CONTRACT


def run_lens(client, model: str, lens: dict, prompt: str) -> list[dict]:
    out = []
    for f in _call_findings(client, model, prompt):
        out.append({
            "lens": lens["title"],
            "scene": str(f.get("scene", "?")),
            "issue": (f.get("issue") or f.get("reaction") or "").strip(),
            "severity": (f.get("severity") or "Med").strip().capitalize(),
            "why": (f.get("why") or "").strip(),
            "advisory": lens.get("floor") is None,   # the open naive lens is a human signal, never blocks
        })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Review a whole week's generated content with the 4-lens panel.")
    ap.add_argument("storyboard", help="path to the week's storyboard.md (its dir holds the .da/.en)")
    ap.add_argument("--bible", default="story_bible.md")
    ap.add_argument("--curriculum", default="curriculum_da.md")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="judge model (e.g. gemini-3.1-pro-preview)")
    ap.add_argument("--location", default="global",
                    help="Vertex location (default 'global' — required for gemini-3 models)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", help="also write the findings list as JSON to this path (for the week-revise loop)")
    args = ap.parse_args(argv)
    if args.location:
        os.environ["GOOGLE_CLOUD_LOCATION"] = args.location

    hdr = parse_storyboard_header(args.storyboard)
    rows = parse_storyboard(args.storyboard)
    header_line = f"Week {hdr['week']} · {hdr['level']} · grammar: {hdr['grammar']} · {len(rows)} scenes"
    week_text = assemble_week(args.storyboard)
    bible = Path(args.bible).read_text(encoding="utf-8") if Path(args.bible).exists() else "(no bible)"
    curric = curriculum_row(args.curriculum, hdr["week"])

    client = make_client()
    prompts = {l["key"]: build_prompt(l, header=header_line, week_text=week_text, bible=bible, curric=curric)
               for l in LENSES}

    findings: list[dict] = []
    failed: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(run_lens, client, args.model, l, prompts[l["key"]]): l for l in LENSES}
        for fut in concurrent.futures.as_completed(futs):
            lens = futs[fut]
            try:
                findings.extend(fut.result())
            except Exception as exc:
                failed.append(lens["title"])
                print(f"  [warn] lens '{lens['title']}' failed: {exc}")

    findings.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 1), f["lens"]))
    highs = [f for f in findings if f["severity"] == "High" and not f["advisory"]]
    adv_high = sum(1 for f in findings if f["severity"] == "High" and f["advisory"])
    if args.out:
        Path(args.out).write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== WEEK-CONTENT REVIEW — {header_line} ===")
    extra = f", {adv_high} advisory High" if adv_high else ""
    print(f"{len(findings)} findings ({len(highs)} blocking High{extra}) across {len(LENSES) - len(failed)}/{len(LENSES)} lenses\n")
    for f in findings:
        adv = "  (advisory — does not block)" if f["advisory"] else ""
        print(f"  [{f['severity']:<4}] (scene {f['scene']}; {f['lens']}) {f['issue']}{adv}")
        if f["why"]:
            print(f"         ↳ {f['why']}")
    print()
    if failed:
        print(f"GATE: ⚠ INCOMPLETE — {len(failed)} lens(es) errored ({', '.join(failed)}). Re-run; not a pass.")
        return 2
    if highs:
        print(f"GATE: ✗ {len(highs)} blocking High finding(s) — fix the week before audio.")
        return 1
    print("GATE: ✓ no blocking findings — clear for audio (review advisory + Med/Low first).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
