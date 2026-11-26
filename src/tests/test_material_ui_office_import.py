from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui import app as material_app  # noqa: E402
from material_ui.plugins.context import ensure_plugin_parent  # noqa: E402

ensure_plugin_parent()

from material_ui_plugins.importe import office_import  # noqa: E402
from material_ui_plugins.chat.events import done_event, text_event  # noqa: E402
from material_ui_plugins.chat.service import ChatService  # noqa: E402
from material_ui.config import AppConfig  # noqa: E402
from material_ui.runtime import RuntimeState  # noqa: E402


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


def write_pdf(path: Path, text: str = "Testinhalt zum Ueberpruefen der Textextraktion.") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as document:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
        document.save(path)
    return path


def make_docx_bytes(markdown: str) -> bytes:
    completed = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "docx", "-o", "-"],
        input=markdown.encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return completed.stdout


def make_docx_with_image_bytes(tmp_path: Path, markdown: str) -> bytes:
    work = tmp_path / "docx-src"
    work.mkdir()
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    (work / "bild.png").write_bytes(png)
    source = work / "in.md"
    source.write_text(markdown, encoding="utf-8")
    docx = work / "in.docx"
    # cwd=work ist notwendig: Pandoc loest die relative Bildreferenz "bild.png" gegen das
    # Prozess-cwd auf, nicht gegen den Ordner der Quelldatei; ohne cwd faende es das Bild
    # beim Testlauf (cwd = Projektwurzel) nicht und wuerde es stillschweigend durch einen
    # Platzhalter ersetzen.
    subprocess.run(["pandoc", str(source), "-o", str(docx)], cwd=work, check=True, capture_output=True)
    return docx.read_bytes()


def upload(client, root: Path, payload: bytes, filename: str):
    return client.post(
        "/api/document/import/office",
        data={"file": (io.BytesIO(payload), filename)},
        content_type="multipart/form-data",
    )


def test_upload_pdf_extracts_text_and_suggests_subject_and_grade(client, tmp_path):
    (tmp_path / "unterricht" / "mathematik").mkdir(parents=True)
    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Klasse 6, Mathematik: Bruchrechnung. Aufgabe 1.")
    response = upload(client, tmp_path, pdf_path.read_bytes(), "Bruchrechnung Klasse 6.pdf")
    assert response.status_code == 200
    data = response.get_json()
    assert data["kind"] == "pdf"
    assert data["pages"] == 1
    assert data["duplicateOf"] is None
    assert data["suggested"]["subject"] == "mathematik"
    assert data["suggested"]["grade"] == "6"
    assert "Bruchrechnung" in data["preview"]
    assert data["projectTarget"].startswith("unterricht/mathematik/klasse-06/")
    assert data["wissenZiel"].startswith("arbeitsblatt/mathematik/klasse-06/")


def test_upload_rejects_pdf_without_text_layer(client, tmp_path):
    pdf_path = write_pdf(tmp_path / "leer.pdf", text="")
    response = upload(client, tmp_path, pdf_path.read_bytes(), "leer.pdf")
    assert response.status_code == 400
    assert "wissen-ocr" in response.get_json()["error"]["message"]


def test_upload_rejects_unsupported_extension(client, tmp_path):
    response = upload(client, tmp_path, b"Hallo", "notiz.txt")
    assert response.status_code == 400


def test_upload_docx_extracts_markdown_and_title(client, tmp_path):
    payload = make_docx_bytes("# Dreisatz Uebung\n\nAufgabe 1: Loese die Gleichung.\n")
    response = upload(client, tmp_path, payload, "dreisatz.docx")
    assert response.status_code == 200
    data = response.get_json()
    assert data["kind"] == "docx"
    assert data["suggested"]["title"] == "Dreisatz Uebung"
    assert "Loese die Gleichung" in data["preview"]


def confirm(client, token, *, project_target, wissen_ziel, fields, body=None):
    payload = {"projectTarget": project_target, "wissenZiel": wissen_ziel, "fields": fields}
    if body is not None:
        payload["body"] = body
    return client.post(f"/api/document/import/office/{token}", json=payload)


