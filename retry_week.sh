#!/usr/bin/env bash
set -uo pipefail
PY=.venv/bin/python
for tag in 03_wednesday 06_saturday 07_sunday; do
    echo ">>> Retry $tag [$(date +%H:%M:%S)]"
    if $PY -m tandem "corpora/week/${tag}.da" "corpora/week/${tag}.en" \
        --pre-aligned --src-lang da --tgt-lang en --speed 0.75 --l1-first \
        -o "samples/week/${tag}.mp3" --transcript "samples/week/${tag}_transcript.txt"; then
        echo "    OK $tag"
    else
        echo "    !! $tag FAILED again"
    fi
done
echo "=== RETRY DONE; total episodes: $(ls samples/week/*.mp3 | wc -l)/7 ==="
