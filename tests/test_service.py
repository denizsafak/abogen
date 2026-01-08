from __future__ import annotations

import io
import time
from abogen.webui.service import (
    Job,
    JobStatus,
    build_service,
    _JOB_LOGGER,
    build_audiobookshelf_metadata,
)


def test_service_processes_job(tmp_path):
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    uploads.mkdir()
    outputs.mkdir()

    source = uploads / "sample.txt"
    payload = "hello world"
    source.write_text(payload, encoding="utf-8")

    runner_invocations: list[str] = []

    def runner(job):
        runner_invocations.append(job.id)
        job.add_log("processing")
        job.progress = 1.0
        job.processed_characters = job.total_characters or len(payload)
        job.result.audio_path = outputs / f"{job.id}.wav"

    service = build_service(
        runner=runner,
        output_root=outputs,
        uploads_root=uploads,
    )

    job = service.enqueue(
        original_filename="sample.txt",
        stored_path=source,
        language="a",
        voice="af_alloy",
        speed=1.0,
        use_gpu=False,
        subtitle_mode="Sentence",
        output_format="wav",
        save_mode="Save next to input file",
        output_folder=outputs,
        replace_single_newlines=False,
        subtitle_format="srt",
        total_characters=len(payload),
    )

    deadline = time.time() + 5
    while time.time() < deadline and job.status not in {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }:
        time.sleep(0.05)

    service.shutdown()

    assert runner_invocations, "conversion runner was never called"
    assert job.status is JobStatus.COMPLETED
    assert job.progress == 1.0
    assert job.result.audio_path == outputs / f"{job.id}.wav"
    assert job.chunk_level == "paragraph"
    assert job.speaker_mode == "single"
    assert job.chunks == []
    assert not job.generate_epub3


