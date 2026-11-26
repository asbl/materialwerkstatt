from pathlib import Path
import shutil
import subprocess

import pytest


FILTER = Path(__file__).resolve().parents[1] / "quarto/filters/exam.lua"
pytestmark = pytest.mark.skipif(shutil.which("quarto") is None, reason="Quarto fehlt")


def render(source, target):
    return subprocess.run(
        ["quarto", "pandoc", "--from", "markdown", "--to", target,
         "--lua-filter", str(FILTER)],
        input=source, text=True, capture_output=True, timeout=30,
    )


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("name,default_title", [
    ("Infobox", "Info"),
    ("Warnbox", "Warnung"),
    ("Tippbox", "Tipp"),
])
def test_box_with_title(target, name, default_title):
    result = render(f"[{name}: Wichtiger Hinweis]\n\nText im Kasten\n\n[/{name}]", target)
    assert result.returncode == 0, result.stderr
    begin = (f"\\begin{{{name.lower()}}}{{Wichtiger Hinweis}}" if target == "latex"
             else f"#{name.lower()}(\"Wichtiger Hinweis\")[")
    end = f"\\end{{{name.lower()}}}" if target == "latex" else "]"
    assert begin in result.stdout
    assert "Text im Kasten" in result.stdout
    assert f"[{name}" not in result.stdout
    assert f"[/{name}]" not in result.stdout
    assert result.stdout.index(begin) < result.stdout.index("Text im Kasten")


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("name,default_title", [
    ("Infobox", "Info"),
    ("Warnbox", "Warnung"),
    ("Tippbox", "Tipp"),
])
def test_box_without_title_uses_default(target, name, default_title):
    result = render(f"[{name}]\n\nText im Kasten\n\n[/{name}]", target)
    assert result.returncode == 0, result.stderr
    begin = (f"\\begin{{{name.lower()}}}{{{default_title}}}" if target == "latex"
             else f"#{name.lower()}(\"{default_title}\")[")
    assert begin in result.stdout
    assert f"[{name}]" not in result.stdout
