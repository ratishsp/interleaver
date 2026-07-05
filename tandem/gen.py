"""Gemini-backed script generation + context-rich translation.

One client (google-genai), two interchangeable backends:
  - **Gemini Developer API** (AI Studio) — set ``GEMINI_API_KEY``. Quickest to try; billed via
    AI Studio, *not* the GCP grant. Good for trials.
  - **Vertex AI** (the $20k GCP grant) — set ``GOOGLE_GENAI_USE_VERTEXAI=true``,
    ``GOOGLE_CLOUD_PROJECT=<project>``, ``GOOGLE_CLOUD_LOCATION=<region>``. Use for the real run.

Design decisions this encodes (see design_notes.md):
  - **Author graded text natively in Danish**, English alongside as the L1 gloss + fan-out pivot.
  - **Translation is context-rich**, setting-preserving (translate, don't relocate), and MUST
    preserve 1-sentence-per-line alignment (the per-sentence segmentation is what the clip cache
    and pair assembly key on).

CLI:
  python -m tandem.gen scene --week 1 --scene-title "Arrival" --scene "Maya lands in Copenhagen" \\
      --grammar "present være/hedde/komme fra; der er; pronouns; hvad/hvor" --lines 14 \\
      --out-stem year1/week01/01_arrival
  python -m tandem.gen translate --src en --tgt es --context "Maya's first year, Copenhagen" \\
      --in year1/week01/01_arrival.en --out year1/week01/01_arrival.es
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_MODEL = "gemini-3.1-pro-preview"   # gen, verify, and the gates all run on this (Vertex location 'global')

# The shared story world is story_bible.md — the same ground-truth the review gates read — so the
# author, the QA/revise prompts, and the gates can't drift apart. The per-week STATUS LEDGER is
# gate-only and is NOT fed to the author: it foreshadows later weeks, which a scene could leak.
_BIBLE_PATH = Path(__file__).resolve().parent.parent / "story_bible.md"
_BIBLE_DROP_SECTIONS = ("status ledger",)   # gate-only sections, excluded from the author's view
_STORY_BIBLE: str | None = None


def load_story_bible(path: str | Path | None = None) -> str:
    """The STABLE story facts (Maya, cast, cross-cutting rules) shared by the author + revise prompts.

    Reads story_bible.md and drops the per-week status ledger (gate-only — its foreshadowing must not
    reach the author). Cached when read from the default path.
    """
    global _STORY_BIBLE
    if path is None and _STORY_BIBLE is not None:
        return _STORY_BIBLE
    p = Path(path) if path else _BIBLE_PATH
    kept, started, skip = [], False, False
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):                       # a top-level section header
            started = True
            skip = any(k in line.lower() for k in _BIBLE_DROP_SECTIONS)
        if not started or skip:                          # drop the title/preamble and dropped sections
            continue
        kept.append(line)
    text = ("Story world — canonical facts; keep every scene consistent with these:\n\n"
            + "\n".join(kept).strip())
    if path is None:
        _STORY_BIBLE = text
    return text


def make_client():
    """Return a google-genai Client, auto-selecting backend from the environment."""
    from google import genai

    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true", "yes"}
    if use_vertex:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        if not project:
            raise SystemExit("Vertex backend: set GOOGLE_CLOUD_PROJECT (and optionally GOOGLE_CLOUD_LOCATION).")
        return genai.Client(vertexai=True, project=project, location=location)

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit(
            "No credentials. Either set GEMINI_API_KEY (AI Studio key — get one at "
            "https://aistudio.google.com/apikey), or use Vertex (GOOGLE_GENAI_USE_VERTEXAI=true + "
            "GOOGLE_CLOUD_PROJECT)."
        )
    return genai.Client(api_key=key)


def _parse_json_object(text: str) -> dict | None:
    """Parse a JSON object from model text, tolerating markdown fences / trailing prose.

    Returns the dict, or None if nothing parseable. Transient malformed responses (fences, a
    stray sentence after the JSON, truncation) used to crash whole scenes; salvage what we can.
    """
    t = (text or "").strip()
    if t.startswith("```"):                      # strip a ```json … ``` fence
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
        t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")                          # scan the first BALANCED {...}; ignore trailing junk
    if start < 0:                                # (handles a stray extra '}' or prose after the object)
        return None
    depth, instr, esc = 0, False, False
    for idx in range(start, len(t)):
        c = t[idx]
        if instr:
            esc = (c == "\\" and not esc)
            if c == '"' and not esc:
                instr = False
        elif c == '"':
            instr = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:idx + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _json_call(client, model: str, prompt: str, *, retries: int = 1) -> dict:
    """Call the model forcing a JSON object response and parse it (salvage + one retry).

    Temperature is left UNSET so the model's own default applies (1.0 for current Gemini, which
    Google recommends across both 2.x and 3.x). This keeps the pipeline model-agnostic — no temp to
    retune when swapping models — and avoids Gemini 3's looping/degradation risk from sub-1.0 temps.

    A transient malformed/truncated response is no longer fatal: we salvage fenced/­trailing JSON,
    and regenerate once before giving up (this was dropping whole scenes — wk6 sc6, wk7 sc4).
    """
    from google.genai import types

    last = ""
    for _ in range(retries + 1):
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        last = (resp.text or "").strip()
        parsed = _parse_json_object(last)
        if parsed is not None:
            return parsed
    raise SystemExit(f"Model did not return valid JSON after {retries + 1} tries:\n{last[:500]}")


def scene_prompt(*, week: int, level: str, scene_title: str, scene: str, grammar: str,
                 arc: list | None = None, scene_num: int | None = None,
                 bible: str | None = None) -> str:
    """Build the exact generation prompt (also used by --show-prompt for inspection).

    Scene length is not a caller quota — the prompt steers toward a rich ~15-20 line-pair situation.
    `bible` defaults to the stable sections of story_bible.md (single source of truth with the gates).
    """
    bible = bible if bible is not None else load_story_bible()
    arc_block = ""
    if arc:
        rows = "\n".join(
            f'  {a["num"]}. {a["title"]} — {a["scene"]}'
            + ("   ← WRITE THIS SCENE" if a["num"] == scene_num else "")
            for a in arc)
        arc_block = ("\nThis week's arc (write ONLY the marked scene; do not cover the other "
                     "scenes or bring in characters who first appear in a later scene):\n" + rows + "\n")
    return f"""{bible}

