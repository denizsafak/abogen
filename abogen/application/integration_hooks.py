"""Post-conversion integration hooks.

Called by ConversionService after finalization.
Each integration is a method on PostConversionHooks — isolated, testable,
and easy to extend with new hooks (Plex, Navidrome, etc.).

The service NEVER imports from PyQt or WebUI.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping, Optional

from abogen.application.conversion_ports import ConversionEvents
from abogen.application.conversion_request import ConversionRequest
from abogen.application.conversion_result import ConversionResult
from abogen.domain.metadata_helpers import (
    build_audiobookshelf_metadata as _build_abs_metadata,
    load_audiobookshelf_chapters as _load_abs_chapters,
)
from abogen.domain.settings_core import (
    build_audiobookshelf_config,
    coerce_bool,
    load_audiobookshelf_config,
    stored_integration_config,
)
from abogen.integrations.audiobookshelf import (
    AudiobookshelfClient,
    AudiobookshelfUploadError,
)

logger = logging.getLogger(__name__)


class PostConversionHooks:
    """Runs post-conversion integrations (Audiobookshelf, etc.).

    Usage::

        hooks = PostConversionHooks()
        hooks.run(request, result, events)
    """

    def run(
        self,
        request: ConversionRequest,
        result: ConversionResult,
        events: ConversionEvents,
    ) -> None:
        """Run all registered post-conversion hooks."""
        self._maybe_send_to_audiobookshelf(request, result, events)

    # ------------------------------------------------------------------
    # Audiobookshelf
    # ------------------------------------------------------------------

    def _maybe_send_to_audiobookshelf(
        self,
        request: ConversionRequest,
        result: ConversionResult,
        events: ConversionEvents,
    ) -> None:
        """Upload finished audiobook to Audiobookshelf if enabled."""
        abs_settings = stored_integration_config("audiobookshelf")
        if not abs_settings:
            return

        enabled = coerce_bool(abs_settings.get("enabled"), False)
        auto_send = coerce_bool(abs_settings.get("auto_send"), False)
        if not (enabled and auto_send):
            return

        config = build_audiobookshelf_config(abs_settings)
        if config is None:
            events.log(
                "Audiobookshelf upload skipped: configure base URL, API token, "
                "library ID, and folder ID first.",
                level="warning",
            )
            return

        audio_path = result.audio_path
        if not audio_path or not audio_path.exists():
            events.log(
                "Audiobookshelf upload skipped: audio output not found.",
                level="warning",
            )
            return

        # Build metadata
        filename = request.original_filename or "Audiobook"
        lang = request.language.value if hasattr(request.language, "value") else str(request.language)
        metadata = _build_abs_metadata(
            result.metadata or {},
            language=lang,
            filename=Path(filename).stem,
        )

        # Load chapters from metadata artifact
        chapters = None
        if config.send_chapters:
            metadata_artifact = result.artifacts.get("metadata")
            if metadata_artifact:
                metadata_path = (
                    metadata_artifact
                    if isinstance(metadata_artifact, Path)
                    else Path(str(metadata_artifact))
                )
                chapters = _load_abs_chapters(metadata_path)

        # Resolve cover
        cover_path = None
        if config.send_cover and request.cover and request.cover.path:
            candidate = request.cover.path
            if isinstance(candidate, Path) and candidate.exists():
                cover_path = candidate

        # Resolve subtitles
        subtitles = None
        if config.send_subtitles and result.subtitle_paths:
            subtitles = [
                p for p in result.subtitle_paths
                if isinstance(p, Path) and p.exists()
            ]

        # Upload
        client = AudiobookshelfClient(config)
        display_title = metadata.get("title") or audio_path.stem

        try:
            existing_items = client.find_existing_items(
                display_title, folder_id=config.folder_id,
            )
        except AudiobookshelfUploadError as exc:
            events.log(f"Audiobookshelf lookup failed: {exc}", level="error")
            return

        if existing_items:
            events.log(
                f"Removing existing Audiobookshelf item(s) for '{display_title}'.",
                level="info",
            )
            try:
                client.delete_items(existing_items)
            except Exception as exc:
                events.log(
                    f"Failed to remove existing item(s): {exc}", level="warning",
                )

        try:
            client.upload_audiobook(
                audio_path,
                metadata=metadata,
                cover_path=cover_path,
                chapters=chapters,
                subtitles=subtitles,
            )
            events.log("Audiobookshelf upload queued.", level="info")
        except AudiobookshelfUploadError as exc:
            events.log(f"Audiobookshelf upload failed: {exc}", level="error")
        except Exception as exc:
            events.log(f"Audiobookshelf integration error: {exc}", level="error")
