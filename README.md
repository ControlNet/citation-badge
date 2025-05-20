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

Automatically generate citation badges from Google Scholar and Web of Science webpage.

### Example:

Citations badge: <img src="https://cite.controlnet.space/all.svg">
Reviews badge: <img src="https://cite.controlnet.space/review.svg">


## Quick Setup

1. **Fork this repository**
2. **Set up GitHub Secrets** (Repository Settings → Secrets → Actions):
   - `AUTHOR`: Your name as it appears on Google Scholar (at least one of `SCHOLAR` or `AUTHOR` is required)
   - `SCHOLAR`: Your Google Scholar ID (at least one of `SCHOLAR` or `AUTHOR` is required)
   - `WOS`: Your Web of Science ID (optional)
   - `CNAME`: Custom domain for GitHub Pages (optional)
3. **Enable GitHub Pages** to use the `dist` branch

## Usage

Badges update automatically hourly. Embed them in your sites:

```markdown
![Citations](https://yourusername.github.io/citation-badge/all.svg)
![Paper Citations](https://yourusername.github.io/citation-badge/<GOOGLE_SCHOLAR_ID>_<PUBLICATION_ID>.svg)
![Peer Reviews](https://yourusername.github.io/citation-badge/review.svg)
```
