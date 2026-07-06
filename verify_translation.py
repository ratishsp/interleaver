"""Verify a week's translations — a TRIAGE report, and (with --fix) a bounded revise loop.

For each scene and target language, judge the translated {stem}.{lang} against the English source, with
the aligned Danish as the DISAMBIGUATION reference (the same trio translate_week.py used to produce it).
Prints a per-line issue list. Deterministic gates (alignment, empty, untranslated echo, multi-sentence)
run always; an independent LLM review scores fidelity / disambiguation_carried / naturalness /
no_relocation.

Default is report-only — you act on the Malayalam by ear; the machine's real value is the Tamil gloss
you cannot check. Pass --fix to auto-revise the FLAGGED lines (revise_translation, mirroring the
creation stage's verify->revise) and re-verify, up to --max-rounds. Tip: `--fix --langs ta` fixes only
the Tamil gloss and leaves the Malayalam for your ear.

Run:  set -a; . ./.env; set +a; export GOOGLE_CLOUD_LOCATION=global; \
      .venv/bin/python verify_translation.py year1/week01 --langs ml ta [--fix]
"""
from __future__ import annotations
import argparse
from pathlib import Path

from tandem.gen import parse_storyboard, DEFAULT_MODEL
from tandem.llm import make_client
from tandem.translate import (verify_translation, revise_translation,
                              format_translation_flags, print_translation_report)

LANG_NAMES = {"ml": "Malayalam", "ta": "Tamil", "es": "Spanish", "hi": "Hindi"}


def _lines(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def check_scene_lang(client, *, model, wk, stem, lang, en_lines, da_lines, fix, max_rounds) -> int:
    """Verify one scene/language; with fix, revise flagged lines and re-verify up to max_rounds.

    Returns the issue count at the final state (0 = clean). Rewrites {stem}.{lang} in place on a fix.
    """
    tgt_lang = LANG_NAMES.get(lang, lang)
    tgt_path = wk / f"{stem}.{lang}"
    tgt_lines = _lines(tgt_path)
    ctx = f"{wk.name} · {stem}"
    kw = dict(src_lang="English", tgt_lang=tgt_lang, ref_lang="Danish")
    for rnd in range(max_rounds + 1):
        rep = verify_translation(client, model=model, en_lines=en_lines, ref_lines=da_lines,
                                 tgt_lines=tgt_lines, context=ctx, **kw)
        label = f"\n{stem}.{lang}" + (f"  (re-check {rnd})" if rnd else "")
        n = print_translation_report(rep, label=label)
        if n == 0 or not fix or rnd == max_rounds:
            return n
        feedback = format_translation_flags(rep, src_lang="English", tgt_lang=tgt_lang)
        if not feedback.strip():                 # e.g. an alignment fail — nothing revise can act on
            return n
        try:
            tgt_lines = revise_translation(client, model=model, en_lines=en_lines, ref_lines=da_lines,
                                           tgt_lines=tgt_lines, feedback=feedback, context=ctx, **kw)
        except SystemExit as e:
            print(f"  [revise skipped] {e}")
            return n
        tgt_path.write_text("\n".join(s.strip() for s in tgt_lines) + "\n", encoding="utf-8")
        print(f"  [revised {stem}.{lang}] round {rnd + 1}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("weekdir")
    ap.add_argument("--langs", nargs="+", default=["ml", "ta"])
    ap.add_argument("--scenes", help="stem substring filter (e.g. '01_') to check one scene")
    ap.add_argument("--fix", action="store_true", help="auto-revise flagged lines and re-verify")
    ap.add_argument("--max-rounds", type=int, default=2, help="revise rounds per scene/lang (with --fix)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    wk = Path(a.weekdir)
    client = make_client()

    total = 0
    for r in parse_storyboard(wk / "storyboard.md"):
        stem = r["stem"]
        if a.scenes and a.scenes not in stem:
            continue
        da, en = wk / f"{stem}.da", wk / f"{stem}.en"
        if not (da.exists() and en.exists()):
            print(f"  [skip] {stem}: missing .da/.en")
            continue
        en_lines, da_lines = _lines(en), _lines(da)
        for lang in a.langs:
            if not (wk / f"{stem}.{lang}").exists():
                print(f"  [skip] {stem}.{lang}: not translated yet")
                continue
            total += check_scene_lang(client, model=a.model, wk=wk, stem=stem, lang=lang,
                                      en_lines=en_lines, da_lines=da_lines,
                                      fix=a.fix, max_rounds=a.max_rounds)
    verb = "remaining after fix" if a.fix else "flagged"
    print(f"\n=== {wk.name}: {total} issue(s) {verb} across {', '.join(a.langs)} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
