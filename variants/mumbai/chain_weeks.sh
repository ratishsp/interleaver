#!/bin/bash
# Mumbai week chain: storyboard -> sync -> 3x gen -> 3x panel, week after week.
# Stops at the first escalation/blocking finding for human review.
set -u
cd /home/ratish/project/self/language-learning
set -a; . ./.env; set +a
export GOOGLE_CLOUD_LOCATION=global TANDEM_TIMEOUT_MS=600000
S=${CHAIN_LOGS:-/tmp/mumbai_chain_logs}
mkdir -p "$S"
PUB=$HOME/project/self/interleaver-public
M=$PUB/variants/mumbai
PY=.venv/bin/python

for N in $(seq 2 28); do
  W=$(printf "week%02d" $N)
  P=$(printf "wk%02d" $N)
  if [ -f $M/storyboards/$W.md ]; then
    echo "== $W storyboard already promoted — skipping cycle =="
  else
  echo "########## $W: storyboard ##########"
  TANDEM_TRACE=$M/${P}_storyboard_trace.jsonl $PY gen_storyboard.py $N \
    --example-week $((N-1)) --root $M/hi --cycle \
    --curriculum $M/curriculum_hi.md --bible $M/story_bible_hi.md \
    --language Hindi --setting Mumbai \
    --workdir $S/mumbai_sb > $S/mumbai_sb_${P}.log 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then echo "STOP: $W storyboard escalated (rc=$rc) — see $S/mumbai_sb_${P}.log"; exit 1; fi
  cp $S/mumbai_sb/${P}_storyboard.md $M/storyboards/$W.md
  fi
  if ! (cd $M && python3 sync_storyboards.py > /dev/null); then
    echo "STOP: $W sync guard rejected the master — hand-neutralize $M/storyboards/$W.md"; exit 1
  fi
  for L in hi mr sa; do
    if grep -q "GATE: ✓" $S/mumbai_review_${P}_${L}.log 2>/dev/null; then
      echo "== $W $L already panel-cleared — skipping =="; continue
    fi
    echo "########## $W $L: scenes ##########"
    TANDEM_TRACE=$M/${P}_gen_${L}_trace.jsonl $PY gen_week.py $M/$L/$W/storyboard.md \
      --lang $L --curriculum $M/curriculum_$L.md --bible $M/story_bible_$L.md \
      > $S/mumbai_gen_${P}_${L}.log 2>&1
    if [ $? -ne 0 ]; then echo "STOP: $W $L generation failed — see $S/mumbai_gen_${P}_${L}.log"; exit 1; fi
    if grep -q '"hard_pass": false' $M/$L/$W/verify_summary.json; then
      echo "STOP: $W $L has a scene that failed verification — see verify_summary.json"; exit 1
    fi
    echo "########## $W $L: panel ##########"
    TANDEM_TRACE=$M/${P}_review_${L}_trace.jsonl $PY review_week.py $M/$L/$W/storyboard.md \
      --lang $L --bible $M/story_bible_$L.md --curriculum $M/curriculum_$L.md \
      > $S/mumbai_review_${P}_${L}.log 2>&1
    if ! grep -q "GATE: ✓" $S/mumbai_review_${P}_${L}.log; then
      echo "STOP: $W $L panel has blocking findings — see $S/mumbai_review_${P}_${L}.log"; exit 1
    fi
  done
  FROM=$((N-5)); [ $FROM -lt 1 ] && FROM=1
  for L in hi mr sa; do
    case $L in hi) LN=Hindi;; mr) LN=Marathi;; sa) LN=Sanskrit;; esac
    if [ -f $M/continuity_wk${N}_${L}.json ]; then
      echo "== $W $L continuity already swept — skipping =="; continue
    fi
    echo "########## $W $L: continuity $FROM-$N ##########"
    TANDEM_TRACE=$M/${P}_continuity_${L}_trace.jsonl $PY continuity_check.py \
      --weeks $FROM-$N --root $M/$L --bible $M/story_bible_$L.md --language $LN \
      --out $M/continuity_wk${N}_${L}.json > $S/mumbai_cont_${P}_${L}.log 2>&1
    if [ $? -ne 0 ]; then echo "STOP: $W $L continuity run failed — see $S/mumbai_cont_${P}_${L}.log"; exit 1; fi
    if $PY -c "
import json,sys
f=[x for x in json.load(open('$M/continuity_wk${N}_${L}.json')) if x.get('severity')=='High' and not x.get('advisory')]
sys.exit(1 if f else 0)"; then :; else
      echo "STOP: $W $L continuity found High finding(s) — see continuity_wk${N}_${L}.json"; exit 1
    fi
  done
  case $N in 10|15|21|28)
    for L in hi mr sa; do
      case $L in hi) LN=Hindi;; mr) LN=Marathi;; sa) LN=Sanskrit;; esac
      if [ -f $M/continuity_wk1-${N}_${L}.json ]; then
        echo "== $W $L full sweep already done — skipping =="; continue
      fi
      echo "########## $W $L: FULL continuity 1-$N ##########"
      TANDEM_TRACE=$M/${P}_fullcont_${L}_trace.jsonl $PY continuity_check.py \
        --weeks 1-$N --root $M/$L --bible $M/story_bible_$L.md --language $LN \
        --out $M/continuity_wk1-${N}_${L}.json > $S/mumbai_fullcont_${P}_${L}.log 2>&1
      if [ $? -ne 0 ]; then echo "STOP: $W $L full sweep failed to run"; exit 1; fi
      if $PY -c "
import json,sys
f=[x for x in json.load(open('$M/continuity_wk1-${N}_${L}.json')) if x.get('severity')=='High' and not x.get('advisory')]
sys.exit(1 if f else 0)"; then :; else
        echo "STOP: $W $L FULL sweep found High finding(s) — see continuity_wk1-${N}_${L}.json"; exit 1
      fi
    done ;;
  esac
  echo "== $W COMPLETE (3 tracks, all gates + continuity clear) =="
done
echo "=== MUMBAI CHAIN: ALL WEEKS 2-28 COMPLETE ==="
