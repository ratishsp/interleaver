# Multi-track course campaign playbook (distilled from Kochi + Mumbai wk1-3)

How to build a course (or several language tracks over one story) to current
quality. `chain_weeks.sh` automates the per-week loop; this file records WHY
each gate exists so the next city/language does not relearn it.

## Per week, per track (the chain)
1. **Master storyboard** from the curriculum row, previous week as exemplar
   (wk1 of a relocation: use the counterpart week of an existing relocated
   course — Kochi wk1 seeded Mumbai wk1). Gate through review_storyboard,
   ≤3 revise rounds, keep the BEST round (revises can regress).
2. **Sync masters per track** (`sync_storyboards.py`): grammar header swapped
   from each track's curriculum; scene rows must be PLAIN ENGLISH — the sync
   REFUSES language-specific tokens (wk1: a Hindi vocative in a shared row
   surfaced verbatim in the Sanskrit scenes).
3. **Scenes per track** (gen_week) with the track's own curriculum AND its own
   derived bible (`sync_bible.py` — a shared bible cross-pollinates registers).
4. **Week panel** per track: 0 blocking to proceed; Low/Med advisories
   accumulate for the human batch pass (the ear is the final gate).
5. **Continuity, rolling window** per track: new week vs the 5 before it,
   every week; stop on High.
6. **Full-span sweeps at weeks 10, 15, 21, 28** (≈every 6 weeks, hitting both
   review-week term boundaries) — the window is blind past 5 weeks.

## Stop-for-human conditions (never auto-fix)
storyboard escalation · sync-guard refusal · scene failing verification after
retries · blocking panel finding · High continuity finding.

## Re-gate rule
Re-run a gate only when an edit changes WHAT HAPPENS (scenes added/merged/
reordered, facts changed) — never for wording-level repairs.

## Deferred to batches (before ANY audio)
- Bible **status ledger** entries as weeks lock (judgment; not automated).
- Advisory review + the human ear pass.
- Audio only after sweeps are clean: text is cheap to fix, audio is not.

## Language-specific watchpoints so far
- **Sanskrit**: dual forms whenever TWO people are addressed (parents!),
  vocatives (माये not माया), vowel length in stems (स्वादूनि) — the generator
  reliably fumbles these; expect hand fixes on family/group scenes. No street
  vocative (user ruling); no voice approximation — audio waits for the real
  Gefion indic-parler voice. Synonym drift is its steadiest failure (bed wk1,
  suitcase+laptop wk4) — keep the bible's canonical-object-vocabulary list current.
- **Hindi/Marathi**: kin-term address registers differ per language and per
  age (भैया vs चाचा; दादा vs काका) — codify in each track's bible register
  section, never in shared masters.
- Equational-only weeks invite English calques ("I am here for work") — the
  natural idiom often needs an untaught form; prefer an in-scope natural
  rephrase and save the idiom for the week that owns its grammar.
