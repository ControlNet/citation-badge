# Scholar-only identity contract

- Date: 2026-06-10
- Decision: `AUTHOR` is removed as an input because name-based Google Scholar lookup is unstable.
- Current identity source: `SCHOLAR` only.
- `main.py` requires `--scholar` and no longer exposes `--author` or calls `scholarly.search_author()`.
- GitHub CI should pass only `secrets.SCHOLAR` into `main.py`.
- Docker/service wrapper should read only `SCHOLAR` for Google Scholar identity.
- Future multi-user mode should extend `SCHOLAR` parsing, not reintroduce name-based author lookup.
