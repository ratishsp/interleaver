"""Does a built week actually DELIVER its grammar focus? An LLM judge, one call per week.

The scope gates police what's BEYOND level; nothing measured whether the week's target grammar is
present and drilled — a numbers week shipped without a spoken number (wk2 kochi, user catch). A judge
reads the week whole and rates each target's exposure; deterministic counting was tried and dropped
(Indic-script matching is imprecise — user call).

Run:  set -a; . ./.env; set +a; export GOOGLE_CLOUD_LOCATION=global
      .venv/bin/python grammar_delivery.py variants/kochi --lang ml --weeks 1-7
"""
from __future__ import annotations
import argparse
from pathlib import Path

from gen_storyboard import curriculum_row
from tandem.gen import DEFAULT_MODEL
from tandem.langs import LANG_NAMES
from tandem.llm import make_client, _json_call

PROMPT = """You are reviewing one week of a graded {language} audio course. The week was designed to
teach a specific grammar focus. Judge whether the built text actually DELIVERS it: does the learner
get repeated, varied exposure to each target across the week — enough to internalize it?

THIS WEEK'S GRAMMAR FOCUS:
{grammar}

THE WEEK'S TEXT ({language}, scene by scene):
{text}

For each distinct target in the focus, rate its delivery: "good" (recurring, varied, natural),
"thin" (present but scarce or formulaic), or "missing". Judge the {language} text itself.

Return JSON: {{"targets": [{{"target": "<the form/structure>", "delivery": "good|thin|missing",
"note": "<one line — where it shows up, or what is absent>"}}]}}"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", help="track root (e.g. variants/kochi); use . with --curriculum for the Danish course")
    ap.add_argument("--lang", default="ml")
    ap.add_argument("--weeks", help="e.g. 1-7 (default: all built weeks)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    root = Path(a.root)
    cur = next(root.glob(f"curriculum_{a.lang}*.md"), None) or next(root.glob("curriculum_*.md"))
    language = LANG_NAMES.get(a.lang, a.lang)

    if a.weeks:
        lo, hi = (a.weeks.split("-") + [a.weeks])[:2]
        weeks = range(int(lo), int(hi) + 1)
    else:
        weeks = sorted(int(d.name[4:]) for d in root.glob("week*") if d.name[4:].isdigit())

    client = make_client()
    worst = 0
    for n in weeks:
        wdir = root / f"week{n:02d}"
        files = sorted(p for p in wdir.glob(f"*.{a.lang}") if p.stem[0].isdigit())
        if not files:
            continue
        text = "\n\n".join(f"[{f.stem}]\n{f.read_text(encoding='utf-8').strip()}" for f in files)
        row = curriculum_row(n, str(cur))
        out = _json_call(client, a.model, PROMPT.format(language=language, grammar=row["grammar"], text=text),
                         stage=f"grammar_delivery.{n}")
        targets = out.get("targets", []) if isinstance(out, dict) else (out if isinstance(out, list) else [])
        flags = [t for t in targets if isinstance(t, dict) and t.get("delivery") in ("thin", "missing")]
        if flags:
            worst = 1
            print(f"  wk{n:02d}:")
            for t in flags:
                print(f"    [{t.get('delivery','?').upper():>7}] {t.get('target','?')} — {t.get('note','')}")
        else:
            print(f"  wk{n:02d}: all targets delivered")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
