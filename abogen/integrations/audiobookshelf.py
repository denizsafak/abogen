from __future__ import annotations

import json
import logging
import math
import mimetypes
import re
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)


class AudiobookshelfUploadError(RuntimeError):
    """Raised when an upload to Audiobookshelf fails."""


@dataclass(frozen=True)
class AudiobookshelfConfig:
    base_url: str
    api_token: str
    library_id: Optional[str] = None
    collection_id: Optional[str] = None
    folder_id: Optional[str] = None
    verify_ssl: bool = True
    send_cover: bool = True
    send_chapters: bool = True
    send_subtitles: bool = True
    timeout: float = 3600.0

    def normalized_base_url(self) -> str:
        base = (self.base_url or "").strip()
        if not base:
            raise ValueError("Audiobookshelf base URL is required")
        normalized = base.rstrip("/")
        # The web UI historically suggested including '/api' in the base URL; trim
        # it here so we can safely append `/api/...` endpoints below.
        if normalized.lower().endswith("/api"):
            normalized = normalized[:-4]
        return normalized or base


class AudiobookshelfClient:
    """Client for the legacy Audiobookshelf multipart upload endpoint."""

    def __init__(self, config: AudiobookshelfConfig) -> None:
        if not config.api_token:
            raise ValueError("Audiobookshelf API token is required")
        # library_id is now optional for discovery
        self._config = config
        normalized = config.normalized_base_url() or ""
        self._base_url = normalized.rstrip("/") or normalized
        self._client_base_url = f"{self._base_url}/"
        self._folder_cache: Optional[Tuple[str, str, str]] = None

    def get_libraries(self) -> List[Dict[str, Any]]:
        """Fetch all libraries from the Audiobookshelf server."""
        route = self._api_path("libraries")
        try:
            with self._open_client() as client:
                response = client.get(route)
                response.raise_for_status()
                data = response.json()
                # data['libraries'] is a list of library objects
                return data.get("libraries", [])
        except httpx.HTTPError as exc:
            raise AudiobookshelfUploadError(f"Failed to fetch libraries: {exc}") from exc

    def _api_path(self, suffix: str = "") -> str:
        """Join the API prefix with the provided suffix without losing proxies."""
        clean_suffix = suffix.lstrip("/")
        return f"api/{clean_suffix}" if clean_suffix else "api"

    def upload_audiobook(
        self,
        audio_path: Path,
        *,
        metadata: Dict[str, Any],
        cover_path: Optional[Path] = None,
        chapters: Optional[Iterable[Dict[str, Any]]] = None,
        subtitles: Optional[Iterable[Path]] = None,
    ) -> Dict[str, Any]:
        if not audio_path.exists():
            raise AudiobookshelfUploadError(f"Audio path does not exist: {audio_path}")

        form_fields = self._build_upload_fields(audio_path, metadata, chapters)
        file_entries = self._build_file_entries(audio_path, cover_path, subtitles)

        route = self._api_path("upload")
        try:
            with self._open_client() as client, ExitStack() as stack:
                files_payload = self._open_file_handles(file_entries, stack)
                response = client.post(route, data=form_fields, files=files_payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = (exc.response.text or "").strip()
            if detail:
                detail = detail[:200]
                message = f"Audiobookshelf upload failed with status {status}: {detail}"
            else:
                message = f"Audiobookshelf upload failed with status {status}"
            raise AudiobookshelfUploadError(
                message
            ) from exc
        except httpx.HTTPError as exc:
            raise AudiobookshelfUploadError(f"Audiobookshelf upload failed: {exc}") from exc

        return {}

    def _open_client(self) -> httpx.Client:
        headers = {
            "Authorization": f"Bearer {self._config.api_token}",
            "Accept": "application/json",
        }
        return httpx.Client(
            base_url=self._client_base_url,
            headers=headers,
            timeout=self._config.timeout,
            verify=self._config.verify_ssl,
        )

    def _build_upload_fields(
        self,
        audio_path: Path,
        metadata: Dict[str, Any],
        chapters: Optional[Iterable[Dict[str, Any]]],
    ) -> Dict[str, str]:
        folder_id, _, _ = self._ensure_folder()
        title = self._extract_title(metadata, audio_path)
        author = self._extract_author(metadata)
        series = self._extract_series(metadata)
        series_sequence = self._extract_series_sequence(metadata)

        fields: Dict[str, str] = {
            "library": self._config.library_id,
            "folder": folder_id,
            "title": title,
        }
        if author:
            fields["author"] = author
        if series:
            fields["series"] = series
        if series_sequence:
            fields["seriesSequence"] = series_sequence
        if self._config.collection_id:
            fields["collectionId"] = self._config.collection_id

        metadata_payload: Dict[str, Any] = metadata or {}
        if chapters and self._config.send_chapters:
            metadata_payload = dict(metadata_payload)
            metadata_payload["chapters"] = list(chapters)

        if metadata_payload:
            # Ensure authors is a list of strings in the JSON payload if it exists
            if "authors" in metadata_payload:
                authors_val = metadata_payload["authors"]
                if isinstance(authors_val, str):
                    metadata_payload["authors"] = [a.strip() for a in authors_val.split(",") if a.strip()]
                elif isinstance(authors_val, list):
                    metadata_payload["authors"] = [str(a).strip() for a in authors_val if str(a).strip()]

            try:
                fields["metadata"] = json.dumps(metadata_payload, ensure_ascii=False)
            except (TypeError, ValueError):
                logger.debug("Failed to serialize Audiobookshelf metadata payload")

        return fields

    def _build_file_entries(
        self,
        audio_path: Path,
        cover_path: Optional[Path],
        subtitles: Optional[Iterable[Path]],
    ) -> List[Tuple[str, Path]]:
        entries: List[Tuple[str, Path]] = [("file0", audio_path)]
        index = 1

        if cover_path and self._config.send_cover and cover_path.exists():
            entries.append((f"file{index}", cover_path))
            index += 1

        if subtitles and self._config.send_subtitles:
            for subtitle in subtitles:
                if subtitle.exists():
                    entries.append((f"file{index}", subtitle))
                    index += 1

        return entries

    def _open_file_handles(
        self,
        entries: Sequence[Tuple[str, Path]],
        stack: ExitStack,
    ) -> List[Tuple[str, Tuple[str, Any, str]]]:
        files: List[Tuple[str, Tuple[str, Any, str]]] = []
        for field_name, path in entries:
            mime_type, _ = mimetypes.guess_type(path.name)
            mime_type = mime_type or "application/octet-stream"
            handle = stack.enter_context(path.open("rb"))
            files.append((field_name, (path.name, handle, mime_type)))
        return files

    def find_existing_items(
        self,
        title: str,
        *,
        folder_id: Optional[str] = None,
    ) -> List[Mapping[str, Any]]:
        normalized_title = self._normalize_title_value(title)
        if not normalized_title:
            return []

        folder_hint = folder_id or self._config.folder_id
        target_folders = set()
        if folder_hint:
            folder_token = str(folder_hint).strip().lower()
            if folder_token:
                target_folders.add(folder_token)

        requests = self._candidate_search_requests(title, folder_hint)
        if not requests:
            return []

        matches: List[Mapping[str, Any]] = []

        try:
            with self._open_client() as client:
                for route, params in requests:
                    try:
                        response = client.get(route, params=params)
                    except httpx.HTTPError as exc:
                        logger.debug("Audiobookshelf lookup failed for %s: %s", route, exc)
                        continue

                    if response.status_code == 404:
                        continue

                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        status = exc.response.status_code
                        if status in {401, 403}:
                            raise AudiobookshelfUploadError(
                                "Audiobookshelf authentication failed while checking for existing items."
                            ) from exc
                        logger.debug("Audiobookshelf lookup error %s for %s", status, route)
                        continue

                    try:
                        payload = response.json()
                    except ValueError:
                        continue

                    candidates = self._extract_candidate_items(payload)
                    for item in candidates:
                        item_title = self._normalize_item_title(item)
                        if not item_title or item_title != normalized_title:
                            continue
                        if target_folders:
                            item_folder = self._normalize_folder_id(item)
                            if item_folder and item_folder not in target_folders:
                                continue
                        matches.append(item)
                    if matches:
                        break
        except AudiobookshelfUploadError:
            raise
        except Exception:
            logger.debug(
                "Unexpected error while checking Audiobookshelf for existing items",
                exc_info=True,
            )

        return matches

    def delete_items(self, items: Iterable[Mapping[str, Any] | str]) -> None:
        to_delete: List[str] = []
        for entry in items:
            if isinstance(entry, Mapping):
                item_id = self._extract_item_id(entry)
            else:
                item_id = str(entry).strip()
            if item_id:
                to_delete.append(item_id)

        if not to_delete:
            return

        with self._open_client() as client:
            for item_id in to_delete:
                self._delete_single_item(client, item_id)

    def _candidate_search_requests(
        self,
        title: str,
        folder_id: Optional[str],
    ) -> List[Tuple[str, Dict[str, Any]]]:
        query = (title or "").strip()
        if not query:
            return []

        library_id = self._config.library_id
        folder_token = (folder_id or self._config.folder_id or "").strip()

        requests: List[Tuple[str, Dict[str, Any]]] = []
        seen_routes: set[str] = set()

        def _append(route: str, params: Dict[str, Any]) -> None:
            if route in seen_routes:
                return
            seen_routes.add(route)
            requests.append((route, params))

        if folder_token:
            _append(
                self._api_path(f"folders/{folder_token}/items"),
                {"library": library_id, "search": query},
            )

        _append(self._api_path(f"libraries/{library_id}/items"), {"search": query})
        _append(self._api_path("items"), {"library": library_id, "search": query})
        _append(
            self._api_path("search"),
            {"query": query, "library": library_id, "media": "audiobook"},
        )

        return requests

    def _delete_single_item(self, client: httpx.Client, item_id: str) -> None:
        routes = [
            self._api_path(f"items/{item_id}"),
            self._api_path(f"libraries/{self._config.library_id}/items/{item_id}"),
        ]

        for route in routes:
            try:
                response = client.delete(route)
            except httpx.HTTPError as exc:
                logger.debug("Audiobookshelf delete failed for %s: %s", route, exc)
                continue

            if response.status_code in (200, 202, 204):
                return
            if response.status_code == 404:
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise AudiobookshelfUploadError(
                    f"Failed to delete Audiobookshelf item '{item_id}': {exc}"
                ) from exc

        logger.debug("Audiobookshelf item %s could not be confirmed deleted", item_id)

    def resolve_folder(self) -> Tuple[str, str, str]:
        """Return the resolved folder (id, name, library name)."""
        return self._ensure_folder()

    def list_folders(self) -> List[Dict[str, str]]:
        """Return all folders for the configured library."""
        library_name, folders = self._load_library_metadata()
        results: List[Dict[str, str]] = []
        for folder in folders:
            folder_id = str(folder.get("id") or "").strip()
            if not folder_id:
                continue
            name = self._folder_display_name(folder)
            path = self._select_folder_path(folder)
            results.append(
                {
                    "id": folder_id,
                    "name": name,
                    "path": path,
                    "library": library_name,
                }
            )
        results.sort(key=lambda entry: (entry.get("path") or entry.get("name") or entry.get("id") or "").lower())
        return results

    def _ensure_folder(self) -> Tuple[str, str, str]:
        if self._folder_cache:
            return self._folder_cache

        identifier = (self._config.folder_id or "").strip()
        if not identifier:
            raise AudiobookshelfUploadError(
                "Audiobookshelf folder is required; enter the folder name or ID in Settings."
            )

        identifier_norm = self._normalize_identifier(identifier)
        library_name, folders = self._load_library_metadata()

        # direct ID match
        for folder in folders:
            folder_id = str(folder.get("id") or "").strip()
            if folder_id and folder_id == identifier:
                folder_name = self._folder_display_name(folder) or folder_id
                self._folder_cache = (folder_id, folder_name, library_name)
                return self._folder_cache

        has_path_component = "/" in identifier_norm

        for folder in folders:
            folder_id = str(folder.get("id") or "").strip()
            if not folder_id:
                continue
            folder_name = self._folder_display_name(folder)
            name_norm = self._normalize_identifier(folder_name)
            if name_norm and name_norm == identifier_norm:
                self._folder_cache = (folder_id, folder_name or folder_id, library_name)
                return self._folder_cache

            for candidate in self._folder_path_candidates(folder):
                candidate_norm = self._normalize_identifier(candidate)
                if not candidate_norm:
                    continue
                if candidate_norm == identifier_norm:
                    self._folder_cache = (folder_id, folder_name or folder_id, library_name)
                    return self._folder_cache
                if has_path_component and candidate_norm.endswith(identifier_norm):
                    self._folder_cache = (folder_id, folder_name or folder_id, library_name)
                    return self._folder_cache
                if not has_path_component:
                    tail = candidate_norm.split("/")[-1]
                    if tail and tail == identifier_norm:
                        self._folder_cache = (folder_id, folder_name or folder_id, library_name)
                        return self._folder_cache

        raise AudiobookshelfUploadError(
            f"Folder '{identifier}' was not found in library '{library_name}'. "
            "Enter the folder name exactly as it appears in Audiobookshelf, a trailing path segment, or paste the folder ID."
        )

    def _load_library_metadata(self) -> Tuple[str, List[Mapping[str, Any]]]:
        try:
            with self._open_client() as client:
                response = client.get(self._api_path(f"libraries/{self._config.library_id}"))
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                message = f"Audiobookshelf library '{self._config.library_id}' not found."
            else:
                detail = (exc.response.text or "").strip()
                if detail:
                    detail = detail[:200]
                    message = (
                        f"Failed to load Audiobookshelf library '{self._config.library_id}' "
                        f"(status {status}): {detail}"
                    )
                else:
                    message = (
                        f"Failed to load Audiobookshelf library '{self._config.library_id}' "
                        f"(status {status})."
                    )
            raise AudiobookshelfUploadError(message) from exc
        except httpx.HTTPError as exc:
            raise AudiobookshelfUploadError(
                f"Failed to reach Audiobookshelf library '{self._config.library_id}': {exc}"
            ) from exc

        if not isinstance(payload, Mapping):
            return self._config.library_id, []

        library_name = str(payload.get("name") or payload.get("label") or self._config.library_id)
        raw_folders = payload.get("libraryFolders") or payload.get("folders") or []
        folders = [entry for entry in raw_folders if isinstance(entry, Mapping)]
        return library_name, folders

    @staticmethod
    def _folder_path_candidates(folder: Mapping[str, Any]) -> List[str]:
        candidates: List[str] = []
        for key in ("fullPath", "fullpath", "path", "folderPath", "virtualPath"):
            value = folder.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value)
        return candidates

    @staticmethod
    def _folder_display_name(folder: Mapping[str, Any]) -> str:
        name = str(folder.get("name") or folder.get("label") or "").strip()
        if name:
            return name
        path = AudiobookshelfClient._select_folder_path(folder)
        if path:
            tail = path.strip("/ ")
            tail = tail.split("/")[-1] if tail else ""
            if tail:
                return tail
        return str(folder.get("id") or "").strip()

    @staticmethod
    def _select_folder_path(folder: Mapping[str, Any]) -> str:
        for candidate in AudiobookshelfClient._folder_path_candidates(folder):
            normalized = candidate.replace("\\", "/").strip()
            if normalized:
                return normalized
        return ""

    @staticmethod
    def _normalize_identifier(value: str) -> str:
        token = (value or "").strip()
        token = token.replace("\\", "/")
        if len(token) > 1 and token[1] == ":":
            token = token[2:]
        token = token.strip("/ ")
        return token.lower()

    @staticmethod
    def _normalize_title_value(value: Optional[str]) -> str:
        if not isinstance(value, str):
            return ""
        normalized = re.sub(r"\s+", " ", value).strip()
        return normalized.casefold() if normalized else ""

    @staticmethod
    def _normalize_item_title(item: Mapping[str, Any]) -> str:
        if not isinstance(item, Mapping):
            return ""
        for key in ("title", "name", "label"):
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return AudiobookshelfClient._normalize_title_value(candidate)
        library_item = item.get("libraryItem")
        if isinstance(library_item, Mapping):
            return AudiobookshelfClient._normalize_item_title(library_item)
        return ""

    @staticmethod
    def _normalize_folder_id(item: Mapping[str, Any]) -> Optional[str]:
        if not isinstance(item, Mapping):
            return None
        for key in ("folderId", "libraryFolderId", "folder_id", "folder"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
            if isinstance(value, (int, float)):
                return str(value).strip().lower()
        library_item = item.get("libraryItem")
        if isinstance(library_item, Mapping):
            return AudiobookshelfClient._normalize_folder_id(library_item)
        return None

    @staticmethod
    def _extract_item_id(item: Mapping[str, Any]) -> Optional[str]:
        if not isinstance(item, Mapping):
            return None
        for key in ("id", "libraryItemId", "itemId"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (int, float)):
                return str(value).strip()
        library_item = item.get("libraryItem")
        if isinstance(library_item, Mapping):
            return AudiobookshelfClient._extract_item_id(library_item)
        return None

    @staticmethod
    def _extract_candidate_items(payload: Any) -> List[Mapping[str, Any]]:
        items: List[Mapping[str, Any]] = []
        seen_ids: set[str] = set()
        visited: set[int] = set()

        def _visit(obj: Any) -> None:
            if isinstance(obj, Mapping):
                obj_id = id(obj)
                if obj_id in visited:
                    return
                visited.add(obj_id)

                title = AudiobookshelfClient._normalize_item_title(obj)
                item_id = AudiobookshelfClient._extract_item_id(obj)
                if title and item_id:
                    key = item_id.strip().lower()
                    if key not in seen_ids:
                        seen_ids.add(key)
                        items.append(obj)

                for value in obj.values():
                    _visit(value)

            elif isinstance(obj, list):
                for entry in obj:
                    _visit(entry)

        _visit(payload)
        return items

    @staticmethod
    def _extract_title(metadata: Mapping[str, Any], audio_path: Path) -> str:
        title = metadata.get("title") if isinstance(metadata, Mapping) else None
        candidate = str(title).strip() if isinstance(title, str) else ""
        if candidate:
            return candidate
        return audio_path.stem or audio_path.name

    @staticmethod
    def _extract_author(metadata: Mapping[str, Any]) -> str:
        authors = metadata.get("authors") if isinstance(metadata, Mapping) else None
        if isinstance(authors, str):
            candidate = authors.strip()
            return candidate
        if isinstance(authors, Iterable) and not isinstance(authors, (str, Mapping)):
            names = [str(entry).strip() for entry in authors if isinstance(entry, str) and entry.strip()]
            if names:
                # ABS expects a comma-separated string for multiple authors.
                return ", ".join(names)
        return ""

    @staticmethod
    def _extract_series(metadata: Mapping[str, Any]) -> str:
        series_name = metadata.get("seriesName") if isinstance(metadata, Mapping) else None
        if isinstance(series_name, str) and series_name.strip():
            return series_name.strip()
        return ""

    @staticmethod
    def _extract_series_sequence(metadata: Mapping[str, Any]) -> str:
        if not isinstance(metadata, Mapping):
            return ""

        preferred_keys = (
            "seriesSequence",
            "series_sequence",
            "seriesIndex",
            "series_index",
            "seriesNumber",
            "series_number",
            "bookNumber",
            "book_number",
        )

        for key in preferred_keys:
            if key not in metadata:
                continue
            normalized = AudiobookshelfClient._normalize_series_sequence(metadata.get(key))
            if normalized:
                return normalized
        return ""

    @staticmethod
    def _normalize_series_sequence(raw: Any) -> str:
        if raw is None:
            return ""

        if isinstance(raw, (int, float)):
            if isinstance(raw, float) and (math.isnan(raw) or math.isinf(raw)):
                return ""
            text = str(raw)
        else:
            text = str(raw).strip()

        if not text:
            return ""

        candidate = text.replace(",", ".")
        match = re.search(r"\d+(?:\.\d+)?", candidate)
        if not match:
            return ""

        normalized = match.group(0)
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
            if not normalized:
                normalized = "0"
            return normalized

        try:
            return str(int(normalized))
        except ValueError:
            cleaned = normalized.lstrip("0")
            return cleaned or "0"
