"""Generate + verify a full week from a storyboard, feeding vocab forward and retrying failures.

The week's spec (level / grammar / new-word budget / lines-per-scene) is read from the storyboard's
own header — the storyboard is the single source of truth, so there are no spec constants to keep in
sync here. Pass a storyboard path to drive any week.

Run:  set -a; . ./.env; set +a;  .venv/bin/python gen_week.py [year1/weekNN/storyboard.md]
Writes <stem>.da/.en into the storyboard's dir + verify_summary.json. Audio is a separate step.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from tandem.gen import (make_client, generate_scene, verify_scene, parse_storyboard,
                        parse_storyboard_header, _distinct_words,
                        VERIFY_DIMENSIONS, ADVISORY_DIMS)

STORYBOARD = sys.argv[1] if len(sys.argv) > 1 else "year1/week01/storyboard.md"
_SPEC = parse_storyboard_header(STORYBOARD)            # single source: the storyboard header
WEEK = _SPEC["week"]
LEVEL = _SPEC["level"]
GRAMMAR = _SPEC["grammar"]
NEW_WORDS = _SPEC["new_words"]
LINES = _SPEC["lines"]

GEN_MODEL = "gemini-2.5-pro"
VERIFY_MODEL = "gemini-2.5-pro"     # max capability on the QA gate — false negatives (missing a real
                                    # defect) are the costly error; matters most for low-resource L2s
MAX_RETRIES = 1                      # one retry on hard-fail, then accept best + log (no thrash)
# Hard gates (block + retry) = alignment (structural, checked separately) + every non-advisory dim:
# content_neutral (cross-language reuse invariant), naturalness (idiomatic Danish), gloss_fidelity
# (the EN pivot ~100 languages translate from). grammar_whitelist/cefr_level are advisory. Derived
# from the single source in gen.py so the split can't drift.
HARD_DIMS = tuple(d for d in VERIFY_DIMENSIONS if d not in ADVISORY_DIMS)


def hard_pass(rep: dict) -> bool:
    llm = rep.get("llm", {})
    structural = bool(rep.get("aligned")) and bool(rep.get("one_per_line", True))
    return structural and all((llm.get(d) or {}).get("pass") for d in HARD_DIMS)


def main() -> int:
    client = make_client()
    arc = parse_storyboard(STORYBOARD)
    outdir = Path(STORYBOARD).parent
    prior: set[str] = set()
    summary = []

    for row in arc:
        n, stem = row["num"], row["stem"]
        prior_str = ", ".join(sorted(prior))
        best = best_rep = None
        attempts = 0
        for attempt in range(MAX_RETRIES + 1):
            attempts = attempt + 1
            try:
                res = generate_scene(client, model=GEN_MODEL, week=WEEK, level=LEVEL,
                                     scene_title=row["title"], beat=row["beat"], grammar=GRAMMAR,
                                     new_words=NEW_WORDS, lines=LINES, prior_vocab=prior_str,
                                     arc=arc, scene_num=n)
                rep = verify_scene(client, model=VERIFY_MODEL, level=LEVEL, grammar=GRAMMAR,
                                  da_lines=res["da"], en_lines=res["en"],
                                  cumulative_vocab=prior_str)
            except (Exception, SystemExit) as e:  # noqa: BLE001 — don't let one scene kill the week
                print(f"[{n:2}/{len(arc)}] {stem}: attempt {attempts} ERROR {type(e).__name__}: "
                      f"{str(e)[:120]}", flush=True)
                continue
            best, best_rep = res, rep
            if hard_pass(rep):
                break

        if best is None:
            print(f"[{n:2}/{len(arc)}] {stem}: ALL ATTEMPTS FAILED — skipping", flush=True)
            summary.append({"n": n, "stem": stem, "attempts": attempts, "status": "failed"})
            continue

        (outdir / f"{stem}.da").write_text("\n".join(best["da"]) + "\n", encoding="utf-8")
        (outdir / f"{stem}.en").write_text("\n".join(best["en"]) + "\n", encoding="utf-8")
        prior |= _distinct_words(best["da"])

        llm = best_rep.get("llm", {})
        g = (llm.get("grammar_whitelist") or {}).get("pass")
        c = (llm.get("cefr_level") or {}).get("pass")
        ct = (llm.get("content_neutral") or {}).get("pass")
        nat = (llm.get("naturalness") or {}).get("pass")
        gl = (llm.get("gloss_fidelity") or {}).get("pass")
        row_sum = {"n": n, "stem": stem, "attempts": attempts, "hard_pass": hard_pass(best_rep),
                   "grammar": g, "cefr": c, "content": ct, "natural": nat, "gloss": gl,
                   "lines": len(best["da"]),
                   "issues": {d: (llm.get(d) or {}).get("issues", []) for d in VERIFY_DIMENSIONS}}
        summary.append(row_sum)
        print(f"[{n:2}/{len(arc)}] {stem:24} attempts={attempts} hard={'OK ' if hard_pass(best_rep) else 'FAIL'} "
              f"G={g} CEFR={c} content={ct} natural={nat} gloss={gl}", flush=True)

    (outdir / "verify_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                encoding="utf-8")
    print(f"\n=== WEEK {WEEK} SUMMARY ===")
    for s in summary:
        if s.get("status") == "failed":
            print(f"  {s['n']:2} {s['stem']:24} FAILED ({s['attempts']} attempts)")
            continue
        print(f"  {s['n']:2} {s['stem']:24} att={s['attempts']} "
              f"hard={'OK ' if s['hard_pass'] else 'FAIL'} | "
              f"content={s['content']} natural={s['natural']} gloss={s['gloss']}  "
              f"[adv G={s['grammar']} CEFR={s['cefr']}]")
    print(f"\nDistinct Danish words across the week: {len(prior)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
