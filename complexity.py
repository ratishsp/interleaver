"""Deterministic sentence-complexity readout over a week's .en GLOSS files — runs after generation.

No API, no model. Runs on the ENGLISH gloss, not the L2: the gloss is line-aligned and faithful, so it
mirrors the L2's clause structure — and English is constant across every L2, so this check is
language-agnostic (no per-language conjunction list to maintain as languages are added).

It flags COMPOUND sentences — a line joining two independent clauses with a coordinating conjunction
(", and / , but / , so / , or"), which sits above the one-clause-per-line norm of the early levels.
This is the portable half of the old Danish complexity check (which keyed on "comma + og/men/så");
the Danish-specific busy-line heuristic was dropped. A shared-subject verb pair ("she types on her
computer and registers me" — no comma) is NOT a compound clause and is left alone, as before.

ADVISORY: moderate compounding is fine, and richer levels run higher; the readout just surfaces the
lines so you can split them if a week drifts complex. Split "X, and Y." -> "X. / Y." to simplify.

B1+ UPGRADE: the comma rule catches COORDINATING compounds but not SUBORDINATE clauses (because /
when / that / if …), which have two verbs but no ", and". Those don't occur at A1/A2 (simple grammar
by design), so the regex is enough for now. When subordinate clauses can appear (B1+), upgrade this to
a spaCy clause-count over the same .en gloss — reliable verb/clause detection needs a POS tagger, which
a regex/word-list can't do (English noun/verb ambiguity: "work", "help", "tip", "number"). Same gloss,
smarter counter.

Run:  .venv/bin/python complexity.py year1/week02        (a week dir, a storyboard.md, or a dir of .en)
Exit: always 0 (advisory).
"""
from __future__ import annotations
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# Comma + coordinating conjunction = two independent clauses joined (a compound sentence). The comma
# is the key signal (mirrors Danish, which requires it before og/men/så joining main clauses), so a
# shared-subject verb pair without a comma ("types ... and registers") does not match. A genuine
# compound's comma is the FIRST comma in the line ("X, and Y"); an earlier comma means it's a list
# ("A, B, and C"), whose ", and" before the last item is NOT a clause join — those are excluded.
_COMPOUND = re.compile(r",\s+(and|but|so|or|yet|nor)\s", re.IGNORECASE)


def _is_compound(line: str) -> bool:
    m = _COMPOUND.search(line)
    return bool(m) and "," not in line[:m.start()]   # first comma → clause join, not a list


def _scene_files(target: Path) -> list[Path]:
    """Resolve target → ordered list of scene .en gloss files (a week dir, a storyboard.md, or a dir)."""
    if target.is_file() and target.suffix == ".md":
        target = target.parent
    glosses = [p for p in target.glob("*.en") if re.match(r"\d+_", p.name)]
    return sorted(glosses, key=lambda p: int(p.name.split("_", 1)[0]))


def report(target: Path) -> int:
    files = _scene_files(Path(target))
    if not files:
        print(f"no NN_*.en gloss files under {target}", file=sys.stderr)
        return 2
    per_scene: dict[str, list[str]] = defaultdict(list)
    total = 0
    for f in files:
        stem = f.name.replace(".en", "")
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            total += 1
            if _is_compound(ln):
                per_scene[stem].append(ln.strip())
    flagged = sum(len(v) for v in per_scene.values())

    print(f"\n=== SENTENCE COMPLEXITY (gloss) — {target} · {len(files)} scenes · {total} lines ===")
    print(f"{flagged} compound line(s) ({round(100 * flagged / max(1, total))}%) — two clauses joined\n"
          "  by and/but/so/or; split \"X, and Y.\" -> \"X. / Y.\" if a week reads complex:")
    for stem in per_scene:                              # files are already in scene order
        for ln in per_scene[stem]:
            print(f"    [{stem}] {ln}")
    if not flagged:
        print("    (none — all single-clause)")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sentence-complexity readout over a week's .en gloss (advisory).")
    ap.add_argument("target", help="week dir (year1/week02), a storyboard.md, or any dir of NN_*.en files")
    args = ap.parse_args(argv)
    return report(Path(args.target))


if __name__ == "__main__":
    raise SystemExit(main())
