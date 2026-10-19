import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openalex import OpenAlexClient, carry_over_cache, enrich_profiles


NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.headers = headers if headers is not None else {"x-ratelimit-remaining": "9000"}

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = []

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        self.headers.append(dict(headers or {}))
        if not self.responses:
            raise AssertionError(f"Unexpected OpenAlex request: {url} {params}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def work(title, year=2026, authors=("Zhixi Cai", "Hamid Rezatofighi"), work_id="W1", **extra):
    data = {
        "id": f"https://openalex.org/{work_id}",
        "doi": f"https://doi.org/10.1/{work_id}",
        "display_name": title,
        "publication_date": f"{year}-07-13",
        "publication_year": year,
        "authorships": [{"author": {"display_name": name}} for name in authors],
        "primary_location": {"source": {"display_name": "CVPR", "type": "conference"}},
        "type": "article",
    }
    data.update(extra)
    return data


def search_hit(*works, remaining="9000"):
    return FakeResponse(
        payload={"results": list(works)},
        headers={"x-ratelimit-remaining": remaining},
    )


def budget_exhausted():
    return FakeResponse(status_code=429, headers={"x-ratelimit-remaining": "0"})


def pub(pub_id, title, year="2026", authors="Z Cai, H Rezatofighi"):
    return {"author_pub_id": pub_id, "title": title, "year": year, "authors": authors}


class OpenAlexTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="openalex-test-"))
        self.sleeps = []

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def profile(self, scholar_id, publications):
        profile_dir = self.temp_dir / scholar_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "citation.json").write_text(
            json.dumps(
                {"google_scholar": {"status": "success", "publications": publications}}
            ),
            encoding="utf-8",
        )
        return profile_dir

    def record_path(self, profile_dir, pub_id):
        return profile_dir / "openalex" / f"{pub_id.replace(':', '_')}.json"

    def write_record(self, profile_dir, pub_id, record):
        path = self.record_path(profile_dir, pub_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")

    def read_record(self, profile_dir, pub_id):
        return json.loads(self.record_path(profile_dir, pub_id).read_text(encoding="utf-8"))

    def client(self, http, api_key="key"):
        return OpenAlexClient(http, api_key=api_key, sleep=self.sleeps.append)

    def enrich(self, profile_dirs, http, **kwargs):
        return enrich_profiles(profile_dirs, self.client(http, **kwargs), now=NOW)


class MatchingTest(OpenAlexTestCase):
    def test_new_publication_is_matched_and_written(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "LLM Planning: Two Dissociations")])
        http = FakeHttp([search_hit(work("LLM planning: two dissociations"))])

        summary = self.enrich([profile_dir], http)

        record = self.read_record(profile_dir, "id1:p1")
        self.assertEqual(record["status"], "matched")
        self.assertEqual(record["author_pub_id"], "id1:p1")
        self.assertEqual(record["openalex_id"], "https://openalex.org/W1")
        self.assertEqual(record["publication_date"], "2026-07-13")
        self.assertEqual(record["authors"], ["Zhixi Cai", "Hamid Rezatofighi"])
        self.assertEqual(record["venue"], "CVPR")
        self.assertEqual(record["fetched_at"], NOW.isoformat())
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(http.headers[0], {"Authorization": "Bearer key"})
        self.assertNotIn("api_key", http.calls[0][1])

    def test_search_filter_strips_filter_syntax_characters(self):
        profile_dir = self.profile(
            "id1", [pub("id1:p1", "JRDB-AVR: Active, Visual|Reasoning")]
        )
        http = FakeHttp([search_hit()])

        self.enrich([profile_dir], http, api_key=None)

        url, params = http.calls[0]
        self.assertEqual(url, "https://api.openalex.org/works")
        self.assertEqual(params["filter"], "title.search:jrdb avr active visual reasoning")
        self.assertEqual(http.headers[0], {})

    def test_candidate_without_author_overlap_is_not_found(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "Same Title")])
        http = FakeHttp([search_hit(work("Same Title", authors=("Someone Else",)))])

        summary = self.enrich([profile_dir], http)

        record = self.read_record(profile_dir, "id1:p1")
        self.assertEqual(record["status"], "not_found")
        self.assertEqual(record["checked_at"], NOW.isoformat())
        self.assertEqual(summary["not_found"], 1)

    def test_candidate_with_distant_year_is_not_found(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "Same Title", year="2026")])
        http = FakeHttp([search_hit(work("Same Title", year=2020))])

        self.enrich([profile_dir], http)

        self.assertEqual(self.read_record(profile_dir, "id1:p1")["status"], "not_found")

    def test_closest_year_non_repository_candidate_wins(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "Same Title", year="2026")])
        arxiv = work(
            "Same Title",
            year=2025,
            work_id="W_ARXIV",
            primary_location={"source": {"display_name": "arXiv", "type": "repository"}},
        )
        published = work("Same Title", year=2026, work_id="W_PUB")
        http = FakeHttp([search_hit(arxiv, published)])

        self.enrich([profile_dir], http)

        record = self.read_record(profile_dir, "id1:p1")
        self.assertEqual(record["openalex_id"], "https://openalex.org/W_PUB")


