"""Translate a week's scenes from English into other languages, using the aligned Danish as a
DISAMBIGUATION reference, and write {stem}.{lang} beside the existing {stem}.da / .en.

Thin driver over tandem.gen.translate_lines: English is the source of meaning; the Danish resolves what
English drops (veninde = female friend vs ven; du = singular you vs I = plural; gender/number), and
that distinction flows into the target language wherever it marks it. English wins on a real conflict.

Run:  set -a; . ./.env; set +a;  .venv/bin/python translate_week.py year1/week01 --langs ml ta
"""
from __future__ import annotations
import argparse
from pathlib import Path

from tandem.gen import make_client, translate_lines, parse_storyboard, DEFAULT_MODEL

LANG_NAMES = {"ml": "Malayalam", "ta": "Tamil", "es": "Spanish", "hi": "Hindi"}


def _lines(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("weekdir")
    ap.add_argument("--langs", nargs="+", default=["ml", "ta"])
    ap.add_argument("--scenes", help="stem substring filter (e.g. '01_') to pilot one scene")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    wk = Path(a.weekdir)
    client = make_client()

    for r in parse_storyboard(wk / "storyboard.md"):
        stem = r["stem"]
        if a.scenes and a.scenes not in stem:
            continue
        da, en = wk / f"{stem}.da", wk / f"{stem}.en"
        if not (da.exists() and en.exists()):
            print(f"  [skip] {stem}: missing .da/.en")
            continue
        en_lines, da_lines = _lines(en), _lines(da)
        if len(en_lines) != len(da_lines):
            print(f"  [skip] {stem}: da/en mismatch ({len(da_lines)} vs {len(en_lines)})")
            continue
        for lang in a.langs:
            out = translate_lines(
                client, model=a.model, src_lang="English", tgt_lang=LANG_NAMES.get(lang, lang),
                lines=en_lines, ref_lang="Danish", ref_lines=da_lines,
                context=f"{wk.name} · {stem}")
            (wk / f"{stem}.{lang}").write_text("\n".join(s.strip() for s in out) + "\n",
                                               encoding="utf-8")
        print(f"  [ok] {stem}: {len(en_lines)} lines -> {', '.join('.' + l for l in a.langs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
