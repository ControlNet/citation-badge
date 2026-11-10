# README Build badge timeout

- Date: 2026-11-10
- The shields.io badge `github/actions/workflow/status/ControlNet/citation-badge/build.yml?branch=master` intermittently returned HTTP 408 after about 8 s, so the README showed a broken image. The Docker publish badge uses the same shields service and was not affected at that moment.
- The GitHub workflow-runs API answered in about 0.5 s for every filter tried (`branch`, `event`, both), so the timeouts came from shields.io's own upstream fetching, not from GitHub. A later test with cache-busting URLs succeeded 6/6 for every variant, which confirms the failures were intermittent.
- shields.io sends `cache-control: max-age=60` for this badge by default, so a fresh upstream fetch happens about every minute and each one can time out. Adding `cacheSeconds=3600` makes shields and GitHub's image proxy cache the badge for an hour (`max-age=3600`). The status can then lag by up to an hour, which matches the roughly hourly schedule.
- A switch to GitHub's native `actions/workflows/build.yml/badge.svg` was tried and reverted because its style does not match the other `flat-square` shields badges.
- `event=push` was also rejected: the badge would then ignore the scheduled runs that actually regenerate the badges.
