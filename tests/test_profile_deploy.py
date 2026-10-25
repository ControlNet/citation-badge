"""Synthetic fixtures for semantic downstream deployment, not live citation data."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from profile_deploy import STATE_FILE, acknowledge, needs_deployment, profile_fingerprint

TARGET = "example/homepage@master:deploy.yml"
FIXTURE = {
    "generated_at": "fixture-time-A",
    "google_scholar": {
        "status": "success", "total_citations": 123,
        "total_hindex": 5, "total_i10index": 4,
        "publications": [
            {"author_pub_id": "id1:p1", "citations": 100, "title": "Paper One"},
            {"author_pub_id": "id1:p2", "citations": 23, "title": "Paper Two"},
        ],
    },
    "web_of_science": {"status": "success", "peer_reviews": 12},
}


class ProfileDeploymentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dist = Path(self.tmp.name)
        self.citation = copy.deepcopy(FIXTURE)
        self.write_feed()

    def write_feed(self):
        (self.dist / "citation.json").write_text(json.dumps(self.citation))

    def ack(self):
        changed, fingerprint = needs_deployment(self.dist, TARGET)
        self.assertTrue(changed)
        assert fingerprint is not None
        acknowledge(self.dist, TARGET, fingerprint)

    def assert_update(self, expected):
        self.write_feed()
        self.assertEqual(needs_deployment(self.dist, TARGET)[0], expected)

    def test_first_run_without_receipt_requires_refresh(self):
        self.assert_update(True)

    def test_success_receipt_suppresses_identical_data(self):
        self.ack()
        self.assert_update(False)

    def test_timestamp_only_still_publishes_feed_but_does_not_deploy(self):
        self.ack()
        old_bytes = (self.dist / "citation.json").read_bytes()
        self.citation["generated_at"] = "fixture-time-B"
        self.assert_update(False)
        self.assertNotEqual(old_bytes, (self.dist / "citation.json").read_bytes())

    def test_publication_order_is_not_a_change(self):
        self.ack()
        self.citation["google_scholar"]["publications"].reverse()
        self.assert_update(False)

    def test_publication_metadata_and_openalex_do_not_deploy(self):
        self.ack()
        publication = self.citation["google_scholar"]["publications"][0]
        publication.update(title="Updated title", openalex={"doi": "fixture"})
        self.assert_update(False)

    def test_supplemental_profile_and_cache_do_not_deploy(self):
        self.ack()
        supplemental = self.dist / "another-scholar" / "openalex"
        supplemental.mkdir(parents=True)
        (supplemental / "paper.json").write_text('{"status":"matched"}')
        (self.dist / "another-scholar" / "citation.json").write_text('{"generated_at":"new"}')
        self.assert_update(False)

    def test_peer_review_changes_do_not_rebuild_citation_only_homepage(self):
        self.ack()
        self.citation["web_of_science"]["peer_reviews"] += 1
        self.assert_update(False)

    def test_publication_citation_increase_deploys(self):
        self.ack()
        self.citation["google_scholar"]["publications"][0]["citations"] += 1
        self.assert_update(True)

    def test_publication_citation_decrease_deploys(self):
        self.ack()
        self.citation["google_scholar"]["publications"][0]["citations"] -= 1
        self.assert_update(True)

    def test_equal_total_with_redistributed_citations_deploys(self):
        self.ack()
        pubs = self.citation["google_scholar"]["publications"]
        pubs[0]["citations"] += 1
        pubs[1]["citations"] -= 1
        self.assert_update(True)

    def test_new_publication_deploys(self):
        self.ack()
        self.citation["google_scholar"]["publications"].append(
            {"author_pub_id": "id1:p3", "citations": 0})
        self.assert_update(True)

    def test_removed_publication_deploys(self):
        self.ack()
        self.citation["google_scholar"]["publications"].pop()
        self.assert_update(True)

    def test_total_and_indexes_can_decrease(self):
        self.ack()
        for field in ("total_citations", "total_hindex", "total_i10index"):
            with self.subTest(field=field):
                self.citation = copy.deepcopy(FIXTURE)
                self.citation["google_scholar"][field] -= 1
                self.assert_update(True)

    def test_status_changes_are_not_ignored(self):
        self.ack()
        self.citation["google_scholar"]["status"] = "failed"
        self.assert_update(True)

    def test_failed_scrape_preserving_old_feed_does_not_deploy(self):
        self.ack()
        # The producer preserves citation.json on scrape failure. Only the
        # summary may change; it must not invalidate the last accepted receipt.
        (self.dist / "summary.md").write_text("Synthetic scrape failure")
        self.assert_update(False)

    def test_failed_dispatch_retries_even_without_raw_feed_changes(self):
        # Checks must not acknowledge anything before the API request succeeds.
        before = (self.dist / "citation.json").read_bytes()
        for _ in range(2):
            self.assert_update(True)
            self.assertFalse((self.dist / STATE_FILE).exists())
        self.assertEqual(before, (self.dist / "citation.json").read_bytes())

    def test_real_decrease_back_to_previous_value_is_not_suppressed(self):
        self.ack()
        self.citation["google_scholar"]["publications"][0]["citations"] += 1
        self.write_feed()
        self.ack()
        self.citation = copy.deepcopy(FIXTURE)
        self.assert_update(True)

    def test_changed_deployment_target_requires_refresh(self):
        self.ack()
        self.assertTrue(needs_deployment(self.dist, TARGET + ".different")[0])

    def test_corrupt_or_old_receipt_requires_refresh(self):
        for text in ("not-json", "null", '{"schema_version":0}'):
            with self.subTest(text=text):
                (self.dist / STATE_FILE).write_text(text)
                self.assert_update(True)

    def test_no_root_feed_does_not_deploy_supplemental_profiles(self):
        (self.dist / "citation.json").unlink()
        (self.dist / "another-scholar").mkdir()
        (self.dist / "another-scholar" / "citation.json").write_text(json.dumps(FIXTURE))
        self.assertEqual(needs_deployment(self.dist, TARGET), (False, None))

    def test_malformed_root_feed_is_not_acknowledged(self):
        for text in ("not-json", "null", "[]", "{}", '{"google_scholar":null}'):
            with self.subTest(text=text):
                (self.dist / "citation.json").write_text(text)
                self.assertEqual(needs_deployment(self.dist, TARGET), (False, None))

    def test_duplicate_publications_are_not_silently_collapsed(self):
        self.citation["google_scholar"]["publications"].append(
            self.citation["google_scholar"]["publications"][0])
        self.write_feed()
        self.assertEqual(needs_deployment(self.dist, TARGET), (False, None))

    def test_receipt_cannot_acknowledge_changed_feed(self):
        candidate = profile_fingerprint(self.citation)
        self.citation["google_scholar"]["total_citations"] += 1
        self.write_feed()
        with self.assertRaises(ValueError):
            acknowledge(self.dist, TARGET, candidate)
        self.assertFalse((self.dist / STATE_FILE).exists())

    def test_cli_check_and_acknowledge(self):
        output = self.dist / "github-output"
        script = str(Path(__file__).resolve().parents[1] / "profile_deploy.py")
        env = dict(os.environ, DEPLOY_TARGET=TARGET, GITHUB_OUTPUT=str(output))
        subprocess.run([sys.executable, script, "check", "--dist", str(self.dist)],
                       env=env, check=True, capture_output=True)
        fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(fields["updated"], "true")
        self.assertFalse((self.dist / STATE_FILE).exists())
        subprocess.run([sys.executable, script, "acknowledge", "--dist", str(self.dist),
                        "--fingerprint", fields["fingerprint"]], env=env, check=True)
        self.assert_update(False)
        state = json.loads((self.dist / STATE_FILE).read_text())
        self.assertNotIn(TARGET, json.dumps(state))


if __name__ == "__main__":
    unittest.main()