class CacheTest(OpenAlexTestCase):
    def test_fresh_records_skip_api(self):
        profile_dir = self.profile(
            "id1", [pub("id1:p1", "Matched"), pub("id1:p2", "Missing")]
        )
        self.write_record(
            profile_dir,
            "id1:p1",
            {"status": "matched", "openalex_id": "https://openalex.org/W1",
             "fetched_at": (NOW - timedelta(days=29)).isoformat()},
        )
        self.write_record(
            profile_dir,
            "id1:p2",
            {"status": "not_found", "checked_at": (NOW - timedelta(days=6)).isoformat()},
        )
        http = FakeHttp([])

        summary = self.enrich([profile_dir], http)

        self.assertEqual(http.calls, [])
        self.assertEqual(summary["status"], "complete")

    def test_stale_not_found_is_retried(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "Late Paper")])
        self.write_record(
            profile_dir,
            "id1:p1",
            {"status": "not_found", "checked_at": (NOW - timedelta(days=8)).isoformat()},
        )
        http = FakeHttp([search_hit(work("Late Paper"))])

        self.enrich([profile_dir], http)

        self.assertEqual(self.read_record(profile_dir, "id1:p1")["status"], "matched")

    def test_stale_match_is_refreshed_with_free_lookup(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "Old Paper")])
        self.write_record(
            profile_dir,
            "id1:p1",
            {"status": "matched", "openalex_id": "https://openalex.org/W7",
             "fetched_at": (NOW - timedelta(days=31)).isoformat()},
        )
        http = FakeHttp([FakeResponse(payload=work("Old Paper", work_id="W8"))])

        self.enrich([profile_dir], http)

        self.assertEqual(http.calls[0][0], "https://api.openalex.org/works/W7")
        record = self.read_record(profile_dir, "id1:p1")
        self.assertEqual(record["openalex_id"], "https://openalex.org/W8")
        self.assertEqual(record["fetched_at"], NOW.isoformat())

    def test_corrupt_record_is_treated_as_missing(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "Paper")])
        path = self.record_path(profile_dir, "id1:p1")
        path.parent.mkdir(parents=True)
        path.write_text("{truncated", encoding="utf-8")
        http = FakeHttp([search_hit(work("Paper"))])

        self.enrich([profile_dir], http)

        self.assertEqual(self.read_record(profile_dir, "id1:p1")["status"], "matched")

    def test_coauthored_paper_reuses_other_profile_record(self):
        first = self.profile("id1", [pub("id1:p1", "Shared Paper")])
        second = self.profile("id2", [pub("id2:q1", "Shared  paper")])
        self.write_record(
            first,
            "id1:p1",
            {"status": "matched", "author_pub_id": "id1:p1", "scholar_title": "Shared Paper",
             "openalex_id": "https://openalex.org/W1", "fetched_at": NOW.isoformat()},
        )
        http = FakeHttp([])

        summary = self.enrich([first, second], http)

        record = self.read_record(second, "id2:q1")
        self.assertEqual(record["openalex_id"], "https://openalex.org/W1")
        self.assertEqual(record["author_pub_id"], "id2:q1")
        self.assertEqual(record["scholar_title"], "Shared  paper")
        self.assertEqual(summary["reused"], 1)

    def test_carry_over_keeps_only_current_publications(self):
        old_dir = self.profile("id1", [])
        self.write_record(old_dir, "id1:kept", {"status": "matched"})
        self.write_record(old_dir, "id1:removed", {"status": "matched"})
        (old_dir / "openalex" / "id1_kept.json.tmp").write_text("partial", encoding="utf-8")
        staged_dir = self.temp_dir / "staged"
        staged_dir.mkdir()
        (staged_dir / "citation.json").write_text(
            json.dumps({"google_scholar": {"publications": [pub("id1:kept", "Kept")]}}),
            encoding="utf-8",
        )

        carry_over_cache(old_dir, staged_dir)

        self.assertEqual(
            sorted(p.name for p in (staged_dir / "openalex").iterdir()), ["id1_kept.json"]
        )