TASK: Write ONE scene for WEEK {week} (CEFR level {level}) of the Danish course.
Scene title: "{scene_title}". Scene: {scene}
{arc_block}
The Danish is what's being learned — author it natively and idiomatically; the English is a faithful, natural gloss.

- Level {level}, this week's grammar: {grammar} (earlier-week grammar may recur). Author natural Danish first — it may sit slightly above {level} where that's what's natural, but don't reach clearly beyond it.
- Tell it as Maya's own first-person account; attribute any quoted speech so it's clear who's speaking.
- Match sentence complexity to {level}: at A1–A2 favor short sentences. Reserve dense, multi-clause sentences for B1+.
- One sentence per line in both arrays; let the scene run to a full ~15-20 line-pairs (a complete situation, not a sketch). The "da" and "en" arrays MUST have the same number of entries, aligned line-for-line.

Return JSON: {{"da": [...], "en": [...]}}."""


def generate_scene(client, *, model: str, week: int, level: str, scene_title: str, scene: str,
                   grammar: str, arc: list | None = None,
                   scene_num: int | None = None, bible: str | None = None) -> dict:
    """Author a graded scene natively in Danish + an English gloss. Returns {'da': [...], 'en': [...]}."""
    prompt = scene_prompt(week=week, level=level, scene_title=scene_title, scene=scene,
                          grammar=grammar, arc=arc, scene_num=scene_num, bible=bible)
    out = _json_call(client, model, prompt)
    da, en = out.get("da", []), out.get("en", [])
    if len(da) != len(en):
        raise SystemExit(f"Alignment broken: {len(da)} DA lines vs {len(en)} EN lines.")
    return {"da": da, "en": en}


def revise_prompt(*, level: str, grammar: str, scene: str, da_lines: list[str],
                  en_lines: list[str], feedback: str, bible: str | None = None) -> str:
    """Build the revise prompt: a rejected draft + the QA problems to fix (also used by --show-prompt)."""
    bible = bible if bible is not None else load_story_bible()
    pairs = "\n".join(f"{i+1}. DA: {d}    EN: {e}"
                      for i, (d, e) in enumerate(zip(da_lines, en_lines)))
    return f"""{bible}

A draft scene for this Danish course (CEFR level {level}) was rejected by QA. Fix ONLY the problems listed below; keep everything else — the story, the line order, and every line that wasn't flagged — unchanged.

Scene (for context): {scene}
Level {level}; this week's grammar: {grammar}.

DRAFT (line-aligned Danish / English):
{pairs}

PROBLEMS TO FIX:
{feedback}

Return the FULL corrected scene as JSON: {{"da": [...], "en": [...]}} — one sentence per line, the two arrays the same length and aligned line-for-line. Splitting a line to fix it changes the line count; that's fine, just keep "da" and "en" aligned."""


def revise_scene(client, *, model: str, level: str, grammar: str, scene: str,
                 da_lines: list[str], en_lines: list[str], feedback: str,
                 bible: str | None = None) -> dict:
    """Revise a rejected draft to fix the QA problems, keeping the rest. Returns {'da': [...], 'en': [...]}."""
    prompt = revise_prompt(level=level, grammar=grammar, scene=scene,
                           da_lines=da_lines, en_lines=en_lines, feedback=feedback, bible=bible)
    out = _json_call(client, model, prompt)
    da, en = out.get("da", []), out.get("en", [])
    if len(da) != len(en):
        raise SystemExit(f"Alignment broken: {len(da)} DA lines vs {len(en)} EN lines.")
    return {"da": da, "en": en}


def translate_prompt(*, src_lang: str, tgt_lang: str, lines: list[str], context: str = "",
                     level: str = "", glossary: str = "", ref_lang: str = "",
                     ref_lines: list[str] | None = None, bible: str | None = None) -> str:
    """Build the exact translation prompt (also used by --show-prompt for inspection).

    When `ref_lang`/`ref_lines` are given (the same lines in a third language, aligned one-to-one),
    they are injected as a DISAMBIGUATION REFERENCE: the source is still authoritative for meaning, but
    where it is ambiguous the reference resolves distinctions the source drops (e.g. English "friend"
    vs Danish "veninde" = a female friend; "you" vs "du"/"I" = singular/plural).
    """
    bible = bible if bible is not None else load_story_bible()
    numbered = "\n".join(f"{i+1}. {ln}" for i, ln in enumerate(lines))
    ref_block = ""
    if ref_lang and ref_lines:
        ref_numbered = "\n".join(f"{i+1}. {ln}" for i, ln in enumerate(ref_lines))
        ref_block = f"""
DISAMBIGUATION REFERENCE — the same lines in {ref_lang}, aligned one-to-one with the input. Where a
{src_lang} line is ambiguous or underspecified, use the {ref_lang} line to resolve it and carry that
distinction into {tgt_lang} wherever {tgt_lang} marks it. On a genuine MEANING conflict, follow {src_lang}.
{ref_numbered}
"""
    return f"""{bible}

TASK: Translate the following {len(lines)} lines from {src_lang} into {tgt_lang} for this course.
{f'Scene context: {context}' if context else ''}
{f'Target CEFR level: {level} — keep the translation in-level, do not drift up or down.' if level else ''}

RULES:
- Translate naturally and idiomatically in {tgt_lang}.
- TRANSLATE, DON'T RELOCATE: keep the Danish setting and render proper nouns (København, Nina, Mexico) faithfully by sound — never swap them for a target-culture equivalent (no Copenhagen -> Madrid, no Nina -> María) or auto-localize.
- Keep names consistent.{f' Glossary: {glossary}' if glossary else ''}
- Preserve sentence segmentation EXACTLY: return the SAME number of lines ({len(lines)}), one translation per input line, in order. Do not merge or split lines.
{ref_block}
INPUT:
{numbered}

Return JSON: {{"lines": ["...", ...]}} with exactly {len(lines)} entries, in order."""


