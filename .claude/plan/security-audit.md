# Security Audit — GitHub API Token Handling

**Date**: 2026-09-15
**Method**: senior-security skill — STRIDE threat modeling + `secret_scanner.py` sweep
**Scope**: scripts/, site/, public/, data/, e2e/ (incl. node_modules)

---

## 1. Secret scan (automated)

`secret_scanner.py` (20+ patterns: GitHub PATs, AWS keys, private keys, generic credentials), full-repo sweep, high-severity gate:

| Severity | Findings |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 0 |
| Low | 0 |

**Zero findings. Gate passes.** (After one hardening fix — see §4.)

## 2. Token data flow (verified end to end)

```
CI secret / env GITHUB_TOKEN ──> fetch_trending.py (memory only)
        └── Authorization: Bearer header ──> api.github.com (TLS)
                                             └── response parsed
                                                   └── only public fields persisted
```

| Check | Result |
|---|---|
| Token acquisition | Only `os.environ.get("GITHUB_TOKEN")` or `--token` arg (fetch_trending.py:275) — no hardcoded values |
| Token use | Only in `Authorization: Bearer` header construction (fetch_trending.py:93); not in URL, not in body |
| Persistence | `data/snapshots/*.json` and `data/latest.json` contain only `stars`, `forks`, `language`, `full_name`, `description`, `html_url` — **no headers, no tokens** |
| Logging | Logs only URL + rate-limit counters; header values never printed |
| Frontend bundle | `public/index.html` + `public/styles.css`: zero JS, zero env references, zero token/secret strings (only match: CSS comment about design tokens — benign) |
| Site builder | `build_site.py` receives only `latest.json` — no access to env or credentials |

## 3. STRIDE — credential disclosure focus

| DFD element | Threat | Risk | Mitigation status |
|---|---|---|---|
| Data flow: token → api.github.com | Info Disclosure (interception / http downgrade) | Low | HTTPS only; redirect-downgrade not realistic from api.github.com; urlopen drops cross-host auth headers |
| Process: fetcher | Info Disclosure (`--token` visible in `ps` during run) | Low | Prefer `GITHUB_TOKEN` env / CI secrets; CLI arg documented as fallback |
| Process: fetcher | Repudiation (no audit of who ran with which token) | Low | Single-user pipeline; CI logs provide provenance |
| Data store: snapshots | Info Disclosure (credentials accidentally persisted) | None | Verified — field whitelist in `extract_repos()` |
| External entity: site visitors | Elevation (token exposed to end users) | None | Frontend bundle contains no credentials and no code path to fetch them |

No threat reaches DREAD ≥ 7; no mitigation owner required.

## 4. Findings & actions

| # | Finding | Severity | Action |
|---|---|---|---|
| 1 | Docstring contained a literal `ghp_...` example string — trips stricter CI scanners (and invites copy-paste) | Low | ✅ Fixed: replaced with `GITHUB_TOKEN=<your-pat>` placeholder |
| 2 | `--token` CLI arg visible in process list during the run | Low | Documented: use env var or CI secrets in production (GitHub auto-redacts secrets in logs) |

## 5. CI recommendations (for the upcoming pipeline)

- Pass the PAT via GitHub Actions `secrets` — never commit it, never print it.
- Use `GITHUB_TOKEN` (the automatic Actions token) where possible; scope it to public-read.
- Add `secret_scanner.py` to the CI workflow as a merge gate (exit 0 on zero high/critical findings).
