from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable
from material_core import workspace

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_PROJECT_DIR = workspace.root()
_DOTENV_FILE = _PROJECT_DIR / ".env"
_PREVIEW_COURSES = {"algorithmen-2026", "java-course", "miniworlds-robot", "oop-2026"}
_DEMO_COURSES = {"h5p-demo", "h5p-demo-en", "miniworlds_examples"}
_COURSE_GROUPS = (
    ("courses", "Kurse", "Fertige Kursangebote mit vorbereiteten H5P-Paketen."),
    ("demos", "Demos", "Beispiele und Testkurse für H5P-Fragetypen und Integrationen."),
    ("preview", "Preview", "Unfertige Kurse, die sichtbar sind, aber noch Lücken enthalten können."),
)
_COURSE_COLORS = {
    "algorithmen-2026": "#d97706",
    "h5p-demo": "#7c3aed",
    "h5p-demo-en": "#0891b2",
    "java-course": "#dc2626",
    "miniworlds_examples": "#16a34a",
    "miniworlds-robot": "#0f766e",
    "oop-2026": "#9333ea",
    "python-2026": "#2563eb",
}
_COURSE_DESCRIPTIONS = {
    "algorithmen-2026": "Suchen, Sortieren, Rekursion, Datenstrukturen und Komplexität.",
    "h5p-demo": "Beispiele für die verfügbaren H5P-Fragetypen.",
    "h5p-demo-en": "English examples for the available H5P question types.",
    "java-course": "Ein Java-Kurs mit Turtle, p5, Kontrollstrukturen, Methoden und Objekten.",
    "miniworlds_examples": "Tutorials und Aufgaben rund um miniworlds.",
    "miniworlds-robot": "Programmiergrundlagen mit Roboter-Welten, Schleifen, Bedingungen und Funktionen.",
    "oop-2026": "Objektorientierte Programmierung mit Klassen, Vererbung und Entwurfsmustern.",
    "python-2026": "Python-Grundlagen, Turtle, p5, miniworlds, Funktionen, Listen und Klassen.",
}


def _fill(template: str, **kwargs: str) -> str:
    """Replace ``${KEY}`` (uppercase) placeholders in *template*."""
    for key, value in kwargs.items():
        template = template.replace(f"${{{key.upper()}}}", value)
    return template


