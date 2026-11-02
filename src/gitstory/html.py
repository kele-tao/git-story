"""The self-contained HTML story page.

No CDN, no webfont, no JavaScript: one file you can email. All charts are
inline SVG generated from the same numbers the CLI prints, so the page and the
terminal can never disagree.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
from dataclasses import dataclass

from .classify import classify
from .history import History
from .metrics import (
    HOTSPOT_HIGH,
    Coupling,
    Hotspot,
    MonthPoint,
    bus_factor,
    cochange,
    findings,
    hotspots,
    knowledge_concentration,
    monthly,
    size_distribution,
)
from .onboard import onboard

PALETTE = {
    "bg": "#0b0f17",
    "panel": "#121826",
    "line": "#263042",
    "text": "#e5e7eb",
    "muted": "#8b9bb4",
    "accent": "#22d3ee",
    "feature": "#4ade80",
    "fix": "#ff5f5f",
    "refactor": "#60a5fa",
    "docs": "#fbbf24",
    "test": "#c084fc",
    "build": "#67e8f9",
    "release": "#e5e7eb",
    "chore": "#6b7280",
    "other": "#6b7280",
}


def esc(value: object) -> str:
    return _html.escape(str(value), quote=True)


@dataclass(frozen=True)
class StoryOptions:
    title: str | None = None
    since: str | None = None
    max_months: int = 24
    include_charts: bool = True


def _fmt_month(month: str) -> str:
    try:
        year, mon = month.split("-")
        return _dt.date(int(year), int(mon), 1).strftime("%b %Y")
    except (ValueError, TypeError):
        return month


def _stat_card(label: str, value: str, sub: str = "") -> str:
    return (
        '<div class="card"><div class="card-k">'
        + esc(label)
        + '</div><div class="card-v">'
        + esc(value)
        + "</div>"
        + ('<div class="card-s">' + esc(sub) + "</div>" if sub else "")
        + "</div>"
    )


def _stacked_chart(months: list[MonthPoint], width: int = 1100, height: int = 220) -> str:
    if not months:
        return '<p class="muted">no commits in range</p>'
    keys = ["feature", "fix", "refactor", "other"]
    totals = [sum(getattr(m, k) for k in keys) for m in months]
    peak = max(totals) or 1
    pad_l, pad_b, pad_t = 34, 46, 12
    inner_w = width - pad_l - 12
    inner_h = height - pad_b - pad_t
    slot = inner_w / len(months)
    bar_w = max(3.0, min(46.0, slot * 0.62))
    parts: list[str] = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    for i in range(5):
        y = pad_t + inner_h * i / 4
        value = round(peak * (4 - i) / 4)
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - 12}" y2="{y:.1f}" stroke="{PALETTE["line"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end" class="ax">{value}</text>'
        )
    for idx, month in enumerate(months):
        x = pad_l + slot * idx + (slot - bar_w) / 2
        cursor = pad_t + inner_h
        for key in keys:
            count = getattr(month, key)
            if count <= 0:
                continue
            h = inner_h * count / peak
            cursor -= h
            parts.append(
                f'<rect x="{x:.1f}" y="{cursor:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
                f'rx="2" fill="{PALETTE.get(key, PALETTE["other"])}"><title>{esc(key)}: {count} in {esc(_fmt_month(month.month))}</title></rect>'
            )
        if len(months) <= 14 or idx % max(1, len(months) // 10) == 0:
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{height - pad_b + 18}" text-anchor="middle" class="ax">{esc(_fmt_month(month.month))}</text>'
            )
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{height - pad_b + 34}" text-anchor="middle" class="ax dim">{month.commits}</text>'
            )
    parts.append(
        f'<text x="{pad_l}" y="{height - 6}" class="ax dim">bars: commits by theme, numbers below: total commits</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _concentration_chart(points, width: int = 1100, height: int = 150) -> str:
    if len(points) < 2:
        return '<p class="muted">not enough history for a trend</p>'
    pad_l, pad_r, pad_t, pad_b = 34, 16, 14, 26
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    step = inner_w / (len(points) - 1)
    coords = [
        (pad_l + step * i, pad_t + inner_h * (1 - p.hhi)) for i, p in enumerate(points)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    parts.append(
        f'<line x1="{pad_l}" y1="{pad_t + inner_h}" x2="{width - pad_r}" y2="{pad_t + inner_h}" stroke="{PALETTE["line"]}"/>'
    )
    parts.append(
        f'<polyline points="{line}" fill="none" stroke="{PALETTE["accent"]}" stroke-width="2.5" stroke-linejoin="round"/>'
    )
    for (x, y), point in zip(coords, points, strict=True):
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{PALETTE["bg"]}" stroke="{PALETTE["accent"]}" stroke-width="2">'
            f"<title>HHI {point.hhi:.3f}, top author {point.top_share:.0%}, {point.authors} authors, {esc(point.label)}</title></circle>"
        )
    parts.append(f'<text x="{pad_l}" y="10" class="ax dim">knowledge concentration (HHI, 1.0 = one person)</text>')
    parts.append("</svg>")
    return "".join(parts)


def _quadrant_chart(spots: list[Hotspot], width: int = 520, height: int = 320) -> str:
    if not spots:
        return '<p class="muted">no hotspots</p>'
    pad = 34
    inner_w = width - pad * 2
    inner_h = height - pad * 2
    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    left = pad + HOTSPOT_HIGH * inner_w
    top = pad + inner_h * (1 - HOTSPOT_HIGH)
    parts.append(
        f'<rect x="{left:.1f}" y="{pad}" width="{pad + inner_w - left:.1f}" '
        f'height="{top - pad:.1f}" fill="rgba(255,95,95,.10)" '
        f'stroke="rgba(255,95,95,.35)" stroke-dasharray="4 3"/>'
    )
    parts.append(
        f'<text x="{pad + inner_w - 6}" y="{pad + 14}" text-anchor="end" class="ax" '
        f'fill="{PALETTE["fix"]}">danger: high churn + high complexity</text>'
    )
    parts.append(
        f'<text x="{pad + 4}" y="{pad + 14}" class="ax dim">'
        f"percentile ranks, {len(spots)} files</text>"
    )
    parts.append(f'<line x1="{pad}" y1="{pad + inner_h}" x2="{width - pad}" y2="{pad + inner_h}" stroke="{PALETTE["line"]}"/>')
    parts.append(f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{pad + inner_h}" stroke="{PALETTE["line"]}"/>')
    for spot in spots:
        cx = pad + spot.churn_score * inner_w
        cy = pad + inner_h * (1 - spot.complexity_score)
        radius = 3 + min(6, spot.commits ** 0.5)
        color = PALETTE["fix"] if spot.quadrant == "danger" else (
            PALETTE["docs"] if spot.quadrant == "churny" else (
                PALETTE["refactor"] if spot.quadrant == "fragile" else PALETTE["muted"]))
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius:.1f}" fill="{color}" fill-opacity="0.75">'
            f"<title>{esc(spot.path)}: {spot.commits} commits, {spot.authors} authors, {spot.lines} lines</title></circle>"
        )
    parts.append(
        f'<text x="{width / 2}" y="{height - 6}" text-anchor="middle" class="ax dim">'
        "churn percentile -&gt;</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


def _timeline(history: History, months: list[MonthPoint]) -> str:
    by_month: dict[str, list] = {}
    for commit in history.commits:
        by_month.setdefault(commit.month, []).append(commit)
    blocks: list[str] = []
    for point in reversed(months):
        commits = by_month.get(point.month, [])
        themes: dict[str, int] = {}
        for commit in commits:
            theme = classify(commit).theme
            themes[theme] = themes.get(theme, 0) + 1
        chips = "".join(
            f'<span class="chip" style="--c:{PALETTE.get(theme, PALETTE["other"])}">{esc(theme)} {count}</span>'
            for theme, count in sorted(themes.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        items: list[str] = []
        for commit in commits[:8]:
            info = classify(commit)
            color = PALETTE.get(info.theme, PALETTE["other"])
            items.append(
                '<li class="ev">'
                f'<span class="dot" style="background:{color}"></span>'
                f'<span class="sha">{esc(commit.sha[:7])}</span>'
                f'<span class="subj">{esc(commit.subject[:110])}</span>'
                f'<span class="who">{esc(commit.author)}</span>'
                "</li>"
            )
        more = ""
        if len(commits) > 8:
            more = f'<li class="ev more">+{len(commits) - 8} more commits</li>'
        top_files = _top_files(commits, 5)
        files_html = "".join(
            f'<span class="file">{esc(path)} <span class="n">{n}</span></span>' for path, n in top_files
        )
        blocks.append(
            '<section class="month">'
            f'<div class="month-head"><h3>{esc(_fmt_month(point.month))}</h3>'
            f'<span class="muted">{len(commits)} commits, {point.authors} authors, '
            f'{point.insertions + point.deletions} lines changed</span></div>'
            f'<div class="chips">{chips}</div>'
            f'<ul class="events">{"".join(items)}{more}</ul>'
            f'<div class="files">{files_html}</div>'
            "</section>"
        )
    return "".join(blocks)


def _top_files(commits, limit: int) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for commit in commits:
        for change in commit.files:
            counts[change.path] = counts.get(change.path, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:limit]


def _coupling_rows(pairs: list[Coupling]) -> str:
    if not pairs:
        return '<p class="muted">no strong coupling found</p>'
    rows = []
    for pair in pairs[:8]:
        rows.append(
            "<tr>"
            f"<td>{esc(pair.left)}</td><td>{esc(pair.right)}</td>"
            f"<td class='num'>{pair.together}</td>"
            f"<td class='num'>{pair.confidence:.0%}</td>"
            "</tr>"
        )
    return (
        '<table><thead><tr><th>file</th><th>changes with</th><th>times</th><th>confidence</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_story(history: History, opts: StoryOptions | None = None,
                 sources: dict[str, str] | None = None) -> str:
    """Render the complete HTML page as a string."""
    opts = opts or StoryOptions()
    months = monthly(history)
    if opts.max_months > 0:
        months = months[-opts.max_months :]
        cutoff = months[0].month if months else None
    else:
        cutoff = None
    recent = [c for c in history.commits if cutoff is None or c.month >= cutoff]
    display = _clone_history(history, recent)

    title = opts.title or f"{history.name}: an engineering story"
    span = history.span
    span_text = (
        f"{span[0].isoformat()} to {span[1].isoformat()}" if span else "no commits"
    )
    merged = history.merges()
    bf = bus_factor(display, top=6)
    spots = hotspots(display, sources=sources, top=40)
    pairs = cochange(display, top=10, min_together=2)
    guide = onboard(display, sources=sources, top=10)
    facts = findings(display)
    dist = size_distribution(display)
    concentration = knowledge_concentration(display, bins=10)
    top_authors = _author_counts(history)

    stats = "".join(
        [
            _stat_card("commits", f"{len(history.commits):,}", f"{len(recent):,} in timeline"),
            _stat_card("authors", str(len(top_authors)), f"top: {top_authors[0][0] if top_authors else '-'}"),
            _stat_card("files touched", f"{len(history.file_commits()):,}", f"{len(history.head_files()):,} at HEAD"),
            _stat_card("merge commits", f"{len(merged):,}", f"{len(history.tags)} tags"),
            _stat_card("span", f"{(span[1] - span[0]).days if span else 0:,} days", span_text),
        ]
    )
    bus_rows = "".join(
        f"<tr><td>{esc(row.directory)}</td><td class='num'>{row.commits}</td>"
        f"<td class='num'>{row.authors}</td>"
        f"<td class='num {'bad' if row.bus_factor <= 1 else ''}'>{row.bus_factor}</td>"
        f"<td>{esc(row.top_author)}</td><td class='num'>{row.top_share:.0%}</td></tr>"
        for row in bf
    )
    fact_html = "".join(
        f'<li class="fact {esc(f.severity)}"><span class="badge">{esc(f.severity)}</span>'
        f'<strong>{esc(f.headline)}</strong><span class="muted"> {esc(f.detail)}</span></li>'
        for f in facts[:5]
    )
    guide_html = "".join(
        f"<tr><td class='num'>{entry.rank}</td><td>{esc(entry.path)}</td>"
        f"<td class='num'>{entry.importers}</td><td class='num'>{entry.commits}</td>"
        f"<td class='muted'>{esc(', '.join(entry.reasons))}</td></tr>"
        for entry in guide
    )
    dist_html = "".join(
        f'<div class="dist"><span class="dk">{esc(b.bucket)}</span>'
        f'<span class="dv">{b.count}</span>'
        f'<span class="db" style="width:{max(2, b.share * 100):.1f}%"></span></div>'
        for b in dist
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
 :root {{ color-scheme: dark; }}
 * {{ box-sizing: border-box; }}
 body {{ margin:0; background:{PALETTE["bg"]}; color:{PALETTE["text"]};
   font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
 .wrap {{ max-width:1180px; margin:0 auto; padding:44px 28px 80px; }}
 header h1 {{ font-size:34px; line-height:1.15; margin:0 0 8px; letter-spacing:-.02em; }}
 header .sub {{ color:{PALETTE["muted"]}; font-size:14px; }}
 .muted {{ color:{PALETTE["muted"]}; }}
 .cards {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin:26px 0 8px; }}
 .card {{ background:{PALETTE["panel"]}; border:1px solid {PALETTE["line"]}; border-radius:12px; padding:14px 16px; }}
 .card-k {{ color:{PALETTE["muted"]}; font-size:11px; text-transform:uppercase; letter-spacing:.09em; }}
 .card-v {{ font-size:23px; font-weight:650; margin-top:2px; font-variant-numeric:tabular-nums; }}
 .card-s {{ color:{PALETTE["muted"]}; font-size:12px; }}
 h2 {{ font-size:19px; margin:38px 0 12px; letter-spacing:-.01em; }}
 h2 span {{ color:{PALETTE["muted"]}; font-weight:400; font-size:13px; margin-left:8px; }}
 .panel {{ background:{PALETTE["panel"]}; border:1px solid {PALETTE["line"]}; border-radius:14px; padding:16px 18px; }}
 .chart {{ width:100%; height:auto; display:block; }}
 .ax {{ fill:{PALETTE["muted"]}; font-size:11px; font-family:ui-monospace,Consolas,monospace; }}
 .ax.dim {{ fill:#5b6b82; }}
 .grid2 {{ display:grid; grid-template-columns:1.15fr .85fr; gap:14px; align-items:start; }}
 table {{ width:100%; border-collapse:collapse; font-size:13px; }}
 th {{ text-align:left; color:{PALETTE["muted"]}; font-weight:500; font-size:11px;
   text-transform:uppercase; letter-spacing:.08em; padding:6px 8px; border-bottom:1px solid {PALETTE["line"]}; }}
 td {{ padding:6px 8px; border-bottom:1px solid rgba(38,48,66,.55); }}
 td.num {{ text-align:right; font-variant-numeric:tabular-nums; font-family:ui-monospace,Consolas,monospace; }}
 td.bad {{ color:{PALETTE["fix"]}; font-weight:700; }}
 .facts {{ list-style:none; margin:0; padding:0; }}
 .fact {{ padding:9px 0; border-bottom:1px solid rgba(38,48,66,.55); font-size:13.5px; }}
 .badge {{ display:inline-block; font-size:10px; text-transform:uppercase; letter-spacing:.08em;
   padding:2px 7px; border-radius:999px; margin-right:8px; background:#1e293b; color:{PALETTE["muted"]}; }}
 .fact.critical .badge {{ background:rgba(255,95,95,.16); color:{PALETTE["fix"]}; }}
 .fact.high .badge {{ background:rgba(251,191,36,.16); color:{PALETTE["docs"]}; }}
 .month {{ display:grid; grid-template-columns:150px 1fr; gap:4px 18px; padding:14px 0;
   border-top:1px solid {PALETTE["line"]}; align-items:start; }}
 .month:first-child {{ border-top:0; }}
 .month-head h3 {{ margin:0; font-size:15px; }}
 .month-head .muted {{ font-size:11.5px; display:block; margin-top:3px; }}
 .chips {{ grid-column:2; display:flex; flex-wrap:wrap; gap:6px; margin:0 0 4px; }}
 .chip {{ font-size:11px; padding:2px 8px; border-radius:999px; color:var(--c);
   background:color-mix(in srgb, var(--c) 14%, transparent); border:1px solid color-mix(in srgb, var(--c) 34%, transparent); }}
 .events {{ grid-column:2; list-style:none; margin:0; padding:0; display:flex;
   flex-direction:column; gap:3px; }}
 .ev {{ display:grid; grid-template-columns:10px 62px 1fr auto; gap:9px; align-items:baseline;
   font-size:13px; line-height:1.35; }}
 .ev .dot {{ width:7px; height:7px; border-radius:50%; display:inline-block; }}
 .ev .sha {{ color:#5b6b82; font-family:ui-monospace,Consolas,monospace; font-size:11.5px; }}
 .ev .who {{ color:{PALETTE["muted"]}; font-size:11.5px; }}
 .ev.more {{ color:{PALETTE["muted"]}; font-size:12px; padding-left:82px; }}
 .files {{ grid-column:2; margin-top:4px; display:flex; flex-wrap:wrap; gap:6px; }}
 .file {{ font-size:11px; color:{PALETTE["muted"]}; background:#0f1622;
   border:1px solid {PALETTE["line"]}; border-radius:6px; padding:2px 7px;
   font-family:ui-monospace,Consolas,monospace; }}
 .file .n {{ color:{PALETTE["accent"]}; margin-left:4px; }}
 .dist {{ display:flex; align-items:center; gap:10px; font-size:12px; padding:3px 0; }}
 .dk {{ width:26px; color:{PALETTE["muted"]}; font-family:ui-monospace,Consolas,monospace; }}
 .dv {{ width:34px; text-align:right; font-variant-numeric:tabular-nums; }}
 .db {{ height:9px; border-radius:4px; background:linear-gradient(90deg,{PALETTE["accent"]},{PALETTE["refactor"]}); }}
 footer {{ margin-top:46px; color:#5b6b82; font-size:12px; border-top:1px solid {PALETTE["line"]}; padding-top:14px; }}
 @media (max-width:900px) {{ .cards {{ grid-template-columns:repeat(2,1fr); }}
   .grid2 {{ grid-template-columns:1fr; }} .month {{ grid-template-columns:1fr; }}
   .chips,.events,.files {{ grid-column:1; }} }}
</style></head>
<body><div class="wrap">
<header>
  <h1>{esc(title)}</h1>
  <div class="sub">{esc(history.name)} &middot; {esc(span_text)} &middot; generated by git-story</div>
</header>
<div class="cards">{stats}</div>

<h2>Findings <span>computed from this history, not templated</span></h2>
<div class="panel"><ul class="facts">{fact_html}</ul></div>

<h2>Commit themes per month <span>classified from message + diff shape</span></h2>
<div class="panel">{_stacked_chart(months)}</div>

<h2>Knowledge concentration <span>HHI over ten equal commit buckets</span></h2>
<div class="panel">{_concentration_chart(concentration)}</div>

<h2>Bus factor by directory <span>people who own 50% of the commits</span></h2>
<div class="panel"><table><thead><tr><th>directory</th><th class="num">commits</th><th class="num">authors</th>
<th class="num">bus factor</th><th>top author</th><th class="num">share</th></tr></thead>
<tbody>{bus_rows}</tbody></table></div>

<div class="grid2">
  <div>
    <h2>Hotspots <span>churn x complexity</span></h2>
    <div class="panel">{_quadrant_chart(spots)}</div>
  </div>
  <div>
    <h2>Commit size <span>XS &lt; 10 &hellip; XL &ge; 1000 lines</span></h2>
    <div class="panel">{dist_html}</div>
    <h2>Hidden coupling <span>files that change together</span></h2>
    <div class="panel">{_coupling_rows(pairs)}</div>
  </div>
</div>

<h2>Read these first <span>reverse imports + churn + co-change centrality</span></h2>
<div class="panel"><table><thead><tr><th class="num">#</th><th>file</th>
<th class="num">imported by</th><th class="num">commits</th><th>why</th></tr></thead>
<tbody>{guide_html}</tbody></table></div>

<h2>Timeline <span>newest month first</span></h2>
<div class="panel">{_timeline(display, months)}</div>

<footer>git-story v1.0.0 &middot; every number on this page was computed from
<code>git log</code> of {esc(history.name)} &middot; regenerate with
<code>git-story story --format html</code></footer>
</div></body></html>
"""


def _author_counts(history: History):
    from collections import Counter

    counts = Counter(c.author for c in history.commits)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _clone_history(history: History, commits: list) -> History:
    """A sub-history sharing the repo and tags, used for the timeline window."""
    from .history import History as _History

    return _History(history.repo, list(commits), history.tags)
