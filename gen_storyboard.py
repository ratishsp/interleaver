#!/usr/bin/env python3
"""PROTOTYPE: autonomously author a week's storyboard, then self-correct against the design gate.

The loop:  generate  ->  review_storyboard.py (gate)  ->  if blocking Highs, revise with the
findings fed back  ->  re-gate  ->  ... up to --max-rounds, then escalate (print best + remaining).

Inputs (deliberately NOT design_notes.md — too long):
  - the target week's row in curriculum_da.md (theme / grammar / narrative beat)
  - story_bible.md (continuity ground-truth, via tandem.gen.load_story_bible)
  - the PREVIOUS week's storyboard.md as a format + style exemplar.

Run:  set -a; . ./.env; set +a;  .venv/bin/python gen_storyboard.py 4 --cycle
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from tandem.gen import make_client, _json_call, load_story_bible, DEFAULT_MODEL

CURRICULUM = "curriculum_da.md"


def curriculum_row(week: int) -> dict:
    for line in Path(CURRICULUM).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 5 and cells[0].isdigit() and int(cells[0]) == week:
            return {"wk": week, "level": cells[1], "theme": cells[2],
                    "grammar": cells[3], "beat": cells[4]}
    raise SystemExit(f"week {week} not found in {CURRICULUM}")


def _revise_block(prior_md: str, findings: list[dict]) -> str:
    """Build the rewrite instruction from the gate's blocking + Med findings."""
    keep = [f for f in findings
            if f.get("severity") in ("High", "Med") and not f.get("advisory")]
    items = "\n".join(f"- (scene {f.get('scene')}) {f.get('issue')} — {f.get('why', '')}"
                      for f in keep)
    return f"""
YOUR PREVIOUS DRAFT for this week was reviewed and did NOT pass. Here it is:
<<<PRIOR_DRAFT
{prior_md}
PRIOR_DRAFT

A strict review panel returned these problems. Rewrite the WHOLE storyboard from scratch and fix
EVERY one of them, while keeping what already worked:
{items}

When the panel says a single event is micro-sliced across too many thin scenes, CONDENSE it into
fewer, richer scenes (each a complete activity that moves), and add other DISTINCT situations so the
week has genuine variety — do not just renumber the same object-by-object beats.
"""


def build_prompt(row: dict, exemplar_text: str, exemplar_wk: int,
                 prior_md: str | None = None, findings: list[dict] | None = None) -> str:
    bible = load_story_bible()
    revise = _revise_block(prior_md, findings) if (prior_md and findings) else ""
    return f"""{bible}

You are authoring the STORYBOARD for one week of a Danish (A1->B2) audio course told as Maya's
first-person story. A storyboard decomposes the week's one-line narrative beat into an ordered
sequence of short scenes; each scene is later written as line-aligned Danish/English.

FORMAT + STYLE EXAMPLE — here is the finished storyboard for week {exemplar_wk}. Match its shape and
craft: a short design-rationale paragraph, then a numbered scene list where each scene's beat names a
concrete action AND, in parentheses, the target grammar carried through that action.
<<<EXAMPLE
{exemplar_text}
EXAMPLE

NOW WRITE THE STORYBOARD FOR WEEK {row['wk']} ({row['level']}).
Theme: {row['theme']}
Grammar focus (this week's new structure; earlier weeks recur): {row['grammar']}
Narrative beat to decompose: {row['beat']}
{revise}
Rules:
- CEFR {row['level']}: weeks 1-15 are PRESENT TENSE ONLY (no past tense).
- Decompose the beat into a natural sequence of scenes — let the material decide the count
  (typically ~6-9). Make each scene a full ~15-20 line-pair situation, so the week runs ~15-20 min of audio. Prefer FEWER, RICHER scenes (each a complete
  activity that moves) over many thin object-by-object beats. Vary the scene shapes and span several
  DISTINCT situations so no single kind of beat repeats until it grates.
- Every scene's beat must carry the week's grammar THROUGH ACTION, never a static "X is at Y" list.
  Make sure any (grammar cue) in parentheses is itself correct, natural Danish.
- Honor the story bible exactly: continuity, cast, and what is already true. Never re-introduce as
  new something already established; never contradict it (e.g. an "empty" flat then full of
  furniture). End the week warm (never on loneliness or a low note).
- Give each scene a short snake_case stem with no number, e.g. "the_keys", "first_dinner".

Return JSON exactly:
{{"title": "<short title, e.g. 'Maya moves into her own flat'>",
 "grammar": "<the Grammar header line; may name the recurring earlier-week grammar>",
 "target": "~NN min",
 "rationale": "<one paragraph: how the beat becomes this sequence, plus the continuity notes>",
 "scenes": [{{"stem": "<snake_case>", "beat": "<scene beat, with (grammar cues) in parentheses>"}}]}}
"""


