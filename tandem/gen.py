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
      --grammar "present være/hedde/komme fra; pronouns; hvad/hvor; V2" --new-words 40 --lines 14 \\
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
    "Story world: A graded comprehensible-input language course. The protagonist is Maya, a "
    "31-year-old woman from Mexico, spending her first year in "
    "Copenhagen, Denmark. She has moved to Copenhagen for a fresh start; she arrives knowing almost "
    "no one and gradually settles in — making friends, finding her way around the city, everyday "
    "life. She grew up in a warm climate, so the cold, dark Danish winter is new to her. Recurring "
    "cast: Mette (a Danish friend and neighbour) and her family back home in Mexico (video calls)."
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
    """Call the model forcing a JSON object response and parse it."""
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )
    text = (resp.text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Model did not return valid JSON:\n{text[:500]}\n---\n{exc}")


def scene_prompt(*, week: int, level: str, scene_title: str, beat: str, grammar: str,
                 new_words: int, lines: int, prior_vocab: str = "", arc: list | None = None,
                 scene_num: int | None = None) -> str:
    """Build the exact generation prompt (also used by --show-prompt for inspection)."""
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
AUTHOR THE DANISH NATIVELY AND IDIOMATICALLY — it is the language being learned, so it must be
native-quality and exactly in-level. The English is a faithful, natural gloss of the Danish.

HARD GRADING CONSTRAINTS (this is what 'graded' means — obey strictly):
- Grammar allowed this week ONLY: {grammar}. Do NOT use grammar beyond this (no past tense, no
  modals, no subordinate clauses unless listed above). Earlier-week grammar may recur.
- Vocabulary: about {new_words} distinct content words for the whole week; keep this scene to a
  small, high-frequency slice. Prefer the most common everyday Danish words.
{f'- Vocabulary already introduced (reuse freely, keep recycling): {prior_vocab}' if prior_vocab else ''}
- Sentences must be SHORT and simple ({level} = very simple at A1).
- Exactly {lines} lines. ONE sentence per line. The DA and EN arrays MUST have the same number of
  entries and align line-for-line (line i of EN is the translation of line i of DA).
- Natural spoken register; a little dialogue is good.
- Write a small coherent narrative that follows the beat — connected and flowing, not a list of
  disconnected facts. Keep a warm, natural first-person voice, and only introduce characters the
  beat calls for.

Return JSON: {{"da": ["...", ...], "en": ["...", ...]}} with exactly {lines} entries each."""


def generate_scene(client, *, model: str, week: int, level: str, scene_title: str, beat: str,
                   grammar: str, new_words: int, lines: int, prior_vocab: str = "",
                   arc: list | None = None, scene_num: int | None = None) -> dict:
    """Author a graded scene natively in Danish + an English gloss. Returns {'da': [...], 'en': [...]}."""
    prompt = scene_prompt(week=week, level=level, scene_title=scene_title, beat=beat,
                          grammar=grammar, new_words=new_words, lines=lines, prior_vocab=prior_vocab,
                          arc=arc, scene_num=scene_num)
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
- PHASE-1 POLICY = TRANSLATE, DO NOT RELOCATE. Keep the Danish setting and Danish-specific terms
  (e.g. SKAT, hygge, Janteloven, CPR, MitID, København) — render them naturally, do NOT swap them
  for the target culture's equivalents.
- Keep names consistent.{f' Glossary: {glossary}' if glossary else ''}
- Preserve sentence segmentation EXACTLY: return the SAME number of lines ({len(lines)}), one
  translation per input line, in order. Do not merge or split lines.

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

# Dimensions the LLM reviewer scores (order = display order).
VERIFY_DIMENSIONS = ("grammar_whitelist", "cefr_level", "content_neutral", "naturalness")


def _distinct_words(lines: list[str]) -> set[str]:
    words: set[str] = set()
    for ln in lines:
        words.update(w.lower() for w in _WORD_RE.findall(ln))
    return words


def verify_prompt(*, level: str, grammar: str, new_words: int, da_lines: list[str],
                  en_lines: list[str], cumulative_vocab: str = "") -> str:
    """Build the independent-QA prompt (also used by --show-prompt)."""
    pairs = "\n".join(f"{i+1}. DA: {d}    EN: {e}"
                      for i, (d, e) in enumerate(zip(da_lines, en_lines)))
    return f"""You are an INDEPENDENT QA reviewer for a graded Danish language course. Judge the scene
below against its spec. Be strict, concrete, and cite the offending Danish by line number. Do not be
generous — your job is to catch problems the writer missed.

SPEC:
- CEFR level: {level}
- Grammar FOCUS this week (the new structures introduced): {grammar}
- ALSO always allowed (never flag these): the basic function words every sentence needs — articles
  (en/et), conjunctions (og, men), common possessives (min/din/sin), prepositions, negation (ikke),
  and ordinary adverbs. Only count SUBSTANTIVE structures beyond the level as violations.
- Weekly new-word budget ≈ {new_words}; vocabulary should be high-frequency and appropriate for {level}.
{f'- Vocabulary already taught earlier (fine to reuse): {cumulative_vocab}' if cumulative_vocab else ''}

The Danish is the language being learned, so it must be native-quality and exactly in-level. The
English is only a gloss.

SCENE (line-aligned Danish / English):
{pairs}

Score each dimension. For each: pass = true/false, and list specific issues as {{line, problem}}.
1. grammar_whitelist — does every Danish line stay within the week's grammar? Flag ONLY substantive
   structures beyond the level: other tenses (past/perfect/future), modal verbs (kan/vil/skal/må/bør),
   subordinate or relative clauses, the passive, comparatives/superlatives. Do NOT flag basic function
   words (articles, og/men, min/din, prepositions, ikke) — those are always allowed.
2. cefr_level — is it genuinely {level} (sentence length, complexity, word frequency)? Flag lines
   that are too advanced — or so trivial they break the narrative.
3. content_neutral — is it about ordinary life and NOT about learning a language? Flag any language
   school, language class, or "learning/practising Danish" content.
4. naturalness — is the Danish idiomatic and native (not translationese)? Flag awkward/unnatural lines.

Return JSON exactly:
{{"grammar_whitelist": {{"pass": true, "issues": []}},
 "cefr_level": {{"pass": true, "assessed_level": "{level}", "issues": []}},
 "content_neutral": {{"pass": true, "issues": []}},
 "naturalness": {{"pass": true, "issues": []}}}}
(Use false and fill issues where there are problems; each issue is {{"line": <int>, "problem": "<text>"}}.)"""


def verify_scene(client, *, model: str, level: str, grammar: str, new_words: int,
                 da_lines: list[str], en_lines: list[str], cumulative_vocab: str = "") -> dict:
    """Programmatic checks + an independent LLM review. Returns a report dict."""
    report = {
        "aligned": len(da_lines) == len(en_lines),
        "da_lines": len(da_lines),
        "en_lines": len(en_lines),
        "distinct_da_words": len(_distinct_words(da_lines)),
    }
    prompt = verify_prompt(level=level, grammar=grammar, new_words=new_words,
                           da_lines=da_lines, en_lines=en_lines, cumulative_vocab=cumulative_vocab)
    report["llm"] = _json_call(client, model, prompt)
    return report


def print_verify_report(rep: dict) -> bool:
    """Pretty-print a verify report; return True iff everything passed."""
    ok = rep["aligned"]
    print(f"  alignment: {'OK' if rep['aligned'] else 'FAIL'} "
          f"(DA {rep['da_lines']} / EN {rep['en_lines']} lines)")
    print(f"  distinct Danish words: {rep['distinct_da_words']}")
    llm = rep.get("llm", {})
    for dim in VERIFY_DIMENSIONS:
        d = llm.get(dim, {}) or {}
        passed = bool(d.get("pass", False))
        ok = ok and passed
        extra = f" [assessed {d.get('assessed_level')}]" if dim == "cefr_level" and d.get("assessed_level") else ""
        print(f"  {dim}: {'PASS' if passed else 'FAIL'}{extra}")
        for iss in (d.get("issues") or []):
            print(f"      - line {iss.get('line', '?')}: {iss.get('problem', '')}")
    print(f"  OVERALL: {'PASS ✓' if ok else 'FAIL ✗'}")
    return ok


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
    g.add_argument("--new-words", type=int, default=40)
    g.add_argument("--lines", type=int, default=14)
    g.add_argument("--prior-vocab", default="")
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
    v.add_argument("--new-words", type=int, default=40)
    v.add_argument("--cumulative-vocab", default="")
    v.add_argument("--show-prompt", action="store_true",
                   help="print the exact prompt and exit (no API call, no credentials needed)")

    args = p.parse_args(argv)

    scene_title = beat = arc = scene_num = stem = None
    if args.cmd == "scene":
        scene_title, beat, arc, scene_num, stem = _resolve_scene(args)

    if getattr(args, "show_prompt", False):
        if args.cmd == "scene":
            print(scene_prompt(week=args.week, level=args.level, scene_title=scene_title,
                               beat=beat, grammar=args.grammar, new_words=args.new_words,
                               lines=args.lines, prior_vocab=args.prior_vocab,
                               arc=arc, scene_num=scene_num))
        elif args.cmd == "translate":
            lines = [ln for ln in Path(args.infile).read_text(encoding="utf-8").splitlines() if ln.strip()]
            print(translate_prompt(src_lang=args.src, tgt_lang=args.tgt, lines=lines,
                                   context=args.context, level=args.level, glossary=args.glossary))
        elif args.cmd == "verify":
            da = [ln for ln in Path(args.da).read_text(encoding="utf-8").splitlines() if ln.strip()]
            en = [ln for ln in Path(args.en).read_text(encoding="utf-8").splitlines() if ln.strip()]
            print(verify_prompt(level=args.level, grammar=args.grammar, new_words=args.new_words,
                                da_lines=da, en_lines=en, cumulative_vocab=args.cumulative_vocab))
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
            new_words=args.new_words, lines=args.lines, prior_vocab=args.prior_vocab,
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
                           new_words=args.new_words, da_lines=da, en_lines=en,
                           cumulative_vocab=args.cumulative_vocab)
        print(f"Verifying {args.da} (level {args.level}):", file=sys.stderr)
        ok = print_verify_report(rep)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
