from __future__ import annotations

import time
from pathlib import Path

import pytest

from abogen.webui.conversion_runner import _build_output_path, _prepare_project_layout
from abogen.webui.service import Job


def _sample_job(tmp_path: Path) -> Job:
    source = tmp_path / "sample.txt"
    source.write_text("example", encoding="utf-8")
    return Job(
        id="job-1",
        original_filename="Sample Title.txt",
        stored_path=source,
        language="en",
        voice="af_alloy",
        speed=1.0,
        use_gpu=False,
        subtitle_mode="Sentence",
        output_format="mp3",
        save_mode="Use default save location",
        output_folder=tmp_path,
        replace_single_newlines=False,
        subtitle_format="srt",
        created_at=time.time(),
    )


def test_prepare_project_layout_uses_timestamped_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _sample_job(tmp_path)
    monkeypatch.setattr(
        "abogen.webui.conversion_runner._output_timestamp_token",
        lambda: "20250101-120000",
    )

    project_root, audio_dir, subtitle_dir, metadata_dir = _prepare_project_layout(
        job, tmp_path
    )

    assert project_root.name.startswith(
        "20250101-120000_Sample_Title"
    ), project_root.name
    assert audio_dir == project_root
    assert subtitle_dir == project_root
    assert metadata_dir is None

    output_path = _build_output_path(audio_dir, job.original_filename, "mp3")
    assert output_path == project_root / "Sample_Title.mp3"


def test_prepare_project_layout_creates_project_subdirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job = _sample_job(tmp_path)
    job.save_as_project = True
    monkeypatch.setattr(
        "abogen.webui.conversion_runner._output_timestamp_token",
        lambda: "20250101-120500",
    )

    project_root, audio_dir, subtitle_dir, metadata_dir = _prepare_project_layout(
        job, tmp_path
    )

    assert audio_dir == project_root / "audio"
    assert subtitle_dir == project_root / "subtitles"
    assert metadata_dir == project_root / "metadata"
    assert audio_dir.is_dir()
    assert subtitle_dir.is_dir()
    assert metadata_dir is not None and metadata_dir.is_dir()

    output_path = _build_output_path(audio_dir, job.original_filename, "wav")
    assert output_path == audio_dir / "Sample_Title.wav"