def _read_dotenv_values(dotenv_file: Path = _DOTENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if dotenv_file.exists():
        for raw_line in dotenv_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            values[key] = value
    return values


class TemplateRenderer:
    def __init__(self, *, escape_inline: Callable[[str], str], dotenv_file: Path | None = None) -> None:
        self._escape_inline = escape_inline
        self._dotenv_file = dotenv_file
        self._course_page_tpl = (_TEMPLATES_DIR / "course_page.html").read_text("utf-8")
        self._index_tpl = (_TEMPLATES_DIR / "index.html").read_text("utf-8")

    def _dotenv_values(self) -> dict[str, str]:
        if self._dotenv_file is None:
            return _read_dotenv_values()
        return _read_dotenv_values(self._dotenv_file)

    def _course_color(self, course_name: str) -> str:
        return _COURSE_COLORS.get(course_name, "#2563eb")

    def _course_label(self, course_dir: Path) -> str:
        index_path = course_dir / "index.mdx"
        if not index_path.exists():
            return course_dir.name
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip() or course_dir.name
        return course_dir.name

    def _course_chapter_count(self, course_dir: Path) -> int:
        index_path = course_dir / "index.mdx"
        if not index_path.exists():
            return 0
        return index_path.read_text(encoding="utf-8").count("<Chapter")

    def _course_group_key(self, course_name: str) -> str:
        if course_name in _PREVIEW_COURSES:
            return "preview"
        if course_name in _DEMO_COURSES or "demo" in course_name:
            return "demos"
        return "courses"

    def _env_value(self, values: dict[str, str], *keys: str) -> str:
        for key in keys:
            value = values.get(key) or os.environ.get(key, "")
            if value.strip():
                return value.strip()
        return ""

    def _render_imprint(self) -> str:
        values = self._dotenv_values()
        name = self._env_value(values, "IMPRESSUM_NAME", "IMPRINT_NAME")
        address = self._env_value(values, "IMPRESSUM_ADDRESS", "IMPRINT_ADDRESS")
        email = self._env_value(values, "IMPRESSUM_EMAIL", "IMPRINT_EMAIL")
        phone = self._env_value(values, "IMPRESSUM_PHONE", "IMPRINT_PHONE")
        website = self._env_value(values, "IMPRESSUM_WEBSITE", "IMPRINT_WEBSITE")

        rows = []
        if name:
            rows.append(f"<strong>{self._escape_inline(name)}</strong>")
        if address:
            escaped_address = self._escape_inline(address).replace("\\n", "<br>").replace("\n", "<br>")
            rows.append(escaped_address)
        if email:
            escaped_email = self._escape_inline(email)
            rows.append(f'E-Mail: <a href="mailto:{escaped_email}">{escaped_email}</a>')
        if phone:
            rows.append(f"Telefon: {self._escape_inline(phone)}")
        if website:
            rows.append(f"Web: {self._escape_inline(website)}")

        if not rows:
            rows.append("Impressumsdaten sind noch nicht konfiguriert.")
        return "".join(f"<p>{row}</p>" for row in rows)

    def _render_site_description(self) -> str:
        values = self._dotenv_values()
        description = self._env_value(values, "SITE_DESCRIPTION", "COURSE_INDEX_DESCRIPTION")
        if not description:
            return ""
        escaped_description = self._escape_inline(description).replace("\\n", "<br>").replace("\n", "<br>")
        return f"<p>{escaped_description}</p>"

    def render_course_page(
        self,
        *,
        title: str,
        content_html: str,
        canonical_url: str = "",
        preview_fallback: bool = True,
        home_href: str = "/",
    ) -> str:
        escaped_title = self._escape_inline(title)
        escaped_color = self._escape_inline(self._course_color(title))
        escaped_home_href = self._escape_inline(home_href)
        metadata = ""
        if canonical_url:
            escaped_url = self._escape_inline(canonical_url)
            metadata = (
                f'<link rel="canonical" href="{escaped_url}">\n'
                f'    <meta property="og:title" content="{escaped_title}">\n'
                f'    <meta property="og:type" content="article">\n'
                f'    <meta property="og:url" content="{escaped_url}">'
            )
        return _fill(
            self._course_page_tpl,
            title=escaped_title,
            course_color=escaped_color,
            metadata=metadata,
            content_html=content_html,
            home_href=escaped_home_href,
            preview_href_line=(
                "const previewHref = `/preview/${encodeURIComponent(courseSlug)}/${encodeURIComponent(questionId)}?mode=view&simple=1`;"
                if preview_fallback
                else ""
            ),
            question_href_expr="openLink || previewHref" if preview_fallback else "openLink",
        ).strip()

    def render_index(self, course_dirs: Iterable[Path], *, static: bool = False, canonical_url: str = "") -> str:
        grouped_courses: dict[str, list[Path]] = {key: [] for key, _, _ in _COURSE_GROUPS}
        for course_dir in sorted(course_dirs, key=lambda item: item.name):
            grouped_courses[self._course_group_key(course_dir.name)].append(course_dir)

        course_groups = []
        for group_key, group_title, group_description in _COURSE_GROUPS:
            course_items = grouped_courses[group_key]
            if not course_items:
                continue

            tabs = []
            panels = []
            for index, course_dir in enumerate(course_items):
                tab_html, panel_html = self._render_index_course_item(
                    course_dir,
                    index=index,
                    group_key=group_key,
                    static=static,
                )
                tabs.append(tab_html)
                panels.append(panel_html)

            escaped_title = self._escape_inline(group_title)
            escaped_description = self._escape_inline(group_description)
            tabs_html = "".join(tabs)
            panels_html = "".join(panels)
            course_groups.append(
                f'<section class="course-group" aria-labelledby="course-group-{group_key}">'
                f'<header class="course-group-header">'
                f'<h2 id="course-group-{group_key}">{escaped_title}</h2>'
                f'<p>{escaped_description}</p>'
                f'</header>'
                f'<nav class="course-tabs" role="tablist" aria-label="{escaped_title}">{tabs_html}</nav>'
                f'<section class="course-panels">{panels_html}</section>'
                f'</section>'
            )

        course_groups_html = "".join(course_groups)
        metadata = ""
        if canonical_url:
            escaped_url = self._escape_inline(canonical_url)
            metadata = (
                f'<link rel="canonical" href="{escaped_url}">\n'
                f'    <meta property="og:title" content="Kurse">\n'
                f'    <meta property="og:type" content="website">\n'
                f'    <meta property="og:url" content="{escaped_url}">'
            )
        return _fill(
            self._index_tpl,
            metadata=metadata,
            home_href="index.html" if static else "/",
            course_groups=course_groups_html,
            site_description=self._render_site_description(),
            impressum=self._render_imprint(),
        ).strip()

    def _render_index_course_item(
        self,
        course_dir: Path,
        *,
        index: int,
        group_key: str,
        static: bool,
    ) -> tuple[str, str]:
        course_name = course_dir.name
        label = self._course_label(course_dir)
        escaped_name = self._escape_inline(course_name)
        escaped_label = self._escape_inline(label)
        escaped_color = self._escape_inline(self._course_color(course_name))
        href = (
            f"courses/{escaped_name}/index.html"
            if static
            else f"/courses/{escaped_name}"
        )
        preview = course_name in _PREVIEW_COURSES
        preview_badge = (
            '<span class="course-status preview">Unfertige Preview</span>'
            if preview
            else '<span class="course-status ready">Öffentlich</span>'
        )
        chapter_count = self._course_chapter_count(course_dir)
        description = _COURSE_DESCRIPTIONS.get(course_name, "Interaktive Programmieraufgaben und H5P-Aktivitäten.")
        selected = "true" if index == 0 else "false"
        hidden = "" if index == 0 else " hidden"
        preview_class = " is-preview" if preview else ""
        preview_notice = (
            '<p class="preview-notice">Dieser Kurs ist noch unfertig und kann Lücken, Platzhalter oder ungeprüfte Aufgaben enthalten.</p>'
            if preview
            else ""
        )
        tab_preview_label = '<span class="tab-preview-label">Preview</span>' if preview else ""
        tab_id = f"course-tab-{group_key}-{index}"
        panel_id = f"course-panel-{group_key}-{index}"
        tab_html = (
            f'<button class="course-tab{preview_class}" type="button" role="tab" aria-selected="{selected}" '
            f'aria-controls="{panel_id}" id="{tab_id}" style="--course-color: {escaped_color}">'
            f'<span class="tab-dot" aria-hidden="true"></span><span>{escaped_label}</span>'
            f'{tab_preview_label}</button>'
        )
        panel_html = (
            f'<article class="course-panel{preview_class}" id="{panel_id}" role="tabpanel" aria-labelledby="{tab_id}"{hidden} '
            f'style="--course-color: {escaped_color}">'
            f'<div class="course-panel-main">'
            f'<p class="course-kicker">Kurs</p>'
            f'<h2>{escaped_label}</h2>'
            f'<p>{self._escape_inline(description)}</p>'
            f'{preview_notice}'
            f'<div class="course-meta">{preview_badge}<span>{chapter_count} Kapitel</span></div>'
            f'</div>'
            f'<a class="course-open" href="{href}">Kurs öffnen</a>'
            f'</article>'
        )
        return tab_html, panel_html
