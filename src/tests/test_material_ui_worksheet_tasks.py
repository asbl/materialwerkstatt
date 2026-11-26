"""Detektor fuer Aufgabenbereiche in Arbeitsblatt-PDFs (Besprechungs-Chips)."""
import pymupdf

from material_ui.worksheet_tasks import detect_tasks


def _page(body_texts=(), width=600, height=800):
    pdf = pymupdf.open()
    page = pdf.new_page(width=width, height=height)
    for x, y, text, size, bold, white in body_texts:
        page.insert_text((x, y), text, fontsize=size,
                         fontname='hebo' if bold else 'helv',
                         color=(1, 1, 1) if white else (0, 0, 0))
    return pdf, page


def test_typst_numbered_headings_split_page_into_regions():
    pdf, page = _page([
        (50, 40, 'Meine Lernmission', 10, False, False),
        (50, 100, '1 · Warm werden', 16, True, False),
        (50, 140, 'Berechne 24 + 18 =', 10.5, False, False),
        (50, 300, '2 · Deine Strategie', 16, True, False),
        (50, 340, 'Erkläre deinen Rechenweg.', 10.5, False, False),
    ])
    tasks = detect_tasks(page)
    assert [task['label'] for task in tasks] == ['1', '2']
    assert tasks[0]['title'] == 'Warm werden'
    first, second = tasks[0]['rect'], tasks[1]['rect']
    assert 0 < first[1] < second[1] < first[3] < second[3] <= 1
    assert second[1] >= first[3] - 0.01  # keine nennenswerte Ueberlappung
    assert all(0 <= value <= 1 for region in (first, second) for value in region)
    pdf.close()


def test_latex_tasknum_white_tiles_are_markers():
    pdf, page = _page([
        (50, 40, 'Verdauung', 10, False, False),
        (50, 100, '1', 11, True, True),
        (60, 100, 'Der Weg der Nahrung.', 11, True, False),
        (50, 220, '2', 11, True, True),
        (60, 220, 'Wer macht was?', 11, True, False),
    ])
    tasks = detect_tasks(page)
    assert [task['label'] for task in tasks] == ['1', '2']
    assert tasks[0]['title'].startswith('Der Weg der Nahrung')
    assert tasks[0]['rect'][1] < tasks[1]['rect'][1]
    pdf.close()


def test_aufgabe_headings_yield_descriptive_labels():
    pdf, page = _page([
        (50, 100, 'Aufgabe 3: Sortieranalyse [8 P.]', 12, True, False),
        (50, 140, 'Beschreibe den Ablauf.', 10, False, False),
    ])
    tasks = detect_tasks(page)
    assert [task['label'] for task in tasks] == ['Aufgabe 3']
    assert tasks[0]['title'].startswith('Sortieranalyse')
    pdf.close()


def test_repeated_labels_get_numbered_suffix():
    pdf, page = _page([
        (50, 100, 'Kopfübung 1 · Aufstieg', 13.7, True, False),
        (50, 200, 'Kopfübung 2 · Blitzebene', 13.7, True, False),
        (50, 500, 'Kopfübung 1 · Aufstieg', 13.7, True, False),
    ])
    assert [task['label'] for task in detect_tasks(page)] == ['Kopfübung 1', 'Kopfübung 2', 'Kopfübung 1 (2)']
    pdf.close()


def test_side_by_side_markers_split_horizontally():
    pdf, page = _page([
        (50, 100, '1 links rechnen', 16, True, False),
        (350, 100, '2 rechts ueben', 16, True, False),
        (50, 400, 'Randnotizen', 10, False, False),
    ])
    tasks = detect_tasks(page)
    assert [task['label'] for task in tasks] == ['1', '2']
    first, second = tasks[0]['rect'], tasks[1]['rect']
    assert first[2] <= second[0]  # Spalte teilt an der Luecken-Mitte
    assert abs(first[1] - second[1]) < 0.02
    pdf.close()


def test_pages_without_markers_stay_empty():
    pdf, page = _page([
        (50, 100, 'Berechne 12 + 34 im Heft.', 10.5, False, False),
        (50, 140, 'Löse anschließend die Zusatzaufgabe 5.', 10.5, False, False),
    ])
    assert detect_tasks(page) == []
    pdf.close()


def test_white_words_and_black_digits_are_not_markers():
    pdf, page = _page([
        (50, 100, 'Tipp', 11, False, True),
        (50, 140, '3', 11, True, False),
        (50, 180, '12 + 34 = ?', 11, False, False),
    ])
    assert detect_tasks(page) == []
    pdf.close()
