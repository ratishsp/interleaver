#!/usr/bin/env python3
"""Generate the static course site into docs/ (GitHub Pages serves that folder).

Reads the week directories and storyboards; emits:
  docs/index.html                     landing page
  docs/danish.html, docs/malayalam.html   per-course pages (player + downloads per week)
  docs/transcripts/<course>/weekNN.html   side-by-side transcript pages

Audio is NOT copied here (Pages has a 1 GB cap); players point at the GitHub
Release assets, whose filenames tools/upload_release_assets.sh produces.
Stdlib only. Rerun any time content changes: python tools/build_site.py
"""
from __future__ import annotations
import html
import re
from pathlib import Path

REPO = "ratishsp/interleaver"
TAG = "v1.1"
TAG2 = "v1.1-assets2"  # GitHub caps a release at 1,000 assets; the overflow lives here
ASSET = f"https://github.com/{REPO}/releases/download/{TAG}"
ASSET2 = f"https://github.com/{REPO}/releases/download/{TAG2}"
_ASSETS2 = set(Path(__file__).with_name("release_assets2_manifest.txt").read_text().split())

def asset_url(name: str) -> str:
    return f"{ASSET2}/{name}" if name in _ASSETS2 else f"{ASSET}/{name}"

COURSES = [
    {"key": "danish", "root": Path("year1"), "l2": "da", "l2_name": "Danish",
     "curriculum": "curriculum_da.md", "built_weeks": 28,
     "variants": [("danish", "Danish only"),
                  ("danish-then-english", "Danish → English"),
                  ("english-then-danish", "English → Danish")],
     "full": [("weeks01-28_danish.mp3", "Danish only, whole course"),
              ("weeks01-28_danish-then-english.mp3", "Danish → English, whole course"),
              ("weeks01-28_english-then-danish.mp3", "English → Danish, whole course")]},
    {"key": "malayalam", "root": Path("variants/kochi"), "l2": "ml", "l2_name": "Malayalam",
     "curriculum": "variants/kochi/curriculum_ml.md", "built_weeks": 28,
     "variants": [("malayalam", "Malayalam only"),
                  ("malayalam-then-english", "Malayalam → English"),
                  ("english-then-malayalam", "English → Malayalam")],
     "full": [("weeks01-28_ml.mp3", "Malayalam only, whole course"),
              ("weeks01-28_malayalam-then-english.mp3", "Malayalam → English, whole course"),
              ("weeks01-28_english-then-malayalam.mp3", "English → Malayalam, whole course")]},
    {"key": "german", "root": Path("variants/berlin"), "l2": "de", "l2_name": "German",
     "curriculum": "variants/berlin/curriculum_de.md", "built_weeks": 28,
     "variants": [("german", "German only"),
                  ("german-then-english", "German → English"),
                  ("english-then-german", "English → German")],
     "full": [("weeks01-28_german.mp3", "German only, whole course"),
              ("weeks01-28_german-then-english.mp3", "German → English, whole course"),
              ("weeks01-28_english-then-german.mp3", "English → German, whole course")]},
    {"key": "hindi", "root": Path("variants/mumbai/hi"), "l2": "hi", "l2_name": "Hindi",
     "curriculum": "variants/mumbai/curriculum_hi.md", "built_weeks": 28,
     "variants": [("hindi", "Hindi only"),
                  ("hindi-then-english", "Hindi → English"),
                  ("english-then-hindi", "English → Hindi")],
     "full": [("weeks01-28_hindi.mp3", "Hindi only, whole course"),
              ("weeks01-28_hindi-then-english.mp3", "Hindi → English, whole course"),
              ("weeks01-28_english-then-hindi.mp3", "English → Hindi, whole course")]},
    {"key": "marathi", "root": Path("variants/mumbai/mr"), "l2": "mr", "l2_name": "Marathi",
     "curriculum": "variants/mumbai/curriculum_mr.md", "built_weeks": 28,
     "variants": [("marathi", "Marathi only"),
                  ("marathi-then-english", "Marathi → English"),
                  ("english-then-marathi", "English → Marathi")],
     "full": [("weeks01-28_marathi.mp3", "Marathi only, whole course"),
              ("weeks01-28_marathi-then-english.mp3", "Marathi → English, whole course"),
              ("weeks01-28_english-then-marathi.mp3", "English → Marathi, whole course")]},
    {"key": "sanskrit", "root": Path("variants/mumbai/sa"), "l2": "sa", "l2_name": "Sanskrit",
     "curriculum": "variants/mumbai/curriculum_sa.md", "built_weeks": 28,
     "variants": [("sanskrit", "Sanskrit only"),
                  ("sanskrit-then-english", "Sanskrit → English"),
                  ("english-then-sanskrit", "English → Sanskrit")],
     "full": [("weeks01-28_sanskrit.mp3", "Sanskrit only, whole course"),
              ("weeks01-28_sanskrit-then-english.mp3", "Sanskrit → English, whole course"),
              ("weeks01-28_english-then-sanskrit.mp3", "English → Sanskrit, whole course")]},
]

