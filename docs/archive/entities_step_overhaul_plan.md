# Entities Step Overhaul Plan

## Requirements Recap
- Integrate part-of-speech (POS) tagging to detect proper nouns with better precision.
- Rename Step 3 of the wizard from **Speakers** to **Entities** everywhere (routes, templates, copy, JS).
- Introduce a sub-navigation immediately below the step indicators with three tabs: **People**, **Entities**, **Manual Overrides**.
- Populate tabs with appropriate data:
  - **People**: characters with dialogue/speech evidence.
  - **Entities**: non-person proper nouns (organizations, places, artefacts, etc.).
  - **Manual Overrides**: user-added entries with search-driven selection, pronunciation editing, and voice assignment tools.
- Allow manual overrides to:
  - Search for tokens present in the uploaded manuscript/EPUB.
  - Configure pronunciations and pick a voice (defaulting to narrator voice).
  - Trigger previews using the same audio preview logic as other steps.
- Provide voice selection dropdowns (with auto-generate, browse, clear, etc.) for People and Manual Override rows.
- Tighten extraction logic so only proper nouns surface (no "The", "That", etc.).
- Normalise detected names by removing titles ("Mr.", "Dr.") and possessives ("Bob's" -> "Bob").
- Retain expandable sample paragraphs for context ("Preview full text" pattern) in the People tab and wherever excerpts appear.
- Persist pronunciation overrides in a shared store so recurring entities automatically preload past settings.
- Apply pronunciation overrides to every preview request and final conversion so TTS always respects user inputs.
- Add a help page documenting phonetic spelling techniques (inspired by the CMU guide) and surface it via a contextual tooltip/icon inside Step 3.

## Additional Considerations & Assumptions
- POS tagging scope is English-only for the initial release; spaCy will process the manuscript once and cache results so repeated visits to Step 3 reuse the parsed doc.
- spaCy core is MIT-licensed while the bundled `en_core_web_sm` model is CC BY-SA 3.0; we must include attribution and ensure redistribution remains compliant with the share-alike terms when packaging the model.
- spaCy may surface unusual proper nouns (e.g., fantasy names); users can leave them unchanged or override as desired.
- Manual overrides should persist with the pending job so that they can influence subsequent steps and final conversion. We likely need to extend pending job JSON storage and final job payloads.
- People tab currently depends on `pending.speakers` generated in `speaker_analysis.py`. Re-architecting should avoid breaking existing downstream behaviour (e.g., queueing with selected voices).
- Entities tab is new; we need to decide what metadata to display (count, first occurrence, sample sentences) and how it affects conversion (e.g., optional pronunciations, tags?). For now, assume read-only insights with optional pronunciation overrides similar to People.
- Voice preview/generation flows already live in `prepare.js`; ensure refactors keep a single source of truth to avoid duplication.

## Linguistic & Data Strategy
1. **POS Tagging Research & Adoption**
   - Leverage **spaCy** (>=3.5) for tokenisation, POS tagging, and named entity recognition (NER). It offers:
     - Accurate POS tags for proper nouns (`PROPN`).
     - Entity type labels (`PERSON`, `ORG`, `GPE`, etc.) that can help route to People vs Entities.
   - Add `spacy` to dependencies and document model installation (`en_core_web_sm` minimum). Provide fallbacks:
     - If model missing, prompt friendly error and skip advanced detection rather than failing job.
     - Future extension: allow language-specific models per job language (English default, warn otherwise).

2. **Proper Noun Filtering Logic**
   - Process each chapter/chunk through spaCy pipeline.
   - For each token / entity:
     - Keep tokens tagged `PROPN` or NER labelled as proper nouns.
     - Discard stopwords and determiners even if mislabelled (helps avoid "The", "That").
     - Normalise by removing leading titles (`Mr.`, `Dr.`, `Lady`, etc.) and trailing possessives (`'s`, `’s`).
     - Merge contiguous proper nouns into multi-word names (spaCy entity spans help).
   - Build frequency map; attach contextual snippets (e.g., surrounding sentence) for each.
   - Classify as Person vs Entity:
     - If entity label `PERSON` or strongly associated with dialogue attribution (existing heuristics), treat as **Person**.
     - Otherwise, map to **Entity**; optionally infer subtypes (Org, Place) for later enhancements.

3. **Integration with Existing Speaker Analysis**
   - Reuse dialogue-based detection (`speaker_analysis.py`) for People to keep gender heuristics and sample quotes.
   - Align IDs: ensure People tab entries map to existing speaker IDs so voice selections propagate to final job.
   - Entities tab can draw from new data structure, decoupled from `speaker_analysis` but referencing chapter/chunk indices.

4. **Manual Overrides Workflow**
   - Backend:
     - Maintain `pending.manual_overrides` list containing `token`, `normalised_label`, `pronunciation`, `voice`, `notes`, `context`, while syncing to a persistent overrides table (e.g., SQLite) keyed by normalised token + language so history is reused across projects. Manual entries do not require spaCy detection—users can add arbitrary tokens.
  - On load, hydrate the pending list with any matching historical overrides before rendering Step 3.
  - Provide API endpoints:
       1. `GET` suggestions for a search query (scan processed tokens + raw text indexes).
       2. `POST` create/update override entries.
       3. `DELETE` override.
   - Frontend:
     - Search input with debounced calls to suggestion endpoint; results list to choose target word/phrase.
     - Once selected, show pronunciation input, voice picker (reusing component from People), preview buttons.
    - Allow manual entry of custom tokens when no suggestion matches (spaCy not required).
    - Persist changes via AJAX (same pattern as existing speaker updates if possible) or within form submission when continuing.

