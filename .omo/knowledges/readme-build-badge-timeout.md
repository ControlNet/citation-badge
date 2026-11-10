# README Build badge timeout

- Date: 2026-11-10
- The shields.io badge `github/actions/workflow/status/ControlNet/citation-badge/build.yml?branch=master` intermittently returned HTTP 408 after about 8 s, so the README showed a broken image. shields.io serves it from cache when warm, but a cold fetch has to query GitHub's workflow-runs API, and with more than 5,400 Build runs (mostly hourly schedules) that query regularly exceeds shields' upstream timeout.
- Adding `event=push` made the shields query fast (about 0.6 s), but the badge would then ignore the scheduled runs that actually regenerate the badges.
- The README now uses GitHub's native badge `https://github.com/ControlNet/citation-badge/actions/workflows/build.yml/badge.svg?branch=master`, which reports the latest run on `master` across all events and does not go through shields' timeout. It uses GitHub's own style, not `flat-square`.
- The Docker publish workflow has few runs, so its shields badge stays fast and unchanged.