def translate_lines(client, *, model: str, src_lang: str, tgt_lang: str, lines: list[str],
                    context: str = "", level: str = "", glossary: str = "", ref_lang: str = "",
                    ref_lines: list[str] | None = None, bible: str | None = None) -> list[str]:
    """Context-rich, alignment-preserving translation of `lines` from src_lang to tgt_lang.

    `ref_lang`/`ref_lines` optionally supply an aligned third-language reference to disambiguate the
    source (see translate_prompt).
    """
    prompt = translate_prompt(src_lang=src_lang, tgt_lang=tgt_lang, lines=lines,
                              context=context, level=level, glossary=glossary,
                              ref_lang=ref_lang, ref_lines=ref_lines, bible=bible)
    out = _json_call(client, model, prompt)
    res = out.get("lines", [])
    if len(res) != len(lines):
        raise SystemExit(f"Alignment broken: {len(lines)} in vs {len(res)} out.")
    return res


_WORD_RE = re.compile(r"[a-zA-ZæøåÆØÅ]+")

# A line holds more than one sentence if a sentence-final mark (optionally closing a quote/paren/
# guillemet) is followed by whitespace and a new capitalised sentence. Heuristic, but enough to guard
# the one-sentence-per-line invariant the per-sentence audio assembler depends on. Since this is a
# HARD gate, false positives must be avoided: a digit after the mark ("kl. 10"), a known Danish
# abbreviation ("f.eks. Noget", "bl.a. K"), a single initial ("H. C. Andersen"), and a closing
# quote followed by an attribution clause ('"...?" Nina asks') all produce "mark + space +
# Capital" but are NOT sentence breaks, so they're excluded below.
# The capital may be preceded by an OPENING quote — a new sentence that begins with quoted speech
# ('... siger hun. "Hvad hedder du?"') is still a sentence break.
_MULTI_SENTENCE_RE = re.compile(r"[.!?][\"»«')\]]?\s+[\"«»']?[A-ZÆØÅ]")
_ABBREVS = ("f.eks", "bl.a", "m.m", "m.fl", "d.v.s", "dvs", "osv", "ca", "kl", "nr", "stk",
            "o.l", "inkl", "ekskl", "tlf", "jf", "pga", "evt")
# Speech verbs (present tense, EN + DA): an attribution clause after a quoted utterance —
# «"...?" Nina asks.» / «"...?" siger Nina.» — is ONE audio bead, not two sentences.
_SPEECH_VERBS = frozenset({
    "ask", "asks", "say", "says", "answer", "answers", "reply", "replies", "explain", "explains",
    "add", "adds", "tell", "tells", "continue", "continues", "repeat", "repeats", "whisper",
    "whispers", "shout", "shouts", "call", "calls", "cry", "cries",
    "siger", "spørger", "svarer", "forklarer", "tilføjer", "gentager", "hvisker", "råber",
    "fortsætter", "fortæller", "mener", "kalder",
})


def _multi_sentence_lines(lines: list[str]) -> list[int]:
    """1-based indices of lines that appear to hold more than one sentence (abbreviations excluded)."""
    out = []
    for i, ln in enumerate(lines):
        for m in _MULTI_SENTENCE_RE.finditer(ln):
            if ln[m.start()] == ".":                  # only a period can be an abbreviation
                before = ln[:m.start()].lower()
                if any(before.endswith(a) for a in _ABBREVS):
                    continue                          # e.g. "f.eks.", "kl."
                if re.search(r"(?:^|\s)\w$", before):  # single initial, e.g. "H." / "C."
                    continue
            # Quoted speech + an attribution clause — «"...?" Nina asks» / «"...?" siger han» — is one
            # utterance (one audio bead), not two sentences. Skip when a closing quote precedes the
            # break AND a speech verb is among the next two words. Real narration after a quote
            # («"Hej." Hun smiler.») has no speech verb and still flags, as does a second quoted
            # sentence («"Hej." "Dav."»).
            quoted = ln[m.start() + 1] in "\"»«')]"
            if quoted:
                tail = re.findall(r"[A-Za-zÆØÅæøå]+", ln[m.end() - 1:])[:2]
                if any(t.lower() in _SPEECH_VERBS for t in tail):
                    continue
            out.append(i + 1)
            break
    return out

# Dimensions the LLM reviewer scores (order = display order).
VERIFY_DIMENSIONS = ("grammar_whitelist", "coherence", "naturalness",
                     "gloss_fidelity", "show_dont_tell")
# Advisory dims are reported but never block/retry; everything else (+ alignment) is a hard gate.
# grammar_whitelist = scope: correct-but-slightly-advanced Danish is fine (judged by level, not a strict whitelist).
ADVISORY_DIMS = ("grammar_whitelist", "show_dont_tell")

