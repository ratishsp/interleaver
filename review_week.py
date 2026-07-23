"""Week-content review gate — a panel that reads the WHOLE generated week.

Completes the verification matrix:
                 per-scene             whole-week
   design          —                   review_storyboard (scenes)
   text            verify_scene        review_week (this)   <-- the gap

`verify_scene` reads one scene in isolation, so it is structurally blind to WHOLE-WEEK properties:
repetition/monotony across scenes, cross-scene continuity, and pacing. This panel reads every scene
in order and checks those — pushing that human pass into the pipeline so it holds at scale.

Mood/warmth is deliberately NOT gated here: it's the most ear-judged property, left to the human
listen. A per-scene "must end warm / lift" rule used to live here but was removed —
it manufactured robotic smiling (every scene tacking on "jeg smiler, jeg er glad" to satisfy it).

The "register" lens is the one exception, and it's ADVISORY-ONLY (never blocks, never auto-fixes) —
it flags where a character reads as unintentionally rude/curt against who they're meant to be, but
leaves the call to the human ear. It reports rudeness; it does NOT mandate warmth, so it can't
resurrect the robotic-smiling failure. It's calibrated for Danish directness (imperatives / no
everyday "please" / terse answers are NORMAL, not rude) so it doesn't fire on ordinary Danish.

Reuses review_storyboard's panel machinery (the robust judge call, severity rank, floor+agency and
output contract). Same gate semantics: High-severity findings block; an incomplete run (a lens errors)
is never a silent pass.

Run:  set -a; . ./.env; set +a; export GOOGLE_CLOUD_LOCATION=global
      .venv/bin/python review_week.py year1/week03/storyboard.md --model gemini-3.1-pro-preview
"""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import os
import re
from pathlib import Path

from tandem.gen import DEFAULT_MODEL, parse_storyboard, parse_storyboard_header, revise_scene
from tandem.llm import make_client
from review_storyboard import _call_findings, _SEV_RANK, _FLOOR_AGENCY, _CONTRACT, curriculum_row

COMMON = """This is a {language}-for-English-speakers graded AUDIO course (interleaved English→{language}). A
"week" is several scenes; the learner hears them one after another in a sitting. You are reviewing
the GENERATED TEXT of a FULL WEEK — every scene, in order, as "{language} line  |  English gloss".

A separate PER-SCENE verifier already checked each scene's {language} in isolation (grammar, alignment,
naturalness). Do NOT re-do that. YOUR job is the WHOLE-WEEK view — only what is visible ACROSS scenes:
repetition, the emotional arc, cross-scene consistency, and pacing.

IMPORTANT CALIBRATION — this is a comprehensible-input beginner LANGUAGE course, NOT a novel. MODERATE
repetition of common words and simple phrases is PEDAGOGICALLY GOOD (it reinforces vocabulary) and is
EXPECTED — not a defect. Do NOT flag a word or phrase merely for recurring across scenes (a learner
hearing "varm" or "på skærmen" several times is fine and useful).

GROUND TRUTH:
--- story_bible.md (facts + cross-cutting rules) ---
{bible}
--- this week's curriculum row ---
{curric}
--- end ---

THE FULL WEEK — {header}:
{week_text}
"""

_LISTENER_BODY = """
YOUR ROLE: You are the LEARNER, listening to this ENTIRE week back-to-back for the first time — a
curious adult beginner. There is deliberately NO checklist. Take the scenes in order as one sitting
and REACT honestly, as a person.

Where did your attention drift? What dragged or felt repetitive from scene to scene? Did a later scene clash with an earlier one? What would make
you stop listening? Trust your gut and report whatever strikes you about the WEEK AS A WHOLE (not
single lines — the per-scene check already covered those). Rate by gut-strength: High / Med / Low."""