def test_job_add_log_emits_to_stream(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("payload", encoding="utf-8")

    job = Job(
        id="job-test",
        original_filename="sample.txt",
        stored_path=sample,
        language="a",
        voice="af_alloy",
        speed=1.0,
        use_gpu=False,
        subtitle_mode="Sentence",
        output_format="wav",
        save_mode="Save next to input file",
        output_folder=tmp_path,
        replace_single_newlines=False,
        subtitle_format="srt",
        created_at=time.time(),
    )

    captured_buffers = []
    for handler in list(_JOB_LOGGER.handlers):
        if not hasattr(handler, "setStream"):
            continue
        buffer = io.StringIO()
        original_stream = getattr(handler, "stream", None)
        handler.setStream(buffer)  # type: ignore[attr-defined]
        captured_buffers.append((handler, original_stream, buffer))

    assert captured_buffers, "Expected job logger to have stream handlers"

    try:
        job.add_log("Test log line", level="error")
        outputs = [buffer.getvalue() for _, _, buffer in captured_buffers]
    finally:
        for handler, original_stream, _ in captured_buffers:
            if hasattr(handler, "setStream"):
                handler.setStream(original_stream)  # type: ignore[attr-defined]

    assert any("Test log line" in output for output in outputs)
    assert job.logs[-1].message == "Test log line"


def test_job_add_log_handles_exception(tmp_path, capsys):
    sample = tmp_path / "sample.txt"
    sample.write_text("payload", encoding="utf-8")

    job = Job(
        id="job-fail-test",
        original_filename="sample.txt",
        stored_path=sample,
        language="a",
        voice="af_alloy",
        speed=1.0,
        use_gpu=False,
        subtitle_mode="Sentence",
        output_format="wav",
        save_mode="Save next to input file",
        output_folder=tmp_path,
        replace_single_newlines=False,
        subtitle_format="srt",
        created_at=time.time(),
    )

    # Mock the logger to raise an exception
    original_log = _JOB_LOGGER.log

    def side_effect(*args, **kwargs):
        raise RuntimeError("Logger exploded")

    _JOB_LOGGER.log = side_effect

    try:
        job.add_log("This should trigger fallback", level="info")
    finally:
        _JOB_LOGGER.log = original_log

    captured = capsys.readouterr()
    assert "Logging failed for job job-fail-test" in captured.err
    assert "Logger exploded" in captured.err


def test_retry_removes_failed_job(tmp_path):
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    uploads.mkdir()
    outputs.mkdir()

    source = uploads / "sample.txt"
    source.write_text("hello", encoding="utf-8")

    def failing_runner(job):
        job.add_log("runner failing", level="error")
        raise RuntimeError("boom")

    service = build_service(
        runner=failing_runner,
        output_root=outputs,
        uploads_root=uploads,
    )

    try:
        job = service.enqueue(
            original_filename="sample.txt",
            stored_path=source,
            language="a",
            voice="af_alloy",
            speed=1.0,
            use_gpu=False,
            subtitle_mode="Sentence",
            output_format="wav",
            save_mode="Save next to input file",
            output_folder=outputs,
            replace_single_newlines=False,
            subtitle_format="srt",
            total_characters=len("hello"),
        )

        deadline = time.time() + 5
        while time.time() < deadline and job.status is not JobStatus.FAILED:
            time.sleep(0.05)

        assert job.status is JobStatus.FAILED

        new_job = service.retry(job.id)
        assert new_job is not None
        assert new_job.id != job.id

        job_ids = {entry.id for entry in service.list_jobs()}
        assert job.id not in job_ids
        assert new_job.id in job_ids
    finally:
        service.shutdown()


def test_audiobookshelf_metadata_uses_book_number(tmp_path):
    source = tmp_path / "book.txt"
    source.write_text("content", encoding="utf-8")

    job = Job(
        id="job-abs",
        original_filename="book.txt",
        stored_path=source,
        language="en",
        voice="af_alloy",
        speed=1.0,
        use_gpu=False,
        subtitle_mode="Sentence",
        output_format="mp3",
        save_mode="Save next to input file",
        output_folder=tmp_path,
        replace_single_newlines=False,
        subtitle_format="srt",
        created_at=time.time(),
        metadata_tags={
            "series": "Example Saga",
            "book_number": "7",
        },
    )

    metadata = build_audiobookshelf_metadata(job)

    assert metadata["seriesName"] == "Example Saga"
    assert metadata["seriesSequence"] == "7"


def test_audiobookshelf_metadata_normalizes_sequence_value(tmp_path):
    source = tmp_path / "book.txt"
    source.write_text("content", encoding="utf-8")

    job = Job(
        id="job-abs-normalize",
        original_filename="book.txt",
        stored_path=source,
        language="en",
        voice="af_alloy",
        speed=1.0,
        use_gpu=False,
        subtitle_mode="Sentence",
        output_format="mp3",
        save_mode="Save next to input file",
        output_folder=tmp_path,
        replace_single_newlines=False,
        subtitle_format="srt",
        created_at=time.time(),
        metadata_tags={
            "series": "Example Saga",
            "series_index": "Book 7 of the Series",
        },
    )

    metadata = build_audiobookshelf_metadata(job)

    assert metadata["seriesName"] == "Example Saga"
    assert metadata["seriesSequence"] == "7"


def test_audiobookshelf_metadata_allows_decimal_sequence(tmp_path):
    source = tmp_path / "book.txt"
    source.write_text("content", encoding="utf-8")

    job = Job(
        id="job-abs-decimal",
        original_filename="book.txt",
        stored_path=source,
        language="en",
        voice="af_alloy",
        speed=1.0,
        use_gpu=False,
        subtitle_mode="Sentence",
        output_format="mp3",
        save_mode="Save next to input file",
        output_folder=tmp_path,
        replace_single_newlines=False,
        subtitle_format="srt",
        created_at=time.time(),
        metadata_tags={
            "series": "Example Saga",
            "series_number": "Book 4.5",
        },
    )

    metadata = build_audiobookshelf_metadata(job)

    assert metadata["seriesSequence"] == "4.5"
