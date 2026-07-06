#!/usr/bin/env python3
"""Cross-week continuity check (read-only PROTOTYPE).

Reads every week's ENGLISH gloss (in scene order) + story_bible.md and hunts for CROSS-WEEK
contradictions — the gap neither verify_scene (per-scene, no cross-week view) nor review_storyboard
(design-time, briefs vs bible) covers. Four category lenses that actually bite an A1 slice-of-life arc:
absolute-time/season, character memory/re-introduction, nomenclature, quantitative. Every finding must
cite BOTH conflicting verbatim lines (ConStory-style) — a pair it can't produce is not reported, which
is the built-in false-positive guard. Never modifies content; prints findings + optional --out JSON.

Run:  set -a; . ./.env; set +a; export GOOGLE_CLOUD_LOCATION=global
      .venv/bin/python continuity_check.py [--weeks 1-10] [--out findings.json] [--model ...]
"""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import os
import re
from pathlib import Path

from tandem.gen import DEFAULT_MODEL, parse_storyboard
from tandem.llm import make_client
from review_storyboard import _call_findings, _SEV_RANK

YEAR = "year1"

COMMON = """You are a continuity editor for a graded Danish→English audio course told as Maya's
first-person story across many weeks. Below is the ENGLISH gloss of every scene so far, in order, each
block labelled [Week N · Scene M]. A separate per-scene check already vetted each scene in isolation —
YOUR job is CROSS-WEEK continuity: contradictions BETWEEN scenes in DIFFERENT weeks.

INTENDED TRUTH — what is canonical, and what is ALLOWED to change over time:
--- story_bible.md ---
{bible}
--- end bible ---
Use the bible to tell a real CONTRADICTION from a LEGITIMATE change the story intends (Maya moves from
a temporary flat to her own flat; her job is not-yet-started then started; winter deepens). A narrated
transition is NOT a contradiction.

THE FULL COURSE SO FAR:
{corpus}
"""

LENS = """
YOUR LENS: **{title}** — {focus}

Report ONLY cross-week contradictions in THIS lens. For each finding you MUST cite TWO real, VERBATIM
lines from DIFFERENT weeks that genuinely conflict. If you cannot produce both real quotes, do not
report it. Severity: High = a listener would notice a clear contradiction; Med = a real but minor
slip; Low = borderline.

Return ONLY a JSON object of this exact shape:
{{"findings": [{{"category": "{key}", "severity": "High" | "Med" | "Low",
  "fact_quote": "<verbatim line>", "location": "Week N · Scene M",
  "contradiction_quote": "<the conflicting verbatim line>", "contradiction_location": "Week K · Scene L",
  "why": "<1-2 sentences: what the contradiction is>"}}]}}
Use an empty findings list if you find nothing."""

CATEGORIES = [
    {"key": "absolute_time", "title": "Absolute time / season",
     "focus": "Season or time-of-year drift, or any named month. The course is deliberately all-winter "
              "through these weeks and NEVER names a month; spring comes much later. Flag a later week "
              "implying a warmer or different season than an earlier one, any explicitly named month, or "
              "a daylight/weather cue that contradicts the established winter. Winter simply deepening is fine."},
    {"key": "memory_knowledge", "title": "Memory & knowledge",
     "focus": "A person re-introduced as if newly met when an earlier week already established them (e.g. "
              "meeting Nina 'for the first time' after Week 1), or Maya knowing / not-knowing something "
              "inconsistent with an earlier week. A genuinely new acquaintance is fine."},
    {"key": "nomenclature", "title": "Names & roles",
     "focus": "A name spelled or rendered differently across weeks (e.g. Sofía vs Sofia), or a character's "
              "role/relationship stated inconsistently (e.g. Nina as neighbour in one week, colleague in another)."},
    {"key": "quantitative", "title": "Numbers",
     "focus": "A number that must stay fixed but changes across weeks — Maya's phone number, Nina's phone "
              "number, Maya's age, or a specific price/quantity restated inconsistently. Different numbers "
              "for different things are fine."},
    {"key": "other", "title": "Anything else (open — no checklist)",
     "focus": "ANY cross-week contradiction NOT already covered by the four specific lenses above "
              "(time/season, memory/knowledge, names/roles, numbers). Re-read the whole course as a "
              "sceptical continuity editor and hunt anything a later scene states that conflicts with an "
              "earlier one — an object or appearance detail (the colour of her suitcase, the layout of her "
              "flat), an action or its consequence, a place, a habit, a relationship, or a plot thread "
              "opened and then dropped or contradicted. The four categories are NOT exhaustive; trust your "
              "judgement about what counts as a genuine conflict. Name the real type in `why`."},
]


