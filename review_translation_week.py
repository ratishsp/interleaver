#!/usr/bin/env python3
"""Whole-week review of a TRANSLATED track (.ml/.ta) — the tier the translation track was missing.

The Danish has three tiers: verify_scene (one scene) → review_week (cross-scene) → continuity_check
(cross-week). The translations had only the first, so nothing could see what only shows up BETWEEN
scenes: a name transliterated two ways, a recurring object renamed, a character addressed familiarly in
one scene and formally in the next. continuity_check never helps here — it reads the English gloss and
has never looked at a line of Malayalam or Tamil.

Reuses the Danish week-gate wholesale — its panel runner, its self-consistency vote, its severity ranks —
and swaps only what a lens is shown (the week as EN | DA | TARGET columns) and what a fix is made with
(revise_translation, which locks the line count).

  review_translation_week.py year1/week05/storyboard.md --lang ml
  review_translation_week.py year1/week05/storyboard.md --lang ml --fix --votes 3 --min-votes 2

Run:  set -a; . ./.env; set +a;  .venv/bin/python review_translation_week.py year1/week05/storyboard.md --lang ml
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from tandem.gen import DEFAULT_MODEL, parse_storyboard, parse_storyboard_header
from tandem.llm import make_client
from tandem.translate import revise_translation
from review_week import collect_votes, run_panel, _SEV_RANK

LANG_NAME = {"ml": "Malayalam", "ta": "Tamil", "da": "Danish", "en": "English"}

COMMON = """You are reviewing a whole WEEK of a graded audio course, translated into {tgt_name}.

Each line is shown as three aligned columns: the ENGLISH source (which sets the meaning), the DANISH
(which marks distinctions English drops — gender, number, who is being addressed), and the {tgt_name}
UNDER TEST. The lines are 1:1 across all three.

Every scene was already checked ON ITS OWN. You are here for what a single scene CANNOT show: the week
read straight through, as a listener hears it.

WEEK {week} — {n} scenes:
{week_text}
"""

_CONTRACT = """
Report each problem as JSON:
{"findings": [{"scene": "<scene number>", "issue": "<short title>", "severity": "High|Med|Low",
               "why": "<one sentence, quoting the conflicting lines>"}]}
High = wrong and must be fixed. Med = should be. Low = taste. Report nothing you cannot point at.
An empty list is the right answer for a clean week.
"""

LENSES = [
    {"key": "consistency", "title": "Consistency across the week",
     "body": "Anything that recurs across scenes must be rendered the SAME way each time it recurs. "
             "Read the week as a whole and flag a recurrence the translation does not hold steady."},
    {"key": "register", "title": "Address & register",
     "body": "{tgt_name} marks how people address each other in ways English does not. Judge whether "
             "each choice fits the relationship the story establishes, and whether it stays consistent "
             "as that relationship recurs across the week."},
    {"key": "listener", "title": "Native listener (no checklist)",
     "body": "You are a native {tgt_name} speaker hearing this week straight through, with no checklist. "
             "Say what is wrong, or awkward, or would not be said. Trust your ear."},
]


def assemble_week(storyboard_path: str | Path, tgt: str) -> tuple[str, int]:
    """Every scene's EN | DA | TARGET, in storyboard order. Skips scenes not yet translated."""
    rows = parse_storyboard(storyboard_path)
    wdir = Path(storyboard_path).parent
    parts, n = [], 0
    for r in rows:
        f = {ext: wdir / f"{r['stem']}.{ext}" for ext in ("en", "da", tgt)}
        if not all(p.exists() for p in f.values()):
            continue
        cols = {ext: p.read_text(encoding="utf-8").splitlines() for ext, p in f.items()}
        body = "\n".join(f"  {e}  |  {d}  |  {t}"
                         for e, d, t in zip(cols["en"], cols["da"], cols[tgt]))
        parts.append(f"## Scene {r['num']} — {r['stem']}\n{body}")
        n += 1
    return "\n\n".join(parts), n


def build_prompts(tgt: str, *, week: int, week_text: str, n: int) -> dict:
    tgt_name = LANG_NAME.get(tgt, tgt)
    common = COMMON.format(tgt_name=tgt_name, week=week, n=n, week_text=week_text)
    return {l["key"]: common + f"\nYOUR LENS: **{l['title']}** — "
                               + l["body"].format(tgt_name=tgt_name) + _CONTRACT
            for l in LENSES}


