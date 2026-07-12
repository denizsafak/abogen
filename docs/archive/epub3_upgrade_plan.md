# EPUB 3 Upgrade Plan

## Overview
Elevate Abogen to produce rich EPUB 3 packages with synchronized narration, configurable TTS chunking, and groundwork for multi-speaker voice assignment. This document records the objectives, architectural adjustments, data model changes, UI flows, and implementation phases required to deliver the upgrade.

## Goals
- Generate EPUB 3 output that preserves source metadata and embeds audio narration via media overlays.
- Allow users to choose the chunking granularity (paragraph vs. sentence) used for TTS synthesis and media-overlay alignment.
- Introduce speaker assignments for every chunk, starting with a single narrator but paving the way for multi-speaker control.
- Prototype practical, lightweight strategies for detecting likely speakers and estimating their dialogue frequency.

## Non-goals / Out-of-scope
- Full multi-speaker editing UI (beyond gating the option).
- Automatic voice-casting or LLM-based dialogue attribution.
- Desktop GUI resurrection (web UI remains primary).

## Current Architecture Snapshot
| Area | Notes |
| --- | --- |
| Text ingestion | `abogen/text_extractor.py` outputs `ExtractionResult` with chapter-level text.
| Job prep UI | `web/routes.py` builds `PendingJob` objects and renders chapter selection.
| Audio pipeline | `web/conversion_runner.py` creates per-job audio artifacts; chunking is effectively paragraph-level.
| Metadata | `ExtractionResult.metadata` feeds into FF metadata and output tagging, but not yet into EPUB packaging.

## Feature 1 – EPUB 3 Output with Narration
### Requirements
- Preserve original EPUB metadata (Dublin Core entries, TOC, cover art).
- Package synthesized audio and SMIL media overlays aligned to chosen chunk granularity.
- Provide EPUB as an additional selectable output alongside current audio/subtitle formats.

### Proposed Components
1. **`abogen/epub3/exporter.py`** (new module)
   - Responsibilities: build XHTML spine with IDs, generate overlay SMIL files, write OPF manifest/spine, assemble zip package.
   - Status: **Implemented** — `build_epub3_package` emits EPUB 3 archives with media overlays driven by chunk metadata.
   - Dependencies: reuse `ebooklib` for reading source metadata; use `zipfile` for packaging; optional `lxml` for DOM manipulation.
2. **`EPUB3PackageBuilder` class**
   - Inputs: extraction payload, chunk collection (with IDs, speaker mapping, timing metadata), audio asset paths, source metadata.
   - Outputs: path to generated EPUB.
3. **Metadata preservation**
   - Copy from source `ExtractionResult.metadata` and EPUB navigation if available.
   - Ensure custom fields (e.g., chapter count) survive.
4. **Media overlay generation**
   - Create one SMIL per content doc or per chapter, depending on chunk count.
   - `<par>` nodes reference chunk IDs and audio clip times.
5. **Configuration surface**
   - Add “EPUB 3 (audio + text)” to output format selector (or a dedicated toggle under project settings).

### Data Flow
```
extract_from_path -> Chapter payload
              |-> chunker (sentence/paragraph)
              |-> chunk IDs + audio segments (timestamps from runner)
Conversion runner -> audio files + timing index
EPUB3PackageBuilder -> manifest, spine, SMIL, zip
```

### Open Questions
- Should we embed audio inside the EPUB or link externally? (Plan: embed to comply with spec.)
- How to handle very large audio assets? Consider splitting per chapter to keep file sizes manageable.

## Feature 2 – Configurable Chunking
### Requirements
- Users select chunking level (paragraph or sentence) before audio generation.
- Pipeline produces stable, unique IDs for each chunk regardless of level.
- Provide chunk metadata (text, speaker, offsets) to both TTS and EPUB exporter.

### Proposed Architecture
1. **Chunk Model**
   ```python
   @dataclass
   class Chunk:
       id: str
       chapter_index: int
       order: int
       level: Literal["paragraph", "sentence"]
       text: str
       speaker_id: str
       approx_characters: int
   ```
