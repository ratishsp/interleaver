#!/usr/bin/env python3
"""Autonomous week builder — chains the stages all the way to audio with NO human stop in between.

Philosophy: the human's only touchpoint is listening to the finished audio and giving feedback.
The automated gates are ASSISTIVE, not blocking: each runs and auto-fixes what it can (the storyboard
revise loop, gen_week's per-scene retries), but anything it can't clear does NOT halt the run — it is
recorded as a REVIEW NOTE and the pipeline pushes on to audio. The human then listens, with the notes
in hand, and decides.

Stages:
  1. storyboard  — gen_storyboard.py --cycle  (generate -> design gate -> revise loop)
  2. scenes      — gen_week.py                 (gen -> verify -> revise per scene)
  3. week gate   — review_week.py              (whole-week text panel; advisory here)
  4. audio       — build_week_audio.py

Run:  set -a; . ./.env; set +a;  .venv/bin/python build_week.py 6
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PY = sys.executable


def run(cmd: list) -> int:
    cmd = [str(c) for c in cmd]
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, check=False).returncode


def stage(title: str) -> None:
    print(f"\n{'#' * 72}\n# {title}\n{'#' * 72}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("week", type=int)
    ap.add_argument("--max-rounds", type=int, default=4, help="storyboard revise rounds")
    ap.add_argument("--model", default=None, help="override the gate/generator model")
    ap.add_argument("--location", default="global")
    ap.add_argument("--with-slow", action="store_true", help="also build the slow-Danish audio pass")
    ap.add_argument("--skip-audio", action="store_true")
    a = ap.parse_args()

    wk = a.week
    weekdir = Path(f"year1/week{wk:02d}")
    sb = weekdir / "storyboard.md"
    model = ["--model", a.model] if a.model else []
    notes: list[str] = []   # residual flags for the human listener; never halts the run

    if sb.exists():
        print(f"✗ {sb} already exists — refusing to clobber a built week. Remove it to rebuild.")
        return 2

    # 1 — storyboard: generate -> design gate -> revise. Keep the best draft even if it can't clear.
    stage(f"STAGE 1/4 · storyboard (week {wk})")
    workdir = Path(tempfile.mkdtemp(prefix=f"buildwk{wk:02d}_"))
    rc = run([PY, "gen_storyboard.py", wk, "--cycle", "--max-rounds", a.max_rounds,
              "--location", a.location, "--workdir", workdir] + model)
    draft = workdir / f"wk{wk:02d}_storyboard.md"
    if not draft.exists():
        print("✗ storyboard generation produced no draft at all — the run crashed; nothing to build.")
        return 2
    weekdir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(draft, sb)
    if rc == 1:
        notes.append(f"Storyboard did NOT fully clear the design gate after {a.max_rounds} rounds — "
                     f"best draft was used. Residual findings: {workdir}/wk{wk:02d}_findings.json")
    elif rc == 2:
        notes.append("Storyboard design gate was INCOMPLETE (a lens errored) — verdict unknown.")
    print(f"✓ storyboard in place → {sb}")

    # 2 — scenes: gen_week self-revises hard-fails; note any that still stuck, but keep going.
    stage("STAGE 2/4 · scenes (gen -> verify -> revise)")
    run([PY, "gen_week.py", sb, "--workers", 4, "--location", a.location])
    summary = json.loads((weekdir / "verify_summary.json").read_text(encoding="utf-8"))
    bad = [s for s in summary if s.get("status") == "failed" or not s.get("hard_pass")]
    if bad:
        notes.append(f"{len(bad)}/{len(summary)} scene(s) did not hard-pass after retry "
                     f"(best draft kept): {', '.join(s['stem'] for s in bad)} — listen closely.")
    print(f"✓ scenes generated ({len(summary) - len(bad)}/{len(summary)} hard-passed)")

    # 3 — whole-week text gate: advisory here. Record blockers, do not stop.
    stage("STAGE 3/4 · week review gate (advisory)")
    rc = run([PY, "review_week.py", sb, "--location", a.location] + model)
    if rc == 1:
        notes.append("Whole-week gate flagged blocking issues (see Stage 3 output above).")
    elif rc == 2:
        notes.append("Whole-week gate was INCOMPLETE (a lens errored).")

    # 4 — audio: always built, so there is something to listen to.
    if a.skip_audio:
        print("\n(skipping audio per --skip-audio)")
    else:
        stage("STAGE 4/4 · audio")
        run([PY, "build_week_audio.py", weekdir] + ([] if a.with_slow else ["--natural-only"]))

    stage(f"WEEK {wk} BUILT — your turn: listen to {weekdir}/audio/ and give feedback")
    if notes:
        print(f"\n⚠ {len(notes)} REVIEW NOTE(S) — the gates couldn't fully clear these; "
              f"listen for them, they did NOT stop the build:")
        for i, n in enumerate(notes, 1):
            print(f"  {i}. {n}")
    else:
        print("\n✓ Clean through every gate — no residual flags. Just give it a listen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
