"""English-only audio for a week: just the .en lines read straight through.

  build_en.py <weekdir> [out.mp3]

Scene order comes from the storyboard; voice/loudness match the course tracks
(Chirp3-HD Sulafat, -18 dBFS, 1.1s between lines).
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

from pydub import AudioSegment
from google.cloud import texttospeech as tts

from tandem.gen import parse_storyboard

EN_VOICE = "en-US-Chirp3-HD-Sulafat"
OUTER = AudioSegment.silent(duration=1100)
TARGET_DBFS = -18.0

_client = tts.TextToSpeechClient()


def _synth(text: str) -> AudioSegment:
    r = _client.synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=tts.VoiceSelectionParams(language_code="en-US", name=EN_VOICE),
        audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3),
    )
    s = AudioSegment.from_file(io.BytesIO(r.audio_content), format="mp3")
    return s if s.dBFS == float("-inf") else s.apply_gain(TARGET_DBFS - s.dBFS)


def main() -> int:
    weekdir = Path(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else str(weekdir / "audio_en.mp3")
    full = AudioSegment.empty()
    n = 0
    for row in parse_storyboard(weekdir / "storyboard.md"):
        en = weekdir / f"{row['stem']}.en"
        if not en.exists():
            print(f"  [skip] {row['stem']}")
            continue
        for line in [l for l in en.read_text(encoding="utf-8").splitlines() if l.strip()]:
            full += _synth(line) + OUTER
            n += 1
        print(f"  [ok] {row['stem']}", flush=True)
    full.export(out, format="mp3")
    print(f"\nDONE: {n} lines, {len(full)/60000:.1f} min -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
