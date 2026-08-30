# Peer review input semantics

- Date: 2026-08-30
- `main.py` does not query or otherwise integrate with Web of Science.
- Decision: `PEER_REVIEW` is the only supported environment name for the manually supplied non-negative peer review count.
- `WOS_OVERWRITE` is not retained as an input fallback; missing `PEER_REVIEW` is reported as skipped in the generated summary.
- Existing CI artifact-preservation behavior is unchanged, so a previously successful `review.svg` and peer-review metadata may remain when the new input is omitted.
- The existing `citation.json.web_of_science` and `/status.sources.web_of_science` keys remain unchanged for API compatibility; changing those schemas requires a separate decision.
- The value is stored in the compatible source's `peer_reviews` field and rendered into `review.svg`.
- The GitHub Actions secret and self-hosted container environment must use `PEER_REVIEW` after this migration.
