# tandem — Gemini Prompts (rendered example)

The three prompts that drive script **generation**, **verification**, and **translation**, shown here
**rendered with real Week-1 values** (the model sees exactly this text). They are built by
`tandem/gen.py` — `scene_prompt()`, `verify_prompt()`, `translate_prompt()`. This file is a readable
mirror; edit the prompts in `gen.py`, then regenerate this doc. Print any prompt live (no API call):

```
python -m tandem.gen scene     ... --show-prompt
python -m tandem.gen verify    ... --show-prompt
python -m tandem.gen translate ... --show-prompt
```

**Design split (see `design_notes.md`):** generation = lean positive *intent* (who Maya is, the scene,
the grading targets, the format — no negative-constraint clauses); verification = independent
enforcement by a separate model; gating lives in code, not the prompt. Hard gates: structural
alignment + one-sentence-per-line, and the dims `content_neutral` / `naturalness` / `gloss_fidelity`.
Advisory (reported, never block): `grammar_whitelist` (scope) / `cefr_level`, and the frequency
band-check. Prompts are level-relative (`{level}`/`{grammar}`), so the same text scales A1→B2.

---

## 1. GENERATION prompt
*(Week 1, scene 6 "The Neighbour" — shown with the week arc injected and prior-vocab recycling.)*

```
Story world: The protagonist is Maya, a 31-year-old woman from Mexico, spending her first year in Copenhagen, Denmark. She has moved to Copenhagen for a fresh start; she arrives knowing almost no one and gradually settles in — making friends, finding her way around the city, everyday life. She grew up in a warm climate, so the cold, dark Danish winter is new to her. Recurring cast: Nina (a Danish friend and neighbour) and her family back home in Mexico (video calls).

TASK: Write ONE short scene for WEEK 1 (CEFR level A1) of the Danish course.
Scene title: "The Neighbour". Narrative beat: At the door Maya meets Nina, her Danish neighbour. They introduce themselves; Nina is from Denmark, Maya from Mexico. A friendship begins.

This week's arc (write ONLY the marked scene; do not cover other scenes' beats or bring in characters who first appear in a later scene):
  1. Landing — Maya's plane lands in Copenhagen. She introduces herself — her name, that she is 31 and from Mexico, and that she is now in Denmark.
  2. Baggage — In the busy airport Maya collects her big suitcase. She describes the airport and how she feels — tired but happy.
  3. A Friendly Face — A friendly stranger greets Maya and welcomes her. They exchange names and she says where she is from. A warm first hello.
  4. The Taxi — Maya takes a taxi. The driver is friendly; Maya gives her new address and they talk a little about how big and lovely Copenhagen is.
  5. The Street — The taxi reaches Maya's new street. She looks at the old houses and the quiet street — everything is new to her.
  6. The Neighbour — At the door Maya meets Nina, her Danish neighbour. They introduce themselves; Nina is from Denmark, Maya from Mexico. A friendship begins.   ← WRITE THIS SCENE
  7. The Flat — Maya steps into her new flat. It is small but lovely — a little kitchen, a table, a chair.
  8. The Window — From her window Maya looks out at Copenhagen — a big city, many people. The weather is cold; back home in Mexico it is warm.
  9. A Call Home — Maya makes a video call to her family in Mexico. She tells them she is in Copenhagen, she is well, and it is cold but beautiful here.
  10. Evening Alone — Evening comes. Maya is alone in her new flat — a little tired and a little homesick, but also happy and curious.
  11. The Friend Returns — Nina knocks again and asks how Maya is settling in. Maya says she is happy here. Nina is warm — she's Maya's neighbour now, and Maya is not alone. Maya feels welcome.
  12. First Night — It is late on Maya's first night. She is tired, but Copenhagen is her new home now, and Nina is her first friend.

The Danish is what's being learned — author it natively and idiomatically; the English is a faithful, natural gloss. Natural, correct Danish always beats hitting a target.

- Level A1, this week's grammar: present tense of være / hedde / komme fra; existential der er (there is/are); subject pronouns; hvad/hvor questions; greetings (hej, goddag, tak, velkommen, farvel, undskyld). Earlier-week grammar may recur; don't reach clearly beyond A1.
- Use common everyday words and the already-introduced ones (below); add only a few new ones (~40/week, spread across scenes).
- Follow the beat as a small, connected narrative; only the characters it calls for.
- Already introduced (reuse freely): jeg, er, hedder, Maya, kommer, fra, Mexico, i, København, og, en, by, stor, tak, her, ny
- About 12 lines, one sentence per line; don't pad. The "da" and "en" arrays MUST have the same number of entries, aligned line-for-line.

Return JSON: {"da": [...], "en": [...]}, same number of entries in each.
```

---

## 2. VERIFICATION prompt
*(An independent QA model scores the five dimensions and returns JSON. Sample 4-line scene.)*

