"""Generate + verify a full week from a storyboard, retrying failures.

The week's spec (level / grammar / lines-per-scene) is read from the storyboard's own header — the
storyboard is the single source of truth, so there are no spec constants to keep in sync here. Pass
a storyboard path to drive any week.

Run:  set -a; . ./.env; set +a;  .venv/bin/python gen_week.py [year1/weekNN/storyboard.md] [--scenes 1-3] [--workers 4]
Writes <stem>.da/.en into the storyboard's dir + verify_summary.json. Audio is a separate step.
--scenes regenerates only a subset (e.g. '1-3', '1,4,7'); other scenes are left untouched.
Scenes are independent (no vocab carried between them), so --workers runs them concurrently.
"""
from __future__ import annotations
import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tandem.gen import (make_client, generate_scene, revise_scene, verify_scene, format_failures,
                        parse_storyboard, parse_storyboard_header, VERIFY_DIMENSIONS, ADVISORY_DIMS)


def _parse_scene_sel(s: str | None) -> set[int] | None:
    """Parse a scene selection ('1-3', '1,4,7', '2-3,9') into a set of scene numbers (None = all)."""
    if not s:
        return None
    nums: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            nums.update(range(int(a), int(b) + 1))
        else:
            nums.add(int(part))
    return nums


_ap = argparse.ArgumentParser(description="Generate + verify a week (or a subset of scenes) from a storyboard.")
_ap.add_argument("storyboard", nargs="?", default="year1/week01/storyboard.md",
                 help="storyboard .md (single source for the week's spec + arc)")
_ap.add_argument("--scenes", help="subset to (re)generate, e.g. '1-3', '1,4,7', '2-3,9' "
                                   "(default: all); other scenes are left untouched")
_ap.add_argument("--workers", type=int, default=4,
                 help="concurrent scenes (default 4). Scenes are independent, so they run in "
                      "parallel — raise for speed, lower to stay under API rate limits")
_ap.add_argument("--location", default="global",
                 help="Vertex location (default 'global' — required for gemini-3.1-pro, used for both "
                      "generation and the verify judge)")
_args = _ap.parse_args()
os.environ["GOOGLE_CLOUD_LOCATION"] = _args.location   # gen + verify (both gemini-3.1-pro) run in global
STORYBOARD = _args.storyboard
SCENES = _parse_scene_sel(_args.scenes)
WORKERS = max(1, _args.workers)
_SPEC = parse_storyboard_header(STORYBOARD)            # single source: the storyboard header
WEEK = _SPEC["week"]
LEVEL = _SPEC["level"]
GRAMMAR = _SPEC["grammar"]

GEN_MODEL = "gemini-3.1-pro-preview"      # gen + revise on the strongest model — best first drafts, fewest
                                          # hand-fixes (user choice 2026-06-27). Needs location='global'.
VERIFY_MODEL = "gemini-3.1-pro-preview"   # same model as the generator now, so per-scene verify is a
                                          # SELF-CHECK, not an independent audit. The real independent
                                          # checks are the human read-through + the whole-week gate
                                          # (review_week.py) — lean on those, since a model is weakest at
                                          # catching its own mistakes (it passed wk3's out-of-scope 'var').
MAX_RETRIES = 2                      # up to two revise retries on hard-fail, then accept best + log
# Hard gates (block + retry) = alignment (structural, checked separately) + every non-advisory dim:
# coherence (the scene's lines hang together), naturalness (idiomatic Danish), gloss_fidelity
# (the EN pivot ~100 languages translate from). grammar_whitelist is advisory. Derived
# from the single source in gen.py so the split can't drift.
HARD_DIMS = tuple(d for d in VERIFY_DIMENSIONS if d not in ADVISORY_DIMS)


def _dim(llm: dict, d: str) -> dict:
    """A verify dim's report dict, guarding a malformed non-dict value (e.g. the model returned a list)."""
    v = llm.get(d)
    return v if isinstance(v, dict) else {}


def hard_pass(rep: dict) -> bool:
    llm = rep.get("llm", {})
    structural = bool(rep.get("aligned")) and bool(rep.get("one_per_line", True))
    return structural and all(_dim(llm, d).get("pass") for d in HARD_DIMS)


