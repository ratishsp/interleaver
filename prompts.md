# tandem — Gemini Prompts

The prompts that drive script **generation**, **translation**, and **verification**. This file is a
readable mirror of `tandem/gen.py` (`scene_prompt()`, `translate_prompt()`, `verify_prompt()`); edit
the prompts there, then regenerate this doc. Print any prompt live, no API call / no credentials:

```
python -m tandem.gen scene     ... --show-prompt
python -m tandem.gen translate ... --show-prompt
python -m tandem.gen verify    ... --show-prompt
```

**Design split (see `design_notes.md`):**
- **Generation prompt = positive INTENT** — who Maya is, what the scene is, the grading targets,
  the output format. No negative constraint clauses.
- **Verification prompt = ENFORCEMENT** — an independent pass checks grammar / level / content
  neutrality / naturalness after the fact, so the generation prompt stays lean.
- **Translation = context-rich, setting-preserving, alignment-locked.**
- The generation inputs (`week`, `grammar`, `new-words`, `beat`, `lines`) are a **row of
  `curriculum_da.md`** — the curriculum is the prompt's data source.

The shared `STORY_BIBLE` constant (top of each prompt) holds the world + Maya's bio (31, from Mexico,
first year in Copenhagen). Change the character/world there once.

---

## 1. Generation prompt (`scene`)

Authors one graded scene as aligned Danish + English. Run from a storyboard, it also injects the **week's arc** (every scene's beat, with the current one marked) so the model knows where the scene sits and does not pre-empt later scenes; `--prior-vocab` (the cumulative word list) handles budget. Filled example — **Week 1, scene 1 "Landing"** (from `year1/week01/storyboard.md`):

```
Story world: A graded comprehensible-input language course. The protagonist is Maya, a 31-year-old woman from Mexico, spending her first year in Copenhagen, Denmark. She has moved to Copenhagen for a fresh start; she arrives knowing almost no one and gradually settles in — making friends, finding her way around the city, everyday life. She grew up in a warm climate, so the cold, dark Danish winter is new to her. Recurring cast: Mette (a Danish friend and neighbour) and her family back home in Mexico (video calls).

TASK: Write ONE short scene for WEEK 1 (CEFR level A1) of the Danish course.
Scene title: "Landing". Narrative beat: Maya's plane lands in Copenhagen. She introduces herself — her name, that she is 31 and from Mexico, and that she is now in Denmark for the first time.

This week's arc (write ONLY the marked scene; do not cover other scenes' beats or bring in characters who first appear in a later scene):
  1. Landing — Maya's plane lands in Copenhagen. She introduces herself — her name, that she is 31 and from Mexico, and that she is now in Denmark for the first time.   ← WRITE THIS SCENE
  2. Baggage — In the busy airport Maya collects her big suitcase. She describes the airport and how she feels — tired but happy.
  3. A Friendly Face — A friendly stranger greets Maya and welcomes her. They exchange names and she says where she is from. A warm first hello.
  4. The Taxi — Maya takes a taxi. The driver is friendly; Maya gives her new address and they talk a little about how big and lovely Copenhagen is.
  5. The Street — The taxi reaches Maya's new street. She looks at the old houses and the quiet street — everything is new to her.
  6. The Neighbour — At the door Maya meets Mette, her Danish neighbour. They introduce themselves; Mette is from Denmark, Maya from Mexico. A friendship begins.
  7. The Flat — Maya steps into her new flat. It is small but lovely — a little kitchen, a table, a chair.
  8. The Window — From her window Maya looks out at Copenhagen — a big city, many people. The weather is cold; back home in Mexico it is warm.
  9. A Call Home — Maya makes a video call to her family in Mexico. She tells them she is in Copenhagen, she is well, and it is cold but beautiful here.
  10. Evening Alone — Evening comes. Maya is alone in her new flat — a little tired and a little homesick, but also happy and curious.
  11. Mette Returns — Mette knocks again and asks how Maya is settling in. Maya says she is happy here. Mette is warm — she's Maya's neighbour now, and Maya is not alone. Maya feels welcome.
  12. First Night — It is late on Maya's first night. She is tired, but Copenhagen is her new home now, and Mette is her first friend.

AUTHOR THE DANISH NATIVELY AND IDIOMATICALLY — it is the language being learned, so it must be
native-quality and exactly in-level. The English is a faithful, natural gloss of the Danish.

HARD GRADING CONSTRAINTS (this is what 'graded' means — obey strictly):
- Grammar allowed this week ONLY: present tense of være / hedde / komme fra; subject pronouns; hvad/hvor questions; V2 word order; greetings (hej, goddag, tak, velkommen, farvel). Do NOT use grammar beyond this (no past tense, no
  modals, no subordinate clauses unless listed above). Earlier-week grammar may recur.
- Vocabulary: about 40 distinct content words for the whole week; keep this scene to a
  small, high-frequency slice. Prefer the most common everyday Danish words.

- Sentences must be SHORT and simple (A1 = very simple at A1).
- Exactly 12 lines. ONE sentence per line. The DA and EN arrays MUST have the same number of
  entries and align line-for-line (line i of EN is the translation of line i of DA).
- Natural spoken register; a little dialogue is good.
- Write a small coherent narrative that follows the beat — connected and flowing, not a list of
  disconnected facts. Keep a warm, natural first-person voice, and only introduce characters the
  beat calls for.

Return JSON: {"da": ["...", ...], "en": ["...", ...]} with exactly 12 entries each.
```

---

## 2. Translation prompt (`translate`)

Translates the English pivot into any target language for the fan-out, preserving meaning, level,
the Danish setting, and the 1-sentence-per-line alignment the clip cache depends on. Filled example —
**English → Spanish**, Week 1 lines:

