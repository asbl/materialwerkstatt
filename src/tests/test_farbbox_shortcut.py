import pytest


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("farbe,latex_color", [
    ("blau", "examprimary"), ("tuerkis", "teal!70!black"),
    ("orange", "orange!85!black"), ("lila", "purple!70!black"),
])
def test_farbbox_colors(render_exam_lua, target, farbe, latex_color):
    result = render_exam_lua(f'::: {{.box farbe="{farbe}"}}\nText\n:::', target)
    assert result.returncode == 0, result.stderr
    if target == "latex":
        assert f"\\begin{{farbbox}}{{{latex_color}}}" in result.stdout
        assert "\\end{farbbox}" in result.stdout
    else:
        assert "#farbbox(rgb(" in result.stdout
    assert "Text" in result.stdout


def test_farbbox_unknown_color_errors(render_exam_lua):
    result = render_exam_lua('::: {.box farbe="pink"}\nText\n:::', "typst")
    assert result.returncode != 0
    assert "farbe muss blau, tuerkis, orange oder lila sein" in result.stderr


def test_farbbox_default_color_is_blau(render_exam_lua):
    result = render_exam_lua("::: {.box}\nText\n:::", "latex")
    assert result.returncode == 0, result.stderr
    assert "\\begin{farbbox}{examprimary}" in result.stdout
