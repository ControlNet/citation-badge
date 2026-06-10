# GitHub Pages CNAME automation

- Date: 2026-06-10
- Decision: Do not use a `CNAME` secret or Actions variable.
- The build workflow reads the repository's current GitHub Pages custom domain with `gh api -X GET repos/${GITHUB_REPOSITORY}/pages --jq '.cname // ""'`, and only trusts the output when the command exits successfully.
- If the API returns a domain, CI writes it to `dist/CNAME` before committing the dist branch.
- If the API returns no domain or Pages metadata cannot be read, including a 404 JSON error body, CI removes `dist/CNAME` so stale checked-out dist artifacts are not preserved.
