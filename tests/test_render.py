"""Terminal rendering primitives, including CJK and emoji handling."""

from __future__ import annotations

import io

from gitstory.render import (
    bar,
    colorize,
    pad,
    severity_marker,
    sparkline,
    supports_color,
    table,
    truncate,
    width,
)


def test_colorize_is_a_noop_when_disabled():
    assert colorize("hello", "red", enabled=False) == "hello"


def test_colorize_wraps_with_ansi_and_reset():
    out = colorize("hi", "bold", "red", enabled=True)
    assert out.startswith("\x1b[1m\x1b[31m")
    assert out.endswith("\x1b[0m")
    assert "hi" in out


def test_supports_color_reads_isatty():
    class Stream:
        def __init__(self, tty):
            self._tty = tty

        def isatty(self):
            return self._tty

    assert supports_color(Stream(True))
    assert not supports_color(Stream(False))
    assert not supports_color(io.StringIO())


def test_width_counts_cjk_as_two_columns():
    assert width("abc") == 3
    assert width("\u4f60\u597d") == 4
    assert width("a\u4f60b") == 4


def test_truncate_keeps_short_strings():
    assert truncate("short", 20) == "short"


def test_truncate_adds_an_ellipsis():
    out = truncate("abcdefghij", 6)
    assert out.endswith("\u2026")
    assert width(out) <= 6


def test_truncate_respects_wide_glyphs():
    out = truncate("\u4f60\u597d\u4e16\u754c", 5)
    assert width(out) <= 5


def test_pad_aligns_left_and_right():
    assert pad("ab", 4) == "ab  "
    assert pad("ab", 4, "right") == "  ab"
    assert width(pad("\u4f60", 5)) == 5


def test_table_draws_a_border_and_content():
    out = table(["name", "n"], [["alpha", "1"], ["b", "22"]])
    lines = out.splitlines()
    assert lines[0].startswith("\u250c")
    assert lines[-1].startswith("\u2514")
    assert "alpha" in out
    assert "name" in out
    assert len(lines) == 6


def test_table_clips_wide_cells():
    out = table(["file"], [["x" * 100]], max_width=10)
    assert "x" * 100 not in out


def test_bar_is_bounded():
    assert bar(5, 10, 10) == "\u2588" * 5 + "\u00b7" * 5
    assert bar(0, 10, 4) == "\u00b7" * 4
    assert bar(10, 10, 4) == "\u2588" * 4
    assert bar(1, 0) == ""


def test_sparkline_shapes():
    assert sparkline([]) == ""
    assert len(sparkline([1, 2, 3])) == 3
    assert sparkline([5, 5, 5]) == "\u2588" * 3


def test_severity_markers():
    assert severity_marker("critical") == "!!"
    assert severity_marker("high") == "!"
    assert severity_marker("unknown") == "-"
