#!/usr/bin/env python3
"""Deterministic content checks for CI (stdlib only, no API keys needed).

For every week directory (year1/weekNN, variants/*/weekNN):
  1. every L2 scene file has a same-named .en gloss, and vice versa;
  2. the L2 file and its gloss have the SAME number of non-empty lines
     (the invariant the interleaved audio depends on);
  3. every stem in storyboard.md has scene files, and no scene file is orphaned.

Exit 0 = all clean; exit 1 = violations (printed one per line).
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

L2_EXTS = (".da", ".ml")
errors: list[str] = []


def lines_of(p: Path) -> int:
    return len([l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()])


def storyboard_stems(week: Path) -> list[str]:
    sb = week / "storyboard.md"
    if not sb.exists():
        return []
    return re.findall(r"^\| *\d+ *\| *(\S+) *\|", sb.read_text(encoding="utf-8"), re.M)


def check_week(week: Path) -> None:
    stems_sb = storyboard_stems(week)
    seen = set()
    for l2 in sorted(p for p in week.iterdir() if p.suffix in L2_EXTS):
        seen.add(l2.stem)
        en = l2.with_suffix(".en")
        if not en.exists():
            errors.append(f"{l2}: missing English gloss {en.name}")
            continue
        a, b = lines_of(l2), lines_of(en)
        if a != b:
            errors.append(f"{l2}: {a} lines vs {en.name}: {b} lines (misaligned)")
    for en in week.glob("*.en"):
        if en.stem not in seen:
            errors.append(f"{en}: gloss without an L2 file")
    for stem in stems_sb:
        if stem not in seen:
            errors.append(f"{week}/storyboard.md: stem '{stem}' has no scene files")
    for stem in seen:
        if stems_sb and stem not in stems_sb:
            errors.append(f"{week}: scene '{stem}' not in storyboard.md")


def main() -> int:
    roots = [Path("year1")] + (sorted(Path("variants").glob("*")) if Path("variants").exists() else [])
    n = 0
    for root in roots:
        if not root.is_dir():
            continue
        for week in sorted(root.glob("week[0-9][0-9]")):
            check_week(week)
            n += 1
    for e in errors:
        print(f"FAIL {e}")
    print(f"checked {n} week directories: {'CLEAN' if not errors else f'{len(errors)} violation(s)'}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
