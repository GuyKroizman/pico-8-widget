"""Tests for the pdat parser and cart-row filtering."""

from conftest import fixture

import p8


def make_row(**overrides):
    """A 24-field pdat row with sane defaults; override by field name."""
    fields = {
        "pid": "0", "tid": 1, "title": "A Game", "thumb": "/bbs/thumbs/pico8_g-0.png",
        "w": 256, "h": 170, "created": "2026-01-01 00:00:00", "uid": 7,
        "author": "Someone", "last": "", "c10": 0, "c11": "", "c12": 0, "c13": 1,
        "c14": 0, "cat": 7, "sub": 2, "c17": "0", "tags": [], "flags": 2,
        "c20": 21, "c21": 7, "cart_id": "cartid", "c23": "",
    }
    order = ["pid", "tid", "title", "thumb", "w", "h", "created", "uid", "author",
             "last", "c10", "c11", "c12", "c13", "c14", "cat", "sub", "c17",
             "tags", "flags", "c20", "c21", "cart_id", "c23"]
    row = [fields[name] for name in order]
    for key, value in overrides.items():
        row[order.index(key)] = value
    return row


# ---------------------------------------------------------------------------
# parse_pdat
# ---------------------------------------------------------------------------

def test_parse_real_listing_page():
    rows = p8.parse_pdat(fixture("listing.html"))
    assert len(rows) == 4
    first = rows[0]
    assert first[1] == 159011
    assert first[2] == "get your food "
    assert first[22] == "yupopmoma"


def test_parse_backtick_titles_with_hostile_characters():
    html = "pdat=[ ['1', 2, `title, with ] bracket and \" quote`,] ];"
    rows = p8.parse_pdat(html)
    assert rows[0][2] == 'title, with ] bracket and " quote'


def test_parse_unicode_escape_in_double_quotes():
    html = 'pdat=[ [\'1\', 2, "caf\\u00e9",] ];'  # real JS: "caf\u00e9"
    rows = p8.parse_pdat(html)
    assert rows[0][2] == "café"


def test_parse_empty_fields_and_numbers():
    html = "pdat=[ ['1', 2, `t`,\"\",,170.5,7,2,'0',[],0,4,,``,``] ];"
    rows = p8.parse_pdat(html)
    assert rows[0][1] == 2
    assert rows[0][4] == ""       # truly empty field
    assert rows[0][5] == 170.5    # float kept as a number


def test_parse_missing_blob_returns_empty():
    assert p8.parse_pdat("<html>no data here</html>") == []


def test_parse_nested_tag_array():
    html = "pdat=[ ['1', 2, `t`,\"\",0,0,\"\",0,0,\"\",0,\"\",0,0,0,7,2,'0',[\"wip\",\"raycast\"],2,21,7,`x`,``] ];"
    rows = p8.parse_pdat(html)
    assert rows[0][18] == ["wip", "raycast"]


# ---------------------------------------------------------------------------
# row_to_cart
# ---------------------------------------------------------------------------

def test_valid_row_maps_fields():
    cart = p8.row_to_cart(make_row(tid=158939, title="Rockhound",
                                   author="Very&#39;s Bo&#39;y"))
    assert cart == {
        "tid": 158939,
        "title": "Rockhound",
        "author": "Very's Bo'y",
        "cart_id": "cartid",
        "thumb": "/bbs/thumbs/pico8_g-0.png",
        "created": "2026-01-01 00:00:00",
    }


def test_short_row_rejected():
    assert p8.row_to_cart(make_row()[:20]) is None


def test_non_cart_post_rejected():
    assert p8.row_to_cart(make_row(flags=0)) is None
    assert p8.row_to_cart(make_row(flags=1)) is None  # bit 1 not set
    assert p8.row_to_cart(make_row(flags="2")) is None  # flags must be an int


def test_cart_without_id_rejected():
    assert p8.row_to_cart(make_row(cart_id="")) is None


def test_blank_title_rejected():
    assert p8.row_to_cart(make_row(title="   ")) is None


def test_wip_rejected_by_tag():
    assert p8.row_to_cart(make_row(tags=["wip", "raycast"])) is None


def test_wip_rejected_by_title():
    assert p8.row_to_cart(make_row(title="My WIP Game")) is None
    assert p8.row_to_cart(make_row(title="A Work In Progress Demo")) is None


def test_wip_rejected_by_cart_id():
    assert p8.row_to_cart(make_row(cart_id="castmarble_wip")) is None


def test_wip_only_if_lowercase_match():
    # "wip" as part of a normal word must not disqualify the cart.
    assert p8.row_to_cart(make_row(title="Wipeout Racers")) is not None
    assert p8.row_to_cart(make_row(cart_id="wipper")) is not None


def test_html_entities_unescaped_in_title():
    cart = p8.row_to_cart(make_row(title="It&#39;s Fine &#38; Dandy"))
    assert cart["title"] == "It's Fine & Dandy"
