"""Terminal rendering: colour, unicode tables and text reports.

Everything here is pure text so it can be asserted in tests. Colours are only
emitted when stdout is a TTY (or --color forces them), which keeps piped output
byte-identical and diff-friendly.
"""

from __future__ import annotations

import shutil
import unicodedata
from dataclasses import dataclass

RESET = "\x1b[0m"
STYLES = {
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "white": "\x1b[37m",
    "grey": "\x1b[90m",
}

THEME_COLORS = {
    "feature": "green",
    "fix": "red",
    "refactor": "blue",
    "docs": "yellow",
    "test": "magenta",
    "build": "cyan",
    "release": "white",
    "chore": "grey",
    "other": "grey",
}


def colorize(text: str, *styles: str, enabled: bool = True) -> str:
    """Wrap *text* in ANSI styles, or return it untouched when colour is off."""
    if not enabled or not styles:
        return text
    prefix = "".join(STYLES.get(s, "") for s in styles)
    return prefix + text + RESET


def supports_color(stream) -> bool:
    return bool(getattr(stream, "isatty", lambda: False)())


def width(text: str) -> int:
    """Display width of a string, counting wide CJK glyphs as two columns."""
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def truncate(text: str, limit: int) -> str:
    """Shorten to *limit* columns, appending an ellipsis when cut."""
    if width(text) <= limit:
        return text
    out = ""
    used = 0
    for ch in text:
        step = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + step > limit - 1:
            break
        out += ch
        used += step
    return out + "\u2026"


def pad(text: str, limit: int, align: str = "left") -> str:
    clipped = truncate(text, limit)
    gap = limit - width(clipped)
    if align == "right":
        return " " * gap + clipped
    return clipped + " " * gap


@dataclass(frozen=True)
class Column:
    title: str
    align: str = "left"
    max_width: int = 60


def table(headers: list[str], rows: list[list[str]], aligns: list[str] | None = None,
          max_width: int = 60) -> str:
    """Render a box-drawing table that survives CJK and emoji."""
    aligns = aligns or ["left"] * len(headers)
    columns = [
        Column(title=h, align=(aligns[i] if i < len(aligns) else "left"), max_width=max_width)
        for i, h in enumerate(headers)
    ]
    widths = [width(c.title) for c in columns]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], min(width(str(cell)), columns[i].max_width))
    widths = [max(w, 1) for w in widths]

    def rule(left: str, mid: str, right: str) -> str:
        return left + mid.join("\u2500" * (w + 2) for w in widths) + right

    lines = [rule("\u250c", "\u252c", "\u2510")]
    lines.append(
        "\u2502"
        + "\u2502".join(" " + pad(c.title, widths[i], "left") + " " for i, c in enumerate(columns))
        + "\u2502"
    )
    lines.append(rule("\u251c", "\u253c", "\u2524"))
    for row in rows:
        cells = [
            " "
            + pad(
                str(row[i]) if i < len(row) else "",
                widths[i],
                aligns[i] if i < len(aligns) else "left",
            )
            + " "
            for i in range(len(widths))
        ]
        lines.append("\u2502" + "\u2502".join(cells) + "\u2502")
    lines.append(rule("\u2514", "\u2534", "\u2518"))
    return "\n".join(lines)


def bar(value: float, maximum: float, cells: int = 24, char: str = "\u2588") -> str:
    """A unicode bar for sparkline-style reporting."""
    if maximum <= 0:
        return ""
    filled = int(round((value / maximum) * cells))
    filled = max(0, min(cells, filled))
    return char * filled + "\u00b7" * (cells - filled)


def sparkline(
    values: list[float],
    chars: str = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588",
) -> str:
    """A compact sparkline; empty input yields an empty string."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo
    out = []
    for value in values:
        idx = (
            len(chars) - 1
            if span == 0
            else int(round((value - lo) / span * (len(chars) - 1)))
        )
        out.append(chars[idx])
    return "".join(out)


def terminal_width(default: int = 100) -> int:
    return max(60, min(shutil.get_terminal_size((default, 24)).columns, 160))


def severity_marker(severity: str) -> str:
    return {"critical": "!!", "high": "!", "medium": "~", "info": "-"}.get(severity, "-")
