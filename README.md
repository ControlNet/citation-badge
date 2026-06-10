# Citation Badge


<div align="center">
    <a href="https://github.com/ControlNet/citation-badge/issues">
        <img src="https://img.shields.io/github/issues/ControlNet/citation-badge?style=flat-square">
    </a>
    <a href="https://github.com/ControlNet/citation-badge/network/members">
        <img src="https://img.shields.io/github/forks/ControlNet/citation-badge?style=flat-square">
    </a>
    <a href="https://github.com/ControlNet/citation-badge/stargazers">
        <img src="https://img.shields.io/github/stars/ControlNet/citation-badge?style=flat-square">
    </a>
    <a href="https://github.com/ControlNet/citation-badge/blob/master/LICENSE">
        <img src="https://img.shields.io/github/license/ControlNet/citation-badge?style=flat-square">
    </a>    
</div>

Automatically generate citation badges from Google Scholar and a manually supplied Web of Science peer review count.

### Example:

Citations badge: <img src="https://cite.controlnet.space/all.svg">
Reviews badge: <img src="https://cite.controlnet.space/review.svg">


## Quick Setup

1. **Fork this repository**
2. **Set up GitHub Secrets** (Repository Settings → Secrets → Actions):
   - `AUTHOR`: Your name as it appears on Google Scholar (at least one of `SCHOLAR` or `AUTHOR` is required)
   - `SCHOLAR`: Your Google Scholar ID (at least one of `SCHOLAR` or `AUTHOR` is required)
   - `WOS_OVERWRITE`: Your Web of Science peer review count (optional)
   - `CNAME`: Custom domain for GitHub Pages (optional)
   - `DEPLOY_TOKEN`: Used to trigger the deployment workflow if you have another repository that need to re-deploy to access the citation data. You can use personal access token of your account or the deploy token in the repository (optional)
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
  -e AUTHOR='Yann LeCun' \
  controlnet/citation-badge
```

Or if you prefer to build by yourself:

```bash
docker build -t controlnet/citation-badge .
```

Required env vars:

- `AUTHOR` or `SCHOLAR` (set at least one)
- `WOS_OVERWRITE` is optional and generates the Web of Science peer review badge when set to a non-negative integer

Optional runtime user mapping:

- `PUID` defaults to `1000`
- `PGID` defaults to `1000`
- Set them to `$(id -u)` / `$(id -g)` if you want the containerized service process to match your current host user

Mounted state volume:

- `-v "$PWD/data:/data"` keeps the service’s runtime state and latest promoted release outside the container.

Then you can access the served files as same as the GitHub, such as `localhost:8000/all.svg`, `localhost:8000/citation.json`, etc.

## Usage

Badges update automatically hourly. Embed them in your sites:

```markdown
![Citations](https://yourusername.github.io/citation-badge/all.svg)
![Paper Citations](https://yourusername.github.io/citation-badge/<GOOGLE_SCHOLAR_ID>_<PUBLICATION_ID>.svg)
![Peer Reviews](https://yourusername.github.io/citation-badge/review.svg)
```
