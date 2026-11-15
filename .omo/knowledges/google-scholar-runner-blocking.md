# Google Scholar blocks GitHub-hosted runners most of the time

- Date: 2026-11-15
- Over 29 completed Build runs of a 4-profile fork (2026-11-06 to 2026-11-13), Google Scholar answered in only about 7. Outcomes were all-or-nothing per run: a good run finished the whole job in about 70 s, a blocked run spent 4 x 180 s waiting for every profile to time out. The block is per runner IP, not per profile.
- A blocked run still ends green: previous data is preserved as stale, nothing is pushed to `dist`, and only the job summary shows the failure. Check `generated_at` in `citation.json`, not the workflow status, to judge freshness.
- Why it shows up as a timeout: without a proxy, `scholarly 1.7.11` handles HTTP 403 by sleeping 60-120 s and retrying with a new session without counting the attempt (`_navigator._get_page`), so it never gives up by itself and the `--timeout` kill is the only exit.
- Mitigations in `main.py`:
  - Fail fast: after one profile times out or raises `MaxTriesExceededException`, the remaining profiles are skipped for that run. A blocked run now costs one timeout instead of one per profile.
  - Fewer requests: `scholarly.fill(..., sections=["basics", "indices", "counts", "publications"])`. Measured live on a 28-paper profile: 1 request instead of 2 (the dropped one is the `list_mandates` public-access page; profiles with more than 20 co-authors also drop the full co-author page). The citation metrics and publication list are identical. `scholarly` sorts the passed list in place, so pass a fresh list each call.
  - `build.yml` only runs on pushes that touch `main.py`, `openalex.py`, `profile_deploy.py`, `requirements.txt` or the workflow itself; docs-only pushes no longer scrape.
- Not done: retrying on a fresh runner (new IP) after a blocked run, and surfacing staleness as a failed or warning status.
- The profile fetch runs in a forked child. Its result must be read from the pipe before joining the child: a child that has sent more than the 64 KiB pipe buffer cannot exit until the parent reads, so `join()` first turned every profile above roughly 290 publications into a false timeout. `main.py` now uses `Pipe` + `poll(timeout)` + `recv()`, with the parent's copy of the write end closed so a crashed child reads as EOF.
