"""Stage 4b — orchestrate the pipeline and assemble the interleaved MP3.

For each aligned bead we speak the L2 text, pause, then the L1 text, pause
(longer). The result is one MP3 you can drop on your phone for the gym.
A side-by-side transcript is written too, so you can eyeball alignment quality.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import align as align_mod
from . import extract, segment
from .tts import Engine, get_engine


@dataclass
class BuildConfig:
    src_lang: str = "da"          # L2 — the language you're learning
    tgt_lang: str = "en"          # L1 — your known language
    method: str = "length"        # 'length' or 'embed'
    src_first: bool = True        # speak L2 then L1 (recommended for learning)
    gap_inner_ms: int = 600       # pause between the two languages of a bead
    gap_outer_ms: int = 1000      # pause after a bead, before the next one
    cache_dir: str = "cache/clips"  # persistent clip cache (reused across pairs)


def build_audio(
    src_file: str | Path,
    tgt_file: str | Path,
    out_mp3: str | Path,
    config: BuildConfig | None = None,
    engine: Engine | None = None,
    transcript_path: str | Path | None = None,
    pre_aligned: bool = False,
    limit: int | None = None,
) -> list[align_mod.Bead]:
    cfg = config or BuildConfig()
    engine = engine or get_engine("edge")
    out_mp3 = Path(out_mp3)

    if pre_aligned:
        # Inputs are already line-for-line aligned (e.g. an OPUS Moses pair),
        # so skip extract/segment/align and just zip the lines into beads.
        beads = load_prealigned(src_file, tgt_file)
    else:
        src_sents = segment.split_sentences(extract.extract_text(src_file), cfg.src_lang)
        tgt_sents = segment.split_sentences(extract.extract_text(tgt_file), cfg.tgt_lang)
        beads = align_mod.align(src_sents, tgt_sents, method=cfg.method)

    if limit is not None:
        beads = beads[:limit]

    if transcript_path:
        _write_transcript(beads, Path(transcript_path))

    _render(beads, out_mp3, cfg, engine)
    return beads


def load_prealigned(src_file: str | Path, tgt_file: str | Path) -> list[align_mod.Bead]:
    """Read two line-aligned files into 1-1 beads (one sentence per line)."""
    src_lines = Path(src_file).read_text(encoding="utf-8").splitlines()
    tgt_lines = Path(tgt_file).read_text(encoding="utf-8").splitlines()
    beads: list[align_mod.Bead] = []
    for s, t in zip(src_lines, tgt_lines):
        s, t = s.strip(), t.strip()
        if not s and not t:
            continue
        beads.append(([s] if s else [], [t] if t else []))
    return beads


# Stage directions like "(Applause)" / "(Latter)" that shouldn't be read aloud.
_STAGE_DIRECTION = re.compile(r"\([^)]*\)")


def _clean_for_tts(text: str) -> str:
    return re.sub(r"\s+", " ", _STAGE_DIRECTION.sub(" ", text)).strip()


def _render(beads, out_mp3: Path, cfg: BuildConfig, engine: Engine) -> None:
    from pydub import AudioSegment

    from .cache import ClipCache

    cache = ClipCache(engine, cfg.cache_dir)
    gap_inner = AudioSegment.silent(duration=cfg.gap_inner_ms)
    gap_outer = AudioSegment.silent(duration=cfg.gap_outer_ms)
    combined = AudioSegment.empty()

    for idx, (src_group, tgt_group) in enumerate(beads):
        src_text = _clean_for_tts(" ".join(src_group))
        tgt_text = _clean_for_tts(" ".join(tgt_group))
        first_text, first_lang = (src_text, cfg.src_lang) if cfg.src_first else (tgt_text, cfg.tgt_lang)
        second_text, second_lang = (tgt_text, cfg.tgt_lang) if cfg.src_first else (src_text, cfg.src_lang)

        for part, (text, lang) in enumerate(((first_text, first_lang), (second_text, second_lang))):
            if not text:
                continue
            try:
                # Cache hit if this exact (voice, rate, text) was ever voiced
                # before — so a language reused across pairs synthesises once.
                clip_path = cache.clip(text, lang)
                combined += AudioSegment.from_file(clip_path)
            except Exception as exc:  # noqa: BLE001
                # A single sentence edge-tts can't voice (after retries)
                # shouldn't sink the whole render — skip it and keep going.
                print(f"  [skip] bead {idx} ({lang}): {type(exc).__name__}: {text[:70]!r}",
                      file=sys.stderr)
            combined += gap_inner if part == 0 else gap_outer

    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    combined.export(out_mp3, format="mp3")
    print(f"  [cache] {cache.misses} synthesised, {cache.hits} reused → {cache.dir}",
          file=sys.stderr)


def _write_transcript(beads, path: Path) -> None:
    lines = []
    for idx, (src_group, tgt_group) in enumerate(beads, 1):
        shape = f"{len(src_group)}-{len(tgt_group)}"
        lines.append(f"[{idx:04d}] ({shape})")
        lines.append(f"  L2: {' '.join(src_group)}")
        lines.append(f"  L1: {' '.join(tgt_group)}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
