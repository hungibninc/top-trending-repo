#!/usr/bin/env python3
"""Release-note + social-post generator (Python 3 stdlib only).

Reads data/latest.json (produced by scripts/fetch_trending.py) and renders:
  release/RELEASE-NOTES-<as_of-date>.md  — the weekly markdown release note
  release/social-post-x.md               — X/Twitter announcement
  release/social-post-linkedin.md        — LinkedIn announcement

Fully automated: every number, name, and the #1 spotlight come from the
data. Bootstrap weeks (delta_stars all null) drop the "weekly gain" column
and say so honestly instead of fabricating growth numbers.

Usage:
  scripts/generate_release_note.py
  scripts/generate_release_note.py --site-url https://your-domain.example
"""

import argparse
import html
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template

def esc(value) -> str:
    """Escape user-controlled content and keep markdown tables intact."""
    return html.escape(str(value), quote=True).replace("|", "\\|")


def fmt(value: int) -> str:
    return f"{value:,}"


def fmt_compact(value: int) -> str:
    """Short star counts for social posts (547,208 -> 547K)."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value // 1_000}K"
    return str(value)


def week_start_of(iso: str) -> str:
    dt = datetime.strptime(iso[:10], "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


def stats(top10: list[dict]) -> dict:
    langs = Counter(r.get("language") or "Unknown" for r in top10)
    top_lang, top_count = langs.most_common(1)[0]
    return {
        "total_stars": fmt(sum(r["stars"] for r in top10)),
        "total_forks": fmt(sum(r["forks"] for r in top10)),
        "n_langs": len(langs),
        "top_lang": top_lang,
        "top_count": top_count,
    }


def repo_cells(r: dict, has_deltas: bool, with_rank: bool) -> list[str]:
    cells = []
    if with_rank:
        cells.append(str(r["rank"]))
    cells += [
        f"[{esc(r['full_name'])}]({esc(r['html_url'])})",
        fmt(r["stars"]),
        fmt(r["forks"]),
        esc(r.get("language") or "Unknown"),
    ]
    if has_deltas:
        cells.append(fmt(r["delta_stars"]) if r.get("delta_stars") is not None else "—")
    return cells


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    aligns = ["---:" if h in ("Stars", "Forks", "Weekly gain") else "---" for h in headers]
    sep = "| " + " | ".join(aligns) + " |"
    body = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([header, sep, *body])


def build_spotlight_table(top: dict, has_deltas: bool) -> str:
    headers = ["Stars", "Forks", "Language"] + (["Weekly gain"] if has_deltas else [])
    return md_table(headers, [repo_cells(top, has_deltas, with_rank=False)])


def build_top10_table(top10: list[dict], has_deltas: bool) -> str:
    headers = ["#", "Repository", "Stars", "Forks", "Language"] + (["Weekly gain"] if has_deltas else [])
    return md_table(headers, [repo_cells(r, has_deltas, with_rank=True) for r in top10])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="data/latest.json")
    parser.add_argument("--templates", default="templates")
    parser.add_argument("--out", default="release")
    parser.add_argument("--site-url", default="https://toptrandingrepo.example", help="deployed site URL (set once the site is live; keep it short for X)")
    args = parser.parse_args(argv)

    with open(args.data) as f:
        doc = json.load(f)
    top10 = doc.get("top10") or []
    if not top10:
        print("ERROR: no data in latest.json", file=sys.stderr)
        return 1

    tpl_dir = Path(args.templates)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    as_of = doc.get("as_of", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    week_start = week_start_of(as_of)
    has_deltas = any(r.get("delta_stars") is not None for r in top10)
    s = stats(top10)

    top = top10[0]
    runners = top10[1:4]
    top_lang = top.get("language") or "Unknown"

    # --- release note ---
    if has_deltas:
        intro = (
            f"This week's list covers the 10 fastest-rising repositories on GitHub, "
            f"ranked by stars gained over the previous 7 days. Together they hold "
            f"**{s['total_stars']}** stars and **{s['total_forks']}** forks across "
            f"**{s['n_langs']}** languages, led by **{esc(s['top_lang'])}** "
            f"({s['top_count']} repos)."
        )
        ranking_note = "Ranked by stars gained over the previous 7 days. "
    else:
        intro = (
            f"This week's snapshot covers the 10 most-starred repositories on GitHub. "
            f"Together they hold **{s['total_stars']}** stars and **{s['total_forks']}** "
            f"forks across **{s['n_langs']}** languages, led by **{esc(s['top_lang'])}** "
            f"({s['top_count']} repos)."
        )
        ranking_note = (
            "Bootstrap week: ranked by total stars. The pipeline needs two weekly "
            "snapshots to compute 7-day star gains — the gain column appears next week. "
        )
    for w in doc.get("warnings") or []:
        if w not in ranking_note:
            ranking_note += f"{w}. "

    note = Template((tpl_dir / "release-note.md").read_text()).substitute(
        week_start=week_start,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        as_of=as_of.replace("T", " ").replace("Z", ""),
        site_url=args.site_url,
        intro=intro,
        top_name=esc(top["full_name"]),
        top_url=esc(top["html_url"]),
        top_desc=esc(top.get("description") or "No description provided."),
        spotlight_table=build_spotlight_table(top, has_deltas),
        top10_table=build_top10_table(top10, has_deltas),
        ranking_note=ranking_note,
    )
    note_path = out_dir / f"RELEASE-NOTES-{as_of[:10]}.md"
    note_path.write_text(note)

    # --- social posts ---
    if has_deltas:
        hook = (
            f"With +{fmt(top['delta_stars'])} stars in 7 days, {top['full_name']} "
            f"is GitHub's fastest riser this week."
        )
    else:
        hook = (
            f"{top['full_name']} tops GitHub's most-starred list this week "
            f"with {fmt(top['stars'])}★."
        )
    x_post = Template((tpl_dir / "social-post-x.md").read_text()).substitute(
        week_start=week_start, hook=hook,
        r2_name=runners[0]["full_name"], r2_stars=fmt_compact(runners[0]["stars"]),
        r3_name=runners[1]["full_name"], r3_stars=fmt_compact(runners[1]["stars"]),
        site_url=args.site_url,
    )
    if len(x_post) > 280:
        print(f"WARNING: X post is {len(x_post)} chars (limit 280) — shorten the hook or site URL", file=sys.stderr)
    (out_dir / "social-post-x.md").write_text(x_post)

    li_post = Template((tpl_dir / "social-post-linkedin.md").read_text()).substitute(
        week_start=week_start, hook=hook,
        top_name=esc(top["full_name"]),
        top_desc=esc(top.get("description") or "No description provided."),
        top_stars=fmt(top["stars"]), top_forks=fmt(top["forks"]),
        top_lang=esc(top_lang),
        r2_name=esc(runners[0]["full_name"]), r2_stars=fmt(runners[0]["stars"]),
        r3_name=esc(runners[1]["full_name"]), r3_stars=fmt(runners[1]["stars"]),
        r4_name=esc(runners[2]["full_name"]), r4_stars=fmt(runners[2]["stars"]),
        site_url=args.site_url,
    )
    (out_dir / "social-post-linkedin.md").write_text(li_post)

    print(f"wrote {note_path}")
    print(f"wrote {out_dir / 'social-post-x.md'}")
    print(f"wrote {out_dir / 'social-post-linkedin.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
