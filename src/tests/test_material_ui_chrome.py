"""Oberflaechenrahmen: Kopfzeile, Befehlspalette, Rail, Frontmatter-Faltung, Gestaltungs-Tokens."""
import re
from pathlib import Path

import pytest

from material_ui.app import create_app
from material_ui.config import AppConfig
from test_material_ui import LiveServer, free_port, host_css, sync_playwright, write_qmd

STATIC = Path(__file__).resolve().parents[1] / "material_ui" / "static"
LONG_FRONTMATTER = (
    "---\ntitle: Langes Blatt\nlang: de\nformat:\n  pdf:\n    toc: false\n    papersize: a4\n"
    "header-includes:\n- \\usepackage{tikz}\n---\n\nInhaltstext\n"
)


def _open(playwright, url, tmp_viewport=(1400, 900), path="unterricht/blatt.qmd"):
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": tmp_viewport[0], "height": tmp_viewport[1]})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(
        'localStorage.setItem("material-ui:auto-render", "false"); localStorage.setItem("material-ui:active-view", "folder")'
    )
    page.goto(f"{url}/?path={path}", wait_until="networkidle")
    return browser, page, errors


def test_host_stylesheets_are_split_in_cascade_order_and_use_tokens():
    template = (STATIC.parent / "templates" / "index.html").read_text(encoding="utf-8")
    names = re.findall(r"asset_url\('(app[\w-]*\.css)'\)", template)
    assert names[0] == "app.css" and len(names) == len(set(names)) >= 9
    for name in names:
        assert (STATIC / name).is_file(), name
    # Kein Stylesheet vergroessert sich wieder zur Sammeldatei.
    assert max(len((STATIC / name).read_text(encoding="utf-8").splitlines()) for name in names) < 700

    css = host_css()
    for token in ("--space-2:", "--radius-md:", "--shadow-2:", "--focus-ring:", "--bar-height:"):
        assert token in css
    # Radien und Fokusring kommen aus den Tokens, nicht aus Einzelwerten.
    assert not re.search(r"border-radius:\s*(?:[2-9]|1[0-9]|20)px\s*[;}]", css)
    assert "outline: 2px solid var(--accent);\n  outline-offset: 2px;" not in css


def test_header_has_single_row_controls_and_no_separate_view_strip():
    template = (STATIC.parent / "templates" / "index.html").read_text(encoding="utf-8")
    assert "workspace-view-controls" not in template
    header = template[template.index('<header class="app-header">'):template.index("</header>")]
    for element in ("view-switch", 'id="newDoc"', 'id="newMenuToggle"', 'id="toggleFocusMode"', 'id="themeToggle"', 'id="workspaceNavigation"'):
        assert element in header, element