def test_confirm_copies_media_and_keeps_image_references_valid(client, tmp_path):
    payload = make_docx_with_image_bytes(tmp_path, "# Bildtest\n\n![Bild](bild.png)\n\nText nach dem Bild.\n")
    token = upload(client, tmp_path, payload, "bildtest.docx").get_json()["token"]
    response = confirm(
        client, token,
        project_target="unterricht/mathematik/klasse-06/thema/arbeitsblaetter/bildtest/bildtest.qmd",
        wissen_ziel="arbeitsblatt/mathematik/klasse-06/thema",
        fields={"title": "Bildtest"},
    )
    assert response.status_code == 200
    target = tmp_path / response.get_json()["path"]
    text = target.read_text(encoding="utf-8")
    match = re.search(r"!\[[^\]]*]\((assets/[^)\s]+)\)", text)
    assert match, text
    assert (target.parent / match.group(1)).is_file()


def test_confirm_rejects_non_list_tags_before_erschliessen(client, tmp_path):
    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Inhalt fuer den Tags-Typtest.")
    token = upload(client, tmp_path, pdf_path.read_bytes(), "quelle.pdf").get_json()["token"]
    response = confirm(
        client, token,
        project_target="unterricht/mathematik/klasse-06/thema/arbeitsblaetter/blatt/blatt.qmd",
        wissen_ziel="arbeitsblatt/mathematik/klasse-06/thema",
        fields={"title": "Test", "tags": 42},
    )
    assert response.status_code == 400
    assert not (tmp_path / "wissen").exists()


def test_confirm_quotes_source_pdf_path_with_special_characters(client, tmp_path):
    from material_ui.metadata import read_metadata

    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Inhalt fuer den YAML-Escaping-Test.")
    token = upload(client, tmp_path, pdf_path.read_bytes(), "quelle.pdf").get_json()["token"]
    response = confirm(
        client, token,
        project_target="unterricht/mathematik/klasse-06/thema/arbeitsblaetter/blatt/blatt.qmd",
        wissen_ziel="arbeitsblatt/mathe: hinweis",
        fields={"title": "Test"},
    )
    assert response.status_code == 200
    target = tmp_path / response.get_json()["path"]
    metadata = read_metadata(target.read_text(encoding="utf-8"))
    assert metadata["material"]["import"]["source-pdf"].startswith("wissen/arbeitsblatt/mathe: hinweis/")


def test_confirm_rejects_oversized_body(client, tmp_path, monkeypatch):
    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Inhalt fuer den Body-Groessentest.")
    token = upload(client, tmp_path, pdf_path.read_bytes(), "quelle.pdf").get_json()["token"]
    monkeypatch.setattr(office_import, "MAX_OFFICE_BYTES", 10)
    response = confirm(
        client, token,
        project_target="unterricht/mathematik/klasse-06/thema/arbeitsblaetter/blatt/blatt.qmd",
        wissen_ziel="arbeitsblatt/mathematik/klasse-06/thema",
        fields={"title": "Test"},
        body="x" * 11,
    )
    assert response.status_code == 400


def test_prune_expired_keeps_fresh_in_progress_directory(tmp_path):
    staging_root = tmp_path / ".material-ui" / "office-imports"
    fresh = staging_root / ("a" * 48)
    fresh.mkdir(parents=True)
    office_import._prune_expired(tmp_path)
    assert fresh.is_dir()


def test_prune_expired_removes_stale_directories(tmp_path):
    staging_root = tmp_path / ".material-ui" / "office-imports"
    stale = staging_root / ("b" * 48)
    stale.mkdir(parents=True)
    old = time.time() - office_import.OFFICE_IMPORT_TTL - 3600
    os.utime(stale, (old, old))
    office_import._prune_expired(tmp_path)
    assert not stale.exists()