LENSES = [
    {
        "key": "repetition",
        "title": "Repetition & monotony",
        "lens": "things over-repeated or too samey across the week",
        "floor": (
            "(a) An emotion or state asserted in scene after scene (e.g. the same feeling restated).\n"
            "(b) Scenes built on an identical shape/template — a 'roll-call' of near-identical scenes.\n"
            "(c) A whole scene that recaps another (near-verbatim summary of the same content).\n"
            "(d) A refrain — the same small action or line recurring scene after scene.\n"
            "Reserve High for clear, listener-noticeable monotony."
        ),
    },
    {
        "key": "continuity",
        "title": "Cross-scene continuity & consistency",
        "lens": "facts holding consistent from scene to scene across the week",
        "floor": (
            "(a) Time consistency — time of day, and time-zone between places — across scenes.\n"
            "(b) Names / characters / objects consistent; nothing contradicts an earlier scene this week.\n"
            "(c) What the character has / knows / has done stays consistent scene to scene.\n"
            "(d) The sequence of events makes sense from the first scene to the last."
        ),
    },
    {
        "key": "padding",
        "title": "Padding & filler",
        "lens": "lines that look like fillers",
        "floor": (
            "Flag ONLY what looks like filler; a line whose purpose is visible elsewhere in the "
            "week is not filler.\n"
            "Name the scene and quote the lines in the issue."
        ),
    },
    {
        "key": "register",
        "title": "Register & rudeness",
        "lens": "whether anyone sounds unintentionally rude or cold",
        "advisory": True,   # reports for the human ear — never blocks, never mandates warmth
        "floor": (
            "Text that is harsher or colder than intended.\n"
            "Do not flag ordinary {language} directness as rude. Reserve High for a genuinely "
            "off-putting exchange."
        ),
    },
    {
        "key": "listener",
        "title": "Naive whole-week listener (no checklist)",
        "lens": None,
        "floor": None,
    },
]


def assemble_week(storyboard_path: str | Path, key: str = "da") -> str:
    """Read every scene's .{key}/.en (in storyboard order) into one target|gloss block per scene."""
    rows = parse_storyboard(storyboard_path)
    wdir = Path(storyboard_path).parent
    parts = []
    for r in rows:
        da, en = wdir / f"{r['stem']}.{key}", wdir / f"{r['stem']}.en"
        if not (da.exists() and en.exists()):
            continue
        dal = da.read_text(encoding="utf-8").splitlines()
        enl = en.read_text(encoding="utf-8").splitlines()
        body = "\n".join(f"  {d}  |  {e}" for d, e in zip(dal, enl))
        parts.append(f"## Scene {r['num']} — {r['stem']}\n{body}")
    return "\n\n".join(parts)


def build_prompt(lens: dict, *, header: str, week_text: str, bible: str, curric: str,
                 language: str = "Danish") -> str:
    common = COMMON.format(bible=bible, curric=curric, header=header, week_text=week_text,
                           language=language)
    if lens["key"] == "listener":
        return common + _LISTENER_BODY + _CONTRACT
    floor = lens["floor"].format(language=language) if "{language}" in (lens["floor"] or "") else lens["floor"]
    body = (f"\nYOUR LENS: **{lens['title']}** — {lens['lens']}.\n"
            + _FLOOR_AGENCY.format(floor=floor))
    return common + body + _CONTRACT


def run_lens(client, model: str, lens: dict, prompt: str) -> list[dict]:
    out = []
    for f in _call_findings(client, model, prompt, stage=f"review_week.{lens['key']}"):
        out.append({
            "lens": lens["title"],
            "scene": str(f.get("scene", "?")),
            "issue": (f.get("issue") or f.get("reaction") or "").strip(),
            "severity": (f.get("severity") or "Med").strip().capitalize(),
            "why": (f.get("why") or "").strip(),
            # advisory = never blocks the gate: the open naive lens (no floor), or a lens that opts in explicitly
            "advisory": lens.get("advisory", lens.get("floor") is None),
        })
    return out


def _build_prompts(header_line, week_text, bible, curric, language="Danish"):
    return {l["key"]: build_prompt(l, header=header_line, week_text=week_text, bible=bible,
                                   curric=curric, language=language)
            for l in LENSES}


