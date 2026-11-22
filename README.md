# Citation Badge

<div align="center">
    <a href="https://github.com/ControlNet/citation-badge/issues">
        <img src="https://img.shields.io/github/issues/ControlNet/citation-badge?style=flat-square" alt="GitHub issues">
    </a>
    <a href="https://github.com/ControlNet/citation-badge/network/members">
        <img src="https://img.shields.io/github/forks/ControlNet/citation-badge?style=flat-square" alt="GitHub forks">
    </a>
    <a href="https://github.com/ControlNet/citation-badge/stargazers">
        <img src="https://img.shields.io/github/stars/ControlNet/citation-badge?style=flat-square" alt="GitHub stars">
    </a>
    <a href="https://github.com/ControlNet/citation-badge/blob/master/LICENSE">
        <img src="https://img.shields.io/github/license/ControlNet/citation-badge?style=flat-square" alt="License">
    </a>
    <a href="https://github.com/ControlNet/citation-badge/actions/workflows/build.yml">
        <img src="https://img.shields.io/github/actions/workflow/status/ControlNet/citation-badge/build.yml?branch=master&amp;style=flat-square&amp;logo=githubactions&amp;label=Badges&amp;cacheSeconds=3600" alt="Badge generation workflow status">
    </a>
    <a href="https://github.com/ControlNet/citation-badge/actions/workflows/docker-publish.yml">
        <img src="https://img.shields.io/github/actions/workflow/status/ControlNet/citation-badge/docker-publish.yml?branch=master&amp;style=flat-square&amp;logo=githubactions&amp;label=Docker%20publish" alt="Docker publishing workflow status">
    </a>
    <a href="https://hub.docker.com/r/controlnet/citation-badge">
        <img src="https://img.shields.io/docker/image-size/controlnet/citation-badge/latest?style=flat-square&amp;logo=docker&amp;label=Docker" alt="Docker image size for latest">
    </a>
    <a href="https://hub.docker.com/r/controlnet/citation-badge">
        <img src="https://img.shields.io/docker/pulls/controlnet/citation-badge?style=flat-square" alt="Docker Hub pulls">
    </a>
</div>

Automatically generate Google Scholar citation badges, peer-review badges, and a JSON metadata feed, hosted on GitHub Pages or self-hosted with Docker.

**Example:** <img src="https://cite.controlnet.space/all.svg" alt="Citations badge"> <img src="https://cite.controlnet.space/review.svg" alt="Reviews badge">

## Deployment

### Option 1: GitHub Pages (Serverless)

1. **Fork** this repository.
2. Add repository secrets under **Settings → Secrets and variables → Actions** (`SCHOLAR` is required; see [Configuration](#configuration) for optional secrets).
3. Run the **Build** workflow once (or wait for the hourly schedule), then enable **GitHub Pages** (**Settings → Pages**) from the `dist` branch.

### Option 2: Docker (Self-hosted)

```bash
docker run -d --restart unless-stopped --name citation-badge \
  -p 8000:8000 \
  -v "$PWD/data:/data" \
  -e PUID="$(id -u)" \
  -e PGID="$(id -g)" \
  -e SCHOLAR="WLN3QrAAAAAJ" \
  controlnet/citation-badge
```

Files are served directly at `http://localhost:8000/` (e.g., `http://localhost:8000/all.svg`).

## Usage

Badges update hourly. Embed them in Markdown or HTML, or fetch `citation.json` for your personal website:

```markdown
![Citations](https://<username>.github.io/citation-badge/all.svg)
![Paper Citations](https://<username>.github.io/citation-badge/<SCHOLAR_ID>_<PUB_ID>.svg)
![Peer Reviews](https://<username>.github.io/citation-badge/review.svg)
```

| Path | Content |
| :--- | :--- |
| `/all.svg` | Total citations badge |
| `/<SCHOLAR_ID>_<PUB_ID>.svg` | Per-paper citation badge (`:` in Scholar's `author_pub_id` replaced with `_`) |
| `/review.svg` | Peer-review badge (when `PEER_REVIEW` is set) |
| `/citation.json` | JSON feed with citation counts, h-index, i10-index, yearly counts, and publications |
| `/<SCHOLAR_ID>/*` | Per-profile files when `SCHOLAR` contains multiple comma-separated IDs (the first ID is also served at `/`) |

## Configuration

| Name | Scope | Description |
| :--- | :--- | :--- |
| `SCHOLAR` | Both | **Required.** Google Scholar ID (or comma-separated IDs for multiple profiles) |
| `PEER_REVIEW` | Both | Optional non-negative integer for `review.svg` |
| `OPENALEX_API_KEY` | GitHub Actions | Optional free [OpenAlex API key](https://openalex.org/settings/api) to enrich `citation.json` with DOI, full authors, venue, and date |
| `DEPLOY_TOKEN` | GitHub Actions | Optional GitHub token (`actions:write`) to trigger a downstream website rebuild when citations change |
| `DEPLOY_TARGET` | GitHub Actions | Target workflow for `DEPLOY_TOKEN`, formatted as `owner/repo@ref:workflow_id` |
| `CRON_SCHEDULE` | Docker | Optional refresh cron expression (defaults to `0 * * * *`, UTC) |
| `PUID` / `PGID` | Docker | Optional container UID/GID for volume ownership (defaults to `1000` / `1000`) |
