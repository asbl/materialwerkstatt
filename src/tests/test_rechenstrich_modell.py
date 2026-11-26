def test_basic_rechenstrich_still_renders(render_exam_lua):
    result = render_exam_lua("[Modell rechenstrich | knoten=456,462,532,932 | spruenge=+6,+70,+400]")
    assert result.returncode == 0, result.stderr
    assert "modell-" in result.stdout


def test_farben_wrong_length_errors(render_exam_lua):
    result = render_exam_lua("[Modell rechenstrich | knoten=1,2,3 | spruenge=+1,+1 | farben=rot]")
    assert result.returncode != 0
    assert "farben braucht genau einen Eintrag" in result.stderr


def test_farben_empty_string_is_treated_as_absent(render_exam_lua):
    # farben="" must behave like farben not being given at all (no override),
    # not like a single-entry list -- otherwise it wrongly demands #jumps == 1.
    result = render_exam_lua("[Modell rechenstrich | knoten=1,2,3 | spruenge=+1,+1 | farben=]")
    assert result.returncode == 0, result.stderr


def test_farben_per_jump_override(render_exam_lua, tmp_path):
    media = tmp_path / "media"
    result = render_exam_lua(
        "[Modell rechenstrich | knoten=7043,7045,5047,5045 | spruenge=+2,-1998,-2 | farben=,#b35900,]",
        target="html", extract_media=str(media),
    )
    assert result.returncode == 0, result.stderr
    svgs = list(media.glob("*.svg"))
    assert len(svgs) == 1
    svg = svgs[0].read_text()
    assert svg.count("#b35900") >= 3  # arc, arrowhead, dot for the overridden jump


def test_kommentar_adds_caption_and_height(render_exam_lua, tmp_path):
    media = tmp_path / "media"
    result = render_exam_lua(
        "[Modell rechenstrich | knoten=1,2 | spruenge=+1 | kommentar=1+1 = 2]",
        target="html", extract_media=str(media),
    )
    assert result.returncode == 0, result.stderr
    svg = next(media.glob("*.svg")).read_text()
    assert "1+1 = 2" in svg
    assert 'height="121"' in svg


def test_unknown_nodes_with_question_marks(render_exam_lua):
    result = render_exam_lua("[Modell rechenstrich | knoten=?,?,4215 | spruenge=+2000,+300]")
    assert result.returncode == 0, result.stderr


def test_blank_fill_in_template_with_offen(render_exam_lua):
    result = render_exam_lua("[Modell rechenstrich | knoten=2486,,,, | offen=ja]")
    assert result.returncode == 0, result.stderr
