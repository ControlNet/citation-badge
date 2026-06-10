import unittest

from service.worker import build_worker_argv


class WorkerArgvTest(unittest.TestCase):
    def test_worker_argv_passes_fixed_profile_timeout(self):
        argv = build_worker_argv(
            scholar="id1",
            python_executable="python",
            script_path="main.py",
        )

        self.assertEqual(
            argv,
            ["python", "main.py", "--scholar", "id1", "--timeout", "180"],
        )


if __name__ == "__main__":
    unittest.main()
