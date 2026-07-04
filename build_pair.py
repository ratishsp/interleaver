"""Build interleaved audio for one week in an arbitrary language pair (src spoken first, then tgt).

Reuses the same Chirp 3 HD machinery and clip cache as build_week_audio.py, but parameterised by
language: e.g. Malayalam (L2, learned) first, then Tamil (L1, gloss). One combined MP3 per week.
Run:  set -a; . ./.env; set +a;  .venv/bin/python build_pair.py year1/week01 --src ml --tgt ta
"""
from __future__ import annotations
import argparse
from pathlib import Path

from pydub import AudioSegment

from tandem.build import BuildConfig, build_audio
from tandem.tts import GoogleTTS
from tandem.gen import parse_storyboard

LANG_LOCALE = {"da": "da-DK", "en": "en-US", "ml": "ml-IN", "ta": "ta-IN"}
GAP_SCENE = AudioSegment.silent(duration=1500)


def voice(lang: str, speaker: str) -> str:
    return f"{LANG_LOCALE[lang]}-Chirp3-HD-{speaker}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("weekdir")
    ap.add_argument("--src", default="ml", help="L2, spoken first")
    ap.add_argument("--tgt", default="ta", help="L1 gloss, spoken second")
    ap.add_argument("--speaker", default="Sulafat", help="one Chirp3-HD voice used for both (Maya)")
    ap.add_argument("--out", default=None, help="output mp3 (default: <weekdir>/audio_<src><tgt>.mp3)")
    a = ap.parse_args()
    wk = Path(a.weekdir)

    engine = GoogleTTS(voices={a.src: voice(a.src, a.speaker), a.tgt: voice(a.tgt, a.speaker)},
                       speed={a.src: 1.0, a.tgt: 1.0})
    cfg = BuildConfig(src_lang=a.src, tgt_lang=a.tgt, src_first=True,
                      gap_inner_ms=700, gap_outer_ms=1100, cache_dir="cache/clips")
    out_path = Path(a.out) if a.out else wk / f"audio_{a.src}{a.tgt}.mp3"
    scenes_dir = out_path.parent / "_scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== {wk.name}: {a.src} -> {a.tgt}  (voice {a.speaker}) ===")
    combined = AudioSegment.empty()
    for r in parse_storyboard(wk / "storyboard.md"):
        stem = r["stem"]
        s, t = wk / f"{stem}.{a.src}", wk / f"{stem}.{a.tgt}"
        if not (s.exists() and t.exists()):
            print(f"  [skip] {stem}: missing .{a.src}/.{a.tgt}")
            continue
        scene_mp3 = scenes_dir / f"{wk.name}_{stem}_{a.src}{a.tgt}.mp3"
        build_audio(str(s), str(t), str(scene_mp3), config=cfg, engine=engine, pre_aligned=True)
        combined += AudioSegment.from_file(scene_mp3) + GAP_SCENE
        print(f"  [ok] {stem}")
    combined.export(out_path, format="mp3")
    print(f"  -> {out_path}  ({len(combined) / 60000:.1f} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