def process_scene(client, arc: list, outdir: Path, row: dict) -> dict:
    """Generate + verify one scene (with retry), write its .da/.en, return its summary row.

    Self-contained: scenes share no state (no vocab carried between them), so this is safe to call
    concurrently across scenes.
    """
    n, stem, total = row["num"], row["stem"], len(arc)
    best = best_rep = None
    attempts = 0
    for attempt in range(MAX_RETRIES + 1):
        attempts = attempt + 1
        try:
            if attempt == 0 or best is None:          # fresh draft (or the prior attempt errored)
                res = generate_scene(client, model=GEN_MODEL, week=WEEK, level=LEVEL,
                                     scene_title=row["title"], scene=row["scene"], grammar=GRAMMAR,
                                     arc=arc, scene_num=n)
            else:                                     # revise the rejected draft — fix only what failed
                res = revise_scene(client, model=GEN_MODEL, level=LEVEL, grammar=GRAMMAR,
                                   scene=row["scene"], da_lines=best["da"], en_lines=best["en"],
                                   feedback=format_failures(best_rep))
            rep = verify_scene(client, model=VERIFY_MODEL, level=LEVEL, grammar=GRAMMAR,
                              da_lines=res["da"], en_lines=res["en"])
        except (Exception, SystemExit) as e:  # noqa: BLE001 — don't let one scene kill the week
            print(f"[{n:2}/{total}] {stem}: attempt {attempts} ERROR {type(e).__name__}: "
                  f"{str(e)[:120]}", flush=True)
            continue
        best, best_rep = res, rep
        if hard_pass(rep):
            break

    if best is None:
        print(f"[{n:2}/{total}] {stem}: ALL ATTEMPTS FAILED — skipping", flush=True)
        return {"n": n, "stem": stem, "attempts": attempts, "status": "failed"}

    (outdir / f"{stem}.da").write_text("\n".join(best["da"]) + "\n", encoding="utf-8")
    (outdir / f"{stem}.en").write_text("\n".join(best["en"]) + "\n", encoding="utf-8")

    llm = best_rep.get("llm", {})
    g = _dim(llm, "grammar_whitelist").get("pass")
    coh = _dim(llm, "coherence").get("pass")
    nat = _dim(llm, "naturalness").get("pass")
    gl = _dim(llm, "gloss_fidelity").get("pass")
    print(f"[{n:2}/{total}] {stem:24} attempts={attempts} hard={'OK ' if hard_pass(best_rep) else 'FAIL'} "
          f"G={g} cohere={coh} natural={nat} gloss={gl}", flush=True)
    return {"n": n, "stem": stem, "attempts": attempts, "hard_pass": hard_pass(best_rep),
            "grammar": g, "coherence": coh, "natural": nat, "gloss": gl,
            "lines": len(best["da"]),
            "issues": {d: _dim(llm, d).get("issues", []) for d in VERIFY_DIMENSIONS}}


def main() -> int:
    client = make_client()
    arc = parse_storyboard(STORYBOARD)
    outdir = Path(STORYBOARD).parent
    todo = [row for row in arc if SCENES is None or row["num"] in SCENES]

    workers = min(WORKERS, len(todo)) or 1
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            summary = list(ex.map(lambda r: process_scene(client, arc, outdir, r), todo))
    else:
        summary = [process_scene(client, arc, outdir, r) for r in todo]
    summary.sort(key=lambda s: s["n"])

    (outdir / "verify_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                encoding="utf-8")
    sel = f" (scenes {sorted(SCENES)})" if SCENES is not None else ""
    print(f"\n=== WEEK {WEEK} SUMMARY{sel} ===")
    for s in summary:
        if s.get("status") == "failed":
            print(f"  {s['n']:2} {s['stem']:24} FAILED ({s['attempts']} attempts)")
            continue
        print(f"  {s['n']:2} {s['stem']:24} att={s['attempts']} "
              f"hard={'OK ' if s['hard_pass'] else 'FAIL'} | "
              f"cohere={s['coherence']} natural={s['natural']} gloss={s['gloss']}  "
              f"[adv G={s['grammar']}]")

    # Deterministic repetition lint over the WHOLE week (cheap, no API) — surfaces mechanical repeats
    # (smile-as-every-closer, an emotion tag in half the scenes, a sentence reused across scenes)
    # right after generation, before the LLM week-gate. Advisory: prints flags, never blocks the run.
    try:
        from lint_week import lint as _lint_week
        if _lint_week(outdir) == 1:
            print("  ↳ repetition lint flagged HIGHs above — worth a pass before review_week.")
    except Exception as exc:
        print(f"[warn] repetition lint skipped: {exc}")

    # Week-level vocabulary readout (deterministic) — surfaces the rarest words so a jargon spike
    # from an over-technical event is visible. Advisory; scan the rarest list for technical jargon.
    try:
        from vocab_load import report as _vocab_load
        _vocab_load(outdir)
    except Exception as exc:
        print(f"[warn] vocab readout skipped: {exc}")

    # Sentence-complexity readout (deterministic, on the .en GLOSS) — surfaces compound sentences
    # (two clauses joined by and/but/so/or) that sit above the one-clause-per-line norm of the early
    # levels. Language-agnostic via the gloss. Advisory; split the flagged lines if a week reads complex.
    try:
        from complexity import report as _complexity
        _complexity(outdir)
    except Exception as exc:
        print(f"[warn] complexity readout skipped: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
