"""Generate + verify a full week from a storyboard, feeding vocab forward and retrying failures.

Run:  set -a; . ./.env; set +a;  .venv/bin/python gen_week.py
Writes <stem>.da/.en into the storyboard's dir + verify_summary.json. Audio is a separate step.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from tandem.gen import (make_client, generate_scene, verify_scene, parse_storyboard,
                        _distinct_words)

WEEK = 1
LEVEL = "A1"
NEW_WORDS = 40
LINES = 12
GRAMMAR = ("present tense of være / hedde / komme fra; subject pronouns; hvad/hvor questions; "
           "V2 word order; greetings (hej, goddag, tak, velkommen, farvel)")
GEN_MODEL = "gemini-2.5-pro"
VERIFY_MODEL = "gemini-2.5-flash"   # faster + a degree of independence from the generator
STORYBOARD = "year1/week01/storyboard.md"
MAX_RETRIES = 2                      # so up to 3 attempts per scene
HARD_DIMS = ("grammar_whitelist", "cefr_level", "content_neutral")  # naturalness is advisory


def hard_pass(rep: dict) -> bool:
    llm = rep.get("llm", {})
    return bool(rep.get("aligned")) and all((llm.get(d) or {}).get("pass") for d in HARD_DIMS)


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
                                  new_words=NEW_WORDS, da_lines=res["da"], en_lines=res["en"],
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
        row_sum = {"n": n, "stem": stem, "attempts": attempts, "hard_pass": hard_pass(best_rep),
                   "grammar": g, "cefr": c, "content": ct, "natural": nat,
                   "lines": len(best["da"]), "issues": {d: (llm.get(d) or {}).get("issues", [])
                                                          for d in ("grammar_whitelist", "cefr_level",
                                                                    "content_neutral", "naturalness")}}
        summary.append(row_sum)
        print(f"[{n:2}/{len(arc)}] {stem:24} attempts={attempts} hard={'OK ' if hard_pass(best_rep) else 'FAIL'} "
              f"G={g} CEFR={c} content={ct} natural={nat}", flush=True)

    (outdir / "verify_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                encoding="utf-8")
    print("\n=== WEEK 1 SUMMARY ===")
    for s in summary:
        if s.get("status") == "failed":
            print(f"  {s['n']:2} {s['stem']:24} FAILED ({s['attempts']} attempts)")
            continue
        print(f"  {s['n']:2} {s['stem']:24} att={s['attempts']} "
              f"hard={'OK ' if s['hard_pass'] else 'FAIL'} | G={s['grammar']} CEFR={s['cefr']} "
              f"content={s['content']} natural={s['natural']}")
    print(f"\nDistinct Danish words across the week: {len(prior)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
