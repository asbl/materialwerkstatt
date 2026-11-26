from __future__ import annotations

import operator
import re
from dataclasses import dataclass
from functools import total_ordering


class VersionError(ValueError):
    """Ungültige Version oder Versionsbedingung."""


# Offizielles Semver-2.0.0-Muster (Build-Metadaten erlaubt, für Vergleiche ignoriert).
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?$"
)

# Teilversionen für ^/~ und exakte Partial-Angaben: 1, 1.2, 1.2.3 (optional mit Prärelease).
_PARTIAL_RE = re.compile(r"^(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:\.(0|[1-9]\d*))?(?:-([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$")

# Eine Bedingung: optionaler Operator + Version/Partial/"*".
_CONSTRAINT_PART_RE = re.compile(r"^(>=|<=|==|!=|>|<|\^|~)?\s*(\*|[0-9][0-9a-zA-Z.\-+]*)$")

_COMPARATORS = {
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
}


@total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple = ()   # int- oder str-Kennungen; leere Tupel = Release
    raw: str = ""

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def _key(self):
        if not self.prerelease:
            pre = ((1,),)  # Release sortiert nach jeder Prärelease derselben Basisversion.
        else:
            pre = ((0,), tuple((0, part) if isinstance(part, int) else (1, part) for part in self.prerelease))
        return (self.major, self.minor, self.patch, pre)

    def __eq__(self, other) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __str__(self) -> str:
        return self.raw


def _parse_prerelease(text: str | None) -> tuple:
    if not text:
        return ()
    return tuple(int(part) if part.isdigit() else part for part in text.split("."))


def parse_version(text: str) -> Version:
    """Parst eine vollständige Semver-Version (x.y.z, optional -prerelease und +build)."""
    if not isinstance(text, str):
        raise VersionError(f"Version muss eine Zeichenkette sein: {text!r}")
    stripped = text.strip()
    match = _SEMVER_RE.match(stripped)
    if not match:
        raise VersionError(f"Ungültige Semver-Version (x.y.z erwartet): {text!r}")
    major, minor, patch, pre = match.groups()
    return Version(int(major), int(minor), int(patch), _parse_prerelease(pre), stripped)


def _parse_partial(text: str) -> tuple[int, int | None, int | None, tuple, bool]:
    """Zerlegt 1 / 1.2 / 1.2.3(-pre) in (major, minor, patch, prerelease, full)."""
    match = _PARTIAL_RE.match(text)
    if not match:
        raise VersionError(f"Ungültige Version: {text!r}")
    major, minor, patch, pre = match.groups()
    full = minor is not None and patch is not None
    if pre and not full:
        raise VersionError(f"Prärelease nur bei vollständiger Version erlaubt: {text!r}")
    return int(major), int(minor) if minor is not None else None, int(patch) if patch is not None else None, _parse_prerelease(pre), full


def _caret_upper(major: int, minor: int | None, patch: int | None) -> Version:
    if major > 0:
        return Version(major + 1, 0, 0)
    if minor is None:
        return Version(1, 0, 0)
    if minor > 0:
        return Version(0, minor + 1, 0)
    if patch is None:
        return Version(0, 1, 0)
    return Version(0, 0, patch + 1)


def _tilde_upper(major: int, minor: int | None) -> Version:
    if minor is None:
        return Version(major + 1, 0, 0)
    return Version(major, minor + 1, 0)


def _expand_part(op: str, text: str) -> list[tuple[str, Version]]:
    """Wandelt einen Bedingungsteil in Vergleichstests (op, Version) um."""
    text = text.strip()
    if text == "*":
        return []
    major, minor, patch, pre, full = _parse_partial(text)
    if op in _COMPARATORS and not full:
        raise VersionError(f"Operator {op!r} benötigt eine vollständige Version (x.y.z): {text!r}")
    lower = Version(major, minor or 0, patch or 0, pre, text)
    if op in ("", "==", "*"):
        if full:
            return [("==", lower)]
        # Exakte Partial-Angabe wie 1.2: 1.2.x
        return [(">=", lower), ("<", _tilde_upper(major, minor))]
    if op in (">=", "<=", ">", "<", "==", "!="):
        return [(op, lower)]
    if op == "^":
        return [(">=", lower), ("<", _caret_upper(major, minor, patch))]
    if op == "~":
        return [(">=", lower), ("<", _tilde_upper(major, minor))]
    raise VersionError(f"Unbekannter Operator: {op!r}")


def parse_constraint_list(text: str) -> list[tuple[str, Version]]:
    """Parst eine Bedingung wie '>=1.2.0,<2.0.0' in Vergleichstests; '*' bzw. leer = keine Einschränkung."""
    if not isinstance(text, str):
        raise VersionError(f"Versionsbedingung muss eine Zeichenkette sein: {text!r}")
    tests: list[tuple[str, Version]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        match = _CONSTRAINT_PART_RE.match(part)
        if not match:
            raise VersionError(f"Ungültige Versionsbedingung: {part!r}")
        tests.extend(_expand_part(match.group(1) or "", match.group(2)))
    return tests


def validate_constraint(text: str) -> None:
    """Wirft VersionError, wenn die Bedingung nicht parsebar ist (für Manifest-Prüfung)."""
    parse_constraint_list(text)


def _mentions_prerelease(text: str) -> bool:
    return any(version.is_prerelease for _, version in parse_constraint_list(text))


def satisfies(version: Version, constraint: str) -> bool:
    """Prüft eine Version gegen eine Bedingung; Präreleases nur bei expliziter Prärelease-Bedingung."""
    tests = parse_constraint_list(constraint)
    if version.is_prerelease and not _mentions_prerelease(constraint):
        return False
    return all(_COMPARATORS[op](version, ref) for op, ref in tests)


def satisfies_all(version: Version, constraints) -> bool:
    """Alle Bedingungen (einzeln oder kommagetrennt) müssen erfüllt sein."""
    if isinstance(constraints, str):
        constraints = [constraints]
    return all(satisfies(version, item) for item in constraints)


def select_best(versions, constraint: str) -> Version | None:
    """Höchste Version, die die Bedingung erfüllt (Préreleases nur bei expliziter Anforderung)."""
    candidates = [version for version in versions if satisfies(version, constraint)]
    return max(candidates) if candidates else None
