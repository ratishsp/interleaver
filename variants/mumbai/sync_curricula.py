"""Derive curriculum_mr.md and curriculum_sa.md from curriculum_hi.md.

curriculum_hi.md is the master for the SHARED columns (Theme, Brief): edit the
Mumbai story there, run this script, and the Marathi and Sanskrit files are
regenerated with their own Grammar focus / Grammar in English columns from the
tables below. Never hand-edit a brief in the mr/sa files.

Run:  python variants/mumbai/sync_curricula.py
"""
from pathlib import Path

HERE = Path(__file__).parent

# week -> (grammar focus, grammar in English)
MR = {
    1: ("Equational **आहे**; pronouns **मी/तुम्ही/तो/ती**; **काय/कुठे** questions and the yes-no tag **का** (आहे का?); *माझं नाव … आहे*",
        "Saying who and what things are — \"X is Y\" and \"there is\"; the words for I, you, he and she; asking \"what\" and \"where\"; and turning a sentence into a yes-or-no question with \"ka\"."),
    2: ("Present tense **-तो/-ते** (मी काम करते); numbers 0–100 as words; possession **माझ्याकडे … आहे** and its negation **नाही**; age — **मी … वर्षांची आहे**",
        "The present tense; numbers from zero to one hundred; saying \"I have\" and \"I don't have\"; and giving your age."),
    3: ("Possessives **माझा/तुमचा/त्याचा/तिचा** agreeing with the thing possessed; the indefinite **एक**; **कोण** questions",
        "Possessives — my, your, his and her, agreeing with what is owned; the word for \"a\"; and asking \"who\"."),
    4: ("Locatives **-त/-मध्ये/-वर** (खोलीत, टेबलावर); place words **वर/खाली/जवळ**; placement with **ठेवला आहे** (review *there is*)",
        "Saying where things are — \"in\", \"on\", \"above\", \"below\" and \"near\"; and saying where things have been put."),
    5: ("Wanting and liking with the dative experiencer — **मला हवं** and **मला आवडतं**; the object marker **-ला** on people",
        "Saying \"I want\" and \"I like\"; and marking people as the object of a verb."),
    6: ("Present continuous **-त आहे** (करत आहे) for actions underway, woven naturally through a simple-present routine",
        "The present continuous — \"I am doing\" — woven through an ordinary present-tense routine."),
    7: ("Clock time **वाजता** (किती वाजता?); weekdays & months; frequency adverbs **नेहमी / कधीकधी / रोज**",
        "Clock times; the days of the week and the months; and words like \"always\", \"sometimes\" and \"every day\"."),
    8: ("Polite imperatives **जा/वळा**; directions **सरळ, डावीकडे/उजवीकडे**; **-कडे** (towards)",
        "Polite commands like \"go\" and \"turn\"; directions — straight, left and right; and saying \"towards\" a place."),
    9: ("Prices — **किती झाले? / काय भाव आहे?**; amounts as words; **द्या/हवं** at the stall",
        "Asking prices — \"how much is it?\"; amounts in words; and \"please give me\" at the market stall."),
    10: ("Adjectives as a system — **चांगला/मोठा/लहान** agreeing in gender and number (and the invariable ones); **घालणे** (wear)",
         "Adjectives — good, big and small — changing with gender and number, and the ones that never change; and the verb for wearing clothes."),
    11: ("Weather expressions **ऊन आहे / गरम आहे / पाऊस पडतोय**; simple future **-ईल** for the forecast (पाऊस पडेल)",
         "Talking about the weather — \"it is hot\", \"it is sunny\", \"it is raining\"; and the simple future for the forecast — \"it will rain\"."),
    12: ("The **-ायला** form (खेळायला) with **आवडतं / जाते**; ability with **येणे** (मला खेळता येतं) — landing inside varied actions and exchanges, not as declarations",
         "The infinitive — \"to play\", \"to learn\" — with \"I like to\" and \"I go to\"; and saying \"I can\" with Marathi's \"it comes to me\" pattern."),
    13: ("Polite requests — **द्याल का? / मिळेल का? / हवं** ladder; thanking",
         "Polite requests — \"will you give me?\", \"could I get?\", \"I need\"; and saying thank you."),
    14: ("**चढणे/उतरणे** (board/alight); **-ने** with vehicles (बसने, ट्रेनने); **जायचं आहे** (need to get to)",
         "Getting on and off buses and trains; \"by\" with vehicles; and \"I need to get to\"."),
    15: ("Mixed present-tense narration; consolidation. BOUNDARY: no past tense anywhere — the simple past opens week 16",
         "Review week — everything so far, in flowing present-tense storytelling."),
    16: ("Simple past **-ला/-ली/-लं** (आले, गेले; transitives agree with the object — मी चहा प्यायला); time phrases **काल / गेल्या आठवड्यात / जानेवारीत** (the perfect *-ला आहे* is out of scope — week 19 owns it)",
         "The simple past — \"came\", \"went\", \"saw\" — and how the past verb agrees; and time phrases like \"yesterday\", \"last week\" and \"in January\"."),
    17: ("Past-tense narration; **स्वतःचा** vs **त्याचा/तिचा** (one's own vs another's); time expressions",
         "Telling stories in the past tense; \"one's own\" versus \"his\" or \"hers\"; and more time expressions."),
    18: ("**दुखणे** (माझं डोकं दुखतंय); body parts; **बरं आहे / बरं वाटत नाही**; advice with **-वं** (तुम्ही आराम करावा)",
         "Saying something hurts; the parts of the body; \"I feel fine\" and \"I don't feel well\"; and giving advice with \"you should\"."),
    19: ("Perfect **-ला आहे** (मी केलं आहे — what she has done); professions",
         "The perfect — \"I have done\"; and the names of professions."),
    20: ("Past + perfect mixed; **शिकणे + -ायला** (learning to); ordinals **पहिला/दुसरा**",
         "Past and perfect together; \"learning to do\" something; and ordinal numbers — first, second, third."),
    21: ("Comparative **-पेक्षा** (यापेक्षा मोठा); **मोठा/लहान**; trying on and exchanging",
         "Comparisons — \"bigger than\", \"smaller than\"; and trying on and exchanging things in a shop."),
    22: ("Imperative sequences; quantities (**अर्धा किलो, दोन चमचे**); **आधी/मग/त्यानंतर**",
         "Step-by-step instructions; quantities like \"half a kilo\" and \"two spoons\"; and \"first\", \"then\", \"after that\"."),
    23: ("Future **-ईन** and \"let's\" **करू या/जाऊ या**; reporting thoughts with **की** (मला वाटतं की…)",
         "The future tense — \"it will\" and \"let's\"; and reporting thoughts — \"I think that…\"."),
    24: ("Imperatives + object pronouns **त्याला**; rules with **पाहिजे / करू नये** (must / must not)",
         "Commands with \"it\" and \"him\"; and rules — \"you must\" and \"you must not\"."),
    25: ("Demonstratives **हा/तो + हे/ते** as a system; **पूर्वी** (ago — दोन महिन्यांपूर्वी); time adverbs",
         "This and that — \"this shirt\", \"that one\"; saying \"ago\" — \"two months ago\"; and time adverbs."),
    26: ("Perfect **-ला आहे** vs past **-ला** contrast",
         "The difference between \"I have done\" and \"I did\"."),
    27: ("Habitual **-त असते** (करत असते); instructions; the formal passive **केले जाते** of official language",
         "Saying what you usually do; following instructions; and the formal passive of official notices."),
    28: ("Consolidation across all A2 grammar",
         "Review week — everything from the whole course, in one ordinary week of Maya's life."),
}

