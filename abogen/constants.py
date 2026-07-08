from abogen.utils import get_version

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

# Language description mapping
LANGUAGE_DESCRIPTIONS = {
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
# Currently, only 'a (American English)' and 'b (British English)' are supported for subtitle generation.
# This is because tokens that contain timestamps are not generated for other languages in the Kokoro pipeline.
# Please refer to: https://github.com/hexgrad/kokoro/blob/6d87f4ae7abc2d14dbc4b3ef2e5f19852e861ac2/kokoro/pipeline.py
# 383 English processing (unchanged)
# 384 if self.lang_code in 'ab':
SUPPORTED_LANGUAGES_FOR_SUBTITLE_GENERATION = list(LANGUAGE_DESCRIPTIONS.keys())

# Voice and sample text mapping
SAMPLE_VOICE_TEXTS = {
    "a": "This is a sample of the selected voice.",
    "b": "This is a sample of the selected voice.",
    "e": "Este es una muestra de la voz seleccionada.",
    "f": "Ceci est un exemple de la voix sélectionnée.",
    "h": "यह चयनित आवाज़ का एक नमूना है।",
    "i": "Questo è un esempio della voce selezionata.",
    "j": "これは選択した声のサンプルです。",
    "p": "Este é um exemplo da voz selecionada.",
    "z": "这是所选语音的示例。",
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
