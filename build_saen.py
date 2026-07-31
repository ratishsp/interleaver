"""Interleave a week's Sanskrit line-wavs (from Gefion indic-parler) with an English
gloss (Google Chirp3-HD) into one da/en-style track: each line is Sanskrit (L2), a
short pause, then the English meaning, a longer pause.

  build_saen.py <weekdir> <sa_wav_dir> [out.mp3] [--en-first]

<sa_wav_dir> holds <stem>__<i:02d>.wav (one per line) from synth_week_sa.py. Scene
order + line count come from the .en files (the storyboard arc). Sanskrit has no
Google voice, so the L2 audio is the pre-rendered wav; only the English gloss is synthesised here.
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

from pydub import AudioSegment
from google.cloud import texttospeech as tts

from tandem.gen import parse_storyboard

EN_VOICE = "en-US-Chirp3-HD-Sulafat"
INNER = AudioSegment.silent(duration=700)    # Sanskrit -> English gap
OUTER = AudioSegment.silent(duration=1100)   # between lines (A1 breathing room)
TARGET_DBFS = -18.0    # the parler Sanskrit wavs come out quieter than Google's English;
                       # normalise both to one loudness so the ear doesn't lurch between them

_client = tts.TextToSpeechClient()
_cache = None   # ClipCache, so the English clips synthesize once and both directions reuse them


def _norm(seg: AudioSegment) -> AudioSegment:
    return seg if seg.dBFS == float("-inf") else seg.apply_gain(TARGET_DBFS - seg.dBFS)


def synth_en(text: str) -> AudioSegment:
    global _cache
    if _cache is None:
        from tandem.cache import ClipCache
        from tandem.tts import GoogleTTS
        _cache = ClipCache(GoogleTTS(voices={"en": EN_VOICE}, speed={"en": 1.0}), "cache/clips")
    return AudioSegment.from_file(_cache.clip(text, "en"))


def main() -> int:
    en_first = "--en-first" in sys.argv
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    weekdir = Path(argv[0])
    sa_dir = Path(argv[1])
    out = argv[2] if len(argv) > 2 else str(weekdir / "audio_saen.mp3")

    rows = parse_storyboard(weekdir / "storyboard.md")
    full = AudioSegment.empty()
    n_lines = 0
    for r in rows:
        stem = r["stem"]
        en_path = weekdir / f"{stem}.en"
        if not en_path.exists():
            print(f"  [skip] {stem}: no .en")
            continue
        en_lines = [l for l in en_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        scene = AudioSegment.empty()
        for i, en in enumerate(en_lines):
            sa_wav = sa_dir / f"{stem}__{i:02d}.wav"
            if not sa_wav.exists():
                print(f"  [warn] {stem} line {i}: missing sa wav — skipped")
                continue
            sa_seg, en_seg = _norm(AudioSegment.from_wav(sa_wav)), _norm(synth_en(en))
            first, second = (en_seg, sa_seg) if en_first else (sa_seg, en_seg)
            scene += first + INNER + second + OUTER
            n_lines += 1
        full += scene
        print(f"  [ok] {stem}: {len(en_lines)} lines", flush=True)
    full.export(out, format="mp3")
    print(f"\nDONE: {n_lines} lines -> {out}  ({len(full)/60000:.1f} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
