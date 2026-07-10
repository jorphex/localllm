import unittest

from worker.reporting import summarize_counts
from worker.session_store import summarize_flush


class SessionStoreTests(unittest.TestCase):
    def test_flush_groups_ready_items_separately(self):
        records = [
            {"id": "a", "ready": True},
            {"id": "b", "ready": False},
            {"id": "c", "ready": True},
        ]

        result = summarize_flush(records)

        self.assertEqual(result["ready"], ["a", "c"])
        self.assertEqual(result["pending"], ["b"])

    def test_reporting_counts_are_still_correct(self):
        records = [
            {"id": "a", "ready": True},
            {"id": "b", "ready": False},
            {"id": "c", "ready": False},
        ]

        self.assertEqual(summarize_counts(records), {"ready": 1, "pending": 2})


if __name__ == "__main__":
    unittest.main()