def test_browser_header_menus_view_switch_and_command_palette(tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    write_qmd(tmp_path / "unterricht" / "blatt.qmd", "---\ntitle: Blatt\n---\n\nText\n")
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser, page, errors = _open(pw, url)
            from playwright.sync_api import expect

            # Ansichtsumschalter sitzt in der Kopfzeile und schaltet die Spalten um.
            expect(page.locator(".app-header .view-switch")).to_be_visible()
            expect(page.locator("#workspace")).to_have_attribute("data-view", "split")
            page.locator('[data-workspace-view="edit"]').click()
            expect(page.locator(".preview-pane")).to_be_hidden()
            page.locator('[data-workspace-view="split"]').click()
            expect(page.locator(".preview-pane")).to_be_visible()

            # Neu-Menue: Import ist ein Nebenweg, "Neu" bleibt ein Klick.
            expect(page.locator("#newMenuPanel")).to_be_hidden()
            if page.locator("#newMenuToggle").is_visible():
                page.locator("#newMenuToggle").click()
                expect(page.locator("#newMenuPanel")).to_be_visible()
                page.keyboard.press("Escape")
                expect(page.locator("#newMenuPanel")).to_be_hidden()

            # Farbschema und Optionen liegen im Einstellungsmenue.
            page.locator("#headerMenuToggle").click()
            expect(page.locator("#headerMenuPanel #themeToggle")).to_be_visible()
            page.keyboard.press("Escape")

            # Strg+K fokussiert die Suche, ">" schaltet auf Befehle.
            page.keyboard.press("Control+k")
            expect(page.locator("#documentSearch")).to_be_focused()
            page.locator("#documentSearch").fill(">dunkel")
            expect(page.locator("#documentResults .command-option")).to_have_count(1)
            expect(page.locator("#searchOverlay")).to_have_class(re.compile("command-mode"))
            expect(page.locator(".facet-filters")).to_be_hidden()
            page.keyboard.press("Enter")
            assert page.evaluate("document.documentElement.dataset.theme") == "dark"
            expect(page.locator("#searchOverlay")).to_be_hidden()

            # Befehle ohne Treffer sagen das, Material wird davon nicht beeinflusst.
            page.locator("#documentSearch").fill(">gibtesnicht")
            expect(page.locator("#documentResults")).to_contain_text("Kein Befehl gefunden")
            page.locator("#documentSearch").fill("blatt")
            expect(page.locator("#documentResults .document-option").first).to_contain_text("Blatt")
            assert not errors
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


def test_browser_rail_has_labels_and_index_title_follows_view(tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    write_qmd(tmp_path / "unterricht" / "blatt.qmd", "---\ntitle: Blatt\n---\n\nText\n")
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser, page, errors = _open(pw, url)
            from playwright.sync_api import expect

            expect(page.locator("#folderViewButton .rail-label")).to_have_text("Ordner")
            expect(page.locator("#tagTreeViewButton .rail-label")).to_have_text("Material")
            # Jede sichtbare Beschriftung passt in den Knopf (kein Abschneiden).
            overflow = page.evaluate(
                "[...document.querySelectorAll('.index-rail-button .rail-label')]"
                ".filter(el => el.scrollWidth > el.clientWidth + 1).map(el => el.textContent)"
            )
            assert overflow == []
            expect(page.locator("#indexTitle")).to_have_text("Ordner und Dateien")
            page.locator("#tagTreeViewButton").click()
            expect(page.locator("#indexTitle")).to_have_text("Material finden")
            assert not errors
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


def test_browser_long_frontmatter_is_folded_and_short_stays_open(tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    write_qmd(tmp_path / "unterricht" / "lang.qmd", LONG_FRONTMATTER)
    write_qmd(tmp_path / "unterricht" / "kurz.qmd", "---\ntitle: Kurz\n---\n\nInhaltstext\n")
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser, page, errors = _open(pw, url, path="unterricht/lang.qmd")
            from playwright.sync_api import expect

            expect(page.locator(".qmd-fold-placeholder")).to_contain_text("Metadaten · Langes Blatt")
            expect(page.locator(".cm-content")).to_contain_text("Inhaltstext")
            expect(page.locator(".cm-content")).not_to_contain_text("papersize")
            page.locator(".qmd-fold-placeholder").click()
            expect(page.locator(".cm-content")).to_contain_text("papersize")

            page.goto(f"{url}/?path=unterricht/kurz.qmd", wait_until="networkidle")
            expect(page.locator(".cm-content")).to_contain_text("title: Kurz")
            expect(page.locator(".qmd-fold-placeholder")).to_have_count(0)
            assert not errors
            browser.close()
    finally:
        app.extensions["material_runtime"].close()


def test_browser_narrow_navigation_drawer_closes_on_outside_click(tmp_path):
    if sync_playwright is None:
        pytest.skip("Playwright fehlt")
    write_qmd(tmp_path / "unterricht" / "blatt.qmd", "---\ntitle: Blatt\n---\n\nText\n")
    app = create_app(config=AppConfig(tmp_path))
    try:
        with LiveServer(app, free_port()) as url, sync_playwright() as pw:
            browser, page, errors = _open(pw, url, tmp_viewport=(390, 844))
            from playwright.sync_api import expect

            # Telefonbreite: nichts laeuft horizontal aus dem Fenster.
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            expect(page.locator("#workspaceNavigation")).to_be_visible()
            page.locator("#workspaceNavigation").click()
            expect(page.locator(".workspace-index")).to_be_visible()
            page.locator("#workspace").click(position={"x": 370, "y": 20})
            expect(page.locator(".workspace-index")).to_be_hidden()
            assert not errors
            browser.close()
    finally:
        app.extensions["material_runtime"].close()