def discover_weeks() -> list[int]:
    out = []
    for d in sorted(Path(YEAR).glob("week*")):
        m = re.match(r"week(\d+)$", d.name)
        if m:
            out.append(int(m.group(1)))
    return out


def parse_weeks(s: str | None) -> list[int]:
    if not s:
        return discover_weeks()
    nums: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            nums.extend(range(int(a), int(b) + 1))
        elif part:
            nums.append(int(part))
    return nums


def assemble_corpus(weeks: list[int]) -> tuple[str, int]:
    parts, n_scenes = [], 0
    for w in weeks:
        d = Path(f"{YEAR}/week{w:02d}")
        sb = d / "storyboard.md"
        if sb.exists():
            order = [(r["num"], r["stem"]) for r in parse_storyboard(sb)]
        else:
            order = [(i + 1, p.stem) for i, p in enumerate(sorted(d.glob("*.en")))]
        for num, stem in order:
            en = d / f"{stem}.en"
            if not en.exists():
                continue
            text = en.read_text(encoding="utf-8").strip()
            parts.append(f"### [Week {w} · Scene {num} · {stem}]\n{text}")
            n_scenes += 1
    return "\n\n".join(parts), n_scenes


def build_prompt(cat: dict, *, bible: str, corpus: str) -> str:
    return COMMON.format(bible=bible, corpus=corpus) + LENS.format(**cat)


def run_lens(client, model: str, cat: dict, prompt: str) -> list[dict]:
    out = []
    for f in _call_findings(client, model, prompt):
        out.append({
            "category": (f.get("category") or cat["key"]).strip(),
            "lens": cat["title"],
            "severity": (f.get("severity") or "Med").strip().capitalize(),
            "fact_quote": (f.get("fact_quote") or "").strip(),
            "location": (f.get("location") or "?").strip(),
            "contradiction_quote": (f.get("contradiction_quote") or "").strip(),
            "contradiction_location": (f.get("contradiction_location") or "?").strip(),
            "why": (f.get("why") or "").strip(),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cross-week continuity check (read-only).")
    ap.add_argument("--weeks", help="e.g. '1-10' or '1,4,7' (default: all weeks found in year1/)")
    ap.add_argument("--bible", default="story_bible.md")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--location", default="global",
                    help="Vertex location (default 'global' — required for gemini-3 models)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", help="also write findings JSON here")
    args = ap.parse_args(argv)
    os.environ["GOOGLE_CLOUD_LOCATION"] = args.location

    weeks = parse_weeks(args.weeks)
    corpus, n_scenes = assemble_corpus(weeks)
    if not n_scenes:
        raise SystemExit(f"no English scenes found for weeks {weeks}")
    bible = Path(args.bible).read_text(encoding="utf-8") if Path(args.bible).exists() else "(no bible)"
    approx_words = len(corpus.split())
    print(f"Checking weeks {weeks[0]}–{weeks[-1]}: {n_scenes} scenes, ~{approx_words} words of English.\n")

    client = make_client()
    prompts = {c["key"]: build_prompt(c, bible=bible, corpus=corpus) for c in CATEGORIES}

    findings: list[dict] = []
    failed: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(run_lens, client, args.model, c, prompts[c["key"]]): c for c in CATEGORIES}
        for fut in concurrent.futures.as_completed(futs):
            cat = futs[fut]
            try:
                findings.extend(fut.result())
            except Exception as exc:
                failed.append(cat["title"])
                print(f"  [warn] lens '{cat['title']}' failed: {exc}")

    findings.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 1), f["lens"]))
    if args.out:
        Path(args.out).write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")

    highs = sum(1 for f in findings if f["severity"] == "High")
    print(f"=== CROSS-WEEK CONTINUITY — weeks {weeks[0]}–{weeks[-1]} ===")
    print(f"{len(findings)} finding(s) ({highs} High) across {len(CATEGORIES) - len(failed)}/{len(CATEGORIES)} lenses\n")
    for f in findings:
        print(f"  [{f['severity']:<4}] {f['lens']}")
        print(f"       {f['location']}: \"{f['fact_quote']}\"")
        print(f"    vs {f['contradiction_location']}: \"{f['contradiction_quote']}\"")
        print(f"       ↳ {f['why']}\n")
    if not findings:
        print("  (no cross-week contradictions surfaced)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