def run_panel(client, model, prompts, workers):
    """One full 3-lens panel pass → (findings, failed_lens_titles). Shared by the gate and the fixer."""
    findings, failed = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(run_lens, client, model, l, prompts[l["key"]]): l for l in LENSES}
        for fut in concurrent.futures.as_completed(futs):
            try:
                findings.extend(fut.result())
            except Exception as exc:
                failed.append(futs[fut]["title"])
                print(f"  [warn] lens '{futs[fut]['title']}' failed: {exc}")
    return findings, failed


# ---- vote-gated auto-fix (prototype) --------------------------------------------------
# One panel run is flaky: LLM-judge variance flags different subsets each run (we watched wk1 give
# 3 findings, then 6). Auto-editing on a single run acts on that noise. So --fix runs the panel N
# times and only revises a scene that ≥K runs INDEPENDENTLY flag — majority vote / self-consistency
# (Wang 2023; jury-beats-one-judge, PoLL/Verga 2024). Voting IS the precision guard (no separate
# refute pass until voting is shown to over-fix). A bad revision is a reviewable git diff, not a
# silent corruption — that reversibility is why no in-loop verify gate is needed. Votes bucket per
# SCENE (the fix unit); whole-week findings (the smile/ready refrain) aren't scene-local, so they're
# reported for a human, never auto-fixed.

def _scene_keys(label) -> list[str]:
    """Normalize a judge's scene label into tally keys. The judge writes '2', 'Scene 2', or joint
    labels like '4 and 5' / 'Scenes 8 & 9' — the raw-string tally treated each spelling as a
    different scene (double-revising one, silently dropping a 3/3 joint survivor)."""
    s = re.sub(r"(?i)^scenes?\s*", "", str(label).strip())
    parts = [p.strip() for p in re.split(r"\s*(?:&|,|\band\b)\s*", s) if p.strip()]
    return parts or [str(label).strip()]


def collect_votes(client, model, prompts, *, votes, min_votes, workers):
    """Panel ×votes, tallied by scene. Returns (scene_survivors, week_survivors); each survivor is
    {scene, votes, severity, issues[]}. A scene survives when ≥min_votes distinct runs flag it."""
    tally: dict[str, dict] = {}
    for i in range(votes):
        fs, _ = run_panel(client, model, prompts, workers)
        print(f"  vote {i + 1}/{votes}: {len(fs)} findings")
        for f in fs:
          for key in _scene_keys(f["scene"]):
            b = tally.setdefault(key, {"scene": key, "runs": set(), "issues": [], "sev": "Low"})
            b["runs"].add(i)
            b["issues"].append(f"[{f['severity']}/{f['lens']}] {f['issue']}"
                               + (f" — {f['why']}" if f["why"] else ""))
            if _SEV_RANK.get(f["severity"], 1) < _SEV_RANK.get(b["sev"], 1):
                b["sev"] = f["severity"]
    kept = [{"scene": b["scene"], "votes": len(b["runs"]), "severity": b["sev"], "issues": b["issues"]}
            for b in tally.values() if len(b["runs"]) >= min_votes]
    scenes = sorted((k for k in kept if k["scene"] not in ("week", "?")),
                    key=lambda k: (_SEV_RANK.get(k["severity"], 1), k["scene"]))
    weekly = [k for k in kept if k["scene"] in ("week", "?")]
    return scenes, weekly


