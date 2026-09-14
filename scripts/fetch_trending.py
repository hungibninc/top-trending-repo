#!/usr/bin/env python3
"""Weekly trending GitHub repos fetcher (Python 3 stdlib only, zero deps).

Pipeline step 1-3 of the architecture (.claude/plan/architecture.md):
  1. Fetch the top 50 repos by stars from the GitHub Search API (1 call).
  2. Compute each repo's star gain over the previous ~7 days against the
     most recent snapshot: delta_stars = stars_now - stars_last_week.
  3. Rank by delta_stars desc, then stars desc, then name asc; take top 10.
  4. Persist the snapshot (data/snapshots/YYYY-MM-DD.json) and atomically
     publish data/latest.json in the schema the frontend consumes.

Rate-limit handling:
  - Reads X-RateLimit-Remaining / X-RateLimit-Reset on every response.
  - If the limit is exhausted (HTTP 403/429), sleeps until reset (+5s
    buffer) and retries, capped by max retries and a total deadline.
  - Honors Retry-After when present; exponential backoff with jitter for
    5xx and network errors.
  - Optional PAT via GITHUB_TOKEN env var or --token (raises the limit
    from 60/hr unauthenticated to 5000/hr); sent only when provided.

Failure contract (PRD AC-7):
  - Exit 0: success, data/latest.json published.
  - Exit 1: fetch failed after retries, or data sanity check failed.
    data/latest.json is NEVER modified on failure, so the site keeps
    serving the last good list.

Success criteria (Karpathy discipline):
  - Latency: single API call; typical run < 30s, hard deadline 10 min.
  - RPO: one snapshot per week (data loss window = 1 week).
  - RTO: next scheduled run (<= 7 days), or immediate manual re-run.

Usage:
  scripts/fetch_trending.py                      # unauthenticated (60 req/hr)
  GITHUB_TOKEN=<your-pat> scripts/fetch_trending.py   # authenticated (5000 req/hr)
  scripts/fetch_trending.py --data-dir data --max-retries 5
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_API_URL = "https://api.github.com/search/repositories"
DEFAULT_QUERY = {
    "q": "stars:>1000",
    "sort": "stars",
    "order": "desc",
    "per_page": "50",
}
REQUEST_TIMEOUT_S = 30
MAX_RETRIES = 5
BACKOFF_BASE_S = 2.0
BACKOFF_CAP_S = 60.0
TOTAL_DEADLINE_S = 600
USER_AGENT = "toptrandingrepo-weekly/1.0"
TOP_N = 10


class FetchError(RuntimeError):
    """Permanent failure: stop retrying, exit 1, keep last good output."""


class DataError(RuntimeError):
    """Sanity check failed: refuse to publish, exit 1, keep last good output."""


def log(msg: str) -> None:
    print(f"[fetch_trending] {msg}", file=sys.stderr, flush=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_url(base: str, query: dict) -> str:
    return f"{base}?{urllib.parse.urlencode(query)}"


def api_headers(token: str | None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def int_header(headers, name: str) -> int | None:
    try:
        return int(headers.get(name))
    except (TypeError, ValueError):
        return None


def rate_limit_wait(headers) -> tuple[int | None, str | None]:
    """If the response says we are rate limited, return (seconds, reason)."""
    remaining = int_header(headers, "X-RateLimit-Remaining")
    if remaining is not None and remaining <= 0:
        reset = int_header(headers, "X-RateLimit-Reset")
        if reset is not None:
            wait = max(0, reset - int(time.time())) + 5  # 5s buffer past reset
            return wait, f"rate limit exhausted, resets at epoch {reset}"
    retry_after = int_header(headers, "Retry-After")
    if retry_after is not None:
        return retry_after + 1, "Retry-After header"
    return None, None


def backoff_s(attempt: int) -> float:
    """Exponential backoff with jitter, capped."""
    return min(BACKOFF_BASE_S * (2 ** (attempt - 1)), BACKOFF_CAP_S) * random.uniform(
        0.5, 1.5
    )


def fetch_with_retry(
    url: str, token: str | None, max_retries: int, deadline: float
) -> tuple[bytes, dict]:
    attempt = 0
    while True:
        if time.monotonic() > deadline:
            raise FetchError("total deadline exceeded")
        attempt += 1
        try:
            req = urllib.request.Request(url, headers=api_headers(token))
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                return resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            headers = dict(exc.headers)
            if exc.code in (403, 429):
                wait, reason = rate_limit_wait(headers)
                if (
                    wait is not None
                    and attempt <= max_retries
                    and time.monotonic() + wait <= deadline
                ):
                    log(
                        f"HTTP {exc.code}: {reason} — sleeping {wait}s, "
                        f"retry {attempt}/{max_retries}"
                    )
                    time.sleep(wait)
                    continue
            if exc.code in (500, 502, 503, 504) and attempt <= max_retries:
                wait = backoff_s(attempt)
                if time.monotonic() + wait <= deadline:
                    log(f"HTTP {exc.code}: sleeping {wait:.1f}s, retry {attempt}/{max_retries}")
                    time.sleep(wait)
                    continue
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise FetchError(f"HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt <= max_retries:
                wait = backoff_s(attempt)
                if time.monotonic() + wait <= deadline:
                    log(f"network error ({exc}): sleeping {wait:.1f}s, retry {attempt}/{max_retries}")
                    time.sleep(wait)
                    continue
            raise FetchError(f"network error: {exc}")


def log_rate_limit(headers) -> None:
    remaining = int_header(headers, "X-RateLimit-Remaining")
    limit = int_header(headers, "X-RateLimit-Limit")
    if remaining is not None:
        log(f"rate limit: {remaining}/{limit} remaining")


def extract_repos(payload: dict) -> list[dict]:
    if "items" not in payload:
        raise FetchError(f"unexpected API response shape: {list(payload)[:5]}")
    repos = []
    for item in payload["items"]:
        repos.append(
            {
                "full_name": item["full_name"],
                "description": item.get("description"),
                "html_url": item["html_url"],
                "stars": item["stargazers_count"],
                "forks": item["forks_count"],
                "language": item.get("language"),
            }
        )
    return repos


def load_previous_snapshot(snapshots_dir: Path, today: str) -> tuple[dict | None, str | None]:
    """Newest snapshot older than today (so a same-day re-run can't be its own baseline)."""
    files = sorted(p for p in snapshots_dir.glob("*.json") if p.stem != today)
    if not files:
        return None, None
    path = files[-1]
    with path.open() as f:
        return json.load(f), path.name


def compute_trending(current: list[dict], previous: list[dict] | None) -> list[tuple[dict, int | None, int | None]]:
    """Rank by delta_stars desc, stars desc, name asc; None deltas last."""
    prev_by_name = {r["full_name"]: r for r in previous} if previous else {}
    ranked = []
    for repo in current:
        if previous is not None:
            old = prev_by_name.get(repo["full_name"])
            if old is None:
                continue  # PRD: skip repos missing from the previous snapshot
            delta = repo["stars"] - old["stars"]
            if delta < 0:
                raise DataError(
                    f"negative star delta for {repo['full_name']}: "
                    f"{old['stars']} -> {repo['stars']} (refusing to publish)"
                )
            ranked.append((repo, old["stars"], delta))
        else:
            ranked.append((repo, None, None))
    ranked.sort(
        key=lambda t: (t[2] is None, -(t[2] or 0), -t[0]["stars"], t[0]["full_name"].lower())
    )
    return ranked[:TOP_N]


def save_snapshot(repos: list[dict], snapshots_dir: Path, as_of: str) -> Path:
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    path = snapshots_dir / f"{as_of[:10]}.json"
    payload = {"snapshot_date": as_of[:10], "fetched_at": as_of, "repos": repos}
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def write_latest(
    top10: list[tuple[dict, int | None, int | None]],
    as_of: str,
    stale: bool,
    warnings: list[str],
    latest_path: Path,
) -> None:
    payload = {
        "schema_version": 1,
        "published_at": utc_now_iso(),
        "as_of": as_of,
        "stale": stale,
        "warnings": warnings,
        "top10": [
            {
                "rank": i + 1,
                "full_name": repo["full_name"],
                "description": repo.get("description"),
                "html_url": repo["html_url"],
                "stars": repo["stars"],
                "forks": repo["forks"],
                "language": repo.get("language"),
                "stars_last_week": last_week,
                "delta_stars": delta,
            }
            for i, (repo, last_week, delta) in enumerate(top10)
        ],
    }
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = latest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(latest_path)  # atomic: readers never see a half-written file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default="data", help="data directory (snapshots + latest.json)")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="override API base URL")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"), help="optional PAT")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES)
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    snapshots_dir = data_dir / "snapshots"
    latest_path = data_dir / "latest.json"
    deadline = time.monotonic() + TOTAL_DEADLINE_S

    url = build_url(args.api_url, DEFAULT_QUERY)
    log(f"fetching {url}")
    body, headers = fetch_with_retry(url, args.token, args.max_retries, deadline)
    log_rate_limit(headers)

    as_of = utc_now_iso()
    repos = extract_repos(json.loads(body))
    log(f"got {len(repos)} repos from API")

    previous, prev_name = load_previous_snapshot(snapshots_dir, today=as_of[:10])
    try:
        top10 = compute_trending(repos, previous["repos"] if previous else None)
    except DataError as exc:
        log(f"ERROR: {exc}")
        return 1  # latest.json untouched -> last good list stays live (AC-7)

    warnings = []
    if previous is None:
        warnings.append(
            "bootstrap run: no previous snapshot; ranked by total stars (delta_stars null)"
        )
    elif len(top10) < TOP_N:
        warnings.append(
            f"only {len(top10)} repos appeared in consecutive snapshots; showing fewer than {TOP_N}"
        )

    save_snapshot(repos, snapshots_dir, as_of)
    write_latest(top10, as_of, stale=False, warnings=warnings, latest_path=latest_path)
    log(
        f"wrote {latest_path}: {len(top10)} repos "
        f"(baseline snapshot: {prev_name or 'none'})"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FetchError as exc:
        log(f"ERROR: {exc}")
        sys.exit(1)
