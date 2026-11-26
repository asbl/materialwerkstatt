from __future__ import annotations

import io
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui import app as material_app  # noqa: E402
from material_ui.plugins.context import ensure_plugin_parent  # noqa: E402

ensure_plugin_parent()

from material_ui_plugins.importe import task_image_import  # noqa: E402
from material_ui.config import AppConfig  # noqa: E402


@pytest.fixture(autouse=True)
def no_course_runtime_prewarm(monkeypatch):
    # Chat/import tests must not download and compile unrelated H5P libraries.
    from material_ui.plugins.kurse.preview import PreviewService
    monkeypatch.setattr(PreviewService, "prewarm", lambda self: None)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(material_app, "ROOT", tmp_path)
    app = material_app.create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        try:
            yield app.test_client()
        finally:
            app.extensions["material_runtime"].close()


def make_png(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        out = struct.pack(">I", len(data)) + tag + data
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return out + struct.pack(">I", crc)

    width, height = 10, 10
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def write_qmd(path: Path, text: str = "---\ntitle: Test\n---\n\n<!-- material-ui -->\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def upload(client, payload: bytes, document_path: str, *, filename: str = "aufgabe.png", content_type: str = "image/png"):
    return client.post(
        "/api/document/import/task-image",
        data={"file": (io.BytesIO(payload), filename, content_type), "documentPath": document_path},
        content_type="multipart/form-data",
    )


def test_upload_stages_image_and_suggests_wissen_ziel_from_open_document(client, tmp_path):
    doc_path = "unterricht/mathematik/klasse-06/bruchrechnung/arbeitsblaetter/ab/ab.qmd"
    write_qmd(tmp_path / doc_path)
    response = upload(client, make_png(), doc_path)
    assert response.status_code == 200
    data = response.get_json()
    assert data["wissenZiel"] == "aufgaben/mathematik/klasse-06/bruchrechnung"
    assert "show_task_image" in data["prompt"]
    assert data["token"] in data["prompt"]


def test_upload_rejects_non_image_content_type(client, tmp_path):
    doc_path = "unterricht/mathematik/klasse-06/thema/blatt.qmd"
    write_qmd(tmp_path / doc_path)
    response = upload(client, b"kein bild", doc_path, content_type="text/plain")
    assert response.status_code == 400


def test_upload_rejects_oversized_image(client, tmp_path, monkeypatch):
    doc_path = "unterricht/mathematik/klasse-06/thema/blatt.qmd"
    write_qmd(tmp_path / doc_path)
    monkeypatch.setattr(task_image_import, "MAX_TASK_IMAGE_BYTES", 10)
    response = upload(client, make_png(), doc_path)
    assert response.status_code == 400


def test_cancel_discards_staging(client, tmp_path):
    doc_path = "unterricht/mathematik/klasse-06/thema/blatt.qmd"
    write_qmd(tmp_path / doc_path)
    token = upload(client, make_png(), doc_path).get_json()["token"]
    assert client.delete(f"/api/document/import/task-image/{token}").status_code == 200
    assert not (tmp_path / ".material-ui" / "task-images" / token).exists()


def test_render_endpoint_returns_png(client, tmp_path):
    doc_path = "unterricht/mathematik/klasse-06/thema/blatt.qmd"
    write_qmd(tmp_path / doc_path)
    token = upload(client, make_png(), doc_path).get_json()["token"]
    response = client.post(
        f"/api/document/import/task-image/{token}/render",
        json={"code": "## Aufgabe 1\n\nRechne $1+1$."},
    )
    assert response.status_code == 200
    assert response.content_type == "image/png"
    assert response.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_commit_erschliesst_image_and_returns_markdown(client, tmp_path):
    doc_path = "unterricht/mathematik/klasse-06/thema/blatt.qmd"
    write_qmd(tmp_path / doc_path)
    token = upload(client, make_png(), doc_path).get_json()["token"]
    response = client.post(
        f"/api/document/import/task-image/{token}",
        json={"code": "## Aufgabe 1\n\nText der Aufgabe.", "wissenZiel": "aufgaben/mathematik/klasse-06/thema"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["wissenPath"].startswith("wissen/aufgaben/mathematik/klasse-06/thema/")
    assert "## Aufgabe 1" in data["markdown"]
    assert data["markdown"].strip().startswith(":::")
    assert (tmp_path / data["wissenPath"]).is_file()
    assert not (tmp_path / ".material-ui" / "task-images" / token).exists()


def test_commit_rejects_empty_code(client, tmp_path):
    doc_path = "unterricht/mathematik/klasse-06/thema/blatt.qmd"
    write_qmd(tmp_path / doc_path)
    token = upload(client, make_png(), doc_path).get_json()["token"]
    response = client.post(
        f"/api/document/import/task-image/{token}",
        json={"code": "   ", "wissenZiel": "aufgaben/mathematik/klasse-06/thema"},
    )
    assert response.status_code == 400


def test_commit_detects_duplicate_image(client, tmp_path):
    doc_path = "unterricht/mathematik/klasse-06/thema/blatt.qmd"
    write_qmd(tmp_path / doc_path)
    payload = make_png()
    token_a = upload(client, payload, doc_path).get_json()["token"]
    first = client.post(
        f"/api/document/import/task-image/{token_a}",
        json={"code": "Aufgabe A", "wissenZiel": "aufgaben/mathematik/klasse-06/thema"},
    ).get_json()
    token_b = upload(client, payload, doc_path).get_json()["token"]
    second = client.post(
        f"/api/document/import/task-image/{token_b}",
        json={"code": "Aufgabe B", "wissenZiel": "aufgaben/mathematik/klasse-06/anderes-thema"},
    ).get_json()
    assert second["wissenPath"] == first["wissenPath"]
    assert len(list((tmp_path / "wissen").rglob("*.png"))) == 1


def test_task_image_image_route_serves_staged_image_and_rejects_invalid(client, tmp_path):
    # Der MCP-Server des chat-Plugins liest das Aufgabenbild ueber diese HTTP-Route.
    doc_path = "unterricht/mathematik/klasse-06/thema/blatt.qmd"
    write_qmd(tmp_path / doc_path)
    token = upload(client, make_png(), doc_path).get_json()["token"]
    response = client.get(f"/api/document/import/task-image/{token}/image")
    assert response.status_code == 200
    assert response.data == make_png()
    assert response.mimetype == "image/png"
    assert client.get("/api/document/import/task-image/not-a-valid-token/image").status_code == 400
