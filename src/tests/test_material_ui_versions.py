from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from material_ui.plugins.versions import (
    VersionError,
    parse_version,
    satisfies,
    satisfies_all,
    select_best,
    validate_constraint,
)


def test_parse_version_accepts_semver_and_ignores_build_metadata():
    version = parse_version("1.2.3")
    assert (version.major, version.minor, version.patch) == (1, 2, 3)
    assert not version.is_prerelease
    assert parse_version("1.0.0+build.5") == parse_version("1.0.0")
    pre = parse_version("1.0.0-beta.1")
    assert pre.is_prerelease
    assert pre.prerelease == ("beta", 1)


def test_parse_version_rejects_invalid():
    for text in ("", "1", "1.2", "1.2.3.4", "v1.2.3", "1.2.x", "01.2.3", "1.2.3-"):
        with pytest.raises(VersionError):
            parse_version(text)


def test_version_ordering_follows_semver():
    ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
               "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.2.0", "2.0.0"]
    versions = [parse_version(text) for text in ordered]
    assert versions == sorted(versions)
    assert parse_version("1.0.0") > parse_version("1.0.0-rc.1")
    assert parse_version("1.0.0-beta.2") < parse_version("1.0.0-beta.11")  # numerisch, nicht lexikalisch


def test_satisfies_operators():
    v = parse_version("1.2.3")
    assert satisfies(v, "*")
    assert satisfies(v, "")
    assert satisfies(v, ">=1.2.0")
    assert satisfies(v, ">1.2.3") is False
    assert satisfies(v, "<=1.2.3")
    assert satisfies(v, "==1.2.3")
    assert satisfies(v, "!=1.2.4")
    assert satisfies(v, "^1.2.0") and not satisfies(v, "^2.0.0") and not satisfies(v, "^1.3.0")
    assert satisfies(parse_version("1.3.0"), "^1.2.0") and not satisfies(parse_version("2.0.0"), "^1.2.0")
    assert satisfies(parse_version("0.2.9"), "^0.2.3") and not satisfies(parse_version("0.3.0"), "^0.2.3")
    assert satisfies(parse_version("0.0.2"), "^0.0.2") and not satisfies(parse_version("0.0.3"), "^0.0.2")
    assert satisfies(parse_version("1.2.9"), "~1.2.3") and not satisfies(parse_version("1.3.0"), "~1.2.3")
    assert satisfies(parse_version("1.9.0"), "~1") and not satisfies(parse_version("2.0.0"), "~1")


def test_satisfies_partial_exact_and_multiple_constraints():
    assert satisfies(parse_version("1.2.9"), "1.2") and not satisfies(parse_version("1.3.0"), "1.2")
    assert satisfies(parse_version("1.9.0"), "1") and not satisfies(parse_version("2.0.0"), "1")
    assert satisfies(parse_version("1.5.0"), ">=1.0.0,<2.0.0")
    assert not satisfies(parse_version("2.0.0"), ">=1.0.0,<2.0.0")
    assert satisfies_all(parse_version("1.5.0"), ["^1.0.0", "!=1.5.1"])
    assert not satisfies_all(parse_version("1.5.1"), ["^1.0.0", "!=1.5.1"])


def test_prereleases_only_when_constraint_requests_them():
    beta = parse_version("2.0.0-beta")
    assert not satisfies(beta, "*")
    assert not satisfies(beta, "^1.0.0")
    assert not satisfies(beta, ">=1.0.0")
    assert satisfies(beta, ">=2.0.0-alpha")
    assert satisfies(beta, "==2.0.0-beta")
    assert satisfies(beta, "2.0.0-beta")


def test_select_best_picks_highest_matching():
    versions = [parse_version(text) for text in ("1.0.0", "1.2.0", "1.2.3", "2.0.0-beta", "2.0.0")]
    assert select_best(versions, "^1.0.0") == parse_version("1.2.3")
    assert select_best(versions, "*") == parse_version("2.0.0")          # Prerelease ohne explizite Anforderung ignoriert
    assert select_best(versions, ">=2.0.0-alpha") == parse_version("2.0.0")
    assert select_best(versions, "^3.0.0") is None


def test_validate_constraint_rejects_garbage():
    for text in ("abc", ">=1.2", ">= ", "^", "1.2.3.4", ">=1.2.x"):
        with pytest.raises(VersionError):
            validate_constraint(text)
    for text in ("*", "", ">=1.2.3", "^1.2", "~1.2.3", "1.2", "1.2.3-beta.1", ">=1.0.0,<2.0.0"):
        validate_constraint(text)
