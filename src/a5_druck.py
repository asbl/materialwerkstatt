"""Place each landscape A5 worksheet twice on a portrait A4 print sheet."""
from pathlib import Path


def zwei_auf_eins(source: Path, target: Path) -> Path:
    import pymupdf

    source, target = source.resolve(), target.resolve()
    if source == target:
        raise ValueError("Quelldatei und Druckdatei müssen verschieden sein.")
    with pymupdf.open(source) as document, pymupdf.open() as output:
        if not len(document):
            raise ValueError("Das PDF enthält keine Seiten.")
        for page in document:
            width_mm = page.rect.width * 25.4 / 72
            height_mm = page.rect.height * 25.4 / 72
            if abs(width_mm - 210) > 1 or abs(height_mm - 148) > 1:
                raise ValueError("Erwartet werden A5-Seiten im Querformat (210 × 148 mm).")
        for page in document:
            sheet = output.new_page(width=210 * 72 / 25.4, height=297 * 72 / 25.4)
            half = sheet.rect.height / 2
            for top in (0, half):
                # A5 height is 148 mm; center it within the 148.5 mm half.
                y = top + (half - page.rect.height) / 2
                area = pymupdf.Rect(0, y, sheet.rect.width, y + page.rect.height)
                sheet.show_pdf_page(area, document, page.number)
        target.parent.mkdir(parents=True, exist_ok=True)
        output.save(target, garbage=4, deflate=True)
    return target