```
Story world: A graded comprehensible-input language course. The protagonist is Maya, a 31-year-old woman from Mexico, spending her first year in Copenhagen, Denmark. She has moved to Copenhagen for a fresh start; she arrives knowing almost no one and gradually settles in — making friends, finding her way around the city, everyday life. She grew up in a warm climate, so the cold, dark Danish winter is new to her. Recurring cast: Mette (a Danish friend and neighbour) and her family back home in Mexico (video calls).

TASK: Translate the following 14 lines from English into Spanish for this course.
Scene context: Week 1, 'Arrival' — Maya's first day in Copenhagen
Target CEFR level: A1 — keep the translation in-level, do not drift up or down.

RULES:
- Translate naturally and idiomatically in Spanish; avoid word-for-word translationese.
- PHASE-1 POLICY = TRANSLATE, DO NOT RELOCATE. Keep the Danish setting and Danish-specific terms
  (e.g. SKAT, hygge, Janteloven, CPR, MitID, København) — render them naturally, do NOT swap them
  for the target culture's equivalents.
- Keep names consistent. Glossary: Maya, Mette; København -> Copenhague
- Preserve sentence segmentation EXACTLY: return the SAME number of lines (14), one
  translation per input line, in order. Do not merge or split lines.

INPUT:
1. Hi. My name is Maya.
2. I come from a country far away.
3. Now I am in Copenhagen.
4. Copenhagen is a big city.
5. The city is in Denmark.
6. I am new here.
7. I am a little tired.
8. But I am also happy.
9. The airport is big and full of people.
10. Many people are here.
11. A woman is very friendly.
12. "Welcome to Denmark," she says.
13. "Thank you," I say.
14. Now I am here. I am in Copenhagen.

Return JSON: {"lines": ["...", ...]} with exactly 14 entries, in order.
```

---

## 3. Verification prompt (`verify`)

An **independent QA reviewer** scores a generated scene against its spec and returns JSON with
per-line issues (the CLI also runs programmatic alignment + word-count checks and exits non-zero on
failure, to drive an auto-regenerate loop). Grammar is judged on **substantive structures only**
(tenses, modals, clauses, passive) — basic function words are always allowed. Filled example —
**Week 1 "Arrival" scene at A1**:

```
You are an INDEPENDENT QA reviewer for a graded Danish language course. Judge the scene
below against its spec. Be strict, concrete, and cite the offending Danish by line number. Do not be
generous — your job is to catch problems the writer missed.

SPEC:
- CEFR level: A1
- Grammar FOCUS this week (the new structures introduced): present tense of være / hedde / komme fra; subject pronouns; hvad/hvor questions; V2 word order; greetings (hej, tak, velkommen)
- ALSO always allowed (never flag these): the basic function words every sentence needs — articles
  (en/et), conjunctions (og, men), common possessives (min/din/sin), prepositions, negation (ikke),
  and ordinary adverbs. Only count SUBSTANTIVE structures beyond the level as violations.
- Weekly new-word budget ≈ 40; vocabulary should be high-frequency and appropriate for A1.


The Danish is the language being learned, so it must be native-quality and exactly in-level. The
English is only a gloss.

SCENE (line-aligned Danish / English):
1. DA: Hej.    EN: Hello.
2. DA: Jeg er i København.    EN: I am in Copenhagen.
3. DA: Jeg hedder Maya.    EN: My name is Maya.
4. DA: Jeg kommer fra et land langt væk.    EN: I come from a country far away.
5. DA: Nu er jeg i lufthavnen.    EN: Now I am in the airport.
6. DA: Her er min kuffert.    EN: Here is my suitcase.
7. DA: Den er stor.    EN: It is big.
8. DA: Og den er tung.    EN: And it is heavy.
9. DA: Tak.    EN: Thanks.
10. DA: Nu er jeg ude.    EN: Now I am outside.
11. DA: Her er København.    EN: Here is Copenhagen.
12. DA: København er en stor by.    EN: Copenhagen is a big city.
13. DA: Jeg er alene her.    EN: I am alone here.
14. DA: Velkommen til København, Maya.    EN: Welcome to Copenhagen, Maya.

Score each dimension. For each: pass = true/false, and list specific issues as {line, problem}.
1. grammar_whitelist — does every Danish line stay within the week's grammar? Flag ONLY substantive
   structures beyond the level: other tenses (past/perfect/future), modal verbs (kan/vil/skal/må/bør),
   subordinate or relative clauses, the passive, comparatives/superlatives. Do NOT flag basic function
   words (articles, og/men, min/din, prepositions, ikke) — those are always allowed.
2. cefr_level — is it genuinely A1 (sentence length, complexity, word frequency)? Flag lines
   that are too advanced — or so trivial they break the narrative.
3. content_neutral — is it about ordinary life and NOT about learning a language? Flag any language
   school, language class, or "learning/practising Danish" content.
4. naturalness — is the Danish idiomatic and native (not translationese)? Flag awkward/unnatural lines.

Return JSON exactly:
{"grammar_whitelist": {"pass": true, "issues": []},
 "cefr_level": {"pass": true, "assessed_level": "A1", "issues": []},
 "content_neutral": {"pass": true, "issues": []},
 "naturalness": {"pass": true, "issues": []}}
(Use false and fill issues where there are problems; each issue is {"line": <int>, "problem": "<text>"}.)
```

---

## Editing notes

- For **Phase 2/3** (target-language-specific / localized content) you'd relax the
  translate-don't-relocate rule — a different prompt, same engine.
- The verifier should ideally run on a **different model** than the generator (true independence);
  today both default to `gemini-2.5-pro` on Vertex — point `--model` elsewhere for independence.
