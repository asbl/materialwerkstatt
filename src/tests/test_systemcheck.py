from __future__ import annotations

from material_core import systemcheck


def _fake(key, level, ok, packages=None, **extra):
    return {"key": key, "level": level, "ok": ok, "found": "x" if ok else None,
            "purpose": key, "packages": packages or {}, **extra}


def test_plan_sammelt_fehlendes_je_paketmanager():
    results = [
        _fake("git", "basis", False, {"apt": ["git"], "pacman": ["git"]}),
        _fake("quarto", "bauen", False, {}, aur=["quarto-cli-bin"], hint="url"),
        _fake("typst", "empfohlen", True, {"pacman": ["typst"]}),
    ]
    plan = systemcheck.install_plan(results, "pacman")
    assert plan["packages"] == ["git"]
    assert plan["aur"] == ["quarto-cli-bin"]
    assert systemcheck.install_command(plan) == "sudo pacman -S --needed git"
    apt = systemcheck.install_plan(results, "apt")
    assert apt["manual"] == [("quarto", "url")]


def test_optionales_nur_mit_stufe():
    results = [_fake("xdotool", "optional", False, {"apt": ["xdotool"]})]
    assert systemcheck.install_command(systemcheck.install_plan(results, "apt", ("basis", "bauen"))) == ""
    assert systemcheck.install_command(systemcheck.install_plan(results, "apt")) == "sudo apt install xdotool"


def test_jedes_werkzeug_hat_stufe_und_weg_zur_installation():
    for tool in systemcheck.TOOLS:
        assert tool["level"] in systemcheck.LEVELS
        assert tool["packages"] or tool.get("hint") or tool.get("aur"), tool["key"]


def test_cli_laeuft_ohne_projektabhaengigkeiten(capsys):
    code = systemcheck.main(["--json", "--manager", "apt"])
    assert code in (0, 1)
    assert '"tools"' in capsys.readouterr().out
