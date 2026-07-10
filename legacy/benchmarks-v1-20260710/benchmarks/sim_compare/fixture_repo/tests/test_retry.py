import unittest

from worker.retry import fetch_with_retry


class FetchWithRetryTests(unittest.TestCase):
    def test_returns_after_a_retry(self):
        attempts = []
        sleeps = []

        def flaky_fetch():
            attempts.append("call")
            if len(attempts) < 2:
                raise RuntimeError("try again")
            return "ok"

        result = fetch_with_retry(flaky_fetch, retries=3, delay=0.01, sleep=sleeps.append)

        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sleeps, [0.01])

    def test_raises_last_error_after_final_attempt(self):
        sleeps = []

        def always_fail():
            raise RuntimeError("still broken")

        with self.assertRaisesRegex(RuntimeError, "still broken"):
            fetch_with_retry(always_fail, retries=3, delay=0.01, sleep=sleeps.append)

        self.assertEqual(sleeps, [0.01, 0.02])


if __name__ == "__main__":
    unittest.main()