def apply_fix(client, model, row, *, level, grammar, wdir, issues, bible, language="Danish", key="da"):
    """Revise one scene from its pooled feedback and write it back. revise_scene raises if it breaks
    the 1:1 alignment, so a broken revision is caught and the scene is left untouched."""
    stem = row["stem"]
    da_p, en_p = wdir / f"{stem}.{key}", wdir / f"{stem}.en"
    da = da_p.read_text(encoding="utf-8").splitlines()
    en = en_p.read_text(encoding="utf-8").splitlines()
    feedback = ("The whole-week review panel flagged this scene (fix only what is named, keep the rest, "
                "1 sentence per line, stay in scope):\n" + "\n".join(f"- {x}" for x in issues))
    try:
        rev = revise_scene(client, model=model, level=level, grammar=grammar, scene=row["scene"],
                           da_lines=da, en_lines=en, feedback=feedback, bible=bible,
                           language=language, key=key)
    except (Exception, SystemExit) as exc:
        return {"stem": stem, "status": "rejected", "n0": len(da), "n1": len(da), "err": str(exc)[:80]}
    da_p.write_text("\n".join(rev[key]) + "\n", encoding="utf-8")
    en_p.write_text("\n".join(rev["en"]) + "\n", encoding="utf-8")
    return {"stem": stem, "status": "fixed", "n0": len(da), "n1": len(rev[key])}