# CEFR level → approximate frequency-rank cutoff (the most-common-N Danish word-forms).
# These mirror the curriculum's vocabulary bands. NOTE: the freq list is OpenSubtitles-derived
# and skews conversational, so concrete scene nouns (kuffert, lufthavn, fly) routinely fall
# beyond the band even when perfectly A1-appropriate. The band-check is therefore DIAGNOSTIC
# (advisory) — it lists the out-of-band word-forms + ranks for a human glance, not a hard gate.
CEFR_BANDS = {"A1": 800, "A2": 1500, "B1": 3000, "B2": 5000, "C1": 8000, "C2": 12000}

# Story-world proper nouns — never in a frequency list, always exempt from the band-check.
STORY_NAMES = frozenset({"maya", "nina", "danmark", "danmarks", "københavn", "københavns",
                         "mexico"})

_FREQ_PATH = Path(__file__).parent / "data" / "da_freq_50k.txt"
_FREQ_RANKS: dict[str, int] | None = None


def load_freq_ranks(path: str | Path | None = None) -> dict[str, int]:
    """Load the Danish frequency list (word-form → 1-based rank, most common = 1). Cached."""
    global _FREQ_RANKS
    if path is None and _FREQ_RANKS is not None:
        return _FREQ_RANKS
    p = Path(path) if path else _FREQ_PATH
    ranks: dict[str, int] = {}
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        word = line.split(" ", 1)[0].strip().lower()
        if word and word not in ranks:
            ranks[word] = i
    if path is None:
        _FREQ_RANKS = ranks
    return ranks


def _distinct_words(lines: list[str]) -> set[str]:
    words: set[str] = set()
    for ln in lines:
        words.update(w.lower() for w in _WORD_RE.findall(ln))
    return words


def band_check(da_lines: list[str], *, level: str, ranks: dict[str, int] | None = None,
               exempt: frozenset[str] = frozenset()) -> dict:
    """Flag Danish word-forms ranked beyond the level's frequency band (or unranked). Advisory."""
    if ranks is None:
        ranks = load_freq_ranks()
    band = CEFR_BANDS.get(level.upper())
    out = []
    for w in sorted(_distinct_words(da_lines)):
        if w in STORY_NAMES or w in exempt:
            continue
        r = ranks.get(w)
        if band and (r is None or r > band):
            out.append({"word": w, "rank": r})
    out.sort(key=lambda d: (d["rank"] is not None, d["rank"] or 0))
    return {"level": level, "band": band, "out_of_band": out}


def verify_prompt(*, level: str, grammar: str, da_lines: list[str],
                  en_lines: list[str]) -> str:
    """Build the independent-QA prompt (also used by --show-prompt).

    Note: first-person POV (Maya's own voice) is an AUTHORING invariant set in scene_prompt, not
    re-checked here — a POV dimension would false-flag legitimate quoted speech by other characters.
    """
    pairs = "\n".join(f"{i+1}. DA: {d}    EN: {e}"
                      for i, (d, e) in enumerate(zip(da_lines, en_lines)))
    return f"""You are an INDEPENDENT QA reviewer for a graded Danish language course. Judge the scene below against its spec. Be concrete and cite the offending Danish by line number. Apply each dimension's threshold exactly as written — neither harsher nor more lenient than it says.

SPEC:
- CEFR level: {level}
- Grammar FOCUS this week (the new structures introduced): {grammar}
- ALSO always allowed (never flag these): the basic function words every sentence needs — articles (en/et), conjunctions (og, men), common possessives (min/din/sin), prepositions, negation (ikke), and ordinary adverbs. Only count SUBSTANTIVE structures beyond the level as violations.

The Danish is the language being learned — judge it as real, native Danish; the English is its faithful gloss.

SCENE (line-aligned Danish / English):
{pairs}

Score each dimension. For each: pass = true/false, and list specific issues as {{line, problem}}.
1. grammar_whitelist — is the grammar within {level}? (Earlier weeks' exact structures aren't listed here, so judge by level, not a strict whitelist.) Flag substantive structures (verb tenses, modal verbs, subordinate/relative clauses, the passive, comparatives) ONLY when clearly beyond {level} and not part of this week's focus.
2. coherence — read the lines in order: do they hold together? Flag ONLY hard breaks — a reply that doesn't answer its question, a fact re-introduced as if new, or a contradiction — not taste or pacing.
3. naturalness — would a native speaker actually say this? Flag ONLY lines that are CLEARLY wrong: translationese (word-for-word from English), constructions a native would not use, or errors that make it sound foreign. Do NOT flag matters of taste — register ("too abrupt/formal"), rhetorical choices, or a line you would merely phrase differently. If a native could naturally say it, it passes — reserve a fail for genuinely un-native Danish.
4. gloss_fidelity — does each English line convey the meaning of its Danish line? The English is the pivot ~100 other languages are translated from, so a wrong gloss propagates everywhere. Flag ONLY SUBSTANTIVE divergence — added, dropped, or mistranslated meaning — NOT defensible word or preposition choices (e.g. "ved" as "at" vs "by") or natural rewordings that keep the meaning.
5. show_dont_tell — flag a narrator line that LABELS a scene or event's mood (sums it up with an evaluative word) instead of showing it — a character stating their own plain feeling is fine.

Return JSON exactly:
{{"grammar_whitelist": {{"pass": true, "issues": []}},
 "coherence": {{"pass": true, "issues": []}},
 "naturalness": {{"pass": true, "issues": []}},
 "gloss_fidelity": {{"pass": true, "issues": []}},
 "show_dont_tell": {{"pass": true, "issues": []}}}}
(Use false and fill issues where there are problems; each issue is {{"line": <int>, "problem": "<text>"}}.)"""


