# Docker Hub CI status

Updated on 2026-09-05.

- `.github/workflows/docker-publish.yml` builds the root `Dockerfile` and pushes `controlnet/citation-badge:latest` for `linux/amd64` on pushes to `master` or `main`, or on manual dispatch.
- Docker Hub login references repository Actions secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_PASSWORD`. The user reports that both are configured; their values and remote permissions were not inspected.
- Buildx uses GitHub Actions caching. A shared concurrency group serializes publishing jobs without cancelling an active upload.
- `.github/workflows/build.yml` remains the independent badge generation workflow, including its hourly schedule, `dist` publishing, and optional deployment dispatch.
- Workflow validation command: `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/docker-publish.yml`. Expected result: exit 0 with no diagnostics.
- Validation passed: Actionlint, `git diff --check`, and the secret scanner on `.github/workflows`.
- Local build passed with `docker build --platform linux/amd64 --tag citation-badge:ci-verification .`; the image was exported successfully. Docker Hub login and push have not been exercised by a remote workflow run.
- After a successful remote publishing run, verify availability with `docker pull controlnet/citation-badge:latest`.
- The existing `.gitignore` covers `.env` but lacks common credential patterns such as private key files and `credentials.json`. Add appropriate ignore rules before storing such files locally; this workflow uses GitHub Secrets and creates no local credential files.