2. **Chunker Service (`abogen/chunking.py`)**
   - Accepts chapter text and desired level.
   - Uses spaCy (already bundled via `en-core-web-sm`) for sentence segmentation; fallback to regex when model unavailable.
   - Emits `Chunk` objects with deterministic IDs (e.g., `chap{chapter_index:04d}_para{paragraph_idx:03d}_sent{sentence_idx:03d}`).
3. **Integration points**
   - `web/routes.py` -> apply chunker when building `PendingJob` instead of storing raw paragraphs only.
   - `PendingJob` / `Job` dataclasses -> include `chunks` list and `chunk_level` enum.
   - `conversion_runner` -> iterate over `chunks` when synthesizing audio, producing per-chunk audio and capturing actual duration for overlay.
4. **Settings persistence**
   - Extend config with `chunking_level` default; expose in UI (radio buttons or select).

### Testing
- Unit tests for chunk splitting across languages, punctuation, abbreviations.
- Property-based tests ensuring concatenated chunks reproduce original text (except whitespace normalization).

## Feature 3 – Speaker Assignment Foundations
### Requirements
- Every chunk must carry a `speaker_id` (default `narrator`).
- UI offers new option: “Single Speaker” (proceeds) vs. “Multi-Speaker (Coming Soon)” (blocks and shows message).
- Data model anticipates future multi-speaker support.

### Implementation Outline
1. **Data Model Changes**
   - `Chunk.speaker_id` default `"narrator"`.
   - `PendingJob` & `Job` store `speakers` metadata (dictionary of speaker descriptors).
   - `JobResult` optionally includes `chunk_speakers.json` artifact for downstream use.
2. **UI Adjustments**
   - On upload form (`index.html` / JS), add selector for speaker mode.
   - If “Multi-Speaker” chosen, display tooltip/modal: “Coming soon; please choose Single Speaker to continue.” disable submission.
   - In `prepare_job.html`, display speaker info column (read-only for now).
3. **Serialization**
   - Update JSON API routes to include speaker data.
   - Update queue/job detail templates to show chunk level & speaker summary.

### Testing
- Add web route tests ensuring multi-speaker path blocks progression.
- Verify job persistence includes `speaker_id` fields.

## Feature 4 – Speaker Detection Strategies
### Objectives
Build groundwork for lightweight, deterministic speaker inference to inform future multi-speaker mode.

### User Stories
1. **As a producer**, I can run an automated analysis on a book to see the list of likely speakers and how often they talk, so I can decide where multiple voices make sense.
   - _Acceptance_: System outputs a JSON report containing speaker IDs/names, occurrence counts, representative excerpts, and confidence tier. Report stored with job artifacts and downloadable from job detail page.
2. **As a producer**, I can set a minimum occurrence threshold so that infrequent speakers automatically fall back to the narrator voice.
   - _Acceptance_: Analysis respects configurable threshold; speakers below it are tagged as `default_narrator` in the report.
3. **As a developer/operator**, I can trigger the analysis via CLI or background task without blocking the main conversion pipeline.
   - _Acceptance_: Command `abogen analyze-speakers <input>` (or background queue hook) runs in isolation, returns exit code 0 on success, emits metrics/logs for CI.

### Strategy Ideas
1. **Quotation-bound heuristic**
   - Split paragraphs on dialogue quotes.
   - Use verb cues ("said", "asked") to associate names preceding/following quotes.
2. **Name detection via NER**
   - Use spaCy’s entity recognition to spot `PERSON` entities inside dialogue spans.
   - Maintain frequency counts per name.
3. **Speaker dictionary**
   - Pre-build mapping of common narrator cues ("he said", "Mary replied") to propagate speaker assignment across adjacent sentences.
4. **Pronoun fallback with gender hints**
   - Map pronouns to most recent speaker mention; degrade gracefully when ambiguous.
