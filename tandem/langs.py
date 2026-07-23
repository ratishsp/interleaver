"""The language registry: code -> (English name, Google TTS locale) — ONE place to add a language.

Every other table is a view of this: LANG_NAMES feeds the translate/verify prompts, LOCALES the audio
builders (a Chirp3-HD voice is just f"{locale}-Chirp3-HD-{speaker}"). Before this, adding a language
meant editing name/locale dicts in five files in lockstep (translate.py, gen_deck, build_lang,
build_pair, combine_all) — and they had already drifted.
"""

LANGS = {
    "da": ("Danish", "da-DK"), "en": ("English", "en-US"), "sv": ("Swedish", "sv-SE"),
    "sa": ("Sanskrit", None),   # no Google voice — Gefion indic-parler (or the mr-IN approximation)
    # Indian
    "hi": ("Hindi", "hi-IN"), "ta": ("Tamil", "ta-IN"), "ml": ("Malayalam", "ml-IN"),
    "bn": ("Bengali", "bn-IN"), "gu": ("Gujarati", "gu-IN"), "kn": ("Kannada", "kn-IN"),
    "mr": ("Marathi", "mr-IN"), "pa": ("Punjabi", "pa-IN"), "te": ("Telugu", "te-IN"),
    "ur": ("Urdu", "ur-IN"),
    # European
    "es": ("Spanish", "es-ES"), "fr": ("French", "fr-FR"), "de": ("German", "de-DE"),
    "it": ("Italian", "it-IT"), "pt": ("Portuguese", "pt-BR"), "ru": ("Russian", "ru-RU"),
    # Asian / other
    "cmn": ("Mandarin Chinese", "cmn-CN"), "ja": ("Japanese", "ja-JP"), "ko": ("Korean", "ko-KR"),
    "ar": ("Arabic", "ar-XA"),
}

LANG_NAMES = {code: name for code, (name, _) in LANGS.items()}
LOCALES = {code: loc for code, (_, loc) in LANGS.items() if loc}
