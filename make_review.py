#!/usr/bin/env python3
"""Regenerate the weeks 1-28 review documents from the current content.

Produces, next to this script:
  review_wk1-28.html / .pdf      bilingual (Danish + English), line-numbered
  review_wk1-28_en.html / .pdf   English-only

Week titles/levels come from curriculum_da.md; scene text from year1/weekNN/*.da/.en.
HTML is rendered to PDF with headless Chrome (google-chrome or chromium).

Usage:  .venv/bin/python make_review.py [--no-pdf] [--weeks 1-28]
"""
import argparse, glob, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def scene_title(stem):
    body = stem.split('_', 1)[1] if '_' in stem else stem
    return body.replace('_', ' ').capitalize()


def load_meta():
    """wk -> (level, theme) from the curriculum table."""
    meta = {}
    with open(os.path.join(ROOT, "curriculum_da.md"), encoding="utf-8") as f:
        for line in f:
            m = re.match(r'^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|', line)
            if m:
                meta[int(m.group(1))] = (m.group(2).strip(), m.group(3).strip())
    return meta


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        out = [ln.rstrip('\n') for ln in f]
    while out and out[-1].strip() == '':
        out.pop()
    return out


HEAD = '''<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>
@page {{ margin: 1.6cm; }}
body {{ font-family: Georgia, 'Times New Roman', serif; font-size: 10.5pt; line-height: 1.32; color:#111; max-width: 62rem; margin: 0 auto; padding: 1rem; }}
h1 {{ font-size: 20pt; border-bottom: 2px solid #333; padding-bottom:.3rem; }}
.sub {{ color:#555; font-size: 10pt; margin-bottom:2rem; }}
.week {{ page-break-before: always; }}
.week:first-of-type {{ page-break-before: avoid; }}
h2 {{ font-size: 15pt; background:#f0f0f0; padding:.35rem .5rem; border-left:4px solid #555; margin-top:1.4rem; }}
.lvl {{ float:right; font-size:10pt; color:#777; font-weight:normal; }}
.scene {{ page-break-inside: avoid; margin:.5rem 0 1rem; }}
h3 {{ font-size:11.5pt; color:#333; margin:.7rem 0 .25rem; }}
table {{ border-collapse: collapse; width:100%; }}
td {{ padding:1px 6px; vertical-align:top; }}
td.n {{ color:#bbb; font-size:8pt; text-align:right; width:1.4rem; }}
td.da {{ font-weight:600; width:47%; }}
td.en {{ color:{en_color}; font-style:{en_style}; }}
p.prose {{ margin:.15rem 0 .7rem; text-align:justify; }}
.warn {{ color:#b00; font-size:9pt; font-weight:normal; font-style:normal; }}
@media print {{ h2 {{ background:#eee !important; -webkit-print-color-adjust:exact; }} }}
</style></head>'''


def build(weeks, meta, mode):
    """mode: 'bi' (bilingual) | 'en' (English, line-numbered) | 'prose' (English paragraphs)."""
    label = {'bi': 'Danish/English review', 'en': 'English review',
             'prose': 'English review (prose)'}[mode]
    english_only = mode in ('en', 'prose')
    title = f"Maya — {label}, weeks {weeks[0]}–{weeks[-1]}"
    parts = [HEAD.format(title=title,
                         en_color=('#111' if english_only else '#555'),
                         en_style=('normal' if english_only else 'italic')),
             '<body>']
    for wk in weeks:
        d = os.path.join(ROOT, f"year1/week{wk:02d}")
        lvl, theme = meta.get(wk, ('', f'Week {wk}'))
        parts.append(f'<section class="week"><h2>Week {wk} &middot; {esc(theme)}'
                     f'<span class="lvl">{esc(lvl)}</span></h2>')
        for da_path in sorted(glob.glob(os.path.join(d, "[0-9]*.da"))):
            stem = os.path.basename(da_path)[:-3]
            en_path = da_path[:-3] + ".en"
            if not os.path.exists(en_path):
                continue
            da, en = read_lines(da_path), read_lines(en_path)
            if mode == 'prose':
                para = ' '.join(l for l in en if l.strip())
                parts.append(f'<div class="scene"><h3>{esc(scene_title(stem))}</h3>'
                             f'<p class="prose">{esc(para)}</p></div>')
                continue
            warn = '' if len(da) == len(en) else f' <span class="warn">(da {len(da)} / en {len(en)})</span>'
            parts.append(f'<div class="scene"><h3>{esc(scene_title(stem))}{warn}</h3><table>')
            for i in range(max(len(da), len(en))):
                dl = da[i] if i < len(da) else ''
                el = en[i] if i < len(en) else ''
                if english_only:
                    parts.append(f'<tr><td class="n">{i+1}</td><td class="en">{esc(el)}</td></tr>')
                else:
                    parts.append(f'<tr><td class="n">{i+1}</td><td class="da">{esc(dl)}</td>'
                                 f'<td class="en">{esc(el)}</td></tr>')
            parts.append('</table></div>')
        parts.append('</section>')
    parts.append('</body></html>')
    return ''.join(parts)


def find_chrome():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    return None


def to_pdf(chrome, html_path, pdf_path):
    with tempfile.TemporaryDirectory() as prof:
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                        "--no-pdf-header-footer", f"--user-data-dir={prof}",
                        f"--print-to-pdf={pdf_path}", f"file://{html_path}"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", default="1-28", help="range like 1-28")
    ap.add_argument("--no-pdf", action="store_true", help="write HTML only")
    args = ap.parse_args()
    a, b = (int(x) for x in args.weeks.split("-"))
    weeks = list(range(a, b + 1))
    meta = load_meta()

    chrome = None if args.no_pdf else find_chrome()
    if not args.no_pdf and not chrome:
        print("warning: no Chrome/Chromium found — writing HTML only", file=sys.stderr)

    for mode, stem in [('bi', "review_wk1-28"), ('en', "review_wk1-28_en"),
                       ('prose', "review_wk1-28_en_prose")]:
        html = build(weeks, meta, mode)
        html_path = os.path.join(ROOT, stem + ".html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"wrote {stem}.html  ({len(html):,} bytes)")
        if chrome:
            pdf_path = os.path.join(ROOT, stem + ".pdf")
            to_pdf(chrome, html_path, pdf_path)
            print(f"wrote {stem}.pdf   ({os.path.getsize(pdf_path):,} bytes)")


if __name__ == "__main__":
    main()
