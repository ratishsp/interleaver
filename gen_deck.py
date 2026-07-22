"""gen_deck.py — build a principled Anki deck from a week's content.

Per pedagogy.md, three self-graded card types per week, aligned to the week's ILO (its grammar
target):
  - production : each da/en line pair, split into two single-sided notes — English->Danish (Apply) and
                 Danish->English comprehension (Understand), tagged apart. Deterministic from the pairs.
  - vocab      : useful words from each scene, both directions as separate notes (Remember). LLM-picked.
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
import re
from pathlib import Path

import genanki

from tandem.gen import DEFAULT_MODEL, parse_storyboard
from tandem.llm import make_client, _json_call
from tandem.tts import GoogleTTS
from tandem.cache import ClipCache

ROOT = Path(__file__).resolve().parent
DECK_BASE = 2_059_400_000            # stable base; per-week deck id = DECK_BASE + week
MIN_PROD_WORDS = 4                   # skip trivial line pairs ("Ja, tak.") as production cards

LANG_NAMES = {"da": "Danish", "en": "English", "ml": "Malayalam", "ta": "Tamil", "es": "Spanish",
              "hi": "Hindi", "fr": "French", "sa": "Sanskrit", "sv": "Swedish", "bn": "Bengali"}

# Audio via the shared ClipCache. Danish reuses the course's cached clips (build_week_audio's Maya
# voice, Sulafat) so real lines are cache HITS; other languages fall back to the tts default voice and
# synth fresh. English is the universal gloss. Voice overrides where we need a specific cached speaker:
CLIP_DIR = ROOT / "cache/clips"
VOICE_OVERRIDES = {"da": "da-DK-Chirp3-HD-Sulafat", "fr": "fr-FR-Chirp3-HD-Aoede"}
DECK_SPEED = 1.0

# gen_eval imports these; keep the Danish names as aliases so the eval path is untouched.
TOP = f"{LANG_NAMES['da']} (Maya)"
DA_VOICE, DA_SPEED = VOICE_OVERRIDES["da"], DECK_SPEED


def deck_top(lang: str) -> str:
    return f"{LANG_NAMES.get(lang, lang)} (Maya)"


def _voice(cache, text: str, media: dict, lang: str = "da") -> str | None:
    """Get/synthesise the clip for `text` in `lang`, register it in `media`, return its filename
    (None on failure — e.g. a language with no configured voice, so the deck ships text-only)."""
    try:
        clip = cache.clip(text, lang)
    except Exception:
        return None
    media[clip.name] = clip
    return clip.name

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


CARD_PROMPT = """You are building Anki study cards for a graded {lang} course (learner level {level}).
The week's grammar focus is: {grammar}.

From the scene below ({lang} line | English gloss), produce two lists:

- "vocab": a few of the most useful words to drill, including any central to the grammar focus,
  each as {{"l2": <{lang} citation form>, "en": <English>}}.

- "cloze": sentences that exercise the grammar focus. Wrap the target word as Anki cloze markup
  {{{{c1::WORD::HINT}}}}, leaving the rest of the sentence exactly as written. HINT = the English
  meaning plus the minimal grammatical signal needed to produce the exact form; lowercase. Each item:
  {{"cloze": <the sentence>, "en": <English gloss>}}.
  If none fit, return an empty list.

Return JSON: {{"vocab": [...], "cloze": [...]}}.

