# Multi-profile Scholar publishing contract

- `SCHOLAR` may contain comma-separated Google Scholar IDs. Runtime parsing trims whitespace, drops empty entries, and deduplicates while preserving order.
- Each Scholar ID publishes independently under `dist/<SCHOLAR_ID>/` using a staging directory first. A profile directory is replaced only after a successful Google Scholar refresh.
- Failed profile refreshes never write failed `citation.json` artifacts. If a previous successful profile artifact exists, it remains stale and untouched; otherwise the profile is not published.
- The root `dist/` output remains the compatibility mirror for the first Scholar ID only. Later successful profiles must not take over root output when the first profile fails.
- `WOS_OVERWRITE` belongs to the first Scholar profile. Its `peer_reviews` value is written into `dist/<FIRST_SCHOLAR_ID>/citation.json`, and `review.svg` is generated in `dist/<FIRST_SCHOLAR_ID>/review.svg`.
- When the first profile succeeds, root output is refreshed from that first profile, including `all.svg`, paper SVGs, `review.svg`, and `citation.json`.
- Root `dist/citation.json` must match `dist/<FIRST_SCHOLAR_ID>/citation.json`; later profile JSON files keep Web of Science as `skipped` unless they become the first profile in `SCHOLAR` order.
- `citation_updated.flag=true` means the publishable contents of `dist/` changed after staging was excluded. Success attempts that rewrite identical bytes keep the flag `false`, so CI does not enter the `dist` commit/push path with nothing to commit.
- Per-profile Google Scholar refresh timeout is supplied only by the CLI `--timeout` argument. GitHub Actions passes `--timeout 180` for the fixed 3-minute profile timeout; there is no environment-variable timeout override.
