import contextlib
import io
import json
import os
import runpy
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = REPO_ROOT / "main.py"


class MultiProfileCliTest(unittest.TestCase):
    def run_main(self, scholar_arg, authors, *, wos_overwrite=None, workdir=None):
        temp_dir = workdir or tempfile.mkdtemp(prefix="citation-badge-test-")
        old_cwd = os.getcwd()
        old_argv = sys.argv[:]
        old_env = os.environ.copy()
        old_modules = {
            name: sys.modules.get(name)
            for name in ["requests", "scholarly", "scholarly._proxy_generator"]
        }

        class FakeMaxTriesExceededException(Exception):
            pass

        class FakeScholarly:
            def fill(self, author_seed):
                scholar_id = author_seed["scholar_id"]
                result = authors[scholar_id]
                if isinstance(result, Exception):
                    raise result
                return result

        class FakeResponse:
            def __init__(self, url):
                self.content = f"badge:{url}".encode("utf-8")

        fake_requests = types.SimpleNamespace(get=lambda url: FakeResponse(url))
        fake_scholarly_module = types.SimpleNamespace(scholarly=FakeScholarly())
        fake_proxy_module = types.SimpleNamespace(
            MaxTriesExceededException=FakeMaxTriesExceededException
        )

        sys.modules["requests"] = fake_requests
        sys.modules["scholarly"] = fake_scholarly_module
        sys.modules["scholarly._proxy_generator"] = fake_proxy_module

        os.chdir(temp_dir)
        sys.argv = [str(MAIN_PATH), "--scholar", scholar_arg, "--gen_summary"]
        os.environ.clear()
        if wos_overwrite is not None:
            os.environ["WOS_OVERWRITE"] = str(wos_overwrite)

        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                runpy.run_path(str(MAIN_PATH), run_name="__main__")
        finally:
            sys.argv = old_argv
            os.environ.clear()
            os.environ.update(old_env)
            os.chdir(old_cwd)
            for name, module in old_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        return Path(temp_dir), stdout.getvalue()

    def tearDown(self):
        temp_dir = getattr(self, "temp_dir", None)
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def author(self, scholar_id, citations):
        return {
            "citedby": citations,
            "citedby5y": citations - 1,
            "hindex": 4,
            "hindex5y": 3,
            "i10index": 2,
            "i10index5y": 1,
            "cites_per_year": {"2026": citations},
            "publications": [
                {
                    "author_pub_id": f"{scholar_id}:paper",
                    "num_citations": citations // 2,
                    "bib": {"title": f"Paper {scholar_id}", "pub_year": "2026"},
                }
            ],
        }

    def test_multi_profile_success_writes_profiles_and_first_profile_root_mirror(self):
        self.temp_dir, _ = self.run_main(
            " id1, id2,,id1 ",
            {"id1": self.author("id1", 12), "id2": self.author("id2", 20)},
            wos_overwrite=7,
        )

        dist = self.temp_dir / "dist"
        self.assertTrue((dist / "id1" / "citation.json").exists())
        self.assertTrue((dist / "id1" / "all.svg").exists())
        self.assertTrue((dist / "id1" / "id1_paper.svg").exists())
        self.assertTrue((dist / "id2" / "citation.json").exists())
        self.assertTrue((dist / "id2" / "all.svg").exists())
        self.assertTrue((dist / "id2" / "id2_paper.svg").exists())
        self.assertTrue((dist / "all.svg").exists())
        self.assertTrue((dist / "id1_paper.svg").exists())
        self.assertFalse((dist / "id2_paper.svg").exists())
        self.assertTrue((dist / "review.svg").exists())
        self.assertTrue((dist / "id1" / "review.svg").exists())
        self.assertFalse((dist / "id2" / "review.svg").exists())

        root_data = json.loads((dist / "citation.json").read_text(encoding="utf-8"))
        id1_data = json.loads((dist / "id1" / "citation.json").read_text(encoding="utf-8"))
        id2_data = json.loads((dist / "id2" / "citation.json").read_text(encoding="utf-8"))
        self.assertEqual(root_data, id1_data)
        self.assertEqual(root_data["google_scholar"]["total_citations"], 12)
        self.assertEqual(root_data["web_of_science"]["peer_reviews"], 7)
        self.assertEqual(root_data["web_of_science"]["status"], "success")
        self.assertEqual(id2_data["web_of_science"]["status"], "skipped")
        self.assertEqual((self.temp_dir / "citation_updated.flag").read_text(), "true")

    def test_first_profile_failure_does_not_let_later_success_take_root(self):
        self.temp_dir, _ = self.run_main(
            "id1,id2",
            {"id1": RuntimeError("scholar timeout"), "id2": self.author("id2", 20)},
        )

        dist = self.temp_dir / "dist"
        self.assertFalse((dist / "citation.json").exists())
        self.assertFalse((dist / "all.svg").exists())
        self.assertFalse((dist / "id1").exists())
        self.assertTrue((dist / "id2" / "citation.json").exists())
        self.assertTrue((dist / "id2" / "all.svg").exists())
        self.assertEqual((self.temp_dir / "citation_updated.flag").read_text(), "true")

    def test_failed_refresh_preserves_existing_artifacts_without_update_flag(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="citation-badge-test-"))
        self.temp_dir = temp_dir
        dist = temp_dir / "dist"
        (dist / "id1").mkdir(parents=True)
        root_json = {
            "google_scholar": {"status": "success", "total_citations": 99},
            "web_of_science": {"status": "success", "peer_reviews": 5},
        }
        profile_json = {
            "google_scholar": {"status": "success", "total_citations": 88},
            "web_of_science": {"status": "skipped", "peer_reviews": 0},
        }
        (dist / "citation.json").write_text(json.dumps(root_json), encoding="utf-8")
        (dist / "all.svg").write_text("old-root", encoding="utf-8")
        (dist / "id1" / "citation.json").write_text(
            json.dumps(profile_json), encoding="utf-8"
        )
        (dist / "id1" / "all.svg").write_text("old-profile", encoding="utf-8")

        old_cwd = os.getcwd()
        os.chdir(temp_dir)
        try:
            _, _ = self.run_main(
                "id1", {"id1": RuntimeError("scholar timeout")}, workdir=temp_dir
            )
        finally:
            os.chdir(old_cwd)

        self.assertEqual((dist / "all.svg").read_text(encoding="utf-8"), "old-root")
        self.assertEqual(
            json.loads((dist / "citation.json").read_text(encoding="utf-8")), root_json
        )
        self.assertEqual(
            json.loads((dist / "id1" / "citation.json").read_text(encoding="utf-8")),
            profile_json,
        )
        self.assertEqual((temp_dir / "citation_updated.flag").read_text(), "false")

    def test_wos_only_same_artifact_does_not_set_update_flag(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="citation-badge-test-"))
        self.temp_dir = temp_dir
        dist = temp_dir / "dist"
        dist.mkdir()
        (dist / "review.svg").write_bytes(
            b"badge:https://img.shields.io/badge/peer reviews-7-_.svg?color=8A2BE2&style=flat-square"
        )

        _, _ = self.run_main(
            "id1",
            {"id1": RuntimeError("scholar timeout")},
            wos_overwrite=7,
            workdir=temp_dir,
        )

        self.assertFalse((dist / "citation.json").exists())
        self.assertEqual((temp_dir / "citation_updated.flag").read_text(), "false")

    def test_success_without_wos_keeps_root_and_first_profile_review_consistent(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="citation-badge-test-"))
        self.temp_dir = temp_dir

        self.run_main(
            "id1",
            {"id1": self.author("id1", 12)},
            wos_overwrite=7,
            workdir=temp_dir,
        )
        self.run_main("id1", {"id1": self.author("id1", 13)}, workdir=temp_dir)

        dist = temp_dir / "dist"
        root_data = json.loads((dist / "citation.json").read_text(encoding="utf-8"))
        profile_data = json.loads(
            (dist / "id1" / "citation.json").read_text(encoding="utf-8")
        )
        self.assertEqual(root_data, profile_data)
        self.assertEqual(root_data["web_of_science"]["status"], "success")
        self.assertEqual(root_data["web_of_science"]["peer_reviews"], 7)
        self.assertEqual(
            (dist / "review.svg").exists(), (dist / "id1" / "review.svg").exists()
        )
        self.assertTrue((dist / "id1" / "review.svg").exists())


if __name__ == "__main__":
    unittest.main()