class BudgetTest(OpenAlexTestCase):
    def test_budget_exhausted_mid_run_keeps_completed_records(self):
        profile_dir = self.profile(
            "id1", [pub("id1:p1", "First"), pub("id1:p2", "Second"), pub("id1:p3", "Third")]
        )
        http = FakeHttp([search_hit(work("First")), budget_exhausted()])

        summary = self.enrich([profile_dir], http)

        self.assertEqual(summary["status"], "budget_exhausted")
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["pending"], 2)
        self.assertEqual(len(http.calls), 2)
        self.assertEqual(
            sorted(p.name for p in (profile_dir / "openalex").iterdir()), ["id1_p1.json"]
        )

    def test_rate_limit_with_remaining_budget_is_retried(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "Paper")])
        per_second = FakeResponse(status_code=429, headers={"x-ratelimit-remaining": "500"})
        http = FakeHttp([per_second, search_hit(work("Paper"))])

        summary = self.enrich([profile_dir], http)

        self.assertEqual(summary["status"], "complete")
        self.assertEqual(self.sleeps, [1])
        self.assertEqual(self.read_record(profile_dir, "id1:p1")["status"], "matched")

    def test_rate_limit_requiring_more_credits_than_remaining_is_budget(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "Paper")])
        response = FakeResponse(
            status_code=429,
            headers={"x-ratelimit-remaining": "5", "x-ratelimit-credits-required": "10"},
        )
        http = FakeHttp([response])

        summary = self.enrich([profile_dir], http)

        self.assertEqual(summary["status"], "budget_exhausted")
        self.assertEqual(self.sleeps, [])

    def test_search_is_skipped_when_remaining_is_below_search_cost(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "First"), pub("id1:p2", "Second")])
        http = FakeHttp([search_hit(work("First"), remaining="5")])

        summary = self.enrich([profile_dir], http)

        self.assertEqual(len(http.calls), 1)
        self.assertEqual(summary["status"], "budget_exhausted")
        self.assertEqual(summary["pending"], 1)

    def test_budget_is_shared_round_robin_across_profiles(self):
        first = self.profile("id1", [pub("id1:p1", "A1"), pub("id1:p2", "A2")])
        second = self.profile("id2", [pub("id2:p1", "B1"), pub("id2:p2", "B2")])
        http = FakeHttp([search_hit(work("A1")), search_hit(work("B1")), budget_exhausted()])

        self.enrich([first, second], http)

        self.assertTrue(self.record_path(first, "id1:p1").exists())
        self.assertTrue(self.record_path(second, "id2:p1").exists())
        self.assertFalse(self.record_path(first, "id1:p2").exists())

    def test_paid_request_cap_stops_run(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "First"), pub("id1:p2", "Second")])
        http = FakeHttp([search_hit(work("First"))])
        client = OpenAlexClient(http, api_key="key", max_paid_requests=1)

        summary = enrich_profiles([profile_dir], client, now=NOW)

        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["pending"], 1)

    def test_network_error_skips_publication_without_leaking_url(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "First"), pub("id1:p2", "Second")])
        leaky = ConnectionError("https://api.openalex.org/works?api_key=secret")
        http = FakeHttp([leaky, search_hit(work("Second"))])

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            summary = self.enrich([profile_dir], http)

        self.assertEqual(summary["errors"], 1)
        self.assertTrue(self.record_path(profile_dir, "id1:p2").exists())
        self.assertNotIn("secret", stdout.getvalue())

    def test_server_error_skips_publication_and_continues(self):
        profile_dir = self.profile("id1", [pub("id1:p1", "First"), pub("id1:p2", "Second")])
        http = FakeHttp([FakeResponse(status_code=500), search_hit(work("Second"))])

        summary = self.enrich([profile_dir], http)

        self.assertFalse(self.record_path(profile_dir, "id1:p1").exists())
        self.assertTrue(self.record_path(profile_dir, "id1:p2").exists())
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["pending"], 1)


if __name__ == "__main__":
    unittest.main()