def apply_fix(client, model, row, *, wdir, tgt, issues):
    """Revise one scene's translation from the pooled feedback. revise_translation raises if the line
    count moves, so a broken revision leaves the scene untouched."""
    stem = row["stem"]
    p = {ext: wdir / f"{stem}.{ext}" for ext in ("en", "da", tgt)}
    cols = {ext: q.read_text(encoding="utf-8").splitlines() for ext, q in p.items()}
    feedback = ("The whole-week panel flagged this scene (fix only what is named, keep the rest):\n"
                + "\n".join(f"- {x}" for x in issues))
    try:
        rev = revise_translation(client, model=model, src_lang="English", tgt_lang=LANG_NAME.get(tgt, tgt),
                                 ref_lang="Danish", en_lines=cols["en"], ref_lines=cols["da"],
                                 tgt_lines=cols[tgt], feedback=feedback, context=row["scene"])
    except (Exception, SystemExit) as exc:
        return {"stem": stem, "status": "rejected", "err": str(exc)[:80]}
    p[tgt].write_text("\n".join(rev) + "\n", encoding="utf-8")
    return {"stem": stem, "status": "fixed", "lines": len(rev)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("storyboard")
    ap.add_argument("--lang", default="ml", help="the translated track to review (ml, ta, …)")
    ap.add_argument("--fix", action="store_true", help="vote, then revise the scenes the panel agrees on")
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--min-votes", type=int, default=2)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--location", default="global")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out")
    a = ap.parse_args()
    os.environ["GOOGLE_CLOUD_LOCATION"] = a.location

    hdr = parse_storyboard_header(a.storyboard)
    rows = parse_storyboard(a.storyboard)
    wdir = Path(a.storyboard).parent
    week_text, n = assemble_week(a.storyboard, a.lang)
    if not n:
        raise SystemExit(f"no scenes with a .{a.lang} track in {wdir}")
    prompts = build_prompts(a.lang, week=hdr["week"], week_text=week_text, n=n)
    client = make_client()

    tag = f"WEEK {hdr['week']} · {LANG_NAME.get(a.lang, a.lang)} · {n} scenes"
    if a.fix:
        print(f"\n--- {tag} — vote-gated fix: {a.votes} panel runs, revise scenes ≥{a.min_votes} agree on ---")
        scenes, weekly = collect_votes(client, a.model, prompts,
                                       votes=a.votes, min_votes=a.min_votes, workers=a.workers)
        if weekly:
            print("\n  whole-week issues (agreed on, not scene-local — handle by hand):")
            for w in weekly:
                print(f"    [{w['severity']}] {w['votes']}/{a.votes} — {w['issues'][0]}")
        by_num = {str(r["num"]): r for r in rows}
        results = []
        for s in scenes:
            row = by_num.get(str(s["scene"]))
            if not row:
                continue
            res = apply_fix(client, a.model, row, wdir=wdir, tgt=a.lang, issues=s["issues"])
            results.append(res)
            print(f"  {'✓' if res['status'] == 'fixed' else '✗'} scene {s['scene']} "
                  f"({row['stem']}) {s['votes']}/{a.votes} {s['severity']}: {res['status']}")
        if not results:
            print("  no scene survived the vote — nothing to fix.")
        out = a.out or str(wdir / f"review_{a.lang}_summary.json")
        Path(out).write_text(json.dumps({"lang": a.lang, "votes": a.votes, "whole_week": weekly,
                                         "scene_survivors": scenes, "revised": results},
                                        indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  findings → {out}")
        return 0

    findings, failed = run_panel(client, a.model, prompts, a.workers)
    print(f"\n=== {tag} ===\n{len(findings)} finding(s) across {len(LENSES) - len(failed)}/{len(LENSES)} lenses\n")
    for f in sorted(findings, key=lambda f: _SEV_RANK.get(f.get("severity"), 3)):
        print(f"  [{f.get('severity', '?'):<4}] (scene {f.get('scene')}; {f.get('lens')}) {f.get('issue')}")
        print(f"         ↳ {f.get('why', '')}")
    if a.out:
        Path(a.out).write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if any(f.get("severity") == "High" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