SA = {
    1: ("Equational **अस्ति** (X is Y) and *there is*; pronouns **अहम् / भवान् / भवती / सः / सा**; **किम् / कुत्र** questions and yes-no questions with **किम्**; *मम नाम … अस्ति*",
        "Saying who and what things are — \"X is Y\" and \"there is\"; the words for I, you (politely), he and she; asking \"what\" and \"where\"; and turning a sentence into a yes-or-no question."),
    2: ("Present tense (**लट्** — गच्छामि/गच्छति); numbers 1–100 as words; possession **मम समीपे … अस्ति** and its negation **नास्ति**; age — **मम … वयः**",
        "The present tense; numbers from one to one hundred; saying \"I have\" and \"I don't have\"; and giving your age."),
    3: ("Genitive possessives **मम / भवत्याः / तस्य / तस्याः**; **एकः/एका/एकम्** agreeing in gender; **कः/का** questions",
        "Possessives — my, your, his and her; the word for \"one\", agreeing in gender; and asking \"who\"."),
    4: ("The locative case (**सप्तमी** — गृहे, प्रकोष्ठे); place words **उपरि / अधः / समीपे**; placement with **स्थापितम् अस्ति** (review *there is*)",
        "Saying where things are — the locative case ending; \"above\", \"below\" and \"near\"; and saying where things have been put."),
    5: ("Wanting and liking — **इच्छामि** and the dative experiencer **मह्यं रोचते**; the accusative case (**द्वितीया**) on the object",
        "Saying \"I want\" and \"I like\"; and the case ending that marks the object of a verb."),
    6: ("Present-tense routine with **अधुना / सम्प्रति** (now) marking what is underway — Sanskrit's present covers both",
        "\"I am doing\" with the word for \"now\" — Sanskrit's present tense covers both — woven through an ordinary routine."),
    7: ("Time — **कति वादनम्?**; weekdays (**सोमवासरः** …) & months; frequency adverbs **सर्वदा / कदाचित् / प्रतिदिनम्**",
        "Clock times; the days of the week and the months; and words like \"always\", \"sometimes\" and \"every day\"."),
    8: ("Polite imperatives (**लोट्** — भवान् गच्छतु / परिवर्तताम्); directions **ऋजु, वामतः / दक्षिणतः**; **प्रति** (towards)",
        "Polite commands like \"go\" and \"turn\"; directions — straight, left and right; and saying \"towards\" a place."),
    9: ("Prices — **कति मूल्यम्?**; amounts as words; **ददातु / इच्छामि** at the stall",
        "Asking prices — \"how much is it?\"; amounts in words; and \"please give me\" at the market stall."),
    10: ("Adjectives **उत्तम / बृहत् / लघु** agreeing with their noun; **धारयति** (wear)",
         "Adjectives — good, big and small — agreeing with their noun; and the verb for wearing clothes."),
    11: ("Weather expressions **उष्णम् अस्ति / आतपः अस्ति / वृष्टिः भवति**; simple future (**लृट्**) for the forecast (**वृष्टिः भविष्यति**)",
         "Talking about the weather — \"it is hot\", \"it is sunny\", \"it is raining\"; and the simple future for the forecast — \"it will rain\"."),
    12: ("Infinitive **-तुम्** (क्रीडितुम्) with **रोचते / गच्छामि**; ability **शक्नोति** (क्रीडितुं शक्नोमि) — landing inside varied actions and exchanges, not as declarations",
         "The infinitive — \"to play\", \"to learn\" — with \"I like to\" and \"I go to\"; and saying \"I can\"."),
    13: ("Polite requests — **ददातु / लभ्यते किम्? / कृपया**; thanking **धन्यवादः**",
         "Polite requests — \"will you give me?\", \"could I get?\", \"I need\"; and saying thank you."),
    14: ("**आरोहति / अवरोहति** (board/alight); the instrumental case with vehicles (**लोकयानेन, रेलयानेन**); **गन्तव्यम् अस्ति** (need to get to)",
         "Getting on and off buses and trains; \"by\" with vehicles — the instrumental case ending; and \"I need to get to\"."),
    15: ("Mixed present-tense narration; consolidation. BOUNDARY: no past tense anywhere — the past opens week 16",
         "Review week — everything so far, in flowing present-tense storytelling."),
    16: ("The past with the **-तवत्** participle (**गतवती, दृष्टवती** — spoken Sanskrit's everyday past); time phrases **ह्यः / गते सप्ताहे / जनवरीमासे** (the *asmi*-supported perfect is out of scope — week 19 owns it)",
         "The everyday past — \"came\", \"went\", \"saw\" — with the participle spoken Sanskrit uses; and time phrases like \"yesterday\", \"last week\" and \"in January\"."),
    17: ("Past narration; **स्वकीय** vs **तस्य / तस्याः** (one's own vs another's); time expressions",
         "Telling stories in the past tense; \"one's own\" versus \"his\" or \"hers\"; and more time expressions."),
    18: ("**वेदना** (मम शिरसि वेदना अस्ति); body parts; **कुशलम् अस्मि / न कुशलम्**; advice with **अर्हति** + infinitive (विश्रामं कर्तुम् अर्हति)",
         "Saying something hurts; the parts of the body; \"I feel fine\" and \"I don't feel well\"; and giving advice with \"you should\"."),
    19: ("\"Have done\" — the participle past with **अस्मि** (**कृतवती अस्मि**) for what she has done; professions",
         "The perfect — \"I have done\"; and the names of professions."),
    20: ("Past forms mixed; **शिक्षते + -तुम्** (learning to); ordinals **प्रथम / द्वितीय**",
         "Past and perfect together; \"learning to do\" something; and ordinal numbers — first, second, third."),
    21: ("Comparative **-तर** and **अपेक्षया** (अस्मात् बृहत्तरम्); trying on and exchanging",
         "Comparisons — \"bigger than\", \"smaller than\"; and trying on and exchanging things in a shop."),
    22: ("Imperative sequences; quantities (**अर्धं किलो, द्वौ चमसौ**); **प्रथमं / ततः / तदनन्तरम्**",
         "Step-by-step instructions; quantities like \"half a kilo\" and \"two spoons\"; and \"first\", \"then\", \"after that\"."),
    23: ("Future (**लृट्** — करिष्यामि) and \"let's\" (**कुर्मः / गच्छामः**); reporting thoughts with **इति** (अहं चिन्तयामि … इति)",
         "The future tense — \"it will\" and \"let's\"; and reporting thoughts — \"I think that…\" with Sanskrit's quoting word \"iti\"."),
    24: ("Imperatives + object pronouns **तम् / एनम्**; rules with **-तव्यम् / न कर्तव्यम्** (must / must not)",
         "Commands with \"it\" and \"him\"; and rules — \"you must\" and \"you must not\"."),
    25: ("Demonstratives **एषः/सः + एतत्/तत्** as a system; **पूर्वम्** (ago — मासद्वयात् पूर्वम्); time adverbs",
         "This and that — \"this shirt\", \"that one\"; saying \"ago\" — \"two months ago\"; and time adverbs."),
    26: ("**कृतवती अस्मि** vs bare **कृतवती** — \"have done\" vs \"did\" contrast",
         "The difference between \"I have done\" and \"I did\"."),
    27: ("Habitual **प्रायः / प्रतिदिनं करोति**; instructions; the passive present (**क्रियते, लिख्यते**) of official language",
         "Saying what you usually do; following instructions; and the formal passive of official notices."),
    28: ("Consolidation across all A2 grammar",
         "Review week — everything from the whole course, in one ordinary week of Maya's life."),
}