```
You are an INDEPENDENT QA reviewer for a graded Danish language course. Judge the scene below against its spec. Be concrete and cite the offending Danish by line number. Apply each dimension's threshold exactly as written — neither harsher nor more lenient than it says.

SPEC:
- CEFR level: A1
- Grammar FOCUS this week (the new structures introduced): present tense of være / hedde / komme fra; existential der er (there is/are); subject pronouns; hvad/hvor questions; greetings (hej, goddag, tak, velkommen, farvel, undskyld)
- ALSO always allowed (never flag these): the basic function words every sentence needs — articles (en/et), conjunctions (og, men), common possessives (min/din/sin), prepositions, negation (ikke), and ordinary adverbs. Only count SUBSTANTIVE structures beyond the level as violations.
- Vocabulary already taught earlier (fine to reuse): jeg, er, hedder, Maya

The Danish is the language being learned — judge it as real, native Danish. The English is its gloss, and is the pivot other languages are later translated from, so it must faithfully convey the Danish.

SCENE (line-aligned Danish / English):
1. DA: Der er en kvinde her.    EN: There is a woman here.
2. DA: "Hej, jeg hedder Nina."    EN: "Hi, my name is Nina."
3. DA: Jeg er din nabo.    EN: I am your neighbour.
4. DA: "Velkommen, Maya."    EN: "Welcome, Maya."

Score each dimension. For each: pass = true/false, and list specific issues as {line, problem}.
1. grammar_whitelist — is the grammar within A1? (Earlier weeks' exact structures aren't listed here, so judge by level, not a strict whitelist.) Flag substantive structures (verb tenses, modal verbs, subordinate/relative clauses, the passive, comparatives) ONLY when clearly beyond A1 and not part of this week's focus. Never flag the basic function words listed above.
2. cefr_level — is the sentence length and complexity appropriate to A1? Flag ONLY lines whose complexity clearly EXCEEDS A1; simplicity that fits A1 is expected, not a defect. (Word frequency is checked separately — ignore it here.)
3. content_neutral — is it about ordinary life and NOT about learning a language? Flag any language school, language class, or "learning/practising Danish" content.
4. naturalness — would a native speaker actually say this? Flag ONLY lines that are CLEARLY wrong: translationese (word-for-word from English), constructions a native would not use, or errors that make it sound foreign. Do NOT flag matters of taste — register ("too abrupt/formal"), rhetorical choices, or a line you would merely phrase differently. If a native could naturally say it, it passes — reserve a fail for genuinely un-native Danish.
5. gloss_fidelity — does each English line convey the meaning of its Danish line? The English is the pivot ~100 other languages are translated from, so a wrong gloss propagates everywhere. Flag ONLY SUBSTANTIVE divergence — added, dropped, or mistranslated meaning — NOT defensible word or preposition choices (e.g. "ved" as "at" vs "by") or natural rewordings that keep the meaning.

Return JSON exactly:
{"grammar_whitelist": {"pass": true, "issues": []},
 "cefr_level": {"pass": true, "assessed_level": "A1", "issues": []},
 "content_neutral": {"pass": true, "issues": []},
 "naturalness": {"pass": true, "issues": []},
 "gloss_fidelity": {"pass": true, "issues": []}}
(Use false and fill issues where there are problems; each issue is {"line": <int>, "problem": "<text>"}.)
```

---

## 3. TRANSLATION prompt
*(English pivot → Spanish. Phase-1 policy: translate, don't relocate; preserve 1:1 line alignment.)*

```
Story world: The protagonist is Maya, a 31-year-old woman from Mexico, spending her first year in Copenhagen, Denmark. She has moved to Copenhagen for a fresh start; she arrives knowing almost no one and gradually settles in — making friends, finding her way around the city, everyday life. She grew up in a warm climate, so the cold, dark Danish winter is new to her. Recurring cast: Nina (a Danish friend and neighbour) and her family back home in Mexico (video calls).

TASK: Translate the following 4 lines from en into es for this course.
Scene context: Maya meets her neighbour Nina at the door, week 1
Target CEFR level: A1 — keep the translation in-level, do not drift up or down.

RULES:
- Translate naturally and idiomatically in es; avoid word-for-word translationese.
- PHASE-1 POLICY = TRANSLATE, DO NOT RELOCATE. Keep the Danish setting and Danish-specific terms (e.g. SKAT, hygge, Janteloven, CPR, MitID, København) — render them naturally, do NOT swap them for the target culture's equivalents.
- Keep names consistent.
- Preserve sentence segmentation EXACTLY: return the SAME number of lines (4), one translation per input line, in order. Do not merge or split lines.

INPUT:
1. There is a woman here.
2. "Hi, my name is Nina."
3. I am your neighbour.
4. "Welcome, Maya."

Return JSON: {"lines": ["...", ...]} with exactly 4 entries, in order.
```
