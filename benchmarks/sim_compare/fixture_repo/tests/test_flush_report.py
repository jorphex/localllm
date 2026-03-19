import unittest

from worker.flush_report import summarize_flush_report
from worker.reporting import build_bucket_counts


class FlushReportTests(unittest.TestCase):
    def test_flush_report_keeps_ids_and_counts_aligned(self):
        records = [
            {"id": "a", "ready": True},
            {"id": "b", "ready": False},
            {"id": "c", "ready": True},
        ]

        result = summarize_flush_report(records)

        self.assertEqual(result["ids"]["ready"], ["a", "c"])
        self.assertEqual(result["ids"]["pending"], ["b"])
        self.assertEqual(result["counts"], {"ready": 2, "pending": 1})

    def test_bucket_counts_still_work_directly(self):
        records = [
            {"id": "a", "ready": True},
            {"id": "b", "ready": False},
            {"id": "c", "ready": False},
        ]

        self.assertEqual(build_bucket_counts(records), {"ready": 1, "pending": 2})


if __name__ == "__main__":
    unittest.main()
