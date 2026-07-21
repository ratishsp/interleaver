"""gen_deck.py — build a principled Anki deck from a week's content.

Per pedagogy.md, three self-graded card types per week, aligned to the week's ILO (its grammar
target):
  - production : each da/en line pair as English->Danish, bidirectional (the comprehension reverse
                 comes free). Deterministic — read straight from the aligned pairs.
  - vocab      : useful words from each scene, bidirectional. LLM-selected per scene.
  - cloze      : the week's TARGET grammar form blanked in a REAL sentence from the scene. LLM picks
                 the sentence + the token to blank, keyed to the grammar focus.

Output: an importable .apkg with one subdeck per week under 'Danish (Maya)'. Anki does the spaced
repetition; this only decides which cards exist and why.

Run:  set -a; . ./.env; set +a
      export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_LOCATION=global ALL_PROXY=socks5h://localhost:18080
      .venv/bin/python gen_deck.py 10,24 --out deck
"""
from __future__ import annotations
import argparse
import hashlib
import re
from pathlib import Path

import genanki

from tandem.gen import DEFAULT_MODEL, parse_storyboard
from tandem.llm import make_client, _json_call

ROOT = Path(__file__).resolve().parent
DECK_BASE = 2_059_400_000            # stable base; per-week deck id = DECK_BASE + week
TOP = "Danish (Maya)"
MIN_PROD_WORDS = 4                   # skip trivial line pairs ("Ja, tak.") as production cards

# Danish clip cache — reuse the exact voiced lines the course audio uses (build_week_audio's Maya
# voice at natural speed). Key mirrors ClipCache._key so we can look up by hash without synthesising.
CLIP_DIR = ROOT / "cache/clips"
DA_VOICE, DA_SPEED = "da-DK-Chirp3-HD-Sulafat", 1.0


def clip_for(text: str) -> Path | None:
    """Path to the cached Danish clip for this exact line, or None if not cached (never synthesises)."""
    descriptor = f"google:{DA_VOICE}:{DA_SPEED}"
    digest = hashlib.sha256(f"{descriptor}\n{text}".encode("utf-8")).hexdigest()[:32]
    p = CLIP_DIR / f"{digest}.mp3"
    return p if p.exists() else None

# Custom cloze model: the back echoes the blanked QUESTION, then the answer + gloss — so cloze
# matches the other two types (whose back re-shows the front prompt above the answer).
CLOZE_QA_MODEL = genanki.Model(
    1_607_392_411, "Danish cloze (question echoed)",
    fields=[{"name": "Text"}, {"name": "Back Extra"}, {"name": "Blanked"}],
    templates=[{
        "name": "Cloze",
        "qfmt": "{{cloze:Text}}",
        "afmt": "{{Blanked}}\n<hr id=answer>\n{{cloze:Text}}<br>\n{{Back Extra}}",
    }],
    model_type=genanki.Model.CLOZE,
)


def curriculum_fields(week: int, curriculum_path: Path) -> tuple[str, str]:
    """Return (level, grammar) for a week from curriculum_da.md, else ('', '')."""
    row = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*[^|]+?\s*\|\s*([^|]+?)\s*\|")
    for line in curriculum_path.read_text(encoding="utf-8").splitlines():
        m = row.match(line)
        if m and int(m.group(1)) == week:
            return m.group(2).strip(), m.group(3).strip()
    return "", ""


CARD_PROMPT = """You are building Anki study cards for a graded Danish course (learner level {level}).
The week's grammar focus is: {grammar}.

From the scene below (Danish line | English gloss), produce two lists:

- "vocab": a few of the most useful words to drill, each as
  {{"da": <word, natural dictionary form>, "en": <English>}}. Skip proper nouns and trivial function
  words.

- "cloze": sentences that exercise the grammar focus. Wrap the target word as Anki cloze markup
  {{{{c1::WORD::HINT}}}}, leaving the rest of the sentence exactly as written. HINT = the English
  meaning plus the minimal grammatical signal needed to produce the exact form; lowercase. Each item:
  {{"cloze": <the sentence>, "en": <English gloss>}}.
  If none fit, return an empty list.

Return JSON: {{"vocab": [...], "cloze": [...]}}.

Scene:
{scene}
"""


