#!/usr/bin/env python3
"""PROTOTYPE: autonomously author a week's storyboard, then self-correct against the design gate.

The loop:  generate  ->  review_storyboard.py (gate)  ->  if blocking Highs, revise with the
findings fed back  ->  re-gate  ->  ... up to --max-rounds, then escalate (print best + remaining).

Inputs (deliberately NOT design_notes.md — too long):
  - the target week's row in curriculum_da.md (theme / grammar / brief)
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

from tandem.gen import load_story_bible, DEFAULT_MODEL
from tandem.llm import make_client, _json_call

CURRICULUM = "curriculum_da.md"


def curriculum_row(week: int) -> dict:
    for line in Path(CURRICULUM).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 5 and cells[0].isdigit() and int(cells[0]) == week:
            return {"wk": week, "level": cells[1], "theme": cells[2],
                    "grammar": cells[3], "brief": cells[4]}
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

A strict review panel returned these problems. Modify the storyboard to address the issues:
{items}
"""


def build_prompt(row: dict, exemplar_text: str, exemplar_wk: int,
                 prior_md: str | None = None, findings: list[dict] | None = None) -> str:
    bible = load_story_bible()
    revise = _revise_block(prior_md, findings) if (prior_md and findings) else ""
    if exemplar_text:
        fmt_block = (
            f"FORMAT + STYLE EXAMPLE — here is the finished storyboard for week {exemplar_wk}. Match its shape and\n"
            "craft: a numbered scene list where each scene names a concrete action.\n"
            f"<<<EXAMPLE\n{exemplar_text}\nEXAMPLE"
        )
    else:
        fmt_block = (
            "FORMAT — write a numbered scene list where each scene names a concrete action."
        )
    return f"""{bible}

You are authoring the STORYBOARD for one week of a Danish (A1->B2) audio course told as Maya's
first-person story. A storyboard decomposes the week's brief into an ordered
sequence of scenes; each scene is later written as line-aligned Danish/English.

{fmt_block}

NOW WRITE THE STORYBOARD FOR WEEK {row['wk']} ({row['level']}).
Theme: {row['theme']}
Grammar focus (this week's new structure; earlier weeks recur): {row['grammar']}
Week brief to decompose: {row['brief']}
{revise}
Rules:
- CEFR {row['level']}: weeks 1-15 are PRESENT TENSE ONLY (no past tense).
- Decompose the brief into a natural sequence of scenes — let the material decide the count. Prefer
  8-10 RICHER scenes (each a complete
  activity that moves) over many thin object-by-object scenes. Vary the scene shapes and span several
  DISTINCT situations so no single kind of scene repeats until it grates.
- Every scene must carry the week's grammar through action, not a static inventory.
- Where the brief rules something OUT, say so inside the scene it would otherwise turn up in — that
  scene's text is all the writer of the scene ever sees. Include no other prompt text.
- Honor the story bible exactly — never contradict it or re-introduce as new something already established.
- Give each scene a short snake_case stem with no number, e.g. "the_keys", "first_dinner".

Return JSON exactly:
{{"title": "<short title, e.g. 'Maya moves into her own flat'>",
 "scenes": [{{"stem": "<snake_case>", "scene": "<the scene>"}}]}}
"""


