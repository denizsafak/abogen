from abogen.utils import get_version
from abogen.domain.enums import Language

# Program Information
PROGRAM_NAME = "abogen"
PROGRAM_DESCRIPTION = "Generate audiobooks from EPUBs, PDFs, text and subtitles with synchronized captions."
GITHUB_URL = "https://github.com/denizsafak/abogen"
VERSION = get_version()

# Settings
CHAPTER_OPTIONS_COUNTDOWN = 30  # Countdown seconds for chapter options
SUBTITLE_FORMATS = [
    ("srt", "SRT (standard)"),
    ("ass_wide", "ASS (wide)"),
    ("ass_narrow", "ASS (narrow)"),
    ("ass_centered_wide", "ASS (centered wide)"),
    ("ass_centered_narrow", "ASS (centered narrow)"),
]

# Language description mapping (Language enum → human-readable label).
LANGUAGE_DESCRIPTIONS = {
    Language.EN_US: "American English",
    Language.EN_GB: "British English",
    Language.ES: "Spanish",
    Language.FR: "French",
    Language.HI: "Hindi",
    Language.IT: "Italian",
    Language.JA: "Japanese",
    Language.PT_BR: "Brazilian Portuguese",
    Language.ZH: "Mandarin Chinese",
}

# Display-only mapping for kokoro codes → labels.
# Used by voice catalog and PyQt (legacy) where kokoro codes are still present.
KOKORO_CODE_LABELS = {
    "a": "American English",
    "b": "British English",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese",
    "p": "Brazilian Portuguese",
    "z": "Mandarin Chinese",
}

# Supported sound formats
SUPPORTED_SOUND_FORMATS = [
    "wav",
    "mp3",
    "opus",
    "m4b",
    "flac",
]

# Supported subtitle formats
SUPPORTED_SUBTITLE_FORMATS = [
    "srt",
    "ass",
    "vtt",
]

# Supported input formats
SUPPORTED_INPUT_FORMATS = [
    "epub",
    "pdf",
    "txt",
    "srt",
    "ass",
    "vtt",
]

# Supported languages for subtitle generation
# Currently, only English (EN_US, EN_GB) are supported for subtitle generation.
# This is because tokens that contain timestamps are not generated for other languages in the Kokoro pipeline.
# Please refer to: https://github.com/hexgrad/kokoro/blob/6d87f4ae7abc2d14dbc4b3ef2e5f19852e861ac2/kokoro/pipeline.py
SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION = [Language.EN_US, Language.EN_GB]

# Voice and sample text mapping
SAMPLE_VOICE_TEXTS = {
    Language.EN_US: "This is a sample of the selected voice.",
    Language.EN_GB: "This is a sample of the selected voice.",
    Language.ES: "Este es una muestra de la voz seleccionada.",
    Language.FR: "Ceci est un exemple de la voix sélectionnée.",
    Language.HI: "यह चयनित आवाज़ का एक नमूना है।",
    Language.IT: "Questo è un esempio della voce selezionata.",
    Language.JA: "これは選択した声のサンプルです。",
    Language.PT_BR: "Este é um exemplo da voz selecionada.",
    Language.ZH: "这是所选语音的示例。",
}

COLORS = {
    "BLUE": "#007dff",
    "RED": "#c0392b",
    "ORANGE": "#FFA500",
    "GREEN": "#42ad4a",
    "GREEN_BG": "rgba(66, 173, 73, 0.1)",
    "GREEN_BG_HOVER": "rgba(66, 173, 73, 0.15)",
    "GREEN_BORDER": "#42ad4a",
    "BLUE_BG": "rgba(0, 102, 255, 0.05)",
    "BLUE_BG_HOVER": "rgba(0, 102, 255, 0.1)",
    "BLUE_BORDER_HOVER": "#6ab0de",
    "YELLOW_BACKGROUND": "rgba(255, 221, 51, 0.40)",
    "GREY_BACKGROUND": "rgba(128, 128, 128, 0.15)",
    "GREY_BORDER": "#808080",
    "RED_BACKGROUND": "rgba(232, 78, 60, 0.15)",
    "RED_BG": "rgba(232, 78, 60, 0.10)",
    "RED_BG_HOVER": "rgba(232, 78, 60, 0.15)",
    # Theme palette colors
    "DARK_BG": "#202326",
    "DARK_BASE": "#141618",
    "DARK_ALT": "#2c2f31",
    "DARK_BUTTON": "#292c30",
    "DARK_DISABLED": "#535353",
    "LIGHT_BG": "#eff0f1",
    "LIGHT_DISABLED": "#9a9999",
}
