# CI: bibtexparser 2.x break and Node 24 action upgrades (2026-09)

## bibtexparser 2.x breaks scholarly 1.7.11

- Symptom: `Build` workflow fails at "Generate badges" with
  `ModuleNotFoundError: No module named 'bibtexparser.bibdatabase'`.
- Cause: `scholarly~=1.7.11` depends on `bibtexparser` unpinned; bibtexparser 2.x
  removed the `bibdatabase` module that scholarly imports.
- Fix: `bibtexparser<2` in `requirements.txt` (also covers the Docker image).
- Failures began after the last green run on 2026-09-08 with no code change,
  so suspect unpinned transitive deps first when scheduled runs start failing.

## Debugging tip

`gh run view <id> --log-failed` returned nothing for these runs; the raw job log
was available via:

```bash
gh api repos/ControlNet/citation-badge/actions/jobs/<job_id>/logs > job.log
```

## Node 20 action deprecation

Upgraded to Node 24 majors: `actions/checkout@v7`, `actions/setup-python@v7`,
`actions/github-script@v9`, `docker/setup-buildx-action@v4`,
`docker/login-action@v4`, `docker/build-push-action@v7`.
`ad-m/github-push-action@master` already uses node24.

Check an action's runtime:

```bash
gh api "repos/actions/checkout/contents/action.yml?ref=v7" -q .content | base64 -d | grep using:
```

Quote the API path in zsh; the `?` is otherwise treated as a glob.

github-script v9 breaking change: `require('@actions/github')` no longer works;
use the injected `getOctokit`. Our deploy script only uses `github.rest`.