def to_markdown(row: dict, data: dict) -> str:
    out = [f"# Week {row['wk']} — Storyboard ({data.get('title', '').strip()})", ""]
    out.append(f"**Level:** {row['level']} · **Grammar:** {row['grammar'].strip()}")
    out.append("")
    out.append("| # | stem | scene |")
    out.append("|---|------|------|")
    for i, s in enumerate(data["scenes"], 1):
        stem = f"{i:02d}_{s['stem'].strip().strip('_')}"
        out.append(f"| {i} | {stem} | {' '.join(s['scene'].split())} |")
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
    ap.add_argument("--no-example", action="store_true",
                    help="generate with NO format exemplar (week 1 has no predecessor; hand-edit after)")
    ap.add_argument("--cycle", action="store_true",
                    help="run the full generate->gate->revise loop (default: single-shot generate)")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--workdir", default=str(Path(tempfile.gettempdir()) / "tandem_storyboards"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--location", default="global")
    ap.add_argument("--show-prompt", action="store_true",
                    help="print the generation prompt and exit (no API call)")
    a = ap.parse_args()
    os.environ["GOOGLE_CLOUD_LOCATION"] = a.location

    if a.no_example or (a.example_week is None and a.week <= 1):
        exemplar, ex_wk = None, None       # week 1 has no predecessor — generate without an exemplar
    else:
        ex_wk = a.example_week or (a.week - 1)
        ex_path = Path(f"year1/week{ex_wk:02d}/storyboard.md")
        if not ex_path.exists():
            raise SystemExit(f"no exemplar storyboard at {ex_path} (pass --example-week or --no-example)")
        exemplar = ex_path.read_text(encoding="utf-8")
    row = curriculum_row(a.week)
    if a.show_prompt:
        print(build_prompt(row, exemplar, ex_wk))
        return 0
    client = make_client()

    if not a.cycle:
        data = _json_call(client, a.model, build_prompt(row, exemplar, ex_wk), stage="storyboard")
        sys.stdout.write(to_markdown(row, data))
        return 0

    work = Path(a.workdir)
    work.mkdir(parents=True, exist_ok=True)
    sb_path = work / f"wk{a.week:02d}_storyboard.md"

    prior_md: str | None = None
    findings: list[dict] | None = None
    best: tuple[tuple[int, int], int, str, Path] | None = None   # (score, round, md, findings path)
    for rnd in range(1, a.max_rounds + 1):
        tag = "GENERATE" if rnd == 1 else f"REVISE (round {rnd})"
        print(f"\n{'=' * 70}\n[{tag}] week {a.week}\n{'=' * 70}", flush=True)
        data = _json_call(client, a.model, build_prompt(row, exemplar, ex_wk, prior_md, findings),
                          stage=f"storyboard.r{rnd}")
        md = to_markdown(row, data)
        sb_path.write_text(md, encoding="utf-8")
        round_path = work / f"wk{a.week:02d}_storyboard_r{rnd}.md"   # per-round copy, preserved for inspection
        round_path.write_text(md, encoding="utf-8")
        print(f"  → {len(data['scenes'])} scenes  ({round_path})", flush=True)

        fp_round = work / f"wk{a.week:02d}_findings_r{rnd}.json"   # per-round findings, preserved
        rc = run_gate(sb_path, fp_round, a.model, a.location)
        if rc == 2:
            print(f"\n⚠ Gate INCOMPLETE (a lens errored) on round {rnd} — escalating to a human.\n")
            return 2
        findings = json.loads(fp_round.read_text(encoding="utf-8"))
        # Revise while anything ACTIONABLE remains — blocking Highs (rc != 0) OR non-advisory Meds.
        # The gate only *blocks* on High, but _revise_block already rewrites for Meds too, so acting
        # on them here (not only when a High forces a round) is the whole point of the loop. `advisory`
        # stays the single "leave it to the human/ear" knob.
        med_actionable = [f for f in findings
                          if f.get("severity") == "Med" and not f.get("advisory")]
        # A revise can REGRESS a good draft (wk6: r1 had 0 blocking Highs, r3 had 5 — the revise rounds
        # invented them). So score every round and keep the BEST, not the last one.
        highs = [f for f in findings if f.get("severity") == "High" and not f.get("advisory")]
        score = (len(highs), len(med_actionable))
        if best is None or score < best[0]:
            best = (score, rnd, md, fp_round)

        if rc == 0 and not med_actionable:
            print(f"\n✓ GATE CLEARED on round {rnd}. Final storyboard at {sb_path}\n")
            sys.stdout.write(md)
            return 0
        kind = "blocking High" if rc != 0 else f"{len(med_actionable)} non-advisory Med"
        print(f"  → revising ({kind} finding(s))", flush=True)
        prior_md = md

    # Rounds exhausted. Ship the BEST round (fewest blocking Highs, then fewest actionable Meds).
    (n_high, n_med), rnd, md, fp_round = best
    sb_path.write_text(md, encoding="utf-8")
    print(f"\n→ best round was r{rnd} ({n_high} blocking High, {n_med} actionable Med)", flush=True)
    if n_high:
        print(f"\n✗ ESCALATE: still blocking after {a.max_rounds} rounds. "
              f"Best draft (r{rnd}) + its findings at {sb_path} / {fp_round}\n")
        return 1
    print(f"\n⚠ Cleared of blocking Highs; {n_med} non-advisory Med finding(s) persisted after "
          f"{a.max_rounds} rounds — accepting r{rnd}. Review the residue at {fp_round}.\n")
    sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
