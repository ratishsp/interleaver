"""Interleave a week's Sanskrit line-wavs (from Gefion indic-parler) with an English
gloss (Google Chirp3-HD) into one da/en-style track: each line is Sanskrit (L2), a
short pause, then the English meaning, a longer pause.

  build_saen.py <weekdir> <sa_wav_dir> [out.mp3]

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


def _norm(seg: AudioSegment) -> AudioSegment:
    return seg if seg.dBFS == float("-inf") else seg.apply_gain(TARGET_DBFS - seg.dBFS)


def synth_en(text: str) -> AudioSegment:
    r = _client.synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=tts.VoiceSelectionParams(language_code="en-US", name=EN_VOICE),
        audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3),
    )
    return AudioSegment.from_file(io.BytesIO(r.audio_content), format="mp3")


def main() -> int:
    weekdir = Path(sys.argv[1])
    sa_dir = Path(sys.argv[2])
    out = sys.argv[3] if len(sys.argv) > 3 else str(weekdir / "audio_saen.mp3")

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
            scene += _norm(AudioSegment.from_wav(sa_wav)) + INNER + _norm(synth_en(en)) + OUTER
            n_lines += 1
        scene.export(str(weekdir / f"{stem}_saen.mp3"), format="mp3")
        full += scene
        print(f"  [ok] {stem}: {len(en_lines)} lines", flush=True)
    full.export(out, format="mp3")
    print(f"\nDONE: {n_lines} lines -> {out}  ({len(full)/60000:.1f} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
