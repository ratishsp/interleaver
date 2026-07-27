"""Derive per-track storyboard copies from the master storyboards.

The master (variants/mumbai/storyboards/weekNN.md) is authored once per week with
the Hindi grammar header. Each track needs the SAME scenes under its own grammar
contract, so this script copies the master into <track>/weekNN/storyboard.md with
the header's Grammar field swapped to that track's curriculum row. Scene tables
are never edited per track — edit the master and re-run.

Run:  python variants/mumbai/sync_storyboards.py
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
TRACKS = ["hi", "mr", "sa"]


def grammar_focus(lang: str, week: int) -> str:
    for line in (HERE / f"curriculum_{lang}.md").read_text("utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[0].isdigit() and int(cells[0]) == week:
            return cells[3]  # | Wk | Lvl | Theme | Grammar focus | Brief | Grammar in English |
    raise SystemExit(f"week {week} not found in curriculum_{lang}.md")


for master in sorted(HERE.glob("storyboards/week*.md")):
    week = int(re.search(r"week(\d+)", master.name).group(1))
    text = master.read_text("utf-8")
    for lang in TRACKS:
        g = grammar_focus(lang, week)
        out = re.sub(r"(\*\*Grammar:\*\* ).*", lambda m: m.group(1) + g, text, count=1)
        dest = HERE / lang / f"week{week:02d}" / "storyboard.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out, "utf-8")
        print(f"{lang}/week{week:02d}/storyboard.md")