HEADER = {
    "mr": """# Marathi · Mumbai — Scope & Sequence (Year 1: A1 → A2, weeks 1–28)

Same story arc as `curriculum_da.md` (Copenhagen) and `variants/kochi/curriculum_ml.md`; the story is
re-instantiated in Mumbai, and the grammar is re-derived for Marathi. Scenes are authored in Marathi.

GENERATED FILE — the Theme and Brief columns come from `curriculum_hi.md` via `sync_curricula.py`;
edit the story there and re-run the script. Only the two grammar columns are Marathi-specific.
""",
    "sa": """# Sanskrit · Mumbai — Scope & Sequence (Year 1: A1 → A2, weeks 1–28)

Same story arc as `curriculum_da.md` (Copenhagen) and `variants/kochi/curriculum_ml.md`; the story is
re-instantiated in Mumbai, and the grammar is re-derived for spoken Sanskrit (Samskrita-Bharati-style
everyday register: the -tavat participle past, polite bhavān/bhavatī, no classical-corpus register).
Scenes are authored in Sanskrit.

GENERATED FILE — the Theme and Brief columns come from `curriculum_hi.md` via `sync_curricula.py`;
edit the story there and re-run the script. Only the two grammar columns are Sanskrit-specific.
""",
}


def build(lang: str, table: dict) -> None:
    out = [HEADER[lang]]
    for line in (HERE / "curriculum_hi.md").read_text("utf-8").splitlines():
        parts = line.split("|")
        if len(parts) >= 8 and parts[1].strip().isdigit():
            wk = int(parts[1].strip())
            parts[4] = f" {table[wk][0]} "
            parts[6] = f" {table[wk][1]} "
            out.append("|".join(parts))
        elif line.startswith("|"):
            out.append(line)  # the table header rows
    (HERE / f"curriculum_{lang}.md").write_text("\n".join(out) + "\n", "utf-8")
    print(f"curriculum_{lang}.md: {sum(1 for r in out if r.split('|')[1:2] and r.split('|')[1].strip().isdigit())} rows")


build("mr", MR)
build("sa", SA)
