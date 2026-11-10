# GitHub Actions hourly schedule is not hourly

- Date: 2026-11-10
- With `cron: "0 * * * *"`, both `ControlNet/citation-badge` and its fork `VL4AI/ci-scholar` only got about 4-6 scheduled Build runs per day (gaps of 3-11 hours) between 2026-10-31 and 2026-11-10, with both repos firing within about a minute of each other.
- GitHub documents that `schedule` events can be delayed under high load, that the start of every hour is a high-load time, and that queued scheduled jobs may be dropped.
- `build.yml` now uses `cron: "37 * * * *"` to avoid minute 0. This lowers the chance of delay but does not guarantee hourly runs. If strictly hourly refreshes matter, trigger `workflow_dispatch` from an external scheduler (needs a token with Actions write access, stored outside the repo) or use the self-hosted Docker service.
- `concurrency: build-dist` queues overlapping runs, so an external trigger cannot race a scheduled run on the force-pushed `dist` branch.