Scene:
{scene}
"""


def scene_cards(client, model, *, lang, level, grammar, l2, en, want_cloze=True):
    """LLM: vocab (+ cloze) for one scene. Returns (vocab_list, cloze_list); tolerant of a bad call."""
    body = "\n".join(f"{d} | {e}" for d, e in zip(l2, en))
    prompt = CARD_PROMPT.format(lang=LANG_NAMES.get(lang, lang), level=level or "A1/A2",
                                grammar=grammar or "(general)", scene=body)
    try:
        out = _json_call(client, model, prompt, stage="gen_deck.cards")
    except SystemExit:
        return [], []
    return out.get("vocab") or [], (out.get("cloze") or [] if want_cloze else [])


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


def _note(model, *, fields, tags, guid_parts):
    """A note with a STABLE guid (from guid_parts, not the editable fields) — so a later content fix
    updates the same card in place on re-import instead of orphaning it."""
    n = genanki.Note(model, fields=fields, tags=tags)
    n.guid = genanki.guid_for(*[str(p) for p in guid_parts])
    return n


def build_week_deck(client, model, week: int, wdir: Path, *, lang, level, grammar, use_llm, max_prod,
                    max_vocab, cache, media):
    deck = genanki.Deck(DECK_BASE + week, f"{deck_top(lang)}::Week {week:02d}")
    tag = f"week{week:02d}"
    want_cloze = bool(grammar)          # cloze/eval need a grammar focus — only where a curriculum exists
    # each direction is its OWN single-sided note (not a bidirectional card): so they can be tagged apart
    # (L2->EN = Apply, EN->L2... = Understand) AND ordered far apart, with no sibling-burying to defer one.
    prod_fwd, prod_rev, vocab_fwd, vocab_rev, cloze_n = [], [], [], [], []
    seen_vocab = set()          # dedupe words across scenes (same word recurs scene to scene)
    n_snd = 0
    for r in parse_storyboard(wdir / "storyboard.md"):
        l2_p, en_p = wdir / f"{r['stem']}.{lang}", wdir / f"{r['stem']}.en"
        if not (l2_p.exists() and en_p.exists()):
            continue
        stem = r["stem"]
        l2 = [l for l in l2_p.read_text(encoding="utf-8").splitlines() if l.strip()]
        en = [l for l in en_p.read_text(encoding="utf-8").splitlines() if l.strip()]
        # production — deterministic; cap per scene, sampled across it, to keep the mix sane
        pairs = [(e, d) for d, e in zip(l2, en) if len(d.split()) >= MIN_PROD_WORDS]
        for e, d in _sample_even(pairs, max_prod):
            l2_field = d
            if cache and (snd := _voice(cache, d, media, lang)):   # [sound:] on L2 field → plays when L2 shows
                l2_field = f"{d} [sound:{snd}]"
                n_snd += 1
            # guid anchors on the English line (stable across L2 edits → a target-lang fix updates in place)
            prod_fwd.append(_note(genanki.BASIC_MODEL,   # L2<-EN: generate the target (Apply)
                                  fields=[e, l2_field], tags=[tag, "production", "bloom::apply"],
                                  guid_parts=[lang, week, stem, "prod", e]))
            prod_rev.append(_note(genanki.BASIC_MODEL,   # L2->EN: comprehend the target (Understand)
                                  fields=[l2_field, e], tags=[tag, "comprehension", "bloom::understand"],
                                  guid_parts=[lang, week, stem, "comp", e]))
        if not use_llm:
            continue
        vocab, cloze = scene_cards(client, model, lang=lang, level=level, grammar=grammar,
                                   l2=l2, en=en, want_cloze=want_cloze)
        added = 0
        for v in vocab:
            if max_vocab and added >= max_vocab:      # cap per scene (guards mix if the model over-lists)
                break
            d, e = (v.get("l2") or "").strip(), (v.get("en") or "").strip()
            key = _norm(d).lower()
            if not (d and e) or key in seen_vocab:    # skip a word already added this week
                continue
            seen_vocab.add(key)
            l2_field = d
            if cache and (snd := _voice(cache, d, media, lang)):   # vocab word — synthesised once, then cached
                l2_field = f"{d} [sound:{snd}]"
                n_snd += 1
            vocab_fwd.append(_note(genanki.BASIC_MODEL,  # L2->EN: recognise the word (Remember)
                                   fields=[l2_field, e], tags=[tag, "vocab", "bloom::remember"],
                                   guid_parts=[lang, week, "vocab-fwd", key]))
            vocab_rev.append(_note(genanki.BASIC_MODEL,  # EN->L2: recall the word (Remember)
                                   fields=[e, l2_field], tags=[tag, "vocab", "bloom::remember"],
                                   guid_parts=[lang, week, "vocab-rev", key]))
            added += 1
        for c in cloze:
            made = make_cloze(c, l2)
            if not made:
                continue
            text, blanked, source = made
            back = (c.get("en") or "").strip()
            if cache and (snd := _voice(cache, source, media, lang)):    # full-sentence audio on the back only
                back = f"{back} [sound:{snd}]".strip()
                n_snd += 1
            cloze_n.append(_note(CLOZE_QA_MODEL, fields=[text, back, blanked],
                                 tags=[tag, "cloze", "bloom::apply"],
                                 guid_parts=[lang, week, stem, "cloze", (c.get("en") or "").strip()]))
    # Two streams: primaries (remember-first: vocab recognition, cloze, production=Apply) and mirrors
    # (word recall + Danish->English comprehension=Understand). Interleave the two streams so
    # comprehension shows up throughout (not blocked at the end), but rotate the mirrors by half first so
    # a given sentence's two directions stay ~a few days apart instead of landing back-to-back.
    primaries = _interleave(vocab_fwd, cloze_n, prod_fwd)
    mirrors = _interleave(vocab_rev, prod_rev)
    if mirrors:
        h = len(mirrors) // 2
        mirrors = mirrors[h:] + mirrors[:h]
    for note in _interleave(primaries, mirrors):
        deck.add_note(note)
    snd = f", {n_snd} with audio" if cache else ""
    print(f"  week{week:02d}: {len(vocab_fwd)}x2 vocab, {len(cloze_n)} cloze, {len(prod_fwd)} production, "
          f"{len(prod_rev)} comprehension{snd}")
    return deck


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a principled Anki deck (.apkg) from week content.")
    ap.add_argument("weeks", help="e.g. '10,24' or '1-15'")
    ap.add_argument("--lang", default="da", help="target language code (da, ta, ml, fr, ...). Default da.")
    ap.add_argument("--out", default="deck", help="output dir (default: deck/)")
    ap.add_argument("--curriculum", default=None,
                    help="grammar curriculum (default: curriculum_<lang>.md if it exists). Drives cloze; "
                         "without one, cloze is skipped and the deck is vocab/production/comprehension.")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--no-llm", action="store_true",
                    help="production cards only (deterministic; skip vocab/cloze LLM calls)")
    ap.add_argument("--max-prod-per-scene", type=int, default=5, dest="max_prod",
                    help="cap production cards per scene, sampled across it (default 5; 0 = no cap)")
    ap.add_argument("--max-vocab-per-scene", type=int, default=5, dest="max_vocab",
                    help="cap vocab cards per scene (default 5; 0 = no cap)")
    ap.add_argument("--audio", action="store_true",
                    help="attach audio: Danish reuses cached clips; other languages synth from the "
                         "per-language voice (a language with no configured voice ships text-only)")
    a = ap.parse_args(argv)

    nums = sorted({n for part in a.weeks.split(",") for n in (
        range(int(part.split("-")[0]), int(part.split("-")[1]) + 1) if "-" in part else [int(part)])})
    cur_path = ROOT / (a.curriculum or f"curriculum_{a.lang}.md")
    have_curriculum = cur_path.exists()
    client = None if a.no_llm else make_client()
    cache = ClipCache(GoogleTTS(voices=VOICE_OVERRIDES, speed=DECK_SPEED), str(CLIP_DIR)) if a.audio else None

    decks, media = [], {}          # media: clip filename -> path (deduped across weeks)
    for w in nums:
        wdir = ROOT / f"year1/week{w:02d}"
        if not (wdir / "storyboard.md").exists():
            print(f"  week{w:02d}: no storyboard — skipped")
            continue
        level, grammar = curriculum_fields(w, cur_path) if have_curriculum else ("", "")
        decks.append(build_week_deck(client, a.model, w, wdir, lang=a.lang,
                                     level=level, grammar=grammar, use_llm=not a.no_llm,
                                     max_prod=a.max_prod, max_vocab=a.max_vocab,
                                     cache=cache, media=media))

    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    span = f"weeks{nums[0]:02d}-{nums[-1]:02d}" if len(nums) > 1 else f"week{nums[0]:02d}"
    out_path = out_dir / f"{span}_{a.lang}.apkg"
    pkg = genanki.Package(decks, media_files=[str(p) for p in media.values()])
    pkg.write_to_file(str(out_path))
    total = sum(len(d.notes) for d in decks)
    aud = f", {len(media)} audio clips" if a.audio else ""
    print(f"-> {out_path}  ({total} cards across {len(decks)} week(s){aud})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
