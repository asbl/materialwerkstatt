from __future__ import annotations

# Eingebaute Designs: neutrale Gestaltungen ohne Fremdmarken. Markenbezogene oder sonst
# nicht freigegebene Designs liegen im privaten Ordner (siehe material_core.template_roots)
# und erweitern die Hintergruende ueber `material_core.private_hooks`.
from material_core.private_hooks import hook


def writing_slide_background(design: dict) -> str:
    """Quiet graph paper and a single styled header for new slide designs."""
    from html import escape

    grid = "".join(
        f'<path d="M{x} 0V900"/>' for x in range(0, 1601, 40)
    ) + "".join(f'<path d="M0 {y}H1600"/>' for y in range(0, 901, 40))
    marks = hook("writing_marks", design, default="")
    primary = escape(design["primary"], quote=True)
    header = hook("writing_header", design, default=None)
    if header is None:
        header = f'<rect x="32" y="32" width="1536" height="120" fill="{primary}"/>'
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">'
        '<rect width="1600" height="900" fill="#ffffff"/>'
        f'<g fill="none" stroke="#e9edf2" stroke-width="1">{grid}</g>'
        f'{header}'
        f'<g font-family="DejaVu Sans Mono, monospace" font-weight="bold" font-size="88">{marks}</g>'
        '</svg>'
    )



def slide_background(design: dict) -> str:
    if design.get("writing_grid"):
        return writing_slide_background(design)
    primary = design["primary"]
    accent = design["accent"]
    ink = design["ink"]
    paper = design["paper"]
    parts = []

    def rectangle(left, top, width, height, fill="white", stroke=primary, thickness=3, radius=0):
        parts.append(f'<rect x="{left}" y="{top}" width="{width}" height="{height}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{thickness}"/>')

    def path(points, stroke=primary, thickness=3, fill="none", extra=""):
        parts.append(f'<path d="{points}" fill="{fill}" stroke="{stroke}" stroke-width="{thickness}" {extra}/>')

    def circle(left, top, radius, fill, stroke="none", thickness=2):
        parts.append(f'<circle cx="{left}" cy="{top}" r="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{thickness}"/>')

    identity = design["id"]
    if hook("slide_background_parts", design, rectangle, path, circle, parts, default=False):
        pass
    elif identity == "anime":
        for left in (12, 1580):
            for top in range(212, 800, 22):
                circle(left, top, 2, primary)
        path("M40 40H1520L1576 160H40Z", ink, 0, ink)
        path("M24 24H1510L1566 148H24Z", ink, 5, "white")
        path("M24 24H1390L1368 40H24Z", primary, 0, primary)
        path("M36 190 1554 174 1572 820 20 832Z", ink, 0, ink)
        path("M24 174 1538 166 1556 804 36 816Z", ink, 5, "white")
        path("M1420 832 1568 824 1544 882 1400 882Z", ink, 4, accent)
        path("M32 840H650L624 884H32Z", ink, 3, "white")
        for offset in range(0, 108, 18):
            path(f"M{1258 + offset} 840l-22 40", primary, 4)
        for top in (52, 76, 100, 124):
            path(f"M4 {top + 12}L20 {top}", ink, 3)
        for top in (242, 350, 458, 566, 674):
            path(f"M1566 {top}l24 -30M1568 {top + 18}l24 -30", primary, 3)
    elif identity in {"foerdermaterial", "retro"}:
        rectangle(40, 40, 1536, 120, ink, ink, 0)
        rectangle(32, 32, 1536, 120, accent, ink, 3)
        rectangle(40, 184, 1536, 644, ink, ink, 0)
        rectangle(32, 176, 1536, 644, "white", primary, 4)
        if identity == "retro":
            rectangle(32, 32, 1536, 12, primary, primary, 0)
            for left in range(24, 1580, 32):
                rectangle(left, 832, 16, 8, accent, accent, 0)
            path("M16 200v584M1584 200v584", primary, 4, extra='stroke-dasharray="8 12"')
        else:
            rectangle(32, 32, 12, 120, primary, primary, 0)
            rectangle(32, 176, 12, 644, accent, accent, 0)
            for left in (24, 1560):
                for top in (24, 808):
                    rectangle(left, top, 16, 16, primary, primary, 0)
            path("M40 840H1560", primary, 4)
    elif identity == "fussball":
        rectangle(16, 16, 1568, 816, primary, primary, 0, 8)
        for left in range(16, 1580, 196):
            rectangle(left, 16, 98, 816, accent, accent, 0)
        rectangle(32, 32, 1536, 120, "white", ink, 3, 4)
        rectangle(32, 176, 1536, 644, "white", ink, 3, 4)
        rectangle(8, 8, 1584, 824, "none", "white", 2)
        path("M800 834v54M40 842H1560", primary, 2)
        circle(800, 860, 24, "none", primary)
        path("M32 846h110v40H32M1568 846h-110v40h110", primary, 2)
        rectangle(24, 846, 630, 38, paper, paper, 0)
    elif identity == "reiten":
        rectangle(24, 24, 1552, 804, "none", primary, 2, 18)
        rectangle(32, 32, 1536, 120, "white", accent, 3, 14)
        rectangle(32, 176, 1536, 644, "white", accent, 3, 14)
        path("M44 44H1556V140H44ZM44 188H1556V808H44Z", primary, 1, extra='stroke-dasharray="6 7"')
        path("M40 842H1560M40 882H1560", primary, 2)
        for left in (712, 768, 824, 880):
            path(f"M{left} 850h32m-32 22h32", accent, 4)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">'
        + f'<rect width="1600" height="900" fill="{paper}"/>'
        + "".join(parts)
        + "</svg>"
    )