def run_fix(client, model, args, *, hdr, rows, bible, curric):
    """Vote → revise the scenes the panel agrees on. One pass; re-run the command to iterate."""
    wdir = Path(args.storyboard).parent
    header_line = f"Week {hdr['week']} · {hdr['level']} · grammar: {hdr['grammar']} · {len(rows)} scenes"
    from tandem.langs import LANG_NAMES
    language = LANG_NAMES.get(args.lang, args.lang)
    prompts = _build_prompts(header_line, assemble_week(args.storyboard, key=args.lang), bible, curric,
                             language=language)
    print(f"\n--- vote-gated fix: {args.votes} panel runs, revise scenes flagged by ≥{args.min_votes} ---")
    scenes, weekly = collect_votes(client, model, prompts,
                                   votes=args.votes, min_votes=args.min_votes, workers=args.workers)
    if weekly:
        print("\n  whole-week issues (agreed on, but not scene-local — handle by hand / regen):")
        for w in weekly:
            print(f"    [{w['severity']}] {w['votes']}/{args.votes} votes — {w['issues'][0]}")
    # The judge labels a survivor by NUMBER ("5"), zero-padded ("05"), or STEM
    # ("05_buying_warm_socks") — accept all three, and never drop a survivor silently (a stem-labeled
    # 3-vote fix once vanished here because the index was number-only).
    index = {}
    for r in rows:
        index[str(r["num"])] = index[f"{r['num']:02d}"] = index[r["stem"]] = r
    results = []
    for s in scenes:
        sid = str(s["scene"]).strip()
        if sid.lower().startswith("scene"):
            sid = sid[5:].strip()                      # the judge sometimes labels 'Scene 4'
        row = index.get(sid) or next((r for r in rows if r["stem"] in sid or sid in r["stem"]), None)
        if not row:
            print(f"  ⚠ survivor '{s['scene']}' {s['votes']}/{args.votes} matched no scene — SKIPPED (fix lost)")
            continue
        res = apply_fix(client, model, row, level=hdr["level"], grammar=hdr["grammar"],
                        wdir=wdir, issues=s["issues"], bible=bible,
                        language=language, key=args.lang)
        results.append({"scene": s["scene"], "stem": row["stem"], "votes": s["votes"],
                        "severity": s["severity"], **res})
        tag = f"scene {s['scene']} ({row['stem']}) {s['votes']}/{args.votes} votes {s['severity']}"
        if res["status"] == "fixed":
            print(f"  ✓ {tag}: revised ({res['n0']}→{res['n1']} lines)")
        else:
            print(f"  ✗ {tag}: revision rejected ({res.get('err', 'misaligned')}) — left unchanged")
    changed = [r["stem"] for r in results if r["status"] == "fixed"]
    if not scenes:
        print("\n  no scene survived the vote — nothing to auto-fix.")
    if changed:
        print(f"\n=== revised {len(changed)} scene(s): {', '.join(changed)} ===")
        print("  ⚠ line counts may have shifted — re-run translate_week for these scenes (ml/ta "
              "re-align) + rebuild audio, then re-run this gate to confirm the fixes held.")
    # Persist the vote results — the whole-week findings + per-scene survivors/revisions.
    out_path = args.out or str(wdir / "review_summary.json")
    Path(out_path).write_text(json.dumps(
        {"mode": "fix", "votes": args.votes, "min_votes": args.min_votes,
         "whole_week": weekly, "scene_survivors": scenes, "revised": results},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  findings → {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Review a whole week's generated content with the 3-lens panel.")
    ap.add_argument("storyboard", help="path to the week's storyboard.md (its dir holds the .da/.en)")
    ap.add_argument("--bible", default="story_bible.md")
    ap.add_argument("--curriculum", default="curriculum_da.md")
    ap.add_argument("--lang", default="da", help="course language code (default da)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="judge model (e.g. gemini-3.1-pro-preview)")
    ap.add_argument("--location", default="global",
                    help="Vertex location (default 'global' — required for gemini-3 models)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", help="also write the findings list as JSON to this path (for the week-revise loop)")
    ap.add_argument("--fix", action="store_true",
                    help="vote-gated auto-fix: run the panel N times and revise scenes ≥K runs agree on")
    ap.add_argument("--votes", type=int, default=3, help="panel runs per fix (self-consistency samples)")
    ap.add_argument("--min-votes", type=int, default=2, dest="min_votes",
                    help="revise a scene only if ≥ this many runs flag it (default 2 of 3 = majority)")
    args = ap.parse_args(argv)
    if args.location:
        os.environ["GOOGLE_CLOUD_LOCATION"] = args.location

    from tandem.langs import LANG_NAMES
    language = LANG_NAMES.get(args.lang, args.lang)
    hdr = parse_storyboard_header(args.storyboard)
    rows = parse_storyboard(args.storyboard)
    header_line = f"Week {hdr['week']} · {hdr['level']} · grammar: {hdr['grammar']} · {len(rows)} scenes"
    week_text = assemble_week(args.storyboard, key=args.lang)
    bible = Path(args.bible).read_text(encoding="utf-8") if Path(args.bible).exists() else "(no bible)"
    curric = curriculum_row(args.curriculum, hdr["week"])

    client = make_client()
    if args.fix:
        return run_fix(client, args.model, args, hdr=hdr, rows=rows, bible=bible, curric=curric)

    prompts = _build_prompts(header_line, week_text, bible, curric, language=language)
    findings, failed = run_panel(client, args.model, prompts, args.workers)

    findings.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 1), f["lens"]))
    highs = [f for f in findings if f["severity"] == "High" and not f["advisory"]]
    adv_high = sum(1 for f in findings if f["severity"] == "High" and f["advisory"])
    if args.out:
        Path(args.out).write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== WEEK-CONTENT REVIEW — {header_line} ===")
    extra = f", {adv_high} advisory High" if adv_high else ""
    print(f"{len(findings)} findings ({len(highs)} blocking High{extra}) across {len(LENSES) - len(failed)}/{len(LENSES)} lenses\n")
    for f in findings:
        adv = "  (advisory — does not block)" if f["advisory"] else ""
        print(f"  [{f['severity']:<4}] (scene {f['scene']}; {f['lens']}) {f['issue']}{adv}")
        if f["why"]:
            print(f"         ↳ {f['why']}")
    print()
    # Deterministic repetition lint (advisory, no API) — fix loops revise scenes AFTER gen_week's
    # lint ran, so re-lint here or a post-revise repeat ships silently (it did: wk1 kochi).
    try:
        from lint_week import lint as _lint_week
        _lint_week(Path(args.storyboard).parent)
    except Exception as exc:
        print(f"[warn] repetition lint skipped: {exc}")

    if failed:
        print(f"GATE: ⚠ INCOMPLETE — {len(failed)} lens(es) errored ({', '.join(failed)}). Re-run; not a pass.")
        return 2
    if highs:
        print(f"GATE: ✗ {len(highs)} blocking High finding(s) — fix the week before audio.")
        return 1
    print("GATE: ✓ no blocking findings — clear for audio (review advisory + Med/Low first).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
