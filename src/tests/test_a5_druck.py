from pathlib import Path

import pymupdf
import pytest

from a5_druck import zwei_auf_eins


def test_a5_pages_are_duplicated_on_a4_without_scaling(tmp_path: Path):
    source = tmp_path / 'a5.pdf'
    target = tmp_path / 'a4.pdf'
    with pymupdf.open() as document:
        for text in ('Aufgabe A', 'Aufgabe B'):
            page = document.new_page(width=210 * 72 / 25.4, height=148 * 72 / 25.4)
            page.insert_text((30, 30), text, fontsize=12)
        document.save(source)
    zwei_auf_eins(source, target)
    with pymupdf.open(target) as result:
        assert len(result) == 2
        for page, label in zip(result, ('Aufgabe A', 'Aufgabe B')):
            assert page.rect.width * 25.4 / 72 == pytest.approx(210)
            assert page.rect.height * 25.4 / 72 == pytest.approx(297)
            assert page.get_text().count(label) == 2
            spans = [span for block in page.get_text('dict')['blocks']
                     if 'lines' in block for line in block['lines'] for span in line['spans']]
            assert all(span['size'] == pytest.approx(12) for span in spans)


def test_rejects_wrong_paper_size_and_overwriting_source(tmp_path: Path):
    source = tmp_path / 'a4.pdf'
    with pymupdf.open() as document:
        document.new_page()
        document.save(source)
    with pytest.raises(ValueError, match='verschieden'):
        zwei_auf_eins(source, source)
    with pytest.raises(ValueError, match='A5'):
        zwei_auf_eins(source, tmp_path / 'out.pdf')
    assert not (tmp_path / 'out.pdf').exists()
