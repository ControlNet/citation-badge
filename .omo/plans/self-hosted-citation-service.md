# Self-Hosted Citation Service

## TL;DR
> **Summary**: Add an additive self-hosted runtime around the existing batch scraper by introducing a Python HTTP service, in-process cron scheduler, and Docker packaging while preserving the current `main.py` + GitHub Actions workflow.
> **Deliverables**:
> - Long-running Python HTTP service exposing `/status`, `/citation.json`, `/all.svg`, `/review.svg`, and `/{author_pub_id}.svg`
> - In-process cron scheduling with startup refresh, single-run lock, and graceful shutdown
> - Staging-to-release promotion so partial writes are never publicly served
> - Dockerfile and README instructions for `docker run` self-hosting
> **Effort**: Large
> **Parallel**: YES - 3 waves
> **Critical Path**: 1 → 2 → 4 → 5 → 6 → 7 → 9

## Context
### Original Request
Create a Docker-deployable local service so the project no longer depends only on GitHub Actions/GitHub Pages for citation refreshes. The service should expose JSON status, support cron-like scheduled scraping, and reuse the existing `main.py` as much as possible.

### Interview Summary
- Keep the original `main.py` and keep the original CI path supported.
- New HTTP server may call `main.py` as a subprocess instead of rewriting scraper logic immediately.
- First version must expose JSON status and keep existing SVG/badge compatibility.
- First version should prioritize Google Scholar; Web of Science is optional.
- Scheduling must use cron-expression semantics.
- v1 must not add automated test infrastructure.
- Deployment scope is Dockerfile plus README `docker run` instructions; no compose requirement.

### Metis Review (gaps addressed)
- Freeze exact HTTP contract now instead of leaving endpoint/status behavior ambiguous.
- Treat service mode as additive wrapper, not scraper rewrite.
- Prevent artifact corruption by running `main.py` in a staging release directory and atomically switching the public release pointer.
- Keep CI-only workflow artifacts (`citation_updated.flag`, `summary.md`) out of the self-hosted public contract.
- Define explicit empty-state behavior, overlap policy, startup behavior, and shutdown behavior.

## Work Objectives
### Core Objective
Ship a self-hosted runtime that serves the latest successful citation artifacts locally from Docker, refreshes on a cron schedule, and preserves the existing GitHub Actions batch workflow unchanged as a supported alternative path.

### Deliverables
- New Python service package under `service/`
- Self-hosted HTTP API and artifact-serving contract
- APScheduler-based cron execution loop
- Dedicated runtime state layout under `/data`
- Dockerfile using exec-form `CMD`
- README section documenting self-hosted `docker build` and `docker run`

### Definition of Done (verifiable conditions with commands)
- `docker build -t citation-badge:self-hosted .` succeeds.
- `docker run --rm -d --name citation-svc -p 8000:8000 -v "$PWD/data:/data" citation-badge:self-hosted` starts and stays healthy.
- `curl -s http://127.0.0.1:8000/status | python -c "import json,sys; d=json.load(sys.stdin); assert d['service']['mode']=='self_hosted'; assert d['schedule']['cron']; assert 'google_scholar' in d['sources']"` passes.
- On a fresh volume with no successful run, `curl -s -o /tmp/citation.json -w '%{http_code}' http://127.0.0.1:8000/citation.json` returns `503` and `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/all.svg` returns `404`.
- After one successful refresh, `/citation.json` returns `200` JSON and `/all.svg` returns `200` with `Content-Type: image/svg+xml`.
- Stale-on-failure behavior preserves the previous successful `/citation.json` and `/all.svg` after a later refresh failure.
- Running `timeout 3m python -u main.py --author "$AUTHOR" --scholar "$SCHOLAR" --wos "$WOS" --gen_summary` continues to work for CI/batch mode.

### Must Have
- Preserve existing `main.py` CLI behavior and `.github/workflows/build.yml` compatibility.
- Reuse the existing `main.py` batch flow via subprocess from the service.
- Exact HTTP contract:
  - `GET /status` → `200 application/json`
  - `GET /citation.json` → `200 application/json` when data exists, otherwise `503 application/json` with `{"error":"no_data","message":"No successful refresh yet"}`
  - `GET /all.svg`, `GET /review.svg`, `GET /{author_pub_id}.svg` → `200 image/svg+xml` when file exists, otherwise `404 text/plain`
