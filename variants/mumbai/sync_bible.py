"""Derive per-track bibles from the master story_bible.md.

The master holds the shared canon plus ALL THREE tracks' register sections.
Feeding that whole file to a track's generator lets registers cross-pollinate
(wk1: the Hindi track picked Marathi's elder kin-term). This script writes
story_bible_{hi,mr,sa}.md, each identical to the master except the Register
section keeps ONLY that track's bullet. Generators and reviewers must be
pointed at the per-track file. Edit the master, re-run.

Run:  python variants/mumbai/sync_bible.py
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
NAMES = {"hi": "Hindi", "mr": "Marathi", "sa": "Sanskrit"}

master = (HERE / "story_bible.md").read_text("utf-8")
m = re.search(r"## Register \(per track\)\n(.*?)(\n## )", master, re.S)
section, rest_marker = m.group(1), m.group(2)
bullets = re.findall(r"(- \*\*(Hindi|Marathi|Sanskrit)\*\* — .*?)(?=\n- \*\*|\Z)", section, re.S)
by_name = {name: text.rstrip() + "\n" for text, name in bullets}
assert set(by_name) == set(NAMES.values()), sorted(by_name)

for code, name in NAMES.items():
    out = master.replace(m.group(0), f"## Register ({name} track)\n{by_name[name]}{rest_marker}")
    (HERE / f"story_bible_{code}.md").write_text(out, "utf-8")
    print(f"story_bible_{code}.md")
