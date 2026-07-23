"""Specimen harness for a single review_week panel lens.

The methodology gate for verifier-wording changes: before trusting a new/edited lens, run it
standalone over specimen weeks with known ground truth (must-flag / must-stay-quiet) and the same
vote mechanics as --fix (a scene "survives" at >=2 of 3 votes). The harness is the arbiter of
wording — occam trims it, but only specimen results earn it a place in the panel.

Specimens are picked per run via --weeks; the expectations live with the invocation (run log /
commit message), not here — they change as content moves.

Run:  set -a; . ./.env; set +a; export GOOGLE_CLOUD_LOCATION=global
      TANDEM_TRACE=variants/kochi/lens_test.trace.jsonl \\
      .venv/bin/python lens_harness.py --lens padding --root variants/kochi \\
          --weeks week01 week02 week03 week09 --lang ml
"""
from __future__ import annotations
import argparse
import concurrent.futures
import os
from pathlib import Path

from review_week import LENSES, assemble_week, build_prompt, run_lens
from review_storyboard import curriculum_row
from tandem.gen import DEFAULT_MODEL, parse_storyboard_header
from tandem.langs import LANG_NAMES
from tandem.llm import make_client


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run one panel lens standalone over specimen weeks, with votes.")
    ap.add_argument("--lens", required=True, help="lens key from review_week.LENSES (e.g. padding)")
    ap.add_argument("--root", required=True, help="course root holding weekNN/ dirs (e.g. variants/kochi)")
    ap.add_argument("--weeks", nargs="+", required=True, help="week dirs under root (e.g. week01 week03)")
    ap.add_argument("--lang", default="da")
    ap.add_argument("--bible", help="bible path (default <root>/story_bible_<lang>.md)")
    ap.add_argument("--curriculum", help="curriculum path (default <root>/curriculum_<lang>.md)")
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--location", default="global")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    if args.location:
        os.environ["GOOGLE_CLOUD_LOCATION"] = args.location

    root = Path(args.root)
    bible_p = Path(args.bible) if args.bible else root / f"story_bible_{args.lang}.md"
    curric_p = Path(args.curriculum) if args.curriculum else root / f"curriculum_{args.lang}.md"
    bible = bible_p.read_text(encoding="utf-8")
    language = LANG_NAMES.get(args.lang, args.lang)
    lens = next((l for l in LENSES if l["key"] == args.lens), None)
    if lens is None:
        raise SystemExit(f"no lens '{args.lens}' — have: {[l['key'] for l in LENSES]}")

    client = make_client()

    def one_vote(week: str, i: int):
        sb = root / week / "storyboard.md"
        hdr = parse_storyboard_header(sb)
        header = f"Week {hdr['week']} · {hdr['level']} · grammar: {hdr['grammar']}"
        prompt = build_prompt(lens, header=header, week_text=assemble_week(sb, key=args.lang),
                              bible=bible, curric=curriculum_row(curric_p, hdr["week"]),
                              language=language)
        return week, i, run_lens(client, args.model, lens, prompt)

    results: dict[str, dict[int, list]] = {w: {} for w in args.weeks}
    jobs = [(w, i) for w in args.weeks for i in range(args.votes)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = [ex.submit(one_vote, w, i) for w, i in jobs]
        for fut in concurrent.futures.as_completed(futs):
            w, i, fs = fut.result()
            results[w][i] = fs
            print(f"  {w} vote {i + 1}: {len(fs)} finding(s)", flush=True)

    min_votes = max(2, (args.votes // 2) + 1) if args.votes > 1 else 1
    for w in args.weeks:
        print(f"\n==== {w} ====")
        for i in sorted(results[w]):
            for f in results[w][i]:
                print(f"  vote{i + 1} [{f['severity']}] scene {f['scene']}: {f['issue']}")
            if not results[w][i]:
                print(f"  vote{i + 1}: quiet")
        tally: dict[str, set] = {}
        for i, fs in results[w].items():
            for f in fs:
                tally.setdefault(str(f["scene"]), set()).add(i)
        survivors = {s: len(v) for s, v in tally.items() if len(v) >= min_votes}
        print(f"  SURVIVORS (>={min_votes}/{args.votes} votes): {survivors or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
