# tandem

Turn a pair of books — the same text in the language you're learning (L2) and a
language you know (L1) — into a single **interleaved bilingual MP3**: each chunk
is spoken in L2, then L1. Built for passive listening at the gym / commuting.

```
L2 book (e.g. Danish)  ─┐
                        ├─ extract ─ segment ─ align ─ synthesize ─→ chapter.mp3
L1 book (e.g. English) ─┘                                            + transcript.txt
```

## Why alignment matters
Literary translations don't line up 1:1 — translators split, merge, and reorder
sentences. So `tandem` aligns by *meaning*, producing "beads" that can be 1-1,
2-1, 1-2, etc. Two aligners:

| method     | quality | needs                              |
|------------|---------|------------------------------------|
| `length`   | decent  | nothing (pure Python, the default) |
| `embed`    | best    | `sentence-transformers` + LaBSE (~1.8 GB, one-time) |

## Install
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# optional, for the better aligner:
pip install -r requirements-embeddings.txt
```
Requires `ffmpeg` on PATH (used by pydub).

## Use
```bash
python -m tandem danish.epub english.epub -o chapter.mp3 \
    --src-lang da --tgt-lang en --transcript transcript.txt
```
Accepts `.txt`, `.epub`, or `.pdf`. EPUB gives the cleanest text.

Useful flags: `--method embed` (better alignment), `--l1-first`,
`--gap-inner`/`--gap-outer` (pause lengths in ms).

**Always skim the transcript first** — it shows each bead's shape (e.g. `2-1`)
so you can spot misalignments before committing to a long listen.

## Layout
- `extract.py` — file → clean text (.txt/.epub/.pdf)
- `segment.py` — text → sentences (per language)
- `align.py`   — L2/L1 sentences → aligned beads
- `tts.py`     — pluggable TTS (default: free `edge-tts`; Piper/Azure later)
- `build.py`   — orchestrates + assembles the MP3
