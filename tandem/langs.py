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
    # 2026-07 expansion (every remaining Chirp3-HD Sulafat locale, one narrator everywhere)
    "nl": ("Dutch", "nl-NL"), "pl": ("Polish", "pl-PL"), "nb": ("Norwegian", "nb-NO"),
    "fi": ("Finnish", "fi-FI"), "cs": ("Czech", "cs-CZ"), "sk": ("Slovak", "sk-SK"),
    "hu": ("Hungarian", "hu-HU"), "ro": ("Romanian", "ro-RO"), "bg": ("Bulgarian", "bg-BG"),
    "el": ("Greek", "el-GR"), "hr": ("Croatian", "hr-HR"), "sr": ("Serbian", "sr-RS"),
    "sl": ("Slovenian", "sl-SI"), "lt": ("Lithuanian", "lt-LT"), "lv": ("Latvian", "lv-LV"),
    "et": ("Estonian", "et-EE"), "uk": ("Ukrainian", "uk-UA"), "tr": ("Turkish", "tr-TR"),
    "id": ("Indonesian", "id-ID"), "th": ("Thai", "th-TH"), "vi": ("Vietnamese", "vi-VN"),
    "yue": ("Cantonese", "yue-HK"), "he": ("Hebrew", "he-IL"), "sw": ("Swahili", "sw-KE"),
}

LANG_NAMES = {code: name for code, (name, _) in LANGS.items()}
LOCALES = {code: loc for code, (_, loc) in LANGS.items() if loc}
