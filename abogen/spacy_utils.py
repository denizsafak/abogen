"""
Lazy-loaded spaCy utilities for sentence segmentation.
"""

# Cached spaCy module and models (lazy loaded)
_spacy = None
_nlp_cache = {}

# Language code to spaCy model mapping
SPACY_MODELS = {
    "a": "en_core_web_sm",  # American English
    "b": "en_core_web_sm",  # British English
    "e": "es_core_news_sm",  # Spanish
    "f": "fr_core_news_sm",  # French
    "i": "it_core_news_sm",  # Italian
    "p": "pt_core_news_sm",  # Brazilian Portuguese
    "z": "zh_core_web_sm",  # Mandarin Chinese
    "j": "ja_core_news_sm",  # Japanese
    "h": "xx_sent_ud_sm",  # Hindi (multi-language model)
}


def _load_spacy():
    """Lazy load spaCy module."""
    global _spacy
    if _spacy is None:
        try:
            import spacy

            _spacy = spacy
        except ImportError:
            return None
    return _spacy


def get_spacy_model(lang_code, log_callback=None):
    """
    Get or load a spaCy model for the given language code.
    Downloads the model automatically if not available.

    Args:
        lang_code: Language code (a, b, e, f, etc.)
        log_callback: Optional function to log messages

    Returns:
        Loaded spaCy model or None if unavailable
    """

    def log(msg, is_error=False):
        # Prefer GUI log callback when provided to avoid spamming stdout.
        if log_callback:
            color = "red" if is_error else "grey"
            try:
                log_callback((msg, color))
            except Exception:
                # Fallback to printing if callback misbehaves
                print(msg)
        else:
            print(msg)

    # Check if model is cached
    if lang_code in _nlp_cache:
        return _nlp_cache[lang_code]

    # Check if language is supported
    model_name = SPACY_MODELS.get(lang_code)
    if not model_name:
        log(f"\nspaCy: No model mapping for language '{lang_code}'...")
        return None

    # Lazy load spaCy
    spacy = _load_spacy()
    if spacy is None:
        log("\nspaCy: Module not installed, falling back to default segmentation...")
        return None

    # Try to load the model
    try:
        log(f"\nLoading spaCy model '{model_name}'...")
        # sentence segmentation involving parentheses, quotes, and complex structure.
        # We only disable heavier components we don't need like NER.
        nlp = spacy.load(
            model_name,
            disable=["ner", "tagger", "lemmatizer", "attribute_ruler"],
        )

        # Ensure a sentence segmentation strategy is in place
        # The parser provides sents, but if it's missing (unlikely for core models), fallback to sentencizer
        if "parser" not in nlp.pipe_names and "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")

        _nlp_cache[lang_code] = nlp
        return nlp
    except OSError:
        # Model not found, attempt download
        log(f"\nspaCy: Downloading model '{model_name}'...")
        try:
            from spacy.cli import download

            download(model_name)
            # Retry loading with the same fix
            nlp = spacy.load(
                model_name,
                disable=["ner", "tagger", "lemmatizer", "attribute_ruler"],
            )
            if "parser" not in nlp.pipe_names and "sentencizer" not in nlp.pipe_names:
                nlp.add_pipe("sentencizer")

            _nlp_cache[lang_code] = nlp
            log(f"spaCy model '{model_name}' downloaded and loaded")
            return nlp
        except Exception as e:
            log(
                f"\nspaCy: Failed to download model '{model_name}': {e}...",
                is_error=True,
            )
            return None
    except Exception as e:
        log(f"\nspaCy: Error loading model '{model_name}': {e}...", is_error=True)
        return None


def segment_sentences(text, lang_code, log_callback=None):
    """
    Segment text into sentences using spaCy.

    Args:
        text: Text to segment
        lang_code: Language code
        log_callback: Optional function to log messages

    Returns:
        List of sentence strings, or None if spaCy unavailable
    """
    nlp = get_spacy_model(lang_code, log_callback)
    if nlp is None:
        return None

    # Ensure spaCy can handle large texts by adjusting max_length if necessary
    try:
        text_len = len(text or "")
        if text_len and hasattr(nlp, "max_length") and text_len > nlp.max_length:
            # increase a bit beyond the text length to be safe
            nlp.max_length = text_len + 1000
    except Exception:
        pass

    # Process text and extract sentences
    doc = nlp(text)
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


def is_spacy_available():
    """Check if spaCy can be imported."""
    return _load_spacy() is not None


def clear_cache():
    """Clear the model cache to free memory."""
    global _nlp_cache
    _nlp_cache.clear()
