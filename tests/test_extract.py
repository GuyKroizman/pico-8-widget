"""Tests for description extraction from cart pages."""

from conftest import fixture

import p8


def test_modern_page_description_extracted():
    desc = p8.extract_description(fixture("cart_page_modern.html"))
    assert "In short: traverse the maze, collect gems, don't get killed!" in desc
    assert "Version History:" in desc
    assert "1.01 - Changed movement to make it easier to walk between gaps in the walls" in desc


def test_modern_page_chrome_removed():
    desc = p8.extract_description(fixture("cart_page_modern.html"))
    # embed instruction, tag chips, like counts, comments, rate buttons
    assert "Copy and paste the snippet below" not in desc
    assert "tag=" not in desc
    assert "puzzle" not in desc      # tag-chip words (maze is in the text)
    assert "arcade" not in desc
    assert "this is a comment" not in desc
    assert "Mark as Spam" not in desc
    assert "No License" not in desc
    assert "Widget" not in desc        # textarea body stripped


def test_embed_disabled_page_notice_removed():
    desc = p8.extract_description(fixture("cart_page_noembed.html"))
    assert "my first game - a tiny platformer" in desc
    assert "arrows to move, x to jump, z to dash" in desc
    assert "0.1 - initial upload" in desc
    assert "embedded playback" not in desc
    assert "link will be included instead" not in desc
    assert "retro" not in desc          # tag-chip word
    assert "must drop the notice" not in desc  # HTML comments are stripped
    assert "someone: nice game!" not in desc


def test_many_tiny_lines_collapse_into_prose():
    paragraphs = ["<p>line " + str(i) + "</p>" for i in range(50)]
    html = "<html><body>" + "".join(paragraphs) + "<br id=comments>x</body></html>"
    desc = p8.extract_description(html)
    assert "\n" not in desc
    assert "line 0" in desc and "line 49" in desc


def test_empty_page_yields_empty_description():
    assert p8.extract_description("<html><body><br id=comments></body></html>") == ""


def test_script_style_textarea_comments_never_leak():
    """The CodeQL py/bad-tag-filter case: regex tag filtering is bypassable
    (e.g. `</script >`), so containers must be dropped structurally."""
    html = """<html><body>
      <script>var evil = "alert(1)";</script>
      <script>var evil2 = "alert(2)";</script >
      <style>body { color: red }</style>
      <textarea><iframe src="x"></iframe></textarea>
      <!-- nasty comment mentioning </script > -->
      <p>the real description</p>
      <br id=comments>
      <p>a comment from someone else</p>
    </body></html>"""
    desc = p8.extract_description(html)
    assert "the real description" in desc
    assert "alert" not in desc
    assert "color: red" not in desc
    assert "iframe" not in desc
    assert "nasty comment" not in desc
    assert "a comment from someone else" not in desc


def test_charrefs_still_unescaped():
    html = "<p>caf&#233; &#38; tea</p><br id=comments>"
    desc = p8.extract_description(html)
    assert desc == "café & tea"
