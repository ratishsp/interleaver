"""gen_eval.py — Phase-2 auto-graded eval: Analyze/Evaluate MCQs per week, generate -> verify -> keep.

Unlike the flashcard cloze (whose answer is a real, content-verified word), an MCQ's answer key is
LLM-asserted with no ground truth — and a wrong key in a graded quiz is worse than a bad flashcard
(it marks you wrong when you're right, or teaches a beginner the wrong form). So every item is
adversarially VERIFIED by a second model (the key is right, exactly one option fits, distractors are
unambiguously wrong, an analyze item has exactly one real error) and only survivors are kept.

Cards are plain self-rated MCQ: question + options on the front; answer + explanation (+ optional
audio) on the back. --audio voices the CORRECT Danish on the back — for an analyze item, the
*corrected* sentence — so the audio always models correct Danish.

Run: set -a; . ./.env; set +a; export ALL_PROXY=... ; .venv/bin/python gen_eval.py 10 --out deck --audio
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

import genanki

from tandem.gen import DEFAULT_MODEL, parse_storyboard
from tandem.llm import make_client, _json_call
from tandem.tts import GoogleTTS
from tandem.cache import ClipCache
from gen_deck import curriculum_fields, DA_VOICE, DA_SPEED, CLIP_DIR, TOP, _voice

ROOT = Path(__file__).resolve().parent
EVAL_DECK_BASE = 2_059_500_000

FRONT = """
<div class="q">{{Question}}</div>
<div class="opts">
  <div>A. {{A}}</div>
  <div>B. {{B}}</div>
  {{#C}}<div>C. {{C}}</div>{{/C}}
  {{#D}}<div>D. {{D}}</div>{{/D}}
</div>
"""
BACK = """{{FrontSide}}
<hr>
<div class="answer">Answer: {{Answer}}</div>
<div class="exp">{{Explanation}}</div>
<div class="voiced">{{Correct}} {{Audio}}</div>
<div class="voiced-en">{{CorrectEn}}</div>
"""
CSS = """
.card{font-family:-apple-system,Segoe UI,sans-serif;font-size:18px;text-align:left;
      max-width:600px;margin:0 auto;color:#222}
.q{font-weight:600;margin-bottom:12px}
.opts div{margin:5px 0}
.answer{font-weight:600;color:#2a8a2a;margin-top:6px}
.exp{margin-top:8px;color:#555}
.voiced{margin-top:10px;font-weight:500}
.voiced-en{color:#777;font-weight:400}
@media (prefers-color-scheme:dark){.card{color:#eee}.exp{color:#bbb}.voiced-en{color:#999}}
"""
MODEL = genanki.Model(
    1_607_392_505, "Danish MCQ (eval)",
    fields=[{"name": n} for n in ("Question", "A", "B", "C", "D", "Answer",
                                  "Explanation", "Correct", "CorrectEn", "Audio")],
    templates=[{"name": "MCQ", "qfmt": FRONT, "afmt": BACK}], css=CSS,
)

GEN_PROMPT = """You are writing quiz questions for a Danish course (learner level {level}). Grammar
focus: {grammar}.

Write {n} multiple-choice questions:
- "evaluate": pick the correct form. The options are competing forms.
- "analyze": pick the sentence with an error. The options are full sentences; exactly one has a
  single error in the grammar focus, the rest are correct.

Phrase each question in English; only the options are Danish. Use the scene lines below.

Each item:
{{"kind": "evaluate" | "analyze",
  "question": <the prompt>,
  "options": [3-4 strings],
  "answer": <letter of the option to pick>,
  "correct_da": <the full correct sentence: the blank filled in, or the error corrected>,
  "correct_en": <English translation of correct_da>,
  "explanation": <one line: why>}}

Return JSON {{"items": [...]}}.

Scene lines:
{scene}
"""

VERIFY_PROMPT = """Check this multiple-choice question for a Danish course (grammar focus: {grammar}).
Reject if anything is wrong.

Confirm all of: the labeled answer is correct; exactly one option fits; for an analyze item, exactly
one option has an error and the rest are correct; correct_da is correct.

Item:
{item}

Return JSON {{"ok": true | false, "reason": <short>}}.
"""


def scene_text(wdir: Path) -> str:
    lines = []
    for r in parse_storyboard(wdir / "storyboard.md"):
        da = wdir / f"{r['stem']}.da"
        if da.exists():
            lines += [l for l in da.read_text(encoding="utf-8").splitlines() if l.strip()]
    return "\n".join(lines)


def generate(client, model, *, level, grammar, scene, n):
    prompt = GEN_PROMPT.format(level=level or "A1/A2", grammar=grammar or "(general)", scene=scene, n=n)
    try:
        return _json_call(client, model, prompt, stage="gen_eval.generate").get("items") or []
    except SystemExit:
        return []


def verify(client, model, *, grammar, item) -> bool:
    prompt = VERIFY_PROMPT.format(grammar=grammar or "(general)",
                                  item=json.dumps(item, ensure_ascii=False))
    try:
        return bool(_json_call(client, model, prompt, stage="gen_eval.verify").get("ok"))
    except SystemExit:
        return False


def clean_item(it: dict) -> dict | None:
    """Normalise + sanity-check an item's shape before it's worth verifying."""
    # strip any leading label the model added ("A)", "B.", "c:") — the template adds its own
    opts = [re.sub(r"^\s*[A-Da-d][).:]\s*", "", str(o)).strip()
            for o in (it.get("options") or []) if str(o).strip()]
    ans = str(it.get("answer") or "").strip().upper()[:1]
    letters = "ABCD"[:len(opts)]
    if not (2 <= len(opts) <= 4) or ans not in letters:
        return None
    return {"kind": it.get("kind", "evaluate"), "question": (it.get("question") or "").strip(),
            "options": opts, "answer": ans, "correct_da": (it.get("correct_da") or "").strip(),
            "correct_en": (it.get("correct_en") or "").strip(),
            "explanation": (it.get("explanation") or "").strip()}


def build_week_deck(client, model, week, wdir, *, level, grammar, n, cache, media):
    deck = genanki.Deck(EVAL_DECK_BASE + week, f"{TOP}::Eval::Week {week:02d}")
    tag = f"week{week:02d}"
    raw = generate(client, model, level=level, grammar=grammar, scene=scene_text(wdir), n=n)
    kept = rejected = 0
    for it in raw:
        item = clean_item(it)
        if not item or not verify(client, model, grammar=grammar, item=item):   # generate -> verify -> keep
            rejected += 1
            continue
        kept += 1
        opts = item["options"] + [""] * (4 - len(item["options"]))
        audio = ""
        if cache and item["correct_da"] and (snd := _voice(cache, item["correct_da"], media)):
            audio = f"[sound:{snd}]"
        deck.add_note(genanki.Note(MODEL, tags=[tag, "eval", item["kind"]],
                                   fields=[item["question"], *opts[:4], item["answer"],
                                           item["explanation"], item["correct_da"],
                                           item["correct_en"], audio]))
    print(f"  week{week:02d}: {kept} kept, {rejected} rejected by verify (of {len(raw)} generated)")
    return deck


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate verified Analyze/Evaluate MCQ eval cards.")
    ap.add_argument("weeks", help="e.g. '10' or '1-28'")
    ap.add_argument("--out", default="deck")
    ap.add_argument("--curriculum", default="curriculum_da.md")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--per-week", type=int, default=8, dest="n", help="MCQs to generate per week (before verify)")
    ap.add_argument("--audio", action="store_true", help="voice the correct Danish on the back (synth + cache)")
    a = ap.parse_args(argv)

    nums = sorted({k for part in a.weeks.split(",") for k in (
        range(int(part.split("-")[0]), int(part.split("-")[1]) + 1) if "-" in part else [int(part)])})
    curriculum = ROOT / a.curriculum
    client = make_client()
    cache = ClipCache(GoogleTTS(voices={"da": DA_VOICE}, speed=DA_SPEED), str(CLIP_DIR)) if a.audio else None

    decks, media = [], {}
    for w in nums:
        wdir = ROOT / f"year1/week{w:02d}"
        if not (wdir / "storyboard.md").exists():
            print(f"  week{w:02d}: no storyboard — skipped")
            continue
        level, grammar = curriculum_fields(w, curriculum)
        decks.append(build_week_deck(client, a.model, w, wdir, level=level, grammar=grammar,
                                     n=a.n, cache=cache, media=media))

    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    span = f"weeks{nums[0]:02d}-{nums[-1]:02d}" if len(nums) > 1 else f"week{nums[0]:02d}"
    out_path = out_dir / f"eval_{span}_da.apkg"
    genanki.Package(decks, media_files=[str(p) for p in media.values()]).write_to_file(str(out_path))
    total = sum(len(d.notes) for d in decks)
    aud = f", {len(media)} audio clips" if a.audio else ""
    print(f"-> {out_path}  ({total} verified MCQs across {len(decks)} week(s){aud})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
