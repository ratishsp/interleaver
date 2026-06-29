"""Deterministic repetition linter for a week's generated scenes — runs BEFORE the LLM week-gate.

No API, no model: pure string analysis over the week's `.en` GLOSS files. It catches the mechanical
repetition the expensive whole-week gate would otherwise spend rounds on (one line closing many
scenes, an emotion word in half the scenes, identical openers, a sentence copy-pasted across scenes).
Cheap + instant → fix the obvious stuff here, let the LLM gate judge what needs judgment.

It runs on the ENGLISH gloss, not the L2: the gloss is line-aligned and faithful, so repetition in
the target language surfaces identically in English — and English is constant across every L2, so this
one check is language-agnostic (no per-language stoplist/tokeniser to maintain as languages are added).

This is the deterministic backstop to the storyboard DENSITY lens (the real fix is dense, varied
scenes — then repetition mostly takes care of itself, as in Anna's week). Calibrated for a
comprehensible-input course: MODERATE repetition of common words is GOOD, so thresholds flag only
genuinely mechanical reuse (a full sentence repeated across scenes, one beat closing many scenes,
an element saturating the week), never ordinary function-word frequency.

Run:  .venv/bin/python lint_week.py year1/week04        (or a storyboard.md, or a dir of .en files)
Exit:  1 if any HIGH-severity repeat, else 0.
"""
from __future__ import annotations
import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Ubiquitous English function words excluded from the "word in many scenes" check. The gloss is
# English, so the stoplist is English too — which is what makes this check language-agnostic.
_STOP = {
    "i", "you", "he", "she", "it", "we", "they", "is", "are", "am", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "a", "an", "the", "and", "or", "but", "not", "no",
    "in", "on", "to", "with", "for", "of", "as", "at", "by", "from", "about", "into", "over",
    "that", "this", "these", "those", "my", "your", "his", "her", "its", "our", "their",
    "here", "there", "now", "so", "very", "just", "then", "what", "where", "when", "who", "how",
    "can", "will", "shall", "would", "could", "should", "me", "him", "us", "them", "up", "out",
}
_WORD = re.compile(r"[a-zæøåA-ZÆØÅ]+")


def _scene_files(target: Path) -> list[Path]:
    """Resolve target → ordered list of scene .en gloss files (a week dir, a storyboard.md, or a dir)."""
    if target.is_file() and target.suffix == ".md":          # storyboard → its directory
        target = target.parent
    glosses = [p for p in target.glob("*.en") if re.match(r"\d+_", p.name)]
    return sorted(glosses, key=lambda p: int(p.name.split("_", 1)[0]))


def _norm(line: str) -> str:
    """Normalize a line for cross-scene equality: lowercase, drop quotes/punctuation/space runs."""
    s = line.lower().strip().strip('"“”')
    s = re.sub(r"[^a-zæøå0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def lint(target: Path) -> int:
    files = _scene_files(target)
    if not files:
        print(f"no NN_*.da scene files under {target}", file=sys.stderr)
        return 2
    n = len(files)
    scenes = {f.name.replace(".en", ""): [ln.rstrip("\n") for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
              for f in files}
    stems = list(scenes)

    line_scenes: dict[str, list[str]] = defaultdict(list)   # normalized line -> scenes it appears in
    openers, closers = Counter(), Counter()
    word_scenes: dict[str, set] = defaultdict(set)          # content word -> set of scenes
    for stem, lines in scenes.items():
        norms = [_norm(l) for l in lines]
        for nl in set(norms):
            if nl:
                line_scenes[nl].append(stem)
        if norms:
            openers[norms[0]] += 1
            closers[norms[-1]] += 1
        for w in {w for l in lines for w in _WORD.findall(l.lower()) if len(w) >= 4 and w not in _STOP}:
            word_scenes[w].add(stem)

    findings: list[tuple[str, str]] = []   # (severity, message)

    # 1) A full sentence repeated verbatim across scenes (≥4 words = a real sentence, not a tag).
    for nl, where in sorted(line_scenes.items(), key=lambda kv: -len(kv[1])):
        if len(where) >= 2 and len(nl.split()) >= 4:
            sev = "HIGH" if len(where) >= 3 else "MED"
            findings.append((sev, f"sentence repeated in {len(where)} scenes ({', '.join(where)}): “{nl}”"))

    # 2) The same closing line ending many scenes (a mechanical scene-ender template).
    for nl, c in closers.most_common():
        if c >= 3 and nl:
            findings.append(("HIGH", f"same CLOSING line ends {c} scenes: “{nl}”"))
        elif c == 2 and nl and len(nl.split()) >= 2:
            findings.append(("MED", f"same closing line ends 2 scenes: “{nl}”"))
    # 3) Identical opening line across many scenes (the "Det er aften." restart).
    for nl, c in openers.most_common():
        if c >= 3 and nl:
            findings.append(("HIGH", f"same OPENING line starts {c} scenes: “{nl}”"))
        elif c == 2 and nl and len(nl.split()) >= 2:
            findings.append(("MED", f"same opening line starts 2 scenes: “{nl}”"))

    # 4) A short standalone clause (an emotion/filler tag) recurring across many scenes.
    for nl, where in line_scenes.items():
        wc = len(nl.split())
        if 1 <= wc <= 3 and len(where) >= 4:
            findings.append(("HIGH", f"short tag line in {len(where)} scenes ({', '.join(where)}): “{nl}”"))

    # 5) A content word saturating the week (in > 55% of scenes) — advisory, the calibrated ceiling.
    sat = sorted(((w, len(s)) for w, s in word_scenes.items() if len(s) > max(3, 0.55 * n)),
                 key=lambda kv: -kv[1])
    for w, c in sat:
        findings.append(("ADV", f"word '{w}' appears in {c}/{n} scenes ({round(100*c/n)}%) — check it isn't a crutch"))

    rank = {"HIGH": 0, "MED": 1, "ADV": 2}
    findings.sort(key=lambda f: rank[f[0]])
    highs = [f for f in findings if f[0] == "HIGH"]

    print(f"\n=== REPETITION LINT — {target} · {n} scenes ===")
    if not findings:
        print("clean — no mechanical repetition flags.")
    for sev, msg in findings:
        print(f"  [{sev:<4}] {msg}")
    print()
    if highs:
        print(f"LINT: ✗ {len(highs)} HIGH repetition flag(s) — fix before the LLM week-gate.")
        return 1
    print("LINT: ✓ no HIGH flags (review MED/ADV).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic repetition linter for a week's .da scenes.")
    ap.add_argument("target", help="week dir (year1/week04), a storyboard.md, or any dir of NN_*.da files")
    args = ap.parse_args(argv)
    return lint(Path(args.target))


if __name__ == "__main__":
    raise SystemExit(main())