def test_confirm_erschliesst_pdf_and_writes_qmd_with_provenance(client, tmp_path):
    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Bruchrechnung Uebung fuer den Import-Test.")
    token = upload(client, tmp_path, pdf_path.read_bytes(), "bruchrechnung.pdf").get_json()["token"]

    response = confirm(
        client,
        token,
        project_target="unterricht/mathematik/klasse-06/bruchrechnung/arbeitsblaetter/ab/ab.qmd",
        wissen_ziel="arbeitsblatt/mathematik/klasse-06/bruchrechnung",
        fields={"title": "Bruchrechnung", "subject": "mathematik", "grade": "06", "thema": "bruchrechnung", "kind": "Arbeitsblatt", "tags": ["uebung"]},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["duplicate"] is False
    assert data["wissenPath"] == "wissen/arbeitsblatt/mathematik/klasse-06/bruchrechnung/bruchrechnung.pdf"

    target = tmp_path / data["path"]
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert 'source-pdf: "wissen/arbeitsblatt/mathematik/klasse-06/bruchrechnung/bruchrechnung.pdf"' in text
    assert "kind: pdf" in text
    assert 'subject: mathematik' in text
    assert "- uebung" in text
    assert (tmp_path / "wissen" / "arbeitsblatt" / "mathematik" / "klasse-06" / "bruchrechnung" / "bruchrechnung.pdf").is_file()
    assert not (tmp_path / ".material-ui" / "office-imports" / token).exists()
    assert any(entry["path"] == data["path"] for entry in data["qmds"])


def test_confirm_detects_duplicate_and_keeps_single_wissen_copy(client, tmp_path):
    first_pdf = write_pdf(tmp_path / "original.pdf", "Identischer Inhalt fuer den Dublettentest.")
    payload = first_pdf.read_bytes()

    token_a = upload(client, tmp_path, payload, "original.pdf").get_json()["token"]
    first = confirm(
        client, token_a,
        project_target="unterricht/mathematik/klasse-06/thema/arbeitsblaetter/erstes/erstes.qmd",
        wissen_ziel="arbeitsblatt/mathematik/klasse-06/thema",
        fields={"title": "Erstes"},
    ).get_json()

    token_b = upload(client, tmp_path, payload, "kopie.pdf").get_json()["token"]
    second = confirm(
        client, token_b,
        project_target="unterricht/mathematik/klasse-06/thema/arbeitsblaetter/zweites/zweites.qmd",
        wissen_ziel="arbeitsblatt/mathematik/klasse-06/anderes-thema",
        fields={"title": "Zweites"},
    ).get_json()

    assert second["duplicate"] is True
    assert second["wissenPath"] == first["wissenPath"]
    wissen_pdfs = list((tmp_path / "wissen").rglob("*.pdf"))
    assert len(wissen_pdfs) == 1


def test_confirm_rejects_hidden_or_non_qmd_target(client, tmp_path):
    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Inhalt fuer den Importtest.")
    token = upload(client, tmp_path, pdf_path.read_bytes(), "quelle.pdf").get_json()["token"]
    response = confirm(
        client, token,
        project_target="unterricht/.versteckt/blatt.qmd",
        wissen_ziel="arbeitsblatt/mathematik/klasse-06/thema",
        fields={},
    )
    assert response.status_code == 400


def test_confirm_rejects_traversal_in_wissen_ziel(client, tmp_path):
    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Inhalt fuer den Importtest.")
    token = upload(client, tmp_path, pdf_path.read_bytes(), "quelle.pdf").get_json()["token"]
    response = confirm(
        client, token,
        project_target="unterricht/mathematik/klasse-06/thema/arbeitsblaetter/blatt/blatt.qmd",
        wissen_ziel="arbeitsblatt/../../ausserhalb",
        fields={},
    )
    assert response.status_code == 400


def test_cancel_discards_staging_and_confirm_then_fails(client, tmp_path):
    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Inhalt fuer den Importtest.")
    token = upload(client, tmp_path, pdf_path.read_bytes(), "quelle.pdf").get_json()["token"]
    assert client.delete(f"/api/document/import/office/{token}").status_code == 200
    assert not (tmp_path / ".material-ui" / "office-imports" / token).exists()
    response = confirm(
        client, token,
        project_target="unterricht/mathematik/klasse-06/thema/arbeitsblaetter/blatt/blatt.qmd",
        wissen_ziel="arbeitsblatt/mathematik/klasse-06/thema",
        fields={},
    )
    assert response.status_code == 404


class FakeChatProvider:
    def __init__(self, rewritten: str) -> None:
        self.name = "ok"
        self.experimental = False
        self.rewritten = rewritten

    def available(self) -> bool:
        return True

    def usage_hint(self) -> dict:
        return {"kind": "link", "message": "ok"}

    def create_session(self) -> dict:
        return {}

    def send(self, session, text):
        yield text_event(self.rewritten)
        yield done_event()

    def close_session(self, session) -> None:
        pass


def test_draft_endpoint_streams_ai_rewrite_and_commit_uses_it(tmp_path):
    (tmp_path / "wissen").mkdir()
    (tmp_path / "unterricht").mkdir()
    runtime = RuntimeState(config=AppConfig(tmp_path))
    app = material_app.create_app(runtime=runtime)
    app.config.update(TESTING=True)
    runtime.plugins.contexts["chat"].chat_service = ChatService(runtime.config, providers=[FakeChatProvider("## Aufgabe 1\n\nUmgebauter Text.\n")])
    local_client = app.test_client()

    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Alter Entwurfstext, der von der KI umgebaut werden soll.")
    token = upload(local_client, tmp_path, pdf_path.read_bytes(), "quelle.pdf").get_json()["token"]

    response = local_client.post(
        f"/api/document/import/office/{token}/draft",
        json={"provider": "ok", "fields": {"title": "Test", "subject": "mathematik"}},
    )
    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data: ")
    ]
    assert events[0] == {"type": "text", "text": "## Aufgabe 1\n\nUmgebauter Text.\n"}
    assert events[1] == {"type": "done"}

    confirmed = confirm(
        local_client, token,
        project_target="unterricht/mathematik/klasse-06/thema/arbeitsblaetter/blatt/blatt.qmd",
        wissen_ziel="arbeitsblatt/mathematik/klasse-06/thema",
        fields={"title": "Test"},
    )
    assert confirmed.status_code == 200
    text = (tmp_path / confirmed.get_json()["path"]).read_text(encoding="utf-8")
    assert "Umgebauter Text." in text
    assert "Alter Entwurfstext" not in text