def verify_scene(client, *, model: str, level: str, grammar: str,
                 da_lines: list[str], en_lines: list[str]) -> dict:
    """Programmatic checks + an independent LLM review. Returns a report dict."""
    multi = sorted(set(_multi_sentence_lines(da_lines)) | set(_multi_sentence_lines(en_lines)))
    report = {
        "aligned": len(da_lines) == len(en_lines),
        "one_per_line": not multi,                 # hard structural gate (audio segmentation)
        "multi_sentence_lines": multi,
        "da_lines": len(da_lines),
        "en_lines": len(en_lines),
        "distinct_da_words": len(_distinct_words(da_lines)),
        "band": band_check(da_lines, level=level),
    }
    prompt = verify_prompt(level=level, grammar=grammar, da_lines=da_lines, en_lines=en_lines)
    report["llm"] = _json_call(client, model, prompt)
    return report


def print_verify_report(rep: dict) -> bool:
    """Pretty-print a verify report; return True iff everything passed."""
    ok = rep["aligned"] and rep.get("one_per_line", True)
    print(f"  alignment: {'OK' if rep['aligned'] else 'FAIL'} "
          f"(DA {rep['da_lines']} / EN {rep['en_lines']} lines)")
    one = rep.get("one_per_line", True)
    print(f"  one sentence per line: {'OK' if one else 'FAIL'}"
          + ("" if one else f" (lines {rep.get('multi_sentence_lines')})"))
    print(f"  distinct Danish words: {rep['distinct_da_words']}")
    band = rep.get("band")
    if band and band.get("band"):
        oob = band["out_of_band"]
        print(f"  band-check ({band['level']} ≈ top {band['band']}): "
              f"{len(oob)} out-of-band word-form(s) [advisory]")
        for o in oob:
            rank = o["rank"] if o["rank"] is not None else "unranked"
            print(f"      - {o['word']} ({rank})")
    llm = rep.get("llm", {})
    for dim in VERIFY_DIMENSIONS:
        if dim not in llm:                     # not scored this run (defensive — e.g. a malformed reply)
            continue
        d = llm.get(dim, {}) or {}
        passed = bool(d.get("pass", False))
        advisory = dim in ADVISORY_DIMS
        if not advisory:                       # only hard dims (+ alignment) gate the overall result
            ok = ok and passed
        tag = " [advisory]" if advisory else ""
        print(f"  {dim}: {'PASS' if passed else 'FAIL'}{tag}")
        for iss in (d.get("issues") or []):
            print(f"      - line {iss.get('line', '?')}: {iss.get('problem', '')}")
    print(f"  OVERALL: {'PASS ✓' if ok else 'FAIL ✗'}")
    return ok


# --- Translation verification (the mirror of verify_scene for a translated target language) ----------
# The Danish verifier judges the AUTHORED da/en. This judges a TRANSLATED target (.ml/.ta/...): it sees
# the English source (meaning), the Danish reference (the distinctions English drops), and the target
# under test. Triage, not a gate — it emits a per-line issue list. For Malayalam the user is the ground
# truth (they hear every line); the machine's unique value is the Tamil gloss they cannot check.
# no_relocation was cut (Occam): it duplicated translate_prompt's TRANSLATE-DON'T-RELOCATE rule, guards
# the single most human-trivially-visible error (a relocated proper noun), and never fired.
TRANSLATION_VERIFY_DIMENSIONS = ("fidelity", "disambiguation_carried", "naturalness")

# Script-agnostic sentence-final marks: '.', '!', '?' plus the Devanagari danda/double-danda. The
# Danish _MULTI_SENTENCE_RE keys on a following CAPITAL, which Indic scripts do not have — so it is
# blind to a two-sentence Malayalam/Tamil line. This flags a sentence-final mark followed by more text.
_SENT_FINAL_RE = re.compile(r"[.!?।॥][\"»«')\]]?\s+\S")


def _multi_sentence_lines_generic(lines: list[str]) -> list[int]:
    """1-based indices of target-language lines that appear to hold more than one sentence.

    Script-agnostic (no capital-letter cue): a sentence-final mark followed by whitespace and more
    content. The period is abbreviation-guarded (reuses _ABBREVS + the single-initial rule); the Indic
    danda is unambiguous. Advisory triage — points the ear at a line, does not hard-gate the audio.
    """
    out = []
    for i, ln in enumerate(lines):
        for m in _SENT_FINAL_RE.finditer(ln):
            if ln[m.start()] == ".":
                before = ln[:m.start()].lower()
                if any(before.endswith(a) for a in _ABBREVS) or re.search(r"(?:^|\s)\w$", before):
                    continue
            out.append(i + 1)
            break
    return out