def scene_cards(client, model, *, level, grammar, da, en):
    """LLM: vocab + cloze for one scene. Returns (vocab_list, cloze_list); tolerant of a bad call."""
    body = "\n".join(f"{d} | {e}" for d, e in zip(da, en))
    prompt = CARD_PROMPT.format(level=level or "A1/A2", grammar=grammar or "(general)", scene=body)
    try:
        out = _json_call(client, model, prompt, stage="gen_deck.cards")
    except SystemExit:
        return [], []
    return out.get("vocab") or [], out.get("cloze") or []


CLOZE_RE = re.compile(r"\{\{c\d+::(.+?)(?:::(.+?))?\}\}")   # {{cN::answer}} or {{cN::answer::hint}}


def _norm(s: str) -> str:
    return " ".join(s.split())


def make_cloze(item: dict, scene_lines) -> tuple[str, str, str] | None:
    """Validate the model's cloze-marked sentence, return (cloze_text, blanked, source_line), else None.

    The model now emits the sentence with its own `{{cN::answer::hint}}` span (it places the blank
    on the token it means — no occurrence guessing). We only CHECK: the markup must parse, and the
    bare sentence (markup stripped to the answers) must match a real scene line verbatim (a guard
    against a paraphrased/invented sentence). 'blanked' (question shown on the back) replaces each
    span with its bracketed hint; 'source_line' is the exact matched scene line (for audio lookup)."""
    text = (item.get("cloze") or "").strip()
    if not text or not CLOZE_RE.search(text):
        return None
    bare = CLOZE_RE.sub(lambda m: m.group(1), text)             # markup -> answers
    source = next((l for l in scene_lines if _norm(l) == _norm(bare)), None)   # verbatim guard
    if source is None:
        return None
    blanked = CLOZE_RE.sub(lambda m: f"[{m.group(2).strip()}]" if m.group(2) else "[…]", text)
    return text, blanked, source


def _sample_even(items, k):
    """Keep at most k items, spread evenly across the list (not just the first k)."""
    if k <= 0 or len(items) <= k:
        return items
    step = len(items) / k
    return [items[int(i * step)] for i in range(k)]


def _interleave(*lists):
    """Round-robin merge, leading with lists[0]: a[0], b[0], c[0], a[1], ... — so the new-card
    stream Anki introduces is a MIX (and leads with cloze), not a block of one type."""
    from itertools import zip_longest
    out = []
    for group in zip_longest(*lists):
        out.extend(x for x in group if x is not None)
    return out


