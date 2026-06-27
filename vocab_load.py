"""Week-level vocabulary-load readout — the counterweight to the storyboard DENSITY lens.

Deterministic, no API. Aggregates the per-scene `band_check` (already in `verify`, but advisory and
per-scene) across a whole week, so a vocab spike is VISIBLE: density pushes events up, this keeps the
word-load honest. Reports distinct word-forms, how many fall beyond the level's frequency band, the
ratio, and — most useful — the RAREST out-of-band words with the scenes they appear in, i.e. the
trim candidates ("does this event really need 'termostat' (rank 34k)?").

It is ADVISORY (like the band-check it sums): some weeks legitimately run noun-heavy (a shopping
week). The real control is the storyboard — choose diverse EVENTS grounded in common, everyday words,
not technical jargon (see the density lens's COMMON VOCABULARY criterion). This readout just confirms
the storyboard's choices landed. Baseline so far: wk1–3 sit at ~28–35% out-of-band for A1.

Run:  .venv/bin/python vocab_load.py year1/week04        (a week dir or a storyboard.md)
Exit: always 0 (advisory).
"""
from __future__ import annotations
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from tandem.gen import CEFR_BANDS, STORY_NAMES, load_freq_ranks, parse_storyboard_header, _distinct_words

# Proper nouns we can't (and shouldn't) simplify — exempt from trim candidates on top of STORY_NAMES.
_FAMILY = frozenset({"sofía", "sofia", "diego", "lola", "mexico"})

# Advisory ceilings on the out-of-band ratio, per level. CALIBRATION (2026-06-27): the ratio tracks
# DENSITY, not difficulty — the OpenSubtitles freq list under-ranks everyday concrete nouns (radiator,
# køleskab, pære), so a rich, eventful week legitimately runs high. The density GOLD STANDARD, Anna's
# week, sits at 61% @ A1 / 48% @ A2. So these ceilings are generous: they catch only a genuinely
# extreme spike. The ACTIONABLE signal is the rarest-words list below (scan it for TECHNICAL jargon —
# termostat/ventil — not for everyday nouns), and the real control is the storyboard's COMMON
# VOCABULARY criterion. The thin wk1–3 (28–35%) were thin BECAUSE their vocab was sparse — not a target.
_CEILING = {"A1": 0.52, "A2": 0.56, "B1": 0.60, "B2": 0.64}
_BENCHMARK = "Anna's-week density benchmark ≈ 61% @ A1 / 48% @ A2"


def _resolve(target: Path) -> tuple[Path, str]:
    """Return (week_dir, level). target may be a week dir or a storyboard.md."""
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
    ranks = load_freq_ranks()
    band = CEFR_BANDS.get(level, 800)
    exempt = STORY_NAMES | _FAMILY

    word_scenes: dict[str, set] = defaultdict(set)
    for f in das:
        stem = f.name.replace(".da", "")
        for w in _distinct_words([l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]):
            if w not in exempt:
                word_scenes[w].add(stem)

    distinct = len(word_scenes)
    oob = {w: ranks.get(w) for w in word_scenes if (ranks.get(w) is None or ranks.get(w) > band)}
    ratio = len(oob) / max(1, distinct)
    ceiling = _CEILING.get(level, 0.40)

    # Rarest first: unranked (None) treated as rarest, then descending rank. These are trim candidates.
    def keyrank(w):
        r = oob[w]
        return (0, 0) if r is None else (1, -r)
    rarest = sorted(oob, key=keyrank)

    print(f"\n=== VOCAB LOAD — {week_dir} · {level} (band ≈ top {band}) · {len(das)} scenes ===")
    print(f"{distinct} distinct word-forms · {len(oob)} beyond band ({round(100*ratio)}%)   "
          f"[{_BENCHMARK}]")
    print("\n  rarest out-of-band — SCAN FOR JARGON (technical/specialized words to commonize at the\n"
          "  storyboard level); everyday concrete nouns here are FINE (the gloss carries them):")
    for w in rarest[:18]:
        r = oob[w]
        rs = "unranked" if r is None else f"rank {r}"
        where = ", ".join(sorted(word_scenes[w]))
        print(f"    {w:<18} {rs:<12} [{where}]")
    print()
    if ratio > ceiling:
        print(f"VOCAB: ⚠ unusually high for {level} ({round(100*ratio)}% > ~{round(100*ceiling)}%, "
              f"beyond even the Anna benchmark) — check the rarest words above for a jargon cluster.")
    else:
        print(f"VOCAB: ✓ {round(100*ratio)}% — within dense-week range for {level} "
              f"(the % tracks density; what matters is no jargon in the list above).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Week-level vocabulary-load readout (advisory).")
    ap.add_argument("target", help="week dir (year1/week04) or a storyboard.md")
    args = ap.parse_args(argv)
    return report(Path(args.target))


if __name__ == "__main__":
    raise SystemExit(main())
