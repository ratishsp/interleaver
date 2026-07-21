"""Combine a range of weeks into two phone-ready MP3s for a language pair, both interleave directions.

src is the L2 (the language being learned), tgt is the L1 gloss. Produces:
  weeks01-08_<tgt>-then-<src>.mp3   (gloss first — recall practice)
  weeks01-08_<src>-then-<tgt>.mp3   (target first — comprehension)
Reuses the persistent clip cache (per-week audio already voiced every line), so no new TTS.
Run:  set -a; . ./.env; set +a;  .venv/bin/python combine_all.py --src ml --tgt ta
"""
from __future__ import annotations
import argparse
from pathlib import Path

from pydub import AudioSegment

from tandem.build import BuildConfig, build_audio
from tandem.tts import GoogleTTS
from tandem.gen import parse_storyboard

LANG_LOCALE = {"da": "da-DK", "en": "en-US", "ml": "ml-IN", "ta": "ta-IN"}
LANG_NAME = {"da": "danish", "en": "english", "ml": "malayalam", "ta": "tamil"}
GAP_SCENE = AudioSegment.silent(duration=1500)
GAP_WEEK = AudioSegment.silent(duration=2500)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default="da", help="L2, the language being learned")
    ap.add_argument("--tgt", default="en", help="L1 gloss")
    ap.add_argument("--speaker", default="Sulafat")
    ap.add_argument("--out", default="combined")
    ap.add_argument("--weeks", default="1-8", help="e.g. '1-8' (default) or '1,4,7'")
    ap.add_argument("--direction", default="both", choices=["both", "src-first", "tgt-first"],
                    help="which interleave to build: 'both' (default), 'src-first' (L2 first, e.g. da-then-en), "
                         "or 'tgt-first' (gloss first)")
    a = ap.parse_args()
    src, tgt = a.src, a.tgt

    nums = sorted({n for part in a.weeks.split(",") for n in (
        range(int(part.split("-")[0]), int(part.split("-")[1]) + 1) if "-" in part else [int(part)])})
    weeks = [Path(f"year1/week{w:02d}") for w in nums]
    span = f"weeks{nums[0]:02d}-{nums[-1]:02d}"
    out_dir = Path(a.out)
    scratch = out_dir / "_scenes"
    scratch.mkdir(parents=True, exist_ok=True)

    engine = GoogleTTS(
        voices={src: f"{LANG_LOCALE[src]}-Chirp3-HD-{a.speaker}",
                tgt: f"{LANG_LOCALE[tgt]}-Chirp3-HD-{a.speaker}"},
        speed={src: 1.0, tgt: 1.0})

    directions = [
        (f"{span}_{LANG_NAME[tgt]}-then-{LANG_NAME[src]}.mp3", False),  # gloss (L1) first
        (f"{span}_{LANG_NAME[src]}-then-{LANG_NAME[tgt]}.mp3", True),   # target (L2) first
    ]
    if a.direction == "src-first":
        directions = [d for d in directions if d[1]]
    elif a.direction == "tgt-first":
        directions = [d for d in directions if not d[1]]

    for fname, src_first in directions:
        cfg = BuildConfig(src_lang=src, tgt_lang=tgt, src_first=src_first,
                          gap_inner_ms=700, gap_outer_ms=1100, cache_dir="cache/clips")
        print(f"\n=== {fname}  (src_first={src_first}) ===")
        combined = AudioSegment.empty()
        for wk in weeks:
            for r in parse_storyboard(wk / "storyboard.md"):
                stem = r["stem"]
                s, t = wk / f"{stem}.{src}", wk / f"{stem}.{tgt}"
                if not (s.exists() and t.exists()):
                    print(f"  [skip] {wk.name}/{stem}: missing .{src}/.{tgt}")
                    continue
                order = f"{src}{tgt}" if src_first else f"{tgt}{src}"
                scene_mp3 = scratch / f"{wk.name}_{stem}_{order}.mp3"
                build_audio(str(s), str(t), str(scene_mp3), config=cfg, engine=engine,
                            pre_aligned=True)
                combined += AudioSegment.from_file(scene_mp3) + GAP_SCENE
            combined += GAP_WEEK
            print(f"  {wk.name}: added ({len(combined) // 1000}s so far)")
        out_path = out_dir / fname
        combined.export(out_path, format="mp3")
        print(f"  -> {out_path}  ({len(combined) / 60000:.1f} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
