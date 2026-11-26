import pytest


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("name", ["Platz", "platz"])
@pytest.mark.parametrize("distance,normalized", [
    ("1cm", "1cm"), ("1,5cm", "1.5cm"), ("15 mm", "15mm"), ("12pt", "12pt"),
])
def test_platz_width_inside_text(render_exam_lua, target, name, distance, normalized):
    result = render_exam_lua(f"Vorher [{name} {distance}], danach [{name} 2cm].", target)
    assert result.returncode == 0, result.stderr
    expected = (f"\\platz[{normalized}]" if target == "latex"
                else f"#platz(width: {normalized})")
    assert expected in result.stdout
    assert ", danach" in result.stdout
    assert result.stdout.rstrip().endswith(".")
    assert result.stdout.index("Vorher") < result.stdout.index(expected) < result.stdout.index("danach")
    assert ("\\platz[2cm]" if target == "latex" else "#platz(width: 2cm)") in result.stdout
    assert f"[{name}" not in result.stdout


@pytest.mark.parametrize("target", ["typst", "latex"])
@pytest.mark.parametrize("name", ["Platz", "platz"])
def test_platz_without_width_uses_default(render_exam_lua, target, name):
    result = render_exam_lua(f"[{name}]", target)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("\\platz" if target == "latex" else "#platz()")


@pytest.mark.parametrize("distance", ["-1cm", "0cm", "abc", "1", "1.2.3cm", "1in"])
def test_invalid_platz_width_produces_helpful_error(render_exam_lua, distance):
    result = render_exam_lua(f"[Platz {distance}]", "typst")
    assert result.returncode != 0
    assert "Platz: Bitte eine positive Breite" in result.stderr
