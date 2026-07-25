#!/bin/bash
# Stage release assets with the site's URL naming, then upload via gh.
#
#   tools/upload_release_assets.sh /path/to/archive-repo [staging-dir]
#
# Stages (copies, never moves) from the archive repo:
#   danish_weekNN_<direction>.mp3      from combined/perweek/
#   malayalam_weekNN_<direction>.mp3   from variants/kochi/combined/perweek/
#   malayalam_weekNN_malayalam.mp3     from variants/kochi/weekNN/audio_ml.mp3
#   whole-course files by their existing names
#   deck/*.apkg if present
# Then prints the gh command to create the v1.0 release with everything attached.
set -euo pipefail
SRC=${1:?usage: upload_release_assets.sh /path/to/archive-repo [staging-dir]}
OUT=${2:-release_assets}
mkdir -p "$OUT"

for f in "$SRC"/combined/perweek/week*.mp3; do
  cp -n "$f" "$OUT/danish_$(basename "$f")"
done
for f in "$SRC"/variants/kochi/combined/perweek/week*.mp3; do
  cp -n "$f" "$OUT/malayalam_$(basename "$f")"
done
for d in "$SRC"/variants/kochi/week[0-9][0-9]; do
  wk=$(basename "$d")
  [ -f "$d/audio_ml.mp3" ] && cp -n "$d/audio_ml.mp3" "$OUT/malayalam_${wk}_malayalam.mp3"
done
for d in "$SRC"/year1/week[0-9][0-9]; do
  wk=$(basename "$d")
  [ -f "$d/audio_da.mp3" ] && cp -n "$d/audio_da.mp3" "$OUT/danish_${wk}_danish.mp3"
done
cp -n "$SRC"/combined/weeks01-28_*.mp3 "$OUT/" 2>/dev/null || true
cp -n "$SRC"/variants/kochi/combined/weeks01-28_*.mp3 "$OUT/" 2>/dev/null || true
cp -n "$SRC"/deck/*.apkg "$OUT/" 2>/dev/null || true
# beta tracks: per-week English-first interleaves for the 19 translated languages
cp -n "$SRC"/combined/beta_perweek/*.mp3 "$OUT/" 2>/dev/null || true
# the clip cache: every synthesized line as a content-addressed clip, so anyone
# can assemble any language pair with the repo scripts and no TTS account
if [ -d "$SRC/cache/clips" ] && [ ! -f "$OUT/clips-cache.zip" ]; then
  (cd "$SRC" && zip -0 -q -r - cache/clips) > "$OUT/clips-cache.zip"
fi

echo "staged $(ls "$OUT" | wc -l) files, $(du -sh "$OUT" | cut -f1) in $OUT/"
echo ""
echo "to publish (after pushing the repo):"
echo "  gh release create v1.0 --title 'Interleaver v1.0' \\"
echo "     --notes 'First release: Danish and Malayalam courses, weeks 1-28, all audio variants + Anki deck.' \\"
echo "     $OUT/*"
