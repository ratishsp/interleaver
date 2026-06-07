"""Stage 4a — text-to-speech, behind a small pluggable interface.

Default engine is `edge-tts` (Microsoft Edge neural voices): free, no API key,
good Danish quality. The Engine protocol lets us drop in Piper (offline) or
Azure later without changing the caller.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol


class Engine(Protocol):
    def synth(self, text: str, lang: str, out_path: Path) -> None: ...


class EdgeTTS:
    """Microsoft Edge online neural voices."""

    DEFAULT_VOICES = {
        "da": "da-DK-ChristelNeural",
        "en": "en-US-AriaNeural",
        "ta": "ta-IN-PallaviNeural",
        "ml": "ml-IN-SobhanaNeural",
        "hi": "hi-IN-SwaraNeural",
        # Sanskrit has no native neural voice. Marathi reads Devanagari without
        # Hindi's schwa-deletion, so it pronounces Sanskrit closest to "as written"
        # (good for vocab/sentences; NOT accurate for Vedic chanting).
        "sa": "mr-IN-AarohiNeural",
        "mr": "mr-IN-AarohiNeural",
        "de": "de-DE-KatjaNeural",
        "fr": "fr-FR-DeniseNeural",
        "es": "es-ES-ElviraNeural",
    }

    def __init__(self, voices: dict[str, str] | None = None, rate: str = "+0%"):
        self.voices = {**self.DEFAULT_VOICES, **(voices or {})}
        self.rate = rate  # edge-tts rate string, e.g. "-25%" for 75% speed

    def synth(self, text: str, lang: str, out_path: Path, retries: int = 4) -> None:
        import time

        import edge_tts

        voice = self.voices.get(lang)
        if voice is None:
            raise ValueError(f"No voice configured for language {lang!r}")

        async def _run():
            await edge_tts.Communicate(text, voice, rate=self.rate).save(str(out_path))

        # edge-tts intermittently returns NoAudioReceived on transient server
        # hiccups; retry a few times before giving up so one blip doesn't kill
        # a whole long render.
        last_exc = None
        for attempt in range(retries):
            try:
                asyncio.run(_run())
                return
            except Exception as exc:  # noqa: BLE001 - retry any synth failure
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        raise last_exc


def speed_to_rate(speed: float) -> str:
    """Convert a speed multiplier (0.75 = 75%) to an edge-tts rate string ('-25%')."""
    pct = round((speed - 1.0) * 100)
    return f"{pct:+d}%"


def get_engine(name: str = "edge", **kwargs) -> Engine:
    if name == "edge":
        return EdgeTTS(**kwargs)
    raise ValueError(f"Unknown TTS engine: {name!r}")
