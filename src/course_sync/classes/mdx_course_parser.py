from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Callable, Pattern

from .models import PythonQuestionBlock, SourceFile, TestCase
from .course_sources import course_source_files, course_source_fingerprint
from .python_runner_policy import ensure_miniworlds_packages, resolve_python_runner, validate_graphics_runner


class MdxCourseParser:
    """Parses MDX course files into strongly typed question blocks."""

    _chapter_re = re.compile(r"<Chapter(?P<attrs>.*?)\/>", re.DOTALL)

    def __init__(
        self,
        *,
        tag_re: Pattern[str],
        fence_re: Pattern[str],
        placeholder_template: str,
        python_question_machine_name: str,
        parse_jsx_expression: Callable[[str], object],
        normalize_whitespace: Callable[[str], str],
        infer_source_package_sidecar_path: Callable[[PythonQuestionBlock], str],
        build_imported_question_from_sidecar: Callable[[Path, str, str], PythonQuestionBlock | None],
        load_h5p_sidecar_file: Callable[[Path, str], dict[str, object]],
        apply_editable_h5p_payload: Callable[[PythonQuestionBlock, dict[str, object]], None],
        course_build_dir: Callable[[Path], Path],
    ) -> None:
        self._tag_re = tag_re
        self._fence_re = fence_re
        self._placeholder_template = placeholder_template
        self._python_question_machine_name = python_question_machine_name
        self._parse_jsx_expression = parse_jsx_expression
        self._normalize_whitespace = normalize_whitespace
        self._infer_source_package_sidecar_path = infer_source_package_sidecar_path
        self._build_imported_question_from_sidecar = build_imported_question_from_sidecar
        self._load_h5p_sidecar_file = load_h5p_sidecar_file
        self._apply_editable_h5p_payload = apply_editable_h5p_payload
        self._course_build_dir = course_build_dir

    def source_files(self, course_dir: Path) -> tuple[Path, ...]:
        return course_source_files(course_dir)

    def source_fingerprint(self, course_dir: Path) -> str:
        return course_source_fingerprint(course_dir)

    def parse_bool(self, value: str, default: bool = False) -> bool:
        if value == "":
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def split_csv(self, value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def parse_braced_attribute(self, raw: str, start_index: int) -> tuple[str, int]:
        depth = 0
        in_string = False
        in_template = False
        escaped = False
        for index in range(start_index, len(raw)):
            char = raw[index]
            if in_template:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "`":
                    in_template = False
                continue
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == "`":
                in_template = True
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
                continue
            if char == "}":
                depth -= 1
                if depth == 0:
                    return raw[start_index:index + 1], index + 1
        raise ValueError("Unvollstaendiger JSX-Ausdruck im PythonQuestion-Tag.")

    def parse_tag_attributes(self, raw_attrs: str) -> dict[str, object]:
        attrs: dict[str, object] = {}
        index = 0
        while index < len(raw_attrs):
            while index < len(raw_attrs) and raw_attrs[index].isspace():
                index += 1
            if index >= len(raw_attrs):
                break

            key_match = re.match(r"([A-Za-z_:][A-Za-z0-9_:-]*)", raw_attrs[index:])
            if key_match is None:
                index += 1
                continue
            key = key_match.group(1)
            index += len(key)
            while index < len(raw_attrs) and raw_attrs[index].isspace():
                index += 1
            if index >= len(raw_attrs) or raw_attrs[index] != "=":
                attrs[key] = ""
                continue
            index += 1
            while index < len(raw_attrs) and raw_attrs[index].isspace():
                index += 1
            if index >= len(raw_attrs):
                break

            if raw_attrs[index] == '"':
                index += 1
                value_start = index
                while index < len(raw_attrs):
                    if raw_attrs[index] == '"' and raw_attrs[index - 1] != "\\":
                        break
                    index += 1
                attrs[key] = html.unescape(raw_attrs[value_start:index].strip())
                index += 1
                continue

            if raw_attrs[index] == "{":
                expression, index = self.parse_braced_attribute(raw_attrs, index)
                attrs[key] = self._parse_jsx_expression(expression[1:-1].strip())
                continue

            value_start = index
            while index < len(raw_attrs) and not raw_attrs[index].isspace():
                index += 1
            attrs[key] = raw_attrs[value_start:index]
        return attrs

    def _chapter_h5p_subdir(self, chapter_src: str) -> str:
        if not chapter_src:
            return ""
        source_path = Path(chapter_src).with_suffix("")
        parts = source_path.parts
        if "chapters" in parts:
            chapter_index = parts.index("chapters")
            if len(parts) > chapter_index + 1:
                return parts[chapter_index + 1]
        return source_path.name

    def build_question_from_attrs(
        self,
        course_dir: Path,
        attrs: dict[str, object],
        *,
        h5p_subdir: str = "",
        infer_source_sidecar: bool = True,
    ) -> PythonQuestionBlock:
        course_slug = course_dir.name
        identifier = str(attrs.get("identifier", "")).strip()
        if not identifier:
            raise ValueError("PythonQuestion benötigt ein identifier-Attribut.")

        title = str(attrs.get("title", identifier))
        instructions = str(attrs.get("instructions", ""))
        preview_url = str(attrs.get("previewUrl", attrs.get("preview-url", "")))
        main_library = str(
            attrs.get("h5pLibrary", attrs.get("h5p-library", self._python_question_machine_name))
        ).strip() or self._python_question_machine_name
        package_url = str(attrs.get("packageUrl", attrs.get("package-url", ""))).strip()
        raw_package = self.parse_bool(str(attrs.get("rawPackage", attrs.get("raw-package", "false"))), default=False)
        h5p_metadata_path = str(attrs.get("h5pMetadataPath", attrs.get("h5p-metadata-path", ""))).strip()
        h5p_content_path = str(attrs.get("h5pContentPath", attrs.get("h5p-content-path", ""))).strip()
        source_package_path = str(attrs.get("sourcePackagePath", attrs.get("source-package-path", ""))).strip()
        explicit_source_package_path = bool(source_package_path)
        h5p_subdir = str(attrs.get("h5pSubdir", attrs.get("h5p-subdir", h5p_subdir))).strip()
        grading_method = str(attrs.get("gradingMethod", attrs.get("grading-method", "please_choose")))
        due_date = str(attrs.get("dueDate", attrs.get("due-date", attrs.get("duedate", "")))).strip()
        packages = ensure_miniworlds_packages(self.split_csv(str(attrs.get("packages", ""))))
        runner = resolve_python_runner(attrs.get("runner", ""), packages=packages)
        show_console = self.parse_bool(str(attrs.get("showConsole", "true")), default=True)
        allow_adding_files = self.parse_bool(str(attrs.get("allowAddingFiles", "false")), default=False)
        editable_h5p_payload = attrs.get("h5p")

        if not source_package_path and infer_source_sidecar:
            source_package_path = self._infer_source_package_sidecar_path(
                PythonQuestionBlock(
                    identifier=identifier,
                    title=identifier,
                    instructions="",
                    course_slug=course_slug,
                    course_dir=course_dir,
                    h5p_subdir=h5p_subdir,
                )
            )

        question = (
            self._build_imported_question_from_sidecar(course_dir, identifier, source_package_path)
            if source_package_path
            else None
        )

        if question is None:
            question = PythonQuestionBlock(
                identifier=identifier,
                title=title,
                instructions=instructions,
                preview_url=preview_url,
                main_library=main_library,
                package_url=package_url,
                raw_package=raw_package,
                h5p_metadata_path=h5p_metadata_path,
                h5p_content_path=h5p_content_path,
                source_package_path=source_package_path,
                h5p_subdir=h5p_subdir,
                runner=runner,
                packages=packages,
                grading_method=grading_method,
                due_date=due_date,
                show_console=show_console,
                allow_adding_files=allow_adding_files,
                course_slug=course_slug,
                course_dir=course_dir,
            )

        if "title" in attrs:
            question.title = title
        if "instructions" in attrs:
            question.instructions = instructions
        if "previewUrl" in attrs or "preview-url" in attrs:
            question.preview_url = preview_url
        if "h5pLibrary" in attrs or "h5p-library" in attrs:
            question.main_library = main_library
        if "packageUrl" in attrs or "package-url" in attrs:
            question.package_url = package_url
        if "rawPackage" in attrs or "raw-package" in attrs:
            question.raw_package = raw_package
        if source_package_path:
            question.source_package_path = source_package_path
            question.source_package_path_inferred = not explicit_source_package_path
        question.h5p_subdir = h5p_subdir
        if due_date:
            question.due_date = due_date
        if "runner" in attrs:
            question.runner = runner
        if "packages" in attrs:
            question.packages = packages
        if "gradingMethod" in attrs or "grading-method" in attrs:
            question.grading_method = grading_method
        if "showConsole" in attrs:
            question.show_console = show_console
        if "allowAddingFiles" in attrs:
            question.allow_adding_files = allow_adding_files

        if h5p_metadata_path:
            question.h5p_metadata = self._load_h5p_sidecar_file(
                question.course_dir,
                h5p_metadata_path,
            )
        if h5p_content_path:
            question.h5p_content = self._load_h5p_sidecar_file(
                question.course_dir,
                h5p_content_path,
            )
        if isinstance(editable_h5p_payload, dict):
            self._apply_editable_h5p_payload(question, editable_h5p_payload)
        return question

    def _expand_chapters(self, course_dir: Path, source: str) -> tuple[str, dict[int, str], dict[int, str]]:
        chapter_subdirs: dict[int, str] = {}
        chapter_due_dates: dict[int, str] = {}
        chunks: list[str] = []
        last_end = 0
        for match in self._chapter_re.finditer(source):
            chunks.append(source[last_end:match.start()])
            attrs = self.parse_tag_attributes(match.group("attrs"))
            chapter_src = str(attrs.get("src", "")).strip()
            if not chapter_src:
                raise ValueError("Chapter benötigt ein src-Attribut.")

            chapter_path = (course_dir / chapter_src).resolve()
            if not chapter_path.is_file():
                raise ValueError(f"Chapter-Datei '{chapter_src}' wurde nicht gefunden.")

            start = sum(len(chunk) for chunk in chunks)
            chapter_source = chapter_path.read_text(encoding="utf-8")
            chunks.append(chapter_source)
            end = start + len(chapter_source)
            chapter_subdirs[start] = self._chapter_h5p_subdir(chapter_src)
            chapter_subdirs[end] = ""
            chapter_due_dates[start] = str(
                attrs.get("dueDate", attrs.get("due-date", attrs.get("duedate", "")))
            ).strip()
            chapter_due_dates[end] = ""
            last_end = match.end()

        chunks.append(source[last_end:])
        return "".join(chunks), chapter_subdirs, chapter_due_dates

    def _h5p_subdir_for_position(
        self,
        position: int,
        chapter_subdirs: dict[int, str],
        sorted_keys: list[int] | None = None,
    ) -> str:
        h5p_subdir = ""
        for start in (sorted_keys if sorted_keys is not None else sorted(chapter_subdirs)):
            if start > position:
                break
            h5p_subdir = chapter_subdirs[start]
        return h5p_subdir

    def _chapter_spans(self, chapter_subdirs: dict[int, str]) -> list[tuple[int, int, str]]:
        spans: list[tuple[int, int, str]] = []
        open_start: int | None = None
        open_subdir = ""
        for position in sorted(chapter_subdirs):
            h5p_subdir = chapter_subdirs[position]
            if h5p_subdir:
                open_start = position
                open_subdir = h5p_subdir
                continue
            if open_start is not None:
                spans.append((open_start, position, open_subdir))
                open_start = None
                open_subdir = ""
        return spans

    def _slugify_identifier_part(self, value: str) -> str:
        normalized = value.strip().lower()
        for source, target in {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
        }.items():
            normalized = normalized.replace(source, target)
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        return re.sub(r"-+", "-", slug) or "inhalt"

    def _markdown_section_title(self, source: str, fallback: str) -> str:
        for line in source.splitlines():
            match = re.match(r"^\s{0,3}#{2,6}\s+(.+?)\s*#*\s*$", line)
            if match:
                return match.group(1).strip()
        return fallback

    def _build_markdown_question(
        self,
        course_dir: Path,
        *,
        markdown_source: str,
        h5p_subdir: str,
        due_date: str,
        used_identifiers: set[str],
    ) -> PythonQuestionBlock:
        title = self._markdown_section_title(markdown_source, "Inhalt")
        base_identifier = self._slugify_identifier_part(f"{h5p_subdir}-{title}")
        identifier = base_identifier
        suffix = 2
        while identifier in used_identifiers:
            identifier = f"{base_identifier}-{suffix}"
            suffix += 1
        used_identifiers.add(identifier)
        instructions = markdown_source.strip()
        packages = ensure_miniworlds_packages([], source=instructions)
        runner = resolve_python_runner(
            "pyodide" if "miniworlds" in instructions.lower() else "",
            packages=packages,
            source=instructions,
        )

        return PythonQuestionBlock(
            identifier=identifier,
            title=title,
            instructions=instructions,
            h5p_subdir=h5p_subdir,
            runner=runner,
            packages=packages,
            grading_method="please_choose",
            due_date=due_date,
            show_console=False,
            h5p_content={
                "contentType": "text_only",
                "pythonRunner": runner,
                "contents": [
                    {
                        "type": "text",
                        "text": instructions,
                    }
                ],
                "editorSettings": {
                    "instructions": instructions,
                    "options": {},
                },
                "gradingSettings": {
                    "gradingMethod": "please_choose",
                },
            },
            course_slug=course_dir.name,
            course_dir=course_dir,
        )

    def _markdown_question_segments(
        self,
        parse_source: str,
        *,
        chapter_spans: list[tuple[int, int, str]],
        tag_matches: list[re.Match[str]],
    ) -> list[tuple[int, int, str]]:
        heading_re = re.compile(r"^###\s+.+$", re.MULTILINE)
        segments: list[tuple[int, int, str]] = []
        for chapter_start, chapter_end, h5p_subdir in chapter_spans:
            events: list[tuple[int, int, str]] = []
            events.extend(
                (match.start(), match.end(), "tag")
                for match in tag_matches
                if chapter_start <= match.start() < chapter_end
            )
            events.extend(
                (match.start(), match.end(), "heading")
                for match in heading_re.finditer(parse_source, chapter_start, chapter_end)
            )
            events.sort(key=lambda item: (item[0], 0 if item[2] == "heading" else 1))

            section_start = chapter_start
            for event_start, event_end, event_type in events:
                if event_start > section_start and parse_source[section_start:event_start].strip():
                    segments.append((section_start, event_start, h5p_subdir))
                if event_type == "tag":
                    section_start = event_end
                else:
                    section_start = event_start
            if chapter_end > section_start and parse_source[section_start:chapter_end].strip():
                segments.append((section_start, chapter_end, h5p_subdir))
        return segments

    def parse_test_case(self, raw: str) -> TestCase:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Testfall muss ein JSON-Objekt sein.")

        inputs = payload.get("inputs", []) or []
        outputs = payload.get("outputs", []) or []

        return TestCase(
            hidden=bool(payload.get("hidden", False)),
            inputs=[str(item) for item in inputs],
            outputs=[str(item) for item in outputs],
        )

    def parse_json_object(self, raw: str, *, description: str) -> dict[str, object]:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"{description} muss ein JSON-Objekt sein.")
        return payload

    def parse_source_file(self, spec_parts: list[str], body: str) -> SourceFile:
        file_token = next((part for part in spec_parts if part.startswith("file:")), "")
        if not file_token:
            raise ValueError("Datei-Codeblock benötigt ein file:NAME.py-Token.")

        file_name = file_token.split(":", 1)[1].strip()
        if not file_name:
            raise ValueError("Datei-Codeblock benötigt einen Dateinamen.")

        visible = True
        editable = True
        for part in spec_parts:
            if part == "hidden-file":
                visible = False
            if part == "readonly-file":
                editable = False

        return SourceFile(
            file_name=file_name,
            code=self._normalize_whitespace(body),
            visible_to_learner=visible,
            learner_editable=editable,
        )

    def parse_course(self, course_dir: Path) -> tuple[str, list[PythonQuestionBlock], str]:
        mdx_path = course_dir / "index.mdx"
        source = mdx_path.read_text(encoding="utf-8")
        parse_source, chapter_subdirs, chapter_due_dates = self._expand_chapters(course_dir, source)

        scratch_payload_identifiers: set[str] = set()
        for fence in self._fence_re.finditer(parse_source):
            spec = fence.group("spec").strip()
            spec_parts = spec.split()
            if len(spec_parts) < 3 or not spec_parts[1].startswith("question:"):
                continue
            role = spec_parts[2]
            if role in {"starter", "solution", "pre", "post", "testcase"} or role.startswith("file:"):
                scratch_payload_identifiers.add(spec_parts[1].split(":", 1)[1].strip())

        questions: dict[str, PythonQuestionBlock] = {}
        question_positions: dict[str, int] = {}
        questions_with_mdx_payload: set[str] = set()
        rendered_source = parse_source
        sorted_chapter_keys = sorted(chapter_subdirs)
        tag_matches = list(self._tag_re.finditer(parse_source))
        used_identifiers: set[str] = set()
        _TAG_TO_LIBRARY = {
            "JavaQuestion": "H5P.JavaQuestion",
            "SQLQuestion": "H5P.SQLQuestion",
            "AutomataQuestion": "H5P.AutomataQuestion",
        }

        for match in tag_matches:
            attrs = self.parse_tag_attributes(match.group("attrs"))
            tag_name = match.group("tag") if "tag" in self._tag_re.groupindex else ""
            if tag_name in _TAG_TO_LIBRARY and "h5pLibrary" not in attrs and "h5p-library" not in attrs:
                attrs = {**attrs, "h5pLibrary": _TAG_TO_LIBRARY[tag_name]}
            identifier = str(attrs.get("identifier", "")).strip()
            question = self.build_question_from_attrs(
                course_dir,
                {
                    **attrs,
                    "dueDate": attrs.get(
                        "dueDate",
                        attrs.get(
                            "due-date",
                            attrs.get(
                                "duedate",
                                self._h5p_subdir_for_position(
                                    match.start(), chapter_due_dates, sorted_chapter_keys
                                ),
                            ),
                        ),
                    ),
                },
                h5p_subdir=self._h5p_subdir_for_position(match.start(), chapter_subdirs, sorted_chapter_keys),
                infer_source_sidecar=identifier not in scratch_payload_identifiers,
            )
            question.course_dir = course_dir
            question.build_dir = self._course_build_dir(course_dir)
            if question.identifier in questions:
                raise ValueError(
                    f"PythonQuestion-Identifier '{question.identifier}' ist in {mdx_path} mehrfach vergeben."
                )
            used_identifiers.add(question.identifier)
            questions[question.identifier] = question
            question_positions[question.identifier] = match.start()
            rendered_source = rendered_source.replace(
                match.group(0),
                self._placeholder_template.format(identifier=question.identifier),
                1,
            )

        for fence in self._fence_re.finditer(parse_source):
            spec = fence.group("spec").strip()
            if not spec:
                continue

            spec_parts = spec.split()
            if len(spec_parts) < 3 or not spec_parts[1].startswith("question:"):
                continue

            identifier = spec_parts[1].split(":", 1)[1].strip()
            question = questions.get(identifier)
            if question is None:
                raise ValueError(f"Codeblock referenziert unbekannte PythonQuestion '{identifier}'.")

            role = spec_parts[2]
            body = self._normalize_whitespace(fence.group("body"))

            if role == "starter":
                question.starter_code = body
                questions_with_mdx_payload.add(identifier)
            elif role == "solution":
                question.solution_code = body
                questions_with_mdx_payload.add(identifier)
            elif role == "pre":
                question.pre_code = body
                questions_with_mdx_payload.add(identifier)
            elif role == "post":
                question.post_code = body
                questions_with_mdx_payload.add(identifier)
            elif role == "testcase":
                question.test_cases.append(self.parse_test_case(body))
                questions_with_mdx_payload.add(identifier)
            elif role == "h5p-metadata":
                question.h5p_metadata = self.parse_json_object(body, description="H5P-Metadaten")
            elif role == "h5p-content":
                question.h5p_content = self.parse_json_object(body, description="H5P-Content")
            elif role == "h5p":
                self._apply_editable_h5p_payload(
                    question,
                    self.parse_json_object(body, description="H5P-Daten"),
                )
            elif role.startswith("file:"):
                question.source_files.append(self.parse_source_file(spec_parts[2:], fence.group("body")))
                questions_with_mdx_payload.add(identifier)
            else:
                raise ValueError(f"Unbekannte PythonQuestion-Rolle '{role}' in {mdx_path}.")

        for question in questions.values():
            if question.identifier in questions_with_mdx_payload and question.source_package_path_inferred:
                question.h5p_metadata = None
                question.h5p_content = None
                question.source_package_path = ""
                question.source_package_path_inferred = False
            self._validate_question_runner(mdx_path, question)

        def strip_question_fence(match: re.Match[str]) -> str:
            spec = match.group("spec").strip()
            spec_parts = spec.split()
            if len(spec_parts) >= 2 and spec_parts[1].startswith("question:"):
                return ""
            return match.group(0)

        rendered_source = self._fence_re.sub(strip_question_fence, rendered_source)

        ordered_questions = sorted(questions.values(), key=lambda question: question_positions[question.identifier])
        return source, ordered_questions, rendered_source

    def _validate_question_runner(self, mdx_path: Path, question: PythonQuestionBlock) -> None:
        source = "\n".join(
            [
                question.starter_code,
                question.solution_code,
                question.pre_code,
                question.post_code,
                *[source_file.code for source_file in question.source_files],
            ]
        )
        question.packages = ensure_miniworlds_packages(question.packages, source=source)
        validate_graphics_runner(
            runner=question.runner,
            source=source,
            location=f"{mdx_path.as_posix()}#{question.identifier}",
        )
