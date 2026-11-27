from __future__ import annotations

import re


DEFAULT_PYTHON_RUNNER = "skulpt"
MINIWORLDS_PYTHON_RUNNER = "pyodide"
MINIWORLDS_PACKAGE = "miniworlds"
MINIWORLDS_ROBOT_PACKAGE = "miniworlds-robot"
MINIWORLDS_TURTLE_PACKAGE = "miniworlds-turtle"
MINIWORLDS_EXTRA_PACKAGES: tuple[str, ...] = ()
GRAPHICS_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+(?:p5|turtle)\b", re.MULTILINE)
P5_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+p5\b", re.MULTILINE)
MINIWORLDS_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(miniworlds(?:_robot|_turtle)?)\b", re.MULTILINE
)
MINIWORLDS_IMPORT_PACKAGES = {
    "miniworlds": MINIWORLDS_PACKAGE,
    "miniworlds_robot": MINIWORLDS_ROBOT_PACKAGE,
    "miniworlds_turtle": MINIWORLDS_TURTLE_PACKAGE,
}
MINIWORLDS_PACKAGES = frozenset(MINIWORLDS_IMPORT_PACKAGES.values())


def _package_name(pkg: str | dict[str, object]) -> str:
    """Return the normalised package name from a string or H5P package-object."""
    if isinstance(pkg, dict):
        return str(pkg.get("package") or pkg.get("name") or "").strip().lower()
    return str(pkg).strip().lower()


def contains_p5_or_turtle_import(source: str) -> bool:
    return bool(GRAPHICS_IMPORT_RE.search(source))


def contains_miniworlds_import(source: str) -> bool:
    return bool(MINIWORLDS_IMPORT_RE.search(source))


def contains_miniworlds_package(packages: list[str | dict[str, object]] | tuple[str | dict[str, object], ...]) -> bool:
    return any(_canonical_package_name(_package_name(p)) in MINIWORLDS_PACKAGES for p in packages)


def _canonical_package_name(name: str) -> str:
    return MINIWORLDS_IMPORT_PACKAGES.get(name.lower(), name)


def _packages_imported_by_source(source: str) -> set[str]:
    return {
        MINIWORLDS_IMPORT_PACKAGES[match.group(1)]
        for match in MINIWORLDS_IMPORT_RE.finditer(source)
    }


def ensure_miniworlds_packages(
    packages: list[str] | tuple[str, ...],
    *,
    source: str = "",
) -> list[str]:
    """Return canonical package names, adding miniworlds where it is required."""
    normalized: list[str] = []
    seen: set[str] = set()
    for package in packages:
        name = _canonical_package_name(str(package).strip())
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        normalized.append(name)
        seen.add(key)

    imported_packages = _packages_imported_by_source(source)
    required_packages = {
        _canonical_package_name(package) for package in normalized
    } | imported_packages
    if not required_packages.intersection(MINIWORLDS_PACKAGES):
        return normalized

    if MINIWORLDS_PACKAGE not in seen:
        normalized.append(MINIWORLDS_PACKAGE)
        seen.add(MINIWORLDS_PACKAGE)
    for package in (MINIWORLDS_ROBOT_PACKAGE, MINIWORLDS_TURTLE_PACKAGE):
        if package in required_packages and package not in seen:
            normalized.append(package)
            seen.add(package)
    for package in MINIWORLDS_EXTRA_PACKAGES:
        if package not in seen:
            normalized.append(package)
            seen.add(package)
    return normalized


def packages_for_h5p_content(
    packages: list[str | dict[str, object]],
) -> list[str]:
    """Return *packages* as unique names for ``pyodideOptions.packages``.

    The PythonQuestion semantics declare a list of selects, so every entry must be a
    plain string. Moodle aborts with "Cannot access offset of type stdClass" when it
    validates an object entry such as ``{"package": "miniworlds", "remote": false}``.
    """
    names = (_canonical_package_name(_package_name(package)) for package in packages)
    return list(dict.fromkeys(name for name in names if name))


def resolve_python_runner(
    runner: object = "",
    *,
    packages: list[str] | tuple[str, ...] = (),
    source: str = "",
) -> str:
    explicit_runner = str(runner or "").strip()
    if explicit_runner:
        return explicit_runner
    if contains_miniworlds_package(packages) or contains_miniworlds_import(source):
        return MINIWORLDS_PYTHON_RUNNER
    return DEFAULT_PYTHON_RUNNER


def validate_graphics_runner(*, runner: str, source: str, location: str) -> None:
    if not contains_p5_or_turtle_import(source):
        return
    if runner.strip() == "skulpt":
        return
    # turtle laeuft ab H5P.PythonQuestion 6.147 zusaetzlich auf Pyodide
    # (tkinter-web-backend mit hinterlegtem turtle-Modul); p5 bleibt auf Skulpt.
    if P5_IMPORT_RE.search(source):
        raise ValueError(
            f"{location}: Inhalte mit p5 muessen pythonRunner: skulpt verwenden "
            f"(gefunden: {runner or 'leer'})."
        )