- Exact `/status` schema:
  - `service`: `{mode,status,version}`
  - `schedule`: `{cron,timezone,refresh_on_startup,overlap_policy,running,next_run_at,last_started_at,last_finished_at}`
  - `storage`: `{state_dir,current_release,has_data}`
  - `sources.google_scholar`: `{enabled,status,last_attempt_at,last_success_at,last_error}`
  - `sources.web_of_science`: `{enabled,status,last_attempt_at,last_success_at,last_error}`
- Runtime defaults:
  - `APP_HOST=0.0.0.0`
  - `APP_PORT=8000`
  - `STATE_DIR=/data`
  - `CRON_SCHEDULE=0 * * * *`
  - `TIMEZONE=UTC`
  - `REFRESH_ON_STARTUP=1`
  - `WORKER_TIMEOUT_SECONDS=180`
  - `ENABLE_WOS=0`
- Overlap policy: if a refresh is already running, the next scheduled trigger is skipped and status remains consistent.
- Empty-state policy: `/status` reports `storage.has_data=false`, `sources.google_scholar.status="never_succeeded"`, `sources.web_of_science.status="disabled"` when `ENABLE_WOS=0`, `/citation.json` returns `503`, SVG routes return `404`.
- Startup policy: perform one immediate refresh attempt after service boot when `REFRESH_ON_STARTUP=1`; do not replay missed cron runs beyond that startup refresh.
- Shutdown policy: on `SIGTERM`, stop accepting new scheduled refreshes, terminate in-flight worker subprocess cleanly, and never promote a partial release.

