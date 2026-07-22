"""Single-language audio for a week: the .{lang} lines read straight through (no gloss interleave).

  build_lang.py <weekdir> <lang> [out.mp3]

Mirrors build_en.py, parameterized by language. Scene order comes from the storyboard; the character
voice is Chirp3-HD Sulafat (Maya) where the locale offers it, else Aoede. Loudness/spacing match the
course tracks (-18 dBFS, 1.1s between lines). Output defaults to <weekdir>/audio_<lang>.mp3.
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

from pydub import AudioSegment
from google.cloud import texttospeech as tts

from tandem.gen import parse_storyboard

SPEAKER = "Sulafat"                       # Maya's voice, kept across languages where it exists
LOCALES = {"en": "en-US", "da": "da-DK", "hi": "hi-IN", "ta": "ta-IN", "ml": "ml-IN",
           "fr": "fr-FR", "es": "es-ES", "sv": "sv-SE", "bn": "bn-IN",
           "gu": "gu-IN", "kn": "kn-IN", "mr": "mr-IN", "pa": "pa-IN", "te": "te-IN", "ur": "ur-IN",
           "de": "de-DE", "it": "it-IT", "pt": "pt-BR", "ru": "ru-RU", "ar": "ar-XA",
           "cmn": "cmn-CN", "ja": "ja-JP", "ko": "ko-KR"}
OUTER = AudioSegment.silent(duration=1100)
TARGET_DBFS = -18.0

_client = tts.TextToSpeechClient()


def _voice_for(locale: str) -> str:
    want = f"{locale}-Chirp3-HD-{SPEAKER}"
    names = {v.name for v in _client.list_voices(language_code=locale).voices}
    return want if want in names else f"{locale}-Chirp3-HD-Aoede"


def _synth(text: str, locale: str, voice: str) -> AudioSegment:
    r = _client.synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=tts.VoiceSelectionParams(language_code=locale, name=voice),
        audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3),
    )
    s = AudioSegment.from_file(io.BytesIO(r.audio_content), format="mp3")
    return s if s.dBFS == float("-inf") else s.apply_gain(TARGET_DBFS - s.dBFS)


def main() -> int:
    weekdir = Path(sys.argv[1])
    lang = sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else str(weekdir / f"audio_{lang}.mp3")
    locale = LOCALES.get(lang, f"{lang}-{lang.upper()}")
    voice = _voice_for(locale)
    print(f"  {weekdir.name} · {lang} · voice {voice}")
    full = AudioSegment.empty()
    n = 0
    for row in parse_storyboard(weekdir / "storyboard.md"):
        f = weekdir / f"{row['stem']}.{lang}"
        if not f.exists():
            print(f"  [skip] {row['stem']}")
            continue
        for line in [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]:
            full += _synth(line, locale, voice) + OUTER
            n += 1
        print(f"  [ok] {row['stem']}", flush=True)
    full.export(out, format="mp3")
    print(f"\nDONE: {n} lines, {len(full)/60000:.1f} min -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