BETA_LANGS = [  # translated tracks (machine-translated from the English gloss; beta)
    ("hi", "hindi", "Hindi"), ("ta", "tamil", "Tamil"), ("gu", "gujarati", "Gujarati"),
    ("kn", "kannada", "Kannada"), ("pa", "punjabi", "Punjabi"), ("te", "telugu", "Telugu"),
    ("ur", "urdu", "Urdu"), ("mr", "marathi", "Marathi"), ("bn", "bengali", "Bengali"),
    ("ml", "malayalam", "Malayalam"),
    ("es", "spanish", "Spanish"), ("fr", "french", "French"), ("de", "german", "German"),
    ("it", "italian", "Italian"), ("pt", "portuguese", "Portuguese"),
    ("ja", "japanese", "Japanese"), ("ko", "korean", "Korean"),
    ("cmn", "mandarin", "Mandarin"), ("ar", "arabic", "Arabic"),
    ("nl", "dutch", "Dutch"), ("pl", "polish", "Polish"), ("sv", "swedish", "Swedish"),
    ("nb", "norwegian", "Norwegian"), ("fi", "finnish", "Finnish"), ("cs", "czech", "Czech"),
    ("sk", "slovak", "Slovak"), ("hu", "hungarian", "Hungarian"), ("ro", "romanian", "Romanian"),
    ("bg", "bulgarian", "Bulgarian"), ("el", "greek", "Greek"), ("hr", "croatian", "Croatian"),
    ("sr", "serbian", "Serbian"), ("sl", "slovenian", "Slovenian"),
    ("lt", "lithuanian", "Lithuanian"), ("lv", "latvian", "Latvian"),
    ("et", "estonian", "Estonian"), ("uk", "ukrainian", "Ukrainian"),
    ("tr", "turkish", "Turkish"), ("id", "indonesian", "Indonesian"), ("th", "thai", "Thai"),
    ("vi", "vietnamese", "Vietnamese"), ("yue", "cantonese", "Cantonese"),
    ("he", "hebrew", "Hebrew"), ("sw", "swahili", "Swahili"),
]

STYLE = """
:root { --fg:#1a1a1a; --muted:#666; --line:#e3e3e3; --accent:#0b5fa5; }
* { box-sizing:border-box; }
body { font:16px/1.55 system-ui,-apple-system,sans-serif; color:var(--fg);
       max-width:64rem; margin:0 auto; padding:1.5rem; }
h1,h2 { line-height:1.25; } a { color:var(--accent); }
table { border-collapse:collapse; width:100%; }
td,th { padding:.5rem .6rem; border-bottom:1px solid var(--line); vertical-align:top;
        text-align:left; }
audio { width:15rem; max-width:100%; height:2rem; }
.muted { color:var(--muted); font-size:.9rem; }
.dl a { margin-right:.6rem; white-space:nowrap; font-size:.9rem; }
.tr td:first-child { width:50%; }
nav a { margin-right:1rem; }
"""


def page(title: str, body: str, depth: int = 0) -> str:
    up = "../" * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{STYLE}</style></head><body>