### Must NOT Have (guardrails, AI slop patterns, scope boundaries)
- Must NOT rewrite `main.py` into a shared in-process library in v1.
- Must NOT add Compose, Redis, Celery, a database, auth, admin UI, or a reverse proxy.
- Must NOT serve files directly from the worker’s live write directory.
- Must NOT expose `citation_updated.flag` or `summary.md` as self-hosted public artifacts.
- Must NOT break or rename the existing SVG filenames documented in `README.md`.
- Must NOT make WOS mandatory in the default Docker path.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: none in-repo for v1; use agent-executed Docker/Bash verification only.
- QA policy: Every task includes a happy path and failure/edge path.
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}`

## Execution Strategy
### Parallel Execution Waves
> Target: 5-8 tasks per wave. <3 per wave (except final) = under-splitting.
> Extract shared dependencies as Wave-1 tasks for max parallelism.

Wave 1: contract and skeleton foundations
- 1. Freeze service contract and config defaults
- 2. Bootstrap runtime state model and metadata persistence
- 3. Add HTTP server skeleton and `/status` empty-state behavior

Wave 2: safe worker execution and artifact publishing
- 4. Add subprocess worker wrapper for `main.py`
- 5. Implement staging releases and atomic public promotion
- 6. Serve `citation.json` and SVG compatibility routes from current release

Wave 3: orchestration and packaging
- 7. Add APScheduler cron loop, overlap skip, and graceful shutdown
- 8. Wire source toggles and preserve CI-mode compatibility boundaries
- 9. Package with Dockerfile and document self-hosted usage in README

### Dependency Matrix (full, all tasks)
- 1 blocks 2, 3, 4, 6, 7, 8, 9
- 2 blocks 3, 5, 6, 7
- 3 blocks 6
- 4 blocks 5, 7, 8
- 5 blocks 6
- 6 blocks 9 verification
- 7 blocks 9 verification
- 8 blocks 9 verification
- 9 depends on 6, 7, 8

### Agent Dispatch Summary (wave → task count → categories)
- Wave 1 → 3 tasks → `deep`, `unspecified-high`, `unspecified-high`
- Wave 2 → 3 tasks → `unspecified-high`, `unspecified-high`, `unspecified-high`
- Wave 3 → 3 tasks → `unspecified-high`, `unspecified-high`, `quick`

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Freeze service contract and config defaults

  **What to do**: Create the service package contract under `service/` and define exact env/config names, `/status` schema, route behavior, empty-state semantics, startup policy, overlap policy, and the runtime path contract (`/app` code, `/data` writable state). Encode these decisions in a central config/state module before any worker logic.
  **Must NOT do**: Do not change `main.py` CLI flags or `.github/workflows/build.yml`. Do not introduce extra routes beyond `/status`, `/citation.json`, `/all.svg`, `/review.svg`, and `/{author_pub_id}.svg`.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: This task freezes the entire contract and avoids downstream ambiguity.
  - Skills: `[]` - No special skill is required.
  - Omitted: `["playwright", "git-master"]` - No browser UI and no git-only workflow work.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 2, 3, 4, 6, 7, 8, 9 | Blocked By: none

  **References** (executor has NO interview context - be exhaustive):
  - Pattern: `main.py:35-43` - Existing CLI input contract to preserve conceptually (`--author`, `--scholar`, `--wos`, `--gen_summary`).
  - Pattern: `main.py:188-257` - Existing citation JSON preservation semantics to preserve conceptually.
  - Pattern: `.github/workflows/build.yml:48-71` - Existing batch invocation and update-flag workflow that must keep working unchanged.
  - Pattern: `README.md:38-46` - Existing public SVG path contract to preserve.

  **Acceptance Criteria** (agent-executable only):
  - [ ] `python -c "from service.config import Settings; s=Settings(); assert s.app_host=='0.0.0.0'; assert s.app_port==8000; assert s.state_dir=='/data'; assert s.cron_schedule=='0 * * * *'; assert s.timezone=='UTC'; assert s.enable_wos is False"`
  - [ ] `python -c "from service.state import empty_status; d=empty_status(); assert d['service']['mode']=='self_hosted'; assert d['schedule']['overlap_policy']=='skip'; assert d['storage']['has_data'] is False; assert d['sources']['google_scholar']['status']=='never_succeeded'; assert d['sources']['web_of_science']['status'] in ('disabled','never_succeeded')"`

  **QA Scenarios** (MANDATORY - task incomplete without these):
  ```
  Scenario: Contract defaults are deterministic
    Tool: Bash
    Steps: python -c "from service.config import Settings; print(Settings().model_dump() if hasattr(Settings(),'model_dump') else Settings().__dict__)" > .sisyphus/evidence/task-1-contract-defaults.txt
    Expected: Evidence file contains APP_HOST=0.0.0.0, APP_PORT=8000, STATE_DIR=/data, CRON_SCHEDULE='0 * * * *', TIMEZONE='UTC', ENABLE_WOS=False
    Evidence: .sisyphus/evidence/task-1-contract-defaults.txt

  Scenario: Empty-state schema is machine-readable
    Tool: Bash
    Steps: python -c "from service.state import empty_status; import json; print(json.dumps(empty_status(), sort_keys=True))" > .sisyphus/evidence/task-1-contract-empty.json
    Expected: JSON includes keys service, schedule, storage, sources.google_scholar, sources.web_of_science
    Evidence: .sisyphus/evidence/task-1-contract-empty.json
  ```

  **Commit**: YES | Message: `feat(service): define self-hosted contract and defaults` | Files: `service/__init__.py`, `service/config.py`, `service/state.py`

- [x] 2. Bootstrap runtime state model and metadata persistence

  **What to do**: Implement the writable runtime layout under `/data` with `releases/`, `status.json`, and `current` release pointer semantics. Add helpers that initialize missing directories, load persisted metadata safely, and persist service status atomically.
  **Must NOT do**: Do not write public artifacts to repo root. Do not use SQLite, Redis, or any external persistence layer.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: Requires careful filesystem and corruption-handling logic.
  - Skills: `[]` - No special skill is required.
  - Omitted: `["playwright", "git-master"]` - No UI or git specialization needed.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 3, 5, 6, 7 | Blocked By: 1

  **References**:
  - Pattern: `main.py:46-47` - Existing assumption that output is written into a `dist/` directory.
  - Pattern: `main.py:193-201` - Existing defensive read of previous JSON to preserve data when current run fails.
  - Pattern: `main.py:247-262` - Existing “last successful data wins” logic to preserve semantically.

  **Acceptance Criteria**:
  - [ ] `python -c "from service.storage import ensure_state_layout; p=ensure_state_layout('/tmp/citation-state'); import os; assert os.path.isdir('/tmp/citation-state/releases'); assert os.path.isfile('/tmp/citation-state/status.json')"`
  - [ ] `python -c "from service.storage import atomic_write_json, load_json_file; p='/tmp/citation-state/status.json'; atomic_write_json(p, {'ok': True}); assert load_json_file(p)['ok'] is True"`

  **QA Scenarios**:
  ```
  Scenario: Fresh state directory initializes correctly
    Tool: Bash
    Steps: rm -rf /tmp/citation-state && python -c "from service.storage import ensure_state_layout; ensure_state_layout('/tmp/citation-state')" && ls -R /tmp/citation-state > .sisyphus/evidence/task-2-state-layout.txt
    Expected: Evidence shows releases/ and status.json under /tmp/citation-state
    Evidence: .sisyphus/evidence/task-2-state-layout.txt

  Scenario: Corrupt status file does not crash loader
    Tool: Bash
    Steps: mkdir -p /tmp/citation-state && printf '{bad json' > /tmp/citation-state/status.json && python -c "from service.storage import safe_load_status; import json; print(json.dumps(safe_load_status('/tmp/citation-state/status.json')))" > .sisyphus/evidence/task-2-state-corrupt.json
    Expected: Loader returns a valid fallback structure instead of raising
    Evidence: .sisyphus/evidence/task-2-state-corrupt.json
  ```

  **Commit**: YES | Message: `feat(service): add runtime state storage helpers` | Files: `service/storage.py`, `service/state.py`

- [x] 3. Add HTTP server skeleton and `/status` empty-state behavior

  **What to do**: Implement a minimal Python HTTP server (stdlib `ThreadingHTTPServer` + request handler) that starts on `APP_HOST:APP_PORT`, loads persisted status, and serves `GET /status` as JSON with the exact schema from Task 1. Empty-state behavior must work before any refresh succeeds.
  **Must NOT do**: Do not add FastAPI/Flask. Do not serve artifacts yet.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: Introduces the runtime entrypoint and HTTP contract.
  - Skills: `[]` - No special skill is required.
  - Omitted: `["playwright", "ui-ux-pro-max"]` - No browser UI or design work.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: 6 | Blocked By: 1, 2

  **References**:
  - Pattern: `README.md:23-24` - Existing self-hosted public expectation is HTTP-served artifacts.
  - Pattern: `main.py:18-31` - Existing metadata shape to mirror at source level.
  - API/Type: `service/state.py` - Contract defined in Task 1.

  **Acceptance Criteria**:
  - [ ] `timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; curl -s http://127.0.0.1:8000/status | python -c "import json,sys; d=json.load(sys.stdin); assert d['service']['mode']=='self_hosted'; assert d['storage']['has_data'] is False"; kill $svc; wait $svc || true`
  - [ ] `timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; test "$(curl -s -o /tmp/status-body.json -w '%{http_code}' http://127.0.0.1:8000/status)" = "200"; kill $svc; wait $svc || true`

  **QA Scenarios**:
  ```
  Scenario: Empty-state /status is served on boot
    Tool: Bash
    Steps: rm -rf /tmp/citation-state && STATE_DIR=/tmp/citation-state timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; curl -s http://127.0.0.1:8000/status > .sisyphus/evidence/task-3-status-empty.json; kill $svc; wait $svc || true
    Expected: Evidence JSON has storage.has_data=false and schedule.running=false
    Evidence: .sisyphus/evidence/task-3-status-empty.json

  Scenario: Unknown route returns 404 without crashing server
    Tool: Bash
    Steps: STATE_DIR=/tmp/citation-state timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/not-found > .sisyphus/evidence/task-3-status-404.txt; kill $svc; wait $svc || true
    Expected: Evidence contains 404
    Evidence: .sisyphus/evidence/task-3-status-404.txt
  ```

  **Commit**: YES | Message: `feat(service): add status endpoint skeleton` | Files: `service/server.py`, `service/state.py`, `service/storage.py`

