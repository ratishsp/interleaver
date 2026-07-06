"""The ml/ta translation track: translate an English scene into another language (with the aligned
Danish as a disambiguation reference), then verify and revise that translation.

This is the second track bolted onto the original da/en generator in gen.py — a self-contained
subsystem that only borrows gen.py's shared infrastructure (the JSON call, the story bible, the
abbreviation list). Kept apart so gen.py stays the authoring/QA core and this stays the translation core.
"""
from __future__ import annotations
import re

from tandem.gen import load_story_bible, _ABBREVS
from tandem.llm import _json_call


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


# Translation verification — the mirror of gen.py's verify_scene, but for a TRANSLATED target
# (.ml/.ta/...): it sees the English source (meaning), the Danish reference (the distinctions English
# drops), and the target under test. Triage, not a gate — a per-line issue list. For Malayalam the user
# is ground truth (they hear every line); the machine's unique value is the Tamil gloss they cannot check.
# no_relocation was cut (Occam): it duplicated translate_prompt's TRANSLATE-DON'T-RELOCATE rule, guarded
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