def verify_translation_prompt(*, src_lang: str, tgt_lang: str, ref_lang: str, en_lines: list[str],
                              ref_lines: list[str], tgt_lines: list[str], context: str = "") -> str:
    """Build the independent translation-QA prompt (also used by --show-prompt).

    Adversarial framing on purpose: the same model family produced the translation, so a neutral
    "score this" invites rubber-stamping. It is told to hunt for the mistranslation but to report a
    line only when it genuinely fails the dimension's threshold.
    """
    triples = "\n".join(
        f"{i+1}. {src_lang}: {e}    {ref_lang}: {r}    {tgt_lang}: {t}"
        for i, (e, r, t) in enumerate(zip(en_lines, ref_lines, tgt_lines)))
    return f"""You are an INDEPENDENT reviewer checking a {tgt_lang} translation for a graded language course. Hunt for mistranslations — do not rubber-stamp — but report a line ONLY when it genuinely fails the dimension's threshold as written. Cite the offending line by number.

Meaning comes from the {src_lang} source. The {ref_lang} column is a DISAMBIGUATION REFERENCE: the same line in a language that marks distinctions {src_lang} drops. Where the two differ, {src_lang} sets the meaning and {ref_lang} sets the distinction.
{f'Scene context: {context}' if context else ''}

LINES ({src_lang} source / {ref_lang} reference / {tgt_lang} under test):
{triples}

Score each dimension. For each: pass = true/false, and list specific issues as {{line, problem}}.
1. fidelity — does each {tgt_lang} line convey the meaning of its {src_lang} source? Flag SUBSTANTIVE divergence — added, dropped, or mistranslated meaning — NOT defensible word/preposition choices or natural rewordings that keep the meaning.
2. disambiguation_carried — where the {ref_lang} line marks a distinction {src_lang} leaves open (gender, formal/informal "you", number), does the {tgt_lang} line carry that SAME distinction wherever {tgt_lang} grammatically marks it? Flag a line that picks the wrong gender/register/number, or defaults to one when {ref_lang} clearly marks the other. Ignore distinctions {tgt_lang} does not mark.
3. naturalness — would a native {tgt_lang} speaker actually say this? Flag translationese (word-for-word from {src_lang}), constructions a native would not use, and register that jumps around from line to line. Do NOT flag mere taste.

Return JSON exactly:
{{"fidelity": {{"pass": true, "issues": []}},
 "disambiguation_carried": {{"pass": true, "issues": []}},
 "naturalness": {{"pass": true, "issues": []}}}}
(Use false and fill issues where there are problems; each issue is {{"line": <int>, "problem": "<text>"}}.)"""


def verify_translation(client, *, model: str, src_lang: str, tgt_lang: str, ref_lang: str,
                       en_lines: list[str], ref_lines: list[str], tgt_lines: list[str],
                       context: str = "") -> dict:
    """Programmatic checks + an independent LLM review of one translated scene. Returns a report dict.

    Deterministic gates run always; the LLM review runs only when the three columns are aligned (an
    unaligned zip would silently drop lines). Triage output — nothing here blocks the pipeline.
    """
    # Quote+attribution lines («"Hello!" she says.») are ONE utterance, but the script-agnostic detector
    # has no speech-verb exemption (the Danish one does) and trips on them. The source is guaranteed
    # one-sentence-per-line upstream, yet the SAME detector trips on its attribution lines too — so use
    # the source's trips as a false-positive mask: flag a target line only if its aligned source is clean.
    src_mask = set(_multi_sentence_lines_generic(en_lines))
    multi = [i for i in _multi_sentence_lines_generic(tgt_lines) if i not in src_mask]
    empties = [i + 1 for i, t in enumerate(tgt_lines) if not t.strip()]
    echoes = [i + 1 for i, (e, t) in enumerate(zip(en_lines, tgt_lines))
              if t.strip() and t.strip() == e.strip()]      # target parroted the English (untranslated)
    report = {
        "aligned": len(en_lines) == len(ref_lines) == len(tgt_lines),
        "counts": {"src": len(en_lines), "ref": len(ref_lines), "tgt": len(tgt_lines)},
        "one_per_line": not multi,
        "multi_sentence_lines": multi,
        "empty_lines": empties,
        "echoed_source_lines": echoes,
    }
    if report["aligned"]:
        prompt = verify_translation_prompt(src_lang=src_lang, tgt_lang=tgt_lang, ref_lang=ref_lang,
                                           en_lines=en_lines, ref_lines=ref_lines, tgt_lines=tgt_lines,
                                           context=context)
        report["llm"] = _json_call(client, model, prompt)
    return report


def print_translation_report(rep: dict, *, label: str = "") -> int:
    """Pretty-print a translation-verify report; return the number of flagged issues (0 = clean)."""
    n = 0
    if label:
        print(label)
    if not rep["aligned"]:
        c = rep["counts"]
        print(f"  alignment: FAIL (src {c['src']} / ref {c['ref']} / tgt {c['tgt']} lines) — LLM review skipped")
        return 1
    for tag, lines in (("multi-sentence", rep["multi_sentence_lines"]),
                       ("empty", rep["empty_lines"]), ("untranslated echo", rep["echoed_source_lines"])):
        if lines:
            n += len(lines)
            print(f"  {tag}: line(s) {', '.join(str(x) for x in lines)}")
    llm = rep.get("llm", {})
    for dim in TRANSLATION_VERIFY_DIMENSIONS:
        d = llm.get(dim, {}) or {}
        issues = d.get("issues") or []
        if not d.get("pass", True) or issues:
            print(f"  {dim}: {'PASS' if d.get('pass') else 'FLAG'}")
            for iss in issues:
                n += 1
                print(f"      - line {iss.get('line', '?')}: {iss.get('problem', '')}")
    if n == 0:
        print("  clean ✓")
    return n


def format_translation_flags(rep: dict, *, src_lang: str = "the source",
                             tgt_lang: str = "the target") -> str:
    """A translation-verify report as a concrete fix-list to feed revise_translation. '' if clean.

    Pulls every flag the report raised — the deterministic ones (multi-sentence / empty / echoed) and
    each LLM dimension's {line, problem} issues. Unlike format_failures there is no hard/advisory split:
    translation verify is triage, so a caller that asks to fix acts on all of it.
    """
    out: list[str] = []
    for i in rep.get("multi_sentence_lines", []):
        out.append(f"- Line {i} reads as more than one sentence; render its single source line as "
                   f"exactly ONE {tgt_lang} sentence (do not change the line count).")
    for i in rep.get("empty_lines", []):
        out.append(f"- Line {i} is empty; provide the {tgt_lang} translation.")
    for i in rep.get("echoed_source_lines", []):
        out.append(f"- Line {i} is still in {src_lang} (untranslated); translate it into {tgt_lang}.")
    llm = rep.get("llm", {})
    for dim in TRANSLATION_VERIFY_DIMENSIONS:
        d = llm.get(dim) or {}
        for iss in (d.get("issues") or []):
            out.append(f"- Line {iss.get('line', '?')} [{dim}]: {iss.get('problem', '')}")
    return "\n".join(out)


