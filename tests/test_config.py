import os
import unittest
from unittest.mock import patch

from service.config import Settings
from service.state import empty_status


class SettingsTest(unittest.TestCase):
    def test_peer_review_reads_new_environment_name(self):
        with patch.dict(os.environ, {"PEER_REVIEW": " 12 "}, clear=True):
            settings = Settings()

        self.assertEqual(settings.peer_review, "12")
        self.assertTrue(settings.peer_review_enabled)
        self.assertTrue(settings.model_dump()["peer_review_configured"])

    def test_legacy_wos_overwrite_is_ignored(self):
        with patch.dict(os.environ, {"WOS_OVERWRITE": "12"}, clear=True):
            settings = Settings()

        self.assertEqual(settings.peer_review, "")
        self.assertFalse(settings.peer_review_enabled)
        self.assertFalse(settings.model_dump()["peer_review_configured"])

    def test_peer_review_controls_compatible_status_source(self):
        with patch.dict(os.environ, {"PEER_REVIEW": "12"}, clear=True):
            settings = Settings()
            status = empty_status(settings)

        self.assertEqual(
            set(status["sources"]),
            {"google_scholar", "web_of_science"},
        )
        self.assertTrue(status["sources"]["web_of_science"]["enabled"])


if __name__ == "__main__":
    unittest.main()
