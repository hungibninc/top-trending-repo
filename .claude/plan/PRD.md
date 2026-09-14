# Weekly Top 10 Trending GitHub Repositories — Lean PRD

**Date**: 2026-09-14
**Author**: Product
**Status**: Draft
**Version**: 1.0

---

## 1. Problem

Developers and tech-curious readers want a quick answer to "what's blowing up on GitHub this week?" GitHub's own Trending page has no public API, and checking it manually is a weekly chore. There is no clean, automated, zero-login way to get a consistent weekly snapshot of the top 10 trending repositories with the metrics that matter.

## 2. Solution

A **static website that refreshes itself once per week** and shows the top 10 trending GitHub repositories, ranked by star growth over the previous 7 days. A scheduled job pulls repo data from the GitHub Search API, stores weekly snapshots, computes the ranking, and regenerates the page. No user accounts, no runtime backend, no manual steps.

## 3. Trending Definition (single source of truth)

- **Trending** = highest **stars gained in the last 7 days**: `Δstars = stars_now − stars_7_days_ago`.
- Each weekly run snapshots the top 50 repos by total stars. After two snapshots exist, the system computes `Δstars` per repo and publishes the top 10.
- Rationale: GitHub's own trending concept is weekly star growth; the Search API exposes no weekly-gain field, so it must be derived from consecutive snapshots.

## 4. Core Data Metrics

Fetched per repository from the GitHub Search API:

| # | Metric | Source | API field | Used for |
|---|--------|--------|-----------|----------|
| 1 | **Stars** (total) | GitHub Search API | `stargazers_count` | Ranking input |
| 2 | **Forks** (total) | GitHub Search API | `forks_count` | Display |
| 3 | **Language** (primary) | GitHub Search API | `language` | Display (nullable) |
| 4 | **Δstars** (weekly gain) | Computed | `stars_now − stars_7d_ago` | **Ranking key** |
| 5 | Rank + snapshot timestamp | Computed | — | Display, freshness |

Additional displayed metadata (from the same API response, no extra calls): `full_name`, `description`, `html_url`.

**Explicitly out of scope for metrics**: watchers, issue counts, contributors, commit activity, language share %.

## 5. Automation Flow

```
Weekly cron (Mon 00:05 UTC)
  → GitHub Search API: top 50 repos by stars (1 call)
  → persist snapshot JSON (stars, forks, language, name, url, timestamp)
  → compute Δstars vs previous snapshot
  → rank, take top 10
  → regenerate static page → deploy
```

- Failure handling: on API failure, keep the last good snapshot and republish with a stale-data indicator. Never publish an empty or partial list silently.

## 6. Scope

**In**
- Weekly automated refresh (scheduled, no manual trigger)
- Ranked top-10 list with repo name, description, link
- Stars, forks, primary language, Δstars per repo
- "As of" timestamp and refresh cadence note

**Out**
- User accounts / login
- Language or time-window filters
- Search
- Daily/monthly trending variants
- Public API, RSS, or email newsletter

## 7. Success Metrics

| Metric | Target |
|--------|--------|
| Automated runs | 100% of weekly runs succeed **or** degrade gracefully to last good data |
| Data freshness | Published list is ≤ 8 days old at all times |
| Manual effort | Zero manual steps between schedule and publish |

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| API rate limit (unauthenticated: 10 req/min, 60/hr) | One API call per run; add a PAT if ever needed |
| Search API star counts lag behind repo pages | Compare snapshots from the same source consistently |
| Repo deleted/renamed between snapshots | Skip missing repos in Δ computation; if list < 10, show fewer and flag |

## 9. Acceptance Criteria

- **AC-1** — The job runs automatically on a fixed weekly schedule with no manual trigger.
- **AC-2** — Every published repo row displays: rank (1–10), owner/repo name, description, primary language, total stars, total forks, and stars gained in the last 7 days (Δstars).
- **AC-3** — Ranking orders repos by Δstars descending; ties break by total stars, then repo name.
- **AC-4** — The list contains exactly 10 repositories once at least two snapshots exist.
- **AC-5** — `stargazers_count`, `forks_count`, and `language` are fetched from the GitHub Search API and persisted in the snapshot; the page renders these values unmodified.
- **AC-6** — Repos with a null language render without error (shown as "Unknown").
- **AC-7** — If the API call fails, the site keeps the previous week's list and shows a stale-data indicator with the last successful fetch timestamp.
- **AC-8** — The page displays an "as of" UTC timestamp for the data.
- **AC-9** — Each repo link opens the correct GitHub repository page in a new tab.
- **AC-10** — Page renders correctly on desktop and mobile (~400px width) with no horizontal scrolling.

## 10. Open Questions

1. Publish channel: GitHub Pages vs. a custom domain? (Default: GitHub Pages.)
2. Is the "top 50 by stars" candidate pool acceptable, or do we need the full trending candidates set (larger pool, more API calls)?
