#!/usr/bin/env bash
# Wait for the in-flight retry to finish, then re-render Wednesday with skip-fix.
while pgrep -f retry_week.sh >/dev/null; do sleep 10; done
echo ">>> Wednesday re-run (skip-enabled) [$(date +%H:%M:%S)]"
.venv/bin/python -m tandem corpora/week/03_wednesday.da corpora/week/03_wednesday.en \
    --pre-aligned --src-lang da --tgt-lang en --speed 0.75 --l1-first \
    -o samples/week/03_wednesday.mp3 --transcript samples/week/03_wednesday_transcript.txt
echo "=== Wednesday done; total: $(ls samples/week/*.mp3 | wc -l)/7 ==="