## Implementation Plan
1. **Backend Enhancements**
   - Add spaCy dependency and lazy-load model in `speaker_analysis.py` or a new `entity_analysis.py` module.
  - Cache parsed spaCy documents per pending job (disk-backed or memoized) so repeated analysis reuses existing results without reprocessing the manuscript.
   - Implement `extract_entities(chapters, language, config)` returning structure:
     ```python
     {
       "people": [
         {"id": "speaker_1", "label": "Bob", "count": 12, "samples": [...], ...}
       ],
       "entities": [
         {"id": "entity_1", "label": "Starfleet", "kind": "ORG", "count": 5, "snippets": [...]}
       ],
       "index": {...}  # for search/autocomplete
     }
     ```
   - Enhance normalisation function to strip titles/possessives and collapse whitespace/diacritics consistently.
   - Integrate entity output into pending job serialization so Step 3 view can render tabs without recomputation.
   - Update job finalisation logic to include manual overrides and entity-derived metadata (for future TTS improvements).
  - Introduce a persistent pronunciation overrides repository (SQLite via SQLAlchemy layer) shared across jobs/instances, with migrations and CRUD helpers.
  - Apply pronunciation overrides to preview/conversion pipelines by substituting text prior to TTS synthesis (covering narrator defaults, People tab assignments, Entities tab items, and manual overrides on every TTS run).

2. **Template & UI Updates**
   - Rename Step 3 to **Entities** in all templates (`prepare_speakers.html`, upload modal partial, step indicator macros).
   - Refactor `prepare_speakers.html` to:
     - Wrap content in tabbed interface (likely `<div role="tablist">` + panels).
     - Tab panels:
       1. **People**: existing speaker list; adjust headings and copy.
       2. **Entities**: new list/grid showing non-person entities with counts and sample context; include optional pronunciation/voice controls if relevant.
       3. **Manual Overrides**: search box, selected override editing form, table of current overrides.
     - Ensure sample paragraphs remain behind a collapsible disclosure control (link + `<details>` as today).
       - Place a help icon near pronunciation inputs; focusing/hovering reveals tooltip text summarising phonetic spelling tips and links to the full guide.
     - Update CSS to style tabs consistent with modal aesthetic, including tooltip styling for the help icon.
     - Add a dedicated phonetic spelling help page (e.g., `phonetic-pronunciation.html`) sourced from the CMU reference with attribution, linked from the tooltip and main help menu.

3. **Frontend Logic (`prepare.js`)**
   - Introduce tab controller managing focus and ARIA attributes.
   - Wire People tab voice dropdowns to existing preview logic; extend to manual overrides entries.
   - Implement search suggestions for manual overrides (debounce, fetch, render list, handle selection).
   - Ensure previews use existing `data-role="speaker-preview"` pipeline; extend dataset attributes as needed.
   - Persist override edits either via hidden inputs or asynchronous saves; align with form submission semantics.

4. **APIs & Routing**
   - Add Flask routes under `routes.py` or `web/service.py` for:
     - `/pending/<id>/entities` (fetch processed entity data if not already included in template context).
     - `/pending/<id>/overrides` (CRUD operations for manual overrides).
   - Ensure permissions and CSRF tokens align with existing patterns.

5. **Data Persistence**
   - Expand pending job model (likely stored in `queue_manager_gui.py` / `queued_item.py`) to keep:
     - `entity_summary` snapshot (people/entities lists).
     - `manual_overrides` list with user edits.
     - Cached spaCy doc metadata (hash of source + serialized parse) to avoid reprocessing unchanged texts.
  - Introduce persistent `pronunciation_overrides` table (SQLite) keyed by normalised token + language, storing pronunciation, preferred voice, notes, and usage metadata for reuse across projects.
  - On finalise, merge overrides into job metadata so downstream conversion can honour pronunciations/voices and sync any changes back to the shared table.

6. **Testing Strategy**
   - Unit tests for new normalisation and POS filtering functions (ensure "The", "That" excluded; "Bob's" normalised).
   - Integration tests to confirm People tab still flows, manual overrides persist, Entities tab populates expected data.
   - Add regression tests ensuring Step 3 rename does not break existing forms (e.g., `test_prepare_form.py`).
   - Consider snapshot tests for API JSON structures.
  - Add automated checks that pronunciation overrides apply to preview playback and conversion payloads for People and Entities entries alike.

7. **Documentation & Ops**
   - Update README / docs with new Step 3 name and manual override instructions.
   - Provide guidance for installing spaCy model (e.g., `python -m spacy download en_core_web_sm`).
  - Document spaCy/model licensing obligations (MIT for core, CC BY-SA for small model) and add attribution in app credits/help page.
  - Publish phonetic spelling help page content and link it from the tooltip/icon in Step 3 and support docs.

## Open Questions / Follow-Ups
- Should Entities tab allow voice assignments that influence TTS, or is it informational only? Yes, it should include voice assignments that influence TTS.
- Manual override search scope: entire text vs detected proper nouns? Current plan searches raw text and entity index.
- Performance: confirm caching strategy (e.g., store spaCy Doc pickles vs. rebuilding from serialized spans) to balance speed and storage.

## Next Steps
1. Validate spaCy dependency choice and licensing obligations (MIT core, CC BY-SA model) with stakeholders.
2. Finalise data contracts for entities, overrides, and the persistent pronunciation history schema.
3. Implement backend entity extraction, cached spaCy parsing, override hydration, and the TTS substitution pipeline.
4. Refactor frontend Step 3 UI with tabs, help icon/tooltip, and updated voice controls.
5. Build manual override search/edit UX wired to the shared overrides store and preview flow.
6. Update documentation (including phonetic guide) and expand automated tests.
