#!/usr/bin/env bash
# Build a 7-episode "week" series from contiguous TED2020 da-en slices.
# Each episode: English first, 0.75x speed, ~320 sentence pairs (~90 min for a 2hr gym session).
set -uo pipefail

PY=.venv/bin/python            # the env that actually has pydub + edge_tts
SRC=corpora/TED2020.da-en.da
TGT=corpora/TED2020.da-en.en
PER=320          # sentence pairs per episode (~90 min at 0.75x)
START=1000       # first source line (past the hour-build's 300-660 range)

mkdir -p corpora/week samples/week

days=(monday tuesday wednesday thursday friday saturday sunday)

for i in "${!days[@]}"; do
    n=$((i + 1))
    day="${days[$i]}"
    a=$((START + i * PER))
    b=$((a + PER - 1))
    tag=$(printf "%02d_%s" "$n" "$day")

    sed -n "${a},${b}p" "$SRC" > "corpora/week/${tag}.da"
    sed -n "${a},${b}p" "$TGT" > "corpora/week/${tag}.en"

    echo ">>> Episode $n ($day): lines $a-$b   [$(date +%H:%M:%S)]"
    if "$PY" -m tandem "corpora/week/${tag}.da" "corpora/week/${tag}.en" \
        --pre-aligned --src-lang da --tgt-lang en --speed 0.75 --l1-first \
        -o "samples/week/${tag}.mp3" \
        --transcript "samples/week/${tag}_transcript.txt"; then
        dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "samples/week/${tag}.mp3" 2>/dev/null || echo 0)
        printf "    done: %s  (%.0f min)\n" "samples/week/${tag}.mp3" "$(echo "$dur/60" | bc -l)"
    else
        echo "    !! Episode $n ($day) FAILED — continuing with the rest"
    fi
done

echo "=== WEEK SERIES COMPLETE [$(date +%H:%M:%S)] ==="
ls -la samples/week/*.mp3 2>/dev/null