class CancellingChatProvider(FakeChatProvider):
    """Simuliert einen Nutzer, der den Import abbricht, waehrend die KI noch antwortet."""

    def __init__(self, rewritten: str, token: str, root: Path) -> None:
        super().__init__(rewritten)
        self._token = token
        self._root = root

    def send(self, session, text):
        yield text_event(self.rewritten)
        office_import.discard_office_import(self._token, root=self._root)
        yield done_event()


def test_draft_endpoint_survives_cancel_during_stream(tmp_path):
    (tmp_path / "wissen").mkdir()
    (tmp_path / "unterricht").mkdir()
    runtime = RuntimeState(config=AppConfig(tmp_path))
    app = material_app.create_app(runtime=runtime)
    app.config.update(TESTING=True)
    local_client = app.test_client()

    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Text fuer den Abbruch-waehrend-KI-Umbau-Test.")
    token = upload(local_client, tmp_path, pdf_path.read_bytes(), "quelle.pdf").get_json()["token"]
    runtime.plugins.contexts["chat"].chat_service = ChatService(runtime.config, providers=[CancellingChatProvider("Umbau", token, tmp_path)])

    response = local_client.post(
        f"/api/document/import/office/{token}/draft",
        json={"provider": "ok", "fields": {}},
    )
    assert response.status_code == 200
    assert response.get_data(as_text=True)  # Stream endet ohne unbehandelte Exception


def test_confirm_accepts_manually_edited_body_override(client, tmp_path):
    pdf_path = write_pdf(tmp_path / "quelle.pdf", "Alter Entwurfstext fuer den Override-Test.")
    token = upload(client, tmp_path, pdf_path.read_bytes(), "quelle.pdf").get_json()["token"]
    response = client.post(
        f"/api/document/import/office/{token}",
        json={
            "projectTarget": "unterricht/mathematik/klasse-06/thema/arbeitsblaetter/blatt/blatt.qmd",
            "wissenZiel": "arbeitsblatt/mathematik/klasse-06/thema",
            "fields": {"title": "Test"},
            "body": "Handbearbeiteter Text statt Extraktion.",
        },
    )
    assert response.status_code == 200
    text = (tmp_path / response.get_json()["path"]).read_text(encoding="utf-8")
    assert "Handbearbeiteter Text statt Extraktion." in text
    assert "Alter Entwurfstext" not in text


def test_default_targets_maps_kind_to_project_and_wissen_paths():
    project_target, wissen_ziel = office_import.default_targets(
        subject="mathematik", grade="6", thema="bruchrechnung", kind="Arbeitsblatt", stem="bruchrechnung-uebung",
    )
    assert project_target == "unterricht/mathematik/klasse-06/bruchrechnung/arbeitsblaetter/ab_bruchrechnung-uebung/ab_bruchrechnung-uebung.qmd"
    assert wissen_ziel == "arbeitsblatt/mathematik/klasse-06/bruchrechnung"


def test_default_targets_routes_curriculum_kind_without_grade_or_thema():
    _, wissen_ziel = office_import.default_targets(
        subject="mathematik", grade="6", thema="bruchrechnung", kind="Curriculum", stem="lehrplan",
    )
    assert wissen_ziel == "mathematik/curriculum"