<nav><a href="{up}index.html">Interleaver</a><a href="{up}danish.html">Danish</a>
<a href="{up}malayalam.html">Malayalam</a><a href="{up}german.html">German</a>
<a href="{up}hindi.html">Hindi</a><a href="{up}marathi.html">Marathi</a>
<a href="{up}sanskrit.html">Sanskrit</a></nav>
{body}
<p class="muted">Content licensed CC BY 4.0 · <a href="https://github.com/{REPO}">source &amp; code</a></p>
</body></html>"""


def week_title(week: Path) -> str:
    sb = week / "storyboard.md"
    if sb.exists():
        m = re.search(r"# Week \d+ — Storyboard \((.+)\)", sb.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    return ""


def read_lines(p: Path) -> list[str]:
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def transcript_page(course: dict, week: Path, n: int) -> str:
    l2 = course["l2"]
    rows = []
    sb_text = (week / "storyboard.md").read_text(encoding="utf-8")
    sb_stems = re.findall(r"^\| *\d+ *\| *(\S+) *\|", sb_text, re.M)
    sb_desc = dict(re.findall(r"^\| *\d+ *\| *(\S+) *\| *(.+?) *\|$", sb_text, re.M))
    for stem in sb_stems:
        f2, fe = week / f"{stem}.{l2}", week / f"{stem}.en"
        if not (f2.exists() and fe.exists()):
            continue
        pretty = stem.split("_", 1)[-1].replace("_", " ")
        rows.append(f"<tr><th colspan=2>{html.escape(pretty)}</th></tr>")
        desc = sb_desc.get(stem, "")
        if desc:
            rows.append(f'<tr><td colspan=2 class=muted><i>Storyboard: {html.escape(desc)}</i></td></tr>')
        for a, b in zip(read_lines(f2), read_lines(fe)):
            rows.append(f"<tr class=tr><td>{html.escape(a)}</td>"
                        f"<td class=muted>{html.escape(b)}</td></tr>")
    body = (f"<h1>Week {n}: {html.escape(week_title(week))}</h1>"
            f"<p class=muted>{course['l2_name']} with English gloss, line-aligned.</p>"
            f"<table>{''.join(rows)}</table>")
    return page(f"Week {n} transcript · {course['l2_name']}", body, depth=2)


def asset_name(course: dict, n: int, variant: str) -> str:
    if variant in ("malayalam", "danish"):
        return f"week{n:02d}_{variant}.mp3"
    return f"week{n:02d}_{variant}.mp3"


def course_page(course: dict) -> str:
    weeks = sorted(course["root"].glob("week[0-9][0-9]"))
    default_variant = course["variants"][-1][0]  # English-first = beginner default
    rows = []
    for wk in weeks:
        n = int(wk.name[4:])
        player = asset_url(f"{course['key']}_{asset_name(course, n, default_variant)}")
        links = " ".join(
            f'<a href="{asset_url(course["key"] + "_" + asset_name(course, n, v))}">{html.escape(label)}</a>'
            for v, label in course["variants"])
        rows.append(
            f"<tr><td><b>Week {n}</b><br><span class=muted>{html.escape(week_title(wk))}</span></td>"
            f'<td><audio controls preload="none" src="{player}"></audio><br>'
            f'<span class=dl>{links} '
            f'<a href="transcripts/{course["key"]}/week{n:02d}.html">transcript</a></span></td></tr>')
    full = "".join(f'<li><a href="{asset_url(f)}">{html.escape(label)}</a></li>'
                   for f, label in course["full"])
    player_note = ("The player uses the English-first interleave (best for a first listen)"
                   if default_variant.startswith("english-then")
                   else f"The player uses the {course['l2_name']}-first interleave "
                        "(the English meaning follows each line)")
    body = (f"<h1>{course['l2_name']} course</h1>"
            f"<p>28 weeks, one continuing story. {player_note}; the links offer every variant. "
            f"See also the <a href='curriculum_{course['key']}.html'>full curriculum</a>.</p>"
            f"<table>{''.join(rows)}</table>"
            f"<h2>Whole course in one file</h2><ul>{full}</ul>")
    return page(f"{course['l2_name']} · Interleaver", body)


def beta_page(code: str, fname: str, label: str) -> str:
    weeks = [Path("year1") / f"week{n:02d}" for n in range(1, 29)]
    rows = []
    for wk in weeks:
        n = int(wk.name[4:])
        player = asset_url(f"trans-{fname}_week{n:02d}_english-then-{fname}.mp3")
        rows.append(
            f"<tr><td><b>Week {n}</b><br><span class=muted>{html.escape(week_title(wk))}</span></td>"
            f'<td><audio controls preload="none" src="{player}"></audio><br>'
            f'<span class=dl><a href="{player}">English → {html.escape(label)}</a> '
            f'<a href="transcripts/trans-{fname}/week{n:02d}.html">transcript</a></span></td></tr>')
    body = (f"<h1>{html.escape(label)}</h1>"
            f"<p>Maya's year in {html.escape(label)}: 28 weeks of one continuing story, every "
            "line paired with English audio and a line-aligned transcript.</p>"
            "<p class=muted>The track is machine-translated. It may sound a bit odd as it is "
            "apart from the Copenhagen setting it is translated from. In contrast, the Danish, German, Hindi, Marathi, Sanskrit "
            "and Malayalam courses are generated source-language-first and thus more realistic "
            "sounding.</p>"
            f"<table>{''.join(rows)}</table>"
            "<p>Want a different direction or pause lengths? See “Build your own language pair” on "
            'the <a href="index.html">home page</a>.</p>')
    return page(f"{label} · Interleaver", body)


def beta_transcript_page(code: str, fname: str, label: str, week: Path, n: int) -> str:
    course = {"l2": code, "l2_name": label}
    return transcript_page(course, week, n)


def strip_md(s: str) -> str:
    return s.replace("**", "").replace("*", "")


def curriculum_page(course: dict) -> str:
    rows = []
    built = course.get("built_weeks", 28)
    for line in Path(course["curriculum"]).read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| *(\d+) *\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        wk, lvl, theme, grammar, brief = int(cells[0]), cells[1], cells[2], cells[3], cells[4]
        tag = "" if wk <= built else ' <span class=muted>(planned)</span>'
        rows.append(f"<tr><td><b>{wk}</b>{tag}<br><span class=muted>{lvl}</span></td>"
                    f"<td><b>{html.escape(strip_md(theme))}</b><br>"
                    f"<span class=muted>{html.escape(strip_md(grammar))}</span><br>"
                    f"{html.escape(strip_md(brief))}</td></tr>")
    body = (f"<h1>{course['l2_name']} curriculum</h1>"
            "<p class=muted>One row per week: theme, grammar focus, and the brief the storyboard "
            "is generated from. Weeks beyond the built range are the planned design.</p>"
            f"<table>{''.join(rows)}</table>")
    return page(f"{course['l2_name']} curriculum · Interleaver", body)


INDEX_BODY = """
<h1>Interleaver</h1>
<p>Free, open audio language courses that follow one story: <b>Maya</b>, a software
engineer from Mexico, moves abroad for a job, and you learn the language by following
her year, one week at a time. Each line is spoken in the language you are
learning and in English. No app, no screen: press play while you commute or
work out.</p>
<ul>
<li><a href="danish.html"><b>Danish</b></a>: Maya in Copenhagen (28 weeks, ~4 h)</li>
<li><a href="malayalam.html"><b>Malayalam</b></a>: Maya in Kochi (28 weeks, ~4 h)</li>
<li><a href="german.html"><b>German</b></a>: Maya in Berlin (28 weeks, ~4 h)</li>
<li><a href="hindi.html"><b>Hindi</b></a>: Maya in Mumbai (28 weeks, ~4 h)</li>
<li><a href="marathi.html"><b>Marathi</b></a>: Maya in Mumbai (28 weeks, ~4 h)</li>
<li><a href="sanskrit.html"><b>Sanskrit</b></a>: Maya in Mumbai (28 weeks, ~4 h)</li>
</ul>
<p class=muted>All six courses currently cover levels A1–A2 (weeks 1–28). 24 more weeks
(B1–B2) are planned to complete Maya's year, and more language/city combinations
are coming.</p>
<h2>Which audio variant should I pick?</h2>
<p><b>First listen:</b> English first, then the target language, so you always know
what's being said. <b>Re-listen:</b> target language first, where you try to understand
before the English confirms it. <b>Review:</b> target language only: pure immersion, once a week feels familiar.</p>
<h2>Flashcards (spaced repetition)</h2>
<p>Each course has a free <a href="https://apps.ankiweb.net/">Anki</a> deck with
vocabulary, translation, and cloze cards, all voiced with the course audio.
Download the <code>.apkg</code> from the
<a href="https://github.com/ratishsp/interleaver/releases">releases page</a> and
double-click it.</p>
<h2>More languages</h2>
<p>The same story exists in <b>46 languages</b>: Danish, English, and 44 more,
every line aligned through the English gloss. That allows up to
<b>46 × 45 = 2,070</b> ordered pairings of a language you know with a language you
want to learn. Pick one:</p>
<p><select id="beta" onchange="if(this.value)location.href=this.value">
<option value="">choose a language</option>
__BETA_OPTIONS__
</select></p>
<noscript><p>__BETA_LINKS__</p></noscript>
<p class=muted>The 44 tracks are machine-translated. They may sound a bit
odd as they are apart from the Copenhagen setting they are translated from. In
contrast, the Danish and Malayalam courses are generated source-language-first and
thus more realistic sounding.</p>
<h2>Build your own language pair</h2>
<p>Every synthesized line is published as an individual audio clip (see the
<code>clips-cache</code> asset on the releases page). With the repository's scripts
and those clips, you can assemble any interleave yourself (either direction, your
own pause lengths, any pair of voiced languages) without any text-to-speech account:
<code>python combine_all.py --src da --tgt en</code>.</p>
<h2>Read along</h2>
<p>Every week has a line-aligned transcript: see the course pages.</p>
<h2>How it's made</h2>
<p>Each week starts from a curriculum row: a theme, a grammar focus, and a story
brief. Gemini turns it into a storyboard and then into scenes. Next we have verifiers which are also built on Gemini. Every storyboard
passes a four-lens verifier, every scene is verified, every week is reviewed by a
three-vote panel, and the whole story is swept for continuity across weeks. A human
can intervene at any stage. The full pipeline, prompts, and checks are open in the
<a href="https://github.com/ratishsp/interleaver">repo</a>. The audio is synthesized
with Google Cloud TTS.</p>
<h2>Feedback, issues, and PRs are welcome</h2>
<p>Tell us what works and what doesn't on
<a href="https://github.com/ratishsp/interleaver/issues">GitHub issues</a>,
or open a pull request.</p>
"""


def main() -> None:
    docs = Path("docs")
    (docs / "transcripts").mkdir(parents=True, exist_ok=True)
    docs.joinpath("index.html").write_text(page("Interleaver", INDEX_BODY), encoding="utf-8")
    for course in COURSES:
        docs.joinpath(f"{course['key']}.html").write_text(course_page(course), encoding="utf-8")
        docs.joinpath(f"curriculum_{course['key']}.html").write_text(
            curriculum_page(course), encoding="utf-8")
        tdir = docs / "transcripts" / course["key"]
        tdir.mkdir(parents=True, exist_ok=True)
        for wk in sorted(course["root"].glob("week[0-9][0-9]")):
            n = int(wk.name[4:])
            tdir.joinpath(f"week{n:02d}.html").write_text(
                transcript_page(course, wk, n), encoding="utf-8")
    opts = "\n".join(f'<option value="trans_{f}.html">{html.escape(l)}</option>'
                      for _, f, l in BETA_LANGS)
    links = " · ".join(f'<a href="trans_{f}.html">{html.escape(l)}</a>' for _, f, l in BETA_LANGS)
    idx = docs / "index.html"
    idx.write_text(idx.read_text(encoding="utf-8")
                   .replace("__BETA_OPTIONS__", opts).replace("__BETA_LINKS__", links),
                   encoding="utf-8")
    for code, fname, label in BETA_LANGS:
        docs.joinpath(f"trans_{fname}.html").write_text(beta_page(code, fname, label), encoding="utf-8")
        tdir = docs / "transcripts" / f"trans-{fname}"
        tdir.mkdir(parents=True, exist_ok=True)
        for n in range(1, 29):
            wk = Path("year1") / f"week{n:02d}"
            tdir.joinpath(f"week{n:02d}.html").write_text(
                beta_transcript_page(code, fname, label, wk, n), encoding="utf-8")
    n_pages = len(list(docs.rglob("*.html")))
    print(f"site built: {n_pages} pages in docs/")


if __name__ == "__main__":
    main()