- [x] 4. Add subprocess worker wrapper for `main.py`

  **What to do**: Implement a worker wrapper that constructs the existing `main.py` command, executes it with `shell=False`, runs it inside a per-run staging directory, passes through `AUTHOR`, `SCHOLAR`, and `WOS` only when enabled, enforces `WORKER_TIMEOUT_SECONDS`, and records attempt metadata for both sources.
  **Must NOT do**: Do not import `main.py` as a Python module. Do not run the worker in `/app` or repo root.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: Subprocess and source-toggle behavior is central and failure-prone.
  - Skills: `[]` - No special skill is required.
  - Omitted: `["playwright", "git-master"]` - No UI and no git-specific work.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 5, 7, 8 | Blocked By: 1

  **References**:
  - Pattern: `main.py:49-127` - Google Scholar fetch flow and failure handling.
  - Pattern: `main.py:128-186` - WOS fetch flow and optional behavior.
  - Pattern: `main.py:274-294` - `summary.md` generation is CI-specific and should not be invoked in service mode.
  - Pattern: `.github/workflows/build.yml:48-50` - Existing CLI invocation shape for compatibility.

  **Acceptance Criteria**:
  - [ ] `python -c "from service.worker import build_worker_argv; argv=build_worker_argv(author='Yann LeCun', scholar='', wos='', enable_wos=False); assert argv[:2]==['python','/app/main.py']; assert '--author' in argv; assert '--gen_summary' not in argv; assert '--wos' not in argv"`
  - [ ] `python -c "from service.worker import should_enable_wos; assert should_enable_wos(False, '') is False; assert should_enable_wos(True, 'ABC123') is True"`

  **QA Scenarios**:
  ```
  Scenario: Worker argv preserves main.py compatibility
    Tool: Bash
    Steps: python -c "from service.worker import build_worker_argv; print(build_worker_argv(author='Yann LeCun', scholar='', wos='', enable_wos=False))" > .sisyphus/evidence/task-4-worker-argv.txt
    Expected: Evidence shows python /app/main.py with --author and no --gen_summary/--wos
    Evidence: .sisyphus/evidence/task-4-worker-argv.txt

  Scenario: Timeout/failure updates metadata rather than crashing service code
    Tool: Bash
    Steps: python -c "from service.worker import record_failure_result; import json; print(json.dumps(record_failure_result('google_scholar','timeout')))" > .sisyphus/evidence/task-4-worker-failure.json
    Expected: Evidence JSON marks source status as failed or stale and contains last_error='timeout'
    Evidence: .sisyphus/evidence/task-4-worker-failure.json
  ```

  **Commit**: YES | Message: `feat(service): wrap main script as subprocess worker` | Files: `service/worker.py`, `service/config.py`, `service/state.py`

