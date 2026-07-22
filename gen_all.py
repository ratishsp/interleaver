"""gen_all.py — one importable .apkg per run, with the full Bloom ladder nested under each week.

Combines the two generators so a week is a single node in Anki:
    Danish (Maya)::Week 10          <- SR flashcards  (Remember / Apply)   from gen_deck
    Danish (Maya)::Week 10::Eval    <- verified MCQs  (Analyze / Evaluate) from gen_eval

Eval stays its OWN subdeck on purpose (pedagogy.md's Phase-1/Phase-2 split): the flashcards are daily
spaced practice; the eval is a periodic assessment you study on its own — never poured into the daily
review queue. One shared media dict means an audio clip used by both sides is packaged only once.

Run:  set -a; . ./.env; set +a
      export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_LOCATION=global ALL_PROXY=socks5h://localhost:18080
      .venv/bin/python gen_all.py 1-28 --audio
"""
from __future__ import annotations
import argparse
from pathlib import Path

import genanki

from tandem.gen import DEFAULT_MODEL
from tandem.llm import make_client
from tandem.tts import GoogleTTS
from tandem.cache import ClipCache

from gen_deck import (ROOT, VOICE_OVERRIDES, DECK_SPEED, CLIP_DIR, curriculum_fields,
                      build_week_deck as build_sr_deck)
from gen_eval import build_week_deck as build_eval_deck


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build one .apkg with SR flashcards + eval MCQs nested per week.")
    ap.add_argument("weeks", help="e.g. '10,24' or '1-28'")
    ap.add_argument("--lang", default="da", help="target language code (da, ta, ml, fr, ...). Default da.")
    ap.add_argument("--out", default="deck", help="output dir (default: deck/)")
    ap.add_argument("--curriculum", default=None,
                    help="grammar curriculum (default: curriculum_<lang>.md if it exists). Drives cloze + "
                         "eval; without one, both are skipped (vocab/production/comprehension only).")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-prod-per-scene", type=int, default=5, dest="max_prod")
    ap.add_argument("--max-vocab-per-scene", type=int, default=5, dest="max_vocab")
    ap.add_argument("--per-week", type=int, default=8, dest="n_eval",
                    help="eval MCQs to generate per week before verify (default 8)")
    ap.add_argument("--no-eval", action="store_true", help="SR flashcards only (skip the eval subdeck)")
    ap.add_argument("--audio", action="store_true",
                    help="attach audio (flashcards + the correct-answer voicing on eval backs)")
    a = ap.parse_args(argv)

    nums = sorted({n for part in a.weeks.split(",") for n in (
        range(int(part.split("-")[0]), int(part.split("-")[1]) + 1) if "-" in part else [int(part)])})
    cur_path = ROOT / (a.curriculum or f"curriculum_{a.lang}.md")
    have_curriculum = cur_path.exists()      # gates cloze + eval (need a grammar focus)
    if not have_curriculum:
        print(f"  [{a.lang}] no curriculum_{a.lang}.md — cloze + eval skipped "
              f"(vocab/production/comprehension only)")
    client = make_client()
    cache = ClipCache(GoogleTTS(voices=VOICE_OVERRIDES, speed=DECK_SPEED), str(CLIP_DIR)) if a.audio else None

    decks, media = [], {}          # media shared across both generators -> a clip is packaged once
    n_sr = n_eval = 0
    for w in nums:
        wdir = ROOT / f"year1/week{w:02d}"
        if not (wdir / "storyboard.md").exists():
            print(f"  week{w:02d}: no storyboard — skipped")
            continue
        level, grammar = curriculum_fields(w, cur_path) if have_curriculum else ("", "")
        sr = build_sr_deck(client, a.model, w, wdir, lang=a.lang, level=level, grammar=grammar,
                           use_llm=True, max_prod=a.max_prod, max_vocab=a.max_vocab,
                           cache=cache, media=media)
        decks.append(sr)
        n_sr += len(sr.notes)
        if not a.no_eval and have_curriculum:     # eval needs the grammar focus → curriculum languages only
            ev = build_eval_deck(client, a.model, w, wdir, level=level, grammar=grammar,
                                 n=a.n_eval, cache=cache, media=media)
            decks.append(ev)
            n_eval += len(ev.notes)

    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    span = f"weeks{nums[0]:02d}-{nums[-1]:02d}" if len(nums) > 1 else f"week{nums[0]:02d}"
    out_path = out_dir / f"{span}_all_{a.lang}.apkg"
    genanki.Package(decks, media_files=[str(p) for p in media.values()]).write_to_file(str(out_path))
    aud = f", {len(media)} audio clips" if a.audio else ""
    print(f"-> {out_path}  ({n_sr} flashcards + {n_eval} eval MCQs across {len(nums)} week(s){aud})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
