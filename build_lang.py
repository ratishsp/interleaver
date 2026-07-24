"""Single-language audio for a week: the .{lang} lines read straight through (no gloss interleave).

  build_lang.py <weekdir> <lang> [out.mp3]

(Supersedes build_en.py — this with lang=en.) Scene order comes from the storyboard; the character
voice is Chirp3-HD Sulafat (Maya) where the locale offers it, else Aoede. Loudness/spacing match the
course tracks (-18 dBFS, 1.1s between lines). Output defaults to <weekdir>/audio_<lang>.mp3.
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

from pydub import AudioSegment
from google.cloud import texttospeech as tts

from tandem.gen import parse_storyboard, parse_storyboard_header
from tandem.langs import LOCALES
from tandem.translate import read_lines

SPEAKER = "Sulafat"                       # Maya's voice, kept across languages where it exists
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


def grammar_intro(weekdir: Path, lang: str) -> str:
    """English announcement spoken before the week: 'Week N. This week's grammar: …'.

    Prefers the curriculum's plain-English 'Grammar in English' column (last column,
    appended so positional parsers of the earlier columns stay valid); falls back to the
    storyboard header's Grammar field. The week's own voice reads it.
    """
    h = parse_storyboard_header(weekdir / "storyboard.md")
    curric = weekdir.parent / f"curriculum_{lang}.md"
    if curric.exists():
        for line in curric.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 6 and cells[0].isdigit() and int(cells[0]) == h["week"]:
                return f"Week {h['week']}. This week's grammar: {cells[5]}"
    g = h["grammar"].replace("**", "").replace("*", "").replace("/", ", ")
    return f"Week {h['week']}. This week's grammar: {g}"


def main() -> int:
    weekdir = Path(sys.argv[1])
    lang = sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else str(weekdir / f"audio_{lang}.mp3")
    locale = LOCALES.get(lang, f"{lang}-{lang.upper()}")
    voice = _voice_for(locale)
    print(f"  {weekdir.name} · {lang} · voice {voice}")
    full = _synth(grammar_intro(weekdir, lang), locale, voice) + OUTER + OUTER
    n = 0
    for row in parse_storyboard(weekdir / "storyboard.md"):
        f = weekdir / f"{row['stem']}.{lang}"
        if not f.exists():
            print(f"  [skip] {row['stem']}")
            continue
        for line in read_lines(f):
            full += _synth(line, locale, voice) + OUTER
            n += 1
        print(f"  [ok] {row['stem']}", flush=True)
    full.export(out, format="mp3")
    print(f"\nDONE: {n} lines, {len(full)/60000:.1f} min -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
