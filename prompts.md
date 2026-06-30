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
the level + grammar, the format — no negative-constraint clauses, no vocabulary list); verification =
independent enforcement by a separate model; gating lives in code, not the prompt. Hard gates: structural
alignment + one-sentence-per-line, and the dims `coherence` / `naturalness` / `gloss_fidelity`.
Advisory (reported, never block): `grammar_whitelist` (scope) / `cefr_level`, and the frequency
band-check. Prompts are level-relative (`{level}`/`{grammar}`), so the same text scales A1→B2.

---

## 1. GENERATION prompt
*(Week 1, scene 6 "The Neighbour" — shown with the week arc injected.)*

```
Story world: The protagonist is Maya, a 31-year-old woman from Mexico, spending her first year in Copenhagen, Denmark. She has moved to Copenhagen for a fresh start; she arrives knowing almost no one and gradually settles in — making friends, finding her way around the city, everyday life. She grew up in a warm climate, so the cold, dark Danish winter is new to her. Recurring cast: Nina (a Danish friend and neighbour) and her family back home in Mexico (video calls).

TASK: Write ONE short scene for WEEK 1 (CEFR level A1) of the Danish course.
Scene title: "The Neighbour". Narrative beat: At the door Maya meets Nina, who lives next door. Nina says hello and tells Maya her name; Maya does the same. Nina comes from Denmark, Maya from Mexico. They are happy — a friendship begins.

This week's arc (write ONLY the marked scene; do not cover other scenes' beats or bring in characters who first appear in a later scene):
  1. Landing — The plane lands in Copenhagen. Maya looks out the small window at the grey sky. She is happy and a little nervous. She says her name, that she is 31, that she comes from Mexico, and that now she is in Denmark. This is her new home.
  2. Baggage — The airport is big and busy — there are many people. Maya walks to the baggage. There are many suitcases. Hers is big and red. She takes it. She is tired but happy.
  3. A Friendly Face — A friendly woman smiles at Maya and welcomes her to Denmark. They say hello and exchange names, and Maya says where she comes from. The woman is Danish. A warm first hello.
  4. The Taxi — Maya takes a taxi. The driver says hello and asks where she is going. Maya gives her new address. They talk a little; Copenhagen is big and beautiful. She looks out at the streets and the tall houses.
  5. The Street — The taxi stops on Maya's new street. The street is quiet. There are old houses — they are tall and beautiful. Everything is new to Maya, and she is curious.
  6. The Neighbour — At the door Maya meets Nina, who lives next door. Nina says hello and tells Maya her name; Maya does the same. Nina comes from Denmark, Maya from Mexico. They are happy — a friendship begins.   ← WRITE THIS SCENE
  7. The Flat — Maya goes into her new flat. It is small but nice. There is a little kitchen, a table, and two chairs. There is a big window. Maya likes her new home.
  8. The Window — Maya stands at the window and looks out at Copenhagen. It is a big city — there are many people and many bikes. The sky is grey and it is cold. At home in Mexico it is warm. She thinks about her family.
  9. A Call Home — Maya calls her family in Mexico. She sees her mother and father on the screen, and they say hello. Maya tells them she is in Copenhagen and she is well. It is cold but beautiful here. She is happy.
  10. Evening Alone — It is evening, and Maya is alone in the flat. It is quiet. She is a little tired and a little homesick. But she is also happy and curious. Tomorrow is a new day.
  11. The Friend Returns — Nina knocks on the door and asks how Maya is doing. Maya says she is happy here. Nina is warm and kind. She is Maya's neighbour now, so Maya is not alone. She feels welcome.
  12. First Night — It is late — Maya's first night in Copenhagen. She is tired, and the city is quiet. Copenhagen is her new home now, and Nina is her first friend. Maya smiles. Good night.

The Danish is what's being learned — author it natively and idiomatically; the English is a faithful, natural gloss. Natural, correct Danish comes first, even when that means not landing exactly in-level.

- Level A1, this week's grammar: present tense of være / hedde / komme fra; existential der er (there is/are); subject pronouns; hvad/hvor questions; greetings (hej, goddag, tak, velkommen, farvel, undskyld). Earlier-week grammar may recur; don't reach clearly beyond A1.
- Tell it as Maya's own first-person account (her voice throughout); attribute any quoted speech so it's clear who's speaking.
- About 14 lines, one sentence per line; don't pad. The "da" and "en" arrays MUST have the same number of entries, aligned line-for-line.

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

The Danish is the language being learned — judge it as real, native Danish; the English is its faithful gloss.

SCENE (line-aligned Danish / English):
1. DA: Der er en kvinde her.    EN: There is a woman here.
2. DA: "Hej, jeg hedder Nina."    EN: "Hi, my name is Nina."
3. DA: Jeg er din nabo.    EN: I am your neighbour.
4. DA: "Velkommen, Maya."    EN: "Welcome, Maya."

Score each dimension. For each: pass = true/false, and list specific issues as {line, problem}.
1. grammar_whitelist — is the grammar within A1? (Earlier weeks' exact structures aren't listed here, so judge by level, not a strict whitelist.) Flag substantive structures (verb tenses, modal verbs, subordinate/relative clauses, the passive, comparatives) ONLY when clearly beyond A1 and not part of this week's focus.
2. cefr_level — is the sentence length and complexity appropriate to A1? Flag ONLY lines whose complexity clearly EXCEEDS A1; simplicity that fits A1 is expected, not a defect. (Word frequency is checked separately — ignore it here.)
3. coherence — read the lines in order: do they hold together? Flag ONLY hard breaks — a reply that doesn't answer its question, a fact re-introduced as if new, or a contradiction — not taste or pacing.
4. naturalness — would a native speaker actually say this? Flag ONLY lines that are CLEARLY wrong: translationese (word-for-word from English), constructions a native would not use, or errors that make it sound foreign. Do NOT flag matters of taste — register ("too abrupt/formal"), rhetorical choices, or a line you would merely phrase differently. If a native could naturally say it, it passes — reserve a fail for genuinely un-native Danish.
5. gloss_fidelity — does each English line convey the meaning of its Danish line? The English is the pivot ~100 other languages are translated from, so a wrong gloss propagates everywhere. Flag ONLY SUBSTANTIVE divergence — added, dropped, or mistranslated meaning — NOT defensible word or preposition choices (e.g. "ved" as "at" vs "by") or natural rewordings that keep the meaning.

Return JSON exactly:
{"grammar_whitelist": {"pass": true, "issues": []},
 "cefr_level": {"pass": true, "assessed_level": "A1", "issues": []},
 "coherence": {"pass": true, "issues": []},
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