def revise_translation_prompt(*, src_lang: str, tgt_lang: str, ref_lang: str, en_lines: list[str],
                              ref_lines: list[str], tgt_lines: list[str], feedback: str,
                              context: str = "") -> str:
    """Build the translation-revise prompt: a flagged target + the problems to fix (also --show-prompt).

    Same trio the verifier saw. The count is LOCKED — the target stays 1:1 with the (already-correct)
    source, so unlike revise_prompt this must NOT split or merge lines. Deliberately NO story bible
    (Occam): that is authoring context for generating Danish; a translation fix needs only the source,
    the disambiguation reference, and the flagged problem — the Danish line already carries gender/name.
    """
    triples = "\n".join(f"{i+1}. {src_lang}: {e}    {ref_lang}: {r}    {tgt_lang}: {t}"
                        for i, (e, r, t) in enumerate(zip(en_lines, ref_lines, tgt_lines)))
    return f"""A {tgt_lang} translation for this course was reviewed and some lines were flagged. Fix ONLY the flagged problems; keep every unflagged line EXACTLY as it is. {src_lang} sets the meaning; the {ref_lang} column resolves distinctions {src_lang} drops — gender, formal vs informal "you", number — so carry those into {tgt_lang} wherever it marks them.
{f'Scene context: {context}' if context else ''}

DRAFT ({src_lang} source / {ref_lang} reference / {tgt_lang} under review):
{triples}

PROBLEMS TO FIX:
{feedback}

Return JSON: {{"lines": ["...", ...]}} with EXACTLY {len(tgt_lines)} entries — the {tgt_lang} translation only, one per source line, in order. Do NOT merge, split, add, or drop lines; the count must stay {len(tgt_lines)}."""


def revise_translation(client, *, model: str, src_lang: str, tgt_lang: str, ref_lang: str,
                       en_lines: list[str], ref_lines: list[str], tgt_lines: list[str],
                       feedback: str, context: str = "") -> list[str]:
    """Revise a flagged translation to fix its issues, keeping the rest. Returns the corrected lines.

    Raises SystemExit if the model changes the line count (the target must stay aligned to the source).
    """
    prompt = revise_translation_prompt(src_lang=src_lang, tgt_lang=tgt_lang, ref_lang=ref_lang,
                                       en_lines=en_lines, ref_lines=ref_lines, tgt_lines=tgt_lines,
                                       feedback=feedback, context=context)
    out = _json_call(client, model, prompt)
    res = out.get("lines", [])
    if len(res) != len(tgt_lines):
        raise SystemExit(f"Alignment broken: {len(tgt_lines)} in vs {len(res)} out.")
    return res


_HARD_DIMS = tuple(d for d in VERIFY_DIMENSIONS if d not in ADVISORY_DIMS)


def format_failures(rep: dict) -> str:
    """The HARD failures in a verify report as a concrete fix-list, for feeding into a revise retry.

    Pulls from what each gate already reports — alignment counts, multi-sentence line numbers, and the
    failing hard dimensions' {line, problem} issues. Advisory dims (they don't gate) are not included.
    Returns '' if nothing hard-failed.
    """
    out: list[str] = []
    if not rep.get("aligned", True):
        out.append(f"- The DA and EN had different line counts (DA {rep.get('da_lines')}, "
                   f"EN {rep.get('en_lines')}). Return the SAME number of lines, aligned one-for-one.")
    multi = rep.get("multi_sentence_lines") or []
    if multi:
        nums = ", ".join(str(n) for n in multi)
        out.append(f"- Line(s) {nums} hold more than one sentence. Put exactly ONE sentence per line, "
                   f'splitting quoted sentences too (e.g. "Hej, mor. Hej, far." becomes two lines).')
    llm = rep.get("llm", {})
    for d in _HARD_DIMS:
        dd = llm.get(d) or {}
        if not dd.get("pass", True):
            for iss in (dd.get("issues") or []):
                out.append(f"- {d}: line {iss.get('line', '?')} — {iss.get('problem', '')}")
    return "\n".join(out)


def parse_storyboard_header(path: str | Path) -> dict:
    """Parse the storyboard's header block into the week's generation spec.

    The header (everything before the scene table) carries the per-week spec as bold fields,
    e.g. ``**Level:** A1 · **Grammar:** … · **New words:** ~40 … · **Lines/scene:** ~12``.
    This is the single machine-read source for the week's grammar/level/budget — gen_week reads
    it instead of hardcoding constants, so the spec lives in exactly one place.
    """
    text = Path(path).read_text(encoding="utf-8")
    head = text.split("|", 1)[0]                    # everything before the table
    flat = " ".join(head.split())                   # collapse wrapped lines
    fields: dict[str, str] = {}
    for m in re.finditer(r"\*\*([^:*]+):\*\*\s*(.*?)(?=\*\*[^:*]+:\*\*|$)", flat):
        fields[m.group(1).strip().lower()] = m.group(2).strip().strip("·").strip()

    title_m = re.search(r"Week\s+(\d+)", flat)
    return {
        "week": int(title_m.group(1)) if title_m else None,
        "level": fields.get("level", "A1"),
        "grammar": fields.get("grammar", ""),
    }


