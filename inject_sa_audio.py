"""Inject [sound:] audio into the existing sa apkg without touching GUIDs/content.

  inject_sa_audio.py <workdir>   (workdir per deck/MAINTENANCE.md)

Field placement mirrors gen_deck: production -> L2 field; comprehension/vocab-fwd
-> field 0 (L2); vocab-rev -> field 1 (L2); cloze -> Back Extra (answer side),
keyed by the unblanked sentence. Line clips from the deck/sa_clips dir (already
mp3); vocab word clips from the Gefion vocab wavs (converted here).
Writes deck/weeks01-28_sa_audio.apkg (the original stays untouched).
"""
import hashlib
import json
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

from pydub import AudioSegment

LL = Path.home() / "project/self/language-learning"
S = Path(sys.argv[1])   # workdir: extracted collection.anki2 + line_texts.txt + line_clip_map.json
SEP = "\x1f"
DEV = re.compile(r"[ऀ-ॿ]")

def dev_ratio(s):
    letters = [c for c in s if c.strip()]
    return sum(1 for c in letters if DEV.match(c)) / max(1, len(letters))

def norm(t):
    return t.strip().strip('"“”')

# --- audio sources ------------------------------------------------------------
line_map = json.loads((S / "sa_apkg/line_clip_map.json").read_text(encoding="utf-8"))
clipdir = LL / "deck/sa_clips"

# vocab: words file line i  <->  vocab__{i:02d}.wav (synth order == file order)
vocab_words = (LL / "gefion/sa_vocab/vocab.sa").read_text(encoding="utf-8").splitlines()
vocab_wavdir = LL / "combined/gefion_sa_fix/vocab"
word_map = {}
for i, w in enumerate(vocab_words):
    wav = vocab_wavdir / f"vocab__{i:02d}.wav"
    if not wav.exists():
        continue
    name = "saw_" + hashlib.sha1(w.encode()).hexdigest()[:16] + ".mp3"
    out = clipdir / name
    if not out.exists():
        seg = AudioSegment.from_wav(wav).set_channels(1)
        if seg.dBFS != float("-inf"):
            seg = seg.apply_gain(-18.0 - seg.dBFS)
        seg.export(out, format="mp3", bitrate="32k")
    word_map[w.strip()] = name

# --- rewrite the collection ---------------------------------------------------
work = S / "sa_apkg"
db = sqlite3.connect(work / "collection.anki2")
rows = db.execute("select id, flds, tags from notes").fetchall()
used, stats = {}, {"production": 0, "comprehension": 0, "vocab": 0, "cloze": 0, "miss": 0}
for nid, flds, tags in rows:
    f = flds.split(SEP)
    tagset = tags.split()
    snd = None
    if "cloze" in tagset:
        source = norm(re.sub(r"\{\{c\d+::(.+?)(::[^}]*)?\}\}", r"\1", f[0]))
        snd = line_map.get(source)
        target = 1
        kind = "cloze"
    elif "production" in tagset or "comprehension" in tagset:
        target = max(range(2), key=lambda i: dev_ratio(f[i]))
        snd = line_map.get(norm(f[target]))
        kind = "production" if "production" in tagset else "comprehension"
    elif "vocab" in tagset:
        target = max(range(2), key=lambda i: dev_ratio(f[i]))
        head = f[target].split(" (")[0].strip()
        snd = word_map.get(head)
        kind = "vocab"
    else:
        continue
    if not snd or "[sound:" in f[target]:
        stats["miss"] += snd is None
        continue
    f[target] = f"{f[target]} [sound:{snd}]"
    db.execute("update notes set flds=?, mod=mod+1 where id=?", (SEP.join(f), nid))
    used[snd] = clipdir / snd
    stats[kind] += 1
db.commit()
db.close()

# --- package ------------------------------------------------------------------
out_apkg = LL / "deck/weeks01-28_sa_audio.apkg"
manifest = {str(i): name for i, name in enumerate(sorted(used))}
with zipfile.ZipFile(out_apkg, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(work / "collection.anki2", "collection.anki2")
    z.writestr("media", json.dumps(manifest))
    for i, name in manifest.items():
        z.write(used[name], i)
print(f"cards with audio: {stats}; media files: {len(used)}")
print(f"-> {out_apkg} ({out_apkg.stat().st_size/1e6:.1f} MB)")