- [x] 5. Implement staging releases and atomic public promotion

  **What to do**: After a worker run, validate staged output, create a versioned release under `STATE_DIR/releases/<run-id>/dist`, atomically switch `STATE_DIR/current` to the latest successful release, and leave the previous successful release untouched on failed runs. Promotion must require a valid staged `dist/citation.json`.
  **Must NOT do**: Do not expose staged files directly. Do not overwrite the current release if the staged run failed or produced incomplete output.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: This task prevents partial data exposure and stale-data regression.
  - Skills: `[]` - No special skill is required.
  - Omitted: `["playwright", "git-master"]` - Filesystem correctness, not UI/git work.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 6 | Blocked By: 2, 4

  **References**:
  - Pattern: `main.py:188-257` - Existing data-preservation semantics to preserve at the release level.
  - Pattern: `main.py:81-105` - Expected staged artifact set includes `all.svg` and per-publication SVG files.
  - Pattern: `main.py:167-172` - Optional `review.svg` generation when WOS succeeds.

  **Acceptance Criteria**:
  - [ ] `python -c "from service.promote import promote_release, current_release_path; import os, json, tempfile; base=tempfile.mkdtemp(); staged=os.path.join(base,'staged','dist'); os.makedirs(staged); open(os.path.join(staged,'all.svg'),'w').write('<svg/>'); open(os.path.join(staged,'citation.json'),'w').write('{}'); promote_release(base, os.path.join(base,'staged')); assert os.path.islink(os.path.join(base,'current')) or os.path.exists(os.path.join(base,'current')); assert current_release_path(base)"`
  - [ ] `python -c "from service.promote import validate_staged_release; import os, tempfile; base=tempfile.mkdtemp(); staged=os.path.join(base,'staged'); os.makedirs(os.path.join(staged,'dist')); assert validate_staged_release(staged) is False"`

  **QA Scenarios**:
  ```
  Scenario: Successful staged release becomes current atomically
    Tool: Bash
    Steps: python - <<'PY' > .sisyphus/evidence/task-5-promote-success.txt
from service.promote import promote_release, current_release_path
import os, tempfile
base=tempfile.mkdtemp()
staged=os.path.join(base,'staged')
os.makedirs(os.path.join(staged,'dist'))
open(os.path.join(staged,'dist','citation.json'),'w').write('{}')
open(os.path.join(staged,'dist','all.svg'),'w').write('<svg/>')
promote_release(base, staged)
print(current_release_path(base))
PY
    Expected: Evidence prints a non-empty current release path
    Evidence: .sisyphus/evidence/task-5-promote-success.txt

  Scenario: Invalid staged release is rejected and old release stays current
    Tool: Bash
    Steps: python - <<'PY' > .sisyphus/evidence/task-5-promote-failure.txt
from service.promote import promote_release
import os, tempfile
base=tempfile.mkdtemp()
good=os.path.join(base,'good')
os.makedirs(os.path.join(good,'dist'))
open(os.path.join(good,'dist','citation.json'),'w').write('{}')
open(os.path.join(good,'dist','all.svg'),'w').write('<svg/>')
promote_release(base, good)
bad=os.path.join(base,'bad')
os.makedirs(os.path.join(bad,'dist'))
try:
    promote_release(base, bad)
except Exception as e:
    print(type(e).__name__)
PY
    Expected: Evidence shows promotion rejected; prior release remains untouched
    Evidence: .sisyphus/evidence/task-5-promote-failure.txt
  ```

  **Commit**: YES | Message: `feat(service): add staged release promotion` | Files: `service/promote.py`, `service/storage.py`, `service/state.py`

