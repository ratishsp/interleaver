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
  python -m tandem.gen scene --week 1 --scene-title "Arrival" --beat "Maya lands in Copenhagen" \\
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

DEFAULT_MODEL = "gemini-2.5-pro"

# The fixed world every prompt shares, so referents / gender / continuity stay consistent.
STORY_BIBLE = (
    "Story world: The protagonist is Maya, a 31-year-old woman from Mexico, spending her first year "
    "in Copenhagen, Denmark. She has moved to Copenhagen for a fresh start and is gradually settling "
    "in. She grew up in a warm climate, so the cold Danish winter is new to her. "
    "Recurring cast: Nina (a Danish neighbour who gradually becomes Maya's friend) and her family "
    "back home in Mexico (video calls)."
)


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


def _json_call(client, model: str, prompt: str) -> dict:
    """Call the model forcing a JSON object response and parse it.

    Temperature is left UNSET so the model's own default applies (1.0 for current Gemini, which
    Google recommends across both 2.x and 3.x). This keeps the pipeline model-agnostic — no temp to
    retune when swapping models — and avoids Gemini 3's looping/degradation risk from sub-1.0 temps.
    """
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    text = (resp.text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Model did not return valid JSON:\n{text[:500]}\n---\n{exc}")


def scene_prompt(*, week: int, level: str, scene_title: str, beat: str, grammar: str,
                 lines: int, arc: list | None = None, scene_num: int | None = None) -> str:
    """Build the exact generation prompt (also used by --show-prompt for inspection).

    `lines` is accepted for caller compatibility but is no longer fed to the generator as a
    target — scene length follows the beat, not a quota (the storyboard's Lines/scene is advisory).
    """
    del lines  # intentionally not surfaced to the model
    arc_block = ""
    if arc:
        rows = "\n".join(
            f'  {a["num"]}. {a["title"]} — {a["beat"]}'
            + ("   ← WRITE THIS SCENE" if a["num"] == scene_num else "")
            for a in arc)
        arc_block = ("\nThis week's arc (write ONLY the marked scene; do not cover other scenes' "
                     "beats or bring in characters who first appear in a later scene):\n" + rows + "\n")
    return f"""{STORY_BIBLE}

TASK: Write ONE short scene for WEEK {week} (CEFR level {level}) of the Danish course.
Scene title: "{scene_title}". Narrative beat: {beat}
{arc_block}
The Danish is what's being learned — author it natively and idiomatically; the English is a faithful, natural gloss.

- Level {level}, this week's grammar: {grammar} (earlier-week grammar may recur). Author natural Danish first — it may sit slightly above {level} where that's what's natural, but don't reach clearly beyond it.
- Tell it as Maya's own first-person account; attribute any quoted speech so it's clear who's speaking.
- One sentence per line in both arrays; let the scene run as long as the beat naturally needs — no padding, no quota. The "da" and "en" arrays MUST have the same number of entries, aligned line-for-line.

Return JSON: {{"da": [...], "en": [...]}}, same number of entries in each."""


def generate_scene(client, *, model: str, week: int, level: str, scene_title: str, beat: str,
                   grammar: str, lines: int, arc: list | None = None,
                   scene_num: int | None = None) -> dict:
    """Author a graded scene natively in Danish + an English gloss. Returns {'da': [...], 'en': [...]}."""
    prompt = scene_prompt(week=week, level=level, scene_title=scene_title, beat=beat,
                          grammar=grammar, lines=lines, arc=arc, scene_num=scene_num)
    out = _json_call(client, model, prompt)
    da, en = out.get("da", []), out.get("en", [])
    if len(da) != len(en):
        raise SystemExit(f"Alignment broken: {len(da)} DA lines vs {len(en)} EN lines.")
    return {"da": da, "en": en}


def revise_prompt(*, level: str, grammar: str, beat: str, da_lines: list[str],
                  en_lines: list[str], feedback: str) -> str:
    """Build the revise prompt: a rejected draft + the QA problems to fix (also used by --show-prompt)."""
    pairs = "\n".join(f"{i+1}. DA: {d}    EN: {e}"
                      for i, (d, e) in enumerate(zip(da_lines, en_lines)))
    return f"""{STORY_BIBLE}

A draft scene for this Danish course (CEFR level {level}) was rejected by QA. Fix ONLY the problems listed below; keep everything else — the story, the line order, and every line that wasn't flagged — unchanged.

Scene beat (for context): {beat}
Level {level}; this week's grammar: {grammar}.

DRAFT (line-aligned Danish / English):
{pairs}

PROBLEMS TO FIX:
{feedback}

Return the FULL corrected scene as JSON: {{"da": [...], "en": [...]}} — one sentence per line, the two arrays the same length and aligned line-for-line. Splitting a line to fix it changes the line count; that's fine, just keep "da" and "en" aligned."""


def revise_scene(client, *, model: str, level: str, grammar: str, beat: str,
                 da_lines: list[str], en_lines: list[str], feedback: str) -> dict:
    """Revise a rejected draft to fix the QA problems, keeping the rest. Returns {'da': [...], 'en': [...]}."""
    prompt = revise_prompt(level=level, grammar=grammar, beat=beat,
                           da_lines=da_lines, en_lines=en_lines, feedback=feedback)
    out = _json_call(client, model, prompt)
    da, en = out.get("da", []), out.get("en", [])
    if len(da) != len(en):
        raise SystemExit(f"Alignment broken: {len(da)} DA lines vs {len(en)} EN lines.")
    return {"da": da, "en": en}


def translate_prompt(*, src_lang: str, tgt_lang: str, lines: list[str], context: str = "",
                     level: str = "", glossary: str = "") -> str:
    """Build the exact translation prompt (also used by --show-prompt for inspection)."""
    numbered = "\n".join(f"{i+1}. {ln}" for i, ln in enumerate(lines))
    return f"""{STORY_BIBLE}

TASK: Translate the following {len(lines)} lines from {src_lang} into {tgt_lang} for this course.
{f'Scene context: {context}' if context else ''}
{f'Target CEFR level: {level} — keep the translation in-level, do not drift up or down.' if level else ''}

RULES:
- Translate naturally and idiomatically in {tgt_lang}; avoid word-for-word translationese.
- PHASE-1 POLICY = TRANSLATE, DO NOT RELOCATE. Keep the Danish setting and Danish-specific terms (e.g. SKAT, hygge, Janteloven, CPR, MitID, København) — render them naturally, do NOT swap them for the target culture's equivalents.
- Keep names consistent.{f' Glossary: {glossary}' if glossary else ''}
- Preserve sentence segmentation EXACTLY: return the SAME number of lines ({len(lines)}), one translation per input line, in order. Do not merge or split lines.

INPUT:
{numbered}

Return JSON: {{"lines": ["...", ...]}} with exactly {len(lines)} entries, in order."""


def translate_lines(client, *, model: str, src_lang: str, tgt_lang: str, lines: list[str],
                    context: str = "", level: str = "", glossary: str = "") -> list[str]:
    """Context-rich, alignment-preserving translation of `lines` from src_lang to tgt_lang."""
    prompt = translate_prompt(src_lang=src_lang, tgt_lang=tgt_lang, lines=lines,
                              context=context, level=level, glossary=glossary)
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
# quote followed by the English attribution "I" ('"...?" I ask') all produce "mark + space +
# Capital" but are NOT sentence breaks, so they're excluded below.
# The capital may be preceded by an OPENING quote — a new sentence that begins with quoted speech
# ('... siger hun. "Hvad hedder du?"') is still a sentence break.
_MULTI_SENTENCE_RE = re.compile(r"[.!?][\"»«')\]]?\s+[\"«»']?[A-ZÆØÅ]")
_ABBREVS = ("f.eks", "bl.a", "m.m", "m.fl", "d.v.s", "dvs", "osv", "ca", "kl", "nr", "stk",
            "o.l", "inkl", "ekskl", "tlf", "jf", "pga", "evt")


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
            # Quoted speech + English "I" attribution — «"...?" I ask» is one utterance (one audio
            # bead), not two sentences. Skip ONLY when a closing quote precedes the capital; a bare
            # «. I left.» (no quote) is a real break and still flags.
            quoted = ln[m.start() + 1] in "\"»«')]"
            cap_is_I = ln[m.end() - 1] == "I" and (m.end() >= len(ln) or ln[m.end()] in " \t")
            if quoted and cap_is_I:
                continue
            out.append(i + 1)
            break
    return out

# Dimensions the LLM reviewer scores (order = display order).
VERIFY_DIMENSIONS = ("grammar_whitelist", "cefr_level", "content_neutral", "naturalness",
                     "gloss_fidelity")
# Advisory dims are reported but never block/retry; everything else (+ alignment) is a hard gate.
# grammar_whitelist = scope (correct-but-slightly-advanced Danish is fine); cefr_level = exact level.
ADVISORY_DIMS = ("grammar_whitelist", "cefr_level")

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
2. cefr_level — is the sentence length and complexity appropriate to {level}? Flag ONLY lines whose complexity clearly EXCEEDS {level}; simplicity that fits {level} is expected, not a defect. (Word frequency is checked separately — ignore it here.) Also state, as `assessed_level`, the CEFR level the scene's complexity actually reads as.
3. content_neutral — is it about ordinary life and NOT about learning a language? Flag any language school, language class, or "learning/practising Danish" content.
4. naturalness — would a native speaker actually say this? Flag ONLY lines that are CLEARLY wrong: translationese (word-for-word from English), constructions a native would not use, or errors that make it sound foreign. Do NOT flag matters of taste — register ("too abrupt/formal"), rhetorical choices, or a line you would merely phrase differently. If a native could naturally say it, it passes — reserve a fail for genuinely un-native Danish.
5. gloss_fidelity — does each English line convey the meaning of its Danish line? The English is the pivot ~100 other languages are translated from, so a wrong gloss propagates everywhere. Flag ONLY SUBSTANTIVE divergence — added, dropped, or mistranslated meaning — NOT defensible word or preposition choices (e.g. "ved" as "at" vs "by") or natural rewordings that keep the meaning.

Return JSON exactly:
{{"grammar_whitelist": {{"pass": true, "issues": []}},
 "cefr_level": {{"pass": true, "assessed_level": "{level}", "issues": []}},
 "content_neutral": {{"pass": true, "issues": []}},
 "naturalness": {{"pass": true, "issues": []}},
 "gloss_fidelity": {{"pass": true, "issues": []}}}}
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
        d = llm.get(dim, {}) or {}
        passed = bool(d.get("pass", False))
        advisory = dim in ADVISORY_DIMS
        if not advisory:                       # only hard dims (+ alignment) gate the overall result
            ok = ok and passed
        tag = " [advisory]" if advisory else ""
        extra = f" [assessed {d.get('assessed_level')}]" if dim == "cefr_level" and d.get("assessed_level") else ""
        print(f"  {dim}: {'PASS' if passed else 'FAIL'}{tag}{extra}")
        for iss in (d.get("issues") or []):
            print(f"      - line {iss.get('line', '?')}: {iss.get('problem', '')}")
    print(f"  OVERALL: {'PASS ✓' if ok else 'FAIL ✗'}")
    return ok


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

    def _int(s: str, default: int) -> int:
        m = re.search(r"\d+", s or "")
        return int(m.group()) if m else default

    title_m = re.search(r"Week\s+(\d+)", flat)
    return {
        "week": int(title_m.group(1)) if title_m else None,
        "level": fields.get("level", "A1"),
        "grammar": fields.get("grammar", ""),
        "lines": _int(fields.get("lines/scene", ""), 12),
    }


def parse_storyboard(path: str | Path) -> list[dict]:
    """Parse a storyboard markdown table into rows: {num, stem, title, beat}."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or not cells[0].isdigit():
            continue
        num, stem, beat = int(cells[0]), cells[1], cells[2]
        title = stem.split("_", 1)[1].replace("_", " ").title() if "_" in stem else stem.title()
        rows.append({"num": num, "stem": stem, "title": title, "beat": beat})
    return rows


def _resolve_scene(args) -> tuple:
    """Return (title, beat, arc, scene_num, stem) from --storyboard/--scene-num or explicit flags."""
    if args.storyboard:
        if not args.scene_num:
            raise SystemExit("--scene-num is required with --storyboard")
        arc = parse_storyboard(args.storyboard)
        row = next((r for r in arc if r["num"] == args.scene_num), None)
        if row is None:
            raise SystemExit(f"scene {args.scene_num} not found in {args.storyboard}")
        return row["title"], row["beat"], arc, args.scene_num, row["stem"]
    if not (args.scene_title and args.beat):
        raise SystemExit("provide --scene-title and --beat, or --storyboard and --scene-num")
    return args.scene_title, args.beat, None, None, None


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
    g.add_argument("--beat", help="narrative beat (or use --storyboard/--scene-num)")
    g.add_argument("--storyboard", help="storyboard .md to draw the scene + the week's arc from")
    g.add_argument("--scene-num", type=int, help="which scene number within the storyboard")
    g.add_argument("--grammar", required=True)
    g.add_argument("--lines", type=int, default=12)
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

    scene_title = beat = arc = scene_num = stem = None
    if args.cmd == "scene":
        scene_title, beat, arc, scene_num, stem = _resolve_scene(args)

    if getattr(args, "show_prompt", False):
        if args.cmd == "scene":
            print(scene_prompt(week=args.week, level=args.level, scene_title=scene_title,
                               beat=beat, grammar=args.grammar, lines=args.lines,
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
            scene_title=scene_title, beat=beat, grammar=args.grammar,
            lines=args.lines, arc=arc, scene_num=scene_num,
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
