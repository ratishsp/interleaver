"""Synthesize Sanskrit verses with ai4bharat/indic-parler-tts (a genuinely
trained Sanskrit voice). Reads one Devanagari verse per line, writes one wav
per verse plus a concatenated wav. Run on a GPU node.

Usage:
    python synth_gita.py <verses.txt> <out_dir>
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer

MODEL = "ai4bharat/indic-parler-tts"
# Voice/style is controlled by this natural-language description.
DESCRIPTION = (
    "A female speaker recites the verse slowly and clearly in a calm, "
    "devotional tone, with natural pacing. Very clear, high-quality audio "
    "with no background noise."
)

def main():
    verses_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"device={device}", flush=True)

    model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL).to(device)
    tok = AutoTokenizer.from_pretrained(MODEL)
    desc_tok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
    sr = model.config.sampling_rate

    desc = desc_tok(DESCRIPTION, return_tensors="pt").to(device)
    verses = [l.strip() for l in verses_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    pause = np.zeros(int(sr * 0.8), dtype=np.float32)  # 0.8s between verses
    pieces = []
    for i, verse in enumerate(verses, 1):
        print(f"[{i}/{len(verses)}] {verse[:50]}...", flush=True)
        p = tok(verse, return_tensors="pt").to(device)
        with torch.no_grad():
            gen = model.generate(
                input_ids=desc.input_ids, attention_mask=desc.attention_mask,
                prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask,
            )
        audio = gen.cpu().numpy().squeeze().astype(np.float32)
        sf.write(out_dir / f"verse_{i:02d}.wav", audio, sr)
        pieces.append(audio)
        pieces.append(pause)

    full = np.concatenate(pieces)
    sf.write(out_dir / "gita_sanskrit_all.wav", full, sr)
    print(f"DONE: wrote {len(verses)} verses + gita_sanskrit_all.wav to {out_dir}", flush=True)

if __name__ == "__main__":
    main()