def build_week_deck(client, model, week: int, wdir: Path, *, level, grammar, use_llm, max_prod,
                    max_vocab, audio, media):
    deck = genanki.Deck(DECK_BASE + week, f"{TOP}::Week {week:02d}")
    tag = f"week{week:02d}"
    prod, vocab_n, cloze_n = [], [], []
    n_snd = 0
    for r in parse_storyboard(wdir / "storyboard.md"):
        da_p, en_p = wdir / f"{r['stem']}.da", wdir / f"{r['stem']}.en"
        if not (da_p.exists() and en_p.exists()):
            continue
        da = [l for l in da_p.read_text(encoding="utf-8").splitlines() if l.strip()]
        en = [l for l in en_p.read_text(encoding="utf-8").splitlines() if l.strip()]
        # production — deterministic; cap per scene, sampled across it, to keep the mix sane
        pairs = [(e, d) for d, e in zip(da, en) if len(d.split()) >= MIN_PROD_WORDS]
        for e, d in _sample_even(pairs, max_prod):
            da_field = d
            if audio and (clip := clip_for(d)):     # [sound:] on the Danish field → plays whenever DA shows
                media[clip.name] = clip
                da_field = f"{d} [sound:{clip.name}]"
                n_snd += 1
            prod.append(genanki.Note(genanki.BASIC_AND_REVERSED_CARD_MODEL,
                                     fields=[e, da_field], tags=[tag, "production"]))
        if not use_llm:
            continue
        vocab, cloze = scene_cards(client, model, level=level, grammar=grammar, da=da, en=en)
        added = 0
        for v in vocab:
            if max_vocab and added >= max_vocab:      # cap per scene (guards mix if the model over-lists)
                break
            d, e = (v.get("da") or "").strip(), (v.get("en") or "").strip()
            if d and e:
                vocab_n.append(genanki.Note(genanki.BASIC_AND_REVERSED_CARD_MODEL,
                                            fields=[d, e], tags=[tag, "vocab"]))
                added += 1
        for c in cloze:
            made = make_cloze(c, da)
            if not made:
                continue
            text, blanked, source = made
            back = (c.get("en") or "").strip()
            if audio and (clip := clip_for(source)):    # full-sentence audio on the back only
                media[clip.name] = clip
                back = f"{back} [sound:{clip.name}]".strip()
                n_snd += 1
            cloze_n.append(genanki.Note(CLOZE_QA_MODEL,
                                        fields=[text, back, blanked], tags=[tag, "cloze"]))
    # lead with cloze (the ILO drill), then interleave vocab + production
    for note in _interleave(cloze_n, vocab_n, prod):
        deck.add_note(note)
    snd = f", {n_snd} with audio" if audio else ""
    print(f"  week{week:02d}: {len(prod)} production, {len(vocab_n)} vocab, {len(cloze_n)} cloze{snd}")
    return deck


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a principled Anki deck (.apkg) from week content.")
    ap.add_argument("weeks", help="e.g. '10,24' or '1-15'")
    ap.add_argument("--out", default="deck", help="output dir (default: deck/)")
    ap.add_argument("--curriculum", default="curriculum_da.md")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--no-llm", action="store_true",
                    help="production cards only (deterministic; skip vocab/cloze LLM calls)")
    ap.add_argument("--max-prod-per-scene", type=int, default=5, dest="max_prod",
                    help="cap production cards per scene, sampled across it (default 5; 0 = no cap)")
    ap.add_argument("--max-vocab-per-scene", type=int, default=5, dest="max_vocab",
                    help="cap vocab cards per scene (default 5; 0 = no cap)")
    ap.add_argument("--audio", action="store_true",
                    help="attach the cached Danish clip to production + cloze cards (reuse only; "
                         "never synthesises — a line with no cached clip just gets no audio)")
    a = ap.parse_args(argv)

    nums = sorted({n for part in a.weeks.split(",") for n in (
        range(int(part.split("-")[0]), int(part.split("-")[1]) + 1) if "-" in part else [int(part)])})
    curriculum = ROOT / a.curriculum
    client = None if a.no_llm else make_client()

    decks, media = [], {}          # media: clip filename -> path (deduped across weeks)
    for w in nums:
        wdir = ROOT / f"year1/week{w:02d}"
        if not (wdir / "storyboard.md").exists():
            print(f"  week{w:02d}: no storyboard — skipped")
            continue
        level, grammar = curriculum_fields(w, curriculum)
        decks.append(build_week_deck(client, a.model, w, wdir,
                                     level=level, grammar=grammar, use_llm=not a.no_llm,
                                     max_prod=a.max_prod, max_vocab=a.max_vocab,
                                     audio=a.audio, media=media))

    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    span = f"weeks{nums[0]:02d}-{nums[-1]:02d}" if len(nums) > 1 else f"week{nums[0]:02d}"
    out_path = out_dir / f"{span}_da.apkg"
    pkg = genanki.Package(decks, media_files=[str(p) for p in media.values()])
    pkg.write_to_file(str(out_path))
    total = sum(len(d.notes) for d in decks)
    aud = f", {len(media)} audio clips" if a.audio else ""
    print(f"-> {out_path}  ({total} cards across {len(decks)} week(s){aud})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
