"""Content-addressed clip cache — the keystone of the synth/assembly split.

Each spoken clip is keyed by *what determines its audio*: the engine+voice+rate
descriptor (from `engine.voice_id(lang)`) plus the exact text. So:

- Re-using a language across many pairs (Hindi in Hindi->English AND Hindi->Tamil)
  synthesises its clips ONCE; every later pair is a cache hit.
- Flipping order / changing gaps / re-pairing never touches TTS (pure assembly).
- Only a *voice* change (edge -> gemini, or a new rate) changes the key, so only
  then do clips correctly regenerate.

This is what makes "voice once per language, assemble all N^2 pairs for free" real.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .tts import Engine


class ClipCache:
    def __init__(self, engine: Engine, cache_dir: str | Path = "cache/clips") -> None:
        self.engine = engine
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def _key(self, text: str, lang: str) -> str:
        # voice_id encodes engine + voice + rate, so a voice/speed change -> new key.
        descriptor = self.engine.voice_id(lang)
        digest = hashlib.sha256(f"{descriptor}\n{text}".encode("utf-8")).hexdigest()
        return digest[:32]

    def clip(self, text: str, lang: str) -> Path:
        """Return a persistent path to the clip, synthesising it only on a miss."""
        path = self.dir / f"{self._key(text, lang)}.mp3"
        if path.exists():
            self.hits += 1
            return path
        # Synthesise to a temp sibling and atomically rename, so a crash or a
        # failed synth never leaves a half-written clip cached.
        tmp = path.with_suffix(".tmp.mp3")
        self.engine.synth(text, lang, tmp)
        tmp.replace(path)
        self.misses += 1
        return path
