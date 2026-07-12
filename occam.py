#!/usr/bin/env python3
"""Occam gate — the one artifact class nothing else reviews: the TEXT WE WRITE BY HAND.

Everything downstream of the brief is gated (storyboard -> review_storyboard; scenes -> verify_scene +
review_week). The brief that steers all of it, and the prompts that drive the pipeline, are gated only
by the human catching them — which is the job we are trying to stop doing by hand.

  occam.py brief 6                # the week's curriculum row: theme / grammar / brief
  occam.py diff                   # every ADDED line in the working diff (prompts, rules, briefs)
  occam.py text some_prompt.md    # any prose we wrote

Exit 1 if anything must be cut. Run:  set -a; . ./.env; set +a;  .venv/bin/python occam.py brief 6
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from tandem.gen import DEFAULT_MODEL
from tandem.llm import make_client
from review_storyboard import _call_findings

CURRICULUM = "curriculum_da.md"

# The bar, stated as principles. NOT a list of examples to pattern-match — that narrows a judge to
# exactly the cases named (the very failure this gate exists to catch).
_BAR = """You are applying Occam's razor to text that steers a language model. Every word is either
load-bearing or it is noise that dilutes the words around it. Cut and merge; never add.

Flag, in order of severity:
- REDUNDANT — it says something already said elsewhere in the material you were given, or something the
  reader/model would do anyway. The test is: if this were deleted, would anything change?
- ENUMERATION — it lists instances of a rule instead of stating the rule. A model reads a list as the
  definition of the task and looks only for what is named, so examples NARROW rather than illustrate.
- NOT PLAIN — it needs decoding: idiom, metaphor, cleverness, a fancy verb where a plain one exists, a
  clause that has to be read twice. The model reads literally, and so does a tired human.
- BLOAT — more words than the thought needs.

For each finding give the exact text, and the replacement — a shorter line, or nothing at all.
Say nothing about text that is already doing its job. An empty findings list is the correct answer for
tight text; do not invent work.
"""

_CONTRACT = """
Return JSON exactly:
{"findings": [{"severity": "High|Med|Low", "quote": "<the exact text to cut or change>",
               "issue": "<REDUNDANT|ENUMERATION|NOT PLAIN|BLOAT>", "why": "<one sentence>",
               "fix": "<the replacement text, or \\"cut\\" if it should just go>"}]}
High = must be cut before this text is used. Med = should be. Low = taste.
"""

_BRIEF_LENS = """
This is one WEEK of a Danish course. The BRIEF steers the storyboard generator, which invents the week's
scenes; the generator sees the brief, the theme and the grammar together, exactly as shown below.

A brief should be a SUMMARY of the week we want — what happens, narrated — plus a trailing clause for the
ABSENCES (what must NOT appear, and which week owns it). It is a steer, not a shot-list. Roughly four
short sentences.

Judge the brief against that, and against the standing rules the generator ALREADY has (below) — flag
anything the brief repeats.

Judge the GRAMMAR FOCUS too. It names the week's target and nothing more. Explaining Danish to models
that write it natively is noise; flag anything phrased as an instruction.
"""

_DIFF_LENS = """
Lines we just ADDED. Judge ONLY the added lines (+), and ONLY the text a MODEL will read: prompt
strings, judge criteria, curriculum specs. Code, comments and log messages are read by people, not
models — say nothing about them.
"""


def curriculum_row(week: int) -> dict:
    for line in Path(CURRICULUM).read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0].isdigit() and int(cells[0]) == week:
            return {"wk": week, "level": cells[1], "theme": cells[2],
                    "grammar": cells[3], "brief": cells[4]}
    raise SystemExit(f"week {week} not found in {CURRICULUM}")


def standing_rules() -> str:
    """The rules gen_storyboard already gives the model — the brief must not repeat these."""
    src = Path("gen_storyboard.py").read_text(encoding="utf-8")
    return src.split("Rules:\n", 1)[1].split('\n\nReturn JSON', 1)[0] if "Rules:\n" in src else ""


def build_prompt(kind: str, subject: str, extra: str = "") -> str:
    lens = {"brief": _BRIEF_LENS, "diff": _DIFF_LENS}.get(kind, "")
    return f"{_BAR}\n{lens}\n{extra}\nTHE TEXT TO JUDGE:\n<<<TEXT\n{subject}\nTEXT\n{_CONTRACT}"


def report(findings: list[dict]) -> int:
    if not findings:
        print("\n✓ OCCAM: nothing to cut.\n")
        return 0
    rank = {"High": 0, "Med": 1, "Low": 2}
    for f in sorted(findings, key=lambda f: rank.get(f.get("severity", "Med"), 1)):
        print(f"\n  [{f.get('severity', '?'):<4}] {f.get('issue', '?')}")
        print(f"     “{f.get('quote', '').strip()}”")
        print(f"     ↳ {f.get('why', '')}")
        print(f"     → {f.get('fix', '')}")
    highs = [f for f in findings if f.get("severity") == "High"]
    print(f"\nOCCAM: {len(findings)} finding(s), {len(highs)} must-cut.\n")
    return 1 if highs else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["brief", "diff", "text"])
    ap.add_argument("target", nargs="?", help="week number (brief), git ref (diff), or path (text)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--location", default="global")
    ap.add_argument("--show-prompt", action="store_true", help="print the prompt and exit (no API call)")
    a = ap.parse_args()
    os.environ["GOOGLE_CLOUD_LOCATION"] = a.location

    if a.mode == "brief":
        row = curriculum_row(int(a.target))
        subject = (f"Week {row['wk']} · Level {row['level']}\n"
                   f"Theme: {row['theme']}\n"
                   f"Grammar focus: {row['grammar']}\n"
                   f"Brief: {row['brief']}")
        extra = f"THE GENERATOR'S STANDING RULES (already in its prompt):\n{standing_rules()}"
    elif a.mode == "diff":
        # default: the working diff. A ref judges past commits; "cached" judges what is STAGED (the hook).
        ref = "--cached" if a.target == "cached" else (a.target or "HEAD")
        subject = subprocess.run(  # only text WE write — never the generated weeks under year1/
            ["git", "diff", "-U2", ref, "--", "*.py", "*.md", ":!year1"],
            capture_output=True, text=True, check=False).stdout
        if not subject.strip():
            print("nothing to judge in the diff.")
            return 0
        extra = ""
    else:
        subject, extra = Path(a.target).read_text(encoding="utf-8"), ""

    prompt = build_prompt(a.mode, subject, extra)
    if a.show_prompt:
        print(prompt)
        return 0
    # _call_findings caps the output and SALVAGES a truncated findings array — a long file (e.g.
    # continuity_check.py) overflowed the plain JSON call and killed the whole run.
    findings = _call_findings(make_client(), a.model, prompt, stage=f"occam.{a.mode}")
    return report(findings or [])


if __name__ == "__main__":
    raise SystemExit(main())