- [x] 6. Serve `citation.json` and SVG compatibility routes from current release

  **What to do**: Extend the HTTP handler so `/citation.json` reads from `STATE_DIR/current/dist/citation.json`, `/all.svg` and `/review.svg` map to the current release, and any `/{author_pub_id}.svg` path reads the matching current artifact. Implement exact empty/missing response behavior and content types.
  **Must NOT do**: Do not synthesize SVG content in the HTTP layer. Do not expose directory listing or arbitrary file reads.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: This defines the externally consumed compatibility surface.
  - Skills: `[]` - No special skill is required.
  - Omitted: `["playwright", "ui-ux-pro-max"]` - HTTP artifact serving only.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: 9 | Blocked By: 1, 3, 5

  **References**:
  - Pattern: `README.md:23-24` - Existing badge URLs are `/all.svg` and `/review.svg`.
  - Pattern: `README.md:42-45` - Existing per-publication SVG naming convention.
  - Pattern: `main.py:81-105` - Artifact filenames created today.
  - Pattern: `main.py:190-252` - `citation.json` is the canonical machine-readable snapshot.

  **Acceptance Criteria**:
  - [ ] `mkdir -p /tmp/citation-state/releases/r1/dist && printf '{}' > /tmp/citation-state/releases/r1/dist/citation.json && printf '<svg/>' > /tmp/citation-state/releases/r1/dist/all.svg && ln -sfn /tmp/citation-state/releases/r1 /tmp/citation-state/current && STATE_DIR=/tmp/citation-state timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; test "$(curl -s -o /tmp/body -w '%{http_code}' http://127.0.0.1:8000/citation.json)" = "200"; kill $svc; wait $svc || true`
  - [ ] `mkdir -p /tmp/citation-state/releases/r1/dist && printf '<svg/>' > /tmp/citation-state/releases/r1/dist/all.svg && ln -sfn /tmp/citation-state/releases/r1 /tmp/citation-state/current && STATE_DIR=/tmp/citation-state timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; curl -sI http://127.0.0.1:8000/all.svg | grep 'Content-Type: image/svg+xml'; kill $svc; wait $svc || true`

  **QA Scenarios**:
  ```
  Scenario: Current release artifacts are served with compatibility paths
    Tool: Bash
    Steps: mkdir -p /tmp/citation-state/releases/r1/dist && printf '{}' > /tmp/citation-state/releases/r1/dist/citation.json && printf '<svg/>' > /tmp/citation-state/releases/r1/dist/all.svg && ln -sfn /tmp/citation-state/releases/r1 /tmp/citation-state/current && STATE_DIR=/tmp/citation-state timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; curl -s http://127.0.0.1:8000/citation.json > .sisyphus/evidence/task-6-routes-citation.json; curl -s http://127.0.0.1:8000/all.svg > .sisyphus/evidence/task-6-routes-all.svg; kill $svc; wait $svc || true
    Expected: Evidence files contain the seeded JSON and SVG bodies
    Evidence: .sisyphus/evidence/task-6-routes-citation.json

  Scenario: Missing artifact returns the documented error status
    Tool: Bash
    Steps: rm -rf /tmp/citation-state && mkdir -p /tmp/citation-state && STATE_DIR=/tmp/citation-state timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/review.svg > .sisyphus/evidence/task-6-routes-missing.txt; kill $svc; wait $svc || true
    Expected: Evidence contains 404
    Evidence: .sisyphus/evidence/task-6-routes-missing.txt
  ```

  **Commit**: YES | Message: `feat(service): serve citation artifacts over http` | Files: `service/server.py`, `service/promote.py`

