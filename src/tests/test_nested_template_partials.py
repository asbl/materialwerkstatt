from pathlib import Path
import subprocess

from material_core.builds import BuildService
from material_core.metadata import read_metadata


def test_nested_partials_respect_local_override_and_terminate_cycles(tmp_path):
    (tmp_path / 'worksheet-retro.typst').write_text('$a.typst()$')
    (tmp_path / 'a.typst').write_text('$missing.typst()$')
    overrides = tmp_path / 'overrides'
    overrides.mkdir()
    (overrides / 'a.typst').write_text('$b.typst()$')
    (overrides / 'b.typst').write_text('$a.typst()$')
    source = tmp_path / 'blatt.qmd'
    text = ('---\nformat:\n  typst:\n    template: worksheet-retro.typst\n'
            'template-partials:\n  - overrides/a.typst\n---\nText\n')
    source.write_text(text)
    result = BuildService(tmp_path, subprocess.run).render_text(source, text)
    partials = read_metadata(result)['template-partials']
    assert partials == ['overrides/a.typst', 'overrides/b.typst']
