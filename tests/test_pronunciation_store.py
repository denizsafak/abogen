import json
import os
import shutil

import pytest

from abogen import pronunciation_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "overrides.json"
    monkeypatch.setattr(pronunciation_store, "_store_path", lambda: path)
    return path


def test_save_replaces_existing_overrides_without_copying(store, monkeypatch):
    store.write_text('{"old": true}', encoding="utf-8")

    def windows_rename(source, target):
        raise FileExistsError("Windows rename cannot overwrite an existing file")

    def failed_copy(source, target, **kwargs):
        # A copy fallback can truncate the live file before a failed write.
        with open(target, "w", encoding="utf-8") as output:
            output.write('{"partial":')
        raise OSError("write failed")

    monkeypatch.setattr(os, "rename", windows_rename)
    monkeypatch.setattr(shutil, "copyfile", failed_copy)

    pronunciation_store._save_db({"token": "你好"})

    assert json.loads(store.read_text(encoding="utf-8")) == {"token": "你好"}
    assert list(store.parent.iterdir()) == [store]


def test_override_round_trip_uses_the_replaced_store(store):
    pronunciation_store.save_override(language="en", token="hello", pronunciation="hullo")
    pronunciation_store.save_override(language="en", token="hello", pronunciation="hi")
    entry = pronunciation_store.load_overrides("en", ["hello"])["hello"]
    assert entry["pronunciation"] == "hi"
    pronunciation_store.delete_override(language="en", token="hello")
    assert pronunciation_store.load_overrides("en", ["hello"]) == {}
    assert list(store.parent.iterdir()) == [store]


def test_failed_serialization_preserves_previous_overrides_and_cleans_up(store):
    original = '{"old": true}'
    store.write_text(original, encoding="utf-8")

    with pytest.raises(TypeError):
        pronunciation_store._save_db({"invalid": object()})

    assert store.read_text(encoding="utf-8") == original
    assert list(store.parent.iterdir()) == [store]


def test_failed_replacement_preserves_previous_overrides_and_cleans_up(store, monkeypatch):
    original = '{"old": true}'
    store.write_text(original, encoding="utf-8")

    def locked(*args, **kwargs):
        raise PermissionError("destination is locked")

    monkeypatch.setattr(os, "rename", locked)
    monkeypatch.setattr(os, "replace", locked)
    monkeypatch.setattr(shutil, "copyfile", locked)

    with pytest.raises(PermissionError):
        pronunciation_store._save_db({"new": True})

    assert store.read_text(encoding="utf-8") == original
    assert list(store.parent.iterdir()) == [store]