- [x] 7. Add APScheduler cron loop, overlap skip, and graceful shutdown

  **What to do**: Add APScheduler-backed cron scheduling using `CRON_SCHEDULE` and `TIMEZONE`, run one immediate refresh on boot when `REFRESH_ON_STARTUP=1`, skip overlapping refreshes, update `/status.schedule`, and stop the scheduler plus in-flight worker cleanly on `SIGTERM`.
  **Must NOT do**: Do not rely on host cron, container cron daemon, or polling loops. Do not queue backlogged runs.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: Scheduling and shutdown semantics are operationally critical.
  - Skills: `[]` - No special skill is required.
  - Omitted: `["playwright", "git-master"]` - No UI/git specialization required.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: 9 | Blocked By: 1, 2, 4

  **References**:
  - Pattern: `.github/workflows/build.yml:6-8` - Existing hourly cron baseline.
  - Pattern: `.github/workflows/build.yml:48-50` - Existing worker timeout baseline of 3 minutes.
  - API/Type: `service/worker.py` - Worker wrapper from Task 4.
  - API/Type: `service/state.py` - Schedule schema from Task 1.

  **Acceptance Criteria**:
  - [ ] `python -c "from service.scheduler import build_scheduler; s=build_scheduler('0 * * * *','UTC'); jobs=s.get_jobs(); assert len(jobs)==1"`
  - [ ] `python -c "from service.scheduler import overlap_guard; g=overlap_guard(); assert g.acquire() is True; assert g.acquire() is False; g.release()"`

  **QA Scenarios**:
  ```
  Scenario: Scheduler publishes cron metadata to /status
    Tool: Bash
    Steps: STATE_DIR=/tmp/citation-state CRON_SCHEDULE='0 * * * *' TIMEZONE='UTC' timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; curl -s http://127.0.0.1:8000/status > .sisyphus/evidence/task-7-scheduler-status.json; kill $svc; wait $svc || true
    Expected: Evidence JSON includes cron='0 * * * *', timezone='UTC', overlap_policy='skip'
    Evidence: .sisyphus/evidence/task-7-scheduler-status.json

  Scenario: Graceful shutdown leaves no partial public release
    Tool: Bash
    Steps: STATE_DIR=/tmp/citation-state timeout 10s python -m service.server >/tmp/citation-service.log 2>&1 & svc=$!; sleep 2; docker_stop_status=0; kill -TERM $svc || docker_stop_status=$?; wait $svc || true; test ! -L /tmp/citation-state/current.partial && echo ok > .sisyphus/evidence/task-7-scheduler-shutdown.txt
    Expected: Evidence contains ok and no temporary partial public pointer remains
    Evidence: .sisyphus/evidence/task-7-scheduler-shutdown.txt
  ```

  **Commit**: YES | Message: `feat(service): add cron scheduler and graceful shutdown` | Files: `service/scheduler.py`, `service/server.py`, `requirements.txt`

- [x] 8. Wire source toggles and preserve CI-mode compatibility boundaries

  **What to do**: Ensure service mode passes Scholar inputs through unchanged, only passes `--wos` when `ENABLE_WOS=1` and `WOS` is non-empty, marks WOS as `disabled` otherwise, and keeps `citation_updated.flag` / `summary.md` scoped to CI-mode batch runs rather than self-hosted public state. Verify existing `main.py --gen_summary` path still works.
  **Must NOT do**: Do not alter the existing GitHub Actions workflow contract or rename secrets (`AUTHOR`, `SCHOLAR`, `WOS`, `DEPLOY_TOKEN`, `CNAME`).

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: This task protects backward compatibility and limits WOS complexity.
  - Skills: `[]` - No special skill is required.
  - Omitted: `["playwright", "git-master"]` - Not a UI or git-history task.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: 9 | Blocked By: 1, 4

  **References**:
  - Pattern: `.github/workflows/build.yml:50-68` - Existing `citation_updated.flag` behavior is CI-scoped.
  - Pattern: `main.py:254-269` - Flag file creation by the worker that must remain internal in service mode.
  - Pattern: `main.py:275-294` - `summary.md` is generated only when `--gen_summary` is used and should remain CI-only.
  - Pattern: `README.md:30-35` - Existing secret/env names to preserve.

  **Acceptance Criteria**:
  - [ ] `python -c "from service.worker import build_worker_argv; argv=build_worker_argv(author='', scholar='abc', wos='w1', enable_wos=False); assert '--wos' not in argv"`
  - [ ] `python -c "from service.worker import build_worker_argv; argv=build_worker_argv(author='', scholar='abc', wos='w1', enable_wos=True); assert '--wos' in argv and 'w1' in argv"`
  - [ ] `timeout 3m python -u main.py --author 'Yann LeCun' --gen_summary >/tmp/main-batch.log 2>&1 || true; test -f summary.md || test -f citation_updated.flag`

  **QA Scenarios**:
  ```
  Scenario: WOS disabled mode does not pass --wos
    Tool: Bash
    Steps: python -c "from service.worker import build_worker_argv; print(build_worker_argv(author='Yann LeCun', scholar='', wos='WOS123', enable_wos=False))" > .sisyphus/evidence/task-8-ci-wos-disabled.txt
    Expected: Evidence contains no --wos argument
    Evidence: .sisyphus/evidence/task-8-ci-wos-disabled.txt

  Scenario: Existing batch mode remains invokable
    Tool: Bash
    Steps: timeout 3m python -u main.py --author 'Yann LeCun' --gen_summary >/tmp/main-batch.log 2>&1 || true; (test -f summary.md || test -f citation_updated.flag) && echo ok > .sisyphus/evidence/task-8-ci-batch.txt
    Expected: Evidence contains ok, proving the legacy entrypoint still runs and emits legacy side files
    Evidence: .sisyphus/evidence/task-8-ci-batch.txt
  ```

  **Commit**: YES | Message: `feat(service): preserve ci compatibility and source toggles` | Files: `service/worker.py`, `service/server.py`, `main.py` (only if absolutely required; otherwise none)