def to_markdown(row: dict, data: dict) -> str:
    out = [f"# Week {row['wk']} — Storyboard ({data.get('title', '').strip()})", ""]
    out.append(f"**Level:** {row['level']} · **Grammar:** "
               f"{data.get('grammar', row['grammar']).strip()} · "
               f"**Target:** {data.get('target', '').strip()}")
    out.append("")
    out.append(data.get("rationale", "").strip())
    out.append("")
    out.append("| # | stem | beat |")
    out.append("|---|------|------|")
    for i, s in enumerate(data["scenes"], 1):
        stem = f"{i:02d}_{s['stem'].strip().strip('_')}"
        out.append(f"| {i} | {stem} | {' '.join(s['beat'].split())} |")
    return "\n".join(out) + "\n"


def run_gate(storyboard_path: Path, findings_path: Path, model: str, location: str) -> int:
    """Run review_storyboard.py as the gate; stream its output; return its exit code."""
    proc = subprocess.run(
        [sys.executable, "review_storyboard.py", str(storyboard_path),
         "--model", model, "--location", location, "--out", str(findings_path)],
        check=False)
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("week", type=int)
    ap.add_argument("--example-week", type=int, default=None,
                    help="storyboard to use as the format exemplar (default: previous week)")
    ap.add_argument("--cycle", action="store_true",
                    help="run the full generate->gate->revise loop (default: single-shot generate)")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--workdir", default=str(Path(tempfile.gettempdir()) / "tandem_storyboards"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--location", default="global")
    a = ap.parse_args()
    os.environ["GOOGLE_CLOUD_LOCATION"] = a.location

    ex_wk = a.example_week or (a.week - 1)
    ex_path = Path(f"year1/week{ex_wk:02d}/storyboard.md")
    if not ex_path.exists():
        raise SystemExit(f"no exemplar storyboard at {ex_path} (pass --example-week)")
    exemplar = ex_path.read_text(encoding="utf-8")
    row = curriculum_row(a.week)
    client = make_client()

    if not a.cycle:
        data = _json_call(client, a.model, build_prompt(row, exemplar, ex_wk))
        sys.stdout.write(to_markdown(row, data))
        return 0

    work = Path(a.workdir)
    work.mkdir(parents=True, exist_ok=True)
    sb_path = work / f"wk{a.week:02d}_storyboard.md"
    fp_path = work / f"wk{a.week:02d}_findings.json"

    prior_md: str | None = None
    findings: list[dict] | None = None
    for rnd in range(1, a.max_rounds + 1):
        tag = "GENERATE" if rnd == 1 else f"REVISE (round {rnd})"
        print(f"\n{'=' * 70}\n[{tag}] week {a.week}\n{'=' * 70}", flush=True)
        data = _json_call(client, a.model, build_prompt(row, exemplar, ex_wk, prior_md, findings))
        md = to_markdown(row, data)
        sb_path.write_text(md, encoding="utf-8")
        print(f"  → {len(data['scenes'])} scenes  ({sb_path})", flush=True)

        rc = run_gate(sb_path, fp_path, a.model, a.location)
        if rc == 0:
            print(f"\n✓ GATE CLEARED on round {rnd}. Final storyboard at {sb_path}\n")
            sys.stdout.write(md)
            return 0
        if rc == 2:
            print(f"\n⚠ Gate INCOMPLETE (a lens errored) on round {rnd} — escalating to a human.\n")
            return 2
        findings = json.loads(fp_path.read_text(encoding="utf-8"))
        prior_md = md

    print(f"\n✗ ESCALATE: still blocking after {a.max_rounds} rounds. "
          f"Best draft + remaining findings at {sb_path} / {fp_path}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
