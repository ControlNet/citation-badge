"""Track downstream deployment separately from raw feed publication.

The homepage consumes the root Google Scholar citation counts, not timestamps,
OpenAlex enrichment or other profiles. Acknowledgements live in dist and are
written only after GitHub accepts the downstream workflow dispatch. Until then,
checks keep returning updated=true, even if the next scrape produces no changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

STATE_FILE = ".profile-deploy-state.json"
SCHEMA_VERSION = 1


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def profile_fingerprint(citation: dict) -> str:
    """Fingerprint the root profile's citation semantics, independent of ordering."""
    scholar = citation["google_scholar"]
    status = scholar["status"]
    if status not in {"success", "failed", "skipped"}:
        raise ValueError("Unrecognized Google Scholar status")
    publications = {}
    for publication in scholar.get("publications", []):
        identifier = publication["author_pub_id"]
        if not isinstance(identifier, str) or not identifier or identifier in publications:
            raise ValueError("Missing or duplicate publication identifier")
        publications[identifier] = publication["citations"]
    return _digest({
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "total_citations": scholar.get("total_citations", 0),
        "total_hindex": scholar.get("total_hindex", 0),
        "total_i10index": scholar.get("total_i10index", 0),
        "publications": publications,
    })


def needs_deployment(dist: Path, target: str) -> tuple[bool, str | None]:
    """No valid root feed means nothing to deploy; no trusted ack means refresh."""
    try:
        fingerprint = profile_fingerprint(json.loads((dist / "citation.json").read_text()))
    except (OSError, ValueError, KeyError, TypeError):
        return False, None
    try:
        previous = json.loads((dist / STATE_FILE).read_text())
    except (OSError, ValueError):
        previous = None
    expected = {
        "schema_version": SCHEMA_VERSION,
        "target": _digest(target),
        "fingerprint": fingerprint,
    }
    return previous != expected, fingerprint


def acknowledge(dist: Path, target: str, fingerprint: str) -> None:
    """Record only the exact candidate accepted by the dispatch API."""
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid deployment fingerprint")
    # Do not acknowledge a different feed if files changed between steps.
    current = profile_fingerprint(json.loads((dist / "citation.json").read_text()))
    if current != fingerprint:
        raise ValueError("Root citation data changed after the deployment check")
    state = {
        "schema_version": SCHEMA_VERSION,
        "target": _digest(target),
        "fingerprint": fingerprint,
    }
    temporary = dist / (STATE_FILE + ".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
    temporary.replace(dist / STATE_FILE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "acknowledge"])
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--fingerprint")
    args = parser.parse_args()
    target = os.environ.get("DEPLOY_TARGET", "")
    if not target:
        parser.error("DEPLOY_TARGET is required")
    if args.command == "acknowledge":
        if not args.fingerprint:
            parser.error("--fingerprint is required for acknowledge")
        acknowledge(args.dist, target, args.fingerprint)
        return
    updated, fingerprint = needs_deployment(args.dist, target)
    outputs = f"updated={str(updated).lower()}\nfingerprint={fingerprint or ''}\n"
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(outputs)
    print("Root citation data unavailable" if fingerprint is None else
          "Downstream deployment needed" if updated else "Downstream citation data unchanged")


if __name__ == "__main__":
    main()
