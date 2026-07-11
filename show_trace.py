#!/usr/bin/env python3
"""Read a TANDEM_TRACE JSONL — the input AND output of every model call in a run.

  .venv/bin/python show_trace.py year1/week05/trace.jsonl              # index of the run
  .venv/bin/python show_trace.py year1/week05/trace.jsonl 4            # call 4, in full
  .venv/bin/python show_trace.py year1/week05/trace.jsonl --stage gate # every gate call, in full

The index is the map; the record view prints the exact prompt the model saw and the JSON it
returned. Pipe a record view to `less` — a prompt runs several thousand characters.
"""
import argparse
import json
from pathlib import Path

RULE = "=" * 78


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def one_line(resp) -> str:
    """Summarize a response for the index: the shape, not the content."""
    if isinstance(resp, list):
        return f"[{len(resp)} items]"
    if isinstance(resp, dict):
        return "{" + ", ".join(f"{k}: {len(v) if isinstance(v, (list, str)) else v!r}"
                               for k, v in list(resp.items())[:3]) + "}"
    return str(resp)[:60]


def show(rec: dict, i: int) -> None:
    print(f"\n{RULE}\n[{i}] {rec['stage']}   ({rec['model']})\n{RULE}")
    print(f"\n--- PROMPT ({len(rec['prompt'])} chars) ---\n")
    print(rec["prompt"])
    print("\n--- RESPONSE ---\n")
    print(json.dumps(rec["response"], indent=2, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", type=Path)
    ap.add_argument("n", type=int, nargs="?", help="print this call in full (see the index for numbers)")
    ap.add_argument("--stage", help="print in full every call whose stage contains this substring")
    a = ap.parse_args()

    recs = records(a.trace)
    if a.n is not None:
        show(recs[a.n], a.n)
    elif a.stage:
        for i, r in enumerate(recs):
            if a.stage in r["stage"]:
                show(r, i)
    else:
        print(f"{len(recs)} model calls — {a.trace}\n")
        for i, r in enumerate(recs):
            print(f"  {i:>3}  {r['stage']:<28} {len(r['prompt']):>7,} chars in   {one_line(r['response'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
