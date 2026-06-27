"""Week-level sentence-COMPLEXITY readout — the structural counterpart to vocab_load.

Deterministic, no API. The per-scene CEFR check (an LLM) is lenient about sentence STRUCTURE — it
passed week 4's compound sentences as "A1" even though they string two clauses together ("X, og Y"),
drifting above the one-short-clause-per-line style of weeks 1–3. This catches that drift mechanically:
average words/line, the longest lines, and counts of COMPOUND (comma + og/men/så/eller — two clauses)
and SUBORDINATE (fordi/når/da/som/hvis/mens…) constructions, compared to the level's baseline. It then
lists the most complex lines as SPLIT candidates ("X, og Y." → "X. / Y.").

Baseline observed in weeks 1–3 (A1): ~4.8 words/line, ~1% compound, ~0 subordinate, max ~9–11 words.
Week 4 (3.1 + eventful content) drifted to 5.8 avg / 5.7% compound / one 15-word line — natural prose,
but above A1. Advisory; auto-runs in gen_week with the lint + vocab-load.

Run:  .venv/bin/python complexity.py year1/week04        (a week dir or a storyboard.md)
Exit: always 0 (advisory).
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

from tandem.gen import parse_storyboard_header

_WORD = re.compile(r"[\wæøåÆØÅ']+")
_COMPOUND = re.compile(r",\s+(og|men|så|eller|for)\b")          # comma + coordinator = two clauses
_SUBORD = re.compile(r"\b(fordi|når|da|som|hvis|mens|selvom|inden|efter at|før)\b")
# Place/direction prepositions — a line stacking several is "busy" for A1 even as ONE clause (e.g.
# "over gangen fra mit gamle værelse", "på køleskabet og på brødet på bordet"). The compound-CLAUSE
# check misses these; this surfaces them for a HUMAN to judge (noun lists / two quick actions are fine).
_PREP = {"i", "på", "til", "fra", "med", "over", "under", "ved", "om", "af", "hen", "ind", "ud",
         "bag", "mod", "gennem", "mellem", "efter", "hos", "forbi", "rundt"}


def _busy(line: str) -> bool:
    toks = [t.lower() for t in _WORD.findall(line)]
    preps = sum(1 for t in toks if t in _PREP)
    intra_og = bool(re.search(r"\w\s+og\s+\w", line)) and not re.search(r",\s+og\b", line)
    return len(toks) >= 7 and (preps >= 3 or (intra_og and preps >= 2))

# Per-level advisory ceilings. The PRIMARY structural signal is the COMPOUND ratio (two clauses joined
# by a comma + coordinator) + subordinate clauses — that's what "complex sentences" means and what
# weeks 1–3 kept near zero. The avg-words/line ceiling is SECONDARY and deliberately loose, because it
# is confounded by dialogue attribution ("...," siger jeg til mig selv) and lists, which inflate word
# counts without adding structural complexity. So a dialogue-rich eventful week can sit a little above
# the wk1–3 ~4.8 avg and still be structurally A1, as long as the compound ratio stays low.
_AVG_CEIL = {"A1": 5.6, "A2": 7.0, "B1": 8.5, "B2": 10.5}
_COMPOUND_CEIL = {"A1": 0.03, "A2": 0.12, "B1": 0.25, "B2": 0.40}


def _words(line: str) -> int:
    return len(_WORD.findall(line))


def _resolve(target: Path) -> tuple[Path, str]:
    sb = target if target.is_file() else target / "storyboard.md"
    level = "A1"
    if sb.exists():
        try:
            level = parse_storyboard_header(sb)["level"].split()[0].upper()
        except Exception:
            pass
    return (sb.parent if target.is_file() else target), level


def report(target: Path) -> int:
    week_dir, level = _resolve(target)
    das = sorted((p for p in week_dir.glob("*.da") if re.match(r"\d+_", p.name)),
                 key=lambda p: int(p.name.split("_", 1)[0]))
    if not das:
        print(f"no NN_*.da scene files under {week_dir}", file=sys.stderr)
        return 2

    # (line, words, scene-stem) for every non-blank Danish line
    rows = []
    for f in das:
        stem = f.name.replace(".da", "")
        for l in f.read_text(encoding="utf-8").splitlines():
            l = l.strip()
            if l:
                rows.append((l, _words(l), stem))
    n = len(rows)
    avg = sum(w for _, w, _ in rows) / max(1, n)
    mx = max(w for _, w, _ in rows)
    compound = [(l, w, s) for l, w, s in rows if _COMPOUND.search(l)]
    subord = [(l, w, s) for l, w, s in rows if _SUBORD.search(l.lower())]
    long_lines = [(l, w, s) for l, w, s in rows if w > 12]
    cratio = len(compound) / max(1, n)
    avg_ceil, comp_ceil = _AVG_CEIL.get(level, 6.0), _COMPOUND_CEIL.get(level, 0.10)

    print(f"\n=== SENTENCE COMPLEXITY — {week_dir} · {level} · {len(das)} scenes, {n} lines ===")
    print(f"avg {avg:.1f} words/line (ceiling {avg_ceil}) · max {mx} · "
          f"compound {len(compound)} = {round(100*cratio)}% (ceiling {round(100*comp_ceil)}%) · "
          f"subordinate {len(subord)}")
    print("  (A1 baseline from wk1–3: ~4.8 words/line, ~1% compound, ~0 subordinate)")

    cand = sorted({(l, w, s) for l, w, s in (compound + long_lines + subord)}, key=lambda r: -r[1])
    if cand:
        print("\n  SPLIT candidates (compound/long/subordinate — split into single-clause lines):")
        for l, w, s in cand[:16]:
            print(f"    [{w:2}w] ({s}) {l}")

    # Busy lines: single clause but 2+ stacked phrases — advisory, HUMAN judges (lists are fine).
    busy = sorted({(l, w, s) for l, w, s in rows if _busy(l)}, key=lambda r: -r[1])
    if busy:
        print("\n  BUSY-LINE candidates (one clause, 2+ phrases — simplify if it packs two ideas;\n"
              "  noun lists / two quick actions are FINE, use judgment):")
        for l, w, s in busy[:12]:
            print(f"    [{w:2}w] ({s}) {l}")
    print()
    over = avg > avg_ceil or cratio > comp_ceil
    if over:
        print(f"COMPLEXITY: ⚠ above {level} baseline (avg {avg:.1f}>{avg_ceil} or compound "
              f"{round(100*cratio)}%>{round(100*comp_ceil)}%) — split the compound lines above to "
              f"match the one-short-clause-per-line style.")
    else:
        print(f"COMPLEXITY: ✓ within {level} baseline (avg {avg:.1f}, compound {round(100*cratio)}%).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Week-level sentence-complexity readout (advisory).")
    ap.add_argument("target", help="week dir (year1/week04) or a storyboard.md")
    args = ap.parse_args(argv)
    return report(Path(args.target))


if __name__ == "__main__":
    raise SystemExit(main())
