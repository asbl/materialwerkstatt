import pytest


@pytest.mark.parametrize('target', ['typst', 'latex'])
@pytest.mark.parametrize('wrapper', ['{}', '::: {.aufgaben}\n\n{}\n\n:::', '::: {.columns}\n::: {.column}\n\n{}\n\n:::\n:::'])
def test_spacing_shortcut_inside_layouts(render_exam_lua, target, wrapper):
    source = wrapper.replace('{}', 'Vorher\n\n[Abstand 2mm]\n\nNachher')
    result = render_exam_lua(source, target)
    assert result.returncode == 0, result.stderr
    assert '[Abstand' not in result.stdout
    expected = '#v(2mm, weak: false)' if target == 'typst' else r'\par\vspace*{2mm}'
    assert expected in result.stdout
    assert result.stdout.index('Vorher') < result.stdout.index(expected) < result.stdout.index('Nachher')


def test_invalid_spacing_inside_layout_reports_error(render_exam_lua):
    result = render_exam_lua('::: {.aufgaben}\n\n[Abstand nope]\n\n:::', 'typst')
    assert result.returncode != 0
    assert 'Abstand: Bitte' in result.stderr
