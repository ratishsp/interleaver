"""Command-line entry point:  python -m tandem L2.epub L1.epub -o chapter.mp3"""
from __future__ import annotations

import argparse
import sys

from .build import BuildConfig, build_audio
from .tts import get_engine, speed_to_rate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tandem",
        description="Align a book pair and produce interleaved bilingual audio.",
    )
    p.add_argument("src_file", help="L2 book — the language you're learning (.txt/.epub/.pdf)")
    p.add_argument("tgt_file", help="L1 book — your known language (.txt/.epub/.pdf)")
    p.add_argument("-o", "--out", default="chapter.mp3", help="output MP3 path")
    p.add_argument("--src-lang", default="da", help="L2 language code (default: da)")
    p.add_argument("--tgt-lang", default="en", help="L1 language code (default: en)")
    p.add_argument("--method", choices=["length", "embed"], default="length",
                   help="alignment method (default: length; 'embed' needs sentence-transformers)")
    p.add_argument("--l1-first", action="store_true", help="speak L1 before L2 (default: L2 first)")
    p.add_argument("--gap-inner", type=int, default=600, help="ms pause between the two languages")
    p.add_argument("--gap-outer", type=int, default=1000, help="ms pause between beads")
    p.add_argument("--transcript", help="also write a side-by-side alignment transcript here")
    p.add_argument("--pre-aligned", action="store_true",
                   help="inputs are already line-for-line aligned (e.g. an OPUS Moses pair); skip alignment")
    p.add_argument("--limit", type=int, default=None, help="only use the first N beads (handy for samples)")
    p.add_argument("--speed", type=float, default=1.0,
                   help="speech speed multiplier (e.g. 0.75 = 75%% speed, slower; 1.0 = normal)")
    p.add_argument("--cache-dir", default="cache/clips",
                   help="persistent clip cache dir (clips reused across pairs; default: cache/clips)")
    p.add_argument("--engine", choices=["edge", "google"], default="edge",
                   help="TTS engine: 'edge' (free) or 'google' (Chirp 3 HD, grant-funded)")
    args = p.parse_args(argv)

    cfg = BuildConfig(
        src_lang=args.src_lang,
        tgt_lang=args.tgt_lang,
        method=args.method,
        src_first=not args.l1_first,
        gap_inner_ms=args.gap_inner,
        gap_outer_ms=args.gap_outer,
        cache_dir=args.cache_dir,
    )
    if args.engine == "google":
        engine = get_engine("google", speed=args.speed)
    else:
        engine = get_engine("edge", rate=speed_to_rate(args.speed))
    beads = build_audio(
        args.src_file, args.tgt_file, args.out,
        config=cfg, engine=engine, transcript_path=args.transcript,
        pre_aligned=args.pre_aligned, limit=args.limit,
    )
    print(f"Wrote {args.out} from {len(beads)} aligned beads.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
