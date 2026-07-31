"""Synthesize a week's Sanskrit (.sa) lines with ai4bharat/indic-parler-tts —
one wav PER LINE (so the caller can interleave each line with an English gloss).

  synth_week_sa.py <weekdir> <out_dir>

Reads every *.sa in <weekdir>; for scene stem S with lines 0..n, writes
<out_dir>/S__00.wav, S__01.wav, … at the model's sampling rate. Reuses the Gita
setup (indic-parler is a genuinely trained Sanskrit voice); only the DESCRIPTION
changes from devotional recitation to a calm language-course narrator.
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer

MODEL = "ai4bharat/indic-parler-tts"
DESCRIPTION = (
    "A female speaker narrates in a clear, calm, friendly voice at a natural, "
    "gentle pace, as in a language-learning audio lesson. Very clear, "
    "high-quality audio with no background noise."
)


def main():
    weekdir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"device={device}", flush=True)

    model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL).to(device)
    tok = AutoTokenizer.from_pretrained(MODEL)
    desc_tok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
    sr = model.config.sampling_rate
    desc = desc_tok(DESCRIPTION, return_tensors="pt").to(device)

    for sa_path in sorted(weekdir.glob("*.sa")):
        stem = sa_path.stem
        lines = [l.strip() for l in sa_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for i, line in enumerate(lines):
            p = tok(line, return_tensors="pt").to(device)
            audio = np.zeros(0, dtype=np.float32)
            for attempt in (1, 2, 3):
                with torch.no_grad():
                    gen = model.generate(
                        input_ids=desc.input_ids, attention_mask=desc.attention_mask,
                        prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask,
                    )
                audio = np.atleast_1d(gen.cpu().numpy().squeeze().astype(np.float32))
                if audio.size > 3 * sr // 10:      # >0.1s: the model sometimes emits empty audio
                    break
                print(f"  [retry {attempt}] {stem} [{i:02d}] empty output", flush=True)
            if audio.size <= 3 * sr // 10:
                audio = np.zeros(sr // 2, dtype=np.float32)   # 0.5s silence placeholder
                print(f"  [WARN] {stem} [{i:02d}] silent after 3 attempts: {line[:44]}", flush=True)
            sf.write(out_dir / f"{stem}__{i:02d}.wav", audio, sr)
            print(f"  {stem} [{i:02d}] {line[:44]}", flush=True)
        print(f"[done] {stem}: {len(lines)} lines", flush=True)
    print(f"DONE: sampling_rate={sr}", flush=True)


if __name__ == "__main__":
    main()
