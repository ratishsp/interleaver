# Course campaign playbook (distilled from Kochi, Mumbai, and Berlin's setup)

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

## Storyboard rows: story only (Berlin restart, validated wk1-28)
Rows carry what happens; the grammar header, curriculum column, and bible carry
everything else. In a row:
- **No grammar names, register notes, or L2 tokens** — "uses an imperative",
  "(using the formal Sie)", "('hatte')" all leaked or narrowed generation; the
  header alone landed every target across 28 regenerated weeks.
- **No asserted qualities or states** ("freezing", "feels at home") — the
  generator restates them as narrator mood-labels.
- **No L2 nouns that have plain-English equivalents** (her phone, not das
  Handy); keep only true culture anchors (Späti, Anmeldung).
- **One English word per object across all rows**, and for a loanword/native
  pair the precise English IS the pin ("T-shirt" maps 1:1 to das T-Shirt;
  removing the pin produced three competing nouns).
- Name a generic container ONCE where the scene turns on it; never two rows
  instructing the same action.
- **Weave time into the action** ("On Wednesday evening she walks home") — a
  day-list brief yields "It is [day]..." openers in 5 of 8 scenes.
- Unnamed-character continuity pins live in the rows (the bible holds only
  facts a later WEEK could contradict — a one-week walk-on has no entry; if
  she recurs across weeks, name her and add her to the cast) and are phrased
  in-world, by story reference: a later row says "the same woman from the
  examination room" — never "keep the doctor consistent", and not a
  scene-number range ("the same one through scenes 7 to 10" worked 4x in
  Berlin but is meta-flavoured; prefer the story reference).
- An innocent English SHAPE can bypass the week's L2 target (the double
  definite kills bare -en/-et) — state the target's BOUNDARY in the curriculum
  grammar column, which feeds the scene generator too.

## Refrain-when-target rule
When the week's grammar target is a sayable phrase (gern, mir geht es, seit +
duration), the chant is intrinsic — do not thin it like a mood refrain. Keep
every instance SAID to someone; cut only narrated ones. Confirmed three times
in Berlin (wk12, wk18, wk19).

## Retelling/recap weeks
Diff each memory against its source scene BY HAND — verify_scene is
fabrication-blind there (it checks the week, not the canon). Watch tone
pile-up and grammar-scope regression on the hand edits; a judge will also
propose "realism" that contradicts the source — source canon wins.

## Deferred to batches (before ANY audio)
- Bible **status ledger** entries as weeks lock (judgment; not automated).
- Advisory review + the human ear pass.
- Audio only after sweeps are clean: text is cheap to fix, audio is not.

## Writing the curriculum and bible (before any generation)

**A bible holds facts a later week could contradict — nothing else.** Cast, weekly fixtures,
register, hard constraints (shop-closing days, transit modes), canonical object vocabulary. Not
style coaching, not predictions, not restatements of the briefs.

**A rule earns its place by pointing at an observed defect, not a predicted one.** Berlin's setup
shed three rules that were all the same mistake — writing for problems predicted rather than
problems seen:
- a standing **seasons section** (Mumbai's was cut for the same reason: a per-week weather prompt
  produces per-week weather chatter — the Kochi rain-refrain lesson);
- a standing **"the setting is the point, use local colour"** instruction (or its inverse). A
  generator produces local colour in proportion to what the *brief* invites. Fix the briefs; the
  standing rule is belt-and-braces that mostly narrows the model;
- a **pre-seeded status ledger** — 16 entries of "what is TRUE by week N" for a course with zero
  generated scenes, versus Kochi's 12 after 28 real weeks. It only restated the briefs (which the
  reviewer already reads), and any entry whose fact never reached the scenes would have the checker
  validating later weeks against fiction.

**The exception — pre-seed only when the violation is expensive to catch late.** Canonical object
vocabulary and the register table survived scrutiny because both point at real Kochi/Mumbai failures
AND their violations surface only across several weeks, often after audio is built. Local-colour
hunting, by contrast, is caught cheaply in a week-1 review. Cost-of-late-catch is the test.

**Ledger growth rule**: add an entry only for a fact a GENERATED scene established that the brief
did not — a possession, a habit, a name, a decision a later week must not contradict.

**Audit the grammar ramp against a published inventory where one exists.** Goethe (German),
Instituto Cervantes's Plan Curricular (Spanish), the CEFR référentiels (French, Italian). Use it as
a coverage check, never as the ordering — the ramp stays story-first. Berlin's audit found four A1
items simply absent (plurals, *nicht*, the basic conjunctions, dative-as-object) AND corrected an
over-caution of mine (the passive is A2, not B1). No such inventory exists for Hindi, Marathi,
Malayalam or Sanskrit — those ramps are irreducibly bespoke, which is worth stating honestly rather
than implying parity.

**On `occam.py text` for hand-written prose**: it does not converge — round 4 returns as many
findings as round 1 — so "run until clean" is the wrong stopping rule; it is counsel, not a gate.
Past a couple of rounds it starts trading correctness for brevity (it proposed replacing a factual
shop-closing rule with an invented legal category). And mechanical cuts break structure: verify
brackets and read the result rather than trusting the edit.

## Language-specific watchpoints so far
- **Sanskrit**: dual forms whenever TWO people are addressed (parents!),
  vocatives (माये not माया), vowel length in stems (स्वादूनि) — the generator
  reliably fumbles these; expect hand fixes on family/group scenes. No street
  vocative (user ruling); no voice approximation — audio waits for the real
  Gefion indic-parler voice. Synonym drift is its steadiest failure (bed wk1,
  suitcase+laptop wk4) — keep the bible's canonical-object-vocabulary list current.
- **Hindi/Marathi**: kin-term address registers differ per language and per
  age (भैया vs चाचा; दादा vs काका) — codify in each track's bible register
  section, never in shared masters. Hindi's steadiest failure is
  respectful-plural drift (वह/है for Asha and service staff where the bible
  demands वे/हैं — recurred wk1, wk4, wk7); the panel catches it reliably,
  fix mechanically, expect it.
- **Clothing-exchange week (wk21)**: adopt Kochi's device — the trial-room queue
  is too long, so Maya buys the shirt *untried*, which is *why* it's the wrong size
  and drives the exchange. This motivates the plot AND keeps the try-on inside a
  proper trial room on the return trip. Without it, a generator compressing the
  scene count improvises an over-the-clothes look at a shop-floor mirror (Mumbai
  wk21 — restaged + merged to one trial-room scene). Put the queue device in the
  storyboard brief.
- Equational-only weeks invite English calques ("I am here for work") — the
  natural idiom often needs an untaught form; prefer an in-scope natural
  rephrase and save the idiom for the week that owns its grammar.
