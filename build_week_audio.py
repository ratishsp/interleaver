"""Assemble a week's scenes into interleaved audio with Chirp 3 HD.

Maya (the L2, Danish) and the English gloss get DISTINCT voices so the ear separates L1 from L2.
Natural pace (1.0); beginner-gentleness comes from gaps + the interleaving, not slowed speech.
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
WEEKDIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("year1/week01")
OUT = WEEKDIR / "audio"
SPEED = 1.0
SPEAKER = "Sulafat"                       # chosen for Maya — warm, clear female voice
MAYA_DA = f"da-DK-Chirp3-HD-{SPEAKER}"    # the learner's L2 voice (Maya)

# Same speaker for the English gloss -> one consistent first-person narrator.
_c = tts.TextToSpeechClient()
en_voices = {v.name for v in _c.list_voices(language_code="en-US").voices}
GLOSS_EN = (f"en-US-Chirp3-HD-{SPEAKER}" if f"en-US-Chirp3-HD-{SPEAKER}" in en_voices
            else "en-US-Chirp3-HD-Aoede")
print(f"Maya (da) = {MAYA_DA}\nEnglish gloss = {GLOSS_EN}\n")

engine = GoogleTTS(voices={"da": MAYA_DA, "en": GLOSS_EN}, speed=SPEED)
cfg = BuildConfig(
    src_lang="da", tgt_lang="en",
    src_first=False,        # English (L1) first, then Danish (L2) — meaning, then target
    gap_inner_ms=700,       # pause between the two languages
    gap_outer_ms=1100,      # pause between sentences (A1 breathing room)
    cache_dir="cache/clips",
)

OUT.mkdir(parents=True, exist_ok=True)
rows = parse_storyboard(WEEKDIR / "storyboard.md")
for r in rows:
    stem = r["stem"]
    da, en = WEEKDIR / f"{stem}.da", WEEKDIR / f"{stem}.en"
    if not (da.exists() and en.exists()):
        print(f"  [skip] {stem}: missing .da/.en")
        continue
    beads = build_audio(str(da), str(en), str(OUT / f"{stem}.mp3"),
                        config=cfg, engine=engine,
                        transcript_path=str(OUT / f"{stem}.txt"), pre_aligned=True)
    print(f"  [ok] {stem}: {len(beads)} beads -> {OUT / (stem + '.mp3')}", flush=True)

print("\nDone. Per-scene MP3s in", OUT)
