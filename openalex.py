"""OpenAlex enrichment cached as one JSON file per Google Scholar publication.

Each profile keeps `<profile_dir>/openalex/<author_pub_id with ':' -> '_'>.json`.
A fresh file means no request is made; the daily OpenAlex budget may run out
mid-run, in which case finished files are kept and the rest wait for a later run.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

JsonDict = dict[str, Any]
WorkItem = tuple[JsonDict, Path, "JsonDict | None", int]


API_BASE = "https://api.openalex.org"
OPENALEX_DIRNAME = "openalex"
WORK_FIELDS = (
    "id,doi,display_name,publication_date,publication_year,authorships,"
    "primary_location,type"
)

NOT_FOUND_RETRY_DAYS = 7
MATCHED_REFRESH_DAYS = 30
MAX_PAID_REQUESTS_PER_RUN = 50
RUN_DEADLINE_SECONDS = 120
REQUEST_TIMEOUT_SECONDS = 30
MAX_RATE_LIMIT_RETRIES = 3
SEARCH_COST_CREDITS = 10
MAX_YEAR_DIFFERENCE = 1

PRIORITY_NEW = 0
PRIORITY_RETRY_NOT_FOUND = 1
PRIORITY_REFRESH_MATCHED = 2


class OpenAlexError(Exception):
    pass


class BudgetExhausted(OpenAlexError):
    pass


class RunLimitReached(OpenAlexError):
    pass


def _header_int(headers, name: str) -> int | None:
    try:
        return int(float(headers.get(name)))
    except (TypeError, ValueError):
        return None


def _rate_limit_headers(headers) -> JsonDict:
    return {
        key: value
        for key, value in headers.items()
        if key.lower().startswith("x-ratelimit") or key.lower() == "retry-after"
    }


class OpenAlexClient:
    def __init__(
        self,
        http_get: Callable[..., Any],
        api_key: str | None = None,
        *,
        max_paid_requests: int = MAX_PAID_REQUESTS_PER_RUN,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.http_get = http_get
        self.api_key = api_key
        self.max_paid_requests = max_paid_requests
        self.sleep = sleep
        self.remaining: int | None = None
        self.paid_requests = 0

    def search_title(self, title: str) -> list[JsonDict]:
        if self.paid_requests >= self.max_paid_requests:
            raise RunLimitReached(f"Reached {self.max_paid_requests} paid requests this run")
        if self.remaining is not None and self.remaining < SEARCH_COST_CREDITS:
            raise BudgetExhausted(f"Only {self.remaining} credits left")
        self.paid_requests += 1
        params = {
            "filter": f"title.search:{normalize_title(title)}",
            "per_page": "10",
            "select": WORK_FIELDS,
        }
        return self._get("/works", params).get("results", [])

    def get_work(self, openalex_id: str) -> JsonDict | None:
        # Single-entity lookups cost no credits.
        work_key = openalex_id.rstrip("/").rsplit("/", 1)[-1]
        return self._get(f"/works/{work_key}", {"select": WORK_FIELDS}, allow_not_found=True)

    def _get(self, path: str, params: JsonDict, allow_not_found: bool = False) -> Any:
        # Send the key as a header: request exceptions embed the URL, so a
        # query-string key would leak into logs and the job summary.
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = self.http_get(
                    f"{API_BASE}{path}",
                    params=params,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except Exception as e:
                raise OpenAlexError(f"Request failed: {e.__class__.__name__}") from None
            remaining = _header_int(response.headers, "x-ratelimit-remaining")
            if remaining is not None:
                self.remaining = remaining
            if response.status_code == 429:
                headers = _rate_limit_headers(response.headers)
                print(f"OpenAlex 429 for {path}: {headers}", flush=True)
                if not self._is_per_second_limit(response.headers):
                    raise BudgetExhausted(f"Daily budget exhausted ({headers})")
                if attempt < MAX_RATE_LIMIT_RETRIES:
                    self.sleep(2**attempt)
                    continue
                raise OpenAlexError("Rate limited after retries")
            if allow_not_found and response.status_code == 404:
                return None
            if response.status_code != 200:
                raise OpenAlexError(f"HTTP {response.status_code} for {path}")
            try:
                return response.json()
            except ValueError:
                raise OpenAlexError(f"Invalid JSON for {path}") from None
        raise OpenAlexError("Rate limited after retries")

    @staticmethod
    def _is_per_second_limit(headers) -> bool:
        # Per-second and daily-budget limits share status 429; only the
        # remaining-credit headers tell them apart.
        remaining = _header_int(headers, "x-ratelimit-remaining")
        required = _header_int(headers, "x-ratelimit-credits-required")
        if remaining is None or remaining <= 0:
            return False
        return required is None or required <= remaining


def normalize_title(title: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", title.casefold()).split())


def record_filename(author_pub_id: str) -> str:
    return f"{author_pub_id.replace(':', '_')}.json"


def _surname(name: str) -> str:
    parts = normalize_title(name).split()
    return parts[-1] if parts else ""


def _scholar_surnames(author_line: str) -> set[str]:
    names = [name.strip() for name in author_line.split(",")]
    return {_surname(name) for name in names if name and name.strip(".… ")} - {""}


def _parse_year(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def match_work(candidates: list[JsonDict], publication: JsonDict) -> JsonDict | None:
    title = normalize_title(publication.get("title", ""))
    year = _parse_year(publication.get("year"))
    surnames = _scholar_surnames(publication.get("authors", ""))
    accepted = []
    for work in candidates:
        if normalize_title(work.get("display_name") or "") != title:
            continue
        work_year = _parse_year(work.get("publication_year"))
        if year is not None and work_year is not None:
            if abs(work_year - year) > MAX_YEAR_DIFFERENCE:
                continue
        work_surnames = {
            _surname((authorship.get("author") or {}).get("display_name") or "")
            for authorship in work.get("authorships") or []
        }
        if surnames and not surnames & work_surnames:
            continue
        accepted.append(work)

    def preference(work: JsonDict) -> tuple[int, bool]:
        work_year = _parse_year(work.get("publication_year"))
        year_gap = abs(work_year - year) if year is not None and work_year is not None else 0
        source = (work.get("primary_location") or {}).get("source") or {}
        return year_gap, source.get("type") == "repository"

    return min(accepted, key=preference) if accepted else None


def _matched_record(publication: JsonDict, work: JsonDict, now: datetime) -> JsonDict:
    source = (work.get("primary_location") or {}).get("source") or {}
    return {
        "status": "matched",
        "author_pub_id": publication["author_pub_id"],
        "scholar_title": publication.get("title", ""),
        "fetched_at": now.isoformat(),
        "openalex_id": work.get("id"),
        "doi": work.get("doi"),
        "title": work.get("display_name"),
        # OpenAlex reports YYYY-01-01 when only the year is known.
        "publication_date": work.get("publication_date"),
        "publication_year": work.get("publication_year"),
        "authors": [
            (authorship.get("author") or {}).get("display_name")
            for authorship in work.get("authorships") or []
            if (authorship.get("author") or {}).get("display_name")
        ],
        "venue": source.get("display_name"),
        "type": work.get("type"),
    }


def _not_found_record(publication: JsonDict, now: datetime) -> JsonDict:
    return {
        "status": "not_found",
        "author_pub_id": publication["author_pub_id"],
        "scholar_title": publication.get("title", ""),
        "checked_at": now.isoformat(),
    }


def _load_record(path: Path) -> JsonDict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("status") not in {"matched", "not_found"}:
        return None
    return record


def _write_record(path: Path, record: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _due_priority(record: JsonDict | None, now: datetime) -> int | None:
    if record is None:
        return PRIORITY_NEW
    if record["status"] == "not_found":
        checked_at = _parse_time(record.get("checked_at"))
        if checked_at is None or now - checked_at >= timedelta(days=NOT_FOUND_RETRY_DAYS):
            return PRIORITY_RETRY_NOT_FOUND
        return None
    fetched_at = _parse_time(record.get("fetched_at"))
    if fetched_at is None or now - fetched_at >= timedelta(days=MATCHED_REFRESH_DAYS):
        return PRIORITY_REFRESH_MATCHED
    return None


def _profile_publications(profile_dir: Path) -> list[JsonDict]:
    try:
        with open(profile_dir / "citation.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    publications = data.get("google_scholar", {}).get("publications", [])
    return [pub for pub in publications if pub.get("author_pub_id")]


def carry_over_cache(old_profile_dir: Path, staged_profile_dir: Path) -> None:
    """Move cached records of still-listed publications into the staged profile."""
    old_cache_dir = old_profile_dir / OPENALEX_DIRNAME
    if not old_cache_dir.is_dir():
        return
    wanted = {
        record_filename(pub["author_pub_id"])
        for pub in _profile_publications(staged_profile_dir)
    }
    staged_cache_dir = staged_profile_dir / OPENALEX_DIRNAME
    for path in old_cache_dir.glob("*.json"):
        if path.name in wanted:
            staged_cache_dir.mkdir(parents=True, exist_ok=True)
            os.replace(path, staged_cache_dir / path.name)


def _citation_summary(record: JsonDict | None) -> JsonDict | None:
    if record is None or record["status"] != "matched":
        return None
    return {
        "id": record.get("openalex_id"),
        "doi": record.get("doi"),
        "publication_date": record.get("publication_date"),
        "authors": record.get("authors", []),
        "venue": record.get("venue"),
    }


def merge_cache_into_citation(profile_dir: Path) -> None:
    """Set `publications[].openalex` in citation.json from the cached records."""
    citation_path = profile_dir / "citation.json"
    try:
        with open(citation_path, "r", encoding="utf-8") as f:
            citation = json.load(f)
    except (OSError, ValueError):
        return
    cache_dir = profile_dir / OPENALEX_DIRNAME
    for publication in citation.get("google_scholar", {}).get("publications", []):
        pub_id = publication.get("author_pub_id")
        record = _load_record(cache_dir / record_filename(pub_id)) if pub_id else None
        publication["openalex"] = _citation_summary(record)
    _write_record(citation_path, citation)


def _round_robin(queues: list[list[WorkItem]]) -> list[WorkItem]:
    ordered: list[WorkItem] = []
    for index in range(max((len(queue) for queue in queues), default=0)):
        ordered.extend(queue[index] for queue in queues if index < len(queue))
    return ordered


def enrich_profiles(
    profile_dirs: list[Path],
    client: OpenAlexClient,
    *,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> JsonDict:
    now = now or datetime.now(timezone.utc)
    known: dict[str, JsonDict] = {}
    queues_by_priority: dict[int, list[list[WorkItem]]] = {
        PRIORITY_NEW: [],
        PRIORITY_RETRY_NOT_FOUND: [],
        PRIORITY_REFRESH_MATCHED: [],
    }
    for profile_dir in profile_dirs:
        cache_dir = profile_dir / OPENALEX_DIRNAME
        for leftover in cache_dir.glob("*.tmp"):
            leftover.unlink()
        profile_queues: dict[int, list[WorkItem]] = {key: [] for key in queues_by_priority}
        for publication in _profile_publications(profile_dir):
            path = cache_dir / record_filename(publication["author_pub_id"])
            record = _load_record(path)
            priority = _due_priority(record, now)
            if priority is None:
                if record is not None and record["status"] == "matched":
                    known.setdefault(normalize_title(publication.get("title", "")), record)
                continue
            profile_queues[priority].append((publication, path, record, priority))
        for priority, items in profile_queues.items():
            queues_by_priority[priority].append(items)

    # New papers first, then retries, then refreshes; each tier round-robins
    # across profiles so an early stop does not starve later profiles.
    work_items: list[WorkItem] = []
    for priority in sorted(queues_by_priority):
        work_items.extend(_round_robin(queues_by_priority[priority]))

    status, reason = "complete", ""
    counts = {"matched": 0, "not_found": 0, "reused": 0, "errors": 0, "pending": len(work_items)}
    started = clock()
    for publication, path, record, priority in work_items:
        if clock() - started > RUN_DEADLINE_SECONDS:
            status, reason = "partial", "Run deadline reached"
            break
        title_key = normalize_title(publication.get("title", ""))
        try:
            new_record = None
            if priority != PRIORITY_REFRESH_MATCHED and title_key in known:
                new_record = {
                    **known[title_key],
                    "author_pub_id": publication["author_pub_id"],
                    "scholar_title": publication.get("title", ""),
                }
                counts["reused"] += 1
            elif priority == PRIORITY_REFRESH_MATCHED and record and record.get("openalex_id"):
                work = client.get_work(record["openalex_id"])
                if work is not None:
                    new_record = _matched_record(publication, work, now)
            if new_record is None:
                work = match_work(client.search_title(publication.get("title", "")), publication)
                if work is None:
                    new_record = _not_found_record(publication, now)
                else:
                    new_record = _matched_record(publication, work, now)
        except BudgetExhausted as e:
            status, reason = "budget_exhausted", str(e)
            break
        except RunLimitReached as e:
            status, reason = "partial", str(e)
            break
        except OpenAlexError as e:
            print(f"OpenAlex lookup failed for {publication['author_pub_id']}: {e}", flush=True)
            counts["errors"] += 1
            continue

        _write_record(path, new_record)
        known.setdefault(title_key, new_record)
        counts["pending"] -= 1
        if new_record["status"] == "matched":
            counts["matched"] += 1
        else:
            counts["not_found"] += 1

    return {"status": status, "reason": reason, **counts}
