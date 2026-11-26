"""Gemeinsame Interaktionen mit der kompakten Present-Palette."""


def click_toolbar_title(page, title):
    target = page.get_by_title(title)
    if not target.is_visible():
        page.get_by_role("button", name="Stiftfarbe" if title.startswith("Farbe ") else "Weitere Werkzeuge", exact=True).click()
    target.click()


def mock_material_protocol(page):
    """Der statische Testserver liefert denselben Vertrag wie die Material-UI."""
    from pathlib import Path
    contract = (Path(__file__).resolve().parents[2] / "material_ui" / "static" / "api-contract.json").read_text()
    page.route("**/static/api-contract.json", lambda route: route.fulfill(body=contract, content_type="application/json"))
    page.route("**/api/protocol", lambda route: route.fulfill(body=contract, content_type="application/json"))
