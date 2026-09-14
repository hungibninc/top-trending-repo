#!/usr/bin/env python3
"""Static site builder — pipeline step 4 of the architecture (ADR-002).

Reads data/latest.json (produced by scripts/fetch_trending.py) and renders
public/index.html from site/template.html. Zero client-side JS: the page
works with JavaScript disabled and every value is rendered at build time.

Components (build-time render functions):
  render_card()      -> one <article> per repo (rank, name, desc, language,
                        stars, forks, weekly delta)
  render_stale()     -> amber banner when latest.json.stale is true (AC-7)
  render_warnings()  -> muted footnote for bootstrap/partial data

Safety: all GitHub-provided strings (names, descriptions, URLs) are
HTML-escaped — descriptions are attacker-controlled content.

Usage:
  scripts/build_site.py                       # data/latest.json -> public/
  scripts/build_site.py --data data/latest.json --out public
"""

import argparse
import html
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from string import Template

# GitHub linguist colors (subset; fallback gray for everything else)
LANG_COLORS = {
    "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "Python": "#3572A5",
    "Go": "#00ADD8", "Rust": "#dea584", "Java": "#b07219", "C++": "#f34b7d",
    "C#": "#178600", "C": "#555555", "PHP": "#4F5D95", "Ruby": "#701516",
    "Swift": "#F05138", "Kotlin": "#A97BFF", "Dart": "#00B4AB",
    "Shell": "#89e051", "HTML": "#e34c26", "CSS": "#563d7c", "Vue": "#41b883",
    "MDX": "#083fa1", "Markdown": "#083fa1", "Jupyter Notebook": "#DA5B0B",
    "Zig": "#ec915c", "Lua": "#000080", "Scala": "#c22d40",
}
DEFAULT_LANG_COLOR = "#8b949e"

STAR_SVG = (
    '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">'
    '<path d="M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 '
    '.416 1.279l-3.046 2.97.719 4.192a.75.75 0 0 1-1.088.791L8 12.347l-3.766 '
    '1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l'
    '4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z"/></svg>'
)
FORK_SVG = (
    '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">'
    '<path d="M5 5.372v.878c0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75v-.878'
    'a2.25 2.25 0 1 1 1.5 0v.878a2.25 2.25 0 0 1-2.25 2.25h-1.5v2.128a2.251 '
    '2.251 0 1 1-1.5 0V8.5h-1.5A2.25 2.25 0 0 1 3.5 6.25v-.878a2.25 2.25 0 '
    '1 1 1.5 0ZM5 3.25a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Zm6.75.75a.75.75 '
    '0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm-3 8.75a.75.75 0 1 0-1.5 0 .75.75 0 0 0 '
    '1.5 0Z"/></svg>'
)


def esc(value) -> str:
    """Escape attacker-controlled content (repo names/descriptions are public input)."""
    return html.escape(str(value), quote=True)


def fmt_int(value: int) -> str:
    return f"{value:,}"


def render_lang(language: str | None) -> str:
    if not language:
        return '<span class="lang-dot"></span>Unknown'
    color = LANG_COLORS.get(language, DEFAULT_LANG_COLOR)
    return (
        f'<span class="lang-dot" style="--lang-color:{color}"></span>'
        f'{esc(language)}'
    )


def render_delta(delta: int | None) -> str:
    if delta is None:
        return '<span class="stat delta muted">&mdash;</span>'
    return (
        f'<span class="stat delta">+{fmt_int(delta)} this week</span>'
    )


def render_card(repo: dict) -> str:
    desc = repo.get("description") or "No description provided."
    aria = f'"{esc(repo["full_name"])} on GitHub (opens in new tab)"'
    return f"""    <article class="card">
      <div class="card-rank">#{repo["rank"]}</div>
      <div class="card-body">
        <h2 class="card-title"><a href="{esc(repo["html_url"])}" target="_blank" rel="noopener noreferrer" aria-label={aria}>{esc(repo["full_name"])}</a></h2>
        <p class="card-desc">{esc(desc)}</p>
        <ul class="card-meta">
          <li class="stat lang">{render_lang(repo.get("language"))}</li>
          <li class="stat">{STAR_SVG} {fmt_int(repo["stars"])}</li>
          <li class="stat">{FORK_SVG} {fmt_int(repo["forks"])}</li>
          <li>{render_delta(repo.get("delta_stars"))}</li>
        </ul>
      </div>
    </article>"""


def render_stale(doc: dict) -> str:
    if not doc.get("stale"):
        return ""
    return '    <div class="banner" role="alert">⚠ API fetch failed — showing the last successful data.</div>\n'


def render_warnings(warnings: list[str]) -> str:
    if not warnings:
        return ""
    items = "\n".join(f"      <li>{esc(w)}</li>" for w in warnings)
    return f'    <ul class="warnings" aria-label="Data notices">\n{items}\n    </ul>\n'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/latest.json")
    parser.add_argument("--template", default="site/template.html")
    parser.add_argument("--styles", default="site/styles.css")
    parser.add_argument("--out", default="public")
    args = parser.parse_args(argv)

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: {data_path} not found — run scripts/fetch_trending.py first", file=sys.stderr)
        return 1

    with data_path.open() as f:
        doc = json.load(f)
    template = Template(Path(args.template).read_text())

    top10 = doc.get("top10") or []
    as_of = doc.get("as_of", "")
    try:
        as_of_dt = datetime.strptime(as_of, "%Y-%m-%dT%H:%M:%SZ")
        as_of_display = as_of_dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        as_of_display = as_of

    page = template.substitute(
        as_of_iso=esc(as_of),
        as_of_display=esc(as_of_display),
        stale_banner=render_stale(doc),
        cards="\n".join(render_card(r) for r in top10),
        warnings=render_warnings(doc.get("warnings") or []),
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(page)
    shutil.copyfile(args.styles, out_dir / "styles.css")
    print(f"built {out_dir}/index.html with {len(top10)} cards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
