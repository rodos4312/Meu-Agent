"""Gauge colouring in curses/ANSI descriptions only touches ten-cell gauges."""

from hermes_cli.curses_ui import _gauge_bar_segments


def test_real_gauges_are_styled():
    for bar, style in (("[          ]", "green"), ("[||||||    ]", "yellow"), ("[||||||||| ]", "red")):
        assert _gauge_bar_segments(f"Today  {bar}  x") == [("Today  ", None), (bar, style), ("  x", None)]


def test_unrelated_brackets_stay_plain():
    for text in ("toggle [] here", "checkbox [ ] off", "a [||] b", "flag [x]", "[" + " " * 11 + "]"):
        assert _gauge_bar_segments(text) == [(text, None)]
