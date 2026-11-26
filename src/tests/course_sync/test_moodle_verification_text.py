import pytest

from course_sync.moodle_workflows import _normalize_verification_text


@pytest.mark.parametrize("signal, rendered", [
    ("Schreibe die Klasse  Mitarbeiter  als Unterklasse von  Person .",
     "Schreibe die Klasse Mitarbeiter als Unterklasse von Person."),
    ("Schreibe drei Unterklassen von  Charakter :",
     "Schreibe drei Unterklassen von Charakter:"),
    ("### Der Konstruktor `__init__`", "Der Konstruktor __init__"),
    ("Test: Konstruktor mit `super()`", "Test: Konstruktor mit super()"),
    ("Eine lange\n   Aufgabenstellung", "Eine lange Aufgabenstellung"),
])
def test_verification_matches_formatted_source_to_rendered_text(signal, rendered):
    assert _normalize_verification_text(signal) == _normalize_verification_text(rendered)


def test_verification_keeps_different_content_distinct():
    assert _normalize_verification_text("Schreibe die Klasse Mitarbeiter.") not in (
        _normalize_verification_text("Schreibe die Klasse Person.")
    )
