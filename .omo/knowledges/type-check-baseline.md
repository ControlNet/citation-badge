# Type-check baseline

- Date: 2026-08-30
- `pixi run basedpyright --level error` is not clean at the current repository baseline.
- The remaining 18 errors are concentrated in `main.py` bare `dict` annotations and the existing `tests/test_multi_profile_cli.py` module fakes / `temp_dir` initialization.
- The `PEER_REVIEW` migration's service files and new configuration tests pass a focused check with zero errors:
  `pixi run basedpyright --level error service/config.py service/state.py service/server.py tests/test_config.py`.
- Keep the broader typing cleanup separate from configuration renames to preserve a minimal, reviewable patch.
