"""Drive translate + verify(+fix) across a RANGE of weeks, in one resumable command.

translate_week.py does one week and always overwrites; verify_translation.py verifies one week.
This loops both over many weeks so the whole 1-28 x languages run happens hands-off:

  for each week: for each scene: for each language
    translate (unless the target already exists and is aligned) -> verify -> (--fix) revise -> next

IDEMPOTENT / RESUMABLE — a scene/language whose target already exists and is line-aligned is skipped, so
re-running after an interruption (network drop, teardown) picks up where it stopped without redoing
finished work or spending API calls on it. Force a re-translate with --redo <weekspec>.

Per week it sets TANDEM_TRACE=<weekdir>/trace.jsonl, so every call lands in that week's local provenance
trace (not committed — see .gitignore). Report-only by default; --fix auto-revises flagged lines.

Run:  set -a; . ./.env; set +a; export GOOGLE_CLOUD_LOCATION=global; \
      .venv/bin/python translate_run.py --weeks 3-28 --langs hi --fix
      # redo one week and translate the rest fresh, in a single resumable command:
      .venv/bin/python translate_run.py --weeks 3-28 --langs hi --fix --redo 3
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

from tandem.gen import parse_storyboard, DEFAULT_MODEL
from tandem.llm import make_client
from tandem.translate import translate_lines
from translate_week import LANG_NAMES, _lines
from verify_translation import check_scene_lang


def parse_weeks(spec: str) -> list[int]:
    """'3' -> [3]; '3-28' -> [3..28]; '3,5,7' -> [3,5,7]; combinations allowed."""
    weeks: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            weeks.extend(range(int(lo), int(hi) + 1))
        else:
            weeks.append(int(part))
    return weeks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weeks", required=True, help="week range: 3-28, a single 3, or a list 3,5,7")
    ap.add_argument("--langs", nargs="+", default=["hi"])
    ap.add_argument("--root", default="year1", help="course root holding weekNN/ (default year1)")
    ap.add_argument("--fix", action="store_true",
                    help="auto-revise flagged lines and re-verify (else report-only)")
    ap.add_argument("--max-rounds", type=int, default=2, help="revise rounds per scene/lang (with --fix)")
    ap.add_argument("--redo", default="", help="week spec to force re-translate even if the target exists")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()

    root = Path(a.root)
    redo_weeks = set(parse_weeks(a.redo))
    client = make_client()

    summary: list[tuple[int, int]] = []       # (week, issues remaining/flagged)
    failed: list[str] = []                     # scenes whose translate errored (alignment) — re-run these
    mode = "fix" if a.fix else "report-only"

    for n in parse_weeks(a.weeks):
        wk = root / f"week{n:02d}"
        sb = wk / "storyboard.md"
        if not sb.exists():
            print(f"[skip week {n}] no {sb}")
            continue
        os.environ["TANDEM_TRACE"] = str(wk / "trace.jsonl")   # per-week local provenance
        force = n in redo_weeks
        print(f"\n########## week {n:02d}  ({', '.join(a.langs)} · {mode}"
              f"{' · redo' if force else ''}) ##########")

        wk_issues = 0
        for r in parse_storyboard(sb):
            stem = r["stem"]
            da, en = wk / f"{stem}.da", wk / f"{stem}.en"
            if not (da.exists() and en.exists()):
                print(f"  [skip] {stem}: missing .da/.en")
                continue
            en_lines, da_lines = _lines(en), _lines(da)
            if len(en_lines) != len(da_lines):
                print(f"  [skip] {stem}: da/en mismatch ({len(da_lines)} vs {len(en_lines)})")
                continue
            for lang in a.langs:
                tgt = wk / f"{stem}.{lang}"
                if not force and tgt.exists() and len(_lines(tgt)) == len(en_lines):
                    print(f"  [have] {stem}.{lang} — skip")   # already done; resumable no-op
                    continue
                try:
                    out = translate_lines(client, model=a.model, src_lang="English",
                                          tgt_lang=LANG_NAMES.get(lang, lang), lines=en_lines,
                                          ref_lang="Danish", ref_lines=da_lines,
                                          context=f"{wk.name} · {stem}")
                    tgt.write_text("\n".join(s.strip() for s in out) + "\n", encoding="utf-8")
                    print(f"  [ok] {stem}.{lang}: {len(out)} lines")
                    wk_issues += check_scene_lang(client, model=a.model, wk=wk, stem=stem, lang=lang,
                                                  en_lines=en_lines, da_lines=da_lines,
                                                  fix=a.fix, max_rounds=a.max_rounds if a.fix else 0)
                except (SystemExit, Exception) as e:   # a persistent failure on ONE scene (alignment,
                    print(f"  [FAIL] {stem}.{lang}: {e}")  # or a blip that outlived its retries) must
                    failed.append(f"{wk.name}/{stem}.{lang}")   # not abort the batch — log it, move on
                    continue

        summary.append((n, wk_issues))
        print(f"\n=== week {n:02d}: {wk_issues} issue(s) "
              f"{'remaining after fix' if a.fix else 'flagged'} ===")

    print("\n########## RUN SUMMARY ##########")
    for n, iss in summary:
        print(f"  week {n:02d}: {iss} issue(s) {'remaining' if a.fix else 'flagged'}")
    if failed:
        print("FAILED to translate (alignment) — re-run:")
        for f in failed:
            print(f"  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