5. **Thresholding mechanism**
   - After counting occurrences, expose a threshold slider (future UI) to decide when to allocate unique voices vs. default narrator.
6. **Diagnostics**
   - Provide summary report: top N speaker candidates, counts, unresolved dialogue segments.

### Implementation Staging
1. **Phase 1 – Analysis Engine (Backend)**
   - Build `speaker_analysis.py` module implementing heuristics, returning structured results.
   - Add CLI entry point `abogen-speaker-analyze` for standalone runs.
   - Persist analysis artifacts (`speakers.json`, `speaker_excerpts.csv`) alongside job data when invoked post-extraction.
   - Tests: unit tests for heuristic functions; snapshot tests for sample novels.
2. **Phase 2 – Configuration & Thresholding**
   - Extend settings UI with optional “speaker analysis threshold” control (numeric).
   - Update analysis module to accept threshold; mark low-frequency speakers as narrator.
   - Emit summary digest (top speakers, narrator fallback count) in job logs.
3. **Phase 3 – UI Surfacing**
   - Display analysis summary on job detail page (charts/table).
   - Offer download link for raw JSON/CSV artifacts.
   - Provide warning banner when analysis confidence is low (e.g., high unmatched dialogue percentage).
4. **Phase 4 – Integration Hooks**
   - Wire analysis output into chunk speaker assignments (without yet enabling multi-speaker playback).
   - Store mapping in `Job.speakers` metadata for future voice routing.

### Technical Notes
- Reuse spaCy `en_core_web_sm` for entity recognition; allow pluggable models per language.
- Maintain rolling context window to resolve pronouns (e.g., last two named speakers).
- Provide instrumentation (timings, counts) to assess heuristic accuracy on sample corpora.
- Design analysis output schema versioning (`speaker_analysis_version`) to support iterative improvements.

## UI & Configuration Updates
| Screen | Update |
| --- | --- |
| Upload form (`index.html`) | Add chunking level selector and speaker mode buttons. |
| Prepare job (`prepare_job.html`) | Display chunk level, IDs, speaker column; allow future editing hooks. |
| Settings modal | Persist defaults for chunking level and speaker mode. |

## Data Model Checklist
- [x] Update `PendingJob` and `Job` dataclasses with `chunk_level`, `chunks`, `speakers` metadata.
- [x] Ensure serialization persists these fields in queue state file.
- [x] Persist chunk timing metadata from TTS (start/end timestamps).

## Testing Strategy
- Unit tests for chunker and speaker heuristics.
- Integration tests: enqueue job with sentence-level chunking, assert chunk IDs and speaker metadata.
- Regression tests: ensure existing paragraph-level jobs still succeed.
- Acceptance tests for EPUB exporter: validate manifest, spine, and SMIL structure against schema (use `epubcheck` in CI if feasible).

## Migration & Compat
- Bump state version in `ConversionService` when augmenting job schema; include migration logic for legacy queues.
- Provide CLI flag to reprocess older jobs without speaker metadata.
- Document new dependencies (e.g., `lxml`, optional spaCy models for languages beyond English).

## Implementation Phases
1. **Foundation** – Introduce chunk model, chunker service, speaker defaults.
2. **Pipeline integration** – Update job lifecycle and TTS runner to work with chunks.
3. **EPUB exporter** – Build packaging module, connect to pipeline.
4. **UI polish** – Expose settings, guard multi-speaker path, surface diagnostics.
5. **Speaker analysis tool** – Prototype heuristics and reporting.

## Open Questions
- How to handle non-EPUB inputs (PDF/TXT) when exporting EPUB 3? (Possible: generate synthetic XHTML with normalized chapters.)
- Storage impact of embedding per-chunk audio – do we need compression or streaming strategies?
- Internationalization: sentence segmentation quality varies; need language-specific models.

## Next Steps
- Review plan with stakeholders for scope confirmation.
- Break down Phase 1 into actionable tickets (chunker, data model migration, UI toggle).
- Estimate resource requirements for EPUB packaging and testing (including epubcheck integration).
