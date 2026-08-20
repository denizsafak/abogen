# AGENTS.md — Segmentation & Subtitle System Contract

This document is the source of truth for how text is split for **voice
processing** (TTS engine segmentation) and **subtitle processing**, across
languages, TTS engines, and subtitle modes. It was written after a bug where
sentence modes "processed all text as a whole" (one merged engine segment →
one giant subtitle). **Do not change this behavior without updating this
table.**

## Voice processing — split pattern passed to the TTS engine

`get_split_pattern(language, mode)` in `abogen/domain/split_pattern.py` is the
default; the spaCy pre-TTS path overrides it. Both UIs must stay in sync:
`spacy_pre_tts_segmentation` (`abogen/domain/conversion_pipeline.py`, WebUI)
and the inline branch in `abogen/pyqt/conversion.py` (~line 860, PyQt).

| Subtitle mode | English (en-US/en-GB) | Non-English, spaCy ON | Non-English, spaCy OFF | CJK (ja/zh) |
|---|---|---|---|---|
| Disabled | `\n` | spaCy pre-split, engine `\n` | `\n+` | `(?<=[.!?؟。！？।])\s*\|\n+` |
| Line | `\n` | spaCy pre-split, engine `\n` | `\n` | `(?<=[.!?؟。！？।])\s*\|\n+` |
| Sentence | `\n` | spaCy pre-split, engine `\n` | `(?<=[.!?؟。！？।])\s+\|\n+` | `(?<=[.!?؟。！？।])\s*\|\n+` |
| Sentence + Comma | `\n` | spaCy pre-split, engine `\n` | `(?<=[.!?,؟。！？،،、।])\s+\|\n+` (commas kept) | `(?<=[.!?,؟。！？،،、।])\s*\|\n+` |
| Sentence + Highlighting | `\n+` | `\n+` | `\n+` | `\n+` |
| N words ("5 words") | `\n` (→ Disabled) | `\n+` | `\n+` | Disabled CJK pattern |

Rules baked into this table:

- **English voice splitting is ALWAYS newline-only** for Disabled, Line,
  Sentence, and Sentence + Comma. English sentence/comma boundaries are
  produced ONLY at subtitle time (spaCy post-TTS / regex fallback). Never add
  punctuation to the English engine pattern.
- **Non-English + spaCy ON**: spaCy pre-segments the text (pre-TTS); the
  engine pattern is `\n` for Sentence AND Sentence + Comma — **never commas**.
  spaCy is skipped when the toggle is off, mode is Disabled/Line, or input is
  a subtitle file.
- **Non-English + spaCy OFF** (toggle off, spaCy failure, subtitle input): the
  default pattern is used — Sentence + Comma KEEPS its commas here. This is
  the intentional fallback, not a bug.
- CJK: punctuation-based patterns for Disabled/Line (historical); spacing is
  `\s*` (no spaces needed between CJK chars).
- Engine-level extra chunking (applies after the pattern): kokoro English
  re-chunks at ~510 phonemes; kokoro non-English at ~400 chars; supertonic
  caps each part at 300 chars.

## Subtitle processing — post-TTS, from tokens

| Mode | Behavior |
|---|---|
| Disabled | no subtitles |
| Line | one entry per TTS segment (line) |
| Sentence | sentence boundaries: English → spaCy; others → regex on `[.!?…]` |
| Sentence + Comma | sentence + comma boundaries at subtitle time (both languages) — commas never affect voice |
| Sentence + Highlighting | karaoke `{\kf…}` per word, grouped by sentence |
| N words | groups of N words by whitespace counting |

Token granularity (timing quality): kokoro English emits **per-word tokens**
with timestamps; kokoro non-English and supertonic emit **no tokens** → each
engine segment becomes one FakeToken, split by regex with proportional timing
when it contains multiple sentences.

## Hard invariants (breaking these reintroduces the original bug)

1. `Pipeline.__call__` (`abogen/tts_plugin/utils.py`) must yield ONE `Segment`
   per engine segment (with tokens) — never merge segments back into the
   whole text. `SynthesizedAudio.segments` carries the per-segment data;
   engines expose it in `plugins/kokoro/engine.py` and
   `plugins/supertonic/engine.py`.
2. `tts_segments` (`abogen/domain/conversion_pipeline.py`) restores trailing
   whitespace on segment-boundary tokens ONLY for real per-word tokens, never
   for FakeToken fallbacks.
3. `_to_language_enum` must return `lang_code` as-is when it is already a
   `Language` enum (`str(Language.ES)` is `"Language.ES"`, which silently
   resolved to EN_US and disabled spaCy pre-TTS for every language in WebUI).
4. English must never use spaCy for PRE-TTS segmentation — only for subtitles.

## Guarded by tests

- `tests/test_split_pattern.py` — English newline-only; non-English sentence
  patterns; CJK behavior.
- `tests/test_domain_conversion_pipeline.py` — `tts_segments` / spaCy
  segmentation helpers.
- Full suite: `python -m pytest tests/ -q` (expect 1566+ passing).