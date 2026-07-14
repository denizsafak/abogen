from abogen.webui.app import create_app


def _large_chapter_form() -> dict[str, str]:
    data = {"step": "chapters"}
    for index in range(370):
        prefix = f"chapter-{index}"
        data[f"{prefix}-enabled"] = "on"
        data[f"{prefix}-title"] = f"Chapter {index} " + ("x" * 1400)
        data[f"{prefix}-voice"] = "af_heart"
        data[f"{prefix}-formula"] = "default"
    return data


def test_large_chapter_form_reaches_wizard_route(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "OUTPUT_FOLDER": str(tmp_path / "output"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
    )

    with app.test_client() as client:
        response = client.post(
            "/wizard/update?format=json",
            data=_large_chapter_form(),
        )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Missing job ID"


def test_large_multipart_chapter_form_reaches_wizard_route(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "OUTPUT_FOLDER": str(tmp_path / "output"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
    )

    with app.test_client() as client:
        response = client.post(
            "/wizard/update?format=json",
            data=_large_chapter_form(),
            content_type="multipart/form-data",
        )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Missing job ID"
