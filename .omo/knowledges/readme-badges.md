# README badges

- The README header uses centered, linked Shields.io badges with `style=flat-square`.
- Reference: `https://github.com/ControlNet/pytorch-jupyter-docker`, whose README links a Docker image-size badge to Docker Hub.
- Docker badges target `controlnet/citation-badge`: image size explicitly uses `latest`, and pulls show the repository download count.
- Workflow badges target `build.yml` and `docker-publish.yml` on `master` and link to their respective GitHub Actions pages.
- Header images have descriptive English alt text. Query-string ampersands are escaped as `&amp;` in HTML attributes.
- Verified on 2026-09-05: the four new Shields.io endpoints returned SVGs with meaningful labels; both workflows reported passing, and Docker size and pull count were available. These values are live and may change. `git diff --check` passed.
