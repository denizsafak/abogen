from __future__ import annotations

from pathlib import Path

from abogen.utils import load_config, save_config
from abogen.webui.app import create_app


def test_settings_update_preserves_abs_api_token_when_blank(tmp_path):
    # Seed config with stored integration secret.
    save_config(
        {
            "language": "en",
            "integrations": {
                "audiobookshelf": {
                    "enabled": True,
                    "base_url": "https://abs.example",
                    "api_token": "SECRET_TOKEN",
                    "library_id": "lib1",
                    "folder_id": "fold1",
                    "verify_ssl": True,
                },
                "calibre_opds": {
                    "enabled": True,
                    "base_url": "https://opds.example",
                    "username": "user",
                    "password": "SECRET_PASS",
                    "verify_ssl": True,
                },
            },
        }
    )

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "OUTPUT_FOLDER": str(tmp_path),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
    )

    with app.test_client() as client:
        # Emulate saving settings where integrations are present but secrets are blank
        # (typical of masked password/token inputs).
        resp = client.post(
            "/settings/update",
            data={
                "language": "en",
                "output_format": "mp3",
                # ABS integration fields (token blank)
                "audiobookshelf_enabled": "on",
                "audiobookshelf_base_url": "https://abs.example",
                "audiobookshelf_api_token": "",
                "audiobookshelf_library_id": "lib1",
                "audiobookshelf_folder_id": "fold1",
                "audiobookshelf_verify_ssl": "on",
                # Calibre OPDS integration fields (password blank)
                "calibre_opds_enabled": "on",
                "calibre_opds_base_url": "https://opds.example",
                "calibre_opds_username": "user",
                "calibre_opds_password": "",
                "calibre_opds_verify_ssl": "on",
            },
            follow_redirects=False,
        )
        assert resp.status_code in {302, 303}

    cfg = load_config() or {}
    integrations = cfg.get("integrations") or {}

    assert integrations["audiobookshelf"]["api_token"] == "SECRET_TOKEN"
    assert integrations["calibre_opds"]["password"] == "SECRET_PASS"


def test_settings_update_preserves_secrets_when_fields_missing(tmp_path):
    save_config(
        {
            "language": "en",
            "integrations": {
                "audiobookshelf": {"api_token": "SECRET_TOKEN"},
                "calibre_opds": {"password": "SECRET_PASS"},
            },
        }
    )

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "OUTPUT_FOLDER": str(tmp_path),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
    )

    with app.test_client() as client:
        # Post unrelated changes; omit integration fields completely.
        resp = client.post(
            "/settings/update",
            data={
                "language": "en",
                "output_format": "wav",
            },
            follow_redirects=False,
        )
        assert resp.status_code in {302, 303}

    cfg = load_config() or {}
    integrations = cfg.get("integrations") or {}
    assert integrations["audiobookshelf"]["api_token"] == "SECRET_TOKEN"
    assert integrations["calibre_opds"]["password"] == "SECRET_PASS"
