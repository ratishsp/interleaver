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

    def voice_id(self, lang: str) -> str:
        """Stable descriptor (engine+voice+rate) used as the clip-cache key.

        Two configs that would produce the same audio must return the same id;
        anything that changes the audio (voice, rate, engine) must change it.
        """
        ...


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
        "sv": "sv-SE-SofieNeural",
        "bn": "bn-IN-TanishaaNeural",
        "ur": "ur-IN-GulNeural",
    }

    def __init__(self, voices: dict[str, str] | None = None, rate: str = "+0%"):
        self.voices = {**self.DEFAULT_VOICES, **(voices or {})}
        self.rate = rate  # edge-tts rate string, e.g. "-25%" for 75% speed

    def voice_id(self, lang: str) -> str:
        voice = self.voices.get(lang)
        if voice is None:
            raise ValueError(f"No voice configured for language {lang!r}")
        return f"edge:{voice}:{self.rate}"

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


class GoogleTTS:
    """Google Cloud Text-to-Speech — Chirp 3 HD voices.

    Grant-funded (the texttospeech SKU) and grants clean redistribution rights, unlike edge-tts —
    so this is the production voice for the public release. Drops into the same Engine protocol, so
    the clip cache treats it as a different voice_id (cache miss) and re-synths only what's needed.
    Speed is `speaking_rate` (0.25–4.0), a native prosody change — not a post-hoc time-stretch.
    """

    DEFAULT_VOICES = {
        # Chirp 3 HD voice names look like "<locale>-Chirp3-HD-<Speaker>"; confirmed/adjusted via
        # client.list_voices(). Maya narrates first-person, so female voices.
        "da": "da-DK-Chirp3-HD-Aoede",
        "en": "en-US-Chirp3-HD-Aoede",
        "es": "es-ES-Chirp3-HD-Aoede",
        "sv": "sv-SE-Chirp3-HD-Aoede",
        "hi": "hi-IN-Chirp3-HD-Aoede",
        "ta": "ta-IN-Chirp3-HD-Aoede",
        "ml": "ml-IN-Chirp3-HD-Aoede",
        "bn": "bn-IN-Chirp3-HD-Aoede",
        "gu": "gu-IN-Chirp3-HD-Aoede", "kn": "kn-IN-Chirp3-HD-Aoede", "mr": "mr-IN-Chirp3-HD-Aoede",
        "pa": "pa-IN-Chirp3-HD-Aoede", "te": "te-IN-Chirp3-HD-Aoede", "ur": "ur-IN-Chirp3-HD-Aoede",
        "fr": "fr-FR-Chirp3-HD-Aoede", "de": "de-DE-Chirp3-HD-Aoede", "it": "it-IT-Chirp3-HD-Aoede",
        "pt": "pt-BR-Chirp3-HD-Aoede", "ru": "ru-RU-Chirp3-HD-Aoede", "ar": "ar-XA-Chirp3-HD-Aoede",
        "cmn": "cmn-CN-Chirp3-HD-Aoede", "ja": "ja-JP-Chirp3-HD-Aoede", "ko": "ko-KR-Chirp3-HD-Aoede",
    }

    def __init__(self, voices: dict[str, str] | None = None,
                 speed: float | dict[str, float] = 1.0):
        self.voices = {**self.DEFAULT_VOICES, **(voices or {})}
        # speaking_rate, 1.0 = natural. A float applies to every language; a dict
        # sets it per language, e.g. {"da": 0.9, "en": 1.0} to slow only the L2.
        self.speed = speed
        self._client = None

    def _speed(self, lang: str) -> float:
        return self.speed.get(lang, 1.0) if isinstance(self.speed, dict) else self.speed

    def _get_client(self):
        if self._client is None:
            from google.cloud import texttospeech as tts
            self._client = tts.TextToSpeechClient()
        return self._client

    def voice_id(self, lang: str) -> str:
        voice = self.voices.get(lang)
        if voice is None:
            raise ValueError(f"No voice configured for language {lang!r}")
        return f"google:{voice}:{self._speed(lang)}"

    def synth(self, text: str, lang: str, out_path: Path, retries: int = 4) -> None:
        import time

        from google.cloud import texttospeech as tts

        voice_name = self.voices.get(lang)
        if voice_name is None:
            raise ValueError(f"No voice configured for language {lang!r}")
        lang_code = "-".join(voice_name.split("-")[:2])  # "da-DK-Chirp3-HD-Aoede" -> "da-DK"

        client = self._get_client()
        synth_input = tts.SynthesisInput(text=text)
        voice = tts.VoiceSelectionParams(language_code=lang_code, name=voice_name)
        audio_config = tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3,
                                       speaking_rate=self._speed(lang))

        last_exc = None
        for attempt in range(retries):
            try:
                resp = client.synthesize_speech(input=synth_input, voice=voice,
                                                audio_config=audio_config)
                out_path.write_bytes(resp.audio_content)
                return
            except Exception as exc:  # noqa: BLE001 - retry transient API errors
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
    if name in ("google", "gcp", "chirp"):
        return GoogleTTS(**kwargs)
    raise ValueError(f"Unknown TTS engine: {name!r}")
