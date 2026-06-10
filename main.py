import argparse
import hashlib
import json
import multiprocessing
import os
import shutil
import traceback
from datetime import datetime
from pathlib import Path

import requests
from scholarly import scholarly
from scholarly._proxy_generator import MaxTriesExceededException


DIST_DIR = Path("dist")
STAGING_DIR = DIST_DIR / ".staging"


class ScholarProfileTimeout(TimeoutError):
    pass


def _get_env_str(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_scholar_ids(raw: str) -> list[str]:
    scholar_ids = []
    seen = set()
    for scholar_id in raw.split(","):
        scholar_id = scholar_id.strip()
        if not scholar_id or scholar_id in seen:
            continue
        scholar_ids.append(scholar_id)
        seen.add(scholar_id)
    return scholar_ids


def _new_citation_metadata() -> dict:
    return {
        "generated_at": datetime.now().isoformat(),
        "google_scholar": {
            "status": "not_attempted",
            "total_citations": 0,
            "5y_citations": 0,
            "total_hindex": 0,
            "5y_hindex": 0,
            "total_i10index": 0,
            "5y_i10index": 0,
            "cites_per_year": {},
            "publications": [],
            "error": None,
        },
        "web_of_science": {"status": "skipped", "peer_reviews": 0, "error": None},
    }


def _write_badge(path: Path, label: str, value: str, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(
            requests.get(
                f"https://img.shields.io/badge/{label}-{value}-_.svg?color={color}&style=flat-square"
            ).content
        )


def _write_wos_badge(output_dir: Path, review_count: str) -> None:
    _write_badge(output_dir / "review.svg", "peer reviews", review_count, "8A2BE2")


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Could not load previous citation data from {path}: {e}", flush=True)
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _has_successful_google_scholar(path: Path) -> bool:
    return _load_json(path).get("google_scholar", {}).get("status") == "success"


def _dist_snapshot() -> dict[str, str]:
    snapshot = {}
    if not DIST_DIR.exists():
        return snapshot

    for path in DIST_DIR.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(DIST_DIR).parts
        if relative_parts[0] in {".git", ".staging"}:
            continue
        snapshot[str(path.relative_to(DIST_DIR))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _fill_author_worker(author_seed: dict, result_queue) -> None:
    try:
        result_queue.put(("success", scholarly.fill(author_seed)))
    except Exception as e:
        result_queue.put(("error", e.__class__.__name__, str(e), traceback.format_exc()))


def _fill_author_with_timeout(author_seed: dict, timeout_seconds: int) -> dict:
    context = multiprocessing.get_context("fork")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=_fill_author_worker, args=(author_seed, result_queue))
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
        raise ScholarProfileTimeout(
            f"Google Scholar profile timed out after {timeout_seconds} seconds"
        )

    if result_queue.empty():
        raise RuntimeError("Google Scholar profile worker exited without a result")

    result = result_queue.get()
    if result[0] == "success":
        return result[1]

    _, error_name, error_message, remote_traceback = result
    if error_name == MaxTriesExceededException.__name__:
        raise MaxTriesExceededException(error_message)
    raise RuntimeError(f"{error_message}\n{remote_traceback}")


def generate_scholar_to_dir(
    scholar_id: str, output_dir: Path, profile_timeout_seconds: int
) -> dict:
    citation_metadata = _new_citation_metadata()

    try:
        author_seed = {
            "affiliation": "",
            "citedby": 0,
            "email_domain": "",
            "filled": [],
            "interests": [],
            "name": "",
            "scholar_id": scholar_id,
            "source": "",
            "url_picture": "",
            "container_type": "Author",
        }
        print(f"Loading Google Scholar profile {scholar_id}...", flush=True)
        print("Google Scholar profile found", flush=True)
        author = _fill_author_with_timeout(author_seed, profile_timeout_seconds)
        print("Google Scholar profile filled", flush=True)
        total_cite = author["citedby"]

        citation_metadata["google_scholar"]["status"] = "success"
        citation_metadata["google_scholar"]["total_citations"] = total_cite
        citation_metadata["google_scholar"]["5y_citations"] = author.get(
            "citedby5y", 0
        )
        citation_metadata["google_scholar"]["total_hindex"] = author.get("hindex", 0)
        citation_metadata["google_scholar"]["5y_hindex"] = author.get("hindex5y", 0)
        citation_metadata["google_scholar"]["total_i10index"] = author.get(
            "i10index", 0
        )
        citation_metadata["google_scholar"]["5y_i10index"] = author.get(
            "i10index5y", 0
        )
        citation_metadata["google_scholar"]["cites_per_year"] = author.get(
            "cites_per_year", {}
        )

        _write_badge(output_dir / "all.svg", "citations", str(total_cite), "3388ee")
        print("All.svg generated", flush=True)

        publications_data = []
        for pub in author["publications"]:
            pub_id = pub["author_pub_id"].replace(":", "_")
            pub_cite = pub["num_citations"]
            publications_data.append(
                {
                    "author_pub_id": pub.get("author_pub_id", ""),
                    "title": pub.get("bib", {}).get("title", ""),
                    "year": pub.get("bib", {}).get("pub_year", ""),
                    "citations": pub_cite,
                }
            )
            _write_badge(output_dir / f"{pub_id}.svg", "citations", str(pub_cite), "3388ee")

        citation_metadata["google_scholar"]["publications"] = publications_data
        _write_json(output_dir / "citation.json", citation_metadata)
        print("All pub svg generated", flush=True)
        return {
            "success": True,
            "metadata": citation_metadata,
            "reason": f"Total citations: {total_cite}",
        }
    except MaxTriesExceededException:
        print(f"Max tries exceeded, skip google scholar badges for {scholar_id}", flush=True)
        citation_metadata["google_scholar"]["status"] = "failed"
        citation_metadata["google_scholar"]["error"] = "Max proxy retries exceeded"
        return {
            "success": False,
            "metadata": citation_metadata,
            "reason": "Max proxy retries exceeded",
        }
    except ScholarProfileTimeout as e:
        print(f"{e}, skip google scholar badges for {scholar_id}", flush=True)
        citation_metadata["google_scholar"]["status"] = "failed"
        citation_metadata["google_scholar"]["error"] = str(e)
        return {
            "success": False,
            "metadata": citation_metadata,
            "reason": str(e),
        }
    except Exception as e:
        print(
            f"An unexpected error occurred with Google Scholar profile {scholar_id}: {e}",
            flush=True,
        )
        traceback.print_exc()
        citation_metadata["google_scholar"]["status"] = "failed"
        citation_metadata["google_scholar"]["error"] = str(e)
        return {
            "success": False,
            "metadata": citation_metadata,
            "reason": f"Unexpected error: {e}",
        }


def _promote_profile(staged_profile_dir: Path, profile_dir: Path) -> None:
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    shutil.move(str(staged_profile_dir), str(profile_dir))


def _mirror_first_profile_to_root(profile_dir: Path) -> None:
    for svg_path in DIST_DIR.glob("*.svg"):
        svg_path.unlink()

    for svg_path in profile_dir.glob("*.svg"):
        shutil.copy2(svg_path, DIST_DIR / svg_path.name)


def _profile_wos_metadata(
    wos_overwrite_raw: str | None, first_profile_dir: Path | None
) -> tuple[dict, dict]:
    if wos_overwrite_raw is None:
        return (
            {"status": "skipped", "peer_reviews": 0, "error": None},
            {"success": False, "reason": "WOS_OVERWRITE not provided"},
        )

    if first_profile_dir is None:
        return (
            {
                "status": "failed",
                "peer_reviews": 0,
                "error": "No successful first profile for WOS_OVERWRITE",
            },
            {
                "success": False,
                "reason": "No successful first profile for WOS_OVERWRITE",
            },
        )

    print(f"Using WOS overwrite: {wos_overwrite_raw}", flush=True)
    try:
        review_count = int(wos_overwrite_raw)
        if review_count < 0:
            raise ValueError("WOS_OVERWRITE must be a non-negative integer")

        _write_wos_badge(first_profile_dir, str(review_count))
        print("Review badge generated", flush=True)
        return (
            {"status": "success", "peer_reviews": review_count, "error": None},
            {"success": True, "reason": f"Peer reviews: {review_count} (override)"},
        )
    except Exception as e:
        print(f"An error occurred during WOS overwrite processing: {e}", flush=True)
        return (
            {"status": "failed", "peer_reviews": 0, "error": str(e)},
            {"success": False, "reason": f"WOS Override Error: {e}"},
        )


def _select_profile_wos(previous_profile_data: dict, current_wos: dict) -> dict:
    if current_wos["status"] == "success":
        return current_wos
    if previous_profile_data.get("web_of_science", {}).get("status") == "success":
        return previous_profile_data["web_of_science"]
    return current_wos


def _save_update_flag(updated: bool) -> None:
    with open("citation_updated.flag", "w") as f:
        f.write("true" if updated else "false")


def _write_summary(profile_statuses: list[dict], wos_status: dict, include_wos: bool) -> None:
    summary_content = """
# Citation Badge Generation

| Source          | Status  | Details                          |
|-----------------|---------|----------------------------------|
"""
    for profile_status in profile_statuses:
        if profile_status["status"] == "success":
            icon = "✅ Success"
        elif profile_status["status"] == "stale":
            icon = "⚠️ Stale"
        else:
            icon = "❌ Failed"
        summary_content += (
            f"| Google Scholar ({profile_status['scholar_id']}) | {icon:<8}| "
            f"{profile_status['reason']:<32} |\n"
        )

    if include_wos:
        wos_icon = "✅ Success" if wos_status["success"] else "❌ Failed"
        summary_content += f"| Web of Science  | {wos_icon:<8}| {wos_status['reason']:<32} |\n"
    else:
        summary_content += f"| Web of Science  | ⚠️ Skipped | {wos_status['reason']:<32} |\n"

    with open("summary.md", "w", encoding="utf-8") as f:
        f.write(summary_content)
    print("Summary written to summary.md", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Get citations from Google Scholar")
    parser.add_argument("--scholar", type=str, required=True, help="Google Scholar ID")
    parser.add_argument(
        "--timeout",
        type=int,
        required=True,
        help="Per-profile Google Scholar timeout in seconds",
    )
    parser.add_argument(
        "--gen_summary", action="store_true", help="Generate summary for github actions"
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be a positive number of seconds")

    scholar_ids = parse_scholar_ids(args.scholar)
    if not scholar_ids:
        parser.error("--scholar must include at least one non-empty Google Scholar ID")

    DIST_DIR.mkdir(exist_ok=True)
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    initial_dist_snapshot = _dist_snapshot()
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    wos_overwrite_raw = _get_env_str("WOS_OVERWRITE")
    profile_timeout_seconds = args.timeout
    profile_results = {}
    profile_statuses = []
    previous_profile_data = {}
    previous_profile_review = {}

    for scholar_id in scholar_ids:
        staged_profile_dir = STAGING_DIR / scholar_id
        profile_dir = DIST_DIR / scholar_id
        previous_profile_data[scholar_id] = _load_json(profile_dir / "citation.json")
        review_path = profile_dir / "review.svg"
        if review_path.exists():
            previous_profile_review[scholar_id] = review_path.read_bytes()
        elif scholar_id == scholar_ids[0] and (DIST_DIR / "review.svg").exists():
            previous_profile_review[scholar_id] = (DIST_DIR / "review.svg").read_bytes()
        result = generate_scholar_to_dir(
            scholar_id, staged_profile_dir, profile_timeout_seconds
        )
        profile_results[scholar_id] = result

        if result["success"]:
            _promote_profile(staged_profile_dir, profile_dir)
            profile_statuses.append(
                {"scholar_id": scholar_id, "status": "success", "reason": result["reason"]}
            )
        else:
            if staged_profile_dir.exists():
                shutil.rmtree(staged_profile_dir)
            if _has_successful_google_scholar(profile_dir / "citation.json"):
                profile_statuses.append(
                    {
                        "scholar_id": scholar_id,
                        "status": "stale",
                        "reason": f"Refresh failed, previous data preserved ({result['reason']})",
                    }
                )
            else:
                profile_statuses.append(
                    {"scholar_id": scholar_id, "status": "failed", "reason": result["reason"]}
                )

    first_id = scholar_ids[0]
    first_result = profile_results[first_id]
    first_profile_dir = DIST_DIR / first_id
    first_profile_has_data = first_result["success"] or _has_successful_google_scholar(
        first_profile_dir / "citation.json"
    )
    current_wos, wos_status = _profile_wos_metadata(
        wos_overwrite_raw, first_profile_dir if first_profile_has_data else None
    )

    should_refresh_root = first_result["success"] or (
        first_profile_has_data and wos_status["success"]
    )
    if should_refresh_root:
        first_profile_data = _load_json(first_profile_dir / "citation.json")
        selected_wos = _select_profile_wos(
            previous_profile_data[first_id], current_wos
        )
        first_profile_data["web_of_science"] = selected_wos
        if (
            selected_wos.get("status") == "success"
            and current_wos.get("status") != "success"
            and first_id in previous_profile_review
        ):
            (first_profile_dir / "review.svg").write_bytes(previous_profile_review[first_id])
        _write_json(first_profile_dir / "citation.json", first_profile_data)
        _mirror_first_profile_to_root(first_profile_dir)
        shutil.copy2(first_profile_dir / "citation.json", DIST_DIR / "citation.json")
        print("Citation metadata mirrored from first profile", flush=True)
    elif not (DIST_DIR / "citation.json").exists():
        print(
            "No successful root Google Scholar data and no previous citation.json - "
            "skipping citation.json",
            flush=True,
        )
    else:
        print("No root citation metadata update - preserving existing citation.json", flush=True)

    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)

    updated = _dist_snapshot() != initial_dist_snapshot
    _save_update_flag(updated)
    print(f"Citation update flag set to {str(updated).lower()}", flush=True)

    if args.gen_summary:
        _write_summary(profile_statuses, wos_status, wos_overwrite_raw is not None)


if __name__ == "__main__":
    main()