- [x] 9. Package with Dockerfile and document self-hosted usage in README

  **What to do**: Add a root `Dockerfile` based on `python:3.10-slim`, install project requirements plus APScheduler, set `WORKDIR /app`, copy repo code, expose port `8000`, declare `VOLUME /data`, and use exec-form `CMD ["python", "-m", "service.server"]`. Update `README.md` with a self-hosted section showing exact `docker build` / `docker run` commands, environment variables, mounted state volume, and the fact that WOS is disabled by default in the Docker path.
  **Must NOT do**: Do not add Compose, Helm, or systemd docs. Do not remove the existing GitHub Actions quick setup section.

  **Recommended Agent Profile**:
  - Category: `quick` - Reason: Packaging and documentation are bounded once runtime behavior is defined.
  - Skills: `[]` - No special skill is required.
  - Omitted: `["playwright", "ui-ux-pro-max"]` - No UI/browser work.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: none | Blocked By: 6, 7, 8

  **References**:
  - Pattern: `.github/workflows/build.yml:18-26` - Existing Python 3.10 baseline and dependency installation.
  - Pattern: `requirements.txt:1-7` - Existing dependency set to preserve and extend minimally.
  - Pattern: `README.md:27-46` - Existing user-facing setup and badge usage docs that self-hosted docs must complement.

  **Acceptance Criteria**:
  - [ ] `docker build -t citation-badge:self-hosted .`
  - [ ] `docker run --rm -d --name citation-svc -p 8000:8000 -v "$PWD/data:/data" -e SCHOLAR='' -e AUTHOR='Yann LeCun' citation-badge:self-hosted && sleep 5 && curl -s http://127.0.0.1:8000/status | python -c "import json,sys; d=json.load(sys.stdin); assert d['service']['mode']=='self_hosted'" && docker rm -f citation-svc`
  - [ ] `grep -n "docker run" README.md`

  **QA Scenarios**:
  ```
  Scenario: Docker image boots and serves /status
    Tool: Bash
    Steps: docker build -t citation-badge:self-hosted . && docker run --rm -d --name citation-svc -p 8000:8000 -v "$PWD/data:/data" -e AUTHOR='Yann LeCun' citation-badge:self-hosted && sleep 5 && curl -s http://127.0.0.1:8000/status > .sisyphus/evidence/task-9-docker-status.json && docker rm -f citation-svc
    Expected: Evidence JSON includes service.mode='self_hosted'
    Evidence: .sisyphus/evidence/task-9-docker-status.json

  Scenario: README documents self-hosted path without removing CI docs
    Tool: Bash
    Steps: grep -n "Quick Setup\|docker run\|GitHub Pages" README.md > .sisyphus/evidence/task-9-docker-readme.txt
    Expected: Evidence includes both legacy CI docs and new self-hosted docker instructions
    Evidence: .sisyphus/evidence/task-9-docker-readme.txt
  ```

  **Commit**: YES | Message: `feat(docker): package self-hosted citation service` | Files: `Dockerfile`, `README.md`, `requirements.txt`

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [x] F1. Plan Compliance Audit — oracle
- [x] F2. Code Quality Review — unspecified-high
- [x] F3. Real Manual QA — unspecified-high (+ playwright if UI)
- [x] F4. Scope Fidelity Check — deep

## Commit Strategy
- Keep commits atomic and aligned to Tasks 1-9.
- Prefer one task per commit; only combine tasks if the executor proves both acceptance criteria together in one diff.
- Any change to `main.py` is last resort and must be isolated in the Task 8 compatibility commit.
- Do not amend or squash until all task-level verification passes.

## Success Criteria
- A self-hosted operator can run one Docker command and reach `/status` locally.
- The service can expose the same badge filenames documented today without GitHub Pages.
- The service reuses `main.py` via subprocess rather than duplicating scraper logic.
- Public artifacts are always served from the last successful release, never a half-written run.
- Existing GitHub Actions batch usage remains supported.
- WOS remains optional and does not block Scholar-only self-hosting.
