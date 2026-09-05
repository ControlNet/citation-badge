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
        <img src="https://img.shields.io/github/actions/workflow/status/ControlNet/citation-badge/build.yml?branch=master&amp;style=flat-square&amp;logo=githubactions&amp;label=Badges" alt="Badge generation workflow status">
    </a>
    <a href="https://github.com/ControlNet/citation-badge/actions/workflows/docker-publish.yml">
        <img src="https://img.shields.io/github/actions/workflow/status/ControlNet/citation-badge/docker-publish.yml?branch=master&amp;style=flat-square&amp;logo=githubactions&amp;label=Docker%20publish" alt="Docker publishing workflow status">
    </a>
    <a href="https://hub.docker.com/r/controlnet/citation-badge">
        <img src="https://img.shields.io/docker/image-size/controlnet/citation-badge/latest?style=flat-square&amp;logo=docker&amp;label=Docker" alt="Docker image size for latest">
    </a>
    <a href="https://hub.docker.com/r/controlnet/citation-badge">
        <img src="https://img.shields.io/docker/pulls/controlnet/citation-badge?style=flat-square&amp;logo=docker" alt="Docker Hub pulls">
    </a>
</div>

Automatically generate citation badges from Google Scholar and a manually supplied peer review count.

### Example:

Citations badge: <img src="https://cite.controlnet.space/all.svg">
Reviews badge: <img src="https://cite.controlnet.space/review.svg">


## Quick Setup

1. **Fork this repository**
2. **Set up GitHub Secrets** (Repository Settings → Secrets → Actions):
   - `SCHOLAR`: Your Google Scholar ID
   - `PEER_REVIEW`: Your peer review count (optional)
   - `DEPLOY_TOKEN`: Used with `DEPLOY_TARGET` to trigger another repository's deployment workflow after citation data updates (optional)
   - `DEPLOY_TARGET`: Target workflow in `owner/repo@ref:workflow_id` format, such as `yourusername/your-site@main:deploy.yml` (optional)
3. **Enable GitHub Pages** to use the `dist` branch

## Self-hosted Docker runtime

This is additive to the existing GitHub Actions/GitHub Pages flow, not a replacement.

Run the service:

```bash
docker run --rm -d --name citation-badge \
  -p 8000:8000 \
  -v "$PWD/data:/data" \
  -e PUID="$(id -u)" \
  -e PGID="$(id -g)" \
  -e SCHOLAR='WLN3QrAAAAAJ' \
  controlnet/citation-badge
```

Or if you prefer to build by yourself:

```bash
docker build -t controlnet/citation-badge .
```

Badge input env vars:

- `SCHOLAR`: Your Google Scholar ID (required)
- `PEER_REVIEW` is optional and generates the peer review badge when set to a non-negative integer

Optional runtime user mapping:

- `PUID` defaults to `1000`
- `PGID` defaults to `1000`
- Set them to `$(id -u)` / `$(id -g)` if you want the containerized service process to match your current host user

Mounted state volume:

- `-v "$PWD/data:/data"` keeps the service’s runtime state and latest promoted release outside the container.

Then you can access the served files as same as the GitHub, such as `localhost:8000/all.svg`, `localhost:8000/citation.json`, etc.

### Automatic Docker Hub publishing

The `Publish Docker image` workflow builds and pushes
`controlnet/citation-badge:latest` for `linux/amd64` on pushes to `master` or
`main`. It can also be run manually from the repository's Actions tab. It uses
GitHub Actions build caching and runs independently of the badge update workflow.

Configure these repository Actions secrets:

- `DOCKERHUB_USERNAME`: Docker Hub username with write access to `controlnet/citation-badge`.
- `DOCKERHUB_PASSWORD`: Docker Hub access token or password with permission to push the image.

Keep credentials in GitHub Secrets; do not put them in source files or commit a
local `.env.local` file. Add `.env.local` to `.gitignore` if using it locally.

After the workflow succeeds, pull the published image:

```bash
docker pull controlnet/citation-badge:latest
```

## Usage

Badges update automatically hourly. Embed them in your sites:

```markdown
![Citations](https://yourusername.github.io/citation-badge/all.svg)
![Paper Citations](https://yourusername.github.io/citation-badge/<GOOGLE_SCHOLAR_ID>_<PUBLICATION_ID>.svg)
![Peer Reviews](https://yourusername.github.io/citation-badge/review.svg)
```