def parse_storyboard(path: str | Path) -> list[dict]:
    """Parse a storyboard markdown table into rows: {num, stem, title, scene}."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or not cells[0].isdigit():
            continue
        num, stem, scene = int(cells[0]), cells[1], cells[2]
        title = stem.split("_", 1)[1].replace("_", " ").title() if "_" in stem else stem.title()
        rows.append({"num": num, "stem": stem, "title": title, "scene": scene})
    return rows


def _resolve_scene(args) -> tuple:
    """Return (title, scene, arc, scene_num, stem) from --storyboard/--scene-num or explicit flags."""
    if args.storyboard:
        if not args.scene_num:
            raise SystemExit("--scene-num is required with --storyboard")
        arc = parse_storyboard(args.storyboard)
        row = next((r for r in arc if r["num"] == args.scene_num), None)
        if row is None:
            raise SystemExit(f"scene {args.scene_num} not found in {args.storyboard}")
        return row["title"], row["scene"], arc, args.scene_num, row["stem"]
    if not (args.scene_title and args.scene):
        raise SystemExit("provide --scene-title and --scene, or --storyboard and --scene-num")
    return args.scene_title, args.scene, None, None, None


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tandem.gen", description="Gemini script generation + translation.")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model (default: {DEFAULT_MODEL})")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("scene", help="author a graded DA+EN scene")
    g.add_argument("--week", type=int, required=True)
    g.add_argument("--level", default="A1")
    g.add_argument("--scene-title", help="scene title (or use --storyboard/--scene-num)")
    g.add_argument("--scene", help="scene description (or use --storyboard/--scene-num)")
    g.add_argument("--storyboard", help="storyboard .md to draw the scene + the week's arc from")
    g.add_argument("--scene-num", type=int, help="which scene number within the storyboard")
    g.add_argument("--grammar", required=True)
    g.add_argument("--out-stem", help="writes <stem>.da and <stem>.en (default: storyboard dir/stem)")
    g.add_argument("--show-prompt", action="store_true",
                   help="print the exact prompt and exit (no API call, no credentials needed)")

    t = sub.add_parser("translate", help="context-rich, alignment-preserving translation")
    t.add_argument("--src", required=True)
    t.add_argument("--tgt", required=True)
    t.add_argument("--in", dest="infile", required=True)
    t.add_argument("--out", help="output file (required unless --show-prompt)")
    t.add_argument("--context", default="")
    t.add_argument("--level", default="")
    t.add_argument("--glossary", default="")
    t.add_argument("--show-prompt", action="store_true",
                   help="print the exact prompt and exit (no API call, no credentials needed)")

    v = sub.add_parser("verify", help="QA a generated scene against its spec (exit 1 on failure)")
    v.add_argument("--da", required=True, help="generated Danish file")
    v.add_argument("--en", required=True, help="generated English file")
    v.add_argument("--level", default="A1")
    v.add_argument("--grammar", required=True, help="grammar allowed this week (the whitelist)")
    v.add_argument("--show-prompt", action="store_true",
                   help="print the exact prompt and exit (no API call, no credentials needed)")

    args = p.parse_args(argv)

    scene_title = scene = arc = scene_num = stem = None
    if args.cmd == "scene":
        scene_title, scene, arc, scene_num, stem = _resolve_scene(args)

    if getattr(args, "show_prompt", False):
        if args.cmd == "scene":
            print(scene_prompt(week=args.week, level=args.level, scene_title=scene_title,
                               scene=scene, grammar=args.grammar,
                               arc=arc, scene_num=scene_num))
        elif args.cmd == "translate":
            lines = [ln for ln in Path(args.infile).read_text(encoding="utf-8").splitlines() if ln.strip()]
            print(translate_prompt(src_lang=args.src, tgt_lang=args.tgt, lines=lines,
                                   context=args.context, level=args.level, glossary=args.glossary))
        elif args.cmd == "verify":
            da = [ln for ln in Path(args.da).read_text(encoding="utf-8").splitlines() if ln.strip()]
            en = [ln for ln in Path(args.en).read_text(encoding="utf-8").splitlines() if ln.strip()]
            print(verify_prompt(level=args.level, grammar=args.grammar, da_lines=da, en_lines=en))
        return 0

    client = make_client()

    if args.cmd == "scene":
        out_stem = args.out_stem or (str(Path(args.storyboard).parent / stem)
                                     if (args.storyboard and stem) else None)
        if not out_stem:
            raise SystemExit("--out-stem is required (unless --show-prompt or --storyboard).")
        res = generate_scene(
            client, model=args.model, week=args.week, level=args.level,
            scene_title=scene_title, scene=scene, grammar=args.grammar,
            arc=arc, scene_num=scene_num,
        )
        _write_lines(Path(out_stem + ".da"), res["da"])
        _write_lines(Path(out_stem + ".en"), res["en"])
        print(f"Wrote {out_stem}.da and .en ({len(res['da'])} aligned lines).", file=sys.stderr)
    elif args.cmd == "translate":
        if not args.out:
            raise SystemExit("--out is required (unless --show-prompt).")
        lines = [ln for ln in Path(args.infile).read_text(encoding="utf-8").splitlines() if ln.strip()]
        res = translate_lines(
            client, model=args.model, src_lang=args.src, tgt_lang=args.tgt, lines=lines,
            context=args.context, level=args.level, glossary=args.glossary,
        )
        _write_lines(Path(args.out), res)
        print(f"Wrote {args.out} ({len(res)} lines, {args.src}→{args.tgt}).", file=sys.stderr)
    elif args.cmd == "verify":
        da = [ln for ln in Path(args.da).read_text(encoding="utf-8").splitlines() if ln.strip()]
        en = [ln for ln in Path(args.en).read_text(encoding="utf-8").splitlines() if ln.strip()]
        rep = verify_scene(client, model=args.model, level=args.level, grammar=args.grammar,
                           da_lines=da, en_lines=en)
        print(f"Verifying {args.da} (level {args.level}):", file=sys.stderr)
        ok = print_verify_report(rep)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
