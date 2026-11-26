"""Zuordnung der Aktivitaeten eines Kurses zu seinen Kapiteln.

Gemeinsame Grundlage fuer den Kursindex im Editor und die Sync-Uebersicht, damit beide
dieselbe Kapitelzuordnung zeigen.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

OTHER_ACTIVITIES_TITLE = "Weitere Aktivitäten"


def group_questions_by_chapter(
    chapters: Iterable[dict[str, Any]],
    questions: Iterable[Any],
    chapter_question_ids: Callable[[str], Iterable[str]] | None = None,
) -> list[dict[str, Any]]:
    """Haengt jede Aktivitaet an ihr Kapitel (Schluessel ``questions``).

    Eine Aktivitaet kennt nur den Unterordner ihres Kapitels (``h5p_subdir``). Teilen sich
    mehrere Kapitel einen Unterordner (``k2/a`` und ``k2/b``), entscheidet
    ``chapter_question_ids(kapitel_slug)`` anhand der Kapiteldatei; ohne Treffer gewinnt das
    erste Kapitel, damit keine Aktivitaet doppelt oder gar nicht erscheint. Aktivitaeten ohne
    passendes Kapitel landen in einem Sammelkapitel am Ende.
    """
    grouped = [{**chapter, "questions": []} for chapter in chapters]
    by_subdir: dict[str, list[dict[str, Any]]] = {}
    for chapter in grouped:
        by_subdir.setdefault(str(chapter["slug"]).split("/")[0], []).append(chapter)
    id_cache: dict[str, set[str]] = {}

    def owns(chapter: dict[str, Any], identifier: str) -> bool:
        slug = str(chapter["slug"])
        if slug not in id_cache:
            id_cache[slug] = set(chapter_question_ids(slug)) if chapter_question_ids else set()
        return identifier in id_cache[slug]

    for question in questions:
        candidates = by_subdir.get(question.h5p_subdir)
        if candidates is None:
            other = {"slug": question.h5p_subdir, "title": OTHER_ACTIVITIES_TITLE, "questions": []}
            grouped.append(other)
            candidates = by_subdir[question.h5p_subdir] = [other]
        chapter = candidates[0]
        if len(candidates) > 1:
            chapter = next((item for item in candidates if owns(item, question.identifier)), chapter)
        chapter["questions"].append(question)
    return grouped
