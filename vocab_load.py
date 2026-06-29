"""Week-level vocabulary readout — surfaces the RAREST words for a jargon check.

Deterministic, no API. Aggregates the per-scene `band_check` across a whole week and lists the rarest
out-of-band words with the scenes they appear in — the trim candidates ("does this event really need
'termostat' (rank 34k)?"). ADVISORY: some weeks legitimately run noun-heavy. The real control is the
storyboard — choose diverse EVENTS grounded in common, everyday words, not technical jargon (see the
density lens's COMMON VOCABULARY criterion); this readout just confirms the storyboard's choices
landed. (Danish-specific: reads the .da and a Danish frequency list — revisit per-language later.)

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

    # Rarest first: unranked (None) treated as rarest, then descending rank. These are trim candidates.
    def keyrank(w):
        r = oob[w]
        return (0, 0) if r is None else (1, -r)
    rarest = sorted(oob, key=keyrank)

    print(f"\n=== VOCAB LOAD — {week_dir} · {level} (band ≈ top {band}) · {len(das)} scenes ===")
    print(f"{distinct} distinct word-forms · {len(oob)} beyond band — SCAN THE RAREST FOR JARGON\n"
          "  (technical/specialized words to commonize at the storyboard level; everyday concrete\n"
          "  nouns here are FINE — the gloss carries them):")
    for w in rarest[:18]:
        r = oob[w]
        rs = "unranked" if r is None else f"rank {r}"
        where = ", ".join(sorted(word_scenes[w]))
        print(f"    {w:<18} {rs:<12} [{where}]")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Week-level vocabulary-load readout (advisory).")
    ap.add_argument("target", help="week dir (year1/week04) or a storyboard.md")
    args = ap.parse_args(argv)
    return report(Path(args.target))


if __name__ == "__main__":
    raise SystemExit(main())
