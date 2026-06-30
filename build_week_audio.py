"""Assemble a week's scenes into interleaved audio with Chirp 3 HD.

Maya (the L2, Danish) and the English gloss get DISTINCT voices so the ear separates L1 from L2.
Builds TWO renders per week: a natural pass (audio/) and a slow pass (audio_slow/) that slows ONLY
the Danish (L2) to 0.75x. The English gloss stays at 1.0 in both, so its clips are shared via the
cache and only the slow-Danish clips are newly synthesised. Extra gentleness also comes from the gaps.
Run:  set -a; . ./.env; set +a;  .venv/bin/python build_week_audio.py
"""
from __future__ import annotations
import sys
from pathlib import Path

from google.cloud import texttospeech as tts
from tandem.build import BuildConfig, build_audio
from tandem.tts import GoogleTTS
from tandem.gen import parse_storyboard

# Week directory may be passed as the first CLI arg; defaults to week 1.
# Pass --natural-only to build just the natural-speed render (skip audio_slow/).
_argv = sys.argv[1:]
NATURAL_ONLY = "--natural-only" in _argv
_pos = [a for a in _argv if not a.startswith("--")]
WEEKDIR = Path(_pos[0]) if _pos else Path("year1/week01")
SPEAKER = "Sulafat"                       # chosen for Maya — warm, clear female voice
MAYA_DA = f"da-DK-Chirp3-HD-{SPEAKER}"    # the learner's L2 voice (Maya)

# Same speaker for the English gloss -> one consistent first-person narrator.
_c = tts.TextToSpeechClient()
en_voices = {v.name for v in _c.list_voices(language_code="en-US").voices}
GLOSS_EN = (f"en-US-Chirp3-HD-{SPEAKER}" if f"en-US-Chirp3-HD-{SPEAKER}" in en_voices
            else "en-US-Chirp3-HD-Aoede")
print(f"Maya (da) = {MAYA_DA}\nEnglish gloss = {GLOSS_EN}\n")

# Two renders: a natural pass, and a slow pass that slows ONLY the Danish (L2). English stays
# at 1.0 in both, so its clips are shared via the cache — only the slow-Danish clips re-synth.
VERSIONS = [
    ("audio",      {"da": 1.0,  "en": 1.0}),   # natural
    ("audio_slow", {"da": 0.75, "en": 1.0}),   # slow Danish for the beginner ear
]
if NATURAL_ONLY:
    VERSIONS = VERSIONS[:1]

rows = parse_storyboard(WEEKDIR / "storyboard.md")
for subdir, speed in VERSIONS:
    out = WEEKDIR / subdir
    out.mkdir(parents=True, exist_ok=True)
    engine = GoogleTTS(voices={"da": MAYA_DA, "en": GLOSS_EN}, speed=speed)
    cfg = BuildConfig(
        src_lang="da", tgt_lang="en",
        src_first=False,        # English (L1) first, then Danish (L2) — meaning, then target
        gap_inner_ms=700,       # pause between the two languages
        gap_outer_ms=1100,      # pause between sentences (A1 breathing room)
        cache_dir="cache/clips",
    )
    print(f"=== {subdir}: Danish {speed['da']}x · English {speed['en']}x ===")
    for r in rows:
        stem = r["stem"]
        da, en = WEEKDIR / f"{stem}.da", WEEKDIR / f"{stem}.en"
        if not (da.exists() and en.exists()):
            print(f"  [skip] {stem}: missing .da/.en")
            continue
        beads = build_audio(str(da), str(en), str(out / f"{stem}.mp3"),
                            config=cfg, engine=engine,
                            transcript_path=str(out / f"{stem}.txt"), pre_aligned=True)
        print(f"  [ok] {stem}: {len(beads)} beads -> {out / (stem + '.mp3')}", flush=True)

print("\nDone. Natural → audio/, slow → audio_slow/ under", WEEKDIR)